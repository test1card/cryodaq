from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from pathlib import Path

import pytest

from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.report_state import (
    experiment_lock_name,
    load_report_state,
    new_pending_state,
    new_running_state,
    terminal_state,
    write_report_state,
)


def _terminal_experiment(
    data_dir: Path,
    experiment_id: str,
    *,
    ended_at: str,
    report_enabled: bool = True,
    retroactive: bool = False,
) -> Path:
    root = data_dir / "experiments" / experiment_id
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": experiment_id,
                    "status": "COMPLETED",
                    "report_enabled": report_enabled,
                    "retroactive": retroactive,
                    "end_time": ended_at,
                },
                "template": {"report_enabled": report_enabled},
            }
        ),
        encoding="utf-8",
    )
    return root


async def test_lexical_cursor_is_persistent_bounded_and_eventually_covers_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    for index in range(5):
        _terminal_experiment(
            tmp_path,
            f"exp-{index}",
            ended_at=f"2026-07-0{index + 1}T00:00:00+00:00",
        )
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(batch_size=2),
        event_addr=None,
    )
    seen: list[str] = []

    async def record(root: Path) -> None:
        seen.append(root.name)

    monkeypatch.setattr(coordinator, "_reconcile_experiment", record)
    await coordinator.reconcile_once()
    await coordinator.stop()

    restarted = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(batch_size=2),
        event_addr=None,
    )
    monkeypatch.setattr(restarted, "_reconcile_experiment", record)
    await restarted.reconcile_once()
    await restarted.reconcile_once()
    await restarted.stop()

    assert seen == ["exp-0", "exp-1", "exp-2", "exp-3", "exp-4"]
    cursor = json.loads(
        (tmp_path / "reporting" / "reconcile_cursor.json").read_text(encoding="utf-8")
    )
    assert cursor["last_experiment_id"] is None


def test_retroactive_experiment_is_not_automatic_work(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    _terminal_experiment(
        tmp_path,
        "exp-retroactive",
        ended_at="2026-07-09T00:00:00+00:00",
        retroactive=True,
    )
    coordinator = ReportCoordinator(tmp_path, event_addr=None)

    assert coordinator._next_batch() == []


async def test_startup_and_timer_reconcile_without_terminal_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(scan_interval_s=5),
        event_addr=None,
    )
    passes = 0
    first = asyncio.Event()
    enough = asyncio.Event()

    async def record_pass() -> None:
        nonlocal passes
        passes += 1
        first.set()
        if passes >= 2:
            enough.set()

    monkeypatch.setattr(coordinator, "reconcile_once", record_pass)
    await coordinator.start()
    try:
        await asyncio.wait_for(first.wait(), timeout=1)
        coordinator.notify_terminal()
        await asyncio.wait_for(enough.wait(), timeout=1)
    finally:
        await coordinator.stop()

    assert passes >= 2


async def test_terminal_event_wakes_without_starving_existing_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(scan_interval_s=60),
        event_addr=None,
    )
    calls = 0
    first = asyncio.Event()
    second = asyncio.Event()

    async def record_pass() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
        if calls == 2:
            second.set()

    monkeypatch.setattr(coordinator, "reconcile_once", record_pass)
    await coordinator.start()
    try:
        await asyncio.wait_for(first.wait(), timeout=1)
        coordinator.notify_terminal()
        await asyncio.wait_for(second.wait(), timeout=1)
    finally:
        await coordinator.stop()

    assert calls >= 2


def test_event_priority_preserves_cursor_progress_for_older_archive(
    tmp_path: Path,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    for index in range(4):
        _terminal_experiment(
            tmp_path,
            f"exp-{index}",
            ended_at=f"2026-07-0{index + 1}T00:00:00+00:00",
        )
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(batch_size=2),
        event_addr=None,
    )
    coordinator._write_cursor("exp-1")

    coordinator.notify_terminal("exp-3")
    first = [root.name for root in coordinator._next_batch()]
    coordinator.notify_terminal("exp-3")
    second = [root.name for root in coordinator._next_batch()]
    third = [root.name for root in coordinator._next_batch()]

    assert first == ["exp-3", "exp-2"]
    assert second == ["exp-3"]
    assert third == ["exp-0", "exp-1"]


async def test_matching_current_fingerprint_skips_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-current",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "1" * 64
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(
        module,
        "load_current_manifest",
        lambda _root: {
            "source_fingerprint": fingerprint,
            "generation_id": "generation-token-0001",
        },
    )

    class FailRunner:
        def generate_experiment(self, _experiment_id: str, *, automatic: bool = False) -> None:
            assert automatic is True
            pytest.fail("matching current manifest must not launch a child")

    coordinator = module.ReportCoordinator(tmp_path, runner=FailRunner(), event_addr=None)
    await coordinator._reconcile_experiment(root)
    state = load_report_state(root)
    assert state is not None
    assert state["status"] == "SUCCEEDED"
    assert state["source_fingerprint"] == fingerprint


async def test_manifest_success_repair_revalidates_source_under_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-manual-race",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    first = "sha256:" + "1" * 64
    changed = "sha256:" + "2" * 64
    fingerprints = iter([first, changed])
    manifest = {
        "source_fingerprint": first,
        "generation_id": "generation-token-0001",
    }
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: next(fingerprints))
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: manifest)

    class NoRender:
        def generate_experiment(self, *_args, **_kwargs) -> None:
            pytest.fail("matching lockless manifest should enter repair lane")

    coordinator = module.ReportCoordinator(tmp_path, runner=NoRender(), event_addr=None)
    await coordinator._reconcile_experiment(root)

    assert load_report_state(root) is None


async def test_manifest_invalidated_during_locked_repair_enters_fresh_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-manifest-invalidated",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "3" * 64
    manifest = {
        "source_fingerprint": fingerprint,
        "generation_id": "generation-token-0001",
    }
    reads = iter([manifest, module.ReportContractError("manifest became invalid"), None])

    def load_manifest(_root):
        value = next(reads)
        if isinstance(value, BaseException):
            raise value
        return value

    rendered: list[str] = []

    class Runner:
        def generate_experiment(self, experiment_id: str, *, automatic: bool = False) -> None:
            assert automatic is True
            rendered.append(experiment_id)

    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(module, "load_current_manifest", load_manifest)
    coordinator = module.ReportCoordinator(tmp_path, runner=Runner(), event_addr=None)

    await coordinator._reconcile_experiment(root)
    assert load_report_state(root) is None
    await coordinator._reconcile_experiment(root)

    assert rendered == [root.name]
    state = load_report_state(root)
    assert state is not None and state["status"] == "PENDING"


async def test_changed_fingerprint_starts_new_attempt_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-changed",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "2" * 64
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(
        module,
        "load_current_manifest",
        lambda _root: {"source_fingerprint": "sha256:" + "1" * 64},
    )
    started = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        def generate_experiment(
            self,
            experiment_id: str,
            *,
            automatic: bool = False,
        ) -> dict[str, object]:
            assert experiment_id == "exp-changed"
            assert automatic is True
            started.set()
            release.wait(timeout=2)
            return {}

    coordinator = module.ReportCoordinator(
        tmp_path,
        runner=BlockingRunner(),
        event_addr=None,
    )
    task = asyncio.create_task(coordinator._reconcile_experiment(root))
    assert await asyncio.to_thread(started.wait, 1)
    responsive = False
    await asyncio.sleep(0)
    responsive = True
    release.set()
    await task

    assert responsive is True


async def test_pending_helper_revalidates_fingerprint_under_kernel_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-mutated-before-lock",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprints = iter(["sha256:" + "1" * 64, "sha256:" + "2" * 64])
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: next(fingerprints))
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)

    class NoRender:
        def generate_experiment(self, *_args, **_kwargs) -> None:
            pytest.fail("stale pre-lock fingerprint must not create work")

    coordinator = module.ReportCoordinator(tmp_path, runner=NoRender(), event_addr=None)
    await coordinator._reconcile_experiment(root)

    assert load_report_state(root) is None


def test_transient_metadata_oserror_does_not_create_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-transient",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    monkeypatch.setattr(
        module,
        "automatic_report_eligible",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("temporary I/O fault")),
    )
    coordinator = module.ReportCoordinator(tmp_path, event_addr=None)

    assert coordinator._eligible_root(root.name, None) is None
    assert load_report_state(root) is None


def test_real_metadata_read_oserror_is_retryable_without_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    root = _terminal_experiment(
        tmp_path,
        "exp-real-io",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    original = Path.read_text

    def fail_metadata(path: Path, *args, **kwargs):
        if path == root / "metadata.json":
            raise OSError("simulated EIO")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_metadata)
    coordinator = ReportCoordinator(tmp_path, event_addr=None)

    assert coordinator._eligible_root(root.name, None) is None
    assert not (root / "report_state.json").exists()


async def test_automatic_child_skips_unchanged_and_regenerates_changed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator
    from cryodaq.report_process import ReportProcessError, read_result_file, result_file_path
    from cryodaq.report_state import load_current_manifest
    from cryodaq.reporting import __main__ as child
    from cryodaq.reporting.generator import ReportGenerator

    root = _terminal_experiment(
        tmp_path,
        "exp-regenerate",
        ended_at="2026-07-09T00:00:00+00:00",
    )

    def fake_generate(
        _self,
        _experiment_id: str,
        output_dir: Path,
        *,
        deadline_epoch: float,
    ) -> SimpleNamespace:
        del deadline_epoch
        (output_dir / "assets").mkdir(parents=True)
        (output_dir / "report_editable.docx").write_bytes(b"docx")
        return SimpleNamespace(sections=("title_page",), skipped=False, reason="")

    monkeypatch.setattr(ReportGenerator, "generate_to_directory", fake_generate)

    class InProcessRunner:
        calls = 0

        def generate_experiment(
            self,
            experiment_id: str,
            *,
            automatic: bool = False,
        ) -> dict[str, object]:
            assert automatic is True
            self.calls += 1
            generation_id = f"generation-token-{self.calls:04d}"
            result_path = result_file_path(tmp_path, generation_id)
            args = argparse.Namespace(
                experiment_id=experiment_id,
                generation_id=generation_id,
                deadline_epoch=time.time() + 30,
            )
            rc = child._run_experiment(args, tmp_path, result_path)
            if rc != 0:
                raise ReportProcessError(f"child exited {rc}")
            try:
                return read_result_file(result_path)["report"]
            finally:
                result_path.unlink(missing_ok=True)

    runner = InProcessRunner()
    coordinator = ReportCoordinator(tmp_path, runner=runner, event_addr=None)
    await coordinator._reconcile_experiment(root)
    first = load_current_manifest(root)
    assert first is not None
    await coordinator._reconcile_experiment(root)
    assert runner.calls == 1

    payload = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    payload["experiment"]["notes"] = "source changed"
    (root / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    await coordinator._reconcile_experiment(root)

    second = load_current_manifest(root)
    assert second is not None
    assert runner.calls == 2
    assert second["generation_id"] != first["generation_id"]
    state = load_report_state(root)
    assert state is not None
    assert state["attempt_count"] == 1
    assert state["source_fingerprint"] == second["source_fingerprint"]


def test_retry_backoff_stops_at_poison_attempt(
    tmp_path: Path,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    root = _terminal_experiment(
        tmp_path,
        "exp-poison",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "3" * 64
    running = new_running_state(
        "exp-poison",
        fingerprint,
        "generation-token-0001",
        "owner-token-000000001",
        attempt_count=3,
        max_attempts=3,
    )
    failed = terminal_state(
        running,
        owner_token="owner-token-000000001",
        succeeded=False,
        error_code="render_failed",
        error_text="boom",
    )
    write_report_state(root, failed)
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(max_attempts=3, base_backoff_s=10),
        event_addr=None,
    )

    assert coordinator._needs_render(root, fingerprint, now=time.time() + 10_000) is False


def test_failed_attempt_gets_bounded_exponential_backoff(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    root = _terminal_experiment(
        tmp_path,
        "exp-backoff",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "7" * 64
    running = new_running_state(
        "exp-backoff",
        fingerprint,
        "generation-token-0001",
        "owner-token-000000001",
        attempt_count=2,
        max_attempts=5,
    )
    failed = terminal_state(
        running,
        owner_token="owner-token-000000001",
        succeeded=False,
        error_code="render_failed",
        error_text="boom",
    )
    write_report_state(root, failed)
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(
            base_backoff_s=10,
            max_backoff_s=15,
            jitter_fraction=0,
        ),
        event_addr=None,
    )
    before = time.time()

    coordinator._record_failure_backoff(root, fingerprint, "boom")

    updated = load_report_state(root)
    assert updated is not None
    assert before + 14.9 <= updated["not_before"] <= time.time() + 15.1


async def test_free_lock_running_recovery_persists_failed_attempt_and_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-crashed-child",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "c" * 64
    running = new_running_state(
        root.name,
        fingerprint,
        "generation-token-0001",
        "owner-token-000000001",
        attempt_count=1,
        max_attempts=3,
    )
    write_report_state(root, running)
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)

    class CrashedChildRecovery:
        def generate_experiment(self, _experiment_id: str, *, automatic: bool = False) -> None:
            assert automatic is True
            current = load_report_state(root)
            assert current is not None and current["status"] == "RUNNING"
            failed = terminal_state(
                current,
                owner_token=current["owner_token"],
                succeeded=False,
                error_code="stale_running",
                error_text="kernel lock is free",
            )
            write_report_state(
                root,
                failed,
                expected_owner_token=current["owner_token"],
                expected_generation_id=current["generation_id"],
                expected_status="RUNNING",
            )
            raise module.ReportProcessError("stale_running: kernel lock is free")

    coordinator = module.ReportCoordinator(
        tmp_path,
        config=module.ReportCoordinatorConfig(
            max_attempts=3,
            base_backoff_s=10,
            jitter_fraction=0,
        ),
        runner=CrashedChildRecovery(),
        event_addr=None,
    )
    before = time.time()

    await coordinator._reconcile_experiment(root)

    recovered = load_report_state(root)
    assert recovered is not None
    assert recovered["status"] == "FAILED"
    assert recovered["attempt_count"] == 1
    assert recovered["error_code"] == "stale_running"
    assert before + 9.9 <= recovered["not_before"] <= time.time() + 10.1


async def test_failed_new_generation_keeps_previous_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-old-current",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    reports = root / "reports"
    reports.mkdir()
    current_path = reports / "current_report.json"
    original = '{"generation_id":"old-generation"}\n'
    current_path.write_text(original, encoding="utf-8")
    fingerprint = "sha256:" + "8" * 64
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(
        module,
        "load_current_manifest",
        lambda _root: {"source_fingerprint": "sha256:" + "0" * 64},
    )

    class FailingRunner:
        def generate_experiment(self, _experiment_id: str, *, automatic: bool = False) -> None:
            assert automatic is True
            raise module.ReportProcessError("render failed")

    coordinator = module.ReportCoordinator(
        tmp_path,
        runner=FailingRunner(),
        event_addr=None,
        random_fn=lambda: 0.5,
    )
    await coordinator._reconcile_experiment(root)

    assert current_path.read_text(encoding="utf-8") == original


def test_running_state_is_immediately_advisory_when_kernel_lock_may_be_free(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    root = _terminal_experiment(
        tmp_path,
        "exp-running",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "4" * 64
    running = new_running_state(
        "exp-running",
        fingerprint,
        "generation-token-0001",
        "owner-token-000000001",
        attempt_count=1,
    )
    write_report_state(root, running)
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(),
        event_addr=None,
    )

    assert coordinator._needs_render(root, fingerprint, now=running["started_at"] + 30) is True
    assert coordinator._needs_render(root, fingerprint, now=running["started_at"] + 61) is True


async def test_two_coordinators_and_manual_race_use_one_experiment_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-race",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = "sha256:" + "5" * 64
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)
    generated = 0
    guard = threading.Lock()

    class LockingRunner:
        def generate_experiment(
            self,
            experiment_id: str,
            *,
            automatic: bool = False,
        ) -> dict[str, object]:
            nonlocal generated
            lock_name = experiment_lock_name(experiment_id)
            fd = try_acquire_lock(lock_name, lock_dir=tmp_path)
            if fd is None:
                return {}
            try:
                with guard:
                    generated += 1
                time.sleep(0.1)
                return {}
            finally:
                release_lock(fd, lock_name, unlink=False, lock_dir=tmp_path)

    runner = LockingRunner()
    first = module.ReportCoordinator(tmp_path, runner=runner, event_addr=None)
    second = module.ReportCoordinator(tmp_path, runner=runner, event_addr=None)
    await asyncio.gather(
        first._reconcile_experiment(root),
        second._reconcile_experiment(root),
        asyncio.to_thread(runner.generate_experiment, "exp-race", automatic=False),
    )

    assert generated == 1


def test_new_pending_state_preserves_configured_attempt_budget() -> None:
    pending = new_pending_state(
        "exp-pending",
        "sha256:" + "6" * 64,
        "generation-token-0001",
        "owner-token-000000001",
        max_attempts=7,
    )
    assert pending["status"] == "PENDING"
    assert pending["attempt_count"] == 0
    assert pending["max_attempts"] == 7


async def test_disabled_coordinator_does_not_start_background_work(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(automatic_enabled=False),
        event_addr=None,
    )
    await coordinator.start()
    assert coordinator._task is None


async def test_active_terminal_metadata_is_not_fingerprinted_until_active_state_clears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    experiment_id = "exp-finalize"
    _terminal_experiment(
        tmp_path,
        experiment_id,
        ended_at="2026-07-09T00:00:00+00:00",
    )
    state_path = tmp_path / "experiment_state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_mode": "experiment",
                "active_experiment_id": experiment_id,
                "updated_at": "2026-07-09T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    fingerprints: list[str] = []
    renders: list[str] = []

    def fingerprint(root: Path) -> str:
        fingerprints.append(root.name)
        return "sha256:" + "a" * 64

    class Runner:
        def generate_experiment(self, experiment: str, *, automatic: bool = False) -> dict:
            assert automatic is True
            renders.append(experiment)
            return {}

    monkeypatch.setattr(module, "compute_source_fingerprint", fingerprint)
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)
    coordinator = module.ReportCoordinator(tmp_path, runner=Runner(), event_addr=None)

    await coordinator.reconcile_once()
    assert fingerprints == []
    assert renders == []

    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_mode": "experiment",
                "active_experiment_id": None,
                "updated_at": "2026-07-09T00:00:01+00:00",
            }
        ),
        encoding="utf-8",
    )
    coordinator.notify_terminal(experiment_id)
    await coordinator.reconcile_once()

    assert fingerprints == [experiment_id, experiment_id]
    assert renders == [experiment_id]
    await coordinator.stop()


def test_eligibility_requires_exact_fields_and_valid_time(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    valid = _terminal_experiment(
        tmp_path,
        "exp-valid",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    invalid_bool = _terminal_experiment(
        tmp_path,
        "exp-string-false",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    invalid_id = _terminal_experiment(
        tmp_path,
        "exp-mismatch",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    _terminal_experiment(
        tmp_path,
        "exp-bad-time",
        ended_at="not-a-time",
    )
    payload = json.loads((invalid_bool / "metadata.json").read_text(encoding="utf-8"))
    payload["experiment"]["report_enabled"] = "false"
    (invalid_bool / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    payload = json.loads((invalid_id / "metadata.json").read_text(encoding="utf-8"))
    payload["experiment"]["experiment_id"] = "someone-else"
    (invalid_id / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    coordinator = ReportCoordinator(tmp_path, event_addr=None)
    roots = coordinator._next_batch()

    assert [root.name for root in roots] == [valid.name]


def test_existing_partial_active_state_fails_closed(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    _terminal_experiment(tmp_path, "exp-active", ended_at="2026-07-09T00:00:00+00:00")
    (tmp_path / "experiment_state.json").write_text("{}", encoding="utf-8")
    coordinator = ReportCoordinator(tmp_path, event_addr=None)

    assert coordinator._next_batch() == []


def test_permanent_metadata_contract_failure_becomes_bounded_poison(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    root = _terminal_experiment(tmp_path, "exp-invalid", ended_at="not-a-time")
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(max_attempts=3),
        event_addr=None,
    )

    assert coordinator._next_batch() == []
    first = load_report_state(root)
    assert first is not None
    assert first["status"] == "FAILED"
    assert first["attempt_count"] == 3
    assert first["error_code"] == "permanent_contract_failure"

    assert coordinator._next_batch() == []
    assert load_report_state(root) == first


async def test_corrupt_report_state_is_preserved_for_explicit_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-corrupt-state",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    state_path = root / "report_state.json"
    original = '{"schema":999,"future_field":"preserve-me"}\n'
    state_path.write_text(original, encoding="utf-8")
    fingerprint = "sha256:" + "d" * 64
    monkeypatch.setattr(module, "compute_source_fingerprint", lambda _root: fingerprint)
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)

    class NoRender:
        def generate_experiment(self, *_args, **_kwargs) -> None:
            pytest.fail("corrupt state must poison instead of rendering")

    coordinator = module.ReportCoordinator(tmp_path, runner=NoRender(), event_addr=None)
    await coordinator._reconcile_experiment(root)
    await coordinator._reconcile_experiment(root)

    assert state_path.read_text(encoding="utf-8") == original


async def test_one_shot_report_state_eio_preserves_state_then_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    root = _terminal_experiment(
        tmp_path,
        "exp-state-eio",
        ended_at="2026-07-09T00:00:00+00:00",
    )
    fingerprint = module.compute_source_fingerprint(root)
    running = new_running_state(
        root.name,
        fingerprint,
        "generation-token-0001",
        "owner-token-000000001",
        attempt_count=1,
        max_attempts=5,
    )
    failed = terminal_state(
        running,
        owner_token=running["owner_token"],
        succeeded=False,
        error_code="render_failed",
        error_text="retryable",
    )
    failed["not_before"] = 0
    write_report_state(root, failed)
    state_path = root / "report_state.json"
    original_bytes = state_path.read_bytes()
    original_read_text = Path.read_text
    faulted = False

    def one_shot_eio(path: Path, *args, **kwargs):
        nonlocal faulted
        if path == state_path and not faulted:
            faulted = True
            raise OSError("simulated one-shot EIO")
        return original_read_text(path, *args, **kwargs)

    rendered: list[str] = []

    class Runner:
        def generate_experiment(self, experiment_id: str, *, automatic: bool = False) -> None:
            assert automatic is True
            rendered.append(experiment_id)

    monkeypatch.setattr(Path, "read_text", one_shot_eio)
    monkeypatch.setattr(module, "load_current_manifest", lambda _root: None)
    coordinator = module.ReportCoordinator(tmp_path, runner=Runner(), event_addr=None)

    await coordinator._reconcile_experiment(root)
    assert state_path.read_bytes() == original_bytes
    assert rendered == []

    await coordinator._reconcile_experiment(root)
    assert rendered == [root.name]
    state = load_report_state(root)
    assert state is not None
    assert state["status"] == "FAILED"
    assert state["attempt_count"] == 1


def test_invalid_cursor_resets_to_safe_lexical_sweep(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    _terminal_experiment(tmp_path, "exp-a", ended_at="2026-07-09T00:00:00+00:00")
    _terminal_experiment(tmp_path, "exp-b", ended_at="2026-07-09T00:00:00+00:00")
    cursor = tmp_path / "reporting" / "reconcile_cursor.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text("{broken", encoding="utf-8")

    coordinator = ReportCoordinator(tmp_path, event_addr=None)

    assert [root.name for root in coordinator._next_batch()] == ["exp-a", "exp-b"]


def test_readable_stale_cursor_cannot_override_fallback_after_write_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.agents.assistant.report_coordinator as module

    for index in range(6):
        _terminal_experiment(
            tmp_path,
            f"exp-{index}",
            ended_at="2026-07-09T00:00:00+00:00",
        )
    cursor = tmp_path / "reporting" / "reconcile_cursor.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(
        json.dumps(
            {"schema": 1, "last_experiment_id": "exp-0", "updated_at": time.time()}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "atomic_write_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace denied")),
    )
    coordinator = module.ReportCoordinator(
        tmp_path,
        config=module.ReportCoordinatorConfig(batch_size=2),
        event_addr=None,
    )

    seen = [root.name for _ in range(3) for root in coordinator._next_batch()]

    assert seen == ["exp-1", "exp-2", "exp-3", "exp-4", "exp-5"]


def test_cursor_rejects_boolean_schema(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    coordinator = ReportCoordinator(tmp_path, event_addr=None)
    cursor = tmp_path / "reporting" / "reconcile_cursor.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(
        json.dumps(
            {"schema": True, "last_experiment_id": "exp-a", "updated_at": time.time()}
        ),
        encoding="utf-8",
    )
    assert coordinator._load_cursor() is None


@pytest.mark.parametrize("event_type", ["experiment_finalize", "experiment_stop", "experiment_abort"])
async def test_real_terminal_events_wake_priority_lane(
    tmp_path: Path,
    event_type: str,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    coordinator = ReportCoordinator(tmp_path, event_addr=None)
    await coordinator._on_event({"event_type": event_type, "experiment_id": "exp-event"})
    assert list(coordinator._priority_ids) == ["exp-event"]
    assert coordinator._wake.is_set()


def test_symlinked_cursor_directory_cannot_escape_data_root(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import (
        ReportCoordinator,
        ReportCoordinatorConfig,
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "reporting").symlink_to(outside, target_is_directory=True)
    for index in range(5):
        _terminal_experiment(
            tmp_path,
            f"exp-{index}",
            ended_at="2026-07-09T00:00:00+00:00",
        )
    coordinator = ReportCoordinator(
        tmp_path,
        config=ReportCoordinatorConfig(batch_size=2),
        event_addr=None,
    )

    seen = [root.name for _ in range(3) for root in coordinator._next_batch()]

    assert seen == ["exp-0", "exp-1", "exp-2", "exp-3", "exp-4"]
    assert list(outside.iterdir()) == []


async def test_coordinator_leadership_releases_and_standby_takes_over(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import ReportCoordinator

    first = ReportCoordinator(tmp_path, event_addr=None)
    second = ReportCoordinator(tmp_path, event_addr=None)
    calls: list[str] = []

    monkeypatch.setattr(first, "_next_batch", lambda: calls.append("first") or [])
    monkeypatch.setattr(second, "_next_batch", lambda: calls.append("second") or [])

    await first.reconcile_once()
    await second.reconcile_once()
    assert calls == ["first"]

    await first.stop()
    await second.reconcile_once()
    assert calls == ["first", "second"]
    await second.stop()


def test_reporting_config_rejects_string_boolean_and_out_of_bounds_values(
    tmp_path: Path,
) -> None:
    from cryodaq.agents.assistant.report_coordinator import load_report_coordinator_config

    (tmp_path / "reporting.yaml").write_text(
        "reporting:\n"
        "  automatic_enabled: 'false'\n"
        "  reconcile_interval_s: 1\n"
        "  scan_batch_size: 1000\n",
        encoding="utf-8",
    )

    config = load_report_coordinator_config(tmp_path)

    assert config.automatic_enabled is True
    assert config.scan_interval_s == 30
    assert config.batch_size == 32


def test_future_dated_reporting_config_uses_safe_default(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.report_coordinator import load_report_coordinator_config

    path = tmp_path / "reporting.yaml"
    path.write_text("reporting:\n  automatic_enabled: false\n", encoding="utf-8")
    future = time.time() + 600
    os.utime(path, (future, future))

    assert load_report_coordinator_config(tmp_path).automatic_enabled is True
