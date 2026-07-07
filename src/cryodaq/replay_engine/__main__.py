"""Entry point: python -m cryodaq.replay_engine

Launched by cryodaq launcher (Stage 4) via:
    python -m cryodaq.replay_engine --source <path> --speed <n> ...
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from cryodaq.core.zmq_bridge import DEFAULT_CMD_ADDR, DEFAULT_PUB_ADDR
from cryodaq.logging_setup import setup_logging
from cryodaq.replay_engine.server import ReplayEngine

logger = logging.getLogger("cryodaq.replay_engine")


def _acquire_engine_lock() -> int:
    """Acquire .engine.lock exclusive flock — same contract as cryodaq.engine."""
    from cryodaq.paths import get_data_dir

    lock_path = get_data_dir() / ".engine.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        logger.error(
            "CryoDAQ engine уже запущен (%s). Остановите его перед запуском replay.",
            lock_path,
        )
        raise SystemExit(1)
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def _release_engine_lock(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        from cryodaq.paths import get_data_dir

        (get_data_dir() / ".engine.lock").unlink(missing_ok=True)
    except OSError:
        pass


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
    parser.add_argument(
        "--force-replay",
        action="store_true",
        help="Skip port-in-use check (spec Q1). Use only when real engine is stopped.",
    )
    parser.add_argument(
        "--legacy-channel-era",
        type=str,
        default=None,
        metavar="ERA",
        help="Apply a legacy channel-rename map for the given recording era "
        "(e.g. 'pre-2025-02'). Affects SQLite/Directory replay only.",
    )
    args = parser.parse_args()

    lock_fd = _acquire_engine_lock()
    try:
        if sys.platform == "win32":
            # pyzmq requires a SelectorEventLoop on Windows (the default
            # Proactor loop lacks the socket support pyzmq needs). Force it
            # via Runner(loop_factory=...) rather than the deprecated
            # WindowsSelectorEventLoopPolicy (the policy system is deprecated
            # in Python 3.14+ and warns on import). Same invariant as
            # cryodaq.engine.main() — the replay server opens ZMQ sockets too.
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                runner.run(_run(args))
        else:
            asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    finally:
        _release_engine_lock(lock_fd)


async def _run(args: argparse.Namespace) -> None:
    channel_map: dict[str, str] | None = None
    if args.legacy_channel_era:
        from cryodaq.replay_engine.legacy_channel_maps import get_legacy_map

        channel_map = get_legacy_map(args.legacy_channel_era) or None
        if channel_map is None:
            logger.warning(
                "Unknown --legacy-channel-era %r — no channel rename applied.",
                args.legacy_channel_era,
            )

    engine = ReplayEngine(
        args.source,
        speed=args.speed,
        phase=args.phase,
        loop=args.loop,
        pub_addr=args.pub_addr,
        cmd_addr=args.cmd_addr,
        cold_channel=args.cold_channel,
        warm_channel=args.warm_channel,
        force=args.force_replay,
        channel_map=channel_map,
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
