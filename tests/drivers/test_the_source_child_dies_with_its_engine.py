"""The process that owns the source must not outlive the process that owns it.

WHY THIS MODULE EXISTS. ``USBTMCTransport`` is the Keithley's transport, and the Keithley
drives the heater. It puts the native VISA session in a separate ``multiprocessing`` child
so a blocking native call cannot stall the engine's event loop. That child is created with
``daemon=True``, and a daemonic child is terminated from an ``atexit`` handler. Ordinary
interpreter shutdown, including an unhandled Python exception, runs that handler; abrupt
termination such as SIGKILL, ``os._exit``, or a native fatal exit bypasses it.

The survivor is not merely untidy. The launcher restarts a dead engine; the replacement
connects and commands OFF on every channel; and the orphan's pending write can land AFTER
that, leaving the instrument sourcing while the software believes it is off. Two owners of
one source is the exact hazard the ownership design exists to prevent. These tests prove only
that the source-owning child cannot outlive its engine. They do not prove USB transaction
settlement, physical OFF, or restart authority. A launcher restart still requires those
independent properties.

WHICH CHILD IS AT RISK, and TWO measurement mistakes made on the way to knowing it.

The first version killed a parent whose child was blocked reading the pipe, and passed with
the binding removed: the parent's death closes the write end, the read returns end-of-file,
and that child leaves by itself. It proved nothing.

The second version used a child that stays busy -- which is the right shape, because a child
inside a native call is not reading the pipe -- but ran its parent through `python -c`.
`spawn` re-imports the main module to rebuild the target, and a `-c` main module cannot be
re-imported, so the child died on a traceback before running a line. The control reported
"no orphan" because the child was never alive to become one.

Measured properly, with the parent as a real FILE: a busy child DOES survive a SIGKILLed
parent, in every shape tried -- sleeping, spinning in Python, and blocked in a native call
that holds the GIL. So the hazard is real, and each test below carries its own control.

TWO DISCIPLINES ADDED AFTER THE FIRST REVIEW ROUND, both paid for by findings.

Every child below ignores SIGTERM outright. A binding quietly swapped from SIGKILL to
SIGTERM would otherwise still green the lifecycle -- the child would die either way. With
the immunity installed before the parent dies, and a direct SIGTERM probe proving it live,
the child's later death can only be the kernel's SIGKILL parent-death delivery.

Every poll and every signal goes through a pidfd opened BEFORE anything can die. A numeric
pid read from READY can be reused after its owner exits; polling or killing that number can
then touch an unrelated process. Where the kernel cannot provide pidfd plus
pidfd_send_signal, the tests SKIP with that limitation named -- a skipped target-OS gate,
never a bare-pid action and never a pass.
"""

from __future__ import annotations

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
from collections.abc import Callable
from pathlib import Path

import pytest

_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="PR_SET_PDEATHSIG is a Linux facility; the laboratory target is Ubuntu 22.04",
)

_WINDOWS_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("win32"),
    reason="pins the OPEN Windows gate: the unbound source worker refuses to start until a real binding exists",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = str(_REPO_ROOT / "src")

# SYS_pidfd_send_signal under unified Linux syscall numbering. Architectures outside this
# table (alpha, sparc, the MIPS families number differently) get no entry and therefore a
# fail-closed skip, never a numeric-pid fallback.
_PIDFD_SEND_SIGNAL_SYSCALL = {
    "x86_64": 424,
    "aarch64": 424,
    "riscv64": 424,
    "loongarch64": 424,
    "ppc64le": 424,
    "s390x": 424,
}.get(platform.machine())
_PIDFD_OPEN_SYSCALL = {
    "x86_64": 434,
    "aarch64": 434,
    "riscv64": 434,
    "loongarch64": 434,
    "ppc64le": 434,
    "s390x": 434,
}.get(platform.machine())
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37


class _UnstableIdentity(RuntimeError):
    """The kernel surface for stable process identity is unavailable here."""


def _stable_identity(pid: int) -> int:
    """Open a pidfd BEFORE anything can exit and its number be reused."""

    if _PIDFD_SEND_SIGNAL_SYSCALL is None or _PIDFD_OPEN_SYSCALL is None:
        raise _UnstableIdentity(f"no pidfd surface on {platform.machine()} / {sys.version_info[:3]}")
    try:
        if hasattr(os, "pidfd_open"):
            return os.pidfd_open(pid)

        # The laboratory conda-forge Python omits os.pidfd_open even though its
        # Ubuntu 22.04 kernel provides the syscall. Use the same exact kernel
        # identity surface directly instead of skipping every registered guard.
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        pidfd = libc.syscall(
            ctypes.c_long(_PIDFD_OPEN_SYSCALL),
            ctypes.c_int(pid),
            ctypes.c_uint(0),
        )
        if pidfd >= 0:
            return int(pidfd)
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    except OSError as exc:
        raise _UnstableIdentity(str(exc)) from exc


def _identity_exited(pidfd: int) -> bool:
    """True once the exact process behind the pidfd has terminated (zombie counts)."""

    with selectors.DefaultSelector() as selector:
        selector.register(pidfd, selectors.EVENT_READ)
        return bool(selector.select(0))


def _pidfd_send_signal_syscall(pidfd: int, sig: int) -> None:
    """Issue the raw exact-identity signal used by both proof and cleanup paths."""

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    status = libc.syscall(
        ctypes.c_long(_PIDFD_SEND_SIGNAL_SYSCALL),
        ctypes.c_int(pidfd),
        ctypes.c_int(sig),
        ctypes.c_void_p(None),
        ctypes.c_uint(0),
    )
    if status == 0:
        return
    code = ctypes.get_errno()
    if code == errno.ESRCH:
        raise ProcessLookupError(code)
    raise OSError(code, os.strerror(code))


def _signal_via_identity(pidfd: int, sig: int) -> None:
    """Signal the EXACT process the pidfd names; ESRCH means it is already gone."""

    _pidfd_send_signal_syscall(pidfd, sig)


def _set_child_subreaper(enabled: bool) -> bool:
    """Set this pytest process as the nearest orphan adopter; return prior state."""

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise _UnstableIdentity(f"PR_GET_CHILD_SUBREAPER failed: {os.strerror(code)}")
    previous_enabled = previous.value == 1
    if previous_enabled != enabled and libc.prctl(_PR_SET_CHILD_SUBREAPER, int(enabled), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise _UnstableIdentity(f"PR_SET_CHILD_SUBREAPER failed: {os.strerror(code)}")
    return previous_enabled


def _child_subreaper_state() -> bool:
    """Read the process-global child-subreaper state without changing it."""

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    current = ctypes.c_int()
    if libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(current), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise _UnstableIdentity(f"PR_GET_CHILD_SUBREAPER failed: {os.strerror(code)}")
    return current.value == 1


def _reap_adopted_child(child_pid: int, *, timeout: float = 10.0) -> None:
    """Reap the exact adopted orphan within a fixed deadline."""

    deadline = time.monotonic() + timeout
    while True:
        try:
            reaped_pid, _status = os.waitpid(child_pid, os.WNOHANG)
        except ChildProcessError as exc:
            raise AssertionError(f"spawned child {child_pid} was not adopted for exact reap") from exc
        if reaped_pid == child_pid:
            return
        assert reaped_pid == 0, f"waitpid reaped {reaped_pid}, expected exact child {child_pid}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"spawned child {child_pid} was not reaped within {timeout:.1f}s")
        time.sleep(0.05)


def _restore_child_subreaper(previous: bool) -> None:
    _set_child_subreaper(previous)


# The parent is written to a FILE, never passed with -c: `spawn` re-imports the main module
# to rebuild the target, and a `-c` main module cannot be re-imported.
_BUSY_CHILD_PARENT = textwrap.dedent(
    """
    import multiprocessing, os, sys, time
    sys.path.insert(0, {src!r})

    def _busy(_connection, expected_parent):
        # DETACH THIS PROCESS FROM THE HARNESS BEFORE DOING ANYTHING ELSE. The control case
        # deliberately leaks a process, and a leaked process that still holds pytest's
        # stdout and stderr keeps those pipes open after pytest exits -- which broke the
        # continuous integration runner's receipt accounting on a suite where every single
        # test had passed. The hazard under test is the process outliving its parent, not
        # the pipes it happens to hold.
        import os as _os
        _null = _os.open(_os.devnull, _os.O_RDWR)
        for _fd in (0, 1, 2):
            _os.dup2(_null, _fd)
        if _null > 2:
            _os.close(_null)
        # IGNORE SIGTERM FROM NOW ON. A binding swapped from SIGKILL to SIGTERM must stop
        # passing these tests: an immune child only dies to SIGKILL, so its death after the
        # parent's death is the kernel's parent-death delivery and nothing else.
        import signal as _signal
        _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)

        from cryodaq.drivers.transport.usbtmc import _bind_lifetime_to_parent
        {binding}
        _connection.send("READY")
        _connection.close()
        # Whatever happens to the parent, this never looks at the pipe -- the shape of a
        # child inside a native call.
        {busy}

    if __name__ == "__main__":
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(target=_busy, args=(child_connection, os.getpid()), daemon=True)
        try:
            process.start()
            child_connection.close()
            # Publish the exact child identity before waiting for its binder. The harness
            # opens a pidfd from this line, so every later startup error still has an exact
            # cleanup authority rather than an already-reusable numeric pid.
            print(f"SPAWNED {{process.pid}}", flush=True)
            if not parent_connection.poll(10):
                raise RuntimeError("child did not report readiness after binding")
            if parent_connection.recv() != "READY":
                raise RuntimeError("child reported an invalid readiness marker")
            print(f"READY {{process.pid}}", flush=True)
            if sys.stdin.buffer.readline().strip() != b"CLEANUP":
                raise RuntimeError("parent received an invalid harness command")
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join(10)
                if process.is_alive():
                    raise RuntimeError("busy child did not settle during parent cleanup")
    """
)


# This parent reaches the production constructor rather than a test-only worker seam:
# USBTMCTransport._settle_process_open creates multiprocessing.Process with
# target=_visa_process_main. The synthetic pyvisa module is installed by the FILE's top
# level, so spawn re-imports it in the real child. Its write then enters a native call that
# holds the GIL and ignores SIGTERM, matching the unsafe in-flight transaction shape.
_PRODUCTION_PROCESS_PARENT = textwrap.dedent(
    """
    import asyncio, ctypes, os, signal, sys, types
    from pathlib import Path
    sys.path.insert(0, {src!r})


    _entered = Path({entered!r})

    class _Resource:
        timeout = 0

        def write(self, _command):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            _entered.write_bytes(b"ENTERED")
            ctypes.PyDLL("libc.so.6").sleep(600)

        def close(self):
            pass

    class _Manager:
        def open_resource(self, _resource):
            return _Resource()

        def close(self):
            pass

    _pyvisa = types.ModuleType("pyvisa")
    _pyvisa.ResourceManager = _Manager
    sys.modules["pyvisa"] = _pyvisa

    async def _main():
        from cryodaq.drivers.transport.usbtmc import USBTMCTransport

        transport = USBTMCTransport(mock=False)
        try:
            await transport._settle_process_open("USB0::PRODUCTION-SPAWN-PROBE")
            owner = transport._process_owner
            if owner is None or owner.process.pid is None:
                raise RuntimeError("production spawn returned no exact process owner")
            print(f"SPAWNED {{owner.process.pid}}", flush=True)
            operation = asyncio.create_task(transport.write("production-spawn-boundary"))
            deadline = asyncio.get_running_loop().time() + 10.0
            while not _entered.is_file():
                if operation.done():
                    await operation
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("production VISA worker never entered the native write")
                await asyncio.sleep(0.01)
            print(f"READY {{owner.process.pid}}", flush=True)
            if (await asyncio.to_thread(sys.stdin.buffer.readline)).strip() != b"CLEANUP":
                raise RuntimeError("parent received an invalid harness command")
        finally:
            owner = transport._process_owner
            if owner is not None:
                if not transport._terminate_process_owner(owner):
                    raise RuntimeError("production VISA worker did not settle during parent cleanup")
                transport._release_stopped_owner(owner)

    if __name__ == "__main__":
        asyncio.run(_main())
    """
)


# This parent uses the production process constructor and framed open request, but holds the
# child immediately before the real _visa_process_main entry. The harness kills the engine
# while the request is already buffered, then releases the child after Linux has reparented it
# to the exact subreaper. A stale engine PID must make the first binder check exit before the
# fake pyvisa ResourceManager records any external effect.
_PREBINDER_REPARENT_PARENT = textwrap.dedent(
    """
    import asyncio, sys, time, types
    from pathlib import Path
    sys.path.insert(0, {src!r})

    _blocked = Path({blocked!r})
    _pinned = Path({pinned!r})
    _release = Path({release!r})
    _request_sent = Path({request_sent!r})
    _visa_effect = Path({visa_effect!r})

    class _Resource:
        timeout = 0

        def close(self):
            pass

    class _Manager:
        def __init__(self):
            _visa_effect.write_bytes(b"PYVISA_RESOURCE_MANAGER")

        def open_resource(self, _resource):
            _visa_effect.write_bytes(b"PYVISA_OPEN_RESOURCE")
            return _Resource()

        def close(self):
            pass

    _pyvisa = types.ModuleType("pyvisa")
    _pyvisa.ResourceManager = _Manager
    sys.modules["pyvisa"] = _pyvisa

    from cryodaq.drivers.transport import usbtmc as _usbtmc

    _production_visa_process_main = _usbtmc._visa_process_main
    _production_send_process_request = _usbtmc.USBTMCTransport._send_process_request

    def _blocked_visa_process_main(connection, expected_parent):
        _blocked.write_bytes(b"BLOCKED_BEFORE_BINDER")
        while not _release.is_file():
            time.sleep(0.01)
        _production_visa_process_main(connection, expected_parent)

    def _recording_send_process_request(self, owner, operation, payload):
        sequence = _production_send_process_request(self, owner, operation, payload)
        _request_sent.write_bytes(b"OPEN_REQUEST_SENT")
        return sequence

    _usbtmc._visa_process_main = _blocked_visa_process_main
    _usbtmc.USBTMCTransport._send_process_request = _recording_send_process_request

    async def _main():
        transport = _usbtmc.USBTMCTransport(mock=False)
        operation = asyncio.create_task(
            transport._settle_process_open("USB0::PREBINDER-REPARENT-PROBE")
        )
        try:
            deadline = asyncio.get_running_loop().time() + 10.0
            spawn_reported = False
            while True:
                owner = transport._process_owner
                if operation.done():
                    await operation
                if owner is not None and owner.process.pid is not None and not spawn_reported:
                    print(f"SPAWNED {{owner.process.pid}}", flush=True)
                    spawn_reported = True
                if (
                    spawn_reported
                    and _blocked.is_file()
                    and _pinned.is_file()
                    and _request_sent.is_file()
                ):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("production VISA worker did not block before its binder")
                await asyncio.sleep(0.01)
            print(f"READY {{owner.process.pid}}", flush=True)
            if (await asyncio.to_thread(sys.stdin.buffer.readline)).strip() != b"CLEANUP":
                raise RuntimeError("parent received an invalid harness command")
        finally:
            if not operation.done():
                operation.cancel()
            try:
                await operation
            except BaseException:
                pass
            owner = transport._process_owner
            if owner is not None:
                if not transport._terminate_process_owner(owner):
                    raise RuntimeError("production VISA worker did not settle during parent cleanup")
                transport._release_stopped_owner(owner)

    if __name__ == "__main__":
        asyncio.run(_main())
    """
)


def _read_startup_line(stream, *, timeout: float) -> str:
    """Return one flushed parent startup line, or an empty string at the deadline."""

    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout):
            return ""
    return stream.readline().decode().strip()


def _preflight_stable_identity_surface() -> None:
    """Skip only before spawning, after proving every pidfd operation we use."""

    pidfd: int | None = None
    try:
        pidfd = _stable_identity(os.getpid())
        if _identity_exited(pidfd):
            raise _UnstableIdentity("the current process pidfd was already readable")
        _signal_via_identity(pidfd, 0)
    except (_UnstableIdentity, OSError, ValueError) as exc:
        pytest.skip(
            "no stable process identity on this host: refusing to spawn an uncleanable "
            f"control child ({exc}). Parent-death evidence requires the Ubuntu 22.04-class "
            "kernel (pidfd plus pidfd_send_signal, >= 5.3); this limitation is the open "
            "target-OS gate, not a pass."
        )
    finally:
        if pidfd is not None:
            os.close(pidfd)


def _wait_for_identity_exit(pidfd: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _identity_exited(pidfd):
            return True
        time.sleep(0.05)
    return _identity_exited(pidfd)


def _reported_child_identity(parent: subprocess.Popen[bytes], *, marker: str, timeout: float) -> int:
    assert parent.stdout is not None
    line = _read_startup_line(parent.stdout, timeout=timeout)
    reported_marker, _, reported_pid = line.partition(" ")
    if reported_marker != marker or not reported_pid.isdigit():
        raise AssertionError(f"parent did not report {marker}; got {line!r}")
    return int(reported_pid)


def _request_exact_parent_cleanup(parent: subprocess.Popen[bytes]) -> None:
    """Let the still-live parent kill and join its exact Process child."""

    if parent.poll() is None:
        assert parent.stdin is not None
        try:
            parent.stdin.write(b"CLEANUP\n")
            parent.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    parent.wait(timeout=15)


def _close_parent_streams(parent: subprocess.Popen[bytes]) -> None:
    first_failure: BaseException | None = None
    later_failures: list[str] = []
    for name, stream in (("stdin", parent.stdin), ("stdout", parent.stdout), ("stderr", parent.stderr)):
        if stream is not None:
            try:
                stream.close()
            except BaseException as exc:
                if first_failure is None:
                    first_failure = exc
                else:
                    later_failures.append(f"{name}: {type(exc).__name__}")
    if first_failure is not None:
        if later_failures:
            sanitized_failures = tuple(later_failures)
            setattr(first_failure, "_cryodaq_later_stream_close_failures", sanitized_failures)
            add_note = getattr(first_failure, "add_note", None)
            if callable(add_note):
                add_note("additional parent stream close failures: " + "; ".join(sanitized_failures))
        raise first_failure


def _spawned_child_survives_killed_parent(
    parent_file: Path,
    *,
    after_child_pin: Callable[[], None] | None = None,
    after_parent_kill: Callable[[], None] | None = None,
    require_sigterm_immunity: bool = True,
) -> bool:
    """Run one parent FILE and settle parent, child, pipes, and pidfd on every exit."""

    _preflight_stable_identity_surface()
    try:
        previous_subreaper = _set_child_subreaper(True)
    except _UnstableIdentity as exc:
        pytest.skip(
            f"this Linux host cannot make the lifecycle harness the exact orphan reaper; refusing to spawn ({exc})"
        )
    try:
        parent = subprocess.Popen(
            [sys.executable, "-B", str(parent_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except BaseException:
        _restore_child_subreaper(previous_subreaper)
        raise
    child_pid: int | None = None
    child_pidfd: int | None = None
    parent_was_killed = False
    try:
        child_pid = _reported_child_identity(parent, marker="SPAWNED", timeout=10.0)
        # From this point onward the exact child is pinned before READY, polling, or any
        # signal. A setup failure is an error, never a post-spawn skip; the live parent
        # still owns the multiprocessing.Process and the finally block asks it to reap it.
        child_pidfd = _stable_identity(child_pid)
        if after_child_pin is not None:
            after_child_pin()
        ready_pid = _reported_child_identity(parent, marker="READY", timeout=10.0)
        if ready_pid != child_pid:
            raise AssertionError(f"READY changed child identity from {child_pid} to {ready_pid}")
        if _identity_exited(child_pidfd):
            raise AssertionError("the child died before the parent was killed")

        if require_sigterm_immunity:
            # Prove the immunity live: a direct SIGTERM must leave the child running, so its
            # death AFTER the parent's death can only be the kernel's SIGKILL delivery.
            _signal_via_identity(child_pidfd, signal.SIGTERM)
            time.sleep(0.2)
            if _identity_exited(child_pidfd):
                raise AssertionError("the child died of a bare SIGTERM; only SIGKILL may close it")

        parent.kill()
        # From the successful kill onward this process, as subreaper, owns the
        # adopted-child waitpid even if the first parent.wait() itself fails.
        parent_was_killed = True
        parent.wait(timeout=10)
        if after_parent_kill is not None:
            after_parent_kill()
        return not _wait_for_identity_exit(child_pidfd, timeout=6.0)
    finally:
        cleanup_errors: list[BaseException] = []
        child_identity_settled = child_pidfd is None
        child_reap_settled = child_pid is None
        try:
            # If pidfd setup succeeded, kill through that exact identity first. The parent then
            # either observes EOF and runs its Process.join, or is already the deliberate
            # SIGKILL victim. If setup failed, the still-live parent remains the exact owner and
            # handles the cleanup command itself.
            if child_pidfd is not None:
                # Never put a fallible poll in front of the exact-identity kill. A pidfd
                # SIGKILL is safe even when the process exited concurrently (ESRCH), while
                # a failed readiness poll must not strand a still-live 600-second child.
                try:
                    _signal_via_identity(child_pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    cleanup_errors.append(exc)
                    # Keep the already-open pidfd as the authority for one independent raw
                    # cleanup attempt. Never fall back to the reusable numeric PID.
                    try:
                        _pidfd_send_signal_syscall(child_pidfd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except BaseException as recovery_exc:
                        cleanup_errors.append(recovery_exc)
                try:
                    if not _wait_for_identity_exit(child_pidfd, timeout=10.0):
                        raise AssertionError(f"spawned child {child_pid} did not reach exact pidfd settlement")
                    child_identity_settled = True
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if not parent_was_killed:
                try:
                    _request_exact_parent_cleanup(parent)
                    child_identity_settled = True
                    child_reap_settled = True
                except BaseException as exc:
                    cleanup_errors.append(exc)
            else:
                try:
                    parent.wait(timeout=10)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if parent_was_killed and child_pid is not None:
                try:
                    _reap_adopted_child(child_pid)
                    child_identity_settled = True
                    child_reap_settled = True
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if child_pidfd is not None and child_identity_settled and child_reap_settled:
                try:
                    os.close(child_pidfd)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            elif child_pidfd is not None:
                cleanup_errors.append(
                    AssertionError(f"retained exact child pidfd {child_pidfd} because exit and reap did not settle")
                )
            try:
                _close_parent_streams(parent)
            except BaseException as exc:
                cleanup_errors.append(exc)
        finally:
            try:
                _restore_child_subreaper(previous_subreaper)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            details = "; ".join(f"{type(error).__name__}: {error}" for error in cleanup_errors)
            raise AssertionError(f"lifecycle harness cleanup failed: {details}") from cleanup_errors[0]


def _child_survives_a_killed_parent(
    tmp_path: Path,
    *,
    bound: bool,
    busy: str,
    after_parent_kill: Callable[[], None] | None = None,
) -> bool:
    """Kill a parent with SIGKILL and report whether its busy child outlived it."""

    parent_file = tmp_path / f"parent_{'bound' if bound else 'unbound'}_{abs(hash(busy))}.py"
    parent_file.write_text(
        _BUSY_CHILD_PARENT.format(
            src=_SRC,
            binding="_bind_lifetime_to_parent(expected_parent)" if bound else "pass",
            busy=busy,
        ),
        encoding="utf-8",
    )
    return _spawned_child_survives_killed_parent(parent_file, after_parent_kill=after_parent_kill)


def _assert_proof_pidfd_exited(pidfd: int, identity_exited) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not identity_exited(pidfd):
        time.sleep(0.05)
    assert identity_exited(pidfd), "the separately pinned child identity remained live after harness cleanup"


def _close_proof_pidfd(pidfd: int) -> None:
    try:
        os.close(pidfd)
    except OSError as exc:
        if exc.errno != errno.EBADF:
            raise


@_LINUX_ONLY
def test_stable_identity_uses_kernel_pidfd_when_python_omits_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if _PIDFD_OPEN_SYSCALL is None:
        pytest.skip(f"no reviewed pidfd_open syscall number for {platform.machine()}")

    monkeypatch.delattr(os, "pidfd_open", raising=False)
    pidfd = _stable_identity(os.getpid())
    try:
        assert not _identity_exited(pidfd)
        _signal_via_identity(pidfd, 0)
    finally:
        os.close(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_closes_preflight_and_child_pidfds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stable_identity = _stable_identity
    opened: list[int] = []

    def recording_stable_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        opened.append(pidfd)
        return pidfd

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_stable_identity)
    try:
        assert not _child_survives_a_killed_parent(tmp_path, bound=True, busy="time.sleep(600)")
        assert len(opened) == 2, "the harness must preflight once and pin the one spawned child once"
        for pidfd in set(opened):
            with pytest.raises(OSError) as raised:
                os.fstat(pidfd)
            assert raised.value.errno == errno.EBADF
    finally:
        for pidfd in set(opened):
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_reaps_exact_child_when_pidfd_setup_fails_after_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    proof_pidfds: list[int] = []

    def failing_child_identity(pid: int) -> int:
        if pid == os.getpid():
            return real_stable_identity(pid)
        child_pidfd = real_stable_identity(pid)
        proof_pidfds.append(os.dup(child_pidfd))
        os.close(child_pidfd)
        raise _UnstableIdentity("injected pidfd setup failure after SPAWNED")

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", failing_child_identity)
    try:
        with pytest.raises(_UnstableIdentity, match="injected pidfd setup failure"):
            _child_survives_a_killed_parent(tmp_path, bound=False, busy="time.sleep(600)")
        assert len(proof_pidfds) == 1
        _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
    finally:
        for pidfd in proof_pidfds:
            if not real_identity_exited(pidfd):
                _signal_via_identity(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_reaps_exact_child_when_pidfd_poll_fails_during_post_parent_kill_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_reap_adopted_child = _reap_adopted_child
    real_signal_via_identity = _signal_via_identity
    real_wait_for_identity_exit = _wait_for_identity_exit
    child_pidfds: list[int] = []
    child_pids: list[int] = []
    proof_pidfds: list[int] = []
    sigkill_attempts: list[int] = []
    reaped_child_pids: list[int] = []
    wait_calls = 0
    cleanup_poll_armed = False
    emergency_sigkill_required = False
    injected = False

    def recording_child_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        if pid != os.getpid():
            child_pidfds.append(pidfd)
            child_pids.append(pid)
            proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def skip_main_settlement_then_poll_in_cleanup(pidfd: int, *, timeout: float) -> bool:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            return False
        return real_wait_for_identity_exit(pidfd, timeout=timeout)

    def fail_cleanup_poll(pidfd: int) -> bool:
        nonlocal injected
        if cleanup_poll_armed and child_pidfds and pidfd == child_pidfds[-1] and not injected:
            injected = True
            raise OSError(errno.EIO, "injected pidfd poll failure during post-parent-kill cleanup")
        return real_identity_exited(pidfd)

    def arm_cleanup_poll() -> None:
        nonlocal cleanup_poll_armed
        cleanup_poll_armed = True

    def recording_signal(pidfd: int, sig: int) -> None:
        if child_pidfds and pidfd == child_pidfds[-1] and sig == signal.SIGKILL:
            sigkill_attempts.append(pidfd)
        real_signal_via_identity(pidfd, sig)

    def recording_reap(child_pid: int) -> None:
        nonlocal emergency_sigkill_required
        if not sigkill_attempts:
            # Keep the red control bounded even when the pre-fix cleanup skips SIGKILL
            # and enters blocking waitpid(child_pid, 0). This emergency signal bypasses
            # the recorder so it cannot satisfy the side-effect assertion below.
            emergency_sigkill_required = True
            real_signal_via_identity(proof_pidfds[0], signal.SIGKILL)
        real_reap_adopted_child(child_pid)
        reaped_child_pids.append(child_pid)

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_wait_for_identity_exit", skip_main_settlement_then_poll_in_cleanup)
    monkeypatch.setattr(sys.modules[__name__], "_identity_exited", fail_cleanup_poll)
    monkeypatch.setattr(sys.modules[__name__], "_signal_via_identity", recording_signal)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", recording_reap)
    try:
        with pytest.raises(AssertionError, match="injected pidfd poll failure during post-parent-kill cleanup"):
            _child_survives_a_killed_parent(
                tmp_path,
                bound=False,
                busy="time.sleep(600)",
                after_parent_kill=arm_cleanup_poll,
            )
        assert injected is True
        assert emergency_sigkill_required is False, "the guard had to rescue a child cleanup left live"
        assert sigkill_attempts == child_pidfds, "cleanup must attempt exact-identity SIGKILL before its poll"
        assert wait_calls == 2, "the injected poll must come from cleanup after the main settlement deadline"
        assert len(child_pids) == 1
        assert reaped_child_pids == child_pids, "cleanup must complete the exact adopted-child reap"
        assert len(proof_pidfds) == 1
        _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
        with pytest.raises(ChildProcessError):
            os.waitpid(child_pids[0], os.WNOHANG)
    finally:
        for pidfd in proof_pidfds:
            if not real_identity_exited(pidfd):
                _signal_via_identity(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_reaps_adopted_child_when_first_post_kill_wait_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_reap_adopted_child = _reap_adopted_child
    child_pids: list[int] = []
    proof_pidfds: list[int] = []
    reaped_child_pids: list[int] = []
    parent_kill_succeeded = False
    injected = False

    def recording_child_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        if pid != os.getpid():
            child_pids.append(pid)
            proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def recording_reap(child_pid: int) -> None:
        real_reap_adopted_child(child_pid)
        reaped_child_pids.append(child_pid)

    def popen_with_first_post_kill_wait_failure(*args, **kwargs):
        parent = real_popen(*args, **kwargs)
        real_kill = parent.kill
        real_wait = parent.wait

        def recording_kill() -> None:
            nonlocal parent_kill_succeeded
            real_kill()
            parent_kill_succeeded = True

        def fail_first_post_kill_wait(timeout=None):
            nonlocal injected
            if parent_kill_succeeded and not injected:
                injected = True
                raise OSError(errno.EIO, "injected first parent wait failure after successful kill")
            return real_wait(timeout=timeout)

        parent.kill = recording_kill
        parent.wait = fail_first_post_kill_wait
        return parent

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", recording_reap)
    monkeypatch.setattr(subprocess, "Popen", popen_with_first_post_kill_wait_failure)
    try:
        with pytest.raises(OSError, match="injected first parent wait failure after successful kill"):
            _child_survives_a_killed_parent(tmp_path, bound=False, busy="time.sleep(600)")
        assert parent_kill_succeeded is True
        assert injected is True
        assert len(child_pids) == 1
        assert reaped_child_pids == child_pids
        assert len(proof_pidfds) == 1
        _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
        with pytest.raises(ChildProcessError):
            os.waitpid(child_pids[0], os.WNOHANG)
    finally:
        for pidfd in proof_pidfds:
            if not real_identity_exited(pidfd):
                _signal_via_identity(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
        for child_pid in child_pids:
            try:
                real_reap_adopted_child(child_pid)
            except AssertionError as exc:
                if not isinstance(exc.__cause__, ChildProcessError):
                    raise
        for pidfd in proof_pidfds:
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_retries_exact_sigkill_before_reap_and_pidfd_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_reap_adopted_child = _reap_adopted_child
    real_signal_via_identity = _signal_via_identity
    real_pidfd_send_signal_syscall = _pidfd_send_signal_syscall
    real_close = os.close
    child_pidfds: list[int] = []
    child_pids: list[int] = []
    proof_pidfds: list[int] = []
    fallback_sigkills: list[int] = []
    reaped_child_pids: list[int] = []
    closed_child_pidfds: list[int] = []
    cleanup_armed = False
    injected = False

    def recording_child_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        if pid != os.getpid():
            child_pidfds.append(pidfd)
            child_pids.append(pid)
            proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def fail_first_cleanup_sigkill(pidfd: int, sig: int) -> None:
        nonlocal injected
        if cleanup_armed and child_pidfds and pidfd == child_pidfds[-1] and sig == signal.SIGKILL and not injected:
            injected = True
            raise OSError(errno.EIO, "injected exact SIGKILL failure after engine death")
        real_signal_via_identity(pidfd, sig)

    def record_raw_fallback(pidfd: int, sig: int) -> None:
        if cleanup_armed and child_pidfds and pidfd == child_pidfds[-1] and sig == signal.SIGKILL:
            fallback_sigkills.append(pidfd)
        real_pidfd_send_signal_syscall(pidfd, sig)

    def record_reap(child_pid: int) -> None:
        real_reap_adopted_child(child_pid)
        reaped_child_pids.append(child_pid)

    def close_after_settlement(fd: int) -> None:
        if child_pidfds and fd == child_pidfds[-1]:
            assert real_identity_exited(fd), "the exact child pidfd was closed before process exit"
            assert reaped_child_pids == child_pids, "the exact child pidfd was closed before reap"
            closed_child_pidfds.append(fd)
        real_close(fd)

    def arm_cleanup() -> None:
        nonlocal cleanup_armed
        cleanup_armed = True

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_signal_via_identity", fail_first_cleanup_sigkill)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_send_signal_syscall", record_raw_fallback)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", record_reap)
    monkeypatch.setattr(os, "close", close_after_settlement)
    try:
        with pytest.raises(AssertionError, match="injected exact SIGKILL failure after engine death"):
            _child_survives_a_killed_parent(
                tmp_path,
                bound=False,
                busy="time.sleep(600)",
                after_parent_kill=arm_cleanup,
            )
        assert injected is True
        assert fallback_sigkills == child_pidfds, "cleanup must retry SIGKILL through the same exact pidfd"
        assert reaped_child_pids == child_pids, "cleanup must reap the exact adopted child after fallback SIGKILL"
        assert closed_child_pidfds == child_pidfds, "pidfd closure must follow exact exit and reap"
        assert len(proof_pidfds) == 1
        _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
        with pytest.raises(ChildProcessError):
            os.waitpid(child_pids[0], os.WNOHANG)
    finally:
        for pidfd in proof_pidfds:
            if not real_identity_exited(pidfd):
                real_pidfd_send_signal_syscall(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
        for child_pid in child_pids:
            try:
                real_reap_adopted_child(child_pid)
            except AssertionError as exc:
                if not isinstance(exc.__cause__, ChildProcessError):
                    raise
        for pidfd in proof_pidfds:
            try:
                real_close(pidfd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
        for pidfd in child_pidfds:
            try:
                real_close(pidfd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise


@_LINUX_ONLY
def test_lifecycle_harness_restores_subreaper_after_parent_stream_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_reap_adopted_child = _reap_adopted_child
    real_restore_child_subreaper = _restore_child_subreaper
    original_subreaper_state = _child_subreaper_state()

    def exercise(restore_action: Callable[[bool], None]) -> None:
        child_pids: list[int] = []
        proof_pidfds: list[int] = []
        reaped_child_pids: list[int] = []
        close_attempts: list[str] = []
        restored_states: list[bool] = []

        def recording_child_identity(pid: int) -> int:
            pidfd = real_stable_identity(pid)
            if pid != os.getpid():
                child_pids.append(pid)
                proof_pidfds.append(os.dup(pidfd))
            return pidfd

        def recording_reap(child_pid: int) -> None:
            real_reap_adopted_child(child_pid)
            reaped_child_pids.append(child_pid)

        class CloseProbe:
            def __init__(self, name: str, stream) -> None:
                self._name = name
                self._stream = stream

            def __getattr__(self, name: str):
                return getattr(self._stream, name)

            def close(self) -> None:
                close_attempts.append(self._name)
                self._stream.close()
                if self._name == "stdin":
                    raise OSError(errno.EIO, "injected first real stream close failure")
                if self._name == "stdout":
                    raise OSError(errno.EIO, "private later close detail must be sanitized")

        def popen_with_close_probes(*args, **kwargs):
            parent = real_popen(*args, **kwargs)
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(parent, name)
                if stream is not None:
                    setattr(parent, name, CloseProbe(name, stream))
            return parent

        def record_restore(previous: bool) -> None:
            restore_action(previous)
            restored_states.append(previous)

        real_restore_child_subreaper(False)
        assert _child_subreaper_state() is False
        with monkeypatch.context() as patch:
            patch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
            patch.setattr(sys.modules[__name__], "_reap_adopted_child", recording_reap)
            patch.setattr(sys.modules[__name__], "_restore_child_subreaper", record_restore)
            patch.setattr(subprocess, "Popen", popen_with_close_probes)
            try:
                with pytest.raises(AssertionError, match="injected first real stream close failure") as caught:
                    _child_survives_a_killed_parent(tmp_path, bound=True, busy="time.sleep(600)")
                assert close_attempts == ["stdin", "stdout", "stderr"]
                first_close_failure = caught.value.__cause__
                assert isinstance(first_close_failure, OSError)
                assert str(first_close_failure) == "[Errno 5] injected first real stream close failure"
                assert getattr(first_close_failure, "_cryodaq_later_stream_close_failures", ()) == ("stdout: OSError",)
                notes = getattr(first_close_failure, "__notes__", [])
                if notes:
                    assert notes == ["additional parent stream close failures: stdout: OSError"]
                assert "private later close detail" not in str(caught.value)
                assert len(child_pids) == 1
                assert reaped_child_pids == child_pids
                assert len(proof_pidfds) == 1
                _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
                with pytest.raises(ChildProcessError):
                    os.waitpid(child_pids[0], os.WNOHANG)
                assert restored_states == [False], (
                    "stream cleanup failure must attempt one restoration to the captured prior state"
                )
                assert _child_subreaper_state() is False, (
                    "restore helper call must restore the actual PR_GET_CHILD_SUBREAPER state"
                )
            finally:
                try:
                    for pidfd in proof_pidfds:
                        if not real_identity_exited(pidfd):
                            _signal_via_identity(pidfd, signal.SIGKILL)
                            _assert_proof_pidfd_exited(pidfd, real_identity_exited)
                    for child_pid in child_pids:
                        try:
                            real_reap_adopted_child(child_pid)
                        except AssertionError as exc:
                            if not isinstance(exc.__cause__, ChildProcessError):
                                raise
                    for pidfd in proof_pidfds:
                        _close_proof_pidfd(pidfd)
                finally:
                    real_restore_child_subreaper(False)

    try:
        exercise(real_restore_child_subreaper)
        with pytest.raises(AssertionError, match="actual PR_GET_CHILD_SUBREAPER"):
            exercise(lambda _previous: None)
    finally:
        real_restore_child_subreaper(original_subreaper_state)


@_LINUX_ONLY
def test_the_binding_decides_whether_a_sleeping_child_outlives_its_killed_parent(tmp_path) -> None:
    """Control and guard in one test, so neither can drift away from the other.

    SIGKILL is the one signal a process cannot handle, and therefore the one case the
    daemonic flag can never cover -- and this child ignores SIGTERM outright, so swapping
    the binding to SIGTERM cannot pass it either. Without the binding the child survives;
    with it the kernel kills it. If the control ever stops reproducing the orphan, this
    fails too -- which is the point, because a guard whose hazard cannot be reproduced is
    a guard nobody can trust.
    """

    assert _child_survives_a_killed_parent(tmp_path, bound=False, busy="time.sleep(600)"), (
        "the control must reproduce the orphan while sleeping, or the guard proves nothing"
    )
    assert not _child_survives_a_killed_parent(tmp_path, bound=True, busy="time.sleep(600)"), (
        "the source-owning child outlived its killed parent while sleeping; it could still "
        "finish a write after a replacement engine had commanded OFF"
    )


@_LINUX_ONLY
def test_the_binding_decides_whether_a_gil_holding_native_child_outlives_its_killed_parent(tmp_path) -> None:
    """The native-call shape: the child never returns to Python, bound or not."""

    busy = "import ctypes; ctypes.PyDLL('libc.so.6').sleep(600)"
    assert _child_survives_a_killed_parent(tmp_path, bound=False, busy=busy), (
        "the control must reproduce the orphan while holding the GIL in a native call, or the guard proves nothing"
    )
    assert not _child_survives_a_killed_parent(tmp_path, bound=True, busy=busy), (
        "the source-owning child outlived its killed parent while holding the GIL in a "
        "native call; it could still finish a write after a replacement engine had "
        "commanded OFF"
    )


@_LINUX_ONLY
def test_production_settle_process_open_worker_cannot_survive_killed_parent(tmp_path: Path) -> None:
    """Exercise the real Process(target=_visa_process_main) construction boundary.

    The fake is only pyvisa's native resource. Process construction, the entry point,
    lifetime binder, framed open request, and transport write path are all production.
    This is process-lifetime evidence only; it does not prove the killed USB transaction
    settled, was cancelled, or left the source OFF.
    READY is emitted only after the spawned VISA worker is inside the SIGTERM-immune native
    write, so parent death cannot be mistaken for ordinary pipe EOF settlement.
    """

    entered = tmp_path / "production_visa_write_entered"
    parent_file = tmp_path / "production_settle_process_open_parent.py"
    parent_file.write_text(
        _PRODUCTION_PROCESS_PARENT.format(src=_SRC, entered=str(entered)),
        encoding="utf-8",
    )

    assert not _spawned_child_survives_killed_parent(parent_file), (
        "the production-spawned VISA worker survived its killed engine parent"
    )


@_LINUX_ONLY
def test_reparented_worker_exits_before_pyvisa_open_after_prebinder_release(tmp_path: Path) -> None:
    """Exercise the initial parent mismatch through its production external effect.

    The exact production open request is buffered while the VISA child is blocked before
    ``_visa_process_main``. The harness is the nearest Linux subreaper: it kills the engine,
    waits for that death, then releases the adopted child. A binder that replaces the
    engine-captured PID with its new ``getppid()`` will continue into ResourceManager and
    create the marker. The correct binder exits first. This proves only process-lifetime
    fail-closed ordering, not USB transaction settlement, physical OFF, or restart authority.
    """

    blocked = tmp_path / "prebinder_blocked"
    pinned = tmp_path / "exact_pidfd_pinned"
    release = tmp_path / "release_after_engine_death"
    request_sent = tmp_path / "production_open_request_sent"
    visa_effect = tmp_path / "pyvisa_open_external_effect"
    parent_file = tmp_path / "production_prebinder_reparent_parent.py"
    parent_file.write_text(
        _PREBINDER_REPARENT_PARENT.format(
            src=_SRC,
            blocked=str(blocked),
            pinned=str(pinned),
            release=str(release),
            request_sent=str(request_sent),
            visa_effect=str(visa_effect),
        ),
        encoding="utf-8",
    )

    def release_after_engine_death() -> None:
        assert blocked.read_bytes() == b"BLOCKED_BEFORE_BINDER"
        assert request_sent.read_bytes() == b"OPEN_REQUEST_SENT"
        assert not visa_effect.exists(), "pyvisa ran while the child was still blocked before its binder"
        release.write_bytes(b"RELEASE")

    def publish_exact_child_pin() -> None:
        pinned.write_bytes(b"PIDFD_PINNED")

    assert not _spawned_child_survives_killed_parent(
        parent_file,
        after_child_pin=publish_exact_child_pin,
        after_parent_kill=release_after_engine_death,
        require_sigterm_immunity=False,
    ), "the reparented production VISA worker remained live after its pre-binder release"
    assert not visa_effect.exists(), (
        "the reparented worker reached pyvisa/open after its engine died; the initial parent "
        "mismatch did not fail closed"
    )


@_LINUX_ONLY
def test_the_binding_requests_exactly_pr_set_pdeathsig_with_sigkill() -> None:
    """The kernel contract is PR_SET_PDEATHSIG carrying SIGKILL -- arg for arg.

    A prctl double that accepts anything leaves the real request unpinned: swapping SIGKILL
    for a catchable signal still greens every marker. This pins the request itself, exactly,
    while the immune-child lifecycle above pins the same fact through the process effect.
    """

    finished = _probe(
        """
        import ctypes, json, os
        _expected = os.getppid()
        usbtmc.os.getppid = lambda: _expected

        class _Records:
            def prctl(self, *args):
                print("PRCTL ARGS " + json.dumps(list(args)), flush=True)
                return 0

        ctypes.CDLL = lambda *a, **k: _Records()
        """
    )
    from cryodaq.drivers.transport import usbtmc

    requested = [
        json.loads(line.removeprefix(b"PRCTL ARGS ").decode("ascii"))
        for line in finished.stdout.splitlines()
        if line.startswith(b"PRCTL ARGS ")
    ]
    assert usbtmc._PR_SET_PDEATHSIG == 1, "PR_SET_PDEATHSIG is kernel ABI 1"
    assert requested == [[1, int(signal.SIGKILL), 0, 0, 0]], (
        f"the binding must ask the kernel exactly for (PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0), got {requested}"
    )


@_WINDOWS_ONLY
def test_on_windows_an_unbound_worker_is_refused() -> None:
    """Windows must fail closed until it has an equivalent parent-death binding."""

    finished = _probe(
        """
        import ctypes, os
        _expected = os.getppid()

        class _Spy:
            def __init__(self, *a, **k):
                pass

            def prctl(self, *args):
                print("PRCTL CALLED", flush=True)
                return 0

        ctypes.CDLL = _Spy
        """
    )
    assert b"KEPT RUNNING" not in finished.stdout, "an unbound Windows worker must exit before it can own a VISA handle"
    assert b"PRCTL CALLED" not in finished.stdout, "no Linux parent-death binding may be pretended on Windows"


def _probe(body: str) -> subprocess.CompletedProcess:
    """Run one binding probe and require it to have REACHED the code under test.

    An absent "KEPT RUNNING" is not proof by itself: an import error, a broken double, or
    any unrelated failure produces the same silence. Every probe therefore prints a marker
    the moment it is about to call the binder, and the exit status is checked as well.
    """

    program = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_SRC!r})
        import cryodaq.drivers.transport.usbtmc as usbtmc
        {body}
        print("REACHED", flush=True)
        usbtmc._bind_lifetime_to_parent(_expected)
        print("KEPT RUNNING", flush=True)
        """
    )
    finished = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=30)
    assert b"REACHED" in finished.stdout, (
        f"the probe never reached the binder, so it proves nothing; stderr={finished.stderr[:600]!r}"
    )
    assert finished.returncode == 0, f"the probe failed for an unrelated reason: {finished.stderr[:600]!r}"
    return finished


@_LINUX_ONLY
def test_the_binding_refuses_rather_than_running_unbound() -> None:
    """A source-owning child that cannot be bound must not run at all.

    Refusing costs one failed open, which the transport reports. Continuing would risk the
    orphan the whole module exists to prevent, so the failure direction is deliberate.
    """

    finished = _probe(
        """
        import ctypes, os
        _expected = os.getppid()
        _calls = []

        class _Refuses:
            def prctl(self, *args):
                _calls.append(args)
                return -1

        ctypes.CDLL = lambda *a, **k: _Refuses()
        """
    )
    assert b"KEPT RUNNING" not in finished.stdout, (
        "a child that could not bind its lifetime to its parent must exit, not continue"
    )


@_LINUX_ONLY
def test_the_parent_changing_after_the_request_is_caught() -> None:
    """The race the second identity read exists for, exercised past prctl.

    The earlier version made the FIRST read return 1, so the function left through the
    already-reparented branch without ever loading libc or calling prctl -- deleting the
    post-call comparison left it green. This one answers with a real parent first and a
    different one after, and requires prctl to have been reached.
    """

    finished = _probe(
        """
        import ctypes, os
        _expected = os.getppid()
        _reads = iter([_expected, _expected + 100_000])
        usbtmc.os.getppid = lambda: next(_reads, _expected + 100_000)

        class _Accepts:
            def prctl(self, *_args):
                print("PRCTL REACHED", flush=True)
                return 0

        ctypes.CDLL = lambda *a, **k: _Accepts()
        """
    )
    assert b"PRCTL REACHED" in finished.stdout, "the race probe must invoke prctl before exiting"
    assert b"KEPT RUNNING" not in finished.stdout, (
        "a child whose parent changed after the request must exit; the signal will never come"
    )


@_LINUX_ONLY
def test_the_expected_parent_is_the_engines_pid_not_one_the_child_reads(tmp_path) -> None:
    """Reading it in the child is unsafe under a subreaper, and the soak runner is one.

    If the engine dies before the child's first instruction, getppid() answers with the
    surviving ancestor. Binding to THAT is binding to the wrong process, and the second
    read agrees with itself, so the orphan returns. The value therefore comes from the
    engine, captured before the spawn.
    """

    import inspect

    from cryodaq.drivers.transport import usbtmc

    spawn = inspect.getsource(usbtmc.USBTMCTransport._settle_process_open)
    assert "args=(child_connection, os.getpid())" in spawn, (
        "the engine must capture its own pid and hand it to the child"
    )
    binder = inspect.getsource(usbtmc._bind_lifetime_to_parent)
    assert "expected_parent: int" in binder
    assert "expected_parent = os.getppid()" not in binder, (
        "the child must not decide for itself which parent it belongs to"
    )


def test_the_binding_runs_before_any_handle_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order matters: a VISA session opened first would be what the orphan holds."""

    from cryodaq.drivers.transport import usbtmc

    events: list[tuple[str, object]] = []

    def bind(expected_parent: int) -> None:
        events.append(("bound", expected_parent))

    def worker(connection: object) -> None:
        assert events == [("bound", 321)]
        events.append(("worker", connection))

    connection = object()
    monkeypatch.setattr(usbtmc, "_bind_lifetime_to_parent", bind)
    monkeypatch.setattr(usbtmc, "_visa_worker_loop", worker)

    usbtmc._visa_process_main(connection, 321)

    assert events == [("bound", 321), ("worker", connection)]
