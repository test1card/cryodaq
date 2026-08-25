"""Real-production-bootstrap engine simulant for the fd-2 shutdown blocker harness.

Executed as a real ``python <this file>`` subprocess with ``stderr=PIPE``. It
runs the exact production chain a launcher-owned POSIX engine child runs:

1. ``cryodaq.engine._consume_engine_launch_authority()`` (real envelope
   consumption from the environment, including the real readiness pipe fd);
2. ``cryodaq.engine._requires_launcher_fd2_isolation(...)`` (the real
   production gate) and, when authorized and requested, the real production
   ``cryodaq._fd2_bootstrap.isolate_launcher_stderr_fd2()``;
3. ``cryodaq.logging_setup.setup_logging("engine")`` (real logging init);
4. one diagnostic emitted through the production stderr path;
5. the REAL ``USBTMCTransport`` spawn path (``multiprocessing`` spawn context,
   real worker process) against the fake pyvisa stub backend, plus a real
   ``multiprocessing.Lock()`` so the REAL ResourceTracker descendant exists.

It never fakes multiprocessing, ResourceTracker, descriptors, pipes, or the
launcher pump. Test-only switches arrive via environment variables.
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import sys
import time
from multiprocessing import util as multiprocessing_util

INSTALL_ISOLATION_ENV = "CRYODAQ_FD2_TEST_INSTALL_ISOLATION"
EXPOSE_PRIVATE_FILENO_ENV = "CRYODAQ_FD2_TEST_EXPOSE_PRIVATE_FILENO"
EXIT_AFTER_MARKER_ENV = "CRYODAQ_FD2_TEST_EXIT_AFTER_MARKER"
PYVISA_STUB_DIRNAME = "_fd2_stubs"
PROBE_MARKER = "CRYODAQ-FD2-PROBE-DIAGNOSTIC"
FAKE_RESOURCE = "FAKE0::FD2TEST::SIMULATED::INSTR"
SLEEP_AFTER_MARKER_S = 120


def _stderr_fileno_probe() -> int | None:
    try:
        fileno = sys.stderr.fileno()
    except Exception:
        return None
    return int(fileno) if type(fileno) is int else None


def _tracker_pid() -> int | None:
    from multiprocessing import resource_tracker

    singleton = getattr(resource_tracker, "_resource_tracker", None)
    candidate = getattr(singleton, "_pid", None)
    if type(candidate) is int and candidate > 0:
        return candidate
    legacy = getattr(resource_tracker, "_pid", None)
    if type(legacy) is int and legacy > 0:
        return legacy
    return None


def main() -> None:
    from cryodaq.engine import _consume_engine_launch_authority, _requires_launcher_fd2_isolation

    instance_id, capability, nonce, channel_fd = _consume_engine_launch_authority()
    isolation_applied = False
    holder_pid: int | None = None
    if _requires_launcher_fd2_isolation(instance_id, capability, nonce, channel_fd):
        if os.environ.get(INSTALL_ISOLATION_ENV) == "1":
            from cryodaq._fd2_bootstrap import isolate_launcher_stderr_fd2

            receipt = isolate_launcher_stderr_fd2()
            isolation_applied = True
            if os.environ.get(EXPOSE_PRIVATE_FILENO_ENV) == "1":
                sys.stderr.fileno = lambda: receipt.private_fd
                holder_pid = int(
                    multiprocessing_util.spawnv_passfds(
                        sys.executable,
                        [sys.executable, "-c", f"import time; time.sleep({SLEEP_AFTER_MARKER_S})"],
                        [receipt.private_fd],
                    )
                )
    from cryodaq.logging_setup import setup_logging

    setup_logging("engine")
    logging.getLogger("cryodaq.engine").error(PROBE_MARKER)
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    try:
        sys.stderr.flush()
    except Exception:
        pass

    worker_pid: int | None = None
    tracker: int | None = None
    if os.environ.get(EXIT_AFTER_MARKER_ENV) != "1":
        stub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), PYVISA_STUB_DIRNAME)
        sys.path.insert(0, stub_dir)
        context = multiprocessing.get_context("spawn")
        context.Lock()
        from cryodaq.drivers.transport.usbtmc import USBTMCTransport

        transport = USBTMCTransport(mock=False)
        asyncio.run(transport.open(FAKE_RESOURCE))
        owner = transport._process_owner
        assert owner is not None
        worker_pid = int(owner.process.pid)
        tracker = _tracker_pid()

    marker = {
        "pid": os.getpid(),
        "isolation_applied": isolation_applied,
        "stderr_fileno": _stderr_fileno_probe(),
        "worker_pid": worker_pid,
        "tracker_pid": tracker,
        "holder_pid": holder_pid,
    }
    sys.stdout.write(json.dumps(marker, sort_keys=True) + "\n")
    sys.stdout.flush()
    if os.environ.get(EXIT_AFTER_MARKER_ENV) == "1":
        return
    time.sleep(SLEEP_AFTER_MARKER_S)


if __name__ == "__main__":
    main()
