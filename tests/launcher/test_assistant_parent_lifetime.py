"""Real-kernel proof that the launcher's assistant cannot become an orphan."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import queue
import selectors
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the Ubuntu laboratory parent-death contract uses Linux pidfds and PR_SET_PDEATHSIG",
)
_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="the native launcher Job-object boundary exists only on Windows",
)
_PIDFD_OPEN_SYSCALL = {
    "x86_64": 434,
    "aarch64": 434,
    "riscv64": 434,
    "loongarch64": 434,
    "ppc64le": 434,
    "s390x": 434,
}.get(platform.machine())
_PIDFD_SEND_SIGNAL_SYSCALL = {
    "x86_64": 424,
    "aarch64": 424,
    "riscv64": 424,
    "loongarch64": 424,
    "ppc64le": 424,
    "s390x": 424,
}.get(platform.machine())
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37
_TERMINATING_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"


class _KernelIdentityUnavailable(RuntimeError):
    pass


def _pidfd_open(pid: int) -> int:
    if _PIDFD_OPEN_SYSCALL is None:
        raise _KernelIdentityUnavailable(f"no reviewed pidfd_open syscall for {platform.machine()}")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    descriptor = libc.syscall(
        ctypes.c_long(_PIDFD_OPEN_SYSCALL),
        ctypes.c_int(pid),
        ctypes.c_uint(0),
    )
    if descriptor >= 0:
        return int(descriptor)
    code = ctypes.get_errno()
    raise _KernelIdentityUnavailable(os.strerror(code)) from OSError(code, os.strerror(code))


def _pidfd_send_signal(pidfd: int, signum: int) -> None:
    if _PIDFD_SEND_SIGNAL_SYSCALL is None:
        raise _KernelIdentityUnavailable(f"no reviewed pidfd_send_signal syscall for {platform.machine()}")
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        ctypes.c_long(_PIDFD_SEND_SIGNAL_SYSCALL),
        ctypes.c_int(pidfd),
        ctypes.c_int(signum),
        ctypes.c_void_p(None),
        ctypes.c_uint(0),
    )
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.ESRCH:
        raise ProcessLookupError(code, os.strerror(code))
    raise OSError(code, os.strerror(code))


def _identity_exited(pidfd: int) -> bool:
    with selectors.DefaultSelector() as selector:
        selector.register(pidfd, selectors.EVENT_READ)
        return bool(selector.select(0))


def _wait_for_identity_exit(pidfd: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _identity_exited(pidfd):
            return True
        time.sleep(0.05)
    return _identity_exited(pidfd)


def _set_subreaper(enabled: bool) -> bool:
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise _KernelIdentityUnavailable(os.strerror(code))
    previous_enabled = previous.value == 1
    if previous_enabled != enabled and libc.prctl(_PR_SET_CHILD_SUBREAPER, int(enabled), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise _KernelIdentityUnavailable(os.strerror(code))
    return previous_enabled


def _read_line(stream, *, timeout: float) -> str:
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise AssertionError("launcher harness did not publish its process identities")
    line = stream.readline()
    if not line:
        raise AssertionError("launcher harness exited before publishing its process identities")
    return line.decode("ascii", errors="strict").strip()


def _read_line_from_windows_pipe(stream, *, timeout: float) -> str:
    """Bound a blocking Windows anonymous-pipe read without psutil."""

    received: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            received.put(stream.readline())
        except BaseException as exc:
            received.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        result = received.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("launcher harness did not publish its process identities") from exc
    if isinstance(result, BaseException):
        raise result
    if not result:
        raise AssertionError("launcher harness exited before publishing its process identities")
    return result.decode("ascii", errors="strict").strip()


def _open_windows_process_identity(pid: int):
    """Open one exact process identity for native wait and bounded cleanup."""

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process_terminate = 0x0001
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(process_terminate | synchronize, False, pid)
    if not handle:
        code = ctypes.get_last_error()
        raise OSError(code, f"OpenProcess failed for {pid}")
    return kernel32, handle


def _wait_windows_process(kernel32, handle, *, timeout: float) -> bool:
    wait_object_0 = 0
    wait_timeout = 258
    result = int(kernel32.WaitForSingleObject(handle, int(timeout * 1000)))
    if result == wait_object_0:
        return True
    if result == wait_timeout:
        return False
    code = ctypes.get_last_error()
    raise OSError(code, f"WaitForSingleObject failed with result {result}")


def _read_available_bytes(stream, *, limit: int, timeout: float) -> bytes:
    descriptor = stream.fileno()
    was_blocking = os.get_blocking(descriptor)
    deadline = time.monotonic() + timeout
    captured = bytearray()
    try:
        os.set_blocking(descriptor, False)
        while len(captured) < limit:
            try:
                chunk = os.read(descriptor, limit - len(captured))
            except BlockingIOError:
                chunk = None
            if chunk == b"":
                break
            if chunk:
                captured.extend(chunk)
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
    finally:
        os.set_blocking(descriptor, was_blocking)
    return bytes(captured)


def _reap_adopted_child(pid: int, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            observed, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if observed == pid:
            return
        time.sleep(0.05)
    raise AssertionError(f"adopted assistant {pid} was not reaped")


def _write_runtime_config(runtime_root: Path) -> None:
    config = runtime_root / "config"
    config.mkdir(parents=True)
    (config / "agent.yaml").write_text(
        "agent:\n  enabled: false\nreporting:\n  automatic_enabled: false\n",
        encoding="utf-8",
    )


def _write_launcher_harness(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import subprocess
            import sys
            import time
            from types import SimpleNamespace

            from cryodaq.launcher import LauncherWindow

            if sys.stdin.buffer.readline() != b"START\\n":
                raise SystemExit(71)
            # Launcher imports need the real immutable application tree (theme
            # packs included); the spawned assistant then receives the minimal
            # valid harness config without changing its production command.
            os.environ["CRYODAQ_ROOT"] = os.environ["CRYODAQ_HARNESS_RUNTIME_ROOT"]
            mode = sys.argv[1]
            host = SimpleNamespace(
                _assistant_experiment_mode=False,
                _assistant_periodic_requested=False,
                _assistant_periodic_health=None,
                _assistant_proc=None,
                _assistant_parent_job=None,
                _assistant_shutdown_path=None,
                _assistant_shutdown_authority=None,
                _assistant_soak_duplicate_owner=None,
                _assistant_unsettled_start_failure=None,
                _assistant_restart_pending=False,
                _soak_artifact_capability=None,
            )
            LauncherWindow._start_assistant(host)
            engine = None
            if mode == "engine-death":
                engine = subprocess.Popen(
                    [sys.executable, "-B", "-c", "import sys; sys.stdin.buffer.read()"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            print(
                json.dumps(
                    {
                        "assistant_pid": host._assistant_proc.pid,
                        "engine_pid": None if engine is None else engine.pid,
                        "launcher_pid": os.getpid(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if mode == "construction-failure":
                os._exit(86)
            if engine is not None:
                while engine.poll() is None:
                    time.sleep(0.02)
                engine.wait()
                print("ENGINE_EXITED", flush=True)
            while True:
                time.sleep(60)
            """
        ),
        encoding="utf-8",
    )


def _preflight_kernel_identity() -> None:
    descriptor: int | None = None
    try:
        descriptor = _pidfd_open(os.getpid())
        _pidfd_send_signal(descriptor, 0)
    except (_KernelIdentityUnavailable, OSError) as exc:
        pytest.skip(f"real parent-death proof requires Ubuntu-class pidfds: {exc}")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _exercise_launcher_parent_death(tmp_path: Path, mode: str) -> tuple[bool, bool]:
    _preflight_kernel_identity()
    runtime_root = tmp_path / "runtime"
    _write_runtime_config(runtime_root)
    harness = tmp_path / "launcher_assistant_harness.py"
    _write_launcher_harness(harness)
    try:
        previous_subreaper = _set_subreaper(True)
    except _KernelIdentityUnavailable as exc:
        pytest.skip(f"real orphan cleanup requires PR_SET_CHILD_SUBREAPER: {exc}")

    parent: subprocess.Popen[bytes] | None = None
    parent_pidfd: int | None = None
    assistant_pidfd: int | None = None
    assistant_pid: int | None = None
    engine_pidfd: int | None = None
    engine_pid: int | None = None
    parent_settled = False
    assistant_exited = False
    survived_engine_death = False
    try:
        env = os.environ.copy()
        env.update(
            {
                "CRYODAQ_ROOT": str(_ROOT),
                "CRYODAQ_STATE_ROOT": str(runtime_root),
                "CRYODAQ_HARNESS_RUNTIME_ROOT": str(runtime_root),
                "PYTHONPATH": str(_SRC),
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        parent = subprocess.Popen(
            [sys.executable, "-B", str(harness), mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        parent_pidfd = _pidfd_open(parent.pid)
        assert parent.stdin is not None
        assert parent.stdout is not None
        parent.stdin.write(b"START\n")
        parent.stdin.flush()
        report = json.loads(_read_line(parent.stdout, timeout=15.0))
        if mode == "engine-death":
            engine_pid = report["engine_pid"]
            assert type(engine_pid) is int and engine_pid > 1
            engine_pidfd = _pidfd_open(engine_pid)
        assert report["launcher_pid"] == parent.pid
        assistant_pid = report["assistant_pid"]
        assert type(assistant_pid) is int and assistant_pid > 1
        assistant_pidfd = _pidfd_open(assistant_pid)

        if mode == "construction-failure":
            assert parent.wait(timeout=10.0) == 86
            parent_settled = True
        else:
            readiness_path = runtime_root / "data"
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline and not readiness_path.is_dir():
                if _identity_exited(assistant_pidfd):
                    stderr = (
                        b"" if parent.stderr is None else _read_available_bytes(parent.stderr, limit=4000, timeout=0.25)
                    )
                    raise AssertionError(f"real assistant exited before readiness: {stderr!r}")
                time.sleep(0.05)
            assert readiness_path.is_dir(), "real assistant never reached its post-binding data setup"

            if mode == "engine-death":
                assert engine_pidfd is not None
                _pidfd_send_signal(engine_pidfd, _TERMINATING_SIGNAL)
                assert _wait_for_identity_exit(engine_pidfd, timeout=10.0)
                assert _read_line(parent.stdout, timeout=10.0) == "ENGINE_EXITED"
                survived_engine_death = not _identity_exited(assistant_pidfd)

            _pidfd_send_signal(parent_pidfd, _TERMINATING_SIGNAL)
            parent.wait(timeout=10.0)
            parent_settled = True

        assistant_exited = _wait_for_identity_exit(assistant_pidfd, timeout=10.0)
    finally:
        cleanup_errors: list[BaseException] = []
        if assistant_pidfd is not None:
            try:
                _pidfd_send_signal(assistant_pidfd, _TERMINATING_SIGNAL)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                if not _wait_for_identity_exit(assistant_pidfd, timeout=10.0):
                    raise AssertionError("assistant cleanup did not reach exact pidfd exit")
            except BaseException as exc:
                cleanup_errors.append(exc)
        if engine_pidfd is not None:
            try:
                _pidfd_send_signal(engine_pidfd, _TERMINATING_SIGNAL)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                if not _wait_for_identity_exit(engine_pidfd, timeout=10.0):
                    raise AssertionError("engine cleanup did not reach exact pidfd exit")
            except BaseException as exc:
                cleanup_errors.append(exc)
        if parent is not None and not parent_settled:
            if parent_pidfd is not None:
                try:
                    _pidfd_send_signal(parent_pidfd, _TERMINATING_SIGNAL)
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    cleanup_errors.append(exc)
            else:
                try:
                    parent.kill()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                parent.wait(timeout=10.0)
                parent_settled = True
            except BaseException as exc:
                cleanup_errors.append(exc)
        if parent is not None:
            if parent.stdin is not None:
                parent.stdin.close()
            if parent.stdout is not None:
                parent.stdout.close()
            if parent.stderr is not None:
                parent.stderr.close()
        if assistant_pid is not None and parent_settled:
            try:
                _reap_adopted_child(assistant_pid)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if engine_pid is not None and parent_settled:
            try:
                _reap_adopted_child(engine_pid)
            except BaseException as exc:
                cleanup_errors.append(exc)
        for descriptor in (assistant_pidfd, engine_pidfd, parent_pidfd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as exc:
                    cleanup_errors.append(exc)
        try:
            _set_subreaper(previous_subreaper)
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            details = "; ".join(f"{type(exc).__name__}: {exc}" for exc in cleanup_errors)
            raise AssertionError(f"assistant lifecycle harness cleanup failed: {details}") from cleanup_errors[0]
    return assistant_exited, survived_engine_death


@_LINUX_ONLY
def test_assistant_cannot_survive_launcher_construction_failure(tmp_path: Path) -> None:
    assistant_exited, _ = _exercise_launcher_parent_death(tmp_path, "construction-failure")

    assert assistant_exited, "assistant survived the launcher failing immediately after its production spawn"


@_LINUX_ONLY
def test_assistant_cannot_survive_launcher_sigkill(tmp_path: Path) -> None:
    assistant_exited, _ = _exercise_launcher_parent_death(tmp_path, "launcher-kill")

    assert assistant_exited, "assistant survived exact launcher SIGKILL"


@_LINUX_ONLY
def test_assistant_is_owned_by_launcher_not_engine(tmp_path: Path) -> None:
    assistant_exited, survived_engine_death = _exercise_launcher_parent_death(tmp_path, "engine-death")

    assert survived_engine_death, "assistant was incorrectly bound to the engine instead of the launcher"
    assert assistant_exited, "assistant survived launcher death after the launcher had reaped its dead engine"


@_WINDOWS_ONLY
def test_real_windows_job_kills_assistant_when_launcher_dies(tmp_path: Path) -> None:
    """Exercise the real launcher Job handle and a real assistant process."""

    runtime_root = tmp_path / "runtime"
    _write_runtime_config(runtime_root)
    harness = tmp_path / "launcher_assistant_harness.py"
    _write_launcher_harness(harness)
    env = os.environ.copy()
    env.update(
        {
            "CRYODAQ_ROOT": str(_ROOT),
            "CRYODAQ_STATE_ROOT": str(runtime_root),
            "CRYODAQ_HARNESS_RUNTIME_ROOT": str(runtime_root),
            "PYTHONPATH": str(_SRC),
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    parent: subprocess.Popen[bytes] | None = None
    kernel32 = None
    assistant_handle = None
    parent_settled = False
    try:
        parent = subprocess.Popen(
            [sys.executable, "-B", str(harness), "launcher-kill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert parent.stdin is not None
        assert parent.stdout is not None
        parent.stdin.write(b"START\n")
        parent.stdin.flush()
        report = json.loads(_read_line_from_windows_pipe(parent.stdout, timeout=15.0))
        assert report["launcher_pid"] == parent.pid
        assistant_pid = report["assistant_pid"]
        assert type(assistant_pid) is int and assistant_pid > 1
        kernel32, assistant_handle = _open_windows_process_identity(assistant_pid)

        readiness_path = runtime_root / "data"
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not readiness_path.is_dir():
            if _wait_windows_process(kernel32, assistant_handle, timeout=0):
                raise AssertionError("real assistant exited before readiness")
            time.sleep(0.05)
        assert readiness_path.is_dir(), "real assistant never reached its post-binding data setup"
        assert not _wait_windows_process(kernel32, assistant_handle, timeout=0)

        parent.kill()
        parent.wait(timeout=10.0)
        parent_settled = True
        assert _wait_windows_process(kernel32, assistant_handle, timeout=10.0), (
            "real assistant survived closure of the launcher's production Job handle"
        )
    finally:
        if parent is not None and not parent_settled:
            parent.kill()
            parent.wait(timeout=10.0)
        if kernel32 is not None and assistant_handle is not None:
            if not _wait_windows_process(kernel32, assistant_handle, timeout=0):
                if not kernel32.TerminateProcess(assistant_handle, 91):
                    code = ctypes.get_last_error()
                    raise OSError(code, "TerminateProcess failed during assistant cleanup")
                assert _wait_windows_process(kernel32, assistant_handle, timeout=10.0)
            if not kernel32.CloseHandle(assistant_handle):
                code = ctypes.get_last_error()
                raise OSError(code, "CloseHandle failed for assistant process identity")
        if parent is not None:
            if parent.stdin is not None:
                parent.stdin.close()
            if parent.stdout is not None:
                parent.stdout.close()
            if parent.stderr is not None:
                parent.stderr.close()


def test_early_exit_diagnostic_is_bounded_while_writer_remains_open() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    try:
        os.write(write_fd, b"bounded diagnostic")

        assert _read_available_bytes(stream, limit=4000, timeout=0.25) == b"bounded diagnostic"
    finally:
        stream.close()
        os.close(write_fd)


def test_parent_creation_failure_restores_subreaper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transitions: list[bool] = []

    def set_subreaper(enabled: bool) -> bool:
        transitions.append(enabled)
        return False

    monkeypatch.setattr(sys.modules[__name__], "_preflight_kernel_identity", lambda: None)
    monkeypatch.setattr(sys.modules[__name__], "_set_subreaper", set_subreaper)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("launcher creation failed")),
    )

    with pytest.raises(OSError, match="launcher creation failed"):
        _exercise_launcher_parent_death(tmp_path, "launcher-kill")

    assert transitions == [True, False]


def test_engine_identity_is_cleaned_if_readiness_fails_after_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stream:
        def write(self, _data: bytes) -> None:
            return None

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Parent:
        pid = 101
        stdin = Stream()
        stdout = Stream()
        stderr = Stream()

        def wait(self, *, timeout: float) -> int:
            assert timeout > 0
            return -_TERMINATING_SIGNAL

    report = json.dumps({"assistant_pid": 202, "engine_pid": 303, "launcher_pid": 101})
    descriptor_by_pid = {101: 1101, 202: 1202, 303: 1303}
    signalled: list[int] = []
    reaped: list[int] = []
    closed: list[int] = []
    monotonic = iter((0.0, 16.0))

    monkeypatch.setattr(sys.modules[__name__], "_preflight_kernel_identity", lambda: None)
    monkeypatch.setattr(sys.modules[__name__], "_set_subreaper", lambda enabled: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Parent())
    monkeypatch.setattr(sys.modules[__name__], "_read_line", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_open", descriptor_by_pid.__getitem__)
    monkeypatch.setattr(sys.modules[__name__], "_identity_exited", lambda _pidfd: False)
    monkeypatch.setattr(sys.modules[__name__], "_wait_for_identity_exit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_pidfd_send_signal",
        lambda pidfd, _signum: signalled.append(pidfd),
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "_reap_adopted_child",
        lambda pid, **_kwargs: reaped.append(pid),
    )
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(os, "close", lambda descriptor: closed.append(descriptor))

    with pytest.raises(AssertionError, match="real assistant never reached"):
        _exercise_launcher_parent_death(tmp_path, "engine-death")

    assert 1303 in signalled
    assert 303 in reaped
    assert 1303 in closed


@_LINUX_ONLY
def test_engine_exits_on_launcher_death_when_pidfd_open_fails_after_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The harness owns a pre-established EOF cleanup path before pidfd_open."""

    real_pidfd_open = _pidfd_open
    calls = 0

    def fail_engine_pidfd(pid: int) -> int:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError(errno.EMFILE, "forced engine pidfd exhaustion")
        return real_pidfd_open(pid)

    monkeypatch.setattr(sys.modules[__name__], "_pidfd_open", fail_engine_pidfd)

    with pytest.raises(OSError, match="forced engine pidfd exhaustion"):
        _exercise_launcher_parent_death(tmp_path, "engine-death")
    assert calls == 3
