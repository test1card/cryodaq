"""ExperimentAdapter — wraps ExperimentManager for query agent."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryodaq.agents.assistant.query.schemas import ExperimentStatus

if TYPE_CHECKING:
    from cryodaq.core.experiment import ExperimentManager

logger = logging.getLogger(__name__)


class ExperimentAdapter:
    """Read current experiment state from ExperimentManager. Read-only."""

    def __init__(self, experiment_manager: ExperimentManager | None) -> None:
        self._em = experiment_manager

    async def status(self) -> ExperimentStatus | None:
        if self._em is None:
            return None
        exp_id = getattr(self._em, "active_experiment_id", None)
        if exp_id is None:
            return None
        try:
            active = getattr(self._em, "active_experiment", None)
            phase: str | None = None
            if hasattr(self._em, "get_current_phase"):
                try:
                    phase = self._em.get_current_phase()
                except Exception:
                    pass

            phase_started_at: float | None = None
            if hasattr(self._em, "_get_phase_started_at"):
                try:
                    phase_started_at = self._em._get_phase_started_at()
                except Exception:
                    pass

            started_at: float | None = None
            if active is not None:
                raw = getattr(active, "started_at", None)
                if raw is not None:
                    try:
                        started_at = float(raw)
                    except (TypeError, ValueError):
                        pass

            experiment_age_s = (time.time() - started_at) if started_at else 0.0

            started_human: str | None = None
            if started_at is not None:
                try:
                    dt = datetime.fromtimestamp(started_at, tz=UTC)
                    started_human = dt.strftime("%H:%M UTC %d.%m.%Y")
                except (OSError, OverflowError, ValueError):
                    pass

            return ExperimentStatus(
                experiment_id=exp_id,
                phase=phase,
                phase_started_at=phase_started_at,
                experiment_age_s=experiment_age_s,
                target_temp=getattr(active, "target_temp", None) if active else None,
                sample_id=getattr(active, "sample_id", None) if active else None,
                experiment_started_human=started_human,
            )
        except Exception as exc:
            logger.warning("ExperimentAdapter.status failed: %s", exc)
            return None
