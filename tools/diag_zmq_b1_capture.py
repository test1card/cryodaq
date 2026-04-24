from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryodaq.gui.zmq_client import ZmqBridge
from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
from tools._zmq_helpers import DEFAULT_CMD_ADDR

log = logging.getLogger(__name__)

# Startup probe tuning. Each attempt sends one `safety_status` command
# through the bridge; any OK reply passes. Total wall-clock bound is
# dominated by the bridge command timeout on each attempt, not by the
# inter-attempt sleeps.
_STARTUP_PROBE_ATTEMPTS = 5
_STARTUP_PROBE_BACKOFF_S = 0.2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical B1 capture against current master. Records bridge-side "
            "and direct-engine command health into JSONL."
        )
    )
    parser.add_argument("--output", type=Path, required=True, help="JSONL artifact path.")
    parser.add_argument("--duration", type=float, default=180.0, help="Capture length in seconds.")
    parser.add_argument("--interval", type=float, default=1.0, help="Sample interval in seconds.")
    parser.add_argument("--address", default=DEFAULT_CMD_ADDR, help="Direct engine REQ address.")
    parser.add_argument(
        "--direct-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for the direct engine probe.",
    )
    parser.add_argument(
        "--skip-direct-probe",
        action="store_true",
        help="Only record bridge-side command health.",
    )
    return parser.parse_args(argv)


def _sample_once(
    bridge: ZmqBridge,
    *,
    address: str,
    direct_timeout_s: float,
    skip_direct_probe: bool,
) -> dict:
    bridge.poll_readings()
    sample = bridge_snapshot(bridge)
    sample["ts_utc"] = datetime.now(UTC).isoformat()
    sample["bridge_reply"] = bridge.send_command({"cmd": "safety_status"})
    if skip_direct_probe:
        sample["direct_reply"] = None
    else:
        try:
            sample["direct_reply"] = direct_engine_probe(
                address=address,
                timeout_s=direct_timeout_s,
            )
        except TimeoutError as exc:
            sample["direct_reply"] = {
                "ok": False,
                "error": str(exc),
                "exception_type": type(exc).__name__,
            }
    return sample


def _validate_bridge_startup(
    bridge: ZmqBridge,
    *,
    attempts: int = _STARTUP_PROBE_ATTEMPTS,
    backoff_s: float = _STARTUP_PROBE_BACKOFF_S,
    sleep_fn=time.sleep,
) -> None:
    """Verify bridge subprocess is alive and engine REP is answering.

    R1 repair for the b2b4fb5 startup race: instead of a single-shot
    ``safety_status`` probe (which aborted the capture at cmd #0 when
    the engine's ipc:// REP socket had not finished binding), retry
    the probe up to ``attempts`` times with ``backoff_s`` between
    attempts. Any OK reply passes. See
    ``docs/decisions/2026-04-24-b2b4fb5-investigation.md`` for the
    empirical background.

    Subprocess-spawn failure is still a single-shot check — no point
    retrying a dead subprocess.
    """
    if not bridge.is_alive():
        raise RuntimeError("ZMQ bridge subprocess failed to start")

    last_reply: dict | None = None
    for attempt in range(attempts):
        reply = bridge.send_command({"cmd": "safety_status"})
        if reply and reply.get("ok") is True:
            return
        last_reply = reply
        if attempt < attempts - 1:
            log.debug(
                "bridge startup probe attempt %d/%d non-OK, retrying in %.2fs: %r",
                attempt + 1,
                attempts,
                backoff_s,
                reply,
            )
            sleep_fn(backoff_s)

    raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")


def run_capture(
    bridge: ZmqBridge,
    *,
    duration_s: float,
    interval_s: float,
    output_path: Path,
    address: str,
    direct_timeout_s: float,
    skip_direct_probe: bool,
    now_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = now_fn() + duration_s
    count = 0

    with output_path.open("w", encoding="utf-8") as fh:
        while True:
            if now_fn() >= deadline:
                break
            sample = _sample_once(
                bridge,
                address=address,
                direct_timeout_s=direct_timeout_s,
                skip_direct_probe=skip_direct_probe,
            )
            count += 1
            sample["seq"] = count
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
            fh.flush()
            if now_fn() >= deadline:
                break
            sleep_fn(interval_s)

    return count


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bridge = ZmqBridge()
    bridge.start()
    time.sleep(1.0)
    try:
        try:
            _validate_bridge_startup(bridge)
        except RuntimeError as exc:
            print(f"B1 capture aborted: {exc}", file=sys.stderr)
            return 1
        samples = run_capture(
            bridge,
            duration_s=args.duration,
            interval_s=args.interval,
            output_path=args.output,
            address=args.address,
            direct_timeout_s=args.direct_timeout,
            skip_direct_probe=args.skip_direct_probe,
        )
    finally:
        bridge.shutdown()
    print(f"Wrote {samples} samples to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
