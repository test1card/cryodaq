"""Read active alarm-v2 state from the engine's read-only query surface."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.adapters._reply import reply_failure_reason, reply_is_success
from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, AlarmStatusResult
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class AlarmAdapter:
    """Read active alarms from the engine over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def active(self) -> AlarmStatusResult:
        try:
            reply = await self._client.call({"cmd": "alarm_v2_status"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(f"active alarms unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(reply_failure_reason(reply, "active alarms unavailable"))
        try:
            active = reply["active"]
            if type(active) is not dict:
                raise ValueError("active must be an object")
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
                raise ValueError("active alarm entry is malformed")
            return AlarmStatusResult(
                active=[
                    ActiveAlarmInfo(
                        alarm_id=alarm_id,
                        level=info["level"],
                        channels=list(info["channels"]),
                        triggered_at=datetime.fromtimestamp(info["triggered_at"], tz=UTC),
                    )
                    for alarm_id, info in active.items()
                ]
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
            logger.warning("AlarmAdapter.active failed: %s", exc)
            return self._unavailable("active alarms response is malformed")

    @staticmethod
    def _unavailable(reason: str) -> AlarmStatusResult:
        return AlarmStatusResult(available=False, stale=True, reason=reason)
