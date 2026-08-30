"""Entry point: python -m cryodaq.replay_engine

Launched by cryodaq launcher (Stage 4) via:
    python -m cryodaq.replay_engine --source <path> --speed <n> ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import stat
import sys
from pathlib import Path

from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_SAFE_CMD_ADDR,
    ZMQCommandIngressTerminalFailure,
)
from cryodaq.logging_setup import setup_logging
from cryodaq.replay_engine.server import ReplayEngine

logger = logging.getLogger("cryodaq.replay_engine")

_REPLAY_READY_NONCE_ENV = "CRYODAQ_REPLAY_READY_NONCE"
_REPLAY_SESSION_ID_ENV = "CRYODAQ_REPLAY_SESSION_ID"
_CHILD_READY_CHANNEL_ENV = "CRYODAQ_CHILD_READY_CHANNEL"
_REPLAY_READY_SCHEMA = "cryodaq.replay_ready.v2"
_REPLAY_READY_PREFIX = b"CRYODAQ_REPLAY_READY_V2 "
_MAX_REPLAY_READY_BYTES = 8192
_REPLAY_SETTLEMENT_RETRY_S = 0.05


async def _await_settlement_task(task: asyncio.Task[None]) -> bool:
    """Wait for exact runtime settlement before propagating cancellation."""

    cancellation_seen = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancellation_seen = True
    task.result()
    return cancellation_seen


async def _settle_replay_runtime_until_complete(engine: object) -> None:
    """Retain the replay owner and retry transient stop failures to success."""

    while True:
        try:
            await engine.stop()  # type: ignore[attr-defined]
        except BaseException as exc:  # noqa: BLE001 - exact ownership remains retained
            logger.error(
                "Replay runtime stop retained ownership; exception=%s",
                type(exc).__name__,
            )
            await asyncio.sleep(_REPLAY_SETTLEMENT_RETRY_S)
            continue
        ownership_probe = getattr(engine, "_runtime_ownership_present", None)
        if not callable(ownership_probe) or ownership_probe() is False:
            return
        logger.error("Replay runtime stop returned with retained ownership")
        await asyncio.sleep(_REPLAY_SETTLEMENT_RETRY_S)


def _consume_replay_ready_channel(encoded: object) -> int:
    """Convert one inherited pipe handle and de-inherit it immediately."""

    descriptor: int | None = None
    try:
        if type(encoded) is not str:
            raise ValueError("readiness channel descriptor is not text")
        if sys.platform == "win32":
            import msvcrt

            prefix = "handle:"
            suffix = encoded[len(prefix) :] if encoded.startswith(prefix) else ""
            if not (1 <= len(suffix) <= 20 and suffix.isascii() and suffix.isdecimal()):
                raise ValueError("invalid readiness channel handle")
            handle = int(suffix)
            if handle <= 0:
                raise ValueError("invalid readiness channel handle")
            standard_handles: set[int] = set()
            for standard_descriptor in (0, 1, 2):
                try:
                    standard_handle = msvcrt.get_osfhandle(standard_descriptor)
                except OSError:
                    continue
                if standard_handle > 0:
                    standard_handles.add(standard_handle)
            if handle in standard_handles:
                raise ValueError("unsafe readiness channel handle")
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))
            if not stat.S_ISFIFO(os.fstat(descriptor).st_mode):
                raise ValueError("readiness channel is not a pipe")
        else:
            prefix = "fd:"
            suffix = encoded[len(prefix) :] if encoded.startswith(prefix) else ""
            if not (1 <= len(suffix) <= 20 and suffix.isascii() and suffix.isdecimal()):
                raise ValueError("invalid readiness channel descriptor")
            candidate = int(suffix)
            if candidate <= 2:
                raise ValueError("unsafe readiness channel descriptor")
            if not stat.S_ISFIFO(os.fstat(candidate).st_mode):
                raise ValueError("readiness channel is not a pipe")
            descriptor = candidate
        os.set_inheritable(descriptor, False)
        return descriptor
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise RuntimeError("launcher replay readiness channel is invalid") from exc


def _consume_launcher_replay_authority() -> tuple[str | None, str | None, int | None]:
    """Consume the one-child readiness authority before descendants can spawn."""

    nonce = os.environ.pop(_REPLAY_READY_NONCE_ENV, None)
    session_id = os.environ.pop(_REPLAY_SESSION_ID_ENV, None)
    channel = os.environ.pop(_CHILD_READY_CHANNEL_ENV, None)
    if nonce is None and session_id is None and channel is None:
        return None, None, None
    if (
        type(nonce) is not str
        or re.fullmatch(r"[0-9a-f]{64}", nonce) is None
        or type(session_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
        or channel is None
    ):
        raise RuntimeError("launcher replay readiness authority is invalid")
    return nonce, session_id, _consume_replay_ready_channel(channel)


def _emit_launcher_replay_ready(
    *,
    nonce: str | None,
    session_id: str | None,
    source: Path,
    speed: float,
    pub_addr: str,
    cmd_addr: str,
    safe_cmd_addr: str,
    channel_fd: int | None,
) -> None:
    """Emit one strict receipt, then close the private one-child pipe."""

    if nonce is None and session_id is None and channel_fd is None:
        return
    if nonce is None or session_id is None or type(channel_fd) is not int or channel_fd <= 2:
        if type(channel_fd) is int and channel_fd > 2:
            os.close(channel_fd)
        raise RuntimeError("launcher replay readiness authority is incomplete")
    try:
        payload = {
            "schema": _REPLAY_READY_SCHEMA,
            "nonce": nonce,
            "session_id": session_id,
            "mode": "replay",
            "source": str(source),
            "speed": speed,
            "pid": os.getpid(),
            "pub_addr": pub_addr,
            "cmd_addr": cmd_addr,
            "safe_cmd_addr": safe_cmd_addr,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        wire = _REPLAY_READY_PREFIX + encoded + b"\n"
        if len(wire) > _MAX_REPLAY_READY_BYTES:
            raise RuntimeError("launcher replay readiness receipt exceeds its bound")
        written = 0
        while written < len(wire):
            count = os.write(channel_fd, wire[written:])
            if count <= 0:
                raise RuntimeError("launcher replay readiness pipe write did not progress")
            written += count
    finally:
        os.close(channel_fd)


def _acquire_engine_lock() -> int:
    """Acquire the shared engine lock through its stable exact object."""
    from cryodaq.instance_lock import try_acquire_lock

    fd = try_acquire_lock(".engine.lock")
    if fd is None:
        logger.error("CryoDAQ engine уже запущен. Остановите его перед запуском replay.")
        raise SystemExit(1)
    return fd


def _release_engine_lock(fd: int) -> None:
    """Release without unlinking the shared path or hiding close failure."""
    from cryodaq.instance_lock import release_lock_exact

    release_lock_exact(fd, ".engine.lock")


def _requires_launcher_fd2_isolation(
    launcher_ready_nonce: str | None,
    launcher_session_id: str | None,
    launcher_ready_channel_fd: int | None,
) -> bool:
    """True only for a launcher-owned POSIX replay child, before any descendant spawn."""

    return sys.platform != "win32" and (
        launcher_ready_nonce is not None and launcher_session_id is not None and type(launcher_ready_channel_fd) is int
    )


def main() -> None:
    launcher_ready_nonce, launcher_session_id, launcher_ready_channel_fd = _consume_launcher_replay_authority()
    if _requires_launcher_fd2_isolation(launcher_ready_nonce, launcher_session_id, launcher_ready_channel_fd):
        from cryodaq._fd2_bootstrap import isolate_launcher_stderr_fd2

        isolate_launcher_stderr_fd2()
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
    parser.add_argument("--safe-cmd-addr", type=str, default=DEFAULT_SAFE_CMD_ADDR)
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
                runner.run(
                    _run(
                        args,
                        launcher_ready_nonce=launcher_ready_nonce,
                        launcher_session_id=launcher_session_id,
                        launcher_ready_channel_fd=launcher_ready_channel_fd,
                    )
                )
        else:
            asyncio.run(
                _run(
                    args,
                    launcher_ready_nonce=launcher_ready_nonce,
                    launcher_session_id=launcher_session_id,
                    launcher_ready_channel_fd=launcher_ready_channel_fd,
                )
            )
    except KeyboardInterrupt:
        pass
    finally:
        _release_engine_lock(lock_fd)


async def _run(
    args: argparse.Namespace,
    *,
    launcher_ready_nonce: str | None = None,
    launcher_session_id: str | None = None,
    launcher_ready_channel_fd: int | None = None,
) -> None:
    channel_map: dict[str, str] | None = None
    if args.legacy_channel_era:
        from cryodaq.replay_engine.legacy_channel_maps import get_legacy_map

        channel_map = get_legacy_map(args.legacy_channel_era) or None
        if channel_map is None:
            logger.warning("Replay legacy channel era rejected; reason=unknown")

    engine = ReplayEngine(
        args.source,
        speed=args.speed,
        phase=args.phase,
        loop=args.loop,
        pub_addr=args.pub_addr,
        cmd_addr=args.cmd_addr,
        safe_cmd_addr=args.safe_cmd_addr,
        cold_channel=args.cold_channel,
        warm_channel=args.warm_channel,
        force=args.force_replay,
        channel_map=channel_map,
        launcher_ready_nonce=launcher_ready_nonce,
        launcher_session_id=launcher_session_id,
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

    source_task: asyncio.Task[None] | None = None
    stop_task: asyncio.Task[bool] | None = None
    ingress_failure_task: asyncio.Task[ZMQCommandIngressTerminalFailure] | None = None
    terminal_failure: tuple[str, str] | None = None
    ingress_terminal_failure: ZMQCommandIngressTerminalFailure | None = None
    try:
        await engine.start()
        engine.require_command_ingress_healthy()
        _emit_launcher_replay_ready(
            nonce=launcher_ready_nonce,
            session_id=launcher_session_id,
            source=args.source,
            speed=args.speed,
            pub_addr=args.pub_addr,
            cmd_addr=args.cmd_addr,
            safe_cmd_addr=args.safe_cmd_addr,
            channel_fd=launcher_ready_channel_fd,
        )
        # Receipt emission is synchronous today, so the event loop cannot
        # interleave a REP failure inside it. Keep the postcondition explicit
        # so future emission changes cannot start replay after a latched fatal.
        engine.require_command_ingress_healthy()
        logger.info("Replay engine exact readiness committed")

        source_task = asyncio.create_task(engine.run_source(), name="replay_source")
        stop_task = asyncio.create_task(stop_event.wait(), name="stop_signal")
        ingress_failure_task = asyncio.create_task(
            engine.wait_command_ingress_failure(),
            name="command_ingress_terminal",
        )
        await asyncio.wait(
            {source_task, stop_task, ingress_failure_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # The pair latch is sticky. Check it first so simultaneous operator
        # shutdown/source completion cannot hide terminal command authority loss.
        ingress_terminal_failure = engine.command_ingress_terminal_failure
        if ingress_terminal_failure is None and ingress_failure_task.done():
            if ingress_failure_task.cancelled():
                terminal_failure = ("command_ingress", "cancelled")
            else:
                ingress_terminal_failure = ingress_failure_task.result()
        for owner_name, task in (("source", source_task), ("stop_signal", stop_task)):
            if not task.done():
                continue
            if task.cancelled():
                terminal_failure = terminal_failure or (owner_name, "cancelled")
                continue
            failure = task.exception()
            if failure is not None:
                terminal_failure = terminal_failure or (owner_name, type(failure).__name__)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Replay runtime failed; exception=%s", type(exc).__name__)
        raise RuntimeError("replay runtime failed") from None
    finally:

        async def settle_runtime() -> None:
            nonlocal ingress_terminal_failure
            tasks = tuple(task for task in (source_task, stop_task, ingress_failure_task) if task is not None)
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error(
                        "Replay terminal task failed; task=%s exception=%s",
                        task.get_name(),
                        type(exc).__name__,
                    )
            ingress_terminal_failure = engine.command_ingress_terminal_failure or ingress_terminal_failure
            await _settle_replay_runtime_until_complete(engine)

        settlement_task = asyncio.create_task(settle_runtime(), name="replay_runtime_settlement")
        try:
            cancellation_seen = await _await_settlement_task(settlement_task)
        except BaseException as exc:
            logger.error(
                "Replay runtime settlement failed; exception=%s",
                type(exc).__name__,
            )
            raise RuntimeError("replay runtime ownership settlement is incomplete") from None
        if cancellation_seen:
            raise asyncio.CancelledError()

    if ingress_terminal_failure is not None:
        logger.error(
            "Replay command ingress terminated; endpoint=%s stage=%s failure=%s",
            ingress_terminal_failure.endpoint,
            ingress_terminal_failure.stage,
            ingress_terminal_failure.failure_type,
        )
        raise RuntimeError("replay command ingress terminated") from None

    if terminal_failure is not None:
        owner_name, failure_type = terminal_failure
        logger.error(
            "Replay terminal child failed; owner=%s failure=%s",
            owner_name,
            failure_type,
        )
        if owner_name == "source":
            raise RuntimeError("replay source execution failed") from None
        raise RuntimeError("replay stop-signal task failed") from None

    logger.info("Replay engine shut down")


if __name__ == "__main__":
    main()
