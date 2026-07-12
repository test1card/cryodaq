from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from queue import Empty
from typing import Any

import pytest

import cryodaq.storage.operator_snapshot_revision as revision_module
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.operator_snapshot_revision import (
    OperatorSnapshotRevisionAllocator,
    OperatorSnapshotRevisionBusyError,
    OperatorSnapshotRevisionCorruptError,
    OperatorSnapshotRevisionError,
    OperatorSnapshotRevisionExhaustedError,
    SnapshotRevision,
)


def _allocate_many(root: str, count: int, output: Any) -> None:
    allocator = OperatorSnapshotRevisionAllocator(Path(root))
    try:
        allocations = (allocator.allocate() for _ in range(count))
        output.put([(item.revision, item.received_at.isoformat()) for item in allocations])
    except BaseException as exc:
        output.put((type(exc).__name__, str(exc)))


def test_fixed_state_path_restart_and_wall_rollback_are_monotonic(tmp_path: Path) -> None:
    times = iter(
        (
            datetime(2026, 7, 12, 3, 0, tzinfo=UTC),
            datetime(2026, 7, 11, 3, 0, tzinfo=UTC),
        )
    )
    allocator = OperatorSnapshotRevisionAllocator(tmp_path, clock=lambda: next(times))

    first = allocator.allocate()
    second = allocator.allocate()
    assert first == SnapshotRevision(1, datetime(2026, 7, 12, 3, 0, tzinfo=UTC))
    assert second.revision == 2
    assert second.received_at == first.received_at
    assert allocator.path == tmp_path / "state" / "operator_snapshot_revision.db"

    restarted = OperatorSnapshotRevisionAllocator(
        tmp_path,
        clock=lambda: datetime(2000, 1, 1, tzinfo=UTC),
    ).allocate()
    assert restarted.revision == 3
    assert restarted.received_at == first.received_at


def test_multiprocess_contention_allocates_one_gap_free_global_sequence(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    processes = [context.Process(target=_allocate_many, args=(str(tmp_path), 20, output)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    allocations: list[tuple[int, str]] = []
    for _ in processes:
        try:
            result = output.get(timeout=5)
        except Empty:
            pytest.fail("allocator worker returned no result")
        assert isinstance(result, list), result
        allocations.extend(result)
    output.close()
    output.join_thread()

    revisions = sorted(revision for revision, _received_at in allocations)
    assert revisions == list(range(1, 81))
    ordered_times = [
        datetime.fromisoformat(received_at) for _revision, received_at in sorted(allocations, key=lambda item: item[0])
    ]
    assert ordered_times == sorted(ordered_times)
    assert OperatorSnapshotRevisionAllocator(tmp_path).allocate().revision == 81


def test_busy_timeout_fails_closed_without_consuming_revision(tmp_path: Path) -> None:
    allocator = OperatorSnapshotRevisionAllocator(tmp_path, busy_timeout_ms=20)
    assert allocator.allocate().revision == 1
    conn = sqlite3.connect(str(allocator.path), isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(OperatorSnapshotRevisionBusyError, match="busy"):
            allocator.allocate()
    finally:
        conn.rollback()
        conn.close()
    assert allocator.allocate().revision == 2


@pytest.mark.parametrize(
    "mutation",
    (
        "PRAGMA application_id=7",
        "PRAGMA user_version=99",
        "CREATE TABLE intruder(value INTEGER)",
        "UPDATE snapshot_revision SET revision='not-an-int'",
        "DELETE FROM snapshot_revision",
    ),
)
def test_identity_schema_and_singleton_corruption_fail_closed(tmp_path: Path, mutation: str) -> None:
    allocator = OperatorSnapshotRevisionAllocator(tmp_path)
    allocator.allocate()
    conn = sqlite3.connect(str(allocator.path))
    if "not-an-int" in mutation:
        conn.execute("PRAGMA ignore_check_constraints=ON")
    conn.execute(mutation)
    conn.commit()
    conn.close()

    with pytest.raises(OperatorSnapshotRevisionCorruptError):
        allocator.allocate()


def test_file_corruption_and_access_failure_are_normalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allocator = OperatorSnapshotRevisionAllocator(tmp_path)
    allocator.path.parent.mkdir(parents=True)
    allocator.path.write_bytes(b"not sqlite")
    with pytest.raises(OperatorSnapshotRevisionCorruptError):
        allocator.allocate()

    other = OperatorSnapshotRevisionAllocator(tmp_path / "other")

    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("private filesystem detail")

    monkeypatch.setattr(revision_module.sqlite3, "connect", denied)
    with pytest.raises(OperatorSnapshotRevisionCorruptError, match="integrity or access") as captured:
        other.allocate()
    assert "private filesystem detail" not in str(captured.value)


def test_symlink_and_non_regular_database_topology_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(OperatorSnapshotRevisionError, match="root must not be a symlink"):
        OperatorSnapshotRevisionAllocator(linked_root).allocate()

    allocator = OperatorSnapshotRevisionAllocator(tmp_path / "regular-root")
    allocator.path.mkdir(parents=True)
    with pytest.raises(OperatorSnapshotRevisionError, match="regular file"):
        allocator.allocate()


def test_signed_63_bit_exhaustion_is_durable_and_fail_closed(tmp_path: Path) -> None:
    allocator = OperatorSnapshotRevisionAllocator(tmp_path)
    allocator.allocate()
    conn = sqlite3.connect(str(allocator.path))
    conn.execute("UPDATE snapshot_revision SET revision=?", ((1 << 63) - 1,))
    conn.commit()
    conn.close()

    with pytest.raises(OperatorSnapshotRevisionExhaustedError, match="exhausted"):
        allocator.allocate()
    conn = sqlite3.connect(str(allocator.path))
    assert conn.execute("SELECT revision FROM snapshot_revision").fetchone() == ((1 << 63) - 1,)
    conn.close()


class _BlockingAllocator(OperatorSnapshotRevisionAllocator):
    def __init__(self, root: Path, *, block_after_commit: bool, fail: bool = False) -> None:
        super().__init__(root)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_after_commit = block_after_commit
        self.fail = fail

    def allocate(self, *, not_before: datetime | None = None) -> SnapshotRevision:
        if not self.block_after_commit:
            self.entered.set()
            assert self.release.wait(5)
        result = super().allocate(not_before=not_before)
        if self.block_after_commit:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail:
            raise OperatorSnapshotRevisionError("worker failure")
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("block_after_commit", (False, True))
async def test_async_cancellation_settles_commit_and_never_reuses_revision(
    tmp_path: Path,
    block_after_commit: bool,
) -> None:
    allocator = _BlockingAllocator(tmp_path, block_after_commit=block_after_commit)
    task = asyncio.create_task(allocator.allocate_async())
    assert await asyncio.to_thread(allocator.entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()  # repeated cancellation must still settle the same worker
    allocator.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert OperatorSnapshotRevisionAllocator(tmp_path).allocate().revision == 2


@pytest.mark.asyncio
async def test_worker_failure_after_cancellation_dominates_cancellation(tmp_path: Path) -> None:
    allocator = _BlockingAllocator(tmp_path, block_after_commit=True, fail=True)
    task = asyncio.create_task(allocator.allocate_async())
    assert await asyncio.to_thread(allocator.entered.wait, 5)
    task.cancel()
    allocator.release.set()
    with pytest.raises(OperatorSnapshotRevisionError, match="worker failure"):
        await task
    assert OperatorSnapshotRevisionAllocator(tmp_path).allocate().revision == 2


@pytest.mark.asyncio
async def test_async_allocation_runs_blocking_core_off_event_loop(tmp_path: Path) -> None:
    event_loop_thread = threading.get_ident()
    observed_threads: list[int] = []

    class RecordingAllocator(OperatorSnapshotRevisionAllocator):
        def allocate(self, *, not_before: datetime | None = None) -> SnapshotRevision:
            observed_threads.append(threading.get_ident())
            return super().allocate(not_before=not_before)

    result = await RecordingAllocator(tmp_path).allocate_async()
    assert result.revision == 1
    assert observed_threads and observed_threads[0] != event_loop_thread


def test_public_contract_has_no_control_or_publication_authority(tmp_path: Path) -> None:
    allocator = OperatorSnapshotRevisionAllocator(tmp_path)
    public_names = {name for name in dir(allocator) if not name.startswith("_")}
    assert public_names == {"allocate", "allocate_async", "path"}
    module_text = Path(revision_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("cryodaq.engine", "cryodaq.gui", "cryodaq.replay", "zmq", "driver"):
        assert forbidden not in module_text


def test_constructor_and_clock_inputs_are_strict(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="pathlib.Path"):
        OperatorSnapshotRevisionAllocator(str(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        OperatorSnapshotRevisionAllocator(tmp_path, busy_timeout_ms=0)
    with pytest.raises(TypeError, match="clock"):
        OperatorSnapshotRevisionAllocator(tmp_path, clock=None)  # type: ignore[arg-type]
    with pytest.raises(OperatorSnapshotRevisionError, match="timezone-aware"):
        OperatorSnapshotRevisionAllocator(tmp_path, clock=lambda: datetime(2026, 1, 1)).allocate()


def test_clock_with_non_null_tzinfo_but_none_offset_fails_without_consuming_revision(tmp_path: Path) -> None:
    class IndeterminateTimezone(tzinfo):
        def utcoffset(self, _value: datetime | None) -> None:
            return None

        def dst(self, _value: datetime | None) -> None:
            return None

    ambiguous = datetime(2026, 7, 12, 4, 0, tzinfo=IndeterminateTimezone())
    with pytest.raises(OperatorSnapshotRevisionError, match="timezone-aware"):
        OperatorSnapshotRevisionAllocator(tmp_path, clock=lambda: ambiguous).allocate()

    # The rejected clock value rolled back the transaction, including any
    # first-open schema initialization, and consumed no ordering token.
    assert OperatorSnapshotRevisionAllocator(tmp_path).allocate().revision == 1


def test_atomic_not_before_floor_survives_clock_rollback_and_restart(tmp_path: Path) -> None:
    floor = datetime(2026, 7, 12, 4, 0, tzinfo=UTC)
    allocator = OperatorSnapshotRevisionAllocator(
        tmp_path,
        clock=lambda: datetime(2000, 1, 1, tzinfo=UTC),
    )

    first = allocator.allocate(not_before=floor)
    second_floor = floor + timedelta(microseconds=1)
    second = OperatorSnapshotRevisionAllocator(
        tmp_path,
        clock=lambda: datetime(1990, 1, 1, tzinfo=UTC),
    ).allocate(not_before=second_floor)

    assert first.received_at == floor
    assert first.received_at is not floor
    assert second.revision == 2
    assert second.received_at == second_floor
    assert second.received_at >= first.received_at


def test_revision_timestamp_is_exact_detached_and_subclasses_fail_before_allocation(tmp_path: Path) -> None:
    received_at = datetime(2026, 7, 12, 4, 0, tzinfo=UTC)
    revision = SnapshotRevision(1, received_at)
    assert type(revision.received_at) is datetime
    assert revision.received_at is not received_at

    class DatetimeSubclass(datetime):
        pass

    hostile = DatetimeSubclass(2026, 7, 12, 4, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="exact timezone-aware"):
        SnapshotRevision(1, hostile)
    with pytest.raises(OperatorSnapshotRevisionError, match="not_before.*exact"):
        OperatorSnapshotRevisionAllocator(tmp_path).allocate(not_before=hostile)
    assert OperatorSnapshotRevisionAllocator(tmp_path).allocate().revision == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod semantics only")
def test_read_only_state_directory_fails_closed_for_unprivileged_process(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    root = tmp_path / "root"
    state = root / "state"
    state.mkdir(parents=True)
    state.chmod(0o500)
    try:
        with pytest.raises(OperatorSnapshotRevisionError):
            OperatorSnapshotRevisionAllocator(root).allocate()
    finally:
        state.chmod(0o700)
