from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cryodaq.report_process import (
    ReportProcessError,
    ReportProcessRunner,
    build_report_command,
    read_result_file,
    result_file_path,
)
from cryodaq.report_state import build_current_manifest, promote_generation


def test_development_command_uses_module_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = build_report_command("exp-1", "generation-token-0001", deadline_epoch=123.0)
    assert command[:4] == [sys.executable, "-m", "cryodaq.reporting", "experiment"]
    assert "--experiment-id=exp-1" in command
    assert "--generation-id=generation-token-0001" in command


def test_frozen_command_reinvokes_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/CryoDAQ.exe")
    command = build_report_command("exp-1", "generation-token-0001", deadline_epoch=123.0)
    assert command[:3] == ["/opt/CryoDAQ.exe", "--mode=report-render", "experiment"]
    assert "-m" not in command


def test_result_file_is_size_and_schema_bounded(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"schema": 1, "ok": True, "report": {}}), encoding="utf-8")
    with pytest.raises(ReportProcessError):
        read_result_file(result)
    result.write_bytes(b"{" + b"x" * (128 * 1024) + b"}")
    with pytest.raises(ReportProcessError, match="too large"):
        read_result_file(result)


def test_result_schema_rejects_json_boolean(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "schema": True,
                "ok": False,
                "generation_id": "generation-token-0001",
                "report": None,
                "error_code": "failed",
                "error_text": "",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReportProcessError, match="unsupported schema"):
        read_result_file(result)


def test_parent_recovers_nonzero_child_after_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    staging = experiment_root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(experiment_root, generation_id, manifest)
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)
    monkeypatch.setattr(runner, "_run_process", lambda *_args, **_kwargs: 7)

    report = runner.generate_experiment("exp-1")

    assert report["docx_path"].endswith("reports/generations/generation-token-0001/report_editable.docx")


def test_parent_does_not_recover_nonzero_without_valid_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)
    monkeypatch.setattr(runner, "_run_process", lambda *_args, **_kwargs: 7)

    with pytest.raises(ReportProcessError):
        runner.generate_experiment("exp-1")


@pytest.mark.parametrize("result_kind", ["valid_success", "valid_failure", "malformed"])
def test_parent_nonzero_always_trusts_matching_manifest_over_result_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_kind: str,
) -> None:
    import cryodaq.report_process as module

    experiment_root = tmp_path / "experiments" / "exp-1"
    experiment_root.mkdir(parents=True)
    (experiment_root / "metadata.json").write_text("{}", encoding="utf-8")
    generation_id = "generation-token-0001"
    staging = experiment_root / "reports" / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    promote_generation(experiment_root, generation_id, manifest)
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: generation_id)

    def nonzero_with_result(*_args, **_kwargs) -> int:
        path = result_file_path(tmp_path, generation_id)
        if result_kind == "malformed":
            path.write_text("{", encoding="utf-8")
        else:
            ok = result_kind == "valid_success"
            payload = {
                "schema": 1,
                "ok": ok,
                "generation_id": generation_id,
                "report": (
                    {
                        "docx_path": "/untrusted/docx",
                        "pdf_path": None,
                        "assets_dir": "/untrusted/assets",
                        "sections": [],
                        "skipped": False,
                        "reason": "",
                    }
                    if ok
                    else None
                ),
                "error_code": None if ok else "crashed",
                "error_text": "" if ok else "after commit",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
        return 7

    monkeypatch.setattr(runner, "_run_process", nonzero_with_result)

    report = runner.generate_experiment("exp-1")
    assert report["docx_path"].endswith("reports/generations/generation-token-0001/report_editable.docx")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group assertion")
def test_timeout_kills_nested_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "nested.pid"
    fake_soffice = tmp_path / "fake_soffice.py"
    fake_soffice.write_text("import time; time.sleep(60)\n", encoding="utf-8")
    script = tmp_path / "report_child.py"
    script.write_text(
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,sys.argv[1]])\n"
        "open(sys.argv[2],'w').write(str(p.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    with pytest.raises(ReportProcessError, match="timed out"):
        runner._run_process([sys.executable, str(script), str(fake_soffice), str(pid_file)])
    pid = int(pid_file.read_text(encoding="ascii"))
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"nested child {pid} survived report timeout")


def test_windows_cleanup_abstraction_uses_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    import cryodaq.report_process as module

    calls: list[list[str]] = []
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **_kwargs: calls.append(list(argv)) or subprocess.CompletedProcess(argv, 0),
    )
    module.terminate_process_tree(321, grace_s=0.0)
    assert calls == [["taskkill", "/PID", "321", "/T", "/F"]]


def test_windows_job_closes_on_ordinary_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    events: list[str] = []

    class FakeProcess:
        pid = 321

        def wait(self, timeout: float | None = None) -> int:
            events.append("wait")
            return 7

    class FakeJob:
        closed = False

        def close(self) -> None:
            events.append("close")
            self.closed = True

    process = FakeProcess()
    job = FakeJob()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: events.append("assign") or job,
    )

    assert runner._run_process(["fixed-child"]) == 7
    assert job.closed is True
    assert events == ["assign", "wait", "close"]


def test_windows_job_closes_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            pass

    class FakeJob:
        closes = 0

        def close(self) -> None:
            self.closes += 1

    process = FakeProcess()
    job = FakeJob()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(module, "_create_windows_job", lambda _process: job)

    with pytest.raises(ReportProcessError, match="timed out"):
        runner._run_process(["fixed-child"])
    assert job.closes >= 1


def test_windows_job_assignment_failure_kills_tree_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321

        def wait(self, timeout: float | None = None) -> int:
            return 1

    events: list[int] = []
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda pid: events.append(pid),
    )

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert events == [321]


def test_windows_job_assignment_failure_forces_kill_when_wait_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0
        killed = False

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(module, "terminate_process_tree", lambda _pid: None)

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert process.killed is True
    assert process.waits == 2


def test_windows_job_assignment_failure_survives_throwing_taskkill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_process as module

    class FakeProcess:
        pid = 321
        waits = 0
        killed = False

        def wait(self, timeout: float | None = None) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixed-child", timeout)
            return 1

        def kill(self) -> None:
            self.killed = True

    process = FakeProcess()
    runner = ReportProcessRunner(tmp_path, timeout_s=0.5)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module, "_creation_kwargs", lambda: {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module,
        "_create_windows_job",
        lambda _process: (_ for _ in ()).throw(OSError("assignment failed")),
    )
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda _pid: (_ for _ in ()).throw(subprocess.TimeoutExpired("taskkill", 2.0)),
    )

    with pytest.raises(ReportProcessError, match="Windows Job Object"):
        runner._run_process(["fixed-child"])
    assert process.killed is True
    assert process.waits == 2


def test_reporting_package_and_engine_do_not_eagerly_import_generator() -> None:
    code = (
        "import sys; import cryodaq.reporting; import cryodaq.engine; "
        "assert 'cryodaq.reporting.generator' not in sys.modules; "
        "assert 'cryodaq.reporting.sections' not in sys.modules; "
        "assert 'cryodaq.notifications.periodic_report' not in sys.modules; "
        "assert 'docx' not in sys.modules; "
        "assert 'matplotlib' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
