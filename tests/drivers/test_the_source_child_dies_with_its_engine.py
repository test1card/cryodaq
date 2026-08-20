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
"""

from __future__ import annotations

import contextlib
import os
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = str(_REPO_ROOT / "src")


def _alive(pid: int) -> bool:
    """True while the pid names a process that is not a reaped zombie."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    # "pid (comm) STATE ..." -- a zombie is gone for every purpose that matters here.
    return state.rsplit(")", 1)[-1].split()[0] != "Z"


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

        from cryodaq.drivers.transport.usbtmc import _bind_lifetime_to_parent
        {binding}
        # Whatever happens to the parent, this never looks at the pipe -- the shape of a
        # child inside a native call.
        {busy}

    if __name__ == "__main__":
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(target=_busy, args=(child_connection, os.getpid()), daemon=True)
        process.start()
        child_connection.close()
        print(process.pid, flush=True)
        time.sleep(600)
    """
)

_BUSY_SHAPES = {
    "sleeping": "time.sleep(600)",
    "holding the GIL in a native call": "import ctypes; ctypes.PyDLL('libc.so.6').sleep(600)",
}


def _child_survives_a_killed_parent(tmp_path, *, bound: bool, busy: str) -> bool:
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
        line = parent.stdout.readline().decode().strip()
        if not line.isdigit():
            raise AssertionError(_diagnose("no child pid reported"))
        child_pid = int(line)
        # The child must be alive AND have got past its own start-up, or a control that
        # reports "no orphan" is only reporting a child that never ran.
        time.sleep(1.0)
        if not _alive(child_pid):
            raise AssertionError(_diagnose("the child died before the parent was killed"))

        parent.kill()
        parent.wait(timeout=10)

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and _alive(child_pid):
            time.sleep(0.05)
        survived = _alive(child_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)
    if survived:
        # Reaping it is not optional either. It is no longer anyone's child, so nothing
        # will wait on it, and leaving it running is how one test's deliberate leak becomes
        # the next test's environment.
        with contextlib.suppress(OSError):
            os.kill(child_pid, signal.SIGKILL)
        gone_by = time.monotonic() + 10.0
        while time.monotonic() < gone_by and _alive(child_pid):
            time.sleep(0.05)
        assert not _alive(child_pid), f"the control's leaked child {child_pid} could not be killed"
    return survived


@_LINUX_ONLY
@pytest.mark.parametrize("shape", sorted(_BUSY_SHAPES), ids=lambda s: s.replace(" ", "-"))
def test_the_binding_decides_whether_a_busy_child_outlives_its_killed_parent(tmp_path, shape: str) -> None:
    """Control and guard in one test, so neither can drift away from the other.

    SIGKILL is the one signal a process cannot handle, and therefore the one case the
    daemonic flag can never cover. Without the binding the child survives; with it the
    kernel kills it. If the control ever stops reproducing the orphan, this fails too --
    which is the point, because a guard whose hazard cannot be reproduced is a guard nobody
    can trust.
    """

    busy = _BUSY_SHAPES[shape]
    assert _child_survives_a_killed_parent(tmp_path, bound=False, busy=busy), (
        f"the control must reproduce the orphan while {shape}, or the guard proves nothing"
    )
    assert not _child_survives_a_killed_parent(tmp_path, bound=True, busy=busy), (
        f"the source-owning child outlived its killed parent while {shape}; it could still "
        "finish a write after a replacement engine had commanded OFF"
    )


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
        _marker = os.environ.get("CRYODAQ_PRCTL_MARKER", "/dev/null")
        usbtmc.os.getppid = lambda: next(_reads, _expected + 100_000)

        class _Accepts:
            def prctl(self, *_args):
                open(_marker, "w").write("prctl reached")
                return 0

        ctypes.CDLL = lambda *a, **k: _Accepts()
        """
    )
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
