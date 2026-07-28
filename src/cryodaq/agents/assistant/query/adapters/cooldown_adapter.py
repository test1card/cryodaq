"""CooldownAdapter — reads the engine's live cooldown ETA prediction.

B1: previously wrapped a direct reference to the in-process
``CooldownService``; now calls the engine's read-only ``cooldown_eta_get``
REP command (new, additive — mirrors the existing ``get_vacuum_trend``
read command, exposing ``CooldownService.last_prediction()`` the same way).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cryodaq.agents.assistant.query.adapters._reply import (
    reply_declares_absence,
    reply_failure_reason,
    reply_is_success,
)
from cryodaq.agents.assistant.query.schemas import CooldownETA
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class CooldownAdapter:
    """Read the engine's cached cooldown prediction over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def eta(self) -> CooldownETA | None:
        try:
            reply = await self._client.call({"cmd": "cooldown_eta_get"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(f"cooldown prediction unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(reply_failure_reason(reply, "cooldown prediction unavailable"))
        if reply_declares_absence(reply, "prediction"):
            return None
        try:
            pred: Any = reply["prediction"]
            if not isinstance(pred, dict):
                raise ValueError("prediction must be an object")
            interval = pred["t_remaining_ci68"]
            if not isinstance(interval, (tuple, list)) or len(interval) != 2:
                raise ValueError("t_remaining_ci68 must have two values")
            phase = pred["phase"]
            if not isinstance(phase, str):
                raise ValueError("phase must be a string")
            n_references = pred["n_references"]
            cooldown_active = pred["cooldown_active"]
            if type(n_references) is not int or type(cooldown_active) is not bool:
                raise ValueError("prediction flags have invalid types")
            return CooldownETA(
                t_remaining_hours=float(pred["t_remaining_hours"]),
                t_remaining_low_68=float(interval[0]),
                t_remaining_high_68=float(interval[1]),
                progress=float(pred["progress"]),
                phase=phase,
                n_references=n_references,
                cooldown_active=cooldown_active,
                T_cold=pred.get("T_cold"),
                T_warm=pred.get("T_warm"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("CooldownAdapter: failed to parse prediction: %s", exc)
            return self._unavailable("cooldown prediction response is malformed")

    @staticmethod
    def _unavailable(reason: str) -> CooldownETA:
        return CooldownETA(0.0, 0.0, 0.0, 0.0, "", 0, False, available=False, stale=True, reason=reason)
