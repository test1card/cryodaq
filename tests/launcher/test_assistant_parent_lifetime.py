"""Real-kernel proof that the launcher's assistant cannot become an orphan."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import selectors
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the Ubuntu laboratory parent-death contract uses Linux pidfds and PR_SET_PDEATHSIG",
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
                    [sys.executable, "-B", "-c", "import time; time.sleep(600)"],
                    stdin=subprocess.DEVNULL,
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
    parent_pidfd: int | None = None
    assistant_pidfd: int | None = None
    assistant_pid: int | None = None
    parent_settled = False
    assistant_exited = False
    survived_engine_death = False
    try:
        parent_pidfd = _pidfd_open(parent.pid)
        assert parent.stdin is not None
        assert parent.stdout is not None
        parent.stdin.write(b"START\n")
        parent.stdin.flush()
        report = json.loads(_read_line(parent.stdout, timeout=15.0))
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
                    stderr = b"" if parent.stderr is None else parent.stderr.read(4000)
                    raise AssertionError(f"real assistant exited before readiness: {stderr!r}")
                time.sleep(0.05)
            assert readiness_path.is_dir(), "real assistant never reached its post-binding data setup"

            if mode == "engine-death":
                engine_pid = report["engine_pid"]
                assert type(engine_pid) is int and engine_pid > 1
                engine_pidfd = _pidfd_open(engine_pid)
                try:
                    _pidfd_send_signal(engine_pidfd, signal.SIGKILL)
                    assert _wait_for_identity_exit(engine_pidfd, timeout=10.0)
                finally:
                    os.close(engine_pidfd)
                assert _read_line(parent.stdout, timeout=10.0) == "ENGINE_EXITED"
                survived_engine_death = not _identity_exited(assistant_pidfd)

            _pidfd_send_signal(parent_pidfd, signal.SIGKILL)
            parent.wait(timeout=10.0)
            parent_settled = True

        assistant_exited = _wait_for_identity_exit(assistant_pidfd, timeout=10.0)
    finally:
        cleanup_errors: list[BaseException] = []
        if assistant_pidfd is not None:
            try:
                _pidfd_send_signal(assistant_pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                if not _wait_for_identity_exit(assistant_pidfd, timeout=10.0):
                    raise AssertionError("assistant cleanup did not reach exact pidfd exit")
            except BaseException as exc:
                cleanup_errors.append(exc)
        if parent_pidfd is not None and not parent_settled:
            try:
                _pidfd_send_signal(parent_pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                parent.wait(timeout=10.0)
                parent_settled = True
            except BaseException as exc:
                cleanup_errors.append(exc)
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
        for descriptor in (assistant_pidfd, parent_pidfd):
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
