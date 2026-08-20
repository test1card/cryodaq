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
    import multiprocessing, sys, time
    sys.path.insert(0, {src!r})

    def _busy(_connection):
        from cryodaq.drivers.transport.usbtmc import _bind_lifetime_to_parent
        {binding}
        # Whatever happens to the parent, this never looks at the pipe -- the shape of a
        # child inside a native call.
        {busy}

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
            binding="_bind_lifetime_to_parent()" if bound else "pass",
            busy=busy,
        ),
        encoding="utf-8",
    )
    parent = subprocess.Popen([sys.executable, "-B", str(parent_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert parent.stdout is not None
        line = parent.stdout.readline().decode().strip()
        assert line.isdigit(), f"no child pid reported; stderr={parent.stderr.read()[:600]!r}"
        child_pid = int(line)
        # The child must be alive AND have got past its own start-up, or a control that
        # reports "no orphan" is only reporting a child that never ran.
        time.sleep(1.0)
        assert _alive(child_pid), f"the child died before the parent was killed; stderr={parent.stderr.read()[:600]!r}"

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
        with contextlib.suppress(OSError):
            os.kill(child_pid, signal.SIGKILL)
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
