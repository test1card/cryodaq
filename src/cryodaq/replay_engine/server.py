"""Replay engine server — ZMQ-compatible replacement for cryodaq.engine in replay mode.

Binds PUB on 5555 (same as real engine) and REP on 5556.
The GUI's ZMQ bridge subprocess connects to these sockets unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from pathlib import Path
from typing import Any

from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    ZMQCommandServer,
    ZMQPublisher,
)
from cryodaq.drivers.base import Reading
from cryodaq.replay_engine.sources import resolve_source

logger = logging.getLogger("cryodaq.replay_engine")

_WATCHDOG_INTERVAL_S = 30.0


def _check_port_available(addr: str, *, force: bool) -> None:
    """Refuse to start if a ZMQ TCP port is already bound (spec Q1).

    Without --force-replay, raises RuntimeError if another process holds the
    port.  This prevents the replay engine from silently stealing ports from
    a running real engine after it frees them via _bind_with_retry retries.
    Wildcard bind addresses (tcp://*:N, tcp://0.0.0.0:N) are normalized to
    127.0.0.1 for the connectivity check.
    """
    if force:
        return
    try:
        _, hostport = addr.rsplit("//", 1)
        host, port_str = hostport.rsplit(":", 1)
        port = int(port_str)
        # Normalize wildcard bind addresses → loopback for connectivity check.
        check_host = "127.0.0.1" if host in ("*", "", "0.0.0.0") else host
    except (ValueError, AttributeError):
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            in_use = sock.connect_ex((check_host, port)) == 0
    except OSError:
        return  # Resolution or network error — skip check, don't block startup
    if in_use:
        raise RuntimeError(
            f"[spec Q1] Port {port} ({addr}) is already in use — "
            f"another engine is likely running. "
            f"Stop the real engine first, or pass --force-replay to override."
        )


# Commands that mutate hardware state — always rejected in replay mode.
_READONLY_PREFIXES: tuple[str, ...] = (
    "set_target",
    "keithley_",
    "experiment.",
    "experiment_",
    "source_on",
    "source_off",
    "emergency_off",
    "safety_",
    "calibration_",
    "shift_",
    "operator_log_add",
)


class ReplayEngine:
    """Minimal engine replacement: PUB readings, REP commands (read-only).

    Usage::

        engine = ReplayEngine(Path("data.db"), speed=10.0)
        await engine.start()
        await engine.run_source()   # blocks until source exhausted or stop()
        await engine.stop()
    """

    def __init__(
        self,
        source_path: Path,
        *,
        speed: float = 10.0,
        phase: str = "cooldown",
        loop: bool = False,
        pub_addr: str = DEFAULT_PUB_ADDR,
        cmd_addr: str = DEFAULT_CMD_ADDR,
        cold_channel: str = "Т12",
        warm_channel: str = "Т11",
        force: bool = False,
    ) -> None:
        self._source_path = source_path
        self._speed = speed
        self._phase = phase
        self._loop = loop
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._cold_channel = cold_channel
        self._warm_channel = warm_channel
        self._force = force

        self._pub: ZMQPublisher | None = None
        self._cmd: ZMQCommandServer | None = None
        self._pub_queue: asyncio.Queue[Reading] | None = None
        self._source = None
        self._session_start: float = 0.0
        self._readings_published: int = 0
        self._watchdog_task: asyncio.Task | None = None

    async def start(self) -> None:
        # Spec Q1: refuse if ports are already bound (another engine running).
        _check_port_available(self._pub_addr, force=self._force)
        _check_port_available(self._cmd_addr, force=self._force)

        self._session_start = time.time()

        self._source = resolve_source(
            self._source_path,
            speed=self._speed,
            loop=self._loop,
            cold_channel=self._cold_channel,
            warm_channel=self._warm_channel,
        )

        self._pub_queue = asyncio.Queue(maxsize=10_000)
        self._pub = ZMQPublisher(self._pub_addr)
        await self._pub.start(self._pub_queue)
        logger.info("ZMQPublisher bound: %s", self._pub_addr)

        self._cmd = ZMQCommandServer(self._cmd_addr, handler=self._handle_command)
        await self._cmd.start()
        logger.info("ZMQCommandServer bound: %s", self._cmd_addr)

        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="replay_watchdog"
        )

    async def run_source(self) -> None:
        """Feed readings from the source into the PUB queue.  Blocks until done."""
        if self._source is None or self._pub_queue is None:
            raise RuntimeError("ReplayEngine.start() must be called before run_source()")
        logger.info("Replay source started: %s", self._source_path)
        await self._source.run(self._publish_reading)
        logger.info(
            "Replay source finished: %d readings published",
            self._readings_published,
        )

    async def stop(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        if self._source is not None:
            self._source.stop()
        if self._cmd is not None:
            await self._cmd.stop()
        if self._pub is not None:
            await self._pub.stop()
        logger.info("ReplayEngine stopped")

    async def _watchdog_loop(self) -> None:
        """Periodic HEARTBEAT log matching engine.py _watchdog cadence (30 s)."""
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_INTERVAL_S)
                uptime_s = time.time() - self._session_start
                hours, remainder = divmod(int(uptime_s), 3600)
                minutes, secs = divmod(remainder, 60)
                logger.info(
                    "HEARTBEAT | uptime=%02d:%02d:%02d | "
                    "readings_published=%d | source=%s | speed=%.1fx",
                    hours,
                    minutes,
                    secs,
                    self._readings_published,
                    self._source_path.name if self._source_path else "?",
                    self._speed,
                )
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish_reading(self, reading: Reading) -> None:
        assert self._pub_queue is not None
        self._readings_published += 1
        await self._pub_queue.put(reading)

    async def _handle_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")

        if action == "safety_status":
            return {"ok": True, "state": "replay", "alarms": []}

        if action == "current_phase":
            return {
                "ok": True,
                "phase": self._phase,
                "phase_started_at": self._session_start,
            }

        if action == "/status":
            return {
                "ok": True,
                "mode": "replay",
                "replay_source": str(self._source_path),
                "replay_speed": self._speed,
                "active_experiment": None,
                "temperature_targets": {},
                "safety_state": "replay",
                "alarms": [],
            }

        if action == "experiment_status":
            return {
                "ok": True,
                "app_mode": "debug",
                "active_experiment": None,
                "current_phase": self._phase,
                "phase_started_at": self._session_start,
                "phases": [],
                "run_records": [],
                "templates": [],
            }

        if action == "cooldown_history_get":
            return {"ok": False, "reason": "predictor_unavailable_in_replay"}

        if any(action.startswith(p) for p in _READONLY_PREFIXES):
            return {"ok": False, "reason": "REPLAY_MODE_READONLY"}

        # Unknown commands — reject as readonly rather than error
        return {"ok": False, "reason": "REPLAY_MODE_READONLY"}
