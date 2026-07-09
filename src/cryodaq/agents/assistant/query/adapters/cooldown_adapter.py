"""CooldownAdapter — reads the engine's live cooldown ETA prediction.

B1: previously wrapped a direct reference to the in-process
``CooldownService``; now calls the engine's read-only ``cooldown_eta_get``
REP command (new, additive — mirrors the existing ``get_vacuum_trend``
read command, exposing ``CooldownService.last_prediction()`` the same way).
"""

from __future__ import annotations

import logging
from typing import Any

from cryodaq.agents.assistant.query.schemas import CooldownETA
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class CooldownAdapter:
    """Read the engine's cached cooldown prediction over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def eta(self) -> CooldownETA | None:
        reply = await self._client.call({"cmd": "cooldown_eta_get"})
        if not reply.get("ok"):
            return None
        pred: dict[str, Any] | None = reply.get("prediction")
        if pred is None:
            return None
        try:
            return CooldownETA(
                t_remaining_hours=float(pred.get("t_remaining_hours", 0.0)),
                t_remaining_low_68=float(pred.get("t_remaining_ci68", (0.0, 0.0))[0]),
                t_remaining_high_68=float(pred.get("t_remaining_ci68", (0.0, 0.0))[1]),
                progress=float(pred.get("progress", 0.0)),
                phase=str(pred.get("phase", "unknown")),
                n_references=int(pred.get("n_references", 0)),
                cooldown_active=bool(pred.get("cooldown_active", False)),
                T_cold=pred.get("T_cold"),
                T_warm=pred.get("T_warm"),
            )
        except Exception as exc:
            logger.warning("CooldownAdapter: failed to parse prediction: %s", exc)
            return None
