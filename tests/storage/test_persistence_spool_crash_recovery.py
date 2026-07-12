from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID

import pytest

from cryodaq.storage.persistence_spool import (
    NormalizedBatchEnvelope,
    NormalizedSpoolRow,
    PersistenceOutcome,
    PersistenceSpool,
    create_materialization_receipt_channel,
)

_FRESH_CREATED_AT = datetime.now(UTC)


def _uuid(number: int) -> str:
    return str(UUID(int=number))


def _envelope(created_at: float | None = None) -> NormalizedBatchEnvelope:
    row = NormalizedSpoolRow.create(
        ingest_uuid=_uuid(1),
        timestamp=datetime(2026, 7, 11, 3, 4, 5, tzinfo=UTC),
        instrument_id="ls218",
        channel="CH1",
        value=4.2,
        unit="K",
        status="ok",
    )
    return NormalizedBatchEnvelope.create(
        (row,),
        batch_uuid=_uuid(2),
        created_at=(_FRESH_CREATED_AT if created_at is None else datetime.fromtimestamp(created_at, tz=UTC)),
    )


def _append_then_crash(path: str, created_at: float) -> None:
    spool = PersistenceSpool(Path(path))
    outcome = spool.append(_envelope(created_at))
    if outcome is not PersistenceOutcome.DURABLY_QUEUED:
        os._exit(91)
    os._exit(0)


def _ack_then_crash_before_checkpoint(path: str, created_at: float) -> None:
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(Path(path), receipt_verifier=verifier)
    spool._checkpoint_reuse = lambda _conn: os._exit(0)
    spool.acknowledge(issuer.issue(_envelope(created_at)))
    os._exit(92)


def test_committed_envelope_survives_abrupt_process_exit_and_reopens_once(tmp_path) -> None:
    path = tmp_path / "spool.db"
    envelope = _envelope()
    process = get_context("spawn").Process(
        target=_append_then_crash,
        args=(str(path), envelope.created_at),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0

    spool = PersistenceSpool(path)
    assert spool.pending_batches() == (envelope,)
    assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
    assert spool.health().pending_batches == 1
    spool.close()


def test_committed_ack_survives_crash_before_checkpoint_without_tombstone(tmp_path) -> None:
    path = tmp_path / "spool.db"
    envelope = _envelope()
    spool = PersistenceSpool(path)
    assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
    spool.close()

    process = get_context("spawn").Process(
        target=_ack_then_crash_before_checkpoint,
        args=(str(path), envelope.created_at),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0

    reopened = PersistenceSpool(path)
    assert reopened.pending_batches() == ()
    assert reopened._connection().execute("SELECT COUNT(*) FROM spool_rows").fetchone() == (0,)
    reopened.close()


async def test_cancelled_async_append_finishes_as_one_recoverable_transaction(tmp_path) -> None:
    path = tmp_path / "spool.db"
    spool = PersistenceSpool(path)
    entered = threading.Event()
    release = threading.Event()

    def block_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)

    spool._before_commit_hook = block_before_commit
    task = asyncio.create_task(spool.append_durable(_envelope()))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert spool.health().pending_batches == 1
    spool._before_commit_hook = None
    spool.close()

    reopened = PersistenceSpool(path)
    assert reopened.pending_batches() == (_envelope(),)
    reopened.close()


async def test_cancelled_async_ack_finishes_delete_and_checkpoint(tmp_path) -> None:
    path = tmp_path / "spool.db"
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(path, receipt_verifier=verifier)
    spool.append(_envelope())
    entered = threading.Event()
    release = threading.Event()

    def block_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)

    spool._before_commit_hook = block_before_commit
    task = asyncio.create_task(spool.acknowledge_durable(issuer.issue(_envelope())))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert spool.health().pending_batches == 0
    spool._before_commit_hook = None
    spool.close()

    reopened = PersistenceSpool(path)
    assert reopened.pending_batches() == ()
    reopened.close()


@pytest.mark.parametrize("operation", ["append", "acknowledge"])
async def test_worker_failure_dominates_cancellation_and_is_retrieved(tmp_path, operation: str) -> None:
    path = tmp_path / f"{operation}.db"
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(path, receipt_verifier=verifier)
    if operation == "acknowledge":
        spool.append(_envelope())
    entered = threading.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))

    def fail_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)
        raise RuntimeError(f"{operation} worker failed")

    spool._before_commit_hook = fail_before_commit
    if operation == "append":
        task = asyncio.create_task(spool.append_durable(_envelope()))
    else:
        task = asyncio.create_task(spool.acknowledge_durable(issuer.issue(_envelope())))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(RuntimeError, match=f"{operation} worker failed"):
            await task
        await asyncio.sleep(0)
        assert loop_errors == []
        expected_pending = 0 if operation == "append" else 1
        assert spool.health().pending_batches == expected_pending
    finally:
        loop.set_exception_handler(previous_handler)
        spool._before_commit_hook = None
        spool.close()


async def test_async_close_waits_off_loop_for_cancelled_durable_operation(tmp_path) -> None:
    spool = PersistenceSpool(tmp_path / "close-race.db")
    entered = threading.Event()
    release = threading.Event()

    def block_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)

    spool._before_commit_hook = block_before_commit
    operation = asyncio.create_task(spool.append_durable(_envelope()))
    assert await asyncio.to_thread(entered.wait, 5)
    operation.cancel()
    await asyncio.sleep(0)
    close_task = asyncio.create_task(spool.close_durable())
    event_loop_progress = asyncio.Event()
    asyncio.get_running_loop().call_soon(event_loop_progress.set)
    await asyncio.wait_for(event_loop_progress.wait(), timeout=1)
    assert not operation.done()
    assert not close_task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    await asyncio.wait_for(close_task, timeout=1)
    with pytest.raises(RuntimeError, match="closed"):
        spool.health()


async def test_repeatedly_cancelled_close_settles_after_append_then_propagates(tmp_path) -> None:
    spool = PersistenceSpool(tmp_path / "cancel-close-append.db")
    entered = threading.Event()
    release = threading.Event()

    def block_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)

    spool._before_commit_hook = block_before_commit
    append_task = asyncio.create_task(spool.append_durable(_envelope()))
    assert await asyncio.to_thread(entered.wait, 5)
    close_task = asyncio.create_task(spool.close_durable())
    await asyncio.sleep(0)
    close_task.cancel()
    await asyncio.sleep(0)
    assert not close_task.done()
    close_task.cancel()
    await asyncio.sleep(0)
    assert not close_task.done()

    release.set()
    assert await append_task is PersistenceOutcome.DURABLY_QUEUED
    with pytest.raises(asyncio.CancelledError):
        await close_task
    with pytest.raises(RuntimeError, match="closed"):
        spool.health()


async def test_close_worker_failure_dominates_cancellation_without_loop_exception(tmp_path) -> None:
    spool = PersistenceSpool(tmp_path / "close-failure.db")
    original_close = spool.close
    entered = threading.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))

    def fail_close() -> None:
        entered.set()
        assert release.wait(timeout=5)
        raise RuntimeError("close worker failed")

    spool.close = fail_close  # type: ignore[method-assign]
    close_task = asyncio.create_task(spool.close_durable())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        close_task.cancel()
        await asyncio.sleep(0)
        assert not close_task.done()
        release.set()
        with pytest.raises(RuntimeError, match="close worker failed"):
            await close_task
        await asyncio.sleep(0)
        assert loop_errors == []
    finally:
        loop.set_exception_handler(previous_handler)
        spool.close = original_close  # type: ignore[method-assign]
        spool.close()


async def test_cancelled_close_settles_after_acknowledgement_race(tmp_path) -> None:
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(tmp_path / "cancel-close-ack.db", receipt_verifier=verifier)
    spool.append(_envelope())
    entered = threading.Event()
    release = threading.Event()

    def block_before_commit() -> None:
        entered.set()
        assert release.wait(timeout=5)

    spool._before_commit_hook = block_before_commit
    acknowledge_task = asyncio.create_task(spool.acknowledge_durable(issuer.issue(_envelope())))
    assert await asyncio.to_thread(entered.wait, 5)
    close_task = asyncio.create_task(spool.close_durable())
    await asyncio.sleep(0)
    close_task.cancel()
    await asyncio.sleep(0)
    assert not close_task.done()

    release.set()
    await acknowledge_task
    with pytest.raises(asyncio.CancelledError):
        await close_task
    with pytest.raises(RuntimeError, match="closed"):
        spool.health()
