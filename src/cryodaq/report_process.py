"""Standard-library-only parent-side report subprocess runner.

The engine imports this module instead of the heavy renderer stack. Commands
are fixed argv lists, results are bounded JSON files, and timeout cleanup owns
the complete child process group/tree.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cryodaq.report_state import (
    MAX_JSON_BYTES,
    ReportContractError,
    load_current_manifest,
    resolve_experiment_dir,
    validate_experiment_id,
    validate_generation_id,
)

DEFAULT_MANUAL_TIMEOUT_S = 48.0
_RESULT_SCHEMA = 1
_REPORT_FIELDS = {"docx_path", "pdf_path", "assets_dir", "sections", "skipped", "reason"}


class ReportProcessError(RuntimeError):
    """A bounded report child failed, timed out, or violated its result contract."""


def build_report_command(
    experiment_id: str,
    generation_id: str,
    *,
    deadline_epoch: float,
    automatic: bool = False,
) -> list[str]:
    """Build the fixed development or frozen experiment-render argv."""
    validate_experiment_id(experiment_id)
    validate_generation_id(generation_id)
    suffix = [
        "experiment",
        f"--experiment-id={experiment_id}",
        f"--generation-id={generation_id}",
        f"--deadline-epoch={deadline_epoch:.6f}",
    ]
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--mode=report-render", *suffix]
    else:
        command = [sys.executable, "-m", "cryodaq.reporting", *suffix]
    if automatic:
        command.append("--automatic")
    return command


def result_file_path(data_dir: Path, generation_id: str) -> Path:
    validate_generation_id(generation_id)
    root = Path(data_dir).resolve()
    reporting = root / "reporting"
    results = reporting / "results"
    if reporting.is_symlink() or results.is_symlink():
        raise ReportProcessError("report result directory must not be a symlink")
    results.mkdir(parents=True, exist_ok=True)
    resolved_results = results.resolve()
    if root != resolved_results and root not in resolved_results.parents:
        raise ReportProcessError("report result directory escapes the data root")
    return resolved_results / f"experiment-{generation_id}.json"


def _validate_report_payload(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) != _REPORT_FIELDS:
        raise ReportProcessError("report child returned an invalid report object")
    if not isinstance(report["docx_path"], str) or not isinstance(report["assets_dir"], str):
        raise ReportProcessError("report child returned invalid artifact paths")
    if report["pdf_path"] is not None and not isinstance(report["pdf_path"], str):
        raise ReportProcessError("report child returned invalid pdf_path")
    if not isinstance(report["sections"], list) or not all(
        isinstance(item, str) and len(item) <= 128 for item in report["sections"]
    ):
        raise ReportProcessError("report child returned invalid sections")
    if type(report["skipped"]) is not bool or not isinstance(report["reason"], str):
        raise ReportProcessError("report child returned invalid status fields")
    if len(report["reason"]) > 2_048:
        raise ReportProcessError("report child reason is too long")
    return dict(report)


def read_result_file(path: Path) -> dict[str, Any]:
    """Read and validate one size-bounded child result file."""
    if path.is_symlink() or not path.is_file():
        raise ReportProcessError("report child did not create a regular result file")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ReportProcessError("report child result is too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportProcessError("report child result is invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "ok",
        "generation_id",
        "report",
        "error_code",
        "error_text",
    }:
        raise ReportProcessError("report child result has an invalid schema")
    if type(payload["schema"]) is not int or payload["schema"] != _RESULT_SCHEMA or type(payload["ok"]) is not bool:
        raise ReportProcessError("report child result has an unsupported schema")
    try:
        validate_generation_id(payload["generation_id"])
    except ReportContractError as exc:
        raise ReportProcessError("report child returned invalid generation_id") from exc
    if payload["ok"]:
        payload["report"] = _validate_report_payload(payload["report"])
        if payload["error_code"] is not None or payload["error_text"] != "":
            raise ReportProcessError("successful report child returned error fields")
    else:
        if payload["report"] is not None:
            raise ReportProcessError("failed report child returned a report object")
        if not isinstance(payload["error_code"], str) or not isinstance(payload["error_text"], str):
            raise ReportProcessError("failed report child returned invalid error fields")
        if len(payload["error_code"]) > 128 or len(payload["error_text"]) > 2_048:
            raise ReportProcessError("report child error fields are too long")
    return payload


def terminate_process_tree(pid: int, *, grace_s: float = 1.0) -> None:
    """Terminate a report process tree using the platform's tree primitive."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1.0, grace_s + 1.0),
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + max(0.0, grace_s)
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.02)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def terminate_descendant_tree(pid: int, *, grace_s: float = 1.0) -> None:
    """Terminate one nested process and descendants without killing its parent group."""
    if os.name == "nt":
        terminate_process_tree(pid, grace_s=grace_s)
        return
    ps = Path("/bin/ps")
    if not ps.exists():
        ps = Path("/usr/bin/ps")
    descendants: list[int] = []
    try:
        completed = subprocess.run(
            [str(ps), "-axo", "pid=,ppid="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        children: dict[int, list[int]] = {}
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            child, parent = (int(field) for field in fields)
            children.setdefault(parent, []).append(child)
        stack = list(children.get(pid, []))
        while stack:
            child = stack.pop()
            descendants.append(child)
            stack.extend(children.get(child, []))
    except (OSError, subprocess.SubprocessError, ValueError):
        descendants = []
    targets = [*reversed(descendants), pid]
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if grace_s > 0:
        time.sleep(grace_s)
    for target in targets:
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _creation_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class _WindowsJob:
    """Kill-on-close Windows Job Object containing a report child tree."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "SetInformationJobObject failed")
        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(job, process_handle):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "AssignProcessToJobObject failed")
        self._kernel32 = kernel32
        self._handle = job

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _create_windows_job(process: subprocess.Popen[Any]) -> _WindowsJob:
    return _WindowsJob(process)


class ReportProcessRunner:
    """Run one synchronous manual report child within the REP budget."""

    def __init__(
        self,
        data_dir: Path,
        *,
        timeout_s: float = DEFAULT_MANUAL_TIMEOUT_S,
    ) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._timeout_s = float(timeout_s)
        if not (0.05 <= self._timeout_s <= 3_600.0):
            raise ValueError("report timeout must be between 0.05 and 3600 seconds")

    def _run_process(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> int:
        process = subprocess.Popen(
            list(command),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=dict(env) if env is not None else None,
            **_creation_kwargs(),
        )
        windows_job: _WindowsJob | None = None
        if os.name == "nt":
            # CPython exposes the process handle only after CreateProcess has
            # started it, so there is a small Popen-to-assignment window. The
            # child/package import path is intentionally side-effect-free and
            # cannot spawn descendants before main. Assignment failure is
            # handled fail-closed below.
            try:
                windows_job = _create_windows_job(process)
            except Exception as exc:
                try:
                    terminate_process_tree(process.pid)
                except Exception:
                    # taskkill itself can time out or fail. The process handle
                    # remains our final cleanup authority below.
                    pass
                try:
                    process.wait(timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=2.0)
                    except Exception as cleanup_exc:
                        raise ReportProcessError(
                            "report child cleanup failed after Windows Job Object assignment failure"
                        ) from cleanup_exc
                raise ReportProcessError("report child could not be assigned to a Windows Job Object") from exc
        timed_out = False
        try:
            return_code = process.wait(timeout=self._timeout_s)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            if windows_job is not None:
                windows_job.close()
            else:
                terminate_process_tree(process.pid)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            raise ReportProcessError(f"report child timed out after {self._timeout_s:g}s") from exc
        finally:
            # A renderer may exit after orphaning a nested soffice process.
            # On POSIX the child owns a dedicated session/process group, so a
            # final group cleanup is safe even after the leader has exited.
            if os.name != "nt" and not timed_out:
                terminate_process_tree(process.pid, grace_s=0.1)
            if windows_job is not None:
                windows_job.close()
        return return_code

    def generate_experiment(
        self,
        experiment_id: str,
        *,
        automatic: bool = False,
    ) -> dict[str, Any]:
        """Render one experiment and return the exact legacy report mapping."""
        experiment_root = resolve_experiment_dir(self._data_dir, experiment_id)
        generation_id = secrets.token_hex(16)
        validate_generation_id(generation_id)
        result_path = result_file_path(self._data_dir, generation_id)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.is_symlink():
            raise ReportProcessError("unsafe report result path")
        result_path.unlink(missing_ok=True)
        deadline_epoch = time.time() + self._timeout_s
        command = build_report_command(
            experiment_id,
            generation_id,
            deadline_epoch=deadline_epoch,
            automatic=automatic,
        )
        env = os.environ.copy()
        env["CRYODAQ_REPORT_DATA_DIR"] = str(self._data_dir)
        recovered_committed_manifest = False
        try:
            return_code = self._run_process(command, env=env)
            manifest = None
            try:
                manifest = load_current_manifest(experiment_root)
            except (OSError, ReportContractError):
                # A damaged or unreadable manifest has no recovery authority.
                # Preserve the child's ordinary result/exit failure below.
                pass
            if return_code != 0 and manifest is not None and manifest["generation_id"] == generation_id:
                recovered_committed_manifest = True
                report = manifest["report"]
                payload = {
                    "schema": _RESULT_SCHEMA,
                    "ok": True,
                    "generation_id": generation_id,
                    "report": {
                        "docx_path": str(experiment_root / report["docx_path"]),
                        "pdf_path": (
                            str(experiment_root / report["pdf_path"]) if report["pdf_path"] is not None else None
                        ),
                        "assets_dir": str(experiment_root / report["assets_dir"]),
                        "sections": list(report["sections"]),
                        "skipped": bool(report["skipped"]),
                        "reason": str(report["reason"]),
                    },
                    "error_code": None,
                    "error_text": "",
                }
            else:
                try:
                    payload = read_result_file(result_path)
                except ReportProcessError:
                    if manifest is None or manifest["generation_id"] != generation_id:
                        raise
                    recovered_committed_manifest = True
                    report = manifest["report"]
                    payload = {
                        "schema": _RESULT_SCHEMA,
                        "ok": True,
                        "generation_id": generation_id,
                        "report": {
                            "docx_path": str(experiment_root / report["docx_path"]),
                            "pdf_path": (
                                str(experiment_root / report["pdf_path"]) if report["pdf_path"] is not None else None
                            ),
                            "assets_dir": str(experiment_root / report["assets_dir"]),
                            "sections": list(report["sections"]),
                            "skipped": bool(report["skipped"]),
                            "reason": str(report["reason"]),
                        },
                        "error_code": None,
                        "error_text": "",
                    }
        finally:
            result_path.unlink(missing_ok=True)
        if (return_code != 0 and not recovered_committed_manifest) or not payload["ok"]:
            code = payload.get("error_code") or f"exit_{return_code}"
            text = payload.get("error_text") or "report child failed"
            raise ReportProcessError(f"{code}: {text}")
        if payload["generation_id"] != generation_id:
            raise ReportProcessError("report child generation mismatch")
        manifest = load_current_manifest(experiment_root)
        if manifest is None or manifest["generation_id"] != generation_id:
            raise ReportProcessError("report child did not select its immutable generation")
        expected = manifest["report"]
        report = payload["report"]
        expected_paths = {
            "docx_path": str(experiment_root / expected["docx_path"]),
            "pdf_path": (str(experiment_root / expected["pdf_path"]) if expected["pdf_path"] is not None else None),
            "assets_dir": str(experiment_root / expected["assets_dir"]),
        }
        for field, expected_value in expected_paths.items():
            if report[field] != expected_value:
                raise ReportProcessError(f"report child returned untrusted {field}")
        return report
