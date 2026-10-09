"""VacuumAdapter — wraps VacuumTrendPredictor.get_prediction() for query agent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cryodaq.agents.assistant.query.schemas import VacuumETA

if TYPE_CHECKING:
    from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor

logger = logging.getLogger(__name__)


class VacuumAdapter:
    """Read latest vacuum trend prediction from VacuumTrendPredictor.

    VacuumTrendPredictor.get_prediction() returns the last computed
    VacuumPrediction (updated every update_interval_s). We read it read-only.
    """

    def __init__(
        self,
        predictor: VacuumTrendPredictor | None,
    ) -> None:
        self._predictor = predictor

    async def eta_to_target(self, target_mbar: float) -> VacuumETA | None:
        if self._predictor is None:
            return None
        pred = self._predictor.get_prediction()
        if pred is None:
            return None
        try:
            # eta_targets keys are stringified scientific notation, e.g. "1e-06"
            target_key = f"{target_mbar:.2e}"
            # also try compact form "1e-06"
            eta_seconds = pred.eta_targets.get(target_key)
            if eta_seconds is None:
                # Try without leading zeros in exponent
                for k, v in pred.eta_targets.items():
                    try:
                        if abs(float(k) - target_mbar) / max(abs(target_mbar), 1e-30) < 1e-3:
                            eta_seconds = v
                            break
                    except ValueError:
                        continue

            # current_mbar from the last known pressure — not in prediction,
            # pass None (caller uses BrokerSnapshot for current value)
            return VacuumETA(
                current_mbar=None,
                eta_seconds=eta_seconds,
                target_mbar=target_mbar,
                trend=str(pred.trend),
                confidence=float(pred.confidence),
            )
        except Exception as exc:
            logger.warning("VacuumAdapter: failed to parse prediction: %s", exc)
            return None
