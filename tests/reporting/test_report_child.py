from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from cryodaq.report_process import read_result_file, result_file_path
from cryodaq.report_state import load_current_manifest
from cryodaq.reporting import __main__ as child


def _experiment(data_dir: Path) -> Path:
    root = data_dir / "experiments" / "exp-1"
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {"experiment_id": "exp-1", "report_enabled": True},
                "template": {"report_enabled": True},
            }
        ),
        encoding="utf-8",
    )
    return root


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        kind="experiment",
        experiment_id="exp-1",
        generation_id="generation-token-0001",
        deadline_epoch=time.time() + 30,
    )


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
