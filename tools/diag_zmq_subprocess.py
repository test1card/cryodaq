"""Diagnostic tool for CryoDAQ ZMQ subprocess bridge.

Spawns the SAME zmq_bridge_main() function that the GUI uses in a
multiprocessing.Process, sends a test command through the queue, and
reports whether the subprocess:

1. Started successfully (proc.is_alive after 3s)
2. Produced heartbeats (sub_drain_loop alive)
3. Returned a reply via reply_queue (cmd_forward_loop alive)
4. Emitted any warnings via data_queue (typical subprocess failure signal)

Usage::

    # Terminal 1: start engine
    CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock

    # Terminal 2: run diagnostic (in project venv)
    .venv/bin/python tools/diag_zmq_subprocess.py

Output tells you exactly where the wedge is:

- If [main] GOT REPLY → subprocess itself is fine, problem is in
  ZmqBridge wiring / launcher process
- If [main] TIMEOUT + warnings found → cmd_forward_loop threw an
  exception at startup (REQ socket create / connect failure)
- If [main] TIMEOUT + no warnings + no heartbeats → subprocess died
  silently at fork/spawn before any thread ran
- If [main] TIMEOUT + heartbeats but no reply → cmd_thread died
  after sub_thread successfully started

Runs with both spawn and fork start methods to isolate mp backend
issues (macOS Python 3.14 default is spawn; legacy code paths may
force fork).
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import sys
import time

from cryodaq.core.zmq_subprocess import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    zmq_bridge_main,
)


def _run_diagnostic(start_method: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"DIAGNOSTIC RUN — mp start_method = {start_method!r}")
    print(f"{'=' * 60}")

    try:
        ctx = mp.get_context(start_method)
    except ValueError as exc:
        print(f"[main] start_method {start_method!r} unavailable: {exc}")
        return

    data_queue: mp.Queue = ctx.Queue(maxsize=10_000)
    cmd_queue: mp.Queue = ctx.Queue(maxsize=1_000)
    reply_queue: mp.Queue = ctx.Queue(maxsize=1_000)
    shutdown_event = ctx.Event()

    proc = ctx.Process(
        target=zmq_bridge_main,
        args=(
            DEFAULT_PUB_ADDR,
            DEFAULT_CMD_ADDR,
            data_queue,
            cmd_queue,
            reply_queue,
            shutdown_event,
        ),
        daemon=True,
        name=f"zmq_bridge_{start_method}",
    )

    t_start = time.monotonic()
    proc.start()
    print(f"[main] proc.start() returned after {time.monotonic()-t_start:.3f}s")
    print(f"[main] subprocess PID = {proc.pid}")

    # Give subprocess time to spin up sub_drain_loop + cmd_forward_loop
    time.sleep(3.0)

    alive = proc.is_alive()
    print(f"[main] proc.is_alive() after 3s: {alive}")
    if not alive:
        print(f"[main] proc.exitcode: {proc.exitcode}")
        print("[main] !! SUBPROCESS DIED BEFORE SENDING ANY COMMAND")
        return

    # Drain initial queue contents, count heartbeats vs other
    heartbeats = 0
    warnings: list[dict] = []
    readings = 0
    while True:
        try:
            item = data_queue.get_nowait()
        except (queue.Empty, EOFError):
            break
        if isinstance(item, dict):
            t = item.get("__type")
            if t == "heartbeat":
                heartbeats += 1
            elif t == "warning":
                warnings.append(item)
            else:
                readings += 1
        else:
            readings += 1

    print(f"[main] initial drain — heartbeats={heartbeats} warnings={len(warnings)} readings={readings}")
    if warnings:
        for w in warnings[:5]:
            print(f"[main]   warning: {w.get('message', w)}")

    if heartbeats == 0:
        print("[main] !! NO HEARTBEATS — sub_drain_loop never ran. Subprocess core broken.")

    # Now send a test command
    print("[main] sending safety_status command...")
    cmd_queue.put({"_rid": "diag1", "cmd": "safety_status"})

    t0 = time.monotonic()
    reply = None
    try:
        reply = reply_queue.get(timeout=10.0)
    except (queue.Empty, EOFError):
        pass
    elapsed = time.monotonic() - t0

    if reply is not None:
        preview = str(reply)[:300]
        print(f"[main] GOT REPLY in {elapsed:.3f}s: {preview}")
    else:
        print(f"[main] !! TIMEOUT after {elapsed:.3f}s — no reply from cmd_forward_loop")

        # Drain again to catch warnings emitted during the failed command
        late_warnings = []
        while True:
            try:
                item = data_queue.get_nowait()
                if isinstance(item, dict) and item.get("__type") == "warning":
                    late_warnings.append(item)
            except (queue.Empty, EOFError):
                break
        if late_warnings:
            print("[main] warnings emitted during command attempt:")
            for w in late_warnings:
                print(f"[main]   {w.get('message', w)}")
        else:
            print("[main] no warnings emitted — cmd_thread likely dead before command sent")

        print(f"[main] proc.is_alive() after timeout: {proc.is_alive()}")
        if proc.is_alive():
            print("[main] subprocess still running — only cmd_thread died silently")
            print("[main] SMOKING GUN: cmd_forward_loop crashed at startup or during get()")

    # Cleanup
    shutdown_event.set()
    proc.join(timeout=5.0)
    if proc.is_alive():
        print("[main] proc did not exit, terminating")
        proc.terminate()
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.kill()


if __name__ == "__main__":
    print("CryoDAQ ZMQ subprocess bridge — diagnostic")
    print("Engine must be running at tcp://127.0.0.1:5555 / :5556")
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Default mp start method: {mp.get_start_method()}")

    # Test both. spawn first because it's the default on macOS Python 3.14.
    _run_diagnostic("spawn")
    _run_diagnostic("fork")

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
