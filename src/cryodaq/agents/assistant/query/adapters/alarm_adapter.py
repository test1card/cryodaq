"""AlarmAdapter — wraps AlarmEngine for query agent."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, AlarmStatusResult

if TYPE_CHECKING:
    from cryodaq.core.alarm import AlarmEngine

logger = logging.getLogger(__name__)


class AlarmAdapter:
    """Read active alarms from AlarmEngine. Read-only."""

    def __init__(self, alarm_engine: AlarmEngine | None) -> None:
        self._engine = alarm_engine

    async def active(self) -> AlarmStatusResult:
        if self._engine is None:
            return AlarmStatusResult()
        try:
            details: list[dict[str, Any]] = self._engine.get_active_alarm_details()
            infos = [
                ActiveAlarmInfo(
                    alarm_id=d["alarm_id"],
                    level=d["level"],
                    channels=[d["channel_pattern"]],
                    triggered_at=d["triggered_at"],
                )
                for d in details
            ]
            return AlarmStatusResult(active=infos)
        except Exception as exc:
            logger.warning("AlarmAdapter.active failed: %s", exc)
            return AlarmStatusResult()
