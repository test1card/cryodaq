"""SQLiteAdapter — range stats queries for query agent, over ZMQ.

B1: previously read the engine's SQLite reader directly (in-process);
now calls the engine's existing read-only ``readings_history`` REP
command (same one the GUI history charts use) and computes the same
stats client-side.
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime

from cryodaq.agents.assistant.query.schemas import RangeStats
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """Range statistics over a time window via the engine's readings history."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def range_stats(
        self,
        channel: str,
        window_minutes: int,
    ) -> RangeStats | None:
        end_ts = datetime.now(UTC).timestamp()
        start_ts = end_ts - window_minutes * 60
        reply = await self._client.call(
            {
                "cmd": "readings_history",
                "channels": [channel],
                "from_ts": start_ts,
                "limit_per_channel": 10_000,
            }
        )
        if not reply.get("ok"):
            return None

        readings = reply.get("data", {}).get(channel, [])
        if not readings:
            return None

        try:
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
        except Exception as exc:
            logger.warning("SQLiteAdapter.range_stats failed: %s", exc)
            return None
