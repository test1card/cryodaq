"""Range-statistics queries for the assistant, over the read-only engine API."""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from datetime import UTC, datetime
from typing import Any

from cryodaq.agents.assistant.query.adapters._reply import (
    reply_declares_empty_sequence,
    reply_failure_reason,
    reply_is_success,
)
from cryodaq.agents.assistant.query.schemas import RangeStats
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """Range statistics over a time window via the engine's readings history."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def range_stats(self, channel: str, window_minutes: int) -> RangeStats | None:
        end_ts = datetime.now(UTC).timestamp()
        start_ts = end_ts - window_minutes * 60
        try:
            reply = await self._client.call(
                {
                    "cmd": "readings_history",
                    "channels": [channel],
                    "from_ts": start_ts,
                    "limit_per_channel": 10_000,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(channel, window_minutes, f"history query unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(channel, window_minutes, reply_failure_reason(reply, "history query unavailable"))
        if reply_declares_empty_sequence(reply, "data", channel):
            return None
        try:
            data: Any = reply["data"]
            if not isinstance(data, dict) or channel not in data or not isinstance(data[channel], list):
                raise ValueError("history response has no channel list")
            readings = data[channel]
            values = []
            for row in readings:
                if not isinstance(row, (tuple, list)) or len(row) != 2:
                    raise ValueError("history sample must have timestamp and value")
                value = row[1]
                if not isinstance(value, int | float) or not math.isfinite(value):
                    raise ValueError("history sample value is invalid")
                values.append(value)
            if not values:
                raise ValueError("history response has no usable values")
            return RangeStats(
                channel=channel,
                window_minutes=window_minutes,
                n_samples=len(values),
                min_value=min(values),
                max_value=max(values),
                mean_value=statistics.mean(values),
                std_value=statistics.stdev(values) if len(values) > 1 else 0.0,
            )
        except (KeyError, TypeError, ValueError, statistics.StatisticsError) as exc:
            logger.warning("SQLiteAdapter.range_stats failed: %s", exc)
            return self._unavailable(channel, window_minutes, "history response is malformed")

    @staticmethod
    def _unavailable(channel: str, window_minutes: int, reason: str) -> RangeStats:
        return RangeStats(channel, window_minutes, 0, 0.0, 0.0, 0.0, 0.0, available=False, stale=True, reason=reason)
