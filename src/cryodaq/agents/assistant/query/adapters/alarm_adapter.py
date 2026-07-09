"""AlarmAdapter — reads active alarms (alarm v2) from the engine over ZMQ.

B1: previously wrapped a direct reference to the in-process
``AlarmStateManager``; now calls the engine's existing read-only
``alarm_v2_status`` REP command (same one the GUI alarm banner uses).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, AlarmStatusResult
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class AlarmAdapter:
    """Read active alarms from the engine over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def active(self) -> AlarmStatusResult:
        reply = await self._client.call({"cmd": "alarm_v2_status"})
        if not reply.get("ok"):
            return AlarmStatusResult()
        try:
            active: dict[str, Any] = reply.get("active", {})
            infos = [
                ActiveAlarmInfo(
                    alarm_id=alarm_id,
                    level=info.get("level", ""),
                    channels=list(info.get("channels", [])),
                    triggered_at=(
                        datetime.fromtimestamp(info["triggered_at"], tz=UTC)
                        if info.get("triggered_at") is not None
                        else None
                    ),
                )
                for alarm_id, info in active.items()
            ]
            return AlarmStatusResult(active=infos)
        except Exception as exc:
            logger.warning("AlarmAdapter.active failed: %s", exc)
            return AlarmStatusResult()
