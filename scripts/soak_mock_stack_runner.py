"""Hard-disabled POSIX soak runner foundation with an R3b receipt sink.

The inherited AF_UNIX endpoint may durably capture isolated periodic-artifact
evidence, but the runner still cannot launch a source process or publish a
successful qualification. Activation and terminal PASS remain fused until the
locked observer and integrated short-run acceptance are reviewed together.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import secrets
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_TEST_FILE: Final = "tests/integration/test_periodic_png_multiprocess.py"
_COLLECTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
    "--collect-only",
    "-q",
    _TEST_FILE,
)
_EXECUTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "-p",
    "pytest_asyncio.plugin",
    "-p",
    "pytest_timeout",
    "-p",
    "no:cacheprovider",
    "-q",
    _TEST_FILE,
)
_EXACT_NODE_IDS: Final = (
    f"{_TEST_FILE}::test_real_loopback_publisher_rep_and_adapter_startup_hydration_alarm_seals",
    f"{_TEST_FILE}::test_publisher_restart_changes_session_and_fresh_adapter_recovers",
    f"{_TEST_FILE}::test_subscriber_disconnect_monitor_invalidates_and_callbacks_stop",
    f"{_TEST_FILE}::test_two_assistants_one_leader_per_domain",
    f"{_TEST_FILE}::test_killed_elected_assistant_replacement_makes_one_forward_result",
    f"{_TEST_FILE}::test_replay_exact_off_child_creates_no_periodic_resources",
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SUMMARY_RE = re.compile(r"6 passed in [0-9]+(?:\.[0-9]+)?s\Z")
_COLLECTION_SUMMARY_RE = re.compile(r"6 tests collected in [0-9]+(?:\.[0-9]+)?s\Z")
_PROGRESS_RE = re.compile(r"\.{6}\s+\[100%\]\Z")
_FORBIDDEN_PYTEST_MARKERS: Final = (" skipped", " deselected", " xfailed", " xpassed", " error")
_MAX_STREAM_BYTES: Final = 8 * 1024 * 1024
_MAX_SNAPSHOT_ARCHIVE_BYTES: Final = 32 * 1024 * 1024
_EXACT_SIX_TIMEOUT_S: Final = 300.0
_PROCESS_GROUP_GRACE_S: Final = 2.0
_STATUS_STRUCT: Final = struct.Struct("!i")
_SUPERVISOR_CODE: Final = """\
import ctypes, os, select, struct, sys
if sys.platform != "linux" or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
    raise SystemExit(126)
status_fd = int(sys.argv[1])
release_fd = int(sys.argv[2])
start_fd = int(sys.argv[3])
argv = sys.argv[4:]
if os.read(start_fd, 1) != b"G":
    raise SystemExit(125)
os.close(start_fd)
child = os.fork()
if child == 0:
    os.close(status_fd)
    os.close(release_fd)
    os.execve("/proc/self/exe", argv, os.environ)
os.close(1)
os.close(2)
_, status = os.waitpid(child, 0)
exit_code = os.waitstatus_to_exitcode(status)
os.write(status_fd, struct.pack("!i", exit_code))
os.close(status_fd)
while True:
    try:
        while os.waitpid(-1, os.WNOHANG)[0] > 0:
            pass
    except ChildProcessError:
        pass
    if select.select([release_fd], [], [], 0.05)[0]:
        os.read(release_fd, 1)
        break
os.close(release_fd)
"""
_MAX_START_IDENTITY_BYTES: Final = 128
_BRIDGE_HANDSHAKE_SCHEMA: Final = "cryodaq.soak.bridge-identity"
_BRIDGE_HANDSHAKE_VERSION: Final = 1
_MAX_BRIDGE_HANDSHAKE_BYTES: Final = 512
_BRIDGE_FD_ENV: Final = "CRYODAQ_SOAK_BRIDGE_FD"
_BRIDGE_NONCE_ENV: Final = "CRYODAQ_SOAK_BRIDGE_NONCE"
_ARTIFACT_FD_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_FD"
_ARTIFACT_NONCE_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_NONCE"
_FRAME_PREFIX: Final = struct.Struct("!I")
_ARTIFACT_IO_TIMEOUT_S: Final = 10.0
_MAX_RECEIPT_LEDGER_BYTES: Final = 8 * 1024 * 1024
_MAX_RECEIPT_RECORD_BYTES: Final = 8 * 1024
_LOCKED_PSUTIL_VERSION: Final = "7.2.2"


class _RunnerFoundationError(ValueError):
    """Pure validation failed; this never represents production authority."""


class _ObservedProcessGone(_RunnerFoundationError):
    """An enumerated descendant exited before its identity could settle."""


class _RunnerActivationDisabled(RuntimeError):
    """Production orchestration remains fused off until R2/R3 integration."""


class _ShaBoundary(StrEnum):
    BEFORE_COLLECTION = "before_collection"
    BETWEEN_COLLECTION_AND_EXECUTION = "between_collection_and_execution"
    AFTER_EXECUTION = "after_execution"
    BEFORE_SOURCE_LAUNCH = "before_source_launch"
    AFTER_SOURCE_SHUTDOWN = "after_source_shutdown"
    BEFORE_TERMINAL_ACCEPTANCE = "before_terminal_acceptance"


@dataclass(frozen=True, slots=True)
class _RunProvenance:
    """Immutable non-authoritative run identity supplied to later R2 code."""

    run_id: str
    nonce_sha256: str
    platform: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None:
            raise _RunnerFoundationError("run_id must be 128-bit lowercase hex")
        if _SHA256_RE.fullmatch(self.nonce_sha256) is None:
            raise _RunnerFoundationError("nonce_sha256 must be canonical")
        if self.platform not in {"linux", "darwin"}:
            raise _RunnerFoundationError("R1 provenance supports POSIX Linux/macOS only")


@dataclass(frozen=True, slots=True)
class _WorktreeImportProof:
    repo_root: Path
    interpreter: Path
    interpreter_sha256: str
    cryodaq_import: Path

    def __post_init__(self) -> None:
        root = self.repo_root.resolve()
        interpreter = self.interpreter.resolve()
        imported = self.cryodaq_import.resolve()
        expected_interpreter = (root / ".venv/bin/python").resolve()
        expected_package = (root / "src/cryodaq").resolve()
        if interpreter != expected_interpreter:
            raise _RunnerFoundationError("interpreter is not the exact worktree .venv Python")
        if _SHA256_RE.fullmatch(self.interpreter_sha256) is None:
            raise _RunnerFoundationError("interpreter hash must be canonical")
        if not imported.is_relative_to(expected_package):
            raise _RunnerFoundationError("cryodaq import does not resolve inside the exact worktree src")
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "interpreter", interpreter)
        object.__setattr__(self, "cryodaq_import", imported)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _hash_regular_file(path: Path) -> str:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise _RunnerFoundationError("worktree interpreter is not a regular file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            opened = os.fstat(stream.fileno())
    except OSError as exc:
        raise _RunnerFoundationError("worktree interpreter hash is unavailable") from exc
    after = path.stat()
    if _file_identity(before) != _file_identity(opened) or _file_identity(before) != _file_identity(after):
        raise _RunnerFoundationError("worktree interpreter changed while hashing")
    return f"sha256:{digest.hexdigest()}"


def _copy_running_executable(expected: Path, destination: Path) -> str:
    """Copy the already-open Linux process image without reopening its pathname."""

    source_fd: int | None = None
    destination_fd: int | None = None
    digest = hashlib.sha256()
    try:
        source_fd = os.open("/proc/self/exe", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode):
            raise _RunnerFoundationError("running interpreter is not a regular file")
        if Path(f"/proc/self/fd/{source_fd}").resolve(strict=True) != expected.resolve(strict=True):
            raise _RunnerActivationDisabled("runner is not executing under the exact worktree .venv interpreter")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o500,
        )
        while chunk := os.read(source_fd, 1024 * 1024):
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise _RunnerFoundationError("sealed interpreter copy made no progress")
                view = view[written:]
        os.fsync(destination_fd)
        source_after = os.fstat(source_fd)
    except OSError as exc:
        raise _RunnerActivationDisabled("running interpreter capture is unavailable") from exc
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
    if _file_identity(source_before) != _file_identity(source_after):
        raise _RunnerFoundationError("running interpreter changed while being captured")
    captured = f"sha256:{digest.hexdigest()}"
    if _hash_regular_file(destination) != captured:
        raise _RunnerFoundationError("sealed interpreter copy contradicts its source")
    return captured


def _controlled_test_environment(repo_root: Path, site_packages: Path) -> dict[str, str]:
    root = Path(repo_root).resolve()
    return {
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root), str(site_packages.resolve()))),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "TMPDIR": "/tmp",
        "TZ": "UTC",
        "XDG_CACHE_HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
    }


def _controlled_git_environment() -> dict[str, str]:
    return {"HOME": "/nonexistent", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"}


@dataclass(frozen=True, slots=True)
class _ExecutionSnapshot:
    root: Path
    interpreter: Path
    environment: dict[str, str]
    tree_sha256: str

    def assert_sealed(self) -> None:
        if _tree_sha256(self.root) != self.tree_sha256:
            raise _RunnerFoundationError("sealed exact-six snapshot changed during execution")


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


@contextmanager
def _sealed_execution_snapshot(git_sha: str):
    interpreter = _REPO_ROOT / ".venv/bin/python"
    try:
        resolved = interpreter.resolve(strict=True)
    except OSError as exc:
        raise _RunnerActivationDisabled("exact worktree .venv interpreter is unavailable") from exc
    try:
        archive = subprocess.run(
            ("git", "archive", "--format=tar", git_sha),
            cwd=_REPO_ROOT,
            env=_controlled_git_environment(),
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RunnerActivationDisabled("sealed exact-six snapshot is unavailable") from exc
    if len(archive) > _MAX_SNAPSHOT_ARCHIVE_BYTES:
        raise _RunnerActivationDisabled("sealed exact-six snapshot exceeds the reviewed bound")
    site_packages = (
        Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    ).resolve()
    if not site_packages.is_dir():
        raise _RunnerActivationDisabled("exact worktree site-packages is unavailable")
    with tempfile.TemporaryDirectory(prefix="cryodaq-exact-six-") as temporary:
        root = Path(temporary)
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                bundle.extractall(root, filter="data")
            snapshot_interpreter = root / ".venv/bin/python"
            snapshot_interpreter.parent.mkdir(parents=True)
            _copy_running_executable(resolved, snapshot_interpreter)
            environment = _controlled_test_environment(root, site_packages)
            code = "from pathlib import Path; import cryodaq; print(Path(cryodaq.__file__).resolve())"
            imported = subprocess.run(
                (str(snapshot_interpreter), "-c", code),
                cwd=root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if imported.stderr.strip() or len(imported.stdout.splitlines()) != 1:
                raise _RunnerFoundationError("sealed exact-six import proof output is invalid")
            if not Path(imported.stdout.strip()).resolve().is_relative_to((root / "src/cryodaq").resolve()):
                raise _RunnerFoundationError("sealed exact-six import escaped the snapshot")
            for path in root.rglob("*"):
                if path.is_file() and path != snapshot_interpreter:
                    path.chmod(0o400)
                elif path.is_dir():
                    path.chmod(0o500)
            root.chmod(0o500)
            snapshot = _ExecutionSnapshot(root, snapshot_interpreter, environment, _tree_sha256(root))
            yield snapshot
            snapshot.assert_sealed()
        finally:
            root.chmod(0o700)
            for path in root.rglob("*"):
                if path.is_dir():
                    path.chmod(0o700)


@dataclass(frozen=True, slots=True)
class _CleanShaObservation:
    boundary: _ShaBoundary
    git_sha: str
    clean: bool

    def __post_init__(self) -> None:
        if not isinstance(self.boundary, _ShaBoundary):
            raise TypeError("boundary must be a _ShaBoundary")
        if _GIT_SHA_RE.fullmatch(self.git_sha) is None:
            raise _RunnerFoundationError("git_sha must be full lowercase 40-character hex")
        if not isinstance(self.clean, bool):
            raise TypeError("clean must be a bool")


def _validate_clean_sha_chain(
    observations: tuple[_CleanShaObservation, ...],
    *,
    expected: tuple[_ShaBoundary, ...] = tuple(_ShaBoundary),
) -> str:
    if tuple(item.boundary for item in observations) != expected:
        raise _RunnerFoundationError("clean SHA observations are incomplete or out of order")
    if any(not item.clean for item in observations):
        raise _RunnerFoundationError("worktree drift is terminal")
    shas = {item.git_sha for item in observations}
    if len(shas) != 1:
        raise _RunnerFoundationError("clean SHA changed across runner boundaries")
    return observations[0].git_sha


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    start_identity: str

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or self.pid <= 0:
            raise _RunnerFoundationError("child PID must be positive")
        if not isinstance(self.start_identity, str):
            raise TypeError("child start identity must be a string")
        encoded = self.start_identity.encode("utf-8")
        if (
            not encoded
            or len(encoded) > _MAX_START_IDENTITY_BYTES
            or any(ord(char) < 32 or ord(char) == 127 for char in self.start_identity)
        ):
            raise _RunnerFoundationError("child start identity is empty or oversized")


class _ChildIdentityObserver(Protocol):
    """R2 adapter boundary; PID alone never identifies a process."""

    def identity_for_pid(self, pid: int) -> _ProcessIdentity: ...


class _LockedPsutilObserver:
    """Fail-closed PID/start observer used only by source qualification.

    The module object is injected only to keep import-time product behavior
    independent of the dev extra.  Runtime construction requires the exact
    lockfile version and never skips access/identity errors.
    """

    __slots__ = ("_psutil",)

    def __init__(self, psutil_module: Any) -> None:
        if getattr(psutil_module, "__version__", None) != _LOCKED_PSUTIL_VERSION:
            raise _RunnerActivationDisabled("locked psutil observer version is unavailable")
        required = ("Process", "NoSuchProcess", "AccessDenied", "TimeoutExpired", "STATUS_ZOMBIE")
        if any(not hasattr(psutil_module, name) for name in required):
            raise _RunnerActivationDisabled("psutil observer API is incomplete")
        self._psutil = psutil_module

    def _process(self, pid: int) -> Any:
        if type(pid) is not int or pid <= 0:
            raise _RunnerFoundationError("observer PID is invalid")
        try:
            return self._psutil.Process(pid)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied) as exc:
            raise _RunnerFoundationError("process identity is unavailable") from exc

    def _identity(self, process: Any, *, allow_zombie: bool = False) -> _ProcessIdentity:
        try:
            created = float(process.create_time())
            status = process.status()
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
            raise _RunnerFoundationError("process start identity is unavailable") from exc
        if not math.isfinite(created) or created <= 0:
            raise _RunnerFoundationError("process start identity is not live")
        if status == self._psutil.STATUS_ZOMBIE and not allow_zombie:
            raise _ObservedProcessGone("process start identity is not live")
        started_ns = int(round(created * 1_000_000_000))
        return _ProcessIdentity(process.pid, f"psutil-{_LOCKED_PSUTIL_VERSION}:ctime-ns={started_ns}")

    def identity_for_pid(self, pid: int) -> _ProcessIdentity:
        return self._identity(self._process(pid))

    def recheck_exact(self, expected: _ProcessIdentity) -> None:
        """Prove PID/start continuity even after the owned leader is a zombie."""

        if not isinstance(expected, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        if self._identity(self._process(expected.pid), allow_zombie=True) != expected:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")

    def group_members(self, process_group_id: int) -> tuple[_ProcessIdentity, ...]:
        members: list[_ProcessIdentity] = []
        if not hasattr(self._psutil, "process_iter"):
            raise _RunnerFoundationError("process-group observer API is unavailable")
        try:
            processes = tuple(self._psutil.process_iter())
        except (self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("process-group membership is unavailable") from exc
        for process in processes:
            try:
                if os.getpgid(process.pid) == process_group_id:
                    members.append(self._identity(process))
            except (ProcessLookupError, self._psutil.NoSuchProcess):
                continue
            except _ObservedProcessGone:
                continue
            except _RunnerFoundationError as exc:
                if isinstance(exc.__cause__, self._psutil.NoSuchProcess):
                    continue
                raise
            except (PermissionError, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
                raise _RunnerFoundationError("process-group membership cannot be proven") from exc
        return tuple(sorted(members, key=lambda item: item.pid))

    def descendants(self, leader: _ProcessIdentity) -> tuple[_ProcessIdentity, ...]:
        process = self._process(leader.pid)
        if self._identity(process, allow_zombie=True) != leader:
            raise _RunnerFoundationError("PID/start identity changed; refusing descendant scan")
        try:
            children = tuple(process.children(recursive=True))
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("owned descendant scan is unavailable") from exc
        if len(children) > 128:
            raise _RunnerFoundationError("owned descendant count exceeds the reviewed bound")
        identities: list[_ProcessIdentity] = []
        for child in children:
            try:
                identities.append(self._identity(child))
            except _ObservedProcessGone:
                continue
            except _RunnerFoundationError as exc:
                if isinstance(exc.__cause__, self._psutil.NoSuchProcess):
                    continue
                raise
        return tuple(sorted(identities, key=lambda item: item.pid))

    def signal_exact_for_cleanup(self, identity: _ProcessIdentity, signum: int) -> None:
        allowed = {signal.SIGTERM, getattr(signal, "SIGKILL", 9)}
        if isinstance(signum, bool) or not isinstance(signum, int) or signum not in allowed:
            raise _RunnerFoundationError("cleanup signal is outside the reviewed allowlist")
        process = self._recheck(identity)
        try:
            process.send_signal(signum)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("exact-identity cleanup signal failed") from exc

    def _recheck(self, expected: _ProcessIdentity) -> Any:
        if not isinstance(expected, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        process = self._process(expected.pid)
        if self._identity(process) != expected:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")
        return process

    def observe_assistant(self, pid: int, *, expected_launcher_pid: int) -> _AssistantProcessObservation:
        process = self._process(pid)
        identity = self._identity(process)
        try:
            parent_pid = int(process.ppid())
            argv = tuple(process.cmdline())
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError, TypeError, ValueError) as exc:
            raise _RunnerFoundationError("assistant process observation is unavailable") from exc
        role = _exact_child_role(argv)
        observation = _AssistantProcessObservation(identity, parent_pid, role, True)
        _bind_positive_assistant_identity(observation, expected_launcher_pid=expected_launcher_pid)
        return observation

    def signal_exact(self, identity: _ProcessIdentity, signum: int) -> None:
        if isinstance(signum, bool) or not isinstance(signum, int) or signum != signal.SIGTERM:
            raise _RunnerFoundationError("qualification permits only exact-identity SIGTERM")
        process = self._recheck(identity)
        try:
            process.send_signal(signum)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied, OSError) as exc:
            raise _RunnerFoundationError("exact-identity signal failed") from exc

    def wait_gone(self, identity: _ProcessIdentity, *, timeout_s: float) -> None:
        if type(timeout_s) not in {int, float} or not math.isfinite(float(timeout_s)) or not 0 < timeout_s <= 20:
            raise _RunnerFoundationError("process wait timeout is outside the reviewed bound")
        if not isinstance(identity, _ProcessIdentity):
            raise TypeError("expected identity must be a _ProcessIdentity")
        try:
            process = self._psutil.Process(identity.pid)
        except self._psutil.NoSuchProcess:
            return
        except self._psutil.AccessDenied as exc:
            raise _RunnerFoundationError("process identity cannot be rechecked before wait") from exc
        if self._identity(process) != identity:
            raise _RunnerFoundationError("PID/start identity changed; refusing process operation")
        try:
            process.wait(timeout=float(timeout_s))
        except self._psutil.NoSuchProcess:
            return
        except (self._psutil.AccessDenied, self._psutil.TimeoutExpired, OSError) as exc:
            raise _RunnerFoundationError("exact process identity did not settle") from exc
        try:
            current = self._psutil.Process(identity.pid)
        except self._psutil.NoSuchProcess:
            return
        except self._psutil.AccessDenied as exc:
            raise _RunnerFoundationError("settled process identity cannot be rechecked") from exc
        if self._identity(current) == identity:
            raise _RunnerFoundationError("exact process identity remains live after wait")


# Whole-argv suffixes (everything after argv[0], the interpreter) allowlisted
# per role. `_exact_child_role` requires an exact tuple match against one of
# these — no extra, duplicate, leading, or trailing tokens tolerated.
_ROLE_ARGV_SUFFIXES: Final = {
    "assistant": (("-m", "cryodaq.agents.assistant_bootstrap"), ("--mode=assistant",)),
    "engine": (
        ("-m", "cryodaq.engine"),
        ("--mode=engine",),
        ("-m", "cryodaq.engine", "--mock"),
        ("--mode=engine", "--mock"),
    ),
}


def _exact_child_role(argv: tuple[str, ...]) -> str:
    if not argv or any(type(item) is not str for item in argv):
        raise _RunnerFoundationError("child argv is unavailable")
    rest = argv[1:]
    for role, suffixes in _ROLE_ARGV_SUFFIXES.items():
        if rest in suffixes:
            return role
    raise _RunnerFoundationError("child argv is not an exact allowlisted role")


class _CleanShaCollector:
    """Collect ordered clean-SHA observations from fixed Git commands."""

    __slots__ = ("_next", "_repo_root", "_sha")

    def __init__(self, repo_root: Path) -> None:
        root = Path(repo_root).resolve()
        if not (root / ".git").exists():
            raise _RunnerFoundationError("runner root is not a Git worktree")
        self._repo_root = root
        self._next = 0
        self._sha: str | None = None

    def observe(self, boundary: _ShaBoundary) -> _CleanShaObservation:
        boundaries = tuple(_ShaBoundary)
        if self._next >= len(boundaries) or boundary is not boundaries[self._next]:
            raise _RunnerFoundationError("clean SHA boundary is out of order")
        try:
            sha = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=self._repo_root,
                env=_controlled_git_environment(),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            status = subprocess.run(
                ("git", "status", "--porcelain=v1", "--untracked-files=all"),
                cwd=self._repo_root,
                env=_controlled_git_environment(),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise _RunnerFoundationError("clean SHA observation failed") from exc
        observation = _CleanShaObservation(boundary, sha, not bool(status))
        if not observation.clean:
            raise _RunnerFoundationError("worktree drift is terminal")
        if self._sha is None:
            self._sha = sha
        elif sha != self._sha:
            raise _RunnerFoundationError("clean SHA changed across runner boundaries")
        self._next += 1
        return observation


@dataclass(frozen=True, slots=True)
class _BridgeHandshakeRecord:
    nonce: str
    launcher_pid: int
    bridge_pid: int
    restart_count: int


class _BridgeHandshakePipe:
    """Runner-owned POSIX one-shot pipe; it grants no evidence acceptance."""

    __slots__ = ("nonce", "read_fd", "write_fd")

    def __init__(self, *, nonce: str, read_fd: int, write_fd: int) -> None:
        self.nonce = nonce
        self.read_fd = read_fd
        self.write_fd = write_fd

    @classmethod
    def create(cls) -> _BridgeHandshakePipe:
        if os.name != "posix":
            raise _RunnerActivationDisabled("bridge handshake pipe is POSIX-only")
        nonce = secrets.token_hex(32)
        read_fd, write_fd = os.pipe()
        try:
            os.set_inheritable(read_fd, False)
            os.set_inheritable(write_fd, False)
            return cls(nonce=nonce, read_fd=read_fd, write_fd=write_fd)
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise

    def child_environment(self) -> dict[str, str]:
        if self.write_fd < 0:
            raise _RunnerFoundationError("bridge handshake write descriptor is closed")
        return {_BRIDGE_FD_ENV: str(self.write_fd), _BRIDGE_NONCE_ENV: self.nonce}

    def child_pass_fds(self) -> tuple[int, ...]:
        if self.write_fd < 0:
            raise _RunnerFoundationError("bridge handshake write descriptor is closed")
        return (self.write_fd,)

    def close_parent_write_end(self) -> None:
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1

    def close(self) -> None:
        self.close_parent_write_end()
        if self.read_fd >= 0:
            os.close(self.read_fd)
            self.read_fd = -1


class _ArtifactCapabilityPair:
    """Runner-owned AF_UNIX socketpair with one launcher-only duplicate."""

    __slots__ = ("nonce", "runner", "launcher")

    def __init__(self, nonce: str, runner: socket.socket, launcher: socket.socket) -> None:
        self.nonce = nonce
        self.runner = runner
        self.launcher = launcher

    @classmethod
    def create(cls) -> _ArtifactCapabilityPair:
        if os.name != "posix":
            raise _RunnerActivationDisabled("artifact capability is POSIX-only")
        runner, launcher = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            runner.set_inheritable(False)
            launcher.set_inheritable(False)
            return cls(secrets.token_hex(32), runner, launcher)
        except BaseException:
            runner.close()
            launcher.close()
            raise

    def child_environment(self) -> dict[str, str]:
        if self.launcher.fileno() < 3:
            raise _RunnerFoundationError("artifact launcher endpoint is closed")
        return {
            _ARTIFACT_FD_ENV: str(self.launcher.fileno()),
            _ARTIFACT_NONCE_ENV: self.nonce,
        }

    def child_pass_fds(self) -> tuple[int, ...]:
        if self.launcher.fileno() < 3:
            raise _RunnerFoundationError("artifact launcher endpoint is closed")
        return (self.launcher.fileno(),)

    def close_launcher_end(self) -> None:
        if self.launcher.fileno() >= 0:
            self.launcher.close()

    def close(self) -> None:
        self.close_launcher_end()
        if self.runner.fileno() >= 0:
            self.runner.close()


class _ArtifactReceiptSink:
    """Runner-side bounded decoder and durable file+ledger authority."""

    __slots__ = ("_dir_fd", "_last_generation", "_next_sequence", "_nonce", "_socket", "_terminal")

    def __init__(self, endpoint: socket.socket, *, nonce: str, evidence_dir: Path) -> None:
        from cryodaq.agents.assistant.soak_periodic_delivery import frame_body_limit

        if os.name != "posix":
            raise _RunnerActivationDisabled("artifact receipt sink is POSIX-only")
        if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise _RunnerFoundationError("artifact nonce is invalid")
        if endpoint.family != socket.AF_UNIX or endpoint.type & socket.SOCK_STREAM != socket.SOCK_STREAM:
            raise _RunnerFoundationError("artifact endpoint is invalid")
        endpoint.getpeername()
        metadata = evidence_dir.lstat()
        if (
            not evidence_dir.is_absolute()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise _RunnerFoundationError("evidence directory is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        self._dir_fd = os.open(evidence_dir, flags)
        opened = os.fstat(self._dir_fd)
        if not os.path.samestat(metadata, opened):
            os.close(self._dir_fd)
            raise _RunnerFoundationError("evidence directory identity changed")
        self._socket = endpoint
        self._socket.set_inheritable(False)
        self._socket.settimeout(_ARTIFACT_IO_TIMEOUT_S)
        self._nonce = nonce
        self._last_generation = 0
        self._next_sequence = 1
        self._terminal = False
        _ = frame_body_limit()

    def accept_one(
        self,
        *,
        assistant_observation: _AssistantProcessObservation,
        expected_launcher_pid: int,
        expected_assistant_generation: int,
        expected_slot_id: str,
        expected_generation_id: str,
        expected_owner_token: str,
        expected_artifact_sha256: str,
    ) -> dict[str, object]:
        from cryodaq.agents.assistant.soak_periodic_delivery import (
            build_ack,
            decode_frame_body,
            frame_body_limit,
        )

        if self._terminal:
            raise _RunnerFoundationError("artifact sink is terminal")
        try:
            deadline = time.monotonic() + _ARTIFACT_IO_TIMEOUT_S
            if (
                type(expected_assistant_generation) is not int
                or expected_assistant_generation <= 0
                or type(expected_slot_id) is not str
                or _SHA256_RE.fullmatch(expected_slot_id) is None
                or type(expected_generation_id) is not str
                or re.fullmatch(r"[0-9a-f]{32}", expected_generation_id) is None
                or type(expected_owner_token) is not str
                or re.fullmatch(r"[0-9a-f]{32}", expected_owner_token) is None
                or type(expected_artifact_sha256) is not str
                or _SHA256_RE.fullmatch(expected_artifact_sha256) is None
            ):
                raise _RunnerFoundationError("expected artifact authority is invalid")
            assistant_identity = _bind_positive_assistant_identity(
                assistant_observation,
                expected_launcher_pid=expected_launcher_pid,
            )
            prefix = self._read_exact(_FRAME_PREFIX.size, deadline=deadline)
            (size,) = _FRAME_PREFIX.unpack(prefix)
            if not 1 <= size <= frame_body_limit():
                raise _RunnerFoundationError("artifact frame size is invalid")
            frame = decode_frame_body(self._read_exact(size, deadline=deadline))
            metadata = frame.metadata
            generation = metadata["assistant_generation"]
            sequence = metadata["sequence"]
            if (
                metadata["nonce"] != self._nonce
                or metadata["assistant_pid"] != assistant_identity.pid
                or generation != expected_assistant_generation
                or metadata["slot_id"] != expected_slot_id
                or metadata["generation_id"] != expected_generation_id
                or metadata["owner_token"] != expected_owner_token
                or metadata["artifact_sha256"] != expected_artifact_sha256
                or type(generation) is not int
                or type(sequence) is not int
                or generation < self._last_generation
                or generation > self._last_generation + 1
                or (generation == self._last_generation and sequence != self._next_sequence)
                or (generation == self._last_generation + 1 and sequence != 1)
            ):
                raise _RunnerFoundationError("artifact identity/generation/sequence is invalid")
            ack = build_ack(frame)
            ack_metadata = json.loads(ack[_FRAME_PREFIX.size :].decode("ascii"))
            self._persist(
                frame,
                ack_metadata=ack_metadata,
                assistant_start_identity=assistant_identity.start_identity,
            )
            self._write_all(ack, deadline=deadline)
            self._last_generation = generation
            self._next_sequence = sequence + 1
            return dict(metadata)
        except BaseException:
            self._terminal = True
            self.close()
            raise

    def _persist(
        self,
        frame: Any,
        *,
        ack_metadata: dict[str, object],
        assistant_start_identity: str,
    ) -> None:
        metadata = frame.metadata
        generation = metadata["assistant_generation"]
        sequence = metadata["sequence"]
        digest = str(metadata["artifact_sha256"])[7:]
        final_name = f"periodic-g{generation}-s{sequence}-{digest}.png"
        staging = f".{final_name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(staging, flags, 0o600, dir_fd=self._dir_fd)
        try:
            os.fchmod(fd, 0o600)
            staging_stat = os.fstat(fd)
            if (
                not stat.S_ISREG(staging_stat.st_mode)
                or staging_stat.st_uid != os.getuid()
                or stat.S_IMODE(staging_stat.st_mode) != 0o600
                or staging_stat.st_nlink != 1
            ):
                raise _RunnerFoundationError("artifact staging descriptor is unsafe")
            self._write_fd(fd, frame.photo)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(staging, final_name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd, follow_symlinks=False)
            os.unlink(staging, dir_fd=self._dir_fd)
            os.fsync(self._dir_fd)
            verify_fd = os.open(final_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._dir_fd)
            try:
                final_stat = os.fstat(verify_fd)
                if (
                    not stat.S_ISREG(final_stat.st_mode)
                    or final_stat.st_uid != os.getuid()
                    or stat.S_IMODE(final_stat.st_mode) != 0o600
                    or final_stat.st_nlink != 1
                    or final_stat.st_size != len(frame.photo)
                ):
                    raise _RunnerFoundationError("persisted artifact descriptor is unsafe")
                raw = bytearray()
                while len(raw) <= len(frame.photo):
                    chunk = os.read(verify_fd, min(64 * 1024, len(frame.photo) + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if bytes(raw) != frame.photo:
                    raise _RunnerFoundationError("persisted artifact rehash mismatch")
            finally:
                os.close(verify_fd)
            record = (
                json.dumps(
                    {
                        "acknowledgement_sha256": ack_metadata["acknowledgement_sha256"],
                        "assistant_start_identity": assistant_start_identity,
                        "filename": final_name,
                        "receipt_id": ack_metadata["receipt_id"],
                        **metadata,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
                + b"\n"
            )
            if len(record) > _MAX_RECEIPT_RECORD_BYTES:
                raise _RunnerFoundationError("receipt ledger record is oversized")
            ledger = self._open_validated_ledger()
            try:
                if os.fstat(ledger).st_size + len(record) > _MAX_RECEIPT_LEDGER_BYTES:
                    raise _RunnerFoundationError("receipt ledger capacity is exhausted")
                self._write_fd(ledger, record)
                os.fsync(ledger)
            finally:
                os.close(ledger)
            os.fsync(self._dir_fd)
        except BaseException:
            try:
                os.unlink(staging, dir_fd=self._dir_fd)
            except OSError:
                pass
            raise

    def _open_validated_ledger(self) -> int:
        name = "periodic-receipts.jsonl"
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        nonblock = getattr(os, "O_NONBLOCK", 0)
        created = False
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | nofollow | nonblock,
                0o600,
                dir_fd=self._dir_fd,
            )
            created = True
            os.fchmod(fd, 0o600)
        except FileExistsError:
            observed = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_uid != os.getuid()
                or stat.S_IMODE(observed.st_mode) != 0o600
                or observed.st_nlink != 1
                or not 1 <= observed.st_size <= _MAX_RECEIPT_LEDGER_BYTES
            ):
                raise _RunnerFoundationError("existing receipt ledger is unsafe") from None
            fd = os.open(name, os.O_RDWR | os.O_APPEND | nofollow | nonblock, dir_fd=self._dir_fd)
            opened = os.fstat(fd)
            if not os.path.samestat(observed, opened):
                os.close(fd)
                raise _RunnerFoundationError("receipt ledger identity changed")
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            os.close(fd)
            raise _RunnerFoundationError("receipt ledger descriptor is unsafe")
        if not created:
            raw = os.pread(fd, metadata.st_size + 1, 0)
            if len(raw) != metadata.st_size or not raw.endswith(b"\n"):
                os.close(fd)
                raise _RunnerFoundationError("receipt ledger has a partial tail")
            seen_receipts: set[str] = set()
            ledger_generation = 0
            ledger_next_sequence = 1
            for line in raw.splitlines(keepends=True):
                if len(line) > _MAX_RECEIPT_RECORD_BYTES or not line.endswith(b"\n"):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is invalid")
                try:
                    value = json.loads(line[:-1].decode("ascii"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is invalid") from None
                canonical = (
                    json.dumps(
                        value,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("ascii")
                    + b"\n"
                )
                if type(value) is not dict or canonical != line:
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is not canonical")
                if not self._valid_ledger_record(value):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger record is semantically invalid")
                receipt_id = value["receipt_id"]
                generation = value["assistant_generation"]
                sequence = value["sequence"]
                if (
                    receipt_id in seen_receipts
                    or generation < ledger_generation
                    or generation > ledger_generation + 1
                    or (generation == ledger_generation and sequence != ledger_next_sequence)
                    or (generation == ledger_generation + 1 and sequence != 1)
                ):
                    os.close(fd)
                    raise _RunnerFoundationError("receipt ledger ordering is invalid")
                seen_receipts.add(receipt_id)
                ledger_generation = generation
                ledger_next_sequence = sequence + 1
        return fd

    @staticmethod
    def _valid_ledger_record(value: dict[str, object]) -> bool:
        expected = {
            "acknowledgement_sha256",
            "artifact_sha256",
            "artifact_size",
            "assistant_generation",
            "assistant_pid",
            "assistant_start_identity",
            "caption_sha256",
            "caption_size",
            "filename",
            "generation_id",
            "nonce",
            "owner_token",
            "receipt_id",
            "schema",
            "sequence",
            "slot_id",
            "type",
            "version",
        }
        if set(value) != expected:
            return False
        generation = value["assistant_generation"]
        sequence = value["sequence"]
        artifact_hash = value["artifact_sha256"]
        try:
            start_identity_bytes = value["assistant_start_identity"].encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            return False
        ack_core = {
            "artifact_sha256": artifact_hash,
            "assistant_generation": generation,
            "assistant_pid": value["assistant_pid"],
            "nonce": value["nonce"],
            "receipt_id": value["receipt_id"],
            "schema": value["schema"],
            "sequence": sequence,
            "type": "ack",
            "version": value["version"],
        }
        expected_ack = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    ack_core,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).hexdigest()
        )
        return bool(
            type(generation) is int
            and generation > 0
            and type(sequence) is int
            and sequence > 0
            and value["receipt_id"] == f"g{generation}:s{sequence}"
            and type(artifact_hash) is str
            and _SHA256_RE.fullmatch(artifact_hash) is not None
            and value["filename"] == f"periodic-g{generation}-s{sequence}-{artifact_hash[7:]}.png"
            and type(value["acknowledgement_sha256"]) is str
            and value["acknowledgement_sha256"] == expected_ack
            and value["schema"] == "cryodaq.soak.periodic-artifact"
            and type(value["version"]) is int
            and value["version"] == 1
            and value["type"] == "artifact"
            and type(value["assistant_pid"]) is int
            and value["assistant_pid"] > 0
            and type(value["nonce"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", value["nonce"]) is not None
            and type(value["slot_id"]) is str
            and _SHA256_RE.fullmatch(value["slot_id"]) is not None
            and type(value["generation_id"]) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["generation_id"]) is not None
            and type(value["owner_token"]) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["owner_token"]) is not None
            and type(value["caption_sha256"]) is str
            and _SHA256_RE.fullmatch(value["caption_sha256"]) is not None
            and type(value["artifact_size"]) is int
            and 33 <= value["artifact_size"] <= 10 * 1024 * 1024
            and type(value["caption_size"]) is int
            and 1 <= value["caption_size"] <= 4096
            and type(value["assistant_start_identity"]) is str
            and 1 <= len(start_identity_bytes) <= _MAX_START_IDENTITY_BYTES
        )

    def _read_exact(self, size: int, *, deadline: float) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise _RunnerFoundationError("artifact stream deadline expired")
            self._socket.settimeout(timeout)
            try:
                chunk = self._socket.recv(remaining)
            except TimeoutError as exc:
                raise _RunnerFoundationError("artifact stream deadline expired") from exc
            if not chunk:
                raise _RunnerFoundationError("artifact stream ended mid-frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _write_all(self, raw: bytes, *, deadline: float) -> None:
        view = memoryview(raw)
        while view:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise _RunnerFoundationError("artifact ACK deadline expired")
            self._socket.settimeout(timeout)
            try:
                sent = self._socket.send(view)
            except TimeoutError as exc:
                raise _RunnerFoundationError("artifact ACK deadline expired") from exc
            if sent <= 0:
                raise _RunnerFoundationError("artifact ACK did not progress")
            view = view[sent:]

    @staticmethod
    def _write_fd(fd: int, raw: bytes) -> None:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise _RunnerFoundationError("durable evidence write did not progress")
            view = view[written:]

    def close(self) -> None:
        if self._socket.fileno() >= 0:
            self._socket.close()
        if self._dir_fd >= 0:
            os.close(self._dir_fd)
            self._dir_fd = -1


@dataclass(frozen=True, slots=True)
class _JoinedReceiptEvidence:
    """One non-authoritative, fully joined local-delivery observation.

    Construction proves agreement between independently collected evidence
    surfaces.  It intentionally grants no terminal PASS authority: the future
    executor must still bind this value to its owned process handles, exact-six
    execution, clean-SHA chain, and cleanup result.
    """

    assistant: _ProcessIdentity
    assistant_generation: int
    sequence: int
    slot_id: str
    generation_id: str
    owner_token: str
    artifact_sha256: str
    receipt_id: str
    acknowledgement_sha256: str
    ledger_record_sha256: str
    destination_fingerprint: str
    state_updated_at: float
    health_updated_at: float


def _validate_joined_receipt(
    *,
    ledger_record: dict[str, object],
    state_payload: dict[str, object],
    artifact_bytes: bytes,
    assistant_observation: _AssistantProcessObservation,
    expected_launcher_pid: int,
) -> _JoinedReceiptEvidence:
    """Join one ACK/file/ledger/process/state cut without accepting PASS.

    The durable state must still expose the successful slot as ``active``.
    ``last_terminal`` deliberately omits the owner token and therefore cannot
    satisfy the preflight's exact owner join on its own.
    """

    from cryodaq.periodic_state import (
        PeriodicStateDocument,
        periodic_local_destination_fingerprint,
    )

    if type(ledger_record) is not dict or not _ArtifactReceiptSink._valid_ledger_record(ledger_record):
        raise _RunnerFoundationError("receipt ledger record is not valid joined evidence")
    if type(state_payload) is not dict:
        raise _RunnerFoundationError("periodic state payload is not a mapping")
    try:
        state = PeriodicStateDocument(state_payload).payload
    except (TypeError, ValueError) as exc:
        raise _RunnerFoundationError("periodic state payload is invalid") from exc
    if type(artifact_bytes) is not bytes:
        raise TypeError("artifact_bytes must be exact bytes")

    assistant = _bind_positive_assistant_identity(
        assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    active = state["active"]
    if type(active) is not dict or active["status"] != "SUCCEEDED":
        raise _RunnerFoundationError("joined state must retain the successful active slot")
    artifact = active["artifact"]
    receipt = active["receipt"]
    health = state["health"]
    if type(artifact) is not dict or type(receipt) is not dict or type(health) is not dict:
        raise _RunnerFoundationError("joined state lacks terminal artifact, receipt, or health evidence")

    artifact_sha256 = f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    nonce = ledger_record["nonce"]
    try:
        destination = periodic_local_destination_fingerprint(nonce)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _RunnerFoundationError("local destination evidence is invalid") from exc
    state_updated = state["updated_at"]
    health_updated = health["updated_at"]
    finished_at = active["finished_at"]
    if not all(type(value) in {int, float} for value in (state_updated, health_updated, finished_at)):
        raise _RunnerFoundationError("joined state timestamps are invalid")
    if (
        float(state_updated) < float(finished_at)
        or float(health_updated) < float(finished_at)
        or health["status"] != "ready"
        or health["error_code"] is not None
        or health["error_text"] != ""
    ):
        raise _RunnerFoundationError("ready health evidence does not reach the delivery cut")

    expected = {
        "assistant_pid": assistant.pid,
        "assistant_start_identity": assistant.start_identity,
        "slot_id": active["slot_id"],
        "generation_id": active["generation_id"],
        "owner_token": active["owner_token"],
        "artifact_sha256": artifact["sha256"],
        "artifact_size": artifact["size"],
        "receipt_id": receipt["receipt_id"],
        "acknowledgement_sha256": receipt["acknowledgement_sha256"],
    }
    for field, value in expected.items():
        if ledger_record[field] != value:
            raise _RunnerFoundationError(f"ledger/state/process join mismatch: {field}")
    if (
        receipt["kind"] != "soak_local"
        or active["destination_fingerprint"] != destination
        or artifact_sha256 != ledger_record["artifact_sha256"]
        or len(artifact_bytes) != ledger_record["artifact_size"]
        or state["unresolved_delivery"] != []
    ):
        raise _RunnerFoundationError("local receipt/file/state authority does not agree")

    return _JoinedReceiptEvidence(
        assistant=assistant,
        assistant_generation=ledger_record["assistant_generation"],  # type: ignore[arg-type]
        sequence=ledger_record["sequence"],  # type: ignore[arg-type]
        slot_id=ledger_record["slot_id"],  # type: ignore[arg-type]
        generation_id=ledger_record["generation_id"],  # type: ignore[arg-type]
        owner_token=ledger_record["owner_token"],  # type: ignore[arg-type]
        artifact_sha256=ledger_record["artifact_sha256"],  # type: ignore[arg-type]
        receipt_id=ledger_record["receipt_id"],  # type: ignore[arg-type]
        acknowledgement_sha256=ledger_record["acknowledgement_sha256"],  # type: ignore[arg-type]
        ledger_record_sha256="sha256:"
        + hashlib.sha256(
            json.dumps(ledger_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest(),
        destination_fingerprint=destination,
        state_updated_at=float(state_updated),
        health_updated_at=float(health_updated),
    )


@dataclass(frozen=True, slots=True)
class _PrePostReceiptEvidence:
    pre_fault: _JoinedReceiptEvidence
    post_fault: _JoinedReceiptEvidence


def _validate_pre_post_receipts(
    *,
    pre_ledger_record: dict[str, object],
    pre_state_payload: dict[str, object],
    pre_artifact_bytes: bytes,
    pre_assistant_observation: _AssistantProcessObservation,
    post_ledger_record: dict[str, object],
    post_state_payload: dict[str, object],
    post_artifact_bytes: bytes,
    post_assistant_observation: _AssistantProcessObservation,
    expected_launcher_pid: int,
    ledger_records: tuple[dict[str, object], ...],
) -> _PrePostReceiptEvidence:
    """Build both joins internally, then require exact assistant replacement."""

    pre_fault = _validate_joined_receipt(
        ledger_record=pre_ledger_record,
        state_payload=pre_state_payload,
        artifact_bytes=pre_artifact_bytes,
        assistant_observation=pre_assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    post_fault = _validate_joined_receipt(
        ledger_record=post_ledger_record,
        state_payload=post_state_payload,
        artifact_bytes=post_artifact_bytes,
        assistant_observation=post_assistant_observation,
        expected_launcher_pid=expected_launcher_pid,
    )
    if (
        pre_ledger_record["nonce"] != post_ledger_record["nonce"]
        or pre_fault.destination_fingerprint != post_fault.destination_fingerprint
    ):
        raise _RunnerFoundationError("replacement assistant changed the retained local capability authority")
    if len(ledger_records) != 2:
        raise _RunnerFoundationError("qualification requires exactly two receipt ledger records")
    if any(type(item) is not dict or not _ArtifactReceiptSink._valid_ledger_record(item) for item in ledger_records):
        raise _RunnerFoundationError("qualification ledger contains invalid records")
    expected_ids = (pre_fault.receipt_id, post_fault.receipt_id)
    observed_hashes = tuple(
        "sha256:"
        + hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        for item in ledger_records
    )
    if (
        tuple(item["receipt_id"] for item in ledger_records) != expected_ids
        or observed_hashes != (pre_fault.ledger_record_sha256, post_fault.ledger_record_sha256)
        or len(set(expected_ids)) != 2
    ):
        raise _RunnerFoundationError("qualification ledger is duplicate, reordered, or incomplete")
    if (
        post_fault.assistant == pre_fault.assistant
        or pre_fault.sequence != 1
        or post_fault.sequence != 1
        or pre_fault.assistant_generation != 1
        or post_fault.assistant_generation != 2
        or post_fault.slot_id == pre_fault.slot_id
        or post_fault.generation_id == pre_fault.generation_id
        or post_fault.owner_token == pre_fault.owner_token
        or post_fault.state_updated_at <= pre_fault.state_updated_at
        or max(post_fault.health_updated_at, post_fault.state_updated_at)
        <= max(pre_fault.health_updated_at, pre_fault.state_updated_at)
    ):
        raise _RunnerFoundationError("replacement assistant lacks a strictly newer joined authority cut")
    return _PrePostReceiptEvidence(pre_fault, post_fault)


@dataclass(frozen=True, slots=True)
class _BridgeProcessObservation:
    identity: _ProcessIdentity
    parent_pid: int
    role: str
    alive: bool


@dataclass(frozen=True, slots=True)
class _AssistantProcessObservation:
    identity: _ProcessIdentity
    parent_pid: int
    role: str
    alive: bool


def _bind_positive_assistant_identity(
    observation: _AssistantProcessObservation,
    *,
    expected_launcher_pid: int,
) -> _ProcessIdentity:
    if type(observation.alive) is not bool or not observation.alive:
        raise _RunnerFoundationError("reported assistant process is not alive")
    if type(expected_launcher_pid) is not int or expected_launcher_pid <= 0:
        raise _RunnerFoundationError("launcher identity is invalid")
    if observation.parent_pid != expected_launcher_pid:
        raise _RunnerFoundationError("reported assistant is not a direct launcher child")
    if observation.role != "assistant":
        raise _RunnerFoundationError("reported PID is not the allowlisted assistant role")
    return observation.identity


def _bind_positive_bridge_identity(
    record: _BridgeHandshakeRecord,
    observation: _BridgeProcessObservation,
) -> _ProcessIdentity:
    """Bind reported PID to one positive direct-child observer identity."""

    if type(observation.alive) is not bool or not observation.alive:
        raise _RunnerFoundationError("reported bridge process is not alive")
    if observation.identity.pid != record.bridge_pid:
        raise _RunnerFoundationError("observer bridge PID contradicts launcher record")
    if type(observation.parent_pid) is not int or observation.parent_pid != record.launcher_pid:
        raise _RunnerFoundationError("reported bridge is not a direct launcher child")
    if observation.role != "zmq_bridge":
        raise _RunnerFoundationError("reported PID is not the allowlisted bridge role")
    return observation.identity


class _BridgeEpochGuard:
    """Pure terminal guard for post-handshake PID/start/restart stability."""

    __slots__ = ("_identity", "_restart_count", "_terminal")

    def __init__(self, identity: _ProcessIdentity, restart_count: int) -> None:
        if type(restart_count) is not int or restart_count != 1:
            raise _RunnerFoundationError("bridge epoch must begin at restart count one")
        self._identity = identity
        self._restart_count = restart_count
        self._terminal = False

    def observe(self, identity: _ProcessIdentity, *, restart_count: int) -> None:
        if self._terminal:
            raise _RunnerFoundationError("bridge epoch guard is terminal")
        if type(restart_count) is not int or identity != self._identity or restart_count != self._restart_count:
            self._terminal = True
            raise _RunnerFoundationError("bridge PID/start identity changed or restarted")


def _parse_bridge_handshake(
    payload: bytes,
    *,
    expected_nonce: str,
    expected_launcher_pid: int,
    received_before_deadline: bool,
) -> _BridgeHandshakeRecord:
    """Parse one launcher-owned bridge record without granting runner authority."""

    if not received_before_deadline:
        raise _RunnerFoundationError("bridge handshake arrived after its deadline")
    if not payload or len(payload) > _MAX_BRIDGE_HANDSHAKE_BYTES or payload.count(b"\n") != 1:
        raise _RunnerFoundationError("bridge handshake is missing, duplicate, or oversized")
    if not payload.endswith(b"\n"):
        raise _RunnerFoundationError("bridge handshake record is incomplete")
    try:
        value = json.loads(payload[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _RunnerFoundationError("bridge handshake is not canonical JSON") from exc
    expected_keys = {"schema", "version", "nonce", "launcher_pid", "bridge_pid", "restart_count"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise _RunnerFoundationError("bridge handshake keys are invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if canonical != payload:
        raise _RunnerFoundationError("bridge handshake is not canonical")
    if (
        value["schema"] != _BRIDGE_HANDSHAKE_SCHEMA
        or type(value["version"]) is not int
        or value["version"] != _BRIDGE_HANDSHAKE_VERSION
    ):
        raise _RunnerFoundationError("bridge handshake schema is invalid")
    nonce = value["nonce"]
    launcher_pid = value["launcher_pid"]
    bridge_pid = value["bridge_pid"]
    restart_count = value["restart_count"]
    if not isinstance(nonce, str) or nonce != expected_nonce or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise _RunnerFoundationError("bridge handshake nonce mismatch")
    if launcher_pid != expected_launcher_pid or isinstance(launcher_pid, bool) or launcher_pid <= 0:
        raise _RunnerFoundationError("bridge handshake launcher PID mismatch")
    if isinstance(bridge_pid, bool) or not isinstance(bridge_pid, int) or bridge_pid <= 0 or bridge_pid == launcher_pid:
        raise _RunnerFoundationError("bridge handshake bridge PID is invalid")
    if type(restart_count) is not int or restart_count != 1:
        raise _RunnerFoundationError("bridge restarted before positive identity acceptance")
    return _BridgeHandshakeRecord(nonce, launcher_pid, bridge_pid, restart_count)


@dataclass(frozen=True, slots=True)
class _StreamEvidence:
    byte_count: int
    sha256: str
    output_complete: bool


class _BoundedStreamDigest:
    """Continuously hash bounded output without retaining its bytes."""

    __slots__ = ("_byte_count", "_complete", "_finalized", "_hash", "_limit")

    def __init__(self, *, limit: int = _MAX_STREAM_BYTES) -> None:
        if isinstance(limit, bool) or limit <= 0 or limit > _MAX_STREAM_BYTES:
            raise _RunnerFoundationError("stream limit is outside the reviewed bound")
        self._limit = limit
        self._byte_count = 0
        self._hash = hashlib.sha256()
        self._complete = True
        self._finalized = False

    def feed(self, chunk: bytes) -> None:
        if self._finalized:
            raise _RunnerFoundationError("finalized stream cannot accept bytes")
        if not isinstance(chunk, bytes):
            raise TypeError("stream chunk must be bytes")
        if not self._complete:
            raise _RunnerFoundationError("overflowed stream is terminal")
        next_count = self._byte_count + len(chunk)
        if next_count > self._limit:
            self._complete = False
            raise _RunnerFoundationError("stream output exceeded the reviewed bound")
        self._hash.update(chunk)
        self._byte_count = next_count

    def finalize(self) -> _StreamEvidence:
        if self._finalized:
            raise _RunnerFoundationError("stream evidence can be finalized only once")
        self._finalized = True
        return _StreamEvidence(
            byte_count=self._byte_count,
            sha256=f"sha256:{self._hash.hexdigest()}",
            output_complete=self._complete,
        )


def _decode_complete_output(stdout: _StreamEvidence, payload: bytes) -> str:
    if not stdout.output_complete or len(payload) != stdout.byte_count:
        raise _RunnerFoundationError("parser requires complete runner-owned output")
    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != stdout.sha256:
        raise _RunnerFoundationError("output bytes contradict streaming evidence")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _RunnerFoundationError("pytest output is not strict UTF-8") from exc


def _parse_exact_collection(
    *,
    stdout_evidence: _StreamEvidence,
    stdout: bytes,
    stderr_evidence: _StreamEvidence,
    stderr: bytes,
    exit_code: int,
) -> tuple[str, ...]:
    if exit_code != 0:
        raise _RunnerFoundationError("exact-six collection exit code is nonzero")
    out = _decode_complete_output(stdout_evidence, stdout)
    err = _decode_complete_output(stderr_evidence, stderr)
    if err.strip():
        raise _RunnerFoundationError("exact-six collection wrote stderr")
    lowered = out.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PYTEST_MARKERS):
        raise _RunnerFoundationError("exact-six collection contains a forbidden pytest outcome")
    lines = tuple(line.strip() for line in out.splitlines() if line.strip())
    nodes = tuple(line for line in lines if line.startswith(f"{_TEST_FILE}::"))
    summaries = tuple(line for line in lines if _COLLECTION_SUMMARY_RE.fullmatch(line))
    if nodes != _EXACT_NODE_IDS or len(summaries) != 1:
        raise _RunnerFoundationError("collection is not the exact ordered six-node matrix")
    if len(lines) != len(nodes) + 1:
        raise _RunnerFoundationError("collection output contains unexpected records")
    return nodes


def _validate_exact_execution(
    *,
    stdout_evidence: _StreamEvidence,
    stdout: bytes,
    stderr_evidence: _StreamEvidence,
    stderr: bytes,
    exit_code: int,
) -> None:
    if exit_code != 0:
        raise _RunnerFoundationError("exact-six execution exit code is nonzero")
    out = _decode_complete_output(stdout_evidence, stdout)
    err = _decode_complete_output(stderr_evidence, stderr)
    if err.strip():
        raise _RunnerFoundationError("exact-six execution wrote stderr")
    lowered = out.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_PYTEST_MARKERS):
        raise _RunnerFoundationError("exact-six execution contains a forbidden pytest outcome")
    lines = tuple(line.strip() for line in out.splitlines() if line.strip())
    if len(lines) != 2 or _PROGRESS_RE.fullmatch(lines[0]) is None or _SUMMARY_RE.fullmatch(lines[1]) is None:
        raise _RunnerFoundationError("execution output is not the exact six-pass result")


@dataclass(frozen=True, slots=True)
class _CompletedCommand:
    stdout_evidence: _StreamEvidence
    stdout: bytes
    stderr_evidence: _StreamEvidence
    stderr: bytes
    exit_code: int


def _require_posix_exact_six() -> None:
    if os.name != "posix" or sys.platform != "linux":
        raise _RunnerActivationDisabled("exact-six execution authority requires Linux subreaper ownership")


def _settle_process_group(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    """Boundedly terminate the runner-owned session and reap its leader."""

    pid = process.pid
    sigkill = getattr(signal, "SIGKILL", 9)

    def recheck() -> None:
        try:
            observer.recheck_exact(expected)
        except AttributeError:
            if observer.identity_for_pid(pid) != expected:
                raise _RunnerFoundationError("exact-six process identity changed; refusing numeric PGID") from None

    def group_exists() -> bool:
        recheck()
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        return True

    recheck()
    if os.getpgid(pid) != pid:
        raise _RunnerFoundationError("exact-six child no longer owns its process group")
    recheck()
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    while group_exists() and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
    if group_exists():
        recheck()
        try:
            os.killpg(pid, sigkill)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_PROCESS_GROUP_GRACE_S)
    except subprocess.TimeoutExpired as exc:
        raise _RunnerFoundationError("exact-six process leader did not settle") from exc


def _settle_owned_tree_once(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    descendants = observer.descendants(expected)
    for identity in reversed(descendants):
        observer.signal_exact_for_cleanup(identity, signal.SIGTERM)
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    while descendants and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
        descendants = observer.descendants(expected)
    for identity in reversed(descendants):
        observer.signal_exact_for_cleanup(identity, getattr(signal, "SIGKILL", 9))
    deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
    while descendants and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
        descendants = observer.descendants(expected)
    if descendants:
        raise _RunnerFoundationError("owned exact-six descendants did not settle")
    _settle_process_group(process, observer=observer, expected=expected)


def _settle_owned_tree(
    process: subprocess.Popen[bytes],
    *,
    observer: _LockedPsutilObserver,
    expected: _ProcessIdentity,
) -> None:
    """Retry settlement once if cancellation interrupts cleanup, then propagate it."""

    interrupted: BaseException | None = None
    try:
        _settle_owned_tree_once(process, observer=observer, expected=expected)
    except BaseException as exc:
        if isinstance(exc, Exception):
            raise
        interrupted = exc
    finally:
        if interrupted is not None:
            _settle_owned_tree_once(process, observer=observer, expected=expected)
    if interrupted is not None:
        raise interrupted


def _execute_bounded_process(
    argv: tuple[str, ...],
    *,
    observer: _LockedPsutilObserver,
    snapshot: _ExecutionSnapshot,
    timeout_s: float = _EXACT_SIX_TIMEOUT_S,
) -> _CompletedCommand:
    """Run one fixed pytest command with bounded output and session cleanup."""

    _require_posix_exact_six()
    if argv not in {_COLLECTION_ARGV, _EXECUTION_ARGV}:
        raise _RunnerFoundationError("runner command is not fixed exact-six argv")
    if type(timeout_s) not in {int, float} or not math.isfinite(float(timeout_s)) or not 0 < timeout_s <= 300:
        raise _RunnerFoundationError("exact-six timeout is outside the reviewed bound")
    status_read, status_write = os.pipe()
    release_read, release_write = os.pipe()
    start_read, start_write = os.pipe()
    supervisor_argv = (
        str(snapshot.interpreter),
        "-I",
        "-c",
        _SUPERVISOR_CODE,
        str(status_write),
        str(release_read),
        str(start_read),
        *argv,
    )
    try:
        process = subprocess.Popen(
            supervisor_argv,
            cwd=snapshot.root,
            env=snapshot.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(status_write, release_read, start_read),
            start_new_session=True,
        )
    except BaseException:
        for fd in (status_read, status_write, release_read, release_write, start_read, start_write):
            os.close(fd)
        raise
    os.close(status_write)
    os.close(release_read)
    os.close(start_read)
    try:
        identity = observer.identity_for_pid(process.pid)
    except BaseException:
        os.close(start_write)
        os.close(release_write)
        os.close(status_read)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        try:
            process.wait(timeout=_PROCESS_GROUP_GRACE_S)
        except subprocess.TimeoutExpired:
            pass
        raise
    try:
        os.write(start_write, b"G")
    except BaseException:
        os.close(start_write)
        _settle_owned_tree(process, observer=observer, expected=identity)
        os.close(release_write)
        os.close(status_read)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        raise
    else:
        os.close(start_write)
    if process.stdout is None or process.stderr is None:
        _settle_owned_tree(process, observer=observer, expected=identity)
        raise _RunnerFoundationError("exact-six pipes are unavailable")
    stdout_digest = _BoundedStreamDigest()
    stderr_digest = _BoundedStreamDigest()
    stdout = bytearray()
    stderr = bytearray()
    status = bytearray()
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + float(timeout_s)
    try:
        if observer.identity_for_pid(process.pid) != identity:
            raise _RunnerFoundationError("exact-six process identity changed before PGID probe")
        if os.getpgid(process.pid) != process.pid:
            raise _RunnerFoundationError("exact-six child does not own its process group")
        selector.register(process.stdout, selectors.EVENT_READ, ("stream", stdout_digest, stdout))
        selector.register(process.stderr, selectors.EVENT_READ, ("stream", stderr_digest, stderr))
        selector.register(status_read, selectors.EVENT_READ, ("status", None, status))
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _RunnerFoundationError("exact-six command timed out")
            for key, _events in selector.select(min(remaining, 0.25)):
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                kind, digest, retained = key.data
                if kind == "status" and len(retained) + len(chunk) > _STATUS_STRUCT.size:
                    raise _RunnerFoundationError("exact-six supervisor status is oversized")
                if digest is not None:
                    digest.feed(chunk)
                retained.extend(chunk)
        if len(status) != _STATUS_STRUCT.size:
            raise _RunnerFoundationError("exact-six supervisor status is incomplete")
        exit_code = _STATUS_STRUCT.unpack(status)[0]
        quiescence_deadline = time.monotonic() + _PROCESS_GROUP_GRACE_S
        descendants = observer.descendants(identity)
        while descendants and time.monotonic() < quiescence_deadline:
            time.sleep(min(0.05, max(0.001, quiescence_deadline - time.monotonic())))
            descendants = observer.descendants(identity)
        if descendants:
            raise _RunnerFoundationError("exact-six child left owned descendants")
        if observer.group_members(process.pid) != (identity,):
            raise _RunnerFoundationError("exact-six child left process-group survivors")
    except BaseException:
        _settle_owned_tree(process, observer=observer, expected=identity)
        raise
    else:
        _settle_owned_tree(process, observer=observer, expected=identity)
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        os.close(status_read)
        os.close(release_write)
    return _CompletedCommand(
        stdout_digest.finalize(),
        bytes(stdout),
        stderr_digest.finalize(),
        bytes(stderr),
        exit_code,
    )


class _ExactSixAuthority:
    __slots__ = ()

    def __new__(cls) -> _ExactSixAuthority:
        del cls
        raise _RunnerFoundationError("exact-six authority cannot be caller-constructed")


class _ExactSixExecutionRegistry:
    """Own completion registration; calling execute necessarily runs both commands."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: dict[int, tuple[_ExactSixAuthority, Any, dict[str, object]]] = {}

    def execute(self, evidence: Any) -> dict[str, object]:
        _require_posix_exact_six()
        try:
            import psutil
        except ImportError as exc:
            raise _RunnerActivationDisabled("locked psutil observer is unavailable") from exc
        observer = _LockedPsutilObserver(psutil)
        collector = _CleanShaCollector(_REPO_ROOT)
        git_sha = collector.observe(_ShaBoundary.BEFORE_COLLECTION).git_sha
        with _sealed_execution_snapshot(git_sha) as snapshot:
            collection = _execute_bounded_process(_COLLECTION_ARGV, observer=observer, snapshot=snapshot)
            _parse_exact_collection(
                stdout_evidence=collection.stdout_evidence,
                stdout=collection.stdout,
                stderr_evidence=collection.stderr_evidence,
                stderr=collection.stderr,
                exit_code=collection.exit_code,
            )
            snapshot.assert_sealed()
            execution = _execute_bounded_process(_EXECUTION_ARGV, observer=observer, snapshot=snapshot)
            _validate_exact_execution(
                stdout_evidence=execution.stdout_evidence,
                stdout=execution.stdout,
                stderr_evidence=execution.stderr_evidence,
                stderr=execution.stderr,
                exit_code=execution.exit_code,
            )
            snapshot.assert_sealed()
        payload: dict[str, object] = {
            "schema": "cryodaq-exact-six-result/v1",
            "command": list(_EXECUTION_ARGV),
            "test_identity": f"{_TEST_FILE}::exact-six",
            "git_sha": git_sha,
            "exit_code": execution.exit_code,
            "status": "PASS",
        }
        authority = object.__new__(_ExactSixAuthority)
        self._records[id(authority)] = (authority, evidence, payload)
        evidence._accept_exact_six_result(authority)
        return payload

    def consume(self, authority: object, evidence: Any) -> dict[str, object]:
        record = self._records.get(id(authority))
        if record is None or record[0] is not authority or record[1] is not evidence:
            raise _RunnerFoundationError("exact-six authority is unregistered, spent, or bound to another Evidence")
        del self._records[id(authority)]
        return record[2]


_EXACT_SIX_EXECUTIONS = _ExactSixExecutionRegistry()


def _collect_and_execute_exact_six(evidence: Any) -> dict[str, object]:
    return _EXACT_SIX_EXECUTIONS.execute(evidence)


def _consume_exact_six_authority(authority: object, evidence: Any) -> dict[str, object]:
    return _EXACT_SIX_EXECUTIONS.consume(authority, evidence)


class _CleanupPhase(StrEnum):
    IDLE = "idle"
    REQUESTED = "requested"
    COMPLETE = "complete"
    TERMINAL_IDENTITY_MISMATCH = "terminal_identity_mismatch"


@dataclass(frozen=True, slots=True)
class _CleanupEvidence:
    phase: _CleanupPhase
    process_group_id: int
    leader: _ProcessIdentity
    descendants: tuple[_ProcessIdentity, ...]
    forced: bool


class _CancellationCleanupContract:
    """Pure cleanup-once state; R2 performs signals and reaping."""

    __slots__ = ("_descendants", "_forced", "_leader", "_phase", "_process_group_id")

    def __init__(
        self,
        process_group_id: int,
        leader: _ProcessIdentity,
        descendants: tuple[_ProcessIdentity, ...],
    ) -> None:
        if isinstance(process_group_id, bool) or process_group_id <= 0:
            raise _RunnerFoundationError("process group ID must be positive")
        if not isinstance(leader, _ProcessIdentity) or leader.pid != process_group_id:
            raise _RunnerFoundationError("declared leader must own the process-group ID")
        descendants = tuple(descendants)
        if sum(item == leader for item in descendants) != 1:
            raise _RunnerFoundationError("cleanup must contain exactly one declared leader identity")
        if len({item.pid for item in descendants}) != len(descendants):
            raise _RunnerFoundationError("cleanup descendant PIDs must be unique across epochs")
        self._process_group_id = process_group_id
        self._leader = leader
        self._descendants = tuple(descendants)
        self._phase = _CleanupPhase.IDLE
        self._forced = False

    def request(self) -> _CleanupEvidence:
        if self._phase is not _CleanupPhase.IDLE:
            raise _RunnerFoundationError("cleanup can be requested only once")
        self._phase = _CleanupPhase.REQUESTED
        return self.evidence()

    def complete(self, *, forced: bool) -> _CleanupEvidence:
        if self._phase is not _CleanupPhase.REQUESTED:
            raise _RunnerFoundationError("cleanup must be requested before completion")
        if not isinstance(forced, bool):
            raise TypeError("forced must be a bool")
        self._forced = forced
        self._phase = _CleanupPhase.COMPLETE
        return self.evidence()

    def record_identity_recheck(self, observed: _ProcessIdentity) -> None:
        """Require exact PID/start continuity before each future R2 operation.

        R2 must call this immediately before every signal and reap. A missing
        PID, changed start identity, or PID reuse is terminal; this R1 method
        intentionally performs no process operation itself.
        """

        if self._phase is not _CleanupPhase.REQUESTED:
            raise _RunnerFoundationError("identity recheck requires requested cleanup")
        expected = next((item for item in self._descendants if item.pid == observed.pid), None)
        if expected != observed:
            self._phase = _CleanupPhase.TERMINAL_IDENTITY_MISMATCH
            raise _RunnerFoundationError("PID/start identity mismatch is terminal; do not signal or reap")

    def evidence(self) -> _CleanupEvidence:
        return _CleanupEvidence(
            self._phase,
            self._process_group_id,
            self._leader,
            self._descendants,
            self._forced,
        )


class _PosixSoakRunner:
    """Non-runnable shell retained until integrated short-run acceptance."""

    def run(self) -> None:
        raise _RunnerActivationDisabled(
            "H4 runner activation requires R2/R3 integration, the locked observer, "
            "and reviewed real POSIX short-run evidence"
        )


__all__: tuple[str, ...] = ()
