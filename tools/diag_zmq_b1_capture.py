from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryodaq.gui.zmq_client import ZmqBridge
from tools._b1_diagnostics import bridge_snapshot, direct_engine_probe
from tools._zmq_helpers import DEFAULT_CMD_ADDR


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
    sample["direct_reply"] = (
        None
        if skip_direct_probe
        else direct_engine_probe(address=address, timeout_s=direct_timeout_s)
    )
    return sample


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
