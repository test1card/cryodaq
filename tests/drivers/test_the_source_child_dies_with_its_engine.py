"""The process that owns the source must not outlive the process that owns it.

WHY THIS MODULE EXISTS. ``USBTMCTransport`` is the Keithley's transport, and the Keithley
drives the heater. It puts the native VISA session in a separate ``multiprocessing`` child
so a blocking native call cannot stall the engine's event loop. That child is created with
``daemon=True``, and a daemonic child is terminated from an ``atexit`` handler -- which runs
only when the parent exits NORMALLY. An engine that is killed, or that crashes, never runs
it.

The survivor is not merely untidy. The launcher restarts a dead engine; the replacement
connects and commands OFF on every channel; and the orphan's pending write can land AFTER
that, leaving the instrument sourcing while the software believes it is off. Two owners of
one source is the exact hazard the ownership design exists to prevent, and it is the reason
an engine crash may be answered with a restart at all.

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

import contextlib
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


class _UnstableIdentity(RuntimeError):
    """The kernel surface for stable process identity is unavailable here."""


def _stable_identity(pid: int) -> int:
    """Open a pidfd BEFORE anything can exit and its number be reused."""

    if _PIDFD_SEND_SIGNAL_SYSCALL is None or not hasattr(os, "pidfd_open"):
        raise _UnstableIdentity(f"no pidfd surface on {platform.machine()} / {sys.version_info[:3]}")
    try:
        return os.pidfd_open(pid)
    except OSError as exc:
        raise _UnstableIdentity(str(exc)) from exc


def _identity_exited(pidfd: int) -> bool:
    """True once the exact process behind the pidfd has terminated (zombie counts)."""

    with selectors.DefaultSelector() as selector:
        selector.register(pidfd, selectors.EVENT_READ)
        return bool(selector.select(0))


def _signal_via_identity(pidfd: int, sig: int) -> None:
    """Signal the EXACT process the pidfd names; ESRCH means it is already gone."""

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
        process.start()
        child_connection.close()
        if not parent_connection.poll(10):
            raise RuntimeError("child did not report readiness after binding")
        if parent_connection.recv() != "READY":
            raise RuntimeError("child reported an invalid readiness marker")
        print(f"READY {{process.pid}}", flush=True)
        time.sleep(600)
    """
)


def _read_startup_line(stream, *, timeout: float) -> str:
    """Return one flushed parent startup line, or an empty string at the deadline."""

    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        if not selector.select(timeout):
            return ""
    return stream.readline().decode().strip()


def _child_survives_a_killed_parent(tmp_path, *, bound: bool, busy: str) -> bool:
    """Kill a parent with SIGKILL and report whether its busy child outlived it."""

    # A skip after READY leaks the deliberately unbound child: it detached its descriptors,
    # ignores SIGTERM, and can remain in its 600-second call. Confirm the identity primitive
    # before any such child exists, so an unsupported host skips without creating an orphan.
    try:
        preflight_pidfd = _stable_identity(os.getpid())
    except _UnstableIdentity as exc:
        pytest.skip(
            "no stable process identity on this host: refusing to spawn an uncleanable "
            f"control child ({exc}). Parent-death evidence requires the Ubuntu 22.04-class "
            "kernel (pidfd plus pidfd_send_signal, >= 5.3); this limitation is the open "
            "target-OS gate, not a pass."
        )
    else:
        os.close(preflight_pidfd)

    parent_file = tmp_path / f"parent_{'bound' if bound else 'unbound'}_{abs(hash(busy))}.py"
    parent_file.write_text(
        _BUSY_CHILD_PARENT.format(
            src=_SRC,
            binding="_bind_lifetime_to_parent(expected_parent)" if bound else "pass",
            busy=busy,
        ),
        encoding="utf-8",
    )
    parent = subprocess.Popen([sys.executable, "-B", str(parent_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _diagnose(reason: str) -> str:
        """Kill the parent FIRST, then read its stderr.

        The parent sleeps for ten minutes and owns the write end of that pipe, so reading
        it while the parent lives blocks until the sleep ends -- turning a clear startup
        failure into a ten-minute hang with no message.
        """

        parent.kill()
        parent.wait(timeout=10)
        return f"{reason}; parent stderr={parent.stderr.read()[:600]!r}"

    try:
        assert parent.stdout is not None
        line = _read_startup_line(parent.stdout, timeout=10.0)
        marker, _, reported_pid = line.partition(" ")
        if marker != "READY" or not reported_pid.isdigit():
            raise AssertionError(_diagnose("no child pid reported"))
        child_pid = int(reported_pid)
        # A numeric pid is only a name; after its owner exits the kernel can hand it to an
        # unrelated process. Open the stable identity NOW, before anything is signalled or
        # polled, and fail closed where the kernel cannot provide one.
        try:
            child_pidfd = _stable_identity(child_pid)
        except _UnstableIdentity as exc:
            pytest.skip(
                "no stable process identity on this host: refusing to poll or signal a "
                f"reusable numeric pid ({exc}). Parent-death evidence requires the "
                "Ubuntu 22.04-class kernel (pidfd plus pidfd_send_signal, >= 5.3); this "
                "limitation is the open target-OS gate, not a pass."
            )
        # READY is sent by the child only after the binding (or its equivalent no-binding
        # control point). Killing the parent only after this marker makes the test prove
        # the parent-death guard rather than a late child's initial identity check.
        if _identity_exited(child_pidfd):
            raise AssertionError(_diagnose("the child died before the parent was killed"))
        # Prove the immunity live: a direct SIGTERM must leave the child running, so its
        # death AFTER the parent's death can only be the kernel's SIGKILL delivery.
        _signal_via_identity(child_pidfd, signal.SIGTERM)
        time.sleep(0.2)
        if _identity_exited(child_pidfd):
            raise AssertionError(_diagnose("the child died of a bare SIGTERM; only SIGKILL may close it"))

        parent.kill()
        parent.wait(timeout=10)

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and not _identity_exited(child_pidfd):
            time.sleep(0.05)
        survived = not _identity_exited(child_pidfd)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)
    if survived:
        # Reaping it is not optional either. It is no longer anyone's child, so nothing
        # will wait on it, and leaving it running is how one test's deliberate leak becomes
        # the next test's environment. The kill goes through the same stable identity as
        # every other signal above.
        with contextlib.suppress(ProcessLookupError):
            _signal_via_identity(child_pidfd, signal.SIGKILL)
        gone_by = time.monotonic() + 10.0
        while time.monotonic() < gone_by and not _identity_exited(child_pidfd):
            time.sleep(0.05)
        assert _identity_exited(child_pidfd), (
            f"the control's leaked child {child_pid} could not be killed through its pidfd"
        )
    return survived


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
