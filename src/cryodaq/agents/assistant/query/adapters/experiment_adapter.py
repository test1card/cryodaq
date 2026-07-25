"""ExperimentAdapter — reads current experiment state from the engine over ZMQ.

B1: previously wrapped a direct reference to the in-process
``ExperimentManager``; now calls the engine's existing read-only
``experiment_status`` REP command (``ExperimentManager.get_status_payload()``
— same one the GUI experiment panel uses).

Note on ``target_temp`` / ``sample_id`` / ``experiment_age_s`` /
``experiment_started_human``: the original adapter read these via
``getattr(active_experiment_obj, "target_temp"/"sample_id"/"started_at", None)``,
but ``ExperimentInfo`` (``core/experiment.py``) is a ``slots=True`` dataclass
with no such attributes — those ``getattr`` calls always fell through to
their defaults in production. This rewrite preserves that exact (dead)
behaviour rather than silently changing what the query agent reports;
fixing it is a separate, deliberate change outside this extraction's scope.
"""

from __future__ import annotations

import logging

from cryodaq.agents.assistant.query.schemas import ExperimentStatus
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class ExperimentAdapter:
    """Read current experiment state from the engine over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def status(self) -> ExperimentStatus | None:
        reply = await self._client.call({"cmd": "experiment_status"})
        if not reply.get("ok"):
            return None
        active = reply.get("active_experiment")
        if active is None:
            return None
        try:
            exp_id = active.get("experiment_id")
            if exp_id is None:
                return None
            return ExperimentStatus(
                experiment_id=exp_id,
                phase=reply.get("current_phase"),
                phase_started_at=reply.get("phase_started_at"),
                # See module docstring — always 0.0 / None in the original too.
                experiment_age_s=0.0,
                target_temp=None,
                sample_id=None,
                experiment_started_human=None,
            )
        except Exception as exc:
            logger.warning("ExperimentAdapter.status failed: %s", exc)
            return None
