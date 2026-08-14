from __future__ import annotations

import hashlib
import importlib
import io
import json
import subprocess
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from build_scripts import windows_onedir_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-onedir-smoke.yml"
EXPECTED_SMOKE_CELL_NAMES = (
    "frozen_driver_imports",
    "gui_startup_offscreen",
    "report_render_unicode",
    "windows_job_timeout",
    "assistant_h2_agent_off",
    "assistant_h2_agent_missing",
    "assistant_replay_exact_off",
    "assistant_h3_only_allowed_idle",
    "assistant_h3_only_restart_lock_release",
)


def test_workflow_builds_and_executes_real_windows_onedir() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in text
    assert '- "environment.yml"' in text
    assert "conda-incubator/setup-miniconda@8ee1f361103df19b6f8c8655fd3967a8ecb162d5" in text
    assert "environment-file: environment.yml" in text
    assert "-r requirements-lock.txt" in text
    assert "pip install --disable-pip-version-check . --no-deps --no-build-isolation" in text
    assert "python -m pip check" in text
    assert "PyInstaller build_scripts/cryodaq.spec" in text
    assert "python build_scripts/post_build.py" in text
    assert "UNQUALIFIED — TEST ONLY" in text
    assert "+checkpoint.unqualified" in text
    assert "Compress-Archive" in text
    assert "windows_onedir_smoke.py check-warnings" in text
    assert "windows_onedir_smoke.py smoke" in text
    assert "build/cryodaq/warn-cryodaq.txt" in text
    assert "dist/CryoDAQ/" in text
    assert "build/windows-smoke/" in text
    assert "Verify safe SQLite runtime" in text
    assert "python -m cryodaq" not in text.lower()
    assert '- "src/**"' in text
    assert '- "config/**"' in text
    assert '- "tsp/**"' in text
    assert "UNQUALIFIED-TEST-ONLY" in text


def test_smoke_matrix_starts_the_built_gui_offscreen() -> None:
    source = (ROOT / "build_scripts" / "windows_onedir_smoke.py").read_text(encoding="utf-8")

    assert 'command = [str(executable), "--mode=gui"]' in source
    assert '"QT_QPA_PLATFORM": "offscreen"' in source
    assert "_run_gui_startup_cell(executable, runtime_root, evidence_dir)" in source


def test_gui_smoke_waits_for_process_not_inherited_pipe_eof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_pipe = threading.Event()

    class InheritedPipe(io.BytesIO):
        def read(self, _size: int = -1) -> bytes:
            data = super().read()
            if data:
                return data
            release_pipe.wait(timeout=5)
            return b""

    class Process:
        pid = 1234
        returncode = 0
        stdout = InheritedPipe(b"gui output\n")
        stderr = InheritedPipe()

        def poll(self) -> None:
            return None

        def send_signal(self, _signal: int) -> None:
            return None

        def wait(self, timeout: float) -> int:
            assert timeout == 20
            return self.returncode

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired("CryoDAQ.exe", timeout)

        def terminate(self) -> None:
            return None

    process = Process()
    ticks = iter((0.0, 0.0, 6.0, 6.0))
    monkeypatch.setattr(smoke.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(smoke, "_pid_exists", lambda _pid: False)

    outcome = None
    try:
        outcome = smoke._run_gui_startup_cell(tmp_path / "CryoDAQ.exe", tmp_path, tmp_path)
    except subprocess.TimeoutExpired:
        pass
    finally:
        release_pipe.set()

    assert outcome is not None, "GUI smoke must wait for the direct process, not inherited pipe EOF"
    assert outcome["status"] == "PASS"
    assert (tmp_path / "gui_startup_offscreen.stdout.log").read_bytes() == b"gui output\n"


def test_smoke_matrix_runs_frozen_driver_imports_from_the_built_exe() -> None:
    source = (ROOT / "build_scripts" / "windows_onedir_smoke.py").read_text(encoding="utf-8")

    assert 'return [str(executable), "--mode=verify-frozen-drivers"]' in source
    assert "_run_frozen_driver_import_cell(executable, runtime_root, evidence_dir)" in source


def test_run_smoke_executes_frozen_driver_cell_as_required_production_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "CryoDAQ.exe").write_bytes(b"test placeholder")
    calls: list[str] = []

    def frozen(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls.append("frozen_driver_imports")
        return {"name": "frozen_driver_imports", "status": "PASS"}

    def gui(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls.append("gui_startup_offscreen")
        return {"name": "gui_startup_offscreen", "status": "PASS"}

    def timeout(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls.append("windows_job_timeout")
        return {"name": "windows_job_timeout", "status": "PASS"}

    def named(*_args: object, name: str, **_kwargs: object) -> dict[str, str]:
        calls.append(name)
        return {"name": name, "status": "PASS"}

    def ignore_config(*_args: object, **_kwargs: object) -> None:
        return None

    def inventory(*_args: object, **_kwargs: object) -> dict[str, int]:
        return {"schema": 1}

    monkeypatch.setattr(smoke.os, "name", "nt")
    monkeypatch.setattr(smoke, "_run_frozen_driver_import_cell", frozen)
    monkeypatch.setattr(smoke, "_run_gui_startup_cell", gui)
    monkeypatch.setattr(smoke, "_run_report_cell", named)
    monkeypatch.setattr(smoke, "_run_job_timeout_cell", timeout)
    monkeypatch.setattr(smoke, "_run_assistant_cell", named)
    monkeypatch.setattr(smoke, "_write_periodic_config", ignore_config)
    monkeypatch.setattr(smoke, "_artifact_inventory", inventory)

    evidence_dir = tmp_path / "success-evidence"
    assert smoke.run_smoke(dist_dir, evidence_dir) == 0
    result = json.loads((evidence_dir / "smoke-result.json").read_text(encoding="utf-8"))
    assert calls == list(EXPECTED_SMOKE_CELL_NAMES)
    assert [cell["name"] for cell in result["cells"]] == list(EXPECTED_SMOKE_CELL_NAMES)
    assert result["status"] == "PASS"

    calls.clear()

    def fail_frozen(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls.append("frozen_driver_imports")
        raise RuntimeError("FROZEN_DRIVER_REQUIRED_CONTROL")

    monkeypatch.setattr(smoke, "_run_frozen_driver_import_cell", fail_frozen)
    failure_dir = tmp_path / "failure-evidence"
    assert smoke.run_smoke(dist_dir, failure_dir) == 1
    failure = json.loads((failure_dir / "smoke-result.json").read_text(encoding="utf-8"))
    assert calls == ["frozen_driver_imports"]
    assert failure["status"] == "FAIL"
    assert "FROZEN_DRIVER_REQUIRED_CONTROL" in failure["reason"]
    assert failure["cells"] == []


def test_frozen_driver_import_cell_accepts_only_the_exact_live_registry_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    evidence_dir = tmp_path / "evidence"
    runtime_root.mkdir()
    evidence_dir.mkdir()
    executable = runtime_root / "CryoDAQ.exe"
    executable.write_bytes(b"test placeholder")
    expected = smoke._expected_frozen_driver_import_payload()
    payload = {
        **expected,
        "module_files": {module: f"frozen/{module}.py" for module in expected["modules"]},
    }
    stdout = (smoke._FROZEN_DRIVER_IMPORT_PREFIX + json.dumps(payload) + "\n").encode()
    captured: dict[str, object] = {}

    def complete(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setenv("PYTHONHOME", "source-interpreter-control")
    monkeypatch.setenv("PYTHONPATH", "source-tree-control")
    monkeypatch.setattr(smoke.subprocess, "run", complete)

    cell = smoke._run_frozen_driver_import_cell(executable, runtime_root, evidence_dir)

    assert cell["status"] == "PASS"
    assert cell["validation"] == expected
    assert captured["command"] == [str(executable), "--mode=verify-frozen-drivers"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert "PYTHONHOME" not in env
    assert "PYTHONPATH" not in env

    modules = expected["modules"]
    assert isinstance(modules, list) and modules
    incomplete = {
        **payload,
        "modules": modules[1:],
        "module_files": {module: payload["module_files"][module] for module in modules[1:]},
    }
    incomplete_stdout = (smoke._FROZEN_DRIVER_IMPORT_PREFIX + json.dumps(incomplete) + "\n").encode()
    with pytest.raises(ValueError, match="does not match the source registry"):
        smoke._parse_frozen_driver_import_payload(incomplete_stdout)


def test_frozen_driver_import_payload_rejects_integer_equality_type_collisions() -> None:
    expected = smoke._expected_frozen_driver_import_payload()
    payload = {
        **expected,
        "module_files": {module: f"frozen/{module}.py" for module in expected["modules"]},
    }
    for field in ("schema", "registry_compat_version"):
        integer = expected[field]
        assert type(integer) is int
        collisions: list[object] = [float(integer)]
        if integer in (0, 1):
            collisions.append(bool(integer))
        for collision in collisions:
            assert collision == integer and type(collision) is not int
            malformed = {**payload, field: collision}
            assert malformed[field] == collision
            stdout = (smoke._FROZEN_DRIVER_IMPORT_PREFIX + json.dumps(malformed) + "\n").encode()
            with pytest.raises(ValueError, match="exact field types"):
                smoke._parse_frozen_driver_import_payload(stdout)


def test_frozen_driver_import_payload_rejects_duplicate_json_fields() -> None:
    expected = smoke._expected_frozen_driver_import_payload()
    pairs = [
        ("schema", 999),
        ("schema", expected["schema"]),
        ("status", "FAIL"),
        ("status", expected["status"]),
        ("registry_compat_version", 999),
        ("registry_compat_version", expected["registry_compat_version"]),
        ("modules", []),
        ("modules", expected["modules"]),
    ]
    record = "{" + ",".join(f"{json.dumps(key)}:{json.dumps(value)}" for key, value in pairs) + "}"
    assert json.loads(record) == expected
    stdout = (smoke._FROZEN_DRIVER_IMPORT_PREFIX + record + "\n").encode()

    with pytest.raises(ValueError, match="repeats field"):
        smoke._parse_frozen_driver_import_payload(stdout)


def test_windows_source_installer_is_ascii_and_reproducible() -> None:
    raw = (ROOT / "install.bat").read_bytes()
    assert raw.isascii()
    text = raw.decode("ascii")
    assert "python -m pip install -r requirements-lock.txt" in text
    assert "python -m pip install -e . --no-deps --no-build-isolation" in text
    assert "if errorlevel 1" in text
    assert "%ERRORLEVEL%" not in text


def test_local_build_scripts_require_the_lock_and_fail_closed() -> None:
    batch = (ROOT / "build_scripts" / "build.bat").read_text(encoding="utf-8")
    shell = (ROOT / "build_scripts" / "build.sh").read_text(encoding="utf-8")

    assert "if not exist requirements-lock.txt" in batch
    assert 'cd /d "%~dp0\\.."\nif errorlevel 1 exit /b 1' in batch.replace("\r\n", "\n")
    assert "python -m PyInstaller" in batch
    assert "python build_scripts\\post_build.py\nif errorlevel 1 exit /b 1" in batch.replace("\r\n", "\n")
    assert "if [ ! -f requirements-lock.txt ]" in shell
    assert "python -m PyInstaller" in shell


def test_shortcut_failure_is_visible_and_powershell_literals_are_escaped(tmp_path, monkeypatch) -> None:
    shortcut = importlib.import_module("create_shortcut")
    desktop = tmp_path / "O'Brien"
    monkeypatch.setattr(shortcut.sys, "platform", "win32")
    monkeypatch.setattr(shortcut, "_get_desktop_path", lambda: desktop)
    monkeypatch.setattr(shortcut, "_get_pythonw", lambda: tmp_path / "pythonw.exe")
    calls = []

    def fail(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stderr="denied")

    monkeypatch.setattr(shortcut.subprocess, "run", fail)

    assert shortcut.create_shortcut() == 1
    assert "O''Brien" in calls[0][-1]


def test_required_warning_filter_is_exact_and_prefix_aware() -> None:
    text = "\n".join(
        [
            "missing module named aiohttp.client_reqrep - imported by x",
            "missing module named optional_vendor_module - imported by y",
            "missing module named 'cryodaq.agents.assistant.periodic_runtime' - imported by z",
        ]
    )

    assert smoke.required_missing_modules(text) == [
        "aiohttp.client_reqrep",
        "cryodaq.agents.assistant.periodic_runtime",
    ]


def test_reviewed_optional_and_nonmodule_warnings_are_exactly_exempt() -> None:
    reviewed = sorted(smoke._KNOWN_OPTIONAL_OR_NONMODULE_WARNINGS)
    exact = "\n".join(f"missing module named '{name}' - imported by x" for name in reviewed)
    near_misses = [f"{name}.unexpected" for name in reviewed]
    unknown = ["pyarrow.unknown_required", "zmq.unknown_required"]
    unsafe = "\n".join(f"missing module named '{name}' - imported by x" for name in near_misses + unknown)

    assert smoke.required_missing_modules(exact) == []
    assert smoke.required_missing_modules(unsafe) == sorted(near_misses + unknown)


def test_missing_warning_file_fails_closed_with_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "warning.json"

    assert smoke.check_warnings(tmp_path / "missing.txt", evidence) == 1
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload == {
        "reason": "PYINSTALLER_WARNING_FILE_MISSING",
        "required_missing_modules": [],
        "schema": 1,
        "status": "FAIL",
    }


def test_frozen_report_command_never_substitutes_python_module(tmp_path: Path) -> None:
    executable = tmp_path / "path with spaces" / "КриоДАК" / "CryoDAQ.exe"
    command = smoke.frozen_report_command(executable, "exp-1", "a" * 32)

    assert command[:3] == [str(executable), "--mode=report-render", "experiment"]
    assert "-m" not in command
    assert not any(part.lower().endswith(("python", "python.exe")) for part in command)

    with pytest.raises(ValueError, match="CryoDAQ.exe"):
        smoke.frozen_report_command(tmp_path / "python.exe", "exp-1", "a" * 32)


def _docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")


def _report_fixture(
    data_dir: Path,
    *,
    experiment_id: str = "exp-1",
    generation: str = "a" * 32,
) -> tuple[dict[str, object], dict[str, object], Path]:
    experiment = data_dir / "experiments" / experiment_id
    final = experiment / "reports" / "generations" / generation
    assets = final / "assets"
    assets.mkdir(parents=True)
    (assets / "chart.png").write_bytes(b"png")
    docx = final / "report_editable.docx"
    _docx(docx)
    report = {
        "docx_path": f"reports/generations/{generation}/report_editable.docx",
        "pdf_path": None,
        "assets_dir": f"reports/generations/{generation}/assets",
        "sections": ["title_page"],
        "skipped": False,
        "reason": "",
    }
    result_report = {
        **report,
        "docx_path": str(docx.resolve()),
        "assets_dir": str(assets.resolve()),
    }
    result = {
        "schema": 1,
        "ok": True,
        "generation_id": generation,
        "report": result_report,
        "error_code": None,
        "error_text": "",
    }
    (final / "result.json").write_text(json.dumps(result), encoding="utf-8")
    artifacts = []
    for path in sorted(item for item in final.rglob("*") if item.is_file()):
        artifacts.append(
            {
                "path": path.relative_to(final).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "schema": 1,
        "experiment_id": experiment_id,
        "generation_id": generation,
        "source_fingerprint": "sha256:" + "b" * 64,
        "created_at": 1.0,
        "report": report,
        "artifacts": artifacts,
    }
    (experiment / "reports" / "current_report.json").write_text(json.dumps(manifest), encoding="utf-8")
    result_dir = data_dir / "reporting" / "results"
    result_dir.mkdir(parents=True)
    (result_dir / f"experiment-{generation}.json").write_text(json.dumps(result), encoding="utf-8")
    return manifest, result, final


def _rewrite_artifacts(manifest: dict[str, object], final: Path) -> None:
    records = []
    for path in sorted(item for item in final.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(final).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest["artifacts"] = records
    manifest_path = final.parents[1] / "current_report.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_report_evidence_validates_manifest_hashes_and_docx(tmp_path: Path) -> None:
    generation = "a" * 32
    manifest, _result, _final = _report_fixture(tmp_path, generation=generation)

    evidence = smoke.validate_report_evidence(tmp_path, "exp-1", generation)

    docx_record = next(record for record in manifest["artifacts"] if record["path"] == "report_editable.docx")
    assert evidence["docx_sha256"] == docx_record["sha256"]
    assert evidence["pdf_path"] is None


def test_report_evidence_accepts_relative_data_root_from_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = "a" * 32
    data_dir = tmp_path / "relative-data"
    _report_fixture(data_dir, generation=generation)
    monkeypatch.chdir(tmp_path)

    evidence = smoke.validate_report_evidence(Path("relative-data"), "exp-1", generation)

    assert evidence["generation_id"] == generation


def test_report_evidence_rejects_artifact_tamper(tmp_path: Path) -> None:
    generation = "a" * 32
    manifest, _result, final = _report_fixture(tmp_path, generation=generation)
    manifest["artifacts"][0]["size"] = 1
    (final.parents[1] / "current_report.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="hash or size"):
        smoke.validate_report_evidence(tmp_path, "exp-1", generation)


def test_report_evidence_rejects_stale_generation_paths(tmp_path: Path) -> None:
    generation = "a" * 32
    stale = "c" * 32
    manifest, result, final = _report_fixture(tmp_path, generation=generation)
    stale_root = final.parent / stale
    stale_assets = stale_root / "assets"
    stale_assets.mkdir(parents=True)
    stale_docx = stale_root / "report_editable.docx"
    _docx(stale_docx)
    manifest_report = manifest["report"]
    manifest_report["docx_path"] = f"reports/generations/{stale}/report_editable.docx"
    manifest_report["assets_dir"] = f"reports/generations/{stale}/assets"
    result_report = result["report"]
    result_report["docx_path"] = str(stale_docx.resolve())
    result_report["assets_dir"] = str(stale_assets.resolve())
    (final / "result.json").write_text(json.dumps(result), encoding="utf-8")
    _rewrite_artifacts(manifest, final)
    external = tmp_path / "reporting" / "results" / f"experiment-{generation}.json"
    external.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="requested generation"):
        smoke.validate_report_evidence(tmp_path, "exp-1", generation)


def test_report_evidence_rejects_unrelated_artifact_inventory(tmp_path: Path) -> None:
    generation = "a" * 32
    manifest, _result, final = _report_fixture(tmp_path, generation=generation)
    manifest["artifacts"] = [record for record in manifest["artifacts"] if record["path"] != "report_editable.docx"]
    (final.parents[1] / "current_report.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly cover"):
        smoke.validate_report_evidence(tmp_path, "exp-1", generation)


def test_report_evidence_rejects_malformed_result_report(tmp_path: Path) -> None:
    generation = "a" * 32
    _manifest, result, _final = _report_fixture(tmp_path, generation=generation)
    result["report"] = {"bogus": True}
    external = tmp_path / "reporting" / "results" / f"experiment-{generation}.json"
    external.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="result report schema"):
        smoke.validate_report_evidence(tmp_path, "exp-1", generation)


def test_smoke_summary_fails_closed_on_status_or_roster_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert smoke.smoke_summary([{"name": "pending", "status": "NOT_RUN"}]) == (
        "FAIL",
        "REQUIRED_CELLS_NOT_RUN",
    )
    assert smoke.smoke_summary([{"name": "bad", "status": "UNKNOWN"}]) == (
        "FAIL",
        "INVALID_CELL_STATUS",
    )

    expected_names = EXPECTED_SMOKE_CELL_NAMES

    assert smoke._REQUIRED_SMOKE_CELLS == expected_names
    valid_cells = [{"name": name, "status": "PASS"} for name in expected_names]
    assert smoke.smoke_summary(valid_cells) == ("PASS", None)

    missing_driver_cell = [cell for cell in valid_cells if cell["name"] != "frozen_driver_imports"]
    assert smoke.smoke_summary(missing_driver_cell) == (
        "FAIL",
        "REQUIRED_CELL_ROSTER_MISMATCH",
    )
    duplicated_cell = [*valid_cells, dict(valid_cells[0])]
    assert smoke.smoke_summary(duplicated_cell) == (
        "FAIL",
        "DUPLICATE_CELL_NAME",
    )

    duplicate_required = (expected_names[0], expected_names[0], *expected_names[2:])
    monkeypatch.setattr(smoke, "_REQUIRED_SMOKE_CELLS", duplicate_required)
    matching_duplicate_cells = [{"name": name, "status": "PASS"} for name in duplicate_required]
    assert smoke.smoke_summary(matching_duplicate_cells) == (
        "FAIL",
        "INVALID_REQUIRED_CELL_ROSTER",
    )


def test_timeout_cell_uses_production_job_object_around_built_exe() -> None:
    source = (ROOT / "build_scripts" / "windows_onedir_smoke.py").read_text(encoding="utf-8")

    assert "from cryodaq.report_process import _create_windows_job" in source
    assert "job = _create_windows_job(process)" in source
    assert "command = frozen_report_command(executable" in source


def test_h3_allowed_idle_requires_exact_health_code_and_orderly_stop() -> None:
    source = (ROOT / "build_scripts" / "windows_onedir_smoke.py").read_text(encoding="utf-8")
    cell = source[source.index("def _run_assistant_cell(") : source.index("def _artifact_inventory(")]

    assert '_H3_ALLOWED_IDLE_HEALTH = ("degraded_source", "periodic_engine_unavailable")' in source
    assert "candidate == _H3_ALLOWED_IDLE_HEALTH" in cell
    assert 'health.get("status"), health.get("error_code")' in cell
    assert '"periodic_stopped"' in cell
    assert '"degraded_runtime"' not in cell


@pytest.mark.skipif(smoke.os.name == "nt", reason="non-Windows fail-closed contract")
def test_local_non_windows_run_records_external_gate_not_a_fake_pass(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"

    assert smoke.run_smoke(tmp_path / "dist", evidence) == 1
    payload = json.loads((evidence / "smoke-result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["reason"] == "RuntimeError:WINDOWS_REQUIRED"
    assert payload["cells"] == []
