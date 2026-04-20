"""Diagnostic tool for CryoDAQ ZmqBridge (GUI-side wrapper).

Phase 2: exercises the full ZmqBridge class exactly the way GUI uses
it (minus Qt), to isolate whether the bug lives in:
- the subprocess (already cleared by tools/diag_zmq_subprocess.py)
- the ZmqBridge wrapper (_consume_replies thread, _pending dict,
  Future.result() wait path)

This script imports the REAL ZmqBridge from cryodaq.gui.zmq_client,
starts it, issues 5 sequential safety_status commands, 5 concurrent
ones via threads, then monitors over 30 seconds whether commands
keep working.

Usage::

    # Terminal 1:
    CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock

    # Terminal 2:
    .venv/bin/python tools/diag_zmq_bridge.py

If all 30s of commands succeed under 100ms — ZmqBridge is fine;
bug is in Qt wiring / MainWindow dispatch. If commands start timing
out at some point (mirror of Vladimir's 52s-after-startup observation)
— bug is reproducible at ZmqBridge level, probably _consume_replies
thread dying silently.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

# Configure logging BEFORE importing cryodaq so we see internal warnings.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Suppress very noisy third-party loggers
logging.getLogger("asyncio").setLevel(logging.WARNING)

from cryodaq.gui.zmq_client import ZmqBridge  # noqa: E402


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _run_sequential(bridge: ZmqBridge, n: int) -> list[tuple[float, dict]]:
    results = []
    for i in range(n):
        t0 = time.monotonic()
        reply = bridge.send_command({"cmd": "safety_status"})
        elapsed = time.monotonic() - t0
        results.append((elapsed, reply))
        print(
            f"[{_ts()}] seq #{i}: {elapsed*1000:.1f}ms "
            f"ok={reply.get('ok')} "
            f"state={reply.get('state') or reply.get('error', '')[:60]}"
        )
    return results


def _run_concurrent(bridge: ZmqBridge, n: int) -> list[tuple[float, dict]]:
    results: list[tuple[float, dict]] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        t0 = time.monotonic()
        reply = bridge.send_command({"cmd": "safety_status"})
        elapsed = time.monotonic() - t0
        with lock:
            results.append((elapsed, reply))
            print(
                f"[{_ts()}] par #{idx}: {elapsed*1000:.1f}ms "
                f"ok={reply.get('ok')} "
                f"state={reply.get('state') or reply.get('error', '')[:60]}"
            )

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True, name=f"par-{i}")
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=40.0)
    return results


def _monitor_over_time(bridge: ZmqBridge, duration_s: float, interval_s: float) -> None:
    print(f"\n[{_ts()}] ========= monitoring {duration_s:.0f}s @ {interval_s:.1f}s interval")
    end = time.monotonic() + duration_s
    count = 0
    fails = 0
    slow = 0  # replies > 500ms
    while time.monotonic() < end:
        t0 = time.monotonic()
        reply = bridge.send_command({"cmd": "safety_status"})
        elapsed = time.monotonic() - t0
        count += 1
        ok = reply.get("ok", False)
        if not ok:
            fails += 1
            err = str(reply.get("error", ""))[:120]
            print(f"[{_ts()}] #{count:3d} FAIL in {elapsed*1000:6.1f}ms: {err}")
        elif elapsed > 0.5:
            slow += 1
            print(f"[{_ts()}] #{count:3d} slow  in {elapsed*1000:6.1f}ms")
        elif count % 10 == 0:
            print(f"[{_ts()}] #{count:3d} ok    in {elapsed*1000:6.1f}ms")
        time.sleep(max(0.0, interval_s - elapsed))
    print(
        f"[{_ts()}] monitoring done: total={count} fails={fails} "
        f"slow(>500ms)={slow}"
    )


def main() -> None:
    print(f"[{_ts()}] Python: {sys.version.split()[0]}, platform: {sys.platform}")
    print(f"[{_ts()}] Engine must be running at tcp://127.0.0.1:5555 / :5556")

    bridge = ZmqBridge()
    print(f"[{_ts()}] Starting ZmqBridge...")
    bridge.start()
    # Give subprocess time for REQ to connect to engine REP.
    # sub_drain_loop sends first heartbeat at T+5s; commands work earlier.
    time.sleep(1.0)
    print(f"[{_ts()}] ZmqBridge started, subprocess alive = {bridge.is_alive()}")

    try:
        print(f"\n[{_ts()}] ========= Phase 1: 5 sequential commands")
        seq = _run_sequential(bridge, 5)
        seq_fails = sum(1 for _, r in seq if not r.get("ok"))
        print(f"[{_ts()}] sequential: {5-seq_fails}/5 ok")

        print(f"\n[{_ts()}] ========= Phase 2: 10 concurrent commands")
        par = _run_concurrent(bridge, 10)
        par_fails = sum(1 for _, r in par if not r.get("ok"))
        print(f"[{_ts()}] concurrent: {10-par_fails}/10 ok")

        # Vladimir saw first timeout 52s after ZMQ bridge startup.
        # Monitor for 60s at 1s interval to cover and pass that window.
        print(f"\n[{_ts()}] ========= Phase 3: 60-second soak test")
        _monitor_over_time(bridge, 60.0, 1.0)

    finally:
        print(f"\n[{_ts()}] Shutting down ZmqBridge...")
        bridge.shutdown()
        print(f"[{_ts()}] Done.")


if __name__ == "__main__":
    main()
