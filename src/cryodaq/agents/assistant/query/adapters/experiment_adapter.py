"""Read current experiment state from the engine's read-only query surface."""

from __future__ import annotations

import asyncio
import logging

from cryodaq.agents.assistant.query.adapters._reply import (
    reply_declares_absence,
    reply_failure_reason,
    reply_is_success,
)
from cryodaq.agents.assistant.query.schemas import ExperimentStatus
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class ExperimentAdapter:
    """Read current experiment state from the engine over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def status(self) -> ExperimentStatus | None:
        try:
            reply = await self._client.call({"cmd": "experiment_status"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(f"experiment status unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(reply_failure_reason(reply, "experiment status unavailable"))
        if reply_declares_absence(reply, "active_experiment"):
            return None
        try:
            active = reply["active_experiment"]
            if not isinstance(active, dict):
                raise ValueError("active_experiment must be an object")
            exp_id = active["experiment_id"]
            if not isinstance(exp_id, str) or not exp_id.strip():
                raise ValueError("experiment_id must be a non-empty string")
            return ExperimentStatus(
                experiment_id=exp_id,
                phase=reply.get("current_phase"),
                phase_started_at=reply.get("phase_started_at"),
                experiment_age_s=None,
                target_temp=None,
                sample_id=None,
                experiment_started_human=None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("ExperimentAdapter.status failed: %s", exc)
            return self._unavailable("experiment status response is malformed")

    @staticmethod
    def _unavailable(reason: str) -> ExperimentStatus:
        return ExperimentStatus("", None, None, None, available=False, stale=True, reason=reason)
