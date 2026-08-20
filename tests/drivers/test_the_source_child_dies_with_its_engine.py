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

These tests kill a real parent with SIGKILL -- the one signal a process cannot handle, and
therefore the one case ``atexit`` can never cover -- and require the child to be gone.
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

# A parent that starts the REAL child entry point the transport uses, reports its pid, and
# then waits to be killed. The child never opens VISA: it blocks reading its pipe, which is
# exactly where a real one sits between operations.
_PARENT = textwrap.dedent(
    """
    import multiprocessing, sys, time
    sys.path.insert(0, {src!r})
    from cryodaq.drivers.transport.usbtmc import _visa_process_main

    if __name__ == "__main__":
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(
            target=_visa_process_main, args=(child_connection,), daemon=True, name="probe-child"
        )
        process.start()
        child_connection.close()
        print(process.pid, flush=True)
        time.sleep(600)
    """
)


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


@_LINUX_ONLY
def test_killing_the_engine_kills_the_child_that_owns_the_source() -> None:
    """SIGKILL is the case daemon=True cannot cover, and the one a crash looks like."""

    parent = subprocess.Popen(
        [sys.executable, "-c", _PARENT.format(src=str(_REPO_ROOT / "src"))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert parent.stdout is not None
        line = parent.stdout.readline().decode().strip()
        assert line.isdigit(), f"the parent did not report a child pid; stderr={parent.stderr.read()[:400]!r}"
        child_pid = int(line)
        assert _alive(child_pid), "the child must be running before the parent is killed"

        parent.kill()
        parent.wait(timeout=10)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and _alive(child_pid):
            time.sleep(0.05)
        assert not _alive(child_pid), (
            f"the source-owning child {child_pid} outlived its killed parent; "
            "it could still finish a write after a replacement engine commanded OFF"
        )
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=10)


@_LINUX_ONLY
def test_the_binding_refuses_rather_than_running_unbound() -> None:
    """A source-owning child that cannot be bound must not run at all.

    Refusing costs one failed open, which the transport reports. Continuing would risk the
    orphan the whole module exists to prevent, so the failure direction is deliberate.
    """

    program = textwrap.dedent(
        f"""
        import ctypes, sys
        sys.path.insert(0, {str(_REPO_ROOT / "src")!r})
        import cryodaq.drivers.transport.usbtmc as usbtmc

        class _Refuses:
            def prctl(self, *_args):
                return -1

        original = ctypes.CDLL
        ctypes.CDLL = lambda *a, **k: _Refuses()
        try:
            usbtmc._bind_lifetime_to_parent()
        finally:
            ctypes.CDLL = original
        print("KEPT RUNNING", flush=True)
        """
    )
    finished = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=30)
    assert b"KEPT RUNNING" not in finished.stdout, (
        "a child that could not bind its lifetime to its parent must exit, not continue"
    )
    assert finished.returncode == 0, finished.stderr[:400]


@_LINUX_ONLY
def test_a_child_whose_parent_already_died_exits_by_itself() -> None:
    """The classic race: the parent dies between the fork and the request.

    The kernel signal was asked for against a parent that is already gone, so it will never
    arrive. Re-reading the parent identity afterwards is what catches it.
    """

    program = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(_REPO_ROOT / "src")!r})
        import cryodaq.drivers.transport.usbtmc as usbtmc

        usbtmc.os.getppid = lambda: 1
        usbtmc._bind_lifetime_to_parent()
        print("KEPT RUNNING", flush=True)
        """
    )
    finished = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=30)
    assert b"KEPT RUNNING" not in finished.stdout
    assert finished.returncode == 0, finished.stderr[:400]


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
