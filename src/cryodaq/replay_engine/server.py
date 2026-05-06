"""Replay engine server — ZMQ-compatible replacement for cryodaq.engine in replay mode.

Binds PUB on 5555 (same as real engine) and REP on 5556.
The GUI's ZMQ bridge subprocess connects to these sockets unchanged.

[D3-REPLAY] instrumentation is present in this commit for heartbeat parity
verification.  Remove all lines tagged [D3-REPLAY] in the revert commit.
"""

from __future__ import annotations

import asyncio
import logging
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
    ) -> None:
        self._source_path = source_path
        self._speed = speed
        self._phase = phase
        self._loop = loop
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._cold_channel = cold_channel
        self._warm_channel = warm_channel

        self._pub: ZMQPublisher | None = None
        self._cmd: ZMQCommandServer | None = None
        self._pub_queue: asyncio.Queue[Reading] | None = None
        self._source = None
        self._session_start: float = 0.0
        self._readings_published: int = 0  # [D3-REPLAY]

    async def start(self) -> None:
        self._session_start = time.time()
        logger.info(  # [D3-REPLAY]
            "[D3-REPLAY] ReplayEngine.start: source=%s speed=%.1fx phase=%s loop=%s",
            self._source_path,
            self._speed,
            self._phase,
            self._loop,
        )

        self._source = resolve_source(
            self._source_path,
            speed=self._speed,
            loop=self._loop,
            cold_channel=self._cold_channel,
            warm_channel=self._warm_channel,
        )
        logger.info("[D3-REPLAY] source type: %s", type(self._source).__name__)  # [D3-REPLAY]

        self._pub_queue = asyncio.Queue(maxsize=10_000)
        self._pub = ZMQPublisher(self._pub_addr)
        await self._pub.start(self._pub_queue)
        logger.info("[D3-REPLAY] ZMQPublisher bound: %s", self._pub_addr)  # [D3-REPLAY]

        self._cmd = ZMQCommandServer(self._cmd_addr, handler=self._handle_command)
        await self._cmd.start()
        logger.info("[D3-REPLAY] ZMQCommandServer bound: %s", self._cmd_addr)  # [D3-REPLAY]

    async def run_source(self) -> None:
        """Feed readings from the source into the PUB queue.  Blocks until done."""
        if self._source is None or self._pub_queue is None:
            raise RuntimeError("ReplayEngine.start() must be called before run_source()")
        logger.info("[D3-REPLAY] source replay started")  # [D3-REPLAY]
        await self._source.run(self._publish_reading)
        logger.info(  # [D3-REPLAY]
            "[D3-REPLAY] source replay finished: %d readings published",
            self._readings_published,
        )

    async def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
        if self._cmd is not None:
            await self._cmd.stop()
        if self._pub is not None:
            await self._pub.stop()
        logger.info("[D3-REPLAY] ReplayEngine stopped")  # [D3-REPLAY]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish_reading(self, reading: Reading) -> None:
        assert self._pub_queue is not None
        self._readings_published += 1
        if self._readings_published % 100 == 1:  # [D3-REPLAY] — log every 100th
            logger.debug(
                "[D3-REPLAY] PUB #%d ch=%s v=%.3f",
                self._readings_published,
                reading.channel,
                reading.value,
            )
        await self._pub_queue.put(reading)

    async def _handle_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")
        logger.debug("[D3-REPLAY] REP recv: %s", action)  # [D3-REPLAY]

        if action == "safety_status":
            reply = {"ok": True, "state": "replay", "alarms": []}
            logger.debug("[D3-REPLAY] REP reply safety_status: %s", reply)  # [D3-REPLAY]
            return reply

        if action == "current_phase":
            reply = {
                "ok": True,
                "phase": self._phase,
                "phase_started_at": self._session_start,
            }
            logger.debug("[D3-REPLAY] REP reply current_phase: phase=%s", self._phase)  # [D3-R]
            return reply

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

        if action == "cooldown_history_get":
            return {"ok": False, "reason": "predictor_unavailable_in_replay"}

        if any(action.startswith(p) for p in _READONLY_PREFIXES):
            logger.info("[D3-REPLAY] rejected hardware cmd in replay: %s", action)  # [D3-REPLAY]
            return {"ok": False, "reason": "REPLAY_MODE_READONLY"}

        # Unknown commands — reject as readonly rather than error
        return {"ok": False, "reason": "REPLAY_MODE_READONLY"}
