"""Entry point: python -m cryodaq.replay_engine

Launched by cryodaq launcher (Stage 4) via:
    python -m cryodaq.replay_engine --source <path> --speed <n> ...
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from cryodaq.core.zmq_bridge import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR
from cryodaq.logging_setup import setup_logging
from cryodaq.replay_engine.server import ReplayEngine

logger = logging.getLogger("cryodaq.replay_engine")


def main() -> None:
    setup_logging("replay_engine")
    parser = argparse.ArgumentParser(
        prog="cryodaq-replay-engine",
        description="CryoDAQ replay engine — ZMQ-compatible engine for replay mode",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Replay source: SQLite .db file, cooldown_v5 curve .json, or directory of .db files",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=10.0,
        help="Replay speed multiplier (default: 10). 0 = maximum speed.",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default="cooldown",
        help="Phase reported to analytics GUI (cooldown/measurement/heating). Default: cooldown.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop replay after the source is exhausted.",
    )
    parser.add_argument("--pub-addr", type=str, default=DEFAULT_PUB_ADDR)
    parser.add_argument("--cmd-addr", type=str, default=DEFAULT_CMD_ADDR)
    parser.add_argument("--cold-channel", type=str, default="Т12")
    parser.add_argument("--warm-channel", type=str, default="Т11")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


async def _run(args: argparse.Namespace) -> None:
    engine = ReplayEngine(
        args.source,
        speed=args.speed,
        phase=args.phase,
        loop=args.loop,
        pub_addr=args.pub_addr,
        cmd_addr=args.cmd_addr,
        cold_channel=args.cold_channel,
        warm_channel=args.warm_channel,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal(*_: object) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, ValueError):
            signal.signal(sig, lambda *_: stop_event.set())

    await engine.start()
    logger.info("Replay engine ready (source=%s speed=%.1fx)", args.source, args.speed)

    source_task = asyncio.create_task(engine.run_source(), name="replay_source")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop_signal")

    done, pending = await asyncio.wait(
        {source_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await engine.stop()

    # P2: propagate source failure so the CLI exits non-zero on errors.
    if source_task.done() and not source_task.cancelled():
        exc = source_task.exception()
        if exc is not None:
            logger.error("Replay source failed: %s", exc)
            raise exc

    logger.info("Replay engine shut down")


if __name__ == "__main__":
    main()
