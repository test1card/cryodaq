"""AlarmAdapter — reads active alarms (alarm v2) from the engine over ZMQ.

B1: previously wrapped a direct reference to the in-process
``AlarmStateManager``; now calls the engine's existing read-only
``alarm_v2_status`` REP command (same one the GUI alarm banner uses).
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, AlarmStatusResult
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class AlarmAdapter:
    """Read active alarms from the engine over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def active(self) -> AlarmStatusResult | None:
        try:
            reply = await self._client.call({"cmd": "alarm_v2_status"})
            if type(reply) is not dict or reply.get("ok") is not True:
                return None
            active = reply.get("active")
            if type(active) is not dict:
                return None
            if any(
                type(alarm_id) is not str
                or not alarm_id
                or type(info) is not dict
                or type(info.get("level")) is not str
                or not info["level"]
                or type(info.get("triggered_at")) not in (int, float)
                or not math.isfinite(float(info["triggered_at"]))
                or type(info.get("channels")) is not list
                or any(type(channel) is not str for channel in info["channels"])
                for alarm_id, info in active.items()
            ):
                return None
            infos = [
                ActiveAlarmInfo(
                    alarm_id=alarm_id,
                    level=info["level"],
                    channels=list(info["channels"]),
                    triggered_at=datetime.fromtimestamp(info["triggered_at"], tz=UTC),
                )
                for alarm_id, info in active.items()
            ]
            return AlarmStatusResult(active=infos)
        except Exception as exc:
            logger.warning("AlarmAdapter.active failed: %s", exc)
            return None
