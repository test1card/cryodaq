"""Canonical B1 truth-recovery capture CLI."""

from __future__ import annotations

import argparse
import logging
import sys

from cryodaq.gui.zmq_client import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR, ZmqBridge
from tools._b1_diagnostics import capture_b1_truth

logger = logging.getLogger("diag_zmq_b1_capture")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture the canonical current-master B1 diagnostic sequence.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example: python -m tools.diag_zmq_b1_capture "
            "--pub-address tcp://127.0.0.1:5555 --cmd-address tcp://127.0.0.1:5556"
        ),
    )
    parser.add_argument(
        "--pub-address",
        default=DEFAULT_PUB_ADDR,
        help=f"GUI SUB address for readings (default: {DEFAULT_PUB_ADDR}).",
    )
    parser.add_argument(
        "--cmd-address",
        default=DEFAULT_CMD_ADDR,
        help=f"GUI REQ address for commands (default: {DEFAULT_CMD_ADDR}).",
    )
    parser.add_argument(
        "--sequential-count",
        type=int,
        default=5,
        help="How many sequential commands to send first.",
    )
    parser.add_argument(
        "--concurrent-count",
        type=int,
        default=10,
        help="How many concurrent commands to send next.",
    )
    parser.add_argument(
        "--soak-seconds",
        type=float,
        default=60.0,
        help="How long to run the final soak phase.",
    )
    parser.add_argument(
        "--soak-interval",
        type=float,
        default=1.0,
        help="Interval between soak commands in seconds.",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=1.0,
        help="Delay after starting the bridge before sending commands.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    print("[b1] B1 capture starting")
    logger.info(
        "B1 capture starting: pub=%s cmd=%s",
        args.pub_address,
        args.cmd_address,
    )

    bridge = ZmqBridge(pub_addr=args.pub_address, cmd_addr=args.cmd_address)
    try:
        bridge.start()
        logger.info("bridge started")
        capture_b1_truth(
            bridge,
            sequential_count=args.sequential_count,
            concurrent_count=args.concurrent_count,
            soak_seconds=args.soak_seconds,
            soak_interval_s=args.soak_interval,
            start_delay_s=args.start_delay,
            emit=print,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("B1 capture failed: %s", exc)
        return 1
    finally:
        bridge.shutdown()
        logger.info("bridge stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
