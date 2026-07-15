"""Deterministic acceptance smoke for the real Windows PyInstaller ONEDIR.

The harness itself may run under the CI Python interpreter, but every CryoDAQ
runtime cell starts the copied ``CryoDAQ.exe``.  Source-tree ``python -m``
execution is never accepted as frozen evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Any

_JSON_LIMIT = 256 * 1024
_RESULT_LIMIT = 64 * 1024
_REQUIRED_FROZEN_MODULES = (
    "aiohttp",
    "cryodaq.agents.assistant.periodic_png",
    "cryodaq.agents.assistant.periodic_projection",
    "cryodaq.agents.assistant.periodic_runtime",
    "cryodaq.agents.assistant.periodic_telegram",
    "cryodaq.agents.assistant_bootstrap",
    "cryodaq.reporting.__main__",
    "cryodaq.reporting.periodic_input",
    "cryodaq.reporting.periodic_renderer",
    "docx",
    "matplotlib.backends.backend_agg",
    "msgpack",
    "PIL",
    "pyarrow",
    "tzdata",
    "zmq",
)
_KNOWN_OPTIONAL_OR_NONMODULE_WARNINGS = frozenset(
    {
        "pyarrow._azurefs",
        "pyarrow._cuda",
        "pyarrow.gandiva",
        "zmq.ZMQError",
        "zmq.backend.Context",
        "zmq.backend.Frame",
        "zmq.backend.Socket",
        "zmq.backend.proxy",
        "zmq.backend.strerror",
        "zmq.backend.zmq_errno",
        "zmq.backend.zmq_poll",
        "zmq.backend.zmq_version_info",
        "zmq.zmq_version",
        "zmq.zmq_version_info",
    }
)
_MISSING_MODULE = re.compile(r"missing module named ['\"]?([^ '\",]+)")
_H3_ALLOWED_IDLE_HEALTH = ("degraded_source", "periodic_engine_unavailable")


def _json_bytes(payload: object) -> bytes:
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > _JSON_LIMIT:
        raise ValueError("evidence JSON is oversized")
    return raw


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_json_bytes(payload))
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_missing_modules(warning_text: str) -> list[str]:
    """Return required modules named by PyInstaller's warning report."""

    missing: set[str] = set()
    for line in warning_text.splitlines():
        match = _MISSING_MODULE.search(line)
        if match is None:
            continue
        candidate = match.group(1)
        if candidate in _KNOWN_OPTIONAL_OR_NONMODULE_WARNINGS:
            continue
        if any(candidate == required or candidate.startswith(required + ".") for required in _REQUIRED_FROZEN_MODULES):
            missing.add(candidate)
    return sorted(missing)


def check_warnings(warn_file: Path, evidence_file: Path) -> int:
    if not warn_file.is_file():
        payload = {
            "schema": 1,
            "status": "FAIL",
            "reason": "PYINSTALLER_WARNING_FILE_MISSING",
            "required_missing_modules": [],
        }
        _atomic_json(evidence_file, payload)
        return 1
    raw = warn_file.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    missing = required_missing_modules(text)
    payload = {
        "schema": 1,
        "status": "FAIL" if missing else "PASS",
        "reason": "REQUIRED_MODULE_WARNING" if missing else None,
        "required_missing_modules": missing,
        "warning_file_bytes": len(raw),
        "warning_file_sha256": _sha256(warn_file),
    }
    _atomic_json(evidence_file, payload)
    return int(bool(missing))


def _safe_relative(root: Path, raw: object, *, field: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError(f"{field} is not a relative path")
    candidate = (root / raw).resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"{field} escapes the experiment root")
    return candidate


def _selected_path(experiment_root: Path, generation_root: Path, raw: object, *, field: str) -> Path:
    candidate = _safe_relative(experiment_root, raw, field=field)
    if candidate != generation_root and generation_root not in candidate.parents:
        raise ValueError(f"{field} does not belong to the requested generation")
    return candidate


def _result_report_path(
    experiment_root: Path,
    generation_root: Path,
    raw: object,
    *,
    field: str,
) -> Path:
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise ValueError(f"result.{field} is not an absolute path")
    candidate = Path(raw).resolve(strict=True)
    if candidate != generation_root and generation_root not in candidate.parents:
        raise ValueError(f"result.{field} does not belong to the requested generation")
    if experiment_root not in candidate.parents:
        raise ValueError(f"result.{field} escapes the experiment root")
    return candidate


def validate_report_evidence(data_dir: Path, experiment_id: str, generation_id: str) -> dict[str, Any]:
    """Validate result, selected manifest, artifact hashes, and DOCX structure."""

    data_dir = data_dir.resolve(strict=True)
    result_path = data_dir / "reporting" / "results" / f"experiment-{generation_id}.json"
    if not result_path.is_file() or result_path.stat().st_size > _RESULT_LIMIT:
        raise ValueError("bounded result.json is missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if set(result) != {
        "schema",
        "ok",
        "generation_id",
        "report",
        "error_code",
        "error_text",
    }:
        raise ValueError("result.json schema is invalid")
    if result["schema"] != 1 or result["ok"] is not True or result["generation_id"] != generation_id:
        raise ValueError("result.json does not prove the requested generation")
    if result["error_code"] is not None or result["error_text"] != "":
        raise ValueError("successful result.json contains error fields")

    experiment_root = (data_dir / "experiments" / experiment_id).resolve(strict=True)
    generation_root = (experiment_root / "reports" / "generations" / generation_id).resolve(strict=True)
    if not generation_root.is_dir():
        raise ValueError("requested generation directory is missing")
    manifest_path = experiment_root / "reports" / "current_report.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > _RESULT_LIMIT:
        raise ValueError("current_report.json is missing or oversized")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {
        "schema",
        "experiment_id",
        "generation_id",
        "source_fingerprint",
        "created_at",
        "report",
        "artifacts",
    }:
        raise ValueError("manifest schema is invalid")
    if manifest["schema"] != 1 or manifest["experiment_id"] != experiment_id:
        raise ValueError("manifest experiment authority is invalid")
    if manifest["generation_id"] != generation_id:
        raise ValueError("manifest did not select the requested generation")
    report = manifest["report"]
    report_fields = {"docx_path", "pdf_path", "assets_dir", "sections", "skipped", "reason"}
    if not isinstance(report, dict) or set(report) != report_fields:
        raise ValueError("manifest report schema is invalid")
    if report.get("skipped") is not False:
        raise ValueError("report was skipped")
    if not isinstance(report["sections"], list) or not all(isinstance(section, str) for section in report["sections"]):
        raise ValueError("manifest report sections are invalid")
    if not isinstance(report["reason"], str):
        raise ValueError("manifest report reason is invalid")
    docx = _selected_path(
        experiment_root,
        generation_root,
        report.get("docx_path"),
        field="docx_path",
    )
    assets = _selected_path(
        experiment_root,
        generation_root,
        report.get("assets_dir"),
        field="assets_dir",
    )
    if not docx.is_file() or not assets.is_dir():
        raise ValueError("manifest report artifacts are missing")
    pdf: Path | None = None
    if report.get("pdf_path") is not None:
        pdf = _selected_path(
            experiment_root,
            generation_root,
            report["pdf_path"],
            field="pdf_path",
        )
        if not pdf.is_file():
            raise ValueError("manifest PDF path is missing")

    result_report = result["report"]
    if not isinstance(result_report, dict) or set(result_report) != report_fields:
        raise ValueError("result report schema is invalid")
    result_docx = _result_report_path(
        experiment_root,
        generation_root,
        result_report["docx_path"],
        field="docx_path",
    )
    result_assets = _result_report_path(
        experiment_root,
        generation_root,
        result_report["assets_dir"],
        field="assets_dir",
    )
    result_pdf = None
    if result_report["pdf_path"] is not None:
        result_pdf = _result_report_path(
            experiment_root,
            generation_root,
            result_report["pdf_path"],
            field="pdf_path",
        )
    if (
        result_docx != docx
        or result_assets != assets
        or result_pdf != pdf
        or result_report["sections"] != report["sections"]
        or result_report["skipped"] is not report["skipped"]
        or result_report["reason"] != report["reason"]
    ):
        raise ValueError("result report does not match the selected manifest")
    with zipfile.ZipFile(docx) as archive:
        corrupt = archive.testzip()
        names = set(archive.namelist())
    if corrupt is not None or not {"[Content_Types].xml", "word/document.xml"} <= names:
        raise ValueError("DOCX is not a valid Office ZIP document")

    checked: list[dict[str, object]] = []
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("manifest contains no artifact evidence")
    records: dict[str, dict[str, object]] = {}
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}:
            raise ValueError("artifact record schema is invalid")
        relative = record["path"]
        if not isinstance(relative, str):
            raise ValueError("artifact record path is invalid")
        if relative in records:
            raise ValueError("artifact record path is duplicated")
        if type(record["size"]) is not int or record["size"] < 0:
            raise ValueError("artifact record size is invalid")
        if not isinstance(record["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None:
            raise ValueError("artifact record hash is invalid")
        path = _safe_relative(generation_root, relative, field="artifact.path")
        size = path.stat().st_size
        digest = _sha256(path)
        if size != record["size"] or digest != record["sha256"]:
            raise ValueError("artifact hash or size mismatch")
        checked_record = {"path": relative, "size": size, "sha256": digest}
        records[relative] = checked_record
        checked.append(checked_record)

    actual_files: set[str] = set()
    for path in generation_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("requested generation contains a symlink")
        if path.is_file():
            actual_files.add(path.relative_to(generation_root).as_posix())
    if set(records) != actual_files:
        raise ValueError("artifact inventory does not exactly cover the selected generation")

    selected_files = {docx.relative_to(generation_root).as_posix(), "result.json"}
    if pdf is not None:
        selected_files.add(pdf.relative_to(generation_root).as_posix())
    if not selected_files <= records.keys():
        raise ValueError("selected report files are absent from the artifact inventory")
    generation_result = generation_root / "result.json"
    if generation_result.stat().st_size > _RESULT_LIMIT:
        raise ValueError("generation result.json is oversized")
    if json.loads(generation_result.read_text(encoding="utf-8")) != result:
        raise ValueError("external result.json does not match the selected generation")
    return {
        "result_path": result_path.relative_to(data_dir).as_posix(),
        "result_sha256": _sha256(result_path),
        "manifest_path": manifest_path.relative_to(data_dir).as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "docx_path": docx.relative_to(data_dir).as_posix(),
        "docx_sha256": _sha256(docx),
        "pdf_path": pdf.relative_to(data_dir).as_posix() if pdf is not None else None,
        "generation_id": generation_id,
        "artifacts": checked,
    }


def _seed_experiment(data_dir: Path, experiment_id: str) -> None:
    root = data_dir / "experiments" / experiment_id
    root.mkdir(parents=True, exist_ok=False)
    metadata = {
        "schema_version": 1,
        "experiment": {
            "experiment_id": experiment_id,
            "name": "Windows ONEDIR — Кириллица",
            "title": "Windows ONEDIR — Кириллица",
            "operator": "CI",
            "sample": "deterministic fixture",
            "status": "COMPLETED",
            "start_time": "2026-07-10T12:00:00+00:00",
            "end_time": "2026-07-10T12:05:00+00:00",
            "report_enabled": True,
            "retroactive": False,
        },
        "template": {
            "id": "windows_onedir_smoke",
            "name": "Windows ONEDIR smoke",
            "report_enabled": True,
            "report_sections": [],
        },
        "artifact_index": [],
        "result_tables": [],
        "run_records": [],
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def frozen_report_command(executable: Path, experiment_id: str, generation_id: str) -> list[str]:
    if executable.name.lower() != "cryodaq.exe":
        raise ValueError("smoke target must be CryoDAQ.exe")
    return [
        str(executable),
        "--mode=report-render",
        "experiment",
        f"--experiment-id={experiment_id}",
        f"--generation-id={generation_id}",
        f"--deadline-epoch={time.time() + 45:.6f}",
    ]


def _write_log(evidence_dir: Path, name: str, completed: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    stdout = evidence_dir / f"{name}.stdout.log"
    stderr = evidence_dir / f"{name}.stderr.log"
    stdout.write_bytes(completed.stdout[-1024 * 1024 :])
    stderr.write_bytes(completed.stderr[-1024 * 1024 :])
    return {
        "returncode": completed.returncode,
        "stdout": stdout.name,
        "stdout_sha256": _sha256(stdout),
        "stderr": stderr.name,
        "stderr_sha256": _sha256(stderr),
    }


def _run_report_cell(
    executable: Path,
    root: Path,
    evidence_dir: Path,
    *,
    name: str,
    experiment_id: str,
    generation_id: str,
    extra_env: dict[str, str] | None = None,
    timeout: float = 70.0,
) -> dict[str, Any]:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    _seed_experiment(data_dir, experiment_id)
    command = frozen_report_command(executable, experiment_id, generation_id)
    env = os.environ.copy()
    env.update(
        {
            "CRYODAQ_ROOT": str(root),
            "CRYODAQ_REPORT_DATA_DIR": str(data_dir),
            "MPLBACKEND": "Agg",
            "PYTHONUTF8": "1",
        }
    )
    if extra_env:
        env.update(extra_env)
    started = time.monotonic()
    completed = subprocess.run(command, env=env, capture_output=True, timeout=timeout, check=False)
    logs = _write_log(evidence_dir, name, completed)
    if completed.returncode != 0:
        raise RuntimeError(f"{name} returned {completed.returncode}")
    validation = validate_report_evidence(data_dir, experiment_id, generation_id)
    return {
        "name": name,
        "status": "PASS",
        "duration_s": round(time.monotonic() - started, 3),
        "argv": command,
        "runtime": logs,
        "validation": validation,
    }


def _pid_exists(pid: int) -> bool:
    if os.name != "nt" or pid <= 0:
        return False
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and f'"{pid}"' in completed.stdout


def _run_job_timeout_cell(executable: Path, root: Path, evidence_dir: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"name": "windows_job_timeout", "status": "NOT_RUN", "reason": "WINDOWS_REQUIRED"}
    data_dir = root / "data-timeout"
    data_dir.mkdir()
    _seed_experiment(data_dir, "exp-timeout")
    fake_bin = root / "fake soffice bin"
    fake_bin.mkdir()
    # Keep the command payload ASCII-only so cmd.exe's active code page cannot
    # corrupt the evidence path before PowerShell receives it.
    nested_pid_file = evidence_dir / "nested-soffice.pid"
    script = fake_bin / "soffice.cmd"
    escaped_pid = str(nested_pid_file).replace("'", "''")
    script.write_text(
        "@echo off\r\n"
        'powershell -NoProfile -Command "'
        "$p=Start-Process powershell -ArgumentList '-NoProfile','-Command','Start-Sleep 300' -PassThru; "
        f"Set-Content -LiteralPath '{escaped_pid}' -Value $p.Id -Encoding ascii; "
        'Start-Sleep 300"\r\n',
        encoding="utf-8",
    )
    generation = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    command = frozen_report_command(executable, "exp-timeout", generation)
    # Leave only a short child deadline so ReportGenerator must terminate the
    # fake soffice tree and degrade to DOCX-only.
    command[-1] = f"--deadline-epoch={time.time() + 10:.6f}"
    env = os.environ.copy()
    env.update(
        {
            "CRYODAQ_ROOT": str(root),
            "CRYODAQ_REPORT_DATA_DIR": str(data_dir),
            "MPLBACKEND": "Agg",
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "PYTHONUTF8": "1",
        }
    )
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    job: Any = None
    try:
        # Exercise the installed production Job Object implementation while
        # the process placed in it is always the built CryoDAQ.exe.
        from cryodaq.report_process import _create_windows_job

        job = _create_windows_job(process)
        stdout, stderr = process.communicate(timeout=35)
    except BaseException:
        if job is not None:
            job.close()
        with suppress(Exception):
            process.kill()
        with suppress(Exception):
            process.wait(timeout=5)
        raise
    finally:
        if job is not None:
            job.close()
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    logs = _write_log(evidence_dir, "windows_job_timeout", completed)
    if completed.returncode != 0 or not nested_pid_file.is_file():
        raise RuntimeError("timeout fixture did not execute through the built EXE")
    nested_pid = int(nested_pid_file.read_text(encoding="ascii").strip())
    deadline = time.monotonic() + 5
    while _pid_exists(nested_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_exists(nested_pid):
        raise RuntimeError("nested fake soffice descendant survived timeout cleanup")
    validation = validate_report_evidence(data_dir, "exp-timeout", generation)
    if validation["pdf_path"] is not None:
        raise RuntimeError("timeout degradation unexpectedly selected a PDF")
    return {
        "name": "windows_job_timeout",
        "status": "PASS",
        "duration_s": round(time.monotonic() - started, 3),
        "argv": command,
        "job_object_assigned": True,
        "nested_pid": nested_pid,
        "nested_pid_gone": True,
        "runtime": logs,
        "validation": validation,
    }


def _assistant_config(root: Path, *, agent: str | None, automatic: bool) -> None:
    config = root / "config"
    config.mkdir(exist_ok=True)
    if agent is not None:
        (config / "agent.yaml").write_text(
            f"agent:\n  enabled: {agent}\nreporting:\n  automatic_enabled: {'true' if automatic else 'false'}\n",
            encoding="utf-8",
        )
    else:
        with suppress(FileNotFoundError):
            (config / "agent.yaml").unlink()
        (config / "reporting.yaml").write_text(
            f"reporting:\n  automatic_enabled: {'true' if automatic else 'false'}\n",
            encoding="utf-8",
        )


def _write_periodic_config(root: Path, token: str) -> None:
    (root / "config" / "notifications.yaml").write_text(
        "telegram:\n"
        f"  bot_token: '{token}'\n"
        "  chat_id: -100123\n"
        "  timeout_s: 10\n"
        "  verify_ssl: true\n"
        "  send_cleared: true\n"
        "periodic_report:\n"
        "  enabled: true\n"
        "  report_interval_s: 3600\n"
        "commands:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )


def _run_assistant_cell(
    executable: Path,
    root: Path,
    evidence_dir: Path,
    *,
    name: str,
    experiment_mode: str,
    periodic_mode: str,
    agent: str | None,
    automatic: bool,
    expect_periodic_state: bool = False,
    forbidden_text: str | None = None,
) -> dict[str, Any]:
    _assistant_config(root, agent=agent, automatic=automatic)
    state_path = root / "data" / "reporting" / "periodic_state.json"
    assistant_log = root / "logs" / "assistant.log"
    with suppress(FileNotFoundError):
        state_path.unlink()
    with suppress(FileNotFoundError):
        assistant_log.unlink()
    command = [str(executable), "--mode=assistant"]
    env = os.environ.copy()
    env.update(
        {
            "CRYODAQ_ROOT": str(root),
            "CRYODAQ_ASSISTANT_EXPERIMENT_MODE": experiment_mode,
            "CRYODAQ_ASSISTANT_PERIODIC_MODE": periodic_mode,
            "PYTHONUTF8": "1",
        }
    )
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    observed_periodic_health: tuple[str, str] | None = None
    try:
        stable_until = time.monotonic() + (15 if expect_periodic_state else 5)
        while time.monotonic() < stable_until:
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited before readiness observation")
            if expect_periodic_state and state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    health = state.get("health") if isinstance(state, dict) else None
                    candidate = (health.get("status"), health.get("error_code")) if isinstance(health, dict) else None
                    if candidate == _H3_ALLOWED_IDLE_HEALTH:
                        observed_periodic_health = _H3_ALLOWED_IDLE_HEALTH
                        break
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
            time.sleep(0.1)
        if expect_periodic_state and observed_periodic_health is None:
            raise RuntimeError("H3-only assistant did not publish exact allowed-idle health")
        if not expect_periodic_state and state_path.exists():
            raise RuntimeError("exact-off assistant unexpectedly created H3 state")
        process.send_signal(signal.CTRL_BREAK_EVENT)
        stdout, stderr = process.communicate(timeout=20)
    except BaseException:
        with suppress(Exception):
            process.terminate()
        with suppress(Exception):
            process.wait(timeout=5)
        raise
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    file_log = assistant_log.read_bytes() if assistant_log.is_file() else b""
    combined_log = stdout + stderr + file_log
    if forbidden_text is not None and forbidden_text.encode() in combined_log:
        raise RuntimeError(f"{name} exposed forbidden configuration text")
    if b"Traceback (most recent call last)" in combined_log or b"CRITICAL" in combined_log:
        raise RuntimeError(f"{name} emitted an unexpected fatal log")
    logs = _write_log(evidence_dir, name, completed)
    assistant_log_evidence = evidence_dir / f"{name}.assistant.log"
    assistant_log_evidence.write_bytes(file_log[-1024 * 1024 :])
    logs.update(
        {
            "assistant_log": assistant_log_evidence.name,
            "assistant_log_sha256": _sha256(assistant_log_evidence),
        }
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{name} shutdown returned {completed.returncode}")
    if _pid_exists(process.pid):
        raise RuntimeError(f"{name} process remained after shutdown")
    state_summary: dict[str, object] | None = None
    if expect_periodic_state:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        health = state.get("health") if isinstance(state, dict) else None
        if not isinstance(health, dict) or (health.get("status"), health.get("error_code")) != (
            "stopped",
            "periodic_stopped",
        ):
            raise RuntimeError("H3-only assistant persisted invalid shutdown health")
        state_summary = {
            "startup_status": observed_periodic_health[0],
            "startup_error_code": observed_periodic_health[1],
            "shutdown_status": health["status"],
            "shutdown_error_code": health["error_code"],
            "state_sha256": _sha256(state_path),
        }
    return {
        "name": name,
        "status": "PASS",
        "duration_s": round(time.monotonic() - started, 3),
        "argv": command,
        "ctrl_break_clean_exit": True,
        "pid": process.pid,
        "pid_gone": True,
        "runtime": logs,
        "periodic_state": state_summary,
    }


def _artifact_inventory(dist_dir: Path) -> dict[str, object]:
    tree = hashlib.sha256()
    critical: list[dict[str, object]] = []
    total = 0
    count = 0
    for path in sorted(item for item in dist_dir.rglob("*") if item.is_file()):
        count += 1
        size = path.stat().st_size
        total += size
        relative = path.relative_to(dist_dir).as_posix()
        digest = _sha256(path)
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(str(size).encode("ascii"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\n")
        if relative in {
            "CryoDAQ.exe",
            "README_OPERATOR.txt",
            "config/agent.yaml",
            "config/notifications.yaml",
        }:
            critical.append({"path": relative, "size": size, "sha256": digest})
    return {
        "schema": 1,
        "file_count": count,
        "total_bytes": total,
        "tree_sha256": tree.hexdigest(),
        "critical_files": critical,
    }


def smoke_summary(cells: list[dict[str, Any]]) -> tuple[str, str | None]:
    """Fail closed on every failed or unexecuted required cell."""

    statuses = [cell.get("status") for cell in cells]
    if "FAIL" in statuses:
        return "FAIL", "CELL_FAILED"
    if "NOT_RUN" in statuses:
        return "FAIL", "REQUIRED_CELLS_NOT_RUN"
    if not cells or any(status != "PASS" for status in statuses):
        return "FAIL", "INVALID_CELL_STATUS"
    return "PASS", None


def run_smoke(dist_dir: Path, evidence_dir: Path) -> int:
    evidence_dir = evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result_path = evidence_dir / "smoke-result.json"
    cells: list[dict[str, Any]] = []
    status = "FAIL"
    reason: str | None = None
    try:
        if os.name != "nt":
            raise RuntimeError("WINDOWS_REQUIRED")
        dist_dir = dist_dir.resolve(strict=True)
        source_exe = dist_dir / "CryoDAQ.exe"
        if not source_exe.is_file():
            raise RuntimeError("BUILT_EXE_MISSING")
        runtime_root = evidence_dir.parent / "windows smoke runtime path with spaces" / "КриоДАК"
        if runtime_root.exists():
            shutil.rmtree(runtime_root)
        shutil.copytree(dist_dir, runtime_root)
        executable = runtime_root / "CryoDAQ.exe"
        if executable.resolve() == source_exe.resolve():
            raise RuntimeError("UNICODE_COPY_NOT_USED")

        cells.append(
            _run_report_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="report_render_unicode",
                experiment_id="exp-onedir",
                generation_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )
        cells.append(_run_job_timeout_cell(executable, runtime_root, evidence_dir))

        # H2 works independently with both an explicit LLM-off config and a
        # missing optional agent config.  The event SUB socket may be idle.
        cells.append(
            _run_assistant_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="assistant_h2_agent_off",
                experiment_mode="1",
                periodic_mode="0",
                agent="false",
                automatic=True,
            )
        )
        cells.append(
            _run_assistant_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="assistant_h2_agent_missing",
                experiment_mode="1",
                periodic_mode="0",
                agent=None,
                automatic=True,
            )
        )

        cells.append(
            _run_assistant_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="assistant_replay_exact_off",
                experiment_mode="0",
                periodic_mode="0",
                agent="false",
                automatic=False,
            )
        )

        # A valid synthetic config loads the complete frozen H3 stack.  No
        # engine publisher is present, so bounded non-ready durable health is
        # the expected allowed-idle outcome and no Telegram request is attempted.
        synthetic_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
        _write_periodic_config(runtime_root, synthetic_token)
        cells.append(
            _run_assistant_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="assistant_h3_only_allowed_idle",
                experiment_mode="0",
                periodic_mode="1",
                agent="false",
                automatic=False,
                expect_periodic_state=True,
                forbidden_text=synthetic_token,
            )
        )
        # Reacquiring the durable leader and publishing health in the same
        # root proves the first frozen assistant released its kernel lock.
        cells.append(
            _run_assistant_cell(
                executable,
                runtime_root,
                evidence_dir,
                name="assistant_h3_only_restart_lock_release",
                experiment_mode="0",
                periodic_mode="1",
                agent="false",
                automatic=False,
                expect_periodic_state=True,
                forbidden_text=synthetic_token,
            )
        )

        inventory = _artifact_inventory(dist_dir)
        _atomic_json(evidence_dir / "artifact-hashes.json", inventory)
        status, reason = smoke_summary(cells)
    except BaseException as exc:
        reason = f"{type(exc).__name__}:{str(exc)[:512]}"
    finally:
        runtime_parent = evidence_dir.parent / "windows smoke runtime path with spaces"
        if runtime_parent.exists():
            shutil.rmtree(runtime_parent, ignore_errors=True)
    payload = {
        "schema": 1,
        "status": status,
        "reason": reason,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "dist_dir": str(dist_dir),
        "cells": cells,
    }
    _atomic_json(result_path, payload)
    return 0 if status == "PASS" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    warnings = commands.add_parser("check-warnings", allow_abbrev=False)
    warnings.add_argument("--warn-file", required=True, type=Path)
    warnings.add_argument("--evidence-file", required=True, type=Path)
    smoke = commands.add_parser("smoke", allow_abbrev=False)
    smoke.add_argument("--dist-dir", required=True, type=Path)
    smoke.add_argument("--evidence-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check-warnings":
        return check_warnings(args.warn_file, args.evidence_file)
    return run_smoke(args.dist_dir, args.evidence_dir)


if __name__ == "__main__":
    raise SystemExit(main())
