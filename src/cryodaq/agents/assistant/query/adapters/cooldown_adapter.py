"""CooldownAdapter — wraps CooldownService.last_prediction() for query agent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import CooldownETA

if TYPE_CHECKING:
    from cryodaq.analytics.cooldown_service import CooldownService

logger = logging.getLogger(__name__)


class CooldownAdapter:
    """Read cached cooldown prediction from CooldownService.

    CooldownService runs predict() every 30s and caches the result via
    last_prediction(). We read that cache; no new computation here.
    """

    def __init__(self, cooldown_service: CooldownService | None) -> None:
        self._service = cooldown_service

    async def eta(self) -> CooldownETA | None:
        if self._service is None:
            return None
        pred: dict[str, Any] | None = self._service.last_prediction()
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
