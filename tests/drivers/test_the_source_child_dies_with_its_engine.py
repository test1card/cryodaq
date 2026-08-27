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


def _pidfd_open_syscall(pid: int) -> int:
    """Open one exact process identity without depending on Python's wrapper."""

    if _PIDFD_OPEN_SYSCALL is None:
        raise _UnstableIdentity(f"no pidfd_open syscall on {platform.machine()} / {sys.version_info[:3]}")
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
    raise _UnstableIdentity(os.strerror(code)) from OSError(code, os.strerror(code))


def _stable_identity(pid: int) -> int:
    """Open a pidfd before reuse, recovering independently from wrapper failure."""

    if _PIDFD_SEND_SIGNAL_SYSCALL is None or _PIDFD_OPEN_SYSCALL is None:
        raise _UnstableIdentity(f"no pidfd surface on {platform.machine()} / {sys.version_info[:3]}")

    wrapper_error: BaseException | None = None
    if hasattr(os, "pidfd_open"):
        try:
            return os.pidfd_open(pid)
        except (OSError, ValueError) as exc:
            wrapper_error = exc

    # The laboratory conda-forge Python can omit os.pidfd_open even though its
    # Ubuntu 22.04 kernel provides the syscall. A present wrapper can also fail
    # after preflight. In both cases use an independently resolved raw syscall,
    # never another alias of the same Python wrapper or a reusable numeric PID.
    try:
        return _pidfd_open_syscall(pid)
    except (_UnstableIdentity, OSError, ValueError) as raw_error:
        if wrapper_error is None:
            raise _UnstableIdentity(str(raw_error)) from raw_error
        raise _UnstableIdentity(
            f"os.pidfd_open failed ({wrapper_error}); raw pidfd_open failed ({raw_error})"
        ) from wrapper_error


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


# Keep parent lifecycle seams distinct from the child seams that existing mutation guards
# replace. Both aliases still use the same kernel pidfd authority; the separation lets a
# guard falsify parent pinning/signalling without also changing the child under test.
_stable_parent_identity = _stable_identity
_recover_parent_identity = _stable_identity
_recover_child_identity = _stable_identity
_adopted_descendant_identity = _stable_identity
_signal_parent_via_identity = _signal_via_identity


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


_reap_adopted_descendant = _reap_adopted_child


def _restore_child_subreaper(previous: bool) -> None:
    _set_child_subreaper(previous)


# The parent is written to a FILE, never passed with -c: `spawn` re-imports the main module
# to rebuild the target, and a `-c` main module cannot be re-imported.
_BUSY_CHILD_PARENT = textwrap.dedent(
    """
    import multiprocessing, os, sys, time
    from pathlib import Path
    sys.path.insert(0, {src!r})

    _identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
    _gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])

    def _busy(_connection, expected_parent):
        # Publish identity before the worker can become signal-immune or touch VISA.
        _identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
        while not _gate.is_file():
            time.sleep(0.01)

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
        if sys.stdin.buffer.readline().strip() != b"START":
            raise RuntimeError("parent did not receive the exact start authority")
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
    import asyncio, ctypes, os, signal, sys, time, types
    from pathlib import Path
    sys.path.insert(0, {src!r})


    _entered = Path({entered!r})
    _identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
    _gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])

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

    from cryodaq.drivers.transport import usbtmc as _usbtmc

    _production_visa_process_main = _usbtmc._visa_process_main

    def _identity_gated_visa_process_main(connection, expected_parent):
        _identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
        while not _gate.is_file():
            time.sleep(0.01)
        _production_visa_process_main(connection, expected_parent)

    _usbtmc._visa_process_main = _identity_gated_visa_process_main

    async def _main():
        if (await asyncio.to_thread(sys.stdin.buffer.readline)).strip() != b"START":
            raise RuntimeError("parent did not receive the exact start authority")
        transport = _usbtmc.USBTMCTransport(mock=False)
        try:
            opening = asyncio.create_task(
                transport._settle_process_open("USB0::PRODUCTION-SPAWN-PROBE")
            )
            deadline = asyncio.get_running_loop().time() + 10.0
            while True:
                owner = transport._process_owner
                if opening.done():
                    await opening
                if owner is not None and owner.process.pid is not None:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("production spawn returned no exact process owner")
                await asyncio.sleep(0.01)
            print(f"SPAWNED {{owner.process.pid}}", flush=True)
            await opening
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
    import asyncio, os, sys, time, types
    from pathlib import Path
    sys.path.insert(0, {src!r})

    _blocked = Path({blocked!r})
    _identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
    _gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
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
        _identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
        while not _gate.is_file():
            time.sleep(0.01)
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
        if (await asyncio.to_thread(sys.stdin.buffer.readline)).strip() != b"START":
            raise RuntimeError("parent did not receive the exact start authority")
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
    """Read one newline-terminated frame without ever entering blocking ``readline``.

    Readiness says that *some* bytes exist, not that a complete line exists. The old
    select-then-readline sequence could therefore wait forever when a faulty parent kept
    stdout open after writing a partial frame. One-byte ``os.read`` calls preserve the
    framing boundary while every wait remains under the same monotonic deadline.
    """

    deadline = time.monotonic() + timeout
    frame = bytearray()
    fd = stream.fileno()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return ""
            chunk = os.read(fd, 1)
            if not chunk:
                return frame.decode(errors="replace").strip()
            if chunk == b"\n":
                return frame.decode(errors="replace").strip()
            frame.extend(chunk)


def _pidfd_process_id(pidfd: int) -> int:
    """Return the kernel identity named by a pidfd, never a caller-supplied PID."""

    for line in Path(f"/proc/self/fdinfo/{pidfd}").read_text(encoding="ascii").splitlines():
        key, separator, value = line.partition(":")
        if key == "Pid" and separator and value.strip().isdigit():
            return int(value.strip())
    raise _UnstableIdentity(f"pidfd {pidfd} exposed no kernel Pid field")


def _proc_parent_pid(pid: int) -> int:
    """Read Linux's kernel-maintained parent relationship for one live process."""

    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    close = stat.rfind(")")
    if close < 0:
        raise _UnstableIdentity(f"malformed /proc/{pid}/stat")
    fields = stat[close + 2 :].split()
    if len(fields) < 2 or not fields[1].isdigit():
        raise _UnstableIdentity(f"missing PPid in /proc/{pid}/stat")
    return int(fields[1])


def _validate_child_authority(
    child_pid: int,
    child_pidfd: int,
    parent_pid: int,
    parent_pidfd: int,
) -> None:
    """Authenticate a numeric frame against two exact pidfds and the kernel lineage."""

    if _pidfd_process_id(parent_pidfd) != parent_pid:
        raise _UnstableIdentity("the retained parent pidfd no longer names the Popen parent")
    if _pidfd_process_id(child_pidfd) != child_pid:
        raise _UnstableIdentity("the candidate child pidfd does not name the framed process")
    if _proc_parent_pid(child_pid) != parent_pid:
        raise _UnstableIdentity("the framed process is not a kernel child of the pinned parent")
    if _identity_exited(parent_pidfd) or _identity_exited(child_pidfd):
        raise _UnstableIdentity("parent or child exited before lineage authentication completed")


def _direct_child_pids() -> set[int]:
    """Return this process's current kernel children (including adopted orphans)."""

    children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
    text = children.read_text(encoding="ascii").strip()
    return {int(value) for value in text.split()} if text else set()


_ADOPTED_PIN_RETRY_LIMIT = 3
_ADOPTED_PIN_RETRY_BACKOFF_S = 0.02
_ADOPTED_PIN_RETRY_BACKOFF_MAX_S = 0.1
_ADOPTED_DIAGNOSTIC_ENTRY_LIMIT = 12
_ADOPTED_DIAGNOSTIC_TEXT_LIMIT = 180
_ADOPTED_DIAGNOSTIC_TOTAL_LIMIT = 2048


def _settle_new_adopted_descendants(
    baseline: set[int],
    known_pids: set[int],
    *,
    timeout: float = 10.0,
) -> None:
    """Kill and reap every newly adopted descendant before restoring subreaper state."""

    deadline = time.monotonic() + timeout
    empty_observations = 0
    pin_failures: dict[int, int] = {}
    first_error: BaseException | None = None
    error_details: list[str] = []
    seen_details: set[str] = set()
    suppressed_details = 0

    def record_error(context: str, error: BaseException) -> None:
        nonlocal first_error, suppressed_details
        if first_error is None:
            first_error = error
        raw_detail = f"{context}: {type(error).__name__}: {error}"
        detail = raw_detail[:_ADOPTED_DIAGNOSTIC_TEXT_LIMIT]
        if detail in seen_details:
            return
        seen_details.add(detail)
        if len(error_details) < _ADOPTED_DIAGNOSTIC_ENTRY_LIMIT:
            error_details.append(detail)
        else:
            suppressed_details += 1

    def fail(message: str) -> None:
        suffix = "; ".join(error_details)
        if suppressed_details:
            suffix += f"; {suppressed_details} additional distinct errors suppressed"
        diagnostic = f"{message}: {suffix}"[:_ADOPTED_DIAGNOSTIC_TOTAL_LIMIT]
        raise AssertionError(diagnostic) from first_error

    while time.monotonic() < deadline:
        candidates = _direct_child_pids() - baseline - known_pids
        if not candidates:
            empty_observations += 1
            if empty_observations >= 3:
                if first_error is not None:
                    fail("adopted descendant cleanup completed with errors")
                return
            time.sleep(_ADOPTED_PIN_RETRY_BACKOFF_S)
            continue
        empty_observations = 0
        # Inventory the entire generation before cleanup. A failure on one identity must
        # never prevent exact SIGKILL/reap attempts for its siblings.
        identities: list[tuple[int, int]] = []
        for candidate in sorted(candidates):
            if pin_failures.get(candidate, 0) >= _ADOPTED_PIN_RETRY_LIMIT:
                continue
            pidfd: int | None = None
            try:
                pidfd = _adopted_descendant_identity(candidate)
                if _pidfd_process_id(pidfd) != candidate or _proc_parent_pid(candidate) != os.getpid():
                    raise _UnstableIdentity(f"new process {candidate} was not authenticated as this subreaper's child")
                identities.append((candidate, pidfd))
                pin_failures.pop(candidate, None)
            except BaseException as exc:
                pin_failures[candidate] = pin_failures.get(candidate, 0) + 1
                record_error(f"pin adopted descendant {candidate}", exc)
                if pidfd is not None:
                    try:
                        os.close(pidfd)
                    except BaseException as close_exc:
                        record_error(f"close unauthenticated pidfd for {candidate}", close_exc)

        # Signal the complete pinned generation before waiting on any one descendant.
        # Otherwise a slow/failing first identity can delay SIGKILL to every sibling.
        for candidate, pidfd in identities:
            try:
                try:
                    _signal_via_identity(pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    record_error(f"signal adopted descendant {candidate}", exc)
                    # The raw syscall is deliberately independent of the fallible wrapper.
                    try:
                        _pidfd_send_signal_syscall(pidfd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except BaseException as recovery_exc:
                        record_error(f"raw signal adopted descendant {candidate}", recovery_exc)
            except BaseException as exc:
                record_error(f"signal adopted descendant {candidate}", exc)

        for candidate, pidfd in identities:
            exited = False
            reaped = False
            try:
                while time.monotonic() < deadline and not _identity_exited(pidfd):
                    time.sleep(_ADOPTED_PIN_RETRY_BACKOFF_S)
                exited = _identity_exited(pidfd)
                if not exited:
                    record_error(
                        f"wait adopted descendant {candidate}",
                        AssertionError("identity did not exit after exact SIGKILL"),
                    )
                if exited:
                    try:
                        _reap_adopted_descendant(
                            candidate,
                            timeout=max(0.0, deadline - time.monotonic()),
                        )
                        reaped = True
                    except AssertionError as exc:
                        if isinstance(exc.__cause__, ChildProcessError):
                            reaped = True
                        else:
                            record_error(f"reap adopted descendant {candidate}", exc)
                    except ChildProcessError:
                        reaped = True
            except BaseException as exc:
                record_error(f"settle adopted descendant {candidate}", exc)
            finally:
                if exited and reaped:
                    try:
                        os.close(pidfd)
                    except BaseException as exc:
                        record_error(f"close adopted descendant {candidate}", exc)
                else:
                    record_error(
                        f"retain adopted descendant {candidate}",
                        AssertionError(f"pidfd {pidfd} retained because exit and reap did not settle"),
                    )

        exhausted = sorted(
            candidate for candidate in candidates if pin_failures.get(candidate, 0) >= _ADOPTED_PIN_RETRY_LIMIT
        )
        if exhausted:
            for candidate in exhausted:
                record_error(
                    f"pin adopted descendant {candidate}",
                    AssertionError(f"retry limit {_ADOPTED_PIN_RETRY_LIMIT} reached"),
                )
            fail("adopted descendant cleanup failed")

        remaining = _direct_child_pids() - baseline - known_pids
        if remaining:
            retry_level = max((pin_failures.get(pid, 0) for pid in remaining), default=1)
            backoff = min(
                _ADOPTED_PIN_RETRY_BACKOFF_S * (2 ** max(0, retry_level - 1)),
                _ADOPTED_PIN_RETRY_BACKOFF_MAX_S,
            )
            time.sleep(min(backoff, max(0.0, deadline - time.monotonic())))

    remaining = _direct_child_pids() - baseline - known_pids
    if remaining:
        record_error(
            "adopted descendant deadline",
            AssertionError(f"new descendants did not settle before restore: {sorted(remaining)}"),
        )
    fail("adopted descendant cleanup failed")


def _preflight_stable_identity_surface() -> None:
    """Skip only before spawning, after proving every kernel surface we use."""

    pidfd: int | None = None
    try:
        pidfd = _stable_identity(os.getpid())
        if _identity_exited(pidfd):
            raise _UnstableIdentity("the current process pidfd was already readable")
        _signal_via_identity(pidfd, 0)
        _direct_child_pids()
    except (_UnstableIdentity, OSError, ValueError) as exc:
        pytest.skip(
            "no stable process identity or procfs child inventory on this host: refusing "
            f"to spawn an uncleanable control child ({exc}). Parent-death evidence requires "
            "the Ubuntu 22.04-class kernel (pidfd plus pidfd_send_signal, >= 5.3) and "
            "/proc/<pid>/task/<pid>/children; this limitation is the open target-OS gate, "
            "not a pass."
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


def _send_parent_command(parent: subprocess.Popen[bytes], command: bytes) -> None:
    assert parent.stdin is not None
    parent.stdin.write(command + b"\n")
    parent.stdin.flush()


def _wait_for_child_identity_file(
    identity_path: Path,
    parent_pidfd: int,
    *,
    timeout: float,
) -> int:
    """Read the live child's self-published PID before allowing hazardous startup."""

    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        try:
            last_text = identity_path.read_text(encoding="ascii")
        except FileNotFoundError:
            last_text = ""
        prefix = "PID "
        suffix = " END\n"
        if last_text.startswith(prefix) and last_text.endswith(suffix):
            framed_pid = last_text[len(prefix) : -len(suffix)]
            if framed_pid.isdigit():
                return int(framed_pid)
        if _identity_exited(parent_pidfd):
            raise AssertionError("harness parent exited before its child published exact identity")
        time.sleep(0.01)
    raise AssertionError(f"child did not publish exact identity before startup deadline; got {last_text!r}")


def _wait_for_numeric_pid_marker(
    marker_path: Path,
    *,
    expected_count: int,
    timeout: float,
) -> list[int]:
    """Wait for one complete numeric descendant marker, not mere file creation."""

    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        try:
            last_text = marker_path.read_text(encoding="ascii")
        except FileNotFoundError:
            last_text = ""
        values = last_text.split()
        if len(values) == expected_count and all(value.isdigit() for value in values):
            return [int(value) for value in values]
        time.sleep(0.01)
    raise AssertionError(
        f"descendant marker did not publish {expected_count} complete numeric identities; got {last_text!r}"
    )


_PARENT_CLEANUP_WAIT_S = 15.0
_PARENT_TERMINATE_WAIT_S = 2.0
_PARENT_KILL_WAIT_S = 10.0


def _wait_for_parent_exit(parent: subprocess.Popen[bytes], *, timeout: float) -> bool:
    try:
        parent.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _signal_exact_parent_and_wait(
    parent: subprocess.Popen[bytes],
    parent_pidfd: int,
    sig: int,
    *,
    timeout: float,
) -> bool:
    """Signal only the pinned parent identity and wait for the direct child boundedly."""

    try:
        _signal_parent_via_identity(parent_pidfd, sig)
    except ProcessLookupError:
        pass
    return _wait_for_parent_exit(parent, timeout=timeout)


def _request_exact_parent_cleanup(
    parent: subprocess.Popen[bytes], parent_pidfd: int
) -> tuple[bool, list[BaseException]]:
    """Settle the exact parent and return settlement separately from preserved errors."""

    errors: list[BaseException] = []
    if not _identity_exited(parent_pidfd):
        assert parent.stdin is not None
        try:
            parent.stdin.write(b"CLEANUP\n")
            parent.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            errors.append(exc)

    try:
        if _wait_for_parent_exit(parent, timeout=_PARENT_CLEANUP_WAIT_S):
            return True, errors
    except BaseException as exc:
        errors.append(exc)

    for sig, timeout in (
        (signal.SIGTERM, _PARENT_TERMINATE_WAIT_S),
        (signal.SIGKILL, _PARENT_KILL_WAIT_S),
    ):
        try:
            _signal_parent_via_identity(parent_pidfd, sig)
        except ProcessLookupError:
            pass
        except BaseException as exc:
            errors.append(exc)
            if sig == signal.SIGKILL:
                try:
                    _pidfd_send_signal_syscall(parent_pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as recovery_exc:
                    errors.append(recovery_exc)
        try:
            if _wait_for_parent_exit(parent, timeout=timeout):
                return True, errors
        except BaseException as exc:
            errors.append(exc)

    # Preserve every earlier error, but still make one final independent raw kill/wait
    # attempt. The caller owns propagation only after child/descendant settlement.
    try:
        _pidfd_send_signal_syscall(parent_pidfd, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except BaseException as exc:
        errors.append(exc)
    try:
        if _wait_for_parent_exit(parent, timeout=_PARENT_KILL_WAIT_S):
            return True, errors
    except BaseException as exc:
        errors.append(exc)
    errors.append(AssertionError("stalled harness parent did not settle after exact-identity SIGTERM and SIGKILL"))
    return False, errors


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
    before_parent_kill: Callable[[], None] | None = None,
    after_parent_kill: Callable[[], None] | None = None,
    require_sigterm_immunity: bool = True,
) -> bool:
    """Run one parent FILE and settle parent, child, pipes, and pidfds on every exit."""

    _preflight_stable_identity_surface()
    identity_token = f"{os.getpid()}-{time.monotonic_ns()}"
    identity_path = parent_file.with_name(f".{parent_file.name}.{identity_token}.child.pid")
    gate_path = parent_file.with_name(f".{parent_file.name}.{identity_token}.child.gate")
    parent_env = os.environ.copy()
    parent_env["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"] = str(identity_path)
    parent_env["CRYODAQ_HARNESS_CHILD_GATE_PATH"] = str(gate_path)
    try:
        previous_subreaper = _set_child_subreaper(True)
    except _UnstableIdentity as exc:
        pytest.skip(
            f"this Linux host cannot make the lifecycle harness the exact orphan reaper; refusing to spawn ({exc})"
        )
    baseline_child_pids = _direct_child_pids()
    try:
        parent = subprocess.Popen(
            [sys.executable, "-B", str(parent_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=parent_env,
        )
    except BaseException:
        _restore_child_subreaper(previous_subreaper)
        raise
    try:
        # No START byte is granted until one exact parent authority exists. The recovery
        # wrappers are independent seams; the final direct kernel opener was preflighted
        # before Popen and never falls back to signalling ``parent.pid``.
        parent_pidfd = _stable_parent_identity(parent.pid)
    except BaseException as pin_error:
        recovery_pidfd: int | None = None
        cleanup_errors: list[BaseException] = []
        try:
            for opener in (_recover_parent_identity, _pidfd_open_syscall):
                try:
                    recovery_pidfd = opener(parent.pid)
                    break
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if recovery_pidfd is None:
                # With no exact signal authority, revoke startup by closing stdin and wait
                # only. Every parent FILE is required to block on START before spawning.
                if parent.stdin is not None:
                    try:
                        parent.stdin.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                try:
                    if not _wait_for_parent_exit(parent, timeout=_PARENT_KILL_WAIT_S):
                        raise AssertionError(
                            "all exact parent pin attempts failed and the unstarted parent ignored EOF"
                        )
                except BaseException as exc:
                    cleanup_errors.append(exc)
            else:
                parent_settled, parent_errors = _request_exact_parent_cleanup(parent, recovery_pidfd)
                cleanup_errors.extend(parent_errors)
                try:
                    if not parent_settled or not _identity_exited(recovery_pidfd):
                        raise AssertionError("recovered exact parent identity remained live")
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                _settle_new_adopted_descendants(baseline_child_pids, {parent.pid})
            except BaseException as exc:
                cleanup_errors.append(exc)
            if recovery_pidfd is not None:
                try:
                    os.close(recovery_pidfd)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                _close_parent_streams(parent)
            except BaseException as exc:
                cleanup_errors.append(exc)
            for scratch_path in (identity_path, gate_path):
                try:
                    scratch_path.unlink(missing_ok=True)
                except BaseException as exc:
                    cleanup_errors.append(exc)
        finally:
            try:
                _restore_child_subreaper(previous_subreaper)
            except BaseException as exc:
                cleanup_errors.append(exc)
        # Recovery failures are evidence, but the original pin failure remains the cause
        # once every side effect is proven settled and process-global state restored.
        unexpected = [error for error in cleanup_errors if not isinstance(error, _UnstableIdentity)]
        if unexpected:
            details = "; ".join(f"{type(error).__name__}: {error}" for error in cleanup_errors)
            raise AssertionError(f"parent pin failure cleanup failed: {details}") from pin_error
        raise
    child_pid: int | None = None
    child_pidfd: int | None = None
    parent_identity_settled = False
    try:
        _send_parent_command(parent, b"START")
        child_pid = _wait_for_child_identity_file(identity_path, parent_pidfd, timeout=10.0)
        # The child-writable frame is only a candidate. Open an exact pidfd, then authenticate
        # it as a live kernel child of the still-pinned Popen parent BEFORE assigning cleanup
        # authority or releasing the worker gate. A forged/reused numeric PID is closed
        # untouched and can never become a signal target.
        candidate_child_pidfd: int | None = None
        try:
            candidate_child_pidfd = _stable_identity(child_pid)
            _validate_child_authority(child_pid, candidate_child_pidfd, parent.pid, parent_pidfd)
        except BaseException:
            if candidate_child_pidfd is not None:
                os.close(candidate_child_pidfd)
            child_pid = None
            raise
        child_pidfd = candidate_child_pidfd
        if after_child_pin is not None:
            after_child_pin()
        spawned_pid = _reported_child_identity(parent, marker="SPAWNED", timeout=10.0)
        if spawned_pid != child_pid:
            raise AssertionError(f"SPAWNED changed child identity from {child_pid} to {spawned_pid}")
        # The parent-owned SPAWNED frame is the second authority. Only exact equality
        # with the self-report and authenticated pidfd permits a worker side effect.
        gate_path.write_bytes(b"PINNED")
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

        # From this boundary onward cleanup unconditionally attempts the exact adopted-child
        # waitpid after parent settlement. The hook reproduces death just before this signal.
        if before_parent_kill is not None:
            before_parent_kill()
        try:
            _signal_parent_via_identity(parent_pidfd, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=10)
        parent_identity_settled = True
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

            parent_identity_settled, parent_errors = _request_exact_parent_cleanup(parent, parent_pidfd)
            cleanup_errors.extend(parent_errors)

            if parent_identity_settled and child_pid is not None:
                # Always attempt the exact waitpid after parent settlement. A CLEANUP write
                # is not proof that the parent consumed it or completed Process.join: the
                # parent can die between flush and read. If the normal parent already joined,
                # ChildProcessError is positive evidence that no adopted zombie remains.
                try:
                    _reap_adopted_child(child_pid)
                    child_identity_settled = True
                    child_reap_settled = True
                except AssertionError as exc:
                    if isinstance(exc.__cause__, ChildProcessError):
                        child_reap_settled = True
                    else:
                        cleanup_errors.append(exc)
                except ChildProcessError:
                    child_reap_settled = True

            if child_pidfd is not None and child_identity_settled and child_reap_settled:
                try:
                    os.close(child_pidfd)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            elif child_pidfd is not None:
                cleanup_errors.append(
                    AssertionError(f"retained exact child pidfd {child_pidfd} because exit and reap did not settle")
                )

            if parent_identity_settled:
                try:
                    os.close(parent_pidfd)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            else:
                cleanup_errors.append(
                    AssertionError(f"retained exact parent pidfd {parent_pidfd} because parent exit did not settle")
                )

            if parent_identity_settled:
                try:
                    _settle_new_adopted_descendants(
                        baseline_child_pids,
                        ({parent.pid, child_pid} if child_pid is not None else {parent.pid}),
                    )
                except BaseException as exc:
                    cleanup_errors.append(exc)

            try:
                _close_parent_streams(parent)
            except BaseException as exc:
                cleanup_errors.append(exc)
            for scratch_path in (identity_path, gate_path):
                try:
                    scratch_path.unlink(missing_ok=True)
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
    before_parent_kill: Callable[[], None] | None = None,
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
    return _spawned_child_survives_killed_parent(
        parent_file,
        before_parent_kill=before_parent_kill,
        after_parent_kill=after_parent_kill,
    )


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
def test_missing_proc_children_inventory_skips_before_subreaper_or_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_pidfds: list[int] = []
    forbidden_calls: list[str] = []

    def preflight_identity(_pid: int) -> int:
        pidfd = os.open(os.devnull, os.O_RDONLY)
        opened_pidfds.append(pidfd)
        return pidfd

    def missing_children_inventory() -> set[int]:
        raise FileNotFoundError("injected missing /proc children inventory")

    def forbidden_subreaper(_enabled: bool) -> bool:
        forbidden_calls.append("subreaper")
        raise AssertionError("subreaper state changed after failed procfs preflight")

    def forbidden_spawn(*_args, **_kwargs):
        forbidden_calls.append("spawn")
        raise AssertionError("a process spawned after failed procfs preflight")

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", preflight_identity)
    monkeypatch.setattr(sys.modules[__name__], "_identity_exited", lambda _pidfd: False)
    monkeypatch.setattr(sys.modules[__name__], "_signal_via_identity", lambda _pidfd, _sig: None)
    monkeypatch.setattr(sys.modules[__name__], "_direct_child_pids", missing_children_inventory)
    monkeypatch.setattr(sys.modules[__name__], "_set_child_subreaper", forbidden_subreaper)
    monkeypatch.setattr(subprocess, "Popen", forbidden_spawn)

    with pytest.raises(pytest.skip.Exception, match="procfs child inventory"):
        _spawned_child_survives_killed_parent(tmp_path / "must_not_run.py")
    assert forbidden_calls == []
    assert len(opened_pidfds) == 1
    with pytest.raises(OSError) as raised:
        os.fstat(opened_pidfds[0])
    assert raised.value.errno == errno.EBADF


@pytest.mark.parametrize("wrapper_mode", ["failure", "absence"])
@_LINUX_ONLY
def test_child_and_adopted_pins_recover_raw_after_post_start_wrapper_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wrapper_mode: str,
) -> None:
    descendant_marker = tmp_path / f"raw_recovery_descendant_{wrapper_mode}"
    parent_file = tmp_path / f"post_start_pidfd_wrapper_{wrapper_mode}.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, signal, sys, time
            from pathlib import Path
            sys.path.insert(0, {_SRC!r})

            identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            descendant_marker = Path({str(descendant_marker)!r})

            def worker(connection, expected_parent):
                descendant = os.fork()
                if descendant == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    descendant_marker.write_text(str(os.getpid()), encoding="ascii")
                    time.sleep(600)
                    os._exit(0)
                while not descendant_marker.is_file():
                    time.sleep(0.01)
                identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
                while not gate.is_file():
                    time.sleep(0.01)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                from cryodaq.drivers.transport.usbtmc import _bind_lifetime_to_parent
                _bind_lifetime_to_parent(expected_parent)
                connection.send("READY")
                connection.close()
                time.sleep(600)

            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                context = multiprocessing.get_context("spawn")
                parent_connection, child_connection = context.Pipe(duplex=True)
                process = context.Process(
                    target=worker,
                    args=(child_connection, os.getpid()),
                    daemon=True,
                )
                try:
                    process.start()
                    child_connection.close()
                    print(f"SPAWNED {{process.pid}}", flush=True)
                    if not parent_connection.poll(10) or parent_connection.recv() != "READY":
                        raise RuntimeError("worker did not become READY")
                    print(f"READY {{process.pid}}", flush=True)
                    if sys.stdin.buffer.readline().strip() != b"CLEANUP":
                        raise RuntimeError("missing CLEANUP")
                finally:
                    if process.pid is not None:
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_parent_identity = _stable_parent_identity
    real_send_parent_command = _send_parent_command
    real_wrapper_open = getattr(os, "pidfd_open", _pidfd_open_syscall)
    real_raw_open = _pidfd_open_syscall
    real_identity_exited = _identity_exited
    real_reap_child = _reap_adopted_child
    real_close = os.close
    parent_pinned = False
    start_sent = False
    wrapper_failed_pids: set[int] = set()
    raw_opened: list[tuple[int, int]] = []
    live_raw_authorities: dict[int, int] = {}
    closed_raw_pids: list[int] = []
    proof_pidfds: dict[int, int] = {}
    reaped_pids: list[int] = []

    def record_parent_pin(pid: int) -> int:
        nonlocal parent_pinned
        pidfd = real_parent_identity(pid)
        parent_pinned = True
        return pidfd

    def fail_once_per_identity(pid: int, flags: int = 0) -> int:
        assert parent_pinned and start_sent
        assert flags == 0
        if pid not in wrapper_failed_pids:
            wrapper_failed_pids.add(pid)
            raise OSError(errno.EIO, f"injected post-START pidfd_open failure for {pid}")
        return real_wrapper_open(pid, flags)

    def send_start_then_remove_wrapper(parent: subprocess.Popen[bytes], command: bytes) -> None:
        nonlocal start_sent
        assert command == b"START"
        assert parent_pinned, "the wrapper surface changed before the parent identity was pinned"
        real_send_parent_command(parent, command)
        start_sent = True
        if wrapper_mode == "failure":
            monkeypatch.setattr(os, "pidfd_open", fail_once_per_identity, raising=False)
        else:
            monkeypatch.delattr(os, "pidfd_open", raising=False)

    def record_raw_open(pid: int) -> int:
        pidfd = real_raw_open(pid)
        if not start_sent:
            # Python may not expose os.pidfd_open at all. In that supported
            # environment the harness legitimately uses the raw syscall for
            # preflight and for pinning the parent before START; neither call
            # is the post-START recovery this guard is meant to measure.
            return pidfd
        assert parent_pinned, "post-START raw recovery ran before the parent was pinned"
        raw_opened.append((pid, pidfd))
        live_raw_authorities[pidfd] = pid
        proof_pidfds.setdefault(pid, os.dup(pidfd))
        return pidfd

    def record_close(fd: int) -> None:
        raw_pid = live_raw_authorities.pop(fd, None)
        if raw_pid is not None:
            closed_raw_pids.append(raw_pid)
        real_close(fd)

    def record_reap(pid: int, *, timeout: float = 10.0) -> None:
        real_reap_child(pid, timeout=timeout)
        reaped_pids.append(pid)

    monkeypatch.setattr(sys.modules[__name__], "_stable_parent_identity", record_parent_pin)
    monkeypatch.setattr(sys.modules[__name__], "_send_parent_command", send_start_then_remove_wrapper)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_open_syscall", record_raw_open)
    monkeypatch.setattr(os, "close", record_close)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", record_reap)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_descendant", record_reap)
    try:
        assert not _spawned_child_survives_killed_parent(parent_file)
        descendant_pid = int(descendant_marker.read_text(encoding="ascii"))
        recovered_pids = [pid for pid, _pidfd in raw_opened]
        assert len(recovered_pids) >= 2
        worker_pid = recovered_pids[0]
        assert worker_pid != descendant_pid
        assert descendant_pid in recovered_pids
        assert sorted(reaped_pids) == sorted(recovered_pids)
        if wrapper_mode == "failure":
            assert wrapper_failed_pids == set(recovered_pids)
        else:
            assert wrapper_failed_pids == set()
        assert live_raw_authorities == {}
        assert sorted(closed_raw_pids) == sorted(recovered_pids)
        for pid in recovered_pids:
            _assert_proof_pidfd_exited(proof_pidfds[pid], real_identity_exited)
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
    finally:
        for pid, proof_pidfd in proof_pidfds.items():
            if not real_identity_exited(proof_pidfd):
                _pidfd_send_signal_syscall(proof_pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(proof_pidfd, real_identity_exited)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            _close_proof_pidfd(proof_pidfd)


@_LINUX_ONLY
def test_partial_startup_frame_is_deadline_bounded_and_every_process_is_settled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_file = tmp_path / "partial_startup_frame_parent.py"
    parent_file.write_text(
        textwrap.dedent(
            """
            import multiprocessing, os, signal, sys, time
            from pathlib import Path
            identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            def child():
                identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
                while not gate.is_file():
                    time.sleep(0.01)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(600)
            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                process = multiprocessing.get_context("spawn").Process(target=child, daemon=True)
                try:
                    process.start()
                    sys.stdout.write("SPAW")
                    sys.stdout.flush()
                    time.sleep(600)
                finally:
                    if process.pid is not None:
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_identity = _stable_identity
    real_read = _read_startup_line
    real_reap = _reap_adopted_child
    child_pids: list[int] = []
    child_pidfds: list[int] = []
    proof_pidfds: list[int] = []
    reaped: list[int] = []
    original_subreaper = _child_subreaper_state()

    def record_identity(pid: int) -> int:
        pidfd = real_identity(pid)
        if pid != os.getpid():
            child_pids.append(pid)
            child_pidfds.append(pidfd)
            proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def record_reap(pid: int) -> None:
        real_reap(pid)
        reaped.append(pid)

    def short_read(stream, *, timeout: float) -> str:
        return real_read(stream, timeout=min(timeout, 0.3))

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", record_identity)
    monkeypatch.setattr(sys.modules[__name__], "_read_startup_line", short_read)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", record_reap)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    started = time.monotonic()
    try:
        with pytest.raises(AssertionError, match="parent did not report SPAWNED"):
            _spawned_child_survives_killed_parent(parent_file)
        assert time.monotonic() - started < 5.0, "a newline-free partial frame blocked past its deadline"
        assert len(child_pids) == 1
        assert reaped == child_pids
        assert _child_subreaper_state() is original_subreaper
        for pidfd in child_pidfds:
            with pytest.raises(OSError) as raised:
                os.fstat(pidfd)
            assert raised.value.errno == errno.EBADF
        for pidfd in proof_pidfds:
            _assert_proof_pidfd_exited(pidfd, _identity_exited)
    finally:
        for pidfd in proof_pidfds:
            if not _identity_exited(pidfd):
                _signal_via_identity(pidfd, signal.SIGKILL)
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_forged_child_pid_is_never_signalled_or_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    sentinel_pidfd = _stable_identity(sentinel.pid)
    forged_candidate_fds: list[int] = []
    parent_file = tmp_path / "forged_child_identity_parent.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, sys, time
            from pathlib import Path
            identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            def child():
                identity.write_text("PID {sentinel.pid} END\\n", encoding="ascii")
                while not gate.is_file():
                    time.sleep(0.01)
                raise RuntimeError("forged worker gate was released")
            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                process = multiprocessing.get_context("spawn").Process(target=child, daemon=True)
                try:
                    process.start()
                    time.sleep(600)
                finally:
                    if process.pid is not None:
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_identity = _stable_identity

    def record_forged_candidate(pid: int) -> int:
        pidfd = real_identity(pid)
        if pid == sentinel.pid:
            forged_candidate_fds.append(pidfd)
        return pidfd

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", record_forged_candidate)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    try:
        with pytest.raises(_UnstableIdentity, match="not a kernel child"):
            _spawned_child_survives_killed_parent(parent_file)
        assert not _identity_exited(sentinel_pidfd), "forged numeric identity caused sentinel settlement"
        assert len(forged_candidate_fds) == 1
        with pytest.raises(OSError) as raised:
            os.fstat(forged_candidate_fds[0])
        assert raised.value.errno == errno.EBADF
    finally:
        if not _identity_exited(sentinel_pidfd):
            _signal_via_identity(sentinel_pidfd, signal.SIGKILL)
        sentinel.wait(timeout=5)
        os.close(sentinel_pidfd)


@_LINUX_ONLY
def test_same_parent_sibling_forgery_never_releases_worker_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released = tmp_path / "forged_sibling_released"
    parent_file = tmp_path / "same_parent_sibling_forgery.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, sys, time
            from pathlib import Path
            identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            released = Path({str(released)!r})
            def forged_sibling():
                identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
                while not gate.is_file():
                    time.sleep(0.01)
                released.write_bytes(b"RELEASED")
                time.sleep(600)
            def actual_worker():
                time.sleep(600)
            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                context = multiprocessing.get_context("spawn")
                forged = context.Process(target=forged_sibling, daemon=True)
                actual = context.Process(target=actual_worker, daemon=True)
                forged.start()
                actual.start()
                try:
                    while not released.is_file():
                        time.sleep(0.01)
                    print(f"SPAWNED {{actual.pid}}", flush=True)
                    time.sleep(600)
                finally:
                    for process in (forged, actual):
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_read_startup_line = _read_startup_line

    def bounded_startup_read(stream, *, timeout: float) -> str:
        return real_read_startup_line(stream, timeout=min(timeout, 0.3))

    monkeypatch.setattr(sys.modules[__name__], "_read_startup_line", bounded_startup_read)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_TERMINATE_WAIT_S", 0.1)
    try:
        with pytest.raises(AssertionError, match="parent did not report SPAWNED"):
            _spawned_child_survives_killed_parent(parent_file)
        assert not released.exists(), "the forged same-parent sibling observed a RELEASED gate side effect"
    finally:
        released.unlink(missing_ok=True)


@_LINUX_ONLY
def test_parent_signal_error_preserves_error_after_child_descendant_reap_and_fd_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descendant_marker = tmp_path / "hidden_descendant"
    parent_file = tmp_path / "cleanup_error_parent.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, signal, sys, time
            from pathlib import Path
            identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            marker = Path({str(descendant_marker)!r})
            def worker():
                descendant = os.fork()
                if descendant == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    marker.write_text(str(os.getpid()), encoding="ascii")
                    time.sleep(600)
                    os._exit(0)
                identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
                while not gate.is_file():
                    time.sleep(0.01)
            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                process = multiprocessing.get_context("spawn").Process(target=worker, daemon=True)
                process.start()
                print(f"SPAWNED {{process.pid}}", flush=True)
                time.sleep(600)
            """
        ),
        encoding="utf-8",
    )
    real_child_identity = _stable_identity
    real_parent_signal = _signal_parent_via_identity
    real_adopted_identity = _adopted_descendant_identity
    real_reap_child = _reap_adopted_child
    real_identity_exited = _identity_exited
    real_close = os.close
    child_pids: list[int] = []
    child_pidfds: list[int] = []
    child_proofs: list[int] = []
    descendant_proofs: dict[int, int] = {}
    reaped_children: list[int] = []
    closed_child_pidfds: list[int] = []

    def record_child(pid: int) -> int:
        pidfd = real_child_identity(pid)
        if pid != os.getpid():
            child_pids.append(pid)
            child_pidfds.append(pidfd)
            child_proofs.append(os.dup(pidfd))
        return pidfd

    def fail_term(pidfd: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            raise OSError(errno.EIO, "injected parent TERM wrapper error")
        real_parent_signal(pidfd, sig)

    def record_adopted(pid: int) -> int:
        pidfd = real_adopted_identity(pid)
        descendant_proofs[pid] = os.dup(pidfd)
        return pidfd

    def record_reap(pid: int) -> None:
        real_reap_child(pid)
        reaped_children.append(pid)

    def record_close(fd: int) -> None:
        if fd in child_pidfds:
            assert real_identity_exited(fd)
            assert reaped_children == child_pids
            closed_child_pidfds.append(fd)
        real_close(fd)

    def stop_after_pin() -> None:
        deadline = time.monotonic() + 2.0
        while not descendant_marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert descendant_marker.is_file()
        raise RuntimeError("injected failure after exact child pin")

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", record_child)
    monkeypatch.setattr(sys.modules[__name__], "_signal_parent_via_identity", fail_term)
    monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", record_adopted)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", record_reap)
    monkeypatch.setattr(os, "close", record_close)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_TERMINATE_WAIT_S", 0.1)
    try:
        with pytest.raises(AssertionError, match="injected parent TERM wrapper error"):
            _spawned_child_survives_killed_parent(parent_file, after_child_pin=stop_after_pin)
        assert reaped_children == child_pids
        assert closed_child_pidfds == child_pidfds
        hidden_descendant_pid = int(descendant_marker.read_text(encoding="ascii"))
        assert hidden_descendant_pid in descendant_proofs
        for pidfd in child_proofs + list(descendant_proofs.values()):
            _assert_proof_pidfd_exited(pidfd, real_identity_exited)
        for pid in child_pids + list(descendant_proofs):
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
    finally:
        for pidfd in child_proofs + list(descendant_proofs.values()):
            if not real_identity_exited(pidfd):
                _pidfd_send_signal_syscall(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_adopted_descendant_signal_errors_retry_raw_and_attempt_every_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preflight_stable_identity_surface()
    marker = tmp_path / "adopted_descendants"
    launcher = tmp_path / "fork_two_descendants.py"
    launcher.write_text(
        textwrap.dedent(
            f"""
            import os, signal, time
            from pathlib import Path
            marker = Path({str(marker)!r})
            pids = []
            for _ in range(2):
                pid = os.fork()
                if pid == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    time.sleep(600)
                    os._exit(0)
                pids.append(pid)
            marker.write_text(" ".join(map(str, pids)), encoding="ascii")
            """
        ),
        encoding="utf-8",
    )
    previous_subreaper = _set_child_subreaper(True)
    baseline = _direct_child_pids()
    owner = subprocess.Popen([sys.executable, "-B", str(launcher)])
    owner.wait(timeout=5)
    descendant_pids = _wait_for_numeric_pid_marker(marker, expected_count=2, timeout=2.0)
    real_adopted_identity = _adopted_descendant_identity
    real_wrapper_signal = _signal_via_identity
    real_raw_signal = _pidfd_send_signal_syscall
    real_identity_exited = _identity_exited
    pidfd_to_pid: dict[int, int] = {}
    proof_pidfds: dict[int, int] = {}
    wrapper_attempts: list[int] = []
    raw_attempts: list[int] = []

    def record_adopted(pid: int) -> int:
        pidfd = real_adopted_identity(pid)
        pidfd_to_pid[pidfd] = pid
        proof_pidfds[pid] = os.dup(pidfd)
        return pidfd

    def fail_wrapper(pidfd: int, sig: int) -> None:
        if pidfd in pidfd_to_pid and sig == signal.SIGKILL:
            wrapper_attempts.append(pidfd_to_pid[pidfd])
            raise OSError(errno.EIO, f"injected descendant wrapper EIO for {pidfd_to_pid[pidfd]}")
        real_wrapper_signal(pidfd, sig)

    def record_raw(pidfd: int, sig: int) -> None:
        if pidfd in pidfd_to_pid and sig == signal.SIGKILL:
            raw_attempts.append(pidfd_to_pid[pidfd])
        real_raw_signal(pidfd, sig)

    monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", record_adopted)
    monkeypatch.setattr(sys.modules[__name__], "_signal_via_identity", fail_wrapper)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_send_signal_syscall", record_raw)
    try:
        with pytest.raises(AssertionError, match="injected descendant wrapper EIO"):
            _settle_new_adopted_descendants(baseline, {owner.pid}, timeout=3.0)
        assert sorted(wrapper_attempts) == sorted(descendant_pids)
        assert sorted(raw_attempts) == sorted(descendant_pids)
        assert sorted(proof_pidfds) == sorted(descendant_pids)
        for pid in descendant_pids:
            _assert_proof_pidfd_exited(proof_pidfds[pid], real_identity_exited)
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
    finally:
        for pid, pidfd in proof_pidfds.items():
            if not real_identity_exited(pidfd):
                real_raw_signal(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            _close_proof_pidfd(pidfd)
        _restore_child_subreaper(previous_subreaper)


@_LINUX_ONLY
def test_adopted_descendant_waits_share_one_deadline_and_signal_every_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = {101, 102, 103}
    timeout = 3.0
    now = 0.0
    signal_times: list[tuple[int, float]] = []

    def monotonic() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    def record_signal(pidfd: int, sig: int) -> None:
        assert sig == signal.SIGKILL
        signal_times.append((pidfd, now))

    monkeypatch.setattr(time, "monotonic", monotonic)
    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(sys.modules[__name__], "_direct_child_pids", lambda: candidates)
    monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", lambda pid: pid)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_process_id", lambda pidfd: pidfd)
    monkeypatch.setattr(sys.modules[__name__], "_proc_parent_pid", lambda _pid: os.getpid())
    monkeypatch.setattr(sys.modules[__name__], "_signal_via_identity", record_signal)
    monkeypatch.setattr(sys.modules[__name__], "_identity_exited", lambda _pidfd: False)

    with pytest.raises(AssertionError, match="adopted descendant cleanup failed"):
        _settle_new_adopted_descendants(set(), set(), timeout=timeout)

    assert [pid for pid, _at in signal_times] == sorted(candidates)
    assert {at for _pid, at in signal_times} == {0.0}
    assert now <= timeout + _ADOPTED_PIN_RETRY_BACKOFF_S


@_LINUX_ONLY
@pytest.mark.parametrize("fail_proof_open", [False, True])
def test_persistent_adopted_pin_failures_are_bounded_backed_off_and_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_proof_open: bool,
) -> None:
    _preflight_stable_identity_surface()
    marker = tmp_path / "persistent_pin_failure_descendants"
    launcher = tmp_path / "fork_two_persistent_pin_failures.py"
    launcher.write_text(
        textwrap.dedent(
            f"""
            import os, signal, time
            from pathlib import Path
            marker = Path({str(marker)!r})
            pids = []
            for _ in range(2):
                pid = os.fork()
                if pid == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    time.sleep(600)
                    os._exit(0)
                pids.append(pid)
            marker.write_text(" ".join(map(str, pids)), encoding="ascii")
            """
        ),
        encoding="utf-8",
    )
    baseline: set[int] = set()
    owner_pid: int | None = None
    descendant_pids: list[int] = []
    proof_pidfds: dict[int, int] = {}
    attempts: dict[int, int] = {}
    injected_text = "persistent adopted pin failure " + ("x" * 4096)
    proof_open_injected = False
    real_proof_open = _pidfd_open_syscall
    real_adopted_identity = _adopted_descendant_identity

    def persistent_pin_failure(pid: int) -> int:
        attempts[pid] += 1
        raise OSError(errno.EIO, injected_text)

    def open_proof(pid: int) -> int:
        nonlocal proof_open_injected
        if fail_proof_open and not proof_open_injected:
            proof_open_injected = True
            raise _UnstableIdentity("injected descendant proof pidfd failure")
        return real_proof_open(pid)

    previous_subreaper = _set_child_subreaper(True)
    try:
        baseline = _direct_child_pids()
        owner = subprocess.Popen([sys.executable, "-B", str(launcher)])
        owner_pid = owner.pid
        owner.wait(timeout=5)
        descendant_pids = _wait_for_numeric_pid_marker(marker, expected_count=2, timeout=2.0)
        attempts = {pid: 0 for pid in descendant_pids}
        try:
            for pid in descendant_pids:
                proof_pidfds[pid] = open_proof(pid)
        except _UnstableIdentity:
            if not fail_proof_open:
                raise
        else:
            if fail_proof_open:
                raise AssertionError("descendant proof pidfd failure was not injected")
            monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", persistent_pin_failure)
            started = time.monotonic()
            with pytest.raises(AssertionError) as raised:
                _settle_new_adopted_descendants(baseline, {owner.pid}, timeout=3.0)
            elapsed = time.monotonic() - started
            assert set(attempts) == set(descendant_pids)
            assert set(attempts.values()) == {3}
            assert elapsed >= 0.02
            assert elapsed < 1.0
            diagnostic = str(raised.value)
            assert len(diagnostic) <= 2048
            assert diagnostic.count("persistent adopted pin failure") == len(descendant_pids)
    finally:
        for pid, pidfd in proof_pidfds.items():
            if not _identity_exited(pidfd):
                _pidfd_send_signal_syscall(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, _identity_exited)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            os.close(pidfd)
        monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", real_adopted_identity)
        try:
            _settle_new_adopted_descendants(
                baseline,
                ({owner_pid} if owner_pid is not None else set()),
                timeout=3.0,
            )
        finally:
            _restore_child_subreaper(previous_subreaper)
    assert _child_subreaper_state() is previous_subreaper
    assert proof_open_injected is fail_proof_open
    for pid in descendant_pids:
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)


@_LINUX_ONLY
def test_parent_term_signal_and_first_wait_failures_still_end_in_exact_kill_and_reap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_file = tmp_path / "term_failure_parent.py"
    parent_file.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('STALLED', flush=True)\n"
        "time.sleep(600)\n",
        encoding="utf-8",
    )
    parent = subprocess.Popen(
        [sys.executable, "-B", str(parent_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pidfd = _stable_parent_identity(parent.pid)
    real_signal = _signal_parent_via_identity
    real_wait = parent.wait
    signals: list[int] = []
    first_wait_failed = False

    def fail_term(pidfd_arg: int, sig: int) -> None:
        assert pidfd_arg == pidfd
        signals.append(sig)
        if sig == signal.SIGTERM:
            raise OSError(errno.EIO, "injected exact TERM send failure")
        real_signal(pidfd_arg, sig)

    def fail_first_wait(timeout=None):
        nonlocal first_wait_failed
        if not first_wait_failed:
            first_wait_failed = True
            raise OSError(errno.EIO, "injected first parent wait failure")
        return real_wait(timeout=timeout)

    assert parent.stdout is not None
    assert _read_startup_line(parent.stdout, timeout=5.0) == "STALLED"
    parent.wait = fail_first_wait
    monkeypatch.setattr(sys.modules[__name__], "_signal_parent_via_identity", fail_term)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_TERMINATE_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_KILL_WAIT_S", 2.0)
    try:
        settled, errors = _request_exact_parent_cleanup(parent, pidfd)
        assert settled is True
        assert any("injected exact TERM send failure" in str(error) for error in errors)
        assert any("injected first parent wait failure" in str(error) for error in errors)
        assert first_wait_failed is True
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert _identity_exited(pidfd)
        assert parent.returncode == -signal.SIGKILL
        with pytest.raises(ChildProcessError):
            os.waitpid(parent.pid, os.WNOHANG)
    finally:
        if not _identity_exited(pidfd):
            real_signal(pidfd, signal.SIGKILL)
            real_wait(timeout=2)
        os.close(pidfd)
        _close_parent_streams(parent)


@_LINUX_ONLY
def test_unreported_sigterm_immune_descendant_is_inventoried_killed_and_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descendant_marker = tmp_path / "unreported_descendant_pid"
    partial_marker_observed = tmp_path / "unreported_descendant_partial_marker_observed"
    parent_file = tmp_path / "unreported_descendant_parent.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, signal, sys, time
            from pathlib import Path
            marker = Path({str(descendant_marker)!r})
            partial_observed = Path({str(partial_marker_observed)!r})
            def worker():
                descendant = os.fork()
                if descendant == 0:
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    marker.touch()
                    while not partial_observed.is_file():
                        time.sleep(0.01)
                    marker.write_text(str(os.getpid()), encoding="ascii")
                    time.sleep(600)
                    os._exit(0)
                time.sleep(600)
            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing START")
                process = multiprocessing.get_context("spawn").Process(target=worker, daemon=True)
                try:
                    process.start()
                    while not marker.is_file():
                        time.sleep(0.01)
                    time.sleep(600)
                finally:
                    if process.pid is not None:
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_wait_identity = _wait_for_child_identity_file
    real_adopted_identity = _adopted_descendant_identity
    real_read_text = Path.read_text
    descendant_proofs: dict[int, int] = {}
    inventoried: set[int] = set()

    def acknowledge_partial_marker(path: Path, *args, **kwargs) -> str:
        text = real_read_text(path, *args, **kwargs)
        if path == descendant_marker and text == "":
            partial_marker_observed.write_bytes(b"OBSERVED_EMPTY_MARKER")
        return text

    def short_identity_wait(path: Path, parent_pidfd: int, *, timeout: float) -> int:
        descendant_pid = _wait_for_numeric_pid_marker(
            descendant_marker,
            expected_count=1,
            timeout=0.5,
        )[0]
        descendant_proofs[descendant_pid] = _stable_identity(descendant_pid)
        return real_wait_identity(path, parent_pidfd, timeout=min(timeout, 0.5))

    def record_adopted(pid: int) -> int:
        pidfd = real_adopted_identity(pid)
        inventoried.add(pid)
        return pidfd

    monkeypatch.setattr(Path, "read_text", acknowledge_partial_marker)
    monkeypatch.setattr(sys.modules[__name__], "_wait_for_child_identity_file", short_identity_wait)
    monkeypatch.setattr(sys.modules[__name__], "_adopted_descendant_identity", record_adopted)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    try:
        with pytest.raises(AssertionError, match="child did not publish exact identity"):
            _spawned_child_survives_killed_parent(parent_file)
        descendant_pid = int(descendant_marker.read_text(encoding="ascii"))
        assert partial_marker_observed.read_bytes() == b"OBSERVED_EMPTY_MARKER"
        assert descendant_pid in inventoried, "the unreported descendant was never kernel-inventoried"
        _assert_proof_pidfd_exited(descendant_proofs[descendant_pid], _identity_exited)
        with pytest.raises(ChildProcessError):
            os.waitpid(descendant_pid, os.WNOHANG)
    finally:
        for adopted_pid, pidfd in descendant_proofs.items():
            if not _identity_exited(pidfd):
                _signal_via_identity(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, _identity_exited)
            try:
                _reap_adopted_child(adopted_pid)
            except AssertionError as exc:
                if not isinstance(exc.__cause__, ChildProcessError):
                    raise
            _close_proof_pidfd(pidfd)


@pytest.mark.parametrize("failing_suffix", [".child.pid", ".child.gate"])
@_LINUX_ONLY
def test_scratch_unlink_failure_cannot_skip_actual_subreaper_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_suffix: str,
) -> None:
    real_unlink = Path.unlink
    original_subreaper = _child_subreaper_state()
    injected: list[Path] = []

    def fail_selected_unlink(path: Path, *args, **kwargs) -> None:
        if str(path).endswith(failing_suffix) and not injected:
            injected.append(path)
            raise OSError(errno.EIO, f"injected unlink failure for {failing_suffix}")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_selected_unlink)
    try:
        with pytest.raises(AssertionError, match="injected unlink failure"):
            _child_survives_a_killed_parent(tmp_path, bound=True, busy="time.sleep(600)")
        assert len(injected) == 1
        assert _child_subreaper_state() is original_subreaper
    finally:
        for path in injected:
            real_unlink(path, missing_ok=True)


@_LINUX_ONLY
def test_stalled_harness_parent_is_exactly_terminated_killed_and_waited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_file = tmp_path / "stalled_parent.py"
    parent_file.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('STALLED', flush=True)\n"
        "time.sleep(600)\n",
        encoding="utf-8",
    )
    parent = subprocess.Popen(
        [sys.executable, "-B", str(parent_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    parent_pidfd = _stable_parent_identity(parent.pid)
    signals: list[int] = []
    real_parent_signal = _signal_parent_via_identity

    def recording_parent_signal(pidfd: int, sig: int) -> None:
        assert pidfd == parent_pidfd
        signals.append(sig)
        real_parent_signal(pidfd, sig)

    monkeypatch.setattr(sys.modules[__name__], "_signal_parent_via_identity", recording_parent_signal)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_TERMINATE_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_KILL_WAIT_S", 2.0)
    try:
        assert parent.stdout is not None
        assert _read_startup_line(parent.stdout, timeout=5.0) == "STALLED"
        settled, errors = _request_exact_parent_cleanup(parent, parent_pidfd)
        assert settled is True
        assert errors == []
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert parent.returncode == -signal.SIGKILL
        assert _identity_exited(parent_pidfd)
    finally:
        if not _identity_exited(parent_pidfd):
            real_parent_signal(parent_pidfd, signal.SIGKILL)
            parent.wait(timeout=2)
        os.close(parent_pidfd)
        _close_parent_streams(parent)


@_LINUX_ONLY
def test_pre_spawn_report_stall_settles_immune_child_by_preopened_pidfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    immune = tmp_path / "child_is_sigterm_immune"
    parent_file = tmp_path / "stall_after_immune_before_spawned.py"
    parent_file.write_text(
        textwrap.dedent(
            f"""
            import multiprocessing, os, signal, sys, time
            from pathlib import Path

            _identity = Path(os.environ["CRYODAQ_HARNESS_CHILD_IDENTITY_PATH"])
            _gate = Path(os.environ["CRYODAQ_HARNESS_CHILD_GATE_PATH"])
            _immune = Path({str(immune)!r})

            def _immune_child():
                _identity.write_text("PID " + str(os.getpid()) + " END\\n", encoding="ascii")
                while not _gate.is_file():
                    time.sleep(0.01)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                _immune.write_bytes(b"IMMUNE")
                time.sleep(600)

            if __name__ == "__main__":
                if sys.stdin.buffer.readline().strip() != b"START":
                    raise RuntimeError("missing start authority")
                process = multiprocessing.get_context("spawn").Process(
                    target=_immune_child,
                    daemon=True,
                )
                try:
                    process.start()
                    deadline = time.monotonic() + 10.0
                    while not _immune.is_file():
                        if time.monotonic() >= deadline:
                            raise RuntimeError("child never became signal-immune")
                        time.sleep(0.01)
                    time.sleep(600)  # Deliberately never publish SPAWNED.
                finally:
                    if process.pid is not None:
                        if process.is_alive():
                            process.kill()
                        process.join(10)
            """
        ),
        encoding="utf-8",
    )
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_read_startup_line = _read_startup_line
    child_pids: list[int] = []
    proof_pidfds: list[int] = []

    def recording_child_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        if pid != os.getpid():
            child_pids.append(pid)
            proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def bounded_startup_read(stream, *, timeout: float) -> str:
        return real_read_startup_line(stream, timeout=min(timeout, 0.5))

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_read_startup_line", bounded_startup_read)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_CLEANUP_WAIT_S", 0.1)
    monkeypatch.setattr(sys.modules[__name__], "_PARENT_TERMINATE_WAIT_S", 1.0)
    try:
        with pytest.raises(AssertionError, match="parent did not report SPAWNED"):
            _spawned_child_survives_killed_parent(parent_file)
        assert not immune.exists(), "the worker crossed its side-effect gate before SPAWNED corroboration"
        assert len(child_pids) == 1
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
        for child_pid in child_pids:
            try:
                _reap_adopted_child(child_pid)
            except AssertionError as exc:
                if not isinstance(exc.__cause__, ChildProcessError):
                    raise


@_LINUX_ONLY
def test_parent_pin_failure_settles_started_parent_before_restoring_subreaper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_effect = tmp_path / "start_was_granted"
    parent_file = tmp_path / "parent_waiting_for_start.py"
    parent_file.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        f"effect = Path({str(start_effect)!r})\n"
        "if sys.stdin.buffer.readline().strip() == b'START':\n"
        "    effect.write_bytes(b'STARTED')\n"
        "time.sleep(600)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    real_raw_open = _pidfd_open_syscall
    real_identity_exited = _identity_exited
    real_parent_signal = _signal_parent_via_identity
    parent_pids: list[int] = []
    proof_pidfds: list[int] = []
    raw_recovery_pids: list[int] = []

    def wrapper_failure(pid: int, flags: int = 0) -> int:
        raise _UnstableIdentity(f"injected real os.pidfd_open failure for {pid}/{flags}")

    def recording_popen(*args, **kwargs):
        parent = real_popen(*args, **kwargs)
        parent_pids.append(parent.pid)
        proof_pidfds.append(real_raw_open(parent.pid))
        # Force both named parent seams to fail only after Popen. The final raw opener
        # remains independent and must settle the still-unstarted parent.
        monkeypatch.setattr(sys.modules[__name__], "_stable_parent_identity", wrapper_failure)
        monkeypatch.setattr(sys.modules[__name__], "_recover_parent_identity", wrapper_failure)
        return parent

    def recording_raw_open(pid: int) -> int:
        raw_recovery_pids.append(pid)
        return real_raw_open(pid)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    monkeypatch.setattr(sys.modules[__name__], "_pidfd_open_syscall", recording_raw_open)
    try:
        with pytest.raises(_UnstableIdentity, match="injected real os.pidfd_open failure"):
            _spawned_child_survives_killed_parent(parent_file)
        assert not start_effect.exists(), "child creation authority must not be granted before parent pin"
        assert raw_recovery_pids[-1:] == parent_pids, "cleanup did not use the independent raw pidfd opener"
        assert len(parent_pids) == 1
        assert len(proof_pidfds) == 1
        _assert_proof_pidfd_exited(proof_pidfds[0], real_identity_exited)
        with pytest.raises(ChildProcessError):
            os.waitpid(parent_pids[0], os.WNOHANG)
    finally:
        for parent_pid, pidfd in zip(parent_pids, proof_pidfds, strict=True):
            if not real_identity_exited(pidfd):
                real_parent_signal(pidfd, signal.SIGKILL)
                _assert_proof_pidfd_exited(pidfd, real_identity_exited)
            try:
                os.waitpid(parent_pid, 0)
            except ChildProcessError:
                pass
            _close_proof_pidfd(pidfd)


@_LINUX_ONLY
def test_lifecycle_harness_pins_parent_before_startup_and_signals_same_pidfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_parent_identity = _stable_parent_identity
    real_parent_signal = _signal_parent_via_identity
    real_read_startup_line = _read_startup_line
    parent_pidfds: list[int] = []
    parent_signals: list[tuple[int, int]] = []

    def recording_parent_identity(pid: int) -> int:
        pidfd = real_parent_identity(pid)
        parent_pidfds.append(pidfd)
        return pidfd

    def startup_requires_parent_pin(stream, *, timeout: float) -> str:
        assert len(parent_pidfds) == 1, "parent pidfd must exist before any startup line is read"
        return real_read_startup_line(stream, timeout=timeout)

    def recording_parent_signal(pidfd: int, sig: int) -> None:
        parent_signals.append((pidfd, sig))
        real_parent_signal(pidfd, sig)

    monkeypatch.setattr(sys.modules[__name__], "_stable_parent_identity", recording_parent_identity)
    monkeypatch.setattr(sys.modules[__name__], "_read_startup_line", startup_requires_parent_pin)
    monkeypatch.setattr(sys.modules[__name__], "_signal_parent_via_identity", recording_parent_signal)

    assert not _child_survives_a_killed_parent(tmp_path, bound=True, busy="time.sleep(600)")
    assert len(parent_pidfds) == 1
    assert parent_signals == [(parent_pidfds[0], signal.SIGKILL)]
    with pytest.raises(OSError) as raised:
        os.fstat(parent_pidfds[0])
    assert raised.value.errno == errno.EBADF


@_LINUX_ONLY
def test_lifecycle_harness_reaps_child_when_parent_dies_before_explicit_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_parent_identity = _stable_parent_identity
    real_parent_signal = _signal_parent_via_identity
    real_stable_identity = _stable_identity
    real_identity_exited = _identity_exited
    real_reap_adopted_child = _reap_adopted_child
    parent_proof_pidfds: list[int] = []
    child_pids: list[int] = []
    reaped_child_pids: list[int] = []

    def recording_parent_identity(pid: int) -> int:
        pidfd = real_parent_identity(pid)
        parent_proof_pidfds.append(os.dup(pidfd))
        return pidfd

    def recording_child_identity(pid: int) -> int:
        pidfd = real_stable_identity(pid)
        if pid != os.getpid():
            child_pids.append(pid)
        return pidfd

    def kill_parent_before_harness_signal() -> None:
        assert len(parent_proof_pidfds) == 1
        real_parent_signal(parent_proof_pidfds[0], signal.SIGKILL)
        assert _wait_for_identity_exit(parent_proof_pidfds[0], timeout=2.0)

    def recording_reap(child_pid: int) -> None:
        real_reap_adopted_child(child_pid)
        reaped_child_pids.append(child_pid)

    monkeypatch.setattr(sys.modules[__name__], "_stable_parent_identity", recording_parent_identity)
    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", recording_reap)
    try:
        assert not _child_survives_a_killed_parent(
            tmp_path,
            bound=True,
            busy="time.sleep(600)",
            before_parent_kill=kill_parent_before_harness_signal,
        )
        assert len(child_pids) == 1
        assert reaped_child_pids == child_pids
        with pytest.raises(ChildProcessError):
            os.waitpid(child_pids[0], os.WNOHANG)
    finally:
        for pidfd in parent_proof_pidfds:
            if not real_identity_exited(pidfd):
                real_parent_signal(pidfd, signal.SIGKILL)
            _close_proof_pidfd(pidfd)
        for child_pid in child_pids:
            try:
                real_reap_adopted_child(child_pid)
            except AssertionError as exc:
                if not isinstance(exc.__cause__, ChildProcessError):
                    raise


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
    real_parent_signal = _signal_parent_via_identity
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

    def recording_parent_signal(pidfd: int, sig: int) -> None:
        nonlocal parent_kill_succeeded
        real_parent_signal(pidfd, sig)
        if sig == signal.SIGKILL:
            parent_kill_succeeded = True

    def popen_with_first_post_kill_wait_failure(*args, **kwargs):
        parent = real_popen(*args, **kwargs)
        real_wait = parent.wait

        def fail_first_post_kill_wait(timeout=None):
            nonlocal injected
            if parent_kill_succeeded and not injected:
                injected = True
                raise OSError(errno.EIO, "injected first parent wait failure after successful kill")
            return real_wait(timeout=timeout)

        parent.wait = fail_first_post_kill_wait
        return parent

    monkeypatch.setattr(sys.modules[__name__], "_stable_identity", recording_child_identity)
    monkeypatch.setattr(sys.modules[__name__], "_reap_adopted_child", recording_reap)
    monkeypatch.setattr(sys.modules[__name__], "_signal_parent_via_identity", recording_parent_signal)
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
