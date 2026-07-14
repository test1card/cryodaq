from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from build_scripts import windows_onedir_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-onedir-smoke.yml"


def test_workflow_builds_and_executes_real_windows_onedir() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in text
    assert '- "environment.yml"' in text
    assert "conda-incubator/setup-miniconda@8ee1f361103df19b6f8c8655fd3967a8ecb162d5" in text
    assert "environment-file: environment.yml" in text
    assert "-r requirements-lock.txt" in text
    assert "pip install --disable-pip-version-check . --no-deps" in text
    assert "python -m pip check" in text
    assert "PyInstaller build_scripts/cryodaq.spec" in text
    assert "python build_scripts/post_build.py" in text
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


def test_smoke_summary_fails_closed_on_not_run_or_invalid_status() -> None:
    assert smoke.smoke_summary([{"name": "pending", "status": "NOT_RUN"}]) == (
        "FAIL",
        "REQUIRED_CELLS_NOT_RUN",
    )
    assert smoke.smoke_summary([{"name": "bad", "status": "UNKNOWN"}]) == (
        "FAIL",
        "INVALID_CELL_STATUS",
    )
    assert smoke.smoke_summary([{"name": "done", "status": "PASS"}]) == (
        "PASS",
        None,
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
