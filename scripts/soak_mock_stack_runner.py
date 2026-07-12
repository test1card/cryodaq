"""Hard-disabled POSIX soak runner provenance foundation (H4 R1).

This module contains pure types and validators only.  It cannot launch a
process, create execution authority, write evidence, or publish a successful
qualification.  R2/R3 must integrate real process handles, the locked observer,
and the accepted soak foundation before activation is reviewed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

_TEST_FILE: Final = "tests/integration/test_periodic_png_multiprocess.py"
_COLLECTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
    "--collect-only",
    "-q",
    _TEST_FILE,
)
_EXECUTION_ARGV: Final = (
    ".venv/bin/python",
    "-m",
    "pytest",
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
_MAX_START_IDENTITY_BYTES: Final = 128
_BRIDGE_HANDSHAKE_SCHEMA: Final = "cryodaq.soak.bridge-identity"
_BRIDGE_HANDSHAKE_VERSION: Final = 1
_MAX_BRIDGE_HANDSHAKE_BYTES: Final = 512
_BRIDGE_FD_ENV: Final = "CRYODAQ_SOAK_BRIDGE_FD"
_BRIDGE_NONCE_ENV: Final = "CRYODAQ_SOAK_BRIDGE_NONCE"


class _RunnerFoundationError(ValueError):
    """Pure validation failed; this never represents production authority."""


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
) -> str:
    if tuple(item.boundary for item in observations) != tuple(_ShaBoundary):
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


@dataclass(frozen=True, slots=True)
class _BridgeProcessObservation:
    identity: _ProcessIdentity
    parent_pid: int
    role: str
    alive: bool


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
    """Non-runnable R1 shell retained solely for the future fixed runner."""

    def run(self) -> None:
        raise _RunnerActivationDisabled(
            "H4 runner activation requires R2/R3, locked observer dependency, "
            "foundation integration, and real POSIX evidence"
        )


__all__: tuple[str, ...] = ()
