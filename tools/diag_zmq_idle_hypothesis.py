"""Test idle-death hypothesis: high-rate commands vs low-rate.

Extended diag showed REQ dies after ~4s idle (first hang at uptime=39s
but 4 sparse commands successfully before). Hypothesis: idle > N ms
kills loopback REQ peer mapping on macOS Python 3.14 + pyzmq 25.

This tool sends at 5 Hz (200ms interval) for 60 seconds. If this
works without any failures → idle death confirmed. Fix: ipc://
transport instead of tcp://loopback, OR periodic keepalive ping.

Usage::
    .venv/bin/python tools/diag_zmq_idle_hypothesis.py
"""

from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from cryodaq.gui.zmq_client import ZmqBridge  # noqa: E402


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def run_at_rate(bridge: ZmqBridge, duration_s: float, interval_s: float, label: str) -> None:
    print(f"\n[{_ts()}] ===== {label}: {1/interval_s:.1f} Hz for {duration_s:.0f}s")
    start = time.monotonic()
    end = start + duration_s
    i = 0
    fails = 0
    slow = 0
    max_elapsed = 0.0
    while time.monotonic() < end:
        i += 1
        t0 = time.monotonic()
        reply = bridge.send_command({"cmd": "safety_status"})
        elapsed = time.monotonic() - t0
        ok = bool(reply.get("ok"))
        max_elapsed = max(max_elapsed, elapsed)
        if not ok:
            fails += 1
            err = str(reply.get("error", ""))[:80]
            uptime = time.monotonic() - start
            print(
                f"[{_ts()}] {label} #{i:4d} FAIL in {elapsed*1000:7.1f}ms "
                f"uptime={uptime:5.1f}s: {err}"
            )
        elif elapsed > 0.1:
            slow += 1
            if slow <= 5:
                print(
                    f"[{_ts()}] {label} #{i:4d} slow in {elapsed*1000:7.1f}ms"
                )
        # Drain readings to avoid data_queue backpressure masking the
        # true cmd-path behaviour (extended diag didn't drain).
        _ = bridge.poll_readings()
        # Interval (accounting for command time)
        if elapsed < interval_s:
            time.sleep(interval_s - elapsed)
    print(
        f"[{_ts()}] {label} DONE: total={i} fails={fails} "
        f"slow(>100ms)={slow} max={max_elapsed*1000:.1f}ms"
    )


def main() -> None:
    print(f"[{_ts()}] Python: {sys.version.split()[0]}, platform: {sys.platform}")
    bridge = ZmqBridge()
    bridge.start()
    time.sleep(1.0)
    print(f"[{_ts()}] bridge alive = {bridge.is_alive()}")

    try:
        # Phase 1: rapid fire (5 Hz) for 60s. If this works, idle-death confirmed.
        run_at_rate(bridge, 60.0, 0.2, "RAPID_5HZ")

        # Phase 2: slow (1 cmd / 3s) for 60s. Expected to fail quickly.
        run_at_rate(bridge, 60.0, 3.0, "SPARSE_0.33HZ")

        # Phase 3: back to rapid. Does it recover?
        run_at_rate(bridge, 30.0, 0.2, "RECOVER_5HZ")
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(1)
