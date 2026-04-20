"""Extended ZmqBridge diagnostic: continues past first failure.

We found that around command #28 (~30s uptime), one command hangs
for exactly 35s (RCVTIMEO). This tool continues monitoring past that
point to answer:

1. After first hang, do subsequent commands work or stay broken?
2. Is the hang periodic (every ~30 commands)?
3. Does the subprocess recover on its own, or does it need restart?

Usage::

    # Terminal 1:
    CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock

    # Terminal 2:
    .venv/bin/python tools/diag_zmq_bridge_extended.py
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


def main() -> None:
    print(f"[{_ts()}] Extended bridge soak test — 180 seconds")
    print(f"[{_ts()}] Engine must be running at tcp://127.0.0.1:5555 / :5556")

    bridge = ZmqBridge()
    bridge.start()
    time.sleep(1.0)
    print(f"[{_ts()}] bridge started, subprocess alive = {bridge.is_alive()}")

    results: list[tuple[int, float, bool, str]] = []
    start = time.monotonic()
    end = start + 180.0
    i = 0

    print(f"[{_ts()}] sending 1 command/sec for 180s, all outputs logged")
    print(f"[{_ts()}] waiting for first failure...")

    first_fail_at: int | None = None

    while time.monotonic() < end:
        i += 1
        t0 = time.monotonic()
        reply = bridge.send_command({"cmd": "safety_status"})
        elapsed = time.monotonic() - t0
        ok = bool(reply.get("ok"))
        err = str(reply.get("error", ""))[:80] if not ok else ""
        results.append((i, elapsed, ok, err))

        # Verbose output for every command once we see a failure
        if not ok or elapsed > 0.5:
            print(
                f"[{_ts()}] #{i:3d} "
                f"{'FAIL' if not ok else 'slow'} "
                f"in {elapsed*1000:7.1f}ms "
                f"uptime={time.monotonic()-start:5.1f}s "
                f"{err}"
            )
            if first_fail_at is None:
                first_fail_at = i
                print(f"[{_ts()}]     ← FIRST FAILURE. Continuing to see if it recovers...")
        elif i % 5 == 0 or (first_fail_at and i - first_fail_at < 10):
            # after first fail: log every command. before: every 5th.
            print(
                f"[{_ts()}] #{i:3d} "
                f"ok   "
                f"in {elapsed*1000:7.1f}ms "
                f"uptime={time.monotonic()-start:5.1f}s"
            )

        # Target 1 cmd/sec. If last command took > 1s (e.g. 35s timeout),
        # don't sleep — otherwise we'd spread commands out.
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    # Summary
    print(f"\n[{_ts()}] ========= SUMMARY")
    total = len(results)
    fails = sum(1 for _, _, ok, _ in results if not ok)
    slow = sum(1 for _, t, ok, _ in results if ok and t > 0.5)
    print(f"[{_ts()}] total={total} ok={total-fails} fails={fails} slow(>500ms)={slow}")

    if fails > 0:
        print(f"[{_ts()}] failure pattern (cmd_index: elapsed_ms):")
        for idx, t, ok, err in results:
            if not ok:
                print(f"[{_ts()}]   #{idx:3d}: {t*1000:.1f}ms  {err}")

    # Post-failure commands
    if first_fail_at:
        post = results[first_fail_at:]  # all after first fail (inclusive)
        post_fails = sum(1 for _, _, ok, _ in post if not ok)
        post_ok = len(post) - post_fails
        print(f"[{_ts()}] after first failure: {post_ok}/{len(post)} ok")

    bridge.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\ninterrupted by user")
        sys.exit(1)
