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
from cryodaq.agents.assistant.query.schemas import ChannelTrend, RangeStats
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """Range statistics over a time window via the engine's readings history."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    @staticmethod
    def _parse_history_pairs(reply: dict, channel: str) -> tuple[list[tuple[float, float]] | None, str | None]:
        """(timestamp, value) pairs from a SUCCESSFUL reply, or (None, reason).

        Pure: it never touches the engine. That is deliberate — the C1 adapter
        seal requires every method that queries the engine to fail into a typed
        absence of its own, so the query and its failure branch stay inside
        each public method and only the parsing is shared. Sharing the parsing
        is what matters; sharing the socket call would have cost the contract.
        """
        data: Any = reply.get("data")
        if not isinstance(data, dict) or channel not in data or not isinstance(data[channel], list):
            return None, "history response has no channel list"
        pairs: list[tuple[float, float]] = []
        for row in data[channel]:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                return None, "history response is malformed"
            ts, value = row[0], row[1]
            if not isinstance(ts, int | float) or not isinstance(value, int | float):
                return None, "history response is malformed"
            if not math.isfinite(ts) or not math.isfinite(value):
                return None, "history response is malformed"
            pairs.append((float(ts), float(value)))
        if not pairs:
            return None, "history response has no usable values"
        pairs.sort()
        return pairs, None

    async def trend(self, channel: str, window_minutes: int) -> ChannelTrend | None:
        """Rate of change over the window, by least squares.

        Least squares rather than last-minus-first because one noisy endpoint
        should not decide the answer to "куда оно идёт": a flat window whose
        final sample spikes reads as a steep ramp under endpoint arithmetic,
        and that is a reading an operator would act on.

        A window with no time span at all — every sample at one instant — has
        no slope. It says so rather than reporting a rate of zero, which would
        be indistinguishable from a genuinely steady channel.
        """
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
            return self._trend_unavailable(channel, window_minutes, f"history query unavailable: {exc}")
        if not reply_is_success(reply):
            return self._trend_unavailable(
                channel, window_minutes, reply_failure_reason(reply, "history query unavailable")
            )
        if reply_declares_empty_sequence(reply, "data", channel):
            # A TYPED absence, not a bare None. An empty history is not the same
            # as "this channel has no trend to speak of": a channel that is
            # publishing live while its persistence has stopped produces exactly
            # this reply, and returning None made the composite drop it silently
            # and still report itself fresh. The operator would see a channel
            # with no dynamics and no hint that anything was wrong with it.
            return self._trend_unavailable(
                channel, window_minutes, "истории за окно нет — возможно, запись по каналу встала"
            )
        pairs, reason = self._parse_history_pairs(reply, channel)
        if pairs is None:
            return self._trend_unavailable(channel, window_minutes, reason or "history response is malformed")

        span_s = pairs[-1][0] - pairs[0][0]
        t0 = pairs[0][0]
        xs = [ts - t0 for ts, _ in pairs]
        ys = [value for _, value in pairs]
        mean_x = sum(xs) / len(xs)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if len(pairs) < 2 or span_s <= 0 or denominator <= 0:
            return self._trend_unavailable(channel, window_minutes, "window carries no time span; a slope needs one")
        mean_y = sum(ys) / len(ys)
        slope_per_s = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
        intercept = mean_y - slope_per_s * mean_x
        residuals = [y - (slope_per_s * x + intercept) for x, y in zip(xs, ys, strict=True)]
        # Standard error of the SLOPE: residual variance on n-2 degrees of
        # freedom, divided by the spread of the x values. `direction` compares
        # the slope against this, so a window whose scatter swamps its trend
        # cannot claim one — while a small drift measured over many samples
        # still can, because this error falls as the square root of the count.
        dof = max(len(residuals) - 2, 1)
        residual_variance = sum(r * r for r in residuals) / dof
        slope_stderr_per_s = (residual_variance / denominator) ** 0.5
        return ChannelTrend(
            channel=channel,
            window_minutes=window_minutes,
            n_samples=len(pairs),
            first_value=ys[0],
            last_value=ys[-1],
            span_s=span_s,
            rate_per_hour=slope_per_s * 3600.0,
            slope_stderr_per_hour=slope_stderr_per_s * 3600.0,
        )

    @staticmethod
    def _trend_unavailable(channel: str, window_minutes: int, reason: str) -> ChannelTrend:
        return ChannelTrend(
            channel=channel,
            window_minutes=window_minutes,
            n_samples=0,
            first_value=0.0,
            last_value=0.0,
            span_s=0.0,
            rate_per_hour=0.0,
            available=False,
            stale=True,
            reason=reason,
        )

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
