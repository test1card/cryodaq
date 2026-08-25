"""Deterministic production-path guards for the Ubuntu 22.04 fd-2 shutdown blocker.

Measured failure being guarded: on Ubuntu 22.04 an abruptly dead launcher-owned
engine left the launcher stderr pipe open because the USBTMC ``multiprocessing``
spawn descendant inherits OS descriptor 2 and the multiprocessing ResourceTracker
separately preserves ``sys.stderr.fileno()``. The launcher pump never received
EOF and restart remained in HOLD.

The external-effect tests here do NOT fake multiprocessing, ResourceTracker,
descriptors, pipes, or the launcher pump: a real ``subprocess.Popen(stderr=PIPE)``
child runs the real production bootstrap through the real ``cryodaq.engine``
gate and logging init, exercises the REAL ``USBTMCTransport`` spawn path against
the child-importable fake pyvisa stub, emits one diagnostic through the
production stderr path, and is then SIGKILLed while its descendants stay alive.

Two independent falsifying controls prove the harness detects each mutation:
leaving OS fd 2 attached must fail, and exposing the private duplicate through
``fileno()`` must fail.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import signal
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import pytest

import cryodaq
from cryodaq.engine import _requires_launcher_fd2_isolation as engine_gate
from cryodaq.launcher import (
    _EngineStderrAcquisitionOwner,
    _EngineStderrStreamOwner,
    _OwnerSettlementState,
    _pump_engine_stderr,
)
from tests.integration._fd2_engine_simulant import (
    EXIT_AFTER_MARKER_ENV,
    EXPOSE_PRIVATE_FILENO_ENV,
    INSTALL_ISOLATION_ENV,
)

_POSIX = os.name == "posix"
_LINUX = _POSIX and sys.platform == "linux"
_WINDOWS = sys.platform == "win32"
_SRC_ROOT = Path(cryodaq.__file__).resolve().parents[1]
_SIMULANT_PATH = Path(__file__).resolve().parent / "_fd2_engine_simulant.py"
_PUMP_LOGGER_NAME = "cryodaq.launcher.engine_stderr"
_PUMP_STDERR_RECORD_PREFIX = "engine child stderr record received"
_MARKER_TIMEOUT_S = 30.0
_EOF_BUDGET_S = 2.0
_SETTLEMENT_TIMEOUT_S = 8.0
_PIPE_TARGET_RE = re.compile(r"^pipe:\[(\d+)\]$")
_AUTHORITY_KEY_PREFIXES = (
    "CRYODAQ_ENGINE_",
    "CRYODAQ_REPLAY_",
    "CRYODAQ_SOAK_",
)


class _CaptureRecordsHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@dataclass(slots=True)
class _SimulantRun:
    process: subprocess.Popen[bytes]
    marker: dict[str, Any]
    stream_owner: _EngineStderrStreamOwner
    acquisition_owner: _EngineStderrAcquisitionOwner
    pump_thread: threading.Thread
    capture: _CaptureRecordsHandler
    prior_propagate: bool
    launch_pipe_inode: int | None = field(default=None)


def _simulant_base_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["CRYODAQ_STATE_ROOT"] = str(Path(tmp_path) / "state")
    for key in list(env):
        if key.startswith(_AUTHORITY_KEY_PREFIXES) or key in {
            "CRYODAQ_FD2_TEST_INSTALL_ISOLATION",
            "CRYODAQ_FD2_TEST_EXPOSE_PRIVATE_FILENO",
            "CRYODAQ_FD2_TEST_EXIT_AFTER_MARKER",
        }:
            env.pop(key, None)
    return env


def _launcher_authority_env() -> tuple[dict[str, str], int, int]:
    read_fd, write_fd = os.pipe()
    if _WINDOWS:
        import msvcrt

        os.set_inheritable(write_fd, True)
        encoded = f"handle:{msvcrt.get_osfhandle(write_fd)}"
    else:
        os.set_inheritable(write_fd, True)
        encoded = f"fd:{write_fd}"
    authority = {
        "CRYODAQ_ENGINE_INSTANCE_ID": uuid.uuid4().hex,
        "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY": secrets.token_hex(32),
        "CRYODAQ_ENGINE_READY_NONCE": secrets.token_hex(32),
        "CRYODAQ_CHILD_READY_CHANNEL": encoded,
    }
    return authority, read_fd, write_fd


def _start_line_reader(stream: Any) -> tuple[Queue[Any], threading.Thread]:
    lines: Queue[Any] = Queue()

    def _read() -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    reader = threading.Thread(target=_read, name="fd2-marker-reader", daemon=True)
    reader.start()
    return lines, reader


def _wait_for_marker(lines: Queue[Any]) -> dict[str, Any]:
    deadline = time.monotonic() + _MARKER_TIMEOUT_S
    seen: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.05)
        except Empty:
            continue
        if line is None:
            break
        seen.append(line if isinstance(line, str) else line.decode("utf-8", "replace"))
        candidate = seen[-1].strip()
        if candidate.startswith("{"):
            try:
                document = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(document, dict) and type(document.get("pid")) is int:
                return document
    raise AssertionError(f"engine simulant marker did not arrive; stdout so far: {seen!r}")


def _attach_pump(run_process: subprocess.Popen[bytes]) -> tuple[_SimulantRun, logging.Logger]:
    capture = _CaptureRecordsHandler()
    pump_logger = logging.getLogger(_PUMP_LOGGER_NAME)
    prior_propagate = pump_logger.propagate
    pump_logger.addHandler(capture)
    pump_logger.propagate = False
    acquisition_owner = _EngineStderrAcquisitionOwner(run_process.stderr)
    stream_owner = acquisition_owner.bind_exact()
    pump_thread = threading.Thread(
        target=_pump_engine_stderr,
        args=(stream_owner, pump_logger),
        name="fd2-launcher-pump",
        daemon=True,
    )
    run = _SimulantRun(
        process=run_process,
        marker={},
        stream_owner=stream_owner,
        acquisition_owner=acquisition_owner,
        pump_thread=pump_thread,
        capture=capture,
        prior_propagate=prior_propagate,
    )
    return run, pump_logger


def _detach_pump(run: _SimulantRun, pump_logger: logging.Logger) -> None:
    pump_logger.removeHandler(run.capture)
    pump_logger.propagate = run.prior_propagate


def _spawn_simulant(env: dict[str, str], inherit_ready_fd: int | None = None) -> subprocess.Popen[bytes]:
    extra_spawn_arguments: dict[str, Any] = {}
    if inherit_ready_fd is not None:
        if _WINDOWS:
            import msvcrt

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {"handle_list": [msvcrt.get_osfhandle(inherit_ready_fd)]}
            extra_spawn_arguments["startupinfo"] = startupinfo
        else:
            extra_spawn_arguments["pass_fds"] = (inherit_ready_fd,)
    return subprocess.Popen(
        [sys.executable, str(_SIMULANT_PATH)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **extra_spawn_arguments,
    )


def _proc_exists(pid: int) -> bool:
    return os.path.isdir(f"/proc/{pid}")


def _pid_cmdline(pid: int) -> bytes:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def _pipe_inode_descriptors(pid: int, launch_pipe_inode: int) -> list[int]:
    found: list[int] = []
    fd_dir = f"/proc/{pid}/fd"
    try:
        entries = os.listdir(fd_dir)
    except OSError:
        return found
    for entry in entries:
        try:
            target = os.readlink(os.path.join(fd_dir, entry))
        except OSError:
            continue
        match = _PIPE_TARGET_RE.match(target)
        if match is not None and int(match.group(1)) == launch_pipe_inode:
            found.append(int(entry))
    return found


def _kill_exact(pid: int | None) -> bool:
    if type(pid) is not int or pid <= 0 or not _proc_exists(pid):
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


def _resolve_tracker_pid(run: _SimulantRun) -> int | None:
    candidate = run.marker.get("tracker_pid")
    if type(candidate) is int and candidate > 0 and _proc_exists(candidate):
        return candidate
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        numeric = int(pid)
        try:
            with open(f"/proc/{numeric}/stat", "rb") as handle:
                stat_raw = handle.read()
        except OSError:
            continue
        close_index = stat_raw.rfind(b")")
        fields = stat_raw[close_index + 2 :].split()
        if len(fields) < 2:
            continue
        try:
            parent_pid = int(fields[1])
        except ValueError:
            continue
        if parent_pid != run.process.pid:
            continue
        if b"resource_tracker" in _pid_cmdline(numeric):
            return numeric
    return None


def _run_blocker_scenario(tmp_path: Path, *, install_isolation: bool, expose_fileno: bool) -> _SimulantRun:
    env = _simulant_base_env(tmp_path)
    authority, ready_read_fd, ready_write_fd = _launcher_authority_env()
    env.update(authority)
    env[INSTALL_ISOLATION_ENV] = "1" if install_isolation else "0"
    if expose_fileno:
        env[EXPOSE_PRIVATE_FILENO_ENV] = "1"
    try:
        process = _spawn_simulant(env, inherit_ready_fd=ready_write_fd)
    finally:
        for descriptor in (ready_read_fd, ready_write_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass
    marker_lines, _reader_thread = _start_line_reader(process.stdout)
    run, pump_logger = _attach_pump(process)
    try:
        run.marker = _wait_for_marker(marker_lines)
        if _LINUX:
            run.launch_pipe_inode = os.fstat(process.stderr.fileno()).st_ino
        run.pump_thread.start()
    except BaseException:
        _kill_exact(run.marker.get("pid"))
        _detach_pump(run, pump_logger)
        raise
    return run


def _settle_scenario_after_kill(run: _SimulantRun, pump_logger: logging.Logger) -> float:
    started = time.monotonic()
    run.pump_thread.join(_EOF_BUDGET_S + 0.5)
    elapsed = time.monotonic() - started
    try:
        run.process.stdout.close()
    except OSError:
        pass
    try:
        run.process.stderr.close()
    except OSError:
        pass
    run.process.wait(timeout=5)
    _detach_pump(run, pump_logger)
    return elapsed


def _cleanup_descendants(run: _SimulantRun) -> None:
    for key in ("pid", "worker_pid", "tracker_pid", "holder_pid"):
        _kill_exact(run.marker.get(key))


def _wait_for_pump_stderr_record(run: _SimulantRun, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in run.capture.messages:
            if message.startswith(_PUMP_STDERR_RECORD_PREFIX):
                return message
        time.sleep(0.05)
    raise AssertionError(
        "probe diagnostic never reached the launcher pump; "
        f"records={run.capture.messages!r} child_returncode={run.process.poll()}"
    )


def _assert_probe_reached_launcher_pipe(run: _SimulantRun) -> None:
    """Prove the probe crossed child stderr into the launch pipe and the real
    production pump. The production pump publishes exactly one content-free
    record per non-empty child stderr line (launcher._pump_engine_stderr), and
    the simulant emits exactly one diagnostic through setup_logging's stderr
    handler, so a settled pump record is that probe's production observable.
    Waiting here also removes the start-versus-assert race on the pump thread."""
    _wait_for_pump_stderr_record(run, _MARKER_TIMEOUT_S)


@pytest.mark.skipif(not _LINUX, reason="external-effect guard requires Linux /proc and POSIX fd semantics")
def test_abruptly_killed_launcher_engine_releases_stderr_pipe_within_two_seconds(tmp_path: Path) -> None:
    run, pump_logger = _run_blocker_scenario(tmp_path, install_isolation=True, expose_fileno=False)
    try:
        marker = run.marker
        assert marker["isolation_applied"] is True
        assert marker["stderr_fileno"] is None
        assert marker["worker_pid"] is not None
        worker_pid = int(marker["worker_pid"])
        tracker_pid = _resolve_tracker_pid(run)
        assert isinstance(tracker_pid, int) and tracker_pid > 0
        assert _proc_exists(worker_pid) and b"spawn_main" in _pid_cmdline(worker_pid)
        assert _proc_exists(tracker_pid) and b"resource_tracker" in _pid_cmdline(tracker_pid)
        _assert_probe_reached_launcher_pipe(run)
        engine_fd2_target = os.readlink(f"/proc/{marker['pid']}/fd/2")
        assert engine_fd2_target == os.devnull
        pre_kill_violations = {
            "worker": _pipe_inode_descriptors(worker_pid, run.launch_pipe_inode),
            "tracker": _pipe_inode_descriptors(tracker_pid, run.launch_pipe_inode),
        }
        assert not any(pre_kill_violations.values()), (
            f"while the engine lived, descendants already inherited the launch pipe: {pre_kill_violations}"
        )
        assert _kill_exact(int(marker["pid"])) is True
        run.process.wait(timeout=5)
        assert run.process.returncode == -signal.SIGKILL
        elapsed = _settle_scenario_after_kill(run, pump_logger)
        assert not run.pump_thread.is_alive(), "launcher pump never reached EOF after engine SIGKILL"
        assert elapsed <= _EOF_BUDGET_S + 0.25, f"pump termination took {elapsed:.3f}s (budget {_EOF_BUDGET_S}s)"
        assert run.stream_owner.settlement_state is _OwnerSettlementState.SETTLED
        assert run.acquisition_owner.settlement_state is _OwnerSettlementState.SETTLED
        assert run.stream_owner.pump_failure is None
        assert run.stream_owner.close_failure is None
        post_kill_violations: dict[str, list[int]] = {}
        if _proc_exists(tracker_pid):
            post_kill_violations["tracker"] = _pipe_inode_descriptors(tracker_pid, run.launch_pipe_inode)
        if _proc_exists(worker_pid):
            post_kill_violations["worker"] = _pipe_inode_descriptors(worker_pid, run.launch_pipe_inode)
        assert not any(post_kill_violations.values()), (
            f"surviving descendants still hold the launch pipe after engine death: {post_kill_violations}"
        )
    finally:
        _cleanup_descendants(run)
        run.pump_thread.join(_SETTLEMENT_TIMEOUT_S)
        _detach_pump(run, pump_logger)


@pytest.mark.skipif(not _LINUX, reason="mutation control requires Linux /proc and POSIX fd semantics")
def test_control_leaving_fd2_attached_must_fail_detected_as_leak(tmp_path: Path) -> None:
    run, pump_logger = _run_blocker_scenario(tmp_path, install_isolation=False, expose_fileno=False)
    try:
        marker = run.marker
        assert marker["isolation_applied"] is False
        assert marker["stderr_fileno"] == 2
        worker_pid = int(marker["worker_pid"])
        tracker_pid = _resolve_tracker_pid(run)
        assert isinstance(tracker_pid, int) and tracker_pid > 0
        assert _proc_exists(worker_pid) and _proc_exists(tracker_pid)
        engine_fd2_target = os.readlink(f"/proc/{marker['pid']}/fd/2")
        match = _PIPE_TARGET_RE.match(engine_fd2_target)
        assert match is not None and int(match.group(1)) == run.launch_pipe_inode
        _assert_probe_reached_launcher_pipe(run)
        held_by_worker_pre_kill = _pipe_inode_descriptors(worker_pid, run.launch_pipe_inode)
        held_by_tracker_pre_kill = _pipe_inode_descriptors(tracker_pid, run.launch_pipe_inode)
        assert held_by_worker_pre_kill or held_by_tracker_pre_kill, (
            "detector failed: without the bootstrap no descendant shows "
            "the inherited launch pipe while the engine lives"
        )
        assert _kill_exact(int(marker["pid"])) is True
        run.process.wait(timeout=5)
        assert run.process.returncode == -signal.SIGKILL
        run.pump_thread.join(_EOF_BUDGET_S + 0.5)
        assert run.pump_thread.is_alive(), (
            "control expectation violated: without the bootstrap the pump must remain blocked past the budget"
        )
        if _proc_exists(tracker_pid):
            held_by_tracker_post_kill = _pipe_inode_descriptors(tracker_pid, run.launch_pipe_inode)
            assert held_by_tracker_post_kill, (
                "detector failed: surviving resource tracker no longer preserves the inherited launch pipe"
            )
    finally:
        _cleanup_descendants(run)
        run.pump_thread.join(_SETTLEMENT_TIMEOUT_S)
        assert not run.pump_thread.is_alive(), "pump did not settle even after every descendant was killed"
        assert run.stream_owner.settlement_state is _OwnerSettlementState.SETTLED
        _detach_pump(run, pump_logger)


@pytest.mark.skipif(not _LINUX, reason="mutation control requires Linux /proc and POSIX fd semantics")
def test_control_exposing_private_fileno_must_fail_detected_as_leak(tmp_path: Path) -> None:
    run, pump_logger = _run_blocker_scenario(tmp_path, install_isolation=True, expose_fileno=True)
    try:
        marker = run.marker
        assert marker["isolation_applied"] is True
        exposed_fileno = marker["stderr_fileno"]
        assert type(exposed_fileno) is int and exposed_fileno > 2
        holder_pid = marker["holder_pid"]
        assert type(holder_pid) is int and holder_pid > 0 and _proc_exists(holder_pid)
        _assert_probe_reached_launcher_pipe(run)
        assert _kill_exact(int(marker["pid"])) is True
        run.process.wait(timeout=5)
        assert run.process.returncode == -signal.SIGKILL
        run.pump_thread.join(_EOF_BUDGET_S + 0.5)
        assert run.pump_thread.is_alive(), (
            "control expectation violated: an exposed private fileno must keep the pump blocked past the budget"
        )
        held_by_holder = _pipe_inode_descriptors(holder_pid, run.launch_pipe_inode)
        assert held_by_holder, (
            f"detector failed: preserving consumer {holder_pid} does not hold the launch pipe via the exposed fd"
        )
    finally:
        _cleanup_descendants(run)
        run.pump_thread.join(_SETTLEMENT_TIMEOUT_S)
        assert not run.pump_thread.is_alive(), "pump did not settle even after the preserving consumer was killed"
        assert run.stream_owner.settlement_state is _OwnerSettlementState.SETTLED
        _detach_pump(run, pump_logger)


def test_direct_cli_engine_child_keeps_stderr_attached_to_launch_pipe(tmp_path: Path) -> None:
    env = _simulant_base_env(tmp_path)
    env[EXIT_AFTER_MARKER_ENV] = "1"
    process = _spawn_simulant(env)
    marker_lines, _reader_thread = _start_line_reader(process.stdout)
    run, pump_logger = _attach_pump(process)
    try:
        run.marker = _wait_for_marker(marker_lines)
        run.pump_thread.start()
        marker = run.marker
        assert marker["isolation_applied"] is False
        assert marker["stderr_fileno"] == 2
        _assert_probe_reached_launcher_pipe(run)
        if _LINUX:
            launch_pipe_inode = os.fstat(process.stderr.fileno()).st_ino
            fd2_target = os.readlink(f"/proc/{marker['pid']}/fd/2")
            match = _PIPE_TARGET_RE.match(fd2_target)
            assert match is not None and int(match.group(1)) == launch_pipe_inode
        assert process.wait(timeout=20) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        run.pump_thread.join(_SETTLEMENT_TIMEOUT_S)
        _detach_pump(run, pump_logger)


@pytest.mark.skipif(not _WINDOWS, reason="Windows-unchanged guard runs only on win32")
def test_windows_launcher_owned_engine_child_remains_unisolated(tmp_path: Path) -> None:
    env = _simulant_base_env(tmp_path)
    authority, ready_read_fd, ready_write_fd = _launcher_authority_env()
    env.update(authority)
    env[INSTALL_ISOLATION_ENV] = "1"
    env[EXIT_AFTER_MARKER_ENV] = "1"
    try:
        process = _spawn_simulant(env, inherit_ready_fd=ready_write_fd)
    finally:
        for descriptor in (ready_read_fd, ready_write_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass
    marker_lines, _reader_thread = _start_line_reader(process.stdout)
    run, pump_logger = _attach_pump(process)
    try:
        run.marker = _wait_for_marker(marker_lines)
        run.pump_thread.start()
        marker = run.marker
        assert marker["isolation_applied"] is False
        assert marker["stderr_fileno"] == 2
        _assert_probe_reached_launcher_pipe(run)
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        run.pump_thread.join(_SETTLEMENT_TIMEOUT_S)
        _detach_pump(run, pump_logger)


def test_engine_gate_requires_complete_envelope_and_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert engine_gate("a" * 32, "b" * 64, "c" * 64, 7) is True
    assert engine_gate("", "b" * 64, "c" * 64, 7) is False
    assert engine_gate("a" * 32, "", "c" * 64, 7) is False
    assert engine_gate("a" * 32, "b" * 64, "", 7) is False
    assert engine_gate("a" * 32, "b" * 64, "c" * 64, None) is False
    monkeypatch.setattr(sys, "platform", "win32")
    assert engine_gate("a" * 32, "b" * 64, "c" * 64, 7) is False


def test_replay_gate_requires_complete_authority_and_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryodaq.replay_engine.__main__ import _requires_launcher_fd2_isolation as replay_gate

    monkeypatch.setattr(sys, "platform", "linux")
    assert replay_gate("n" * 64, "s" * 32, 9) is True
    assert replay_gate(None, "s" * 32, 9) is False
    assert replay_gate("n" * 64, None, 9) is False
    assert replay_gate("n" * 64, "s" * 32, None) is False
    monkeypatch.setattr(sys, "platform", "win32")
    assert replay_gate("n" * 64, "s" * 32, 9) is False


_IDEMPOTENCY_SCRIPT = textwrap.dedent(
    """
    import io, json, logging, sys
    from cryodaq._fd2_bootstrap import current_receipt, isolate_launcher_stderr_fd2
    first = isolate_launcher_stderr_fd2()
    second = isolate_launcher_stderr_fd2()
    try:
        sys.stderr.fileno()
        denied = False
    except io.UnsupportedOperation:
        denied = True
    logging.getLogger("cryodaq.fd2.idempotency").error("LOGGED-PROBE")
    sys.stderr.write("POST-INSTALL-PROBE\\n")
    print(json.dumps({
        "first_private_fd": first.private_fd,
        "same_receipt": first == second,
        "receipt_current": current_receipt() == second,
        "fileno_denied": denied,
    }))
    """
)


@pytest.mark.skipif(not _POSIX, reason="installer behaviour is POSIX-only")
def test_install_is_idempotent_denies_fileno_and_keeps_logging_reaching_the_pipe(tmp_path: Path) -> None:
    env = _simulant_base_env(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", _IDEMPOTENCY_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = process.communicate(timeout=60)
    assert process.returncode == 0, f"installer child failed: rc={process.returncode} stderr={stderr_bytes!r}"
    document = json.loads(stdout_bytes.decode().strip().splitlines()[-1])
    assert document["same_receipt"] is True
    assert document["receipt_current"] is True
    assert document["fileno_denied"] is True
    assert type(document["first_private_fd"]) is int and document["first_private_fd"] > 2
    assert b"LOGGED-PROBE" in stderr_bytes
    assert b"POST-INSTALL-PROBE\n" in stderr_bytes


_REPLAY_WIRING_SCRIPT = textwrap.dedent(
    """
    import io, json, sys
    from cryodaq.replay_engine.__main__ import _requires_launcher_fd2_isolation as gate
    result = {"direct_absent": gate(None, None, None)}
    if gate("nonce-value", "session-value", 11):
        from cryodaq._fd2_bootstrap import isolate_launcher_stderr_fd2
        receipt = isolate_launcher_stderr_fd2()
        try:
            sys.stderr.fileno()
            denied = False
        except io.UnsupportedOperation:
            denied = True
        result.update(installed=True, private_fd=receipt.private_fd, fileno_denied=denied)
    sys.platform = "win32"
    result["windows_gate"] = gate("nonce-value", "session-value", 11)
    print(json.dumps(result))
    """
)


@pytest.mark.skipif(not _POSIX, reason="replay wiring guard installs the POSIX-only bootstrap")
def test_replay_entry_installs_isolation_only_for_launcher_authority(tmp_path: Path) -> None:
    env = _simulant_base_env(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", _REPLAY_WIRING_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = process.communicate(timeout=90)
    assert process.returncode == 0, f"replay wiring child failed: rc={process.returncode} stderr={stderr_bytes!r}"
    document = json.loads(stdout_bytes.decode().strip().splitlines()[-1])
    assert document["direct_absent"] is False
    assert document.get("installed") is True
    assert document["fileno_denied"] is True
    assert type(document["private_fd"]) is int and document["private_fd"] > 2
    assert document["windows_gate"] is False
