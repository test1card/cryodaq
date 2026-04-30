"""SQLiteAdapter — range stats queries for query agent."""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime
from typing import Any

from cryodaq.agents.assistant.query.schemas import RangeStats

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """Range statistics over a time window via the existing SQLite reader."""

    def __init__(self, sqlite_reader: Any) -> None:
        self._reader = sqlite_reader

    async def range_stats(
        self,
        channel: str,
        window_minutes: int,
    ) -> RangeStats | None:
        if not hasattr(self._reader, "read_readings_history"):
            return None
        end_ts = datetime.now(UTC).timestamp()
        start_ts = end_ts - window_minutes * 60
        try:
            data: dict[str, list[tuple[float, float]]] = (
                await self._reader.read_readings_history(
                    channels=[channel],
                    from_ts=start_ts,
                    limit_per_channel=10_000,
                )
            )
        except Exception as exc:
            logger.warning("SQLiteAdapter.range_stats failed: %s", exc)
            return None

        readings = data.get(channel, [])
        if not readings:
            return None

        values = [v for _, v in readings]
        return RangeStats(
            channel=channel,
            window_minutes=window_minutes,
            n_samples=len(values),
            min_value=min(values),
            max_value=max(values),
            mean_value=statistics.mean(values),
            std_value=statistics.stdev(values) if len(values) > 1 else 0.0,
        )
