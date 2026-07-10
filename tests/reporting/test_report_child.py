from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from cryodaq.report_process import read_result_file, result_file_path
from cryodaq.report_state import (
    compute_source_fingerprint,
    load_current_manifest,
    load_report_state,
    new_pending_state,
    new_running_state,
    terminal_state,
    write_report_state,
)
from cryodaq.reporting import __main__ as child


def _experiment(data_dir: Path) -> Path:
    root = data_dir / "experiments" / "exp-1"
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": "exp-1",
                    "status": "COMPLETED",
                    "end_time": "2026-07-09T00:00:00+00:00",
                    "report_enabled": True,
                    "retroactive": False,
                },
                "template": {"report_enabled": True},
            }
        ),
        encoding="utf-8",
    )
    return root


def _args(
    generation_id: str = "generation-token-0001",
    *,
    automatic: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        kind="experiment",
        experiment_id="exp-1",
        generation_id=generation_id,
        deadline_epoch=time.time() + 30,
        automatic=automatic,
    )


def _patch_fast_generator(monkeypatch, calls: list[str] | None = None) -> None:
    from cryodaq.reporting.generator import ReportGenerator

    def fake_generate(
        _self,
        _experiment_id: str,
        output_dir: Path,
        *,
        deadline_epoch: float,
    ) -> SimpleNamespace:
        del deadline_epoch
        if calls is not None:
            calls.append(output_dir.name)
        (output_dir / "assets").mkdir(parents=True)
        (output_dir / "report_editable.docx").write_bytes(b"docx")
        return SimpleNamespace(sections=("title_page",), skipped=False, reason="")

    monkeypatch.setattr(ReportGenerator, "generate_to_directory", fake_generate)


def test_child_acquires_lock_before_fingerprinting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _experiment(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(
        child,
        "try_acquire_lock",
        lambda *_args, **_kwargs: events.append("lock") or None,
    )
    monkeypatch.setattr(
        child,
        "compute_source_fingerprint",
        lambda _root: events.append("fingerprint") or "sha256:" + "1" * 64,
    )
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(), tmp_path, result_path) == 2
    assert events == ["lock"]


def test_automatic_child_rechecks_current_manifest_under_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _experiment(tmp_path)
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    first_result = result_file_path(tmp_path, "generation-token-0001")
    second_result = result_file_path(tmp_path, "generation-token-0002")

    assert child._run_experiment(_args(), tmp_path, first_result) == 0
    assert child._run_experiment(
        _args("generation-token-0002", automatic=True),
        tmp_path,
        second_result,
    ) == 3

    assert read_result_file(second_result)["error_code"] == "already_current"
    assert calls == ["generation-token-0001"]


def test_automatic_child_rejects_still_active_experiment_before_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _experiment(tmp_path)
    (tmp_path / "experiment_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "app_mode": "experiment",
                "active_experiment_id": "exp-1",
                "updated_at": "2026-07-09T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        child,
        "compute_source_fingerprint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("active experiment must not be fingerprinted")
        ),
    )
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(automatic=True), tmp_path, result_path) == 3
    assert read_result_file(result_path)["error_code"] == "ineligible"


def test_post_manifest_state_error_recovers_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)

    from cryodaq.reporting.generator import ReportGenerator

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
        (output_dir / "report_raw.docx").write_bytes(b"raw")
        return SimpleNamespace(sections=("title_page",), skipped=False, reason="")

    monkeypatch.setattr(ReportGenerator, "generate_to_directory", fake_generate)
    real_write = child.write_report_state
    calls = 0

    def fail_terminal(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("state disk fault after manifest")
        real_write(*args, **kwargs)

    monkeypatch.setattr(child, "write_report_state", fail_terminal)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(), tmp_path, result_path) == 0
    manifest = load_current_manifest(root)
    assert manifest is not None
    assert manifest["generation_id"] == "generation-token-0001"
    result = read_result_file(result_path)
    assert result["ok"] is True


def test_post_manifest_reload_validation_error_is_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _experiment(tmp_path)

    from cryodaq.reporting.generator import ReportGenerator

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
    real_write = child.write_report_state
    calls = 0

    def fail_terminal(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("post-manifest state fault")
        real_write(*args, **kwargs)

    monkeypatch.setattr(child, "write_report_state", fail_terminal)
    monkeypatch.setattr(
        child,
        "load_current_manifest",
        lambda _root: (_ for _ in ()).throw(RuntimeError("manifest reload failed")),
    )
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(), tmp_path, result_path) == 1
    result = read_result_file(result_path)
    assert result["ok"] is False


def test_child_resets_attempt_count_when_fingerprint_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    running = new_running_state(
        "exp-1",
        "sha256:" + "0" * 64,
        "old-generation-0001",
        "old-owner-token-0001",
        attempt_count=5,
        max_attempts=5,
    )
    failed = terminal_state(
        running,
        owner_token="old-owner-token-0001",
        succeeded=False,
        error_code="render_failed",
        error_text="old source failed",
    )
    write_report_state(root, failed)
    _patch_fast_generator(monkeypatch)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(), tmp_path, result_path) == 0
    state = load_report_state(root)
    assert state is not None
    assert state["attempt_count"] == 1
    assert state["source_fingerprint"] != failed["source_fingerprint"]


def test_poison_blocks_automatic_but_manual_overrides_under_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    fingerprint = compute_source_fingerprint(root)
    running = new_running_state(
        "exp-1",
        fingerprint,
        "old-generation-0001",
        "old-owner-token-0001",
        attempt_count=5,
        max_attempts=5,
    )
    failed = terminal_state(
        running,
        owner_token="old-owner-token-0001",
        succeeded=False,
        error_code="render_failed",
        error_text="poison",
    )
    write_report_state(root, failed)
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    automatic_result = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(
        _args(automatic=True),
        tmp_path,
        automatic_result,
    ) == 3
    assert read_result_file(automatic_result)["error_code"] == "poisoned"
    assert calls == []

    manual_result = result_file_path(tmp_path, "generation-token-0002")
    assert child._run_experiment(
        _args("generation-token-0002"),
        tmp_path,
        manual_result,
    ) == 0
    state = load_report_state(root)
    assert state is not None
    assert state["status"] == "SUCCEEDED"
    assert state["attempt_count"] == 1
    assert calls == ["generation-token-0002"]


def test_automatic_child_enforces_not_before_under_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    fingerprint = compute_source_fingerprint(root)
    pending = new_pending_state(
        "exp-1",
        fingerprint,
        "old-generation-0001",
        "old-owner-token-0001",
        not_before=time.time() + 60,
    )
    write_report_state(root, pending)
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(automatic=True), tmp_path, result_path) == 3
    assert read_result_file(result_path)["error_code"] == "backoff"
    assert calls == []


def test_automatic_child_free_lock_marks_running_attempt_failed_immediately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    fingerprint = compute_source_fingerprint(root)
    running = new_running_state(
        "exp-1",
        fingerprint,
        "old-generation-0001",
        "old-owner-token-0001",
        attempt_count=1,
    )
    write_report_state(root, running)
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(
        _args(automatic=True),
        tmp_path,
        result_path,
    ) == 3
    assert read_result_file(result_path)["error_code"] == "stale_running"
    assert calls == []
    state = load_report_state(root)
    assert state is not None
    assert state["status"] == "FAILED"
    assert state["attempt_count"] == 1
    assert state["error_code"] == "stale_running"


def test_manual_child_can_render_retroactive_experiment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    metadata_path = root / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["experiment"]["retroactive"] = True
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(_args(), tmp_path, result_path) == 0
    assert calls == ["generation-token-0001"]


def test_stale_running_at_attempt_limit_becomes_poison_under_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _experiment(tmp_path)
    fingerprint = compute_source_fingerprint(root)
    running = new_running_state(
        "exp-1",
        fingerprint,
        "old-generation-0001",
        "old-owner-token-0001",
        attempt_count=5,
        max_attempts=5,
    )
    write_report_state(root, running)
    calls: list[str] = []
    _patch_fast_generator(monkeypatch, calls)
    result_path = result_file_path(tmp_path, "generation-token-0001")

    assert child._run_experiment(
        _args(automatic=True),
        tmp_path,
        result_path,
    ) == 3
    assert read_result_file(result_path)["error_code"] == "poisoned"
    state = load_report_state(root)
    assert state is not None
    assert state["status"] == "FAILED"
    assert state["attempt_count"] == 5
    assert calls == []
