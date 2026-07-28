"""VacuumAdapter — reads the engine's live vacuum trend prediction.

B1: previously wrapped a direct reference to the in-process
``VacuumTrendPredictor``; now calls the engine's existing read-only
``get_vacuum_trend`` REP command (same one the GUI vacuum-trend widget
already uses — ``{"ok": True, **dataclasses.asdict(prediction)}``).
"""

from __future__ import annotations

import asyncio
import logging

from cryodaq.agents.assistant.query.adapters._reply import (
    reply_declares_no_data,
    reply_failure_reason,
    reply_is_success,
)
from cryodaq.agents.assistant.query.schemas import VacuumETA
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class VacuumAdapter:
    """Read the engine's cached vacuum trend prediction over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def eta_to_target(self, target_mbar: float) -> VacuumETA | None:
        try:
            reply = await self._client.call({"cmd": "get_vacuum_trend"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(target_mbar, f"vacuum prediction unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(target_mbar, reply_failure_reason(reply, "vacuum prediction unavailable"))
        if reply_declares_no_data(reply):
            return None
        try:
            eta_targets = reply["eta_targets"]
            trend = reply["trend"]
            confidence = reply["confidence"]
            if not isinstance(eta_targets, dict) or not isinstance(trend, str):
                raise ValueError("vacuum prediction has invalid fields")
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
                trend=trend,
                confidence=float(confidence),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("VacuumAdapter: failed to parse prediction: %s", exc)
            return self._unavailable(target_mbar, "vacuum prediction response is malformed")

    @staticmethod
    def _unavailable(target_mbar: float, reason: str) -> VacuumETA:
        return VacuumETA(None, None, target_mbar, "", 0.0, available=False, stale=True, reason=reason)
