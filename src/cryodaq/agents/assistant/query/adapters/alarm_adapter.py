"""AlarmAdapter — wraps AlarmStateManager (alarm v2) for query agent."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, AlarmStatusResult

if TYPE_CHECKING:
    from cryodaq.core.alarm_v2 import AlarmStateManager

logger = logging.getLogger(__name__)


class AlarmAdapter:
    """Read active alarms from AlarmStateManager (alarm v2). Read-only."""

    def __init__(self, alarm_state_mgr: AlarmStateManager | None) -> None:
        self._mgr = alarm_state_mgr

    async def active(self) -> AlarmStatusResult:
        if self._mgr is None:
            return AlarmStatusResult()
        try:
            active: dict[str, Any] = self._mgr.get_active()
            infos = [
                ActiveAlarmInfo(
                    alarm_id=alarm_id,
                    level=event.level,
                    channels=list(event.channels),
                    triggered_at=datetime.fromtimestamp(event.triggered_at, tz=UTC),
                )
                for alarm_id, event in active.items()
            ]
            return AlarmStatusResult(active=infos)
        except Exception as exc:
            logger.warning("AlarmAdapter.active failed: %s", exc)
            return AlarmStatusResult()
