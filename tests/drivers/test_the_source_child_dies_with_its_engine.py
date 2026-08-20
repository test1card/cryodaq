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

WHICH CHILD IS ACTUALLY AT RISK, measured rather than assumed. A child sitting on its pipe
between operations already dies by itself: the parent's death closes the write end, the read
returns end-of-file, and it leaves. The FIRST version of this module tested exactly that
child and passed with the binding removed -- it proved nothing. The child at risk is the one
INSIDE a native VISA call, which is not reading the pipe and cannot see the end-of-file
until the call returns. That is the child these tests use: one that is busy.
"""

from __future__ import annotations

import os
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


# A parent that starts a child which binds its lifetime and then stays BUSY -- never reading
# the pipe, exactly like one inside a native call. It reports the child pid and waits to die.
_BUSY_CHILD_PARENT = textwrap.dedent(
    """
    import multiprocessing, sys, time
    sys.path.insert(0, {src!r})

    def _busy(_connection):
        from cryodaq.drivers.transport.usbtmc import _bind_lifetime_to_parent
        {binding}
        # Whatever happens to the parent, this loop does not look at the pipe.
        time.sleep(600)

    if __name__ == "__main__":
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(target=_busy, args=(child_connection,), daemon=True)
        process.start()
        child_connection.close()
        print(process.pid, flush=True)
        time.sleep(600)
    """
)


def _child_survives_a_killed_parent(*, bound: bool) -> bool:
    """Kill a parent with SIGKILL and report whether its busy child outlived it."""

    program = _BUSY_CHILD_PARENT.format(
        src=_SRC,
        binding="_bind_lifetime_to_parent()" if bound else "pass",
    )
    parent = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert parent.stdout is not None
        line = parent.stdout.readline().decode().strip()
        assert line.isdigit(), f"no child pid reported; stderr={parent.stderr.read()[:400]!r}"
        child_pid = int(line)
        assert _alive(child_pid), "the child must be running before the parent is killed"

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
        try:
            os.kill(child_pid, 9)
        except OSError:
            pass
    return survived


@_LINUX_ONLY
def test_a_busy_child_outlives_a_killed_parent_without_the_binding() -> None:
    """The control. Without it the hazard is real, and this is what proves it.

    SIGKILL is the one signal a process cannot handle, and therefore the one case the
    daemonic flag can never cover. A child that is not reading its pipe does not notice.
    """

    assert _child_survives_a_killed_parent(bound=False), (
        "the control must reproduce the orphan, or the guard below proves nothing"
    )


@_LINUX_ONLY
def test_the_binding_kills_the_busy_child_with_its_parent() -> None:
    """The same child, bound. The kernel delivers what atexit never could."""

    assert not _child_survives_a_killed_parent(bound=True), (
        "the source-owning child outlived its killed parent; it could still finish a "
        "write after a replacement engine had commanded OFF"
    )


@_LINUX_ONLY
def test_the_binding_refuses_rather_than_running_unbound() -> None:
    """A source-owning child that cannot be bound must not run at all.

    Refusing costs one failed open, which the transport reports. Continuing would risk the
    orphan the whole module exists to prevent, so the failure direction is deliberate.
    """

    program = textwrap.dedent(
        f"""
        import ctypes, sys
        sys.path.insert(0, {_SRC!r})
        import cryodaq.drivers.transport.usbtmc as usbtmc

        class _Refuses:
            def prctl(self, *_args):
                return -1

        ctypes.CDLL = lambda *a, **k: _Refuses()
        usbtmc._bind_lifetime_to_parent()
        print("KEPT RUNNING", flush=True)
        """
    )
    finished = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=30)
    assert b"KEPT RUNNING" not in finished.stdout, (
        "a child that could not bind its lifetime to its parent must exit, not continue"
    )


@_LINUX_ONLY
def test_a_child_whose_parent_already_died_exits_by_itself() -> None:
    """The classic race: the parent dies between the fork and the request.

    The kernel signal was asked for against a parent that is already gone, so it will never
    arrive. Re-reading the parent identity afterwards is what catches it.
    """

    program = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {_SRC!r})
        import cryodaq.drivers.transport.usbtmc as usbtmc

        usbtmc.os.getppid = lambda: 1
        usbtmc._bind_lifetime_to_parent()
        print("KEPT RUNNING", flush=True)
        """
    )
    finished = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=30)
    assert b"KEPT RUNNING" not in finished.stdout


def test_the_binding_runs_before_any_handle_exists() -> None:
    """Order matters: a VISA session opened first would be what the orphan holds."""

    import inspect

    from cryodaq.drivers.transport import usbtmc

    source = inspect.getsource(usbtmc._visa_process_main)
    body = source.split('"""', 2)[-1]
    assert "_bind_lifetime_to_parent()" in body, "the child must bind its lifetime to its parent"
    assert body.index("_bind_lifetime_to_parent()") < body.index("_receive_document"), (
        "the binding must happen before the child reads its first request"
    )
