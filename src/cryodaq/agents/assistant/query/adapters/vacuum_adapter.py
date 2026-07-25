"""VacuumAdapter — reads the engine's live vacuum trend prediction.

B1: previously wrapped a direct reference to the in-process
``VacuumTrendPredictor``; now calls the engine's existing read-only
``get_vacuum_trend`` REP command (same one the GUI vacuum-trend widget
already uses — ``{"ok": True, **dataclasses.asdict(prediction)}``).
"""

from __future__ import annotations

import logging

from cryodaq.agents.assistant.query.schemas import VacuumETA
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class VacuumAdapter:
    """Read the engine's cached vacuum trend prediction over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def eta_to_target(self, target_mbar: float) -> VacuumETA | None:
        reply = await self._client.call({"cmd": "get_vacuum_trend"})
        if not reply.get("ok") or reply.get("status") == "no_data":
            return None
        try:
            eta_targets: dict = reply.get("eta_targets") or {}
            # eta_targets keys are stringified scientific notation, e.g. "1e-06"
            target_key = f"{target_mbar:.2e}"
            eta_seconds = eta_targets.get(target_key)
            if eta_seconds is None:
                # Try without leading zeros in exponent
                for k, v in eta_targets.items():
                    try:
                        if abs(float(k) - target_mbar) / max(abs(target_mbar), 1e-30) < 1e-3:
                            eta_seconds = v
                            break
                    except ValueError:
                        continue

            # current_mbar from the last known pressure — not in prediction,
            # caller (CompositeAdapter) fills it in from BrokerSnapshot.
            return VacuumETA(
                current_mbar=None,
                eta_seconds=eta_seconds,
                target_mbar=target_mbar,
                trend=str(reply.get("trend", "unknown")),
                confidence=float(reply.get("confidence", 0.0)),
            )
        except Exception as exc:
            logger.warning("VacuumAdapter: failed to parse prediction: %s", exc)
            return None
