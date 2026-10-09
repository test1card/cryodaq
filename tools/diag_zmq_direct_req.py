"""D3 H5 investigation: direct REQ to engine REP, bypassing bridge subprocess.

Distinguishes engine-REP stall (H5) from bridge-process accumulation as B1 root cause.

If B1 reproduces at ~50-80s here:  H5 CONFIRMED (engine-side).
If clean 180s:                      H5 FALSIFIED (mechanism is bridge-process specific).

Usage::

    # Terminal 1:
    CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock

    # Terminal 2 (tcp, default):
    .venv/bin/python tools/diag_zmq_direct_req.py

    # ipc variant (requires IV.7 worktree engine):
    .venv/bin/python tools/diag_zmq_direct_req.py --transport ipc

    # Custom address:
    .venv/bin/python tools/diag_zmq_direct_req.py --addr tcp://127.0.0.1:5556

Ref: docs/decisions/2026-04-27-d3-h5-experiment.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time

# Addresses match zmq_subprocess.py / zmq_bridge.py defaults
_TCP_CMD_ADDR = "tcp://127.0.0.1:5556"
# IPC address matches IV.7 worktree zmq_bridge.py experiment defaults
_IPC_CMD_ADDR = "ipc:///tmp/cryodaq-cmd.sock"

_RCVTIMEO_MS = 35_000  # match production bridge (zmq_subprocess.py:195)


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _build_req_socket(ctx, cmd_addr: str):
    import zmq

    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, _RCVTIMEO_MS)
    req.setsockopt(zmq.SNDTIMEO, _RCVTIMEO_MS)
    req.connect(cmd_addr)
    return req


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "D3 H5: Direct REQ to engine REP, bypassing bridge subprocess. "
            "Distinguishes engine-side stall (H5) from bridge-process accumulation."
        )
    )
    parser.add_argument(
        "--transport",
        choices=["tcp", "ipc"],
        default="tcp",
        help="Transport shorthand (default: tcp → tcp://127.0.0.1:5556)",
    )
    parser.add_argument(
        "--addr",
        default=None,
        help="Override cmd address directly (e.g. tcp://127.0.0.1:5556)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=180,
        help="Test duration in seconds (default: 180)",
    )
    return parser.parse_args(argv)


def run(cmd_addr: str, duration: int) -> int:
    """Run the soak test. Returns 0 on clean run, 1 if any failure occurred."""
    import zmq

    print(f"[{_ts()}] D3 H5 direct-REQ soak test — {duration}s")
    print(f"[{_ts()}] Connecting directly to {cmd_addr} (NO bridge subprocess)")
    print(f"[{_ts()}] RCVTIMEO={_RCVTIMEO_MS}ms — matches production bridge")

    ctx = zmq.Context()
    req = _build_req_socket(ctx, cmd_addr)

    results: list[tuple[int, float, bool, str]] = []
    start = time.monotonic()
    end = start + duration
    i = 0
    first_fail_at: int | None = None

    print(f"[{_ts()}] socket connected, sending 1 cmd/sec for {duration}s")

    try:
        while time.monotonic() < end:
            i += 1
            t0 = time.monotonic()
            ok = False
            err = ""
            try:
                req.send_string(json.dumps({"cmd": "safety_status"}))
                reply_raw = req.recv_string()
                reply = json.loads(reply_raw)
                ok = bool(reply.get("ok"))
                if not ok:
                    err = str(reply.get("error", ""))[:80]
            except zmq.ZMQError as exc:
                err = f"ZMQError: {exc}"
                # REQ socket enters broken state after any ZMQError.
                # Recreate so we can observe whether engine recovers post-failure.
                req.close(linger=0)
                req = _build_req_socket(ctx, cmd_addr)

            elapsed = time.monotonic() - t0
            results.append((i, elapsed, ok, err))

            if not ok or elapsed > 0.5:
                print(
                    f"[{_ts()}] #{i:3d} "
                    f"{'FAIL' if not ok else 'slow'} "
                    f"in {elapsed * 1000:7.1f}ms "
                    f"uptime={time.monotonic() - start:5.1f}s "
                    f"{err}"
                )
                if first_fail_at is None:
                    first_fail_at = i
                    print(f"[{_ts()}]     ← FIRST FAILURE (direct REQ, no bridge)")
            elif i % 5 == 0 or (first_fail_at is not None and i - first_fail_at < 10):
                print(
                    f"[{_ts()}] #{i:3d} "
                    f"ok   "
                    f"in {elapsed * 1000:7.1f}ms "
                    f"uptime={time.monotonic() - start:5.1f}s"
                )

            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

    finally:
        req.close(linger=0)
        ctx.term()

    # Summary
    total = len(results)
    fails = sum(1 for _, _, ok, _ in results if not ok)
    slow = sum(1 for _, t, ok, _ in results if ok and t > 0.5)
    print(f"\n[{_ts()}] ========= SUMMARY (D3 direct-REQ, {cmd_addr})")
    print(f"[{_ts()}] total={total} ok={total - fails} fails={fails} slow(>500ms)={slow}")

    if fails > 0:
        print(f"[{_ts()}] failure detail:")
        for idx, t, ok, err in results:
            if not ok:
                print(f"[{_ts()}]   #{idx:3d}: {t * 1000:.1f}ms  {err}")

    if first_fail_at is not None:
        post = results[first_fail_at - 1:]
        post_ok = sum(1 for _, _, ok, _ in post if ok)
        print(f"[{_ts()}] after first failure: {post_ok}/{len(post)} ok")
        print(f"[{_ts()}] VERDICT: B1 REPRODUCED on direct REQ at cmd #{first_fail_at}")
    else:
        print(f"[{_ts()}] VERDICT: CLEAN {duration}s — no failure on direct REQ")

    return 1 if fails > 0 else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.addr:
        cmd_addr = args.addr
    elif args.transport == "ipc":
        cmd_addr = _IPC_CMD_ADDR
    else:
        cmd_addr = _TCP_CMD_ADDR
    return run(cmd_addr=cmd_addr, duration=args.duration)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\ninterrupted by user")
        sys.exit(1)
