"""Run registry-selected tests that require the exact Git checkout."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any

import psutil
import yaml

from tools.check_python_compile import compile_python_tree
from tools.ci_candidate_evidence import FAILURE_RECEIPT_INDEX_ENV, FAILURE_RECEIPT_SUITE_ENV
from tools.ci_candidate_runner import (
    _TAIL,
    _candidate_authority_environment,
    _protected_pytest_command,
    _strict_guard_command,
    _validate_strict_guard_receipt,
)
from tools.ci_guard_execution import active_guard_specs, checkout_execution_selection, current_guard_platform

# The sealed candidate disables autoload; this checkout runner must not reuse its explicit plugin list.
_PYTEST = (sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ZERO_SHA = "0" * 40
_REGISTRY = PurePosixPath("governance/agent_preventions.yaml")
_REPRODUCTIONS = PurePosixPath("governance/red_reproductions")


class RedReproductionComparisonError(RuntimeError):
    """The candidate did not retain a trusted-base evidence binding."""


class CandidateProcessSettlementError(RuntimeError):
    """A candidate process boundary could not be created or fully settled."""


_POSIX_BOUNDARY_LOCK = threading.Lock()
_POSIX_BOUNDARY_POISONED = False
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37


class _LinuxSubreaperBoundary:
    """Own candidate descendants in the kernel until all have been reaped."""

    def __init__(self) -> None:
        self._libc: Any = None
        self._prior_subreaper = 0
        self._baseline_children: set[tuple[int, float]] = set()
        self._known: dict[int, float] = {}
        self._root_pid: int | None = None
        self._settled = False
        self._opened = False
        self._changed_subreaper = False

    @staticmethod
    def _identity(process: psutil.Process) -> tuple[int, float]:
        try:
            return process.pid, process.create_time()
        except psutil.AccessDenied as exc:
            raise CandidateProcessSettlementError("candidate process identity could not be established") from exc

    def _subreaper_state(self) -> bool:
        observed = ctypes.c_int()
        if self._libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(observed), 0, 0, 0) != 0:
            raise CandidateProcessSettlementError(f"PR_GET_CHILD_SUBREAPER failed: {ctypes.get_errno()}")
        if observed.value not in (0, 1):
            raise CandidateProcessSettlementError("Linux returned an invalid child-subreaper state")
        return bool(observed.value)

    def _set_subreaper(self, enabled: bool) -> None:
        if self._libc.prctl(_PR_SET_CHILD_SUBREAPER, int(enabled), 0, 0, 0) != 0:
            raise CandidateProcessSettlementError(f"PR_SET_CHILD_SUBREAPER failed: {ctypes.get_errno()}")
        if self._subreaper_state() is not enabled:
            raise CandidateProcessSettlementError("Linux child-subreaper state change was not verified")

    def open(self) -> None:
        global _POSIX_BOUNDARY_POISONED

        if os.name == "nt" or sys.platform != "linux":
            raise CandidateProcessSettlementError("protected candidate execution requires Linux subreaper support")
        _POSIX_BOUNDARY_LOCK.acquire()
        try:
            if _POSIX_BOUNDARY_POISONED:
                raise CandidateProcessSettlementError("Linux subreaper boundary was poisoned by failed settlement")
            self._libc = ctypes.CDLL(None, use_errno=True)
            self._prior_subreaper = int(self._subreaper_state())
            self._changed_subreaper = not bool(self._prior_subreaper)
            if self._changed_subreaper:
                self._set_subreaper(True)
            owner = psutil.Process(os.getpid())
            for child in owner.children(recursive=False):
                try:
                    self._baseline_children.add(self._identity(child))
                except psutil.NoSuchProcess:
                    continue
            self._opened = True
        except BaseException:
            if self._changed_subreaper:
                try:
                    self._set_subreaper(False)
                except CandidateProcessSettlementError as rollback_exc:
                    _POSIX_BOUNDARY_POISONED = True
                    _POSIX_BOUNDARY_LOCK.release()
                    raise CandidateProcessSettlementError("subreaper setup rollback failed") from rollback_exc
            _POSIX_BOUNDARY_LOCK.release()
            raise

    def attach(self, process: subprocess.Popen[Any]) -> None:
        try:
            identity = self._identity(psutil.Process(process.pid))
        except psutil.NoSuchProcess as exc:
            raise CandidateProcessSettlementError("candidate root identity could not be established") from exc
        self._root_pid = process.pid
        self._known[process.pid] = identity[1]

    def _refresh(self) -> tuple[psutil.Process, ...]:
        try:
            direct = psutil.Process(os.getpid()).children(recursive=False)
        except psutil.AccessDenied as exc:
            raise CandidateProcessSettlementError("subreaper children could not be enumerated") from exc
        candidates: list[psutil.Process] = []
        for child in direct:
            try:
                identity = self._identity(child)
            except psutil.NoSuchProcess:
                continue
            if identity in self._baseline_children:
                continue
            candidates.append(child)
            try:
                candidates.extend(child.children(recursive=True))
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as exc:
                raise CandidateProcessSettlementError("candidate descendants could not be enumerated") from exc
        verified: dict[int, psutil.Process] = {}
        for candidate in candidates:
            try:
                pid, created = self._identity(candidate)
            except psutil.NoSuchProcess:
                continue
            prior = self._known.setdefault(pid, created)
            if prior != created:
                raise CandidateProcessSettlementError("candidate PID was reused during settlement")
            verified[pid] = candidate
        return tuple(verified.values())

    def _reap_adopted(self) -> None:
        for child in self._refresh():
            if child.pid == self._root_pid:
                continue
            try:
                if child.ppid() == os.getpid():
                    os.waitpid(child.pid, os.WNOHANG)
            except (ChildProcessError, ProcessLookupError, psutil.NoSuchProcess):
                continue
            except psutil.AccessDenied as exc:
                raise CandidateProcessSettlementError("adopted candidate child could not be reaped") from exc

    def _live(self) -> tuple[psutil.Process, ...]:
        live: list[psutil.Process] = []
        for process in self._refresh():
            try:
                if process.status() != psutil.STATUS_ZOMBIE:
                    live.append(process)
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as exc:
                raise CandidateProcessSettlementError("candidate descendant status could not be inspected") from exc
        return tuple(live)

    def settle(self, root: subprocess.Popen[Any] | None) -> None:
        for signal_to_send, grace_s in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 5.0)):
            deadline = time.monotonic() + grace_s
            while True:
                live = self._live()
                for process in live:
                    try:
                        process.send_signal(signal_to_send)
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.AccessDenied as exc:
                        raise CandidateProcessSettlementError("candidate descendant could not be terminated") from exc
                if root is not None and root.poll() is None:
                    try:
                        root.wait(timeout=0.01)
                    except subprocess.TimeoutExpired:
                        pass
                self._reap_adopted()
                if (root is None or root.poll() is not None) and not self._live():
                    self._reap_adopted()
                    if not self._refresh():
                        self._settled = True
                        return
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
        raise CandidateProcessSettlementError("candidate Linux subreaper boundary did not settle within five seconds")

    def close(self) -> None:
        global _POSIX_BOUNDARY_POISONED

        if not self._opened:
            return
        try:
            if not self._settled:
                _POSIX_BOUNDARY_POISONED = True
                raise CandidateProcessSettlementError("refusing to restore an unsettled Linux subreaper boundary")
            if self._changed_subreaper:
                try:
                    self._set_subreaper(False)
                except CandidateProcessSettlementError as exc:
                    _POSIX_BOUNDARY_POISONED = True
                    raise CandidateProcessSettlementError("subreaper restore failed") from exc
        finally:
            self._opened = False
            _POSIX_BOUNDARY_LOCK.release()


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_ulonglong),
        ("write_operation_count", ctypes.c_ulonglong),
        ("other_operation_count", ctypes.c_ulonglong),
        ("read_transfer_count", ctypes.c_ulonglong),
        ("write_transfer_count", ctypes.c_ulonglong),
        ("other_transfer_count", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", ctypes.c_ulong),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_ulong),
        ("scheduling_class", ctypes.c_ulong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


def _windows_job() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise CandidateProcessSettlementError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
    information = _ExtendedLimitInformation()
    information.basic_limit_information.limit_flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(information), ctypes.sizeof(information)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise CandidateProcessSettlementError(f"SetInformationJobObject failed: {error}")
    return int(handle)


def _assign_windows_job(handle: int, process: subprocess.Popen[Any]) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    if not kernel32.AssignProcessToJobObject(handle, ctypes.c_void_p(int(process._handle))):  # type: ignore[attr-defined]
        raise CandidateProcessSettlementError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")


def _resume_windows_process(process: subprocess.Popen[Any]) -> None:
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtResumeProcess.argtypes = (ctypes.c_void_p,)
    ntdll.NtResumeProcess.restype = ctypes.c_long
    if ntdll.NtResumeProcess(ctypes.c_void_p(int(process._handle))):  # type: ignore[attr-defined]
        raise CandidateProcessSettlementError("NtResumeProcess failed")


def _settle_windows_job(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        kernel32.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        if not kernel32.TerminateJobObject(handle, 1):
            raise CandidateProcessSettlementError(f"TerminateJobObject failed: {ctypes.get_last_error()}")
        if kernel32.WaitForSingleObject(handle, 5_000) != 0:
            raise CandidateProcessSettlementError("candidate Windows job did not settle within five seconds")
    finally:
        kernel32.CloseHandle(handle)


def _run_candidate_process(
    command: tuple[str, ...],
    *,
    root: Path,
    environment: dict[str, str],
    capture_output: bool,
) -> subprocess.CompletedProcess[Any]:
    """Run candidate code without protected authority and settle its entire process boundary."""

    job = _windows_job() if os.name == "nt" else None
    process: subprocess.Popen[Any] | None = None
    boundary = _LinuxSubreaperBoundary() if os.name != "nt" else None
    boundary_opened = False
    outputs: dict[str, str] = {}
    readers: list[threading.Thread] = []
    streams: list[tuple[str, Any]] = []
    reader_errors: list[tuple[str, BaseException]] = []
    cleanup_errors: list[tuple[str, BaseException]] = []
    primary_error: BaseException | None = None
    returncode: int | None = None

    def drain(label: str, stream: Any) -> None:
        try:
            outputs[label] = stream.read()
        except BaseException as exc:
            reader_errors.append((label, exc))

    def record_cleanup_error(label: str, operation: Any) -> None:
        try:
            operation()
        except BaseException as exc:
            cleanup_errors.append((label, exc))

    def close_streams() -> None:
        for label, stream in streams:
            record_cleanup_error(f"{label} pipe close", stream.close)

    if boundary is not None:
        boundary.open()
        boundary_opened = True
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=capture_output,
            encoding="utf-8" if capture_output else None,
            errors="replace" if capture_output else None,
            start_new_session=os.name != "nt",
            creationflags=0x00000004 if os.name == "nt" else 0,  # CREATE_SUSPENDED
        )
        if capture_output:
            streams = [
                (label, stream)
                for label, stream in (("stdout", process.stdout), ("stderr", process.stderr))
                if stream is not None
            ]
            if len(streams) != 2:
                raise CandidateProcessSettlementError("captured candidate pipes were not created")
        if job is not None:
            _assign_windows_job(job, process)
            _resume_windows_process(process)
        elif boundary is not None:
            boundary.attach(process)
        if capture_output:
            readers = [threading.Thread(target=drain, args=(label, stream), daemon=True) for label, stream in streams]
            for reader in readers:
                reader.start()
        while returncode is None:
            if reader_errors:
                raise reader_errors[0][1]
            try:
                returncode = process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                continue
    except BaseException as exc:
        primary_error = exc
    finally:
        if job is not None:
            record_cleanup_error("Windows job settlement", lambda: _settle_windows_job(job))
        elif boundary is not None and boundary_opened:
            record_cleanup_error("Linux candidate settlement", lambda: boundary.settle(process))

        if process is not None and process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(("candidate root termination", exc))
            else:
                record_cleanup_error("candidate root wait", lambda: process.wait(timeout=5))

        for reader in readers:
            reader.join(timeout=5)
        if any(reader.is_alive() for reader in readers):
            close_streams()
            for reader in readers:
                reader.join(timeout=5)
        else:
            close_streams()
        if any(reader.is_alive() for reader in readers):
            cleanup_errors.append(
                (
                    "candidate output readers",
                    CandidateProcessSettlementError("candidate output readers did not settle within five seconds"),
                )
            )
        for label, error in reader_errors:
            if primary_error is None or error is not primary_error:
                cleanup_errors.append((f"{label} reader", error))
        if boundary is not None and boundary_opened:
            record_cleanup_error("Linux boundary close", boundary.close)

    if primary_error is not None:
        for label, error in cleanup_errors:
            primary_error.add_note(f"{label}: {error!r}")
        raise primary_error
    if cleanup_errors:
        raise cleanup_errors[0][1]
    if returncode is None:
        raise CandidateProcessSettlementError("candidate process did not produce a return code")
    return subprocess.CompletedProcess(
        command,
        returncode,
        outputs.get("stdout") if capture_output else None,
        outputs.get("stderr") if capture_output else None,
    )


def _checkout_environment(root: Path) -> dict[str, str]:
    """Return the subprocess environment for exact-checkout pytest runs.

    A protected run inherits the sealed export's environment, which is poison
    for a real checkout: the population-receipt plugin fails closed without the
    per-invocation index only the exported partition accounting owns, disabled
    plugin autoload withdraws the entry-point plugins (asyncio, timeout) these
    tests rely on, and the exported-candidate marker misdescribes this tree.
    The candidate must never retain protected-job credentials or command
    channels either, so the base environment is the authority-stripped one.
    """

    environment = _candidate_authority_environment()
    for key in (
        FAILURE_RECEIPT_INDEX_ENV,
        FAILURE_RECEIPT_SUITE_ENV,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "CRYODAQ_EXPORTED_CANDIDATE",
    ):
        environment.pop(key, None)
    # An inherited PYTHONPATH is poison twice over: it would bind the judge's
    # tree instead of the candidate's, and its absence leaves the candidate's
    # src-layout package unimportable. Pin the candidate's own root and src,
    # exactly as the sealed candidate runner's bootstrap does
    # (tools/ci_candidate_runner.py).
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "src")))
    return environment


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"exact checkout verification failed: git {' '.join(arguments)}")
    return completed.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, check=False)
    if completed.returncode:
        raise RedReproductionComparisonError(f"trusted-base comparison failed: git {' '.join(arguments)}")
    return completed.stdout


def _commit(root: Path, revision: str, *, label: str) -> str:
    if not isinstance(revision, str) or _SHA.fullmatch(revision) is None or revision == _ZERO_SHA:
        raise RedReproductionComparisonError(f"{label} is not a nonzero lowercase 40-hex SHA")
    try:
        return _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except RuntimeError as exc:
        raise RedReproductionComparisonError(f"{label} is not a resolvable commit") from exc


def _registry_at(root: Path, revision: str) -> dict:
    try:
        payload = yaml.safe_load(_git_bytes(root, "show", f"{revision}:{_REGISTRY}").decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise RedReproductionComparisonError(f"{revision} registry is not valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise RedReproductionComparisonError(f"{revision} registry is not a mapping")
    return payload


def _bindings(payload: dict, *, label: str) -> dict[tuple[str, str], tuple[str, str]]:
    bindings: dict[tuple[str, str], tuple[str, str]] = {}
    for collection in ("records", "false_green_pairs"):
        entries = payload.get(collection)
        if not isinstance(entries, list):
            raise RedReproductionComparisonError(f"{label} registry collection is malformed: {collection}")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise RedReproductionComparisonError(f"{label} registry has an entry without a prevention ID")
            evidence = entry.get("red_evidence")
            if not isinstance(evidence, dict):
                continue
            locator, digest = evidence.get("locator"), evidence.get("sha256")
            if not (isinstance(locator, str) and locator.startswith("red-reproduction:") and isinstance(digest, str)):
                continue
            key = (collection, entry["id"])
            if key in bindings:
                raise RedReproductionComparisonError(f"{label} registry has a duplicate prevention identity: {key}")
            bindings[key] = (locator, digest)
    return bindings


def _canonical_reproduction_path(locator: str) -> PurePosixPath:
    raw = locator.removeprefix("red-reproduction:")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or str(path) != raw
        or any(part in {"", ".", ".."} for part in path.parts)
        or not path.is_relative_to(_REPRODUCTIONS)
        or path == _REPRODUCTIONS
    ):
        raise RedReproductionComparisonError(f"red-reproduction locator is not a canonical contained file: {locator}")
    return path


def _tree_entry(root: Path, revision: str, path: PurePosixPath) -> tuple[str, str, str]:
    """Return the exact committed mode, object kind, and object ID for one literal path."""

    raw = _git_bytes(root, "ls-tree", "-z", "--full-tree", revision, "--", f":(literal){path}")
    records = raw.split(b"\0")
    if len(records) != 2 or not records[0] or records[1]:
        raise RedReproductionComparisonError(f"{revision} has no unique tree entry for {path}")
    metadata, separator, recorded_path = records[0].partition(b"\t")
    fields = metadata.split(b" ")
    if separator != b"\t" or recorded_path != str(path).encode("utf-8") or len(fields) != 3:
        raise RedReproductionComparisonError(f"{revision} has a malformed tree entry for {path}")
    try:
        mode, kind, object_id = (field.decode("ascii") for field in fields)
    except UnicodeError as exc:
        raise RedReproductionComparisonError(f"{revision} has a non-ASCII tree entry for {path}") from exc
    return mode, kind, object_id


def compare_red_reproduction_bindings(root: Path, *, candidate: str, trusted_base: str) -> dict[str, str | int]:
    """Compare committed candidate evidence bindings against one trusted commit.

    This deliberately reads both registries and blobs from Git objects.  No
    ancestry, moving ref, working-tree filter, or candidate parent is authority.
    """

    candidate_commit = _commit(root, candidate, label="candidate commit")
    base_commit = _commit(root, trusted_base, label="trusted base")
    base = _bindings(_registry_at(root, base_commit), label="trusted base")
    current = _bindings(_registry_at(root, candidate_commit), label="candidate")
    for identity, binding in base.items():
        candidate_binding = current.get(identity)
        if candidate_binding is None:
            raise RedReproductionComparisonError(f"candidate deleted trusted-base prevention binding: {identity}")
        if candidate_binding != binding:
            raise RedReproductionComparisonError(
                f"candidate modified trusted-base locator or digest binding: {identity}"
            )
        path = _canonical_reproduction_path(binding[0])
        try:
            base_entry = _tree_entry(root, base_commit, path)
            candidate_entry = _tree_entry(root, candidate_commit, path)
        except RedReproductionComparisonError as exc:
            raise RedReproductionComparisonError(
                f"candidate deleted or renamed trusted-base red-reproduction evidence: {path}"
            ) from exc
        if base_entry[2] != candidate_entry[2]:
            raise RedReproductionComparisonError(f"candidate changed trusted-base red-reproduction bytes: {path}")
        if base_entry[:2] != candidate_entry[:2]:
            raise RedReproductionComparisonError(
                f"candidate changed trusted-base red-reproduction mode or type: {path}"
            )
    return {
        "candidate_commit": candidate_commit,
        "candidate_tree": _git(root, "rev-parse", "--verify", f"{candidate_commit}^{{tree}}"),
        "outcome": "passed",
        "trusted_base_commit": base_commit,
        "trusted_binding_count": len(base),
    }


def _verify_checkout(root: Path, revision: str) -> None:
    if _git(root, "rev-parse", "HEAD") != revision:
        raise RuntimeError("exact checkout HEAD does not match the requested revision")
    _git(root, "diff", "--quiet")
    _git(root, "diff", "--cached", "--quiet")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("exact checkout has tracked or untracked changes")


def run_suite(
    suite: str,
    *,
    root: Path,
    revision: str,
    basetemp: Path,
    trusted_base: str | None = None,
    protected_producer_root: Path | None = None,
) -> int:
    """Execute all and only the registry-selected exact-checkout tests once."""

    root = root.resolve(strict=True)
    _verify_checkout(root, revision)
    # The trusted-base comparison runs only where that authority legitimately
    # exists: the workflow CLI (--trusted-base is required there) and the
    # protected producer.  The sealed candidate runner reaches this function
    # through tools.ci_candidate_runner without the base -- the bootstrap
    # strips it before candidate code can read it -- and the producer has
    # already proven the same comparison and bound it into the signed bundle.
    if trusted_base is not None:
        comparison = compare_red_reproduction_bindings(root, candidate=revision, trusted_base=trusted_base)
        print(f"CRYODAQ_RED_REPRODUCTION_COMPARISON {json.dumps(comparison, sort_keys=True)}", flush=True)
    compile_python_tree(root)
    files, nodes = checkout_execution_selection(root, suite)
    file_set = set(files)
    selected_nodes = tuple(node for node in nodes if node.split("::", 1)[0] not in file_set)
    platform = current_guard_platform()
    guard_specs = active_guard_specs(
        root,
        suite,
        platform=platform,
        execution_root="git-index",
        git_repository=root if protected_producer_root is not None else None,
        require_git_resolution=protected_producer_root is not None,
    )
    guard_nodes = tuple(spec.node for spec in guard_specs)
    # The release suite deliberately registers no guards (the whole-tree guards live
    # in `remaining`), so its exact-checkout selection must itself be executed
    # strictly: feed the selection files to the strict command as required files so
    # a skip/xfail/dynamic-skip marker cannot pass unseen.  Other suites keep their
    # registry-bound strict pass unchanged.
    required_files = files if (not guard_nodes and suite == "release") else ()
    basetemp.mkdir(parents=True, exist_ok=True)
    environment = _checkout_environment(root)

    strict = _strict_guard_command(
        suite,
        active_nodes=guard_nodes,
        basetemp=basetemp,
        execution_root="git-index",
        pytest_command=_PYTEST,
        required_files=required_files,
    )
    if protected_producer_root is not None:
        if strict is not None:
            strict = _protected_pytest_command(
                strict,
                root=root,
                producer_root=protected_producer_root,
                strict=True,
            )
    if strict is not None:
        completed = _run_candidate_process(
            strict,
            root=root,
            environment=environment,
            capture_output=True,
        )
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)
        if completed.returncode:
            return completed.returncode
        _validate_strict_guard_receipt(
            completed.stdout + completed.stderr,
            suite=suite,
            expected=(*guard_nodes, *required_files),
            expected_platforms={
                **{spec.node: spec.platform for spec in guard_specs},
                **{path: None for path in required_files},
            },
            platform=platform,
        )

    ordinary = tuple(path for path in (*files, *selected_nodes) if path not in required_files)
    if ordinary:
        command = _PYTEST + ("--basetemp", str(basetemp / "ordinary"), *ordinary)
        command += tuple(argument for node in guard_nodes for argument in ("--deselect", node)) + _TAIL
        if protected_producer_root is not None:
            command = _protected_pytest_command(
                command,
                root=root,
                producer_root=protected_producer_root,
                strict=False,
            )
        completed = _run_candidate_process(
            command,
            root=root,
            environment=environment,
            capture_output=False,
        )
        if completed.returncode:
            return completed.returncode
    _verify_checkout(root, revision)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    # OB-006 added `release`, the tag-triggered suite. Both names are exact-checkout partitions
    # declared in tools/ci_execution_roots.py; a suite absent from that registry selects nothing
    # and would exit 0 without executing a guard, so this list must never widen past it.
    parser.add_argument("--suite", choices=("release", "remaining"), required=True)
    parser.add_argument("--basetemp", type=Path, required=True)
    parser.add_argument("--trusted-base", required=True)
    parser.add_argument("--protected-producer-root", type=Path)
    args = parser.parse_args(argv)
    return run_suite(
        args.suite,
        root=args.repository,
        revision=args.revision,
        basetemp=args.basetemp,
        trusted_base=args.trusted_base,
        protected_producer_root=args.protected_producer_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
