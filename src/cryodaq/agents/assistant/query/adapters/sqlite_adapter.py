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


#: Rows to ask for per trend query. The engine's own cap is higher; this is
#: what the bucket is sized against.
_TREND_POINT_BUDGET = 3_000


def _trend_bucket(window_minutes: int) -> float:
    """Seconds per bucket so the whole window fits the budget. Rounded up."""
    seconds = max(float(window_minutes), 1.0) * 60.0
    return max(math.ceil(seconds / _TREND_POINT_BUDGET), 2.0)


def _fit_rate(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares rate per hour and its standard error, or None."""
    if len(pairs) < 4:
        return None
    t0 = pairs[0][0]
    xs = [ts - t0 for ts, _ in pairs]
    ys = [value for _, value in pairs]
    mean_x = sum(xs) / len(xs)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return None
    mean_y = sum(ys) / len(ys)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    residuals = [y - (mean_y + slope * (x - mean_x)) for x, y in zip(xs, ys, strict=True)]
    variance = sum(r * r for r in residuals) / max(len(residuals) - 2, 1)
    return slope * 3600.0, (variance / denominator) ** 0.5 * 3600.0


#: A regime is only a regime if enough of it was measured. Below this a split
#: is fitting noise on one side of itself.
_MIN_REGIME_POINTS = 12

#: How much better the two-piece fit must be before a change of regime is
#: claimed.
_REGIME_SSE_GAIN = 2.0

#: AND how differently the two pieces must rise. The residual test alone is not
#: enough: data that merely CURVES is always fitted better by two lines than by
#: one, so on the stand's own pressure — falling 3% across a day — it invented a
#: regime change at an hour when nothing had happened. A real change of regime
#: moves the rate by a lot; curvature moves it by a little.
_REGIME_SLOPE_GAIN = 0.5


def _sse(n: int, sx: float, sy: float, sxx: float, sxy: float, syy: float) -> float | None:
    """Residual sum of squares of the least-squares line, from running sums."""

    if n < 3:
        return None
    sxx_c = sxx - sx * sx / n
    if sxx_c <= 0.0:
        return None
    sxy_c = sxy - sx * sy / n
    syy_c = syy - sy * sy / n
    return max(syy_c - sxy_c * sxy_c / sxx_c, 0.0)


def _regime_start(pairs: list[tuple[float, float]]) -> int | None:
    """Index where the current regime began, or None if the window is one piece.

    The thing that separates a constant source from a decaying one is the
    BEGINNING of the rise, where a decaying source is steepest. A fixed window
    that starts in the middle of a rise cannot see it: on 2026-09-08 the agent
    was asked whether the pressure was a leak or desorption and answered, from
    24 hours of the middle, that the two do not separate. They do — twenty
    minutes after the chamber was isolated the rate was already at its full
    value and it never decayed. The window has to start where the regime did.

    Two straight pieces against one, by residual. No claim is made unless the
    split halves the residual, which a split of genuinely straight data does
    not do.
    """

    n = len(pairs)
    if n < 2 * _MIN_REGIME_POINTS:
        return None
    t0 = pairs[0][0]
    xs = [ts - t0 for ts, _ in pairs]
    ys = [value for _, value in pairs]

    px = [0.0] * (n + 1)
    py = [0.0] * (n + 1)
    pxx = [0.0] * (n + 1)
    pxy = [0.0] * (n + 1)
    pyy = [0.0] * (n + 1)
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        px[i + 1] = px[i] + x
        py[i + 1] = py[i] + y
        pxx[i + 1] = pxx[i] + x * x
        pxy[i + 1] = pxy[i] + x * y
        pyy[i + 1] = pyy[i] + y * y

    def piece(lo: int, hi: int) -> tuple[float, float] | None:
        """Residual and slope of the least-squares line over ``pairs[lo:hi]``."""

        count = hi - lo
        sx = px[hi] - px[lo]
        sy = py[hi] - py[lo]
        sxx = pxx[hi] - pxx[lo]
        sxy = pxy[hi] - pxy[lo]
        syy = pyy[hi] - pyy[lo]
        sse = _sse(count, sx, sy, sxx, sxy, syy)
        if sse is None:
            return None
        sxx_c = sxx - sx * sx / count
        if sxx_c <= 0.0:
            return None
        return sse, (sxy - sx * sy / count) / sxx_c

    entire = piece(0, n)
    if entire is None or entire[0] <= 0.0:
        return None
    whole = entire[0]

    best_index: int | None = None
    best_sse = whole
    best_slopes = (0.0, 0.0)
    for split in range(_MIN_REGIME_POINTS, n - _MIN_REGIME_POINTS + 1):
        left = piece(0, split)
        right = piece(split, n)
        if left is None or right is None:
            continue
        total = left[0] + right[0]
        if total < best_sse:
            best_sse = total
            best_index = split
            best_slopes = (left[1], right[1])
    if best_index is None or best_sse * _REGIME_SSE_GAIN > whole:
        return None
    before, after = best_slopes
    scale = max(abs(before), abs(after))
    if scale <= 0.0 or abs(after - before) < _REGIME_SLOPE_GAIN * scale:
        return None
    return best_index


def _shape_of_rise(pairs: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """RMS residual of three laws: linear, sqrt(t), log(t). Smaller fits better.

    A constant source gives a straight line; a source that depletes bends. The
    three together say which, and by how much, without anybody having to pick a
    threshold: the ratios are the answer.
    """

    if len(pairs) < 8:
        return None
    t0 = pairs[0][0]
    span = pairs[-1][0] - t0
    if span <= 0.0:
        return None
    # A hair of offset so log and sqrt are defined at the first sample.
    floor = max(span / len(pairs), 1.0)
    out: list[float] = []
    for transform in (
        lambda dt: dt,
        lambda dt: math.sqrt(dt + floor),
        lambda dt: math.log(dt + floor),
    ):
        xs = [transform(ts - t0) for ts, _ in pairs]
        ys = [value for _, value in pairs]
        n = len(xs)
        sx = sum(xs)
        sy = sum(ys)
        sse = _sse(
            n,
            sx,
            sy,
            sum(x * x for x in xs),
            sum(x * y for x, y in zip(xs, ys, strict=True)),
            sum(y * y for y in ys),
        )
        if sse is None:
            return None
        out.append((sse / n) ** 0.5)
    return (out[0], out[1], out[2])


def _centred_quadratic(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Fitted CHANGE IN SLOPE across the window, and its standard error.

    Fits p(t) = a + b·(t−tc) + c·(t−tc)² about the window centre and reports
    2·c·T, the slope's change from one end to the other, rather than c itself.
    A curvature coefficient in units per hour squared is not a quantity anyone
    reasons with; "the rate fell by 0.008 mbar/h across the window" is.

    Deliberately no exponential or aged-power-law fit. Their parameters are
    poorly identified over a record this short — slope and curvature are well
    constrained while the split between a constant term and a decaying one is
    not — and a poorly identified parameter still prints as a number, which the
    agent then reports and the reader then believes. This program has already
    told an operator "сигнал 1495σ" once.
    """
    if len(pairs) < 8:
        return None
    t0 = pairs[0][0]
    span = pairs[-1][0] - t0
    if span <= 0:
        return None
    centre = t0 + span / 2.0
    xs = [(ts - centre) / 3600.0 for ts, _ in pairs]
    ys = [value for _, value in pairs]
    n = len(xs)
    s1 = sum(xs)
    s2 = sum(x * x for x in xs)
    s3 = sum(x**3 for x in xs)
    s4 = sum(x**4 for x in xs)
    ty = sum(ys)
    txy = sum(x * y for x, y in zip(xs, ys, strict=True))
    tx2y = sum(x * x * y for x, y in zip(xs, ys, strict=True))
    # Normal equations for the quadratic, solved directly: three unknowns.
    m = [[n, s1, s2], [s1, s2, s3], [s2, s3, s4]]
    rhs = [ty, txy, tx2y]
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    if abs(det) < 1e-30:
        return None

    def _solve(column: int) -> float:
        cols = [[row[i] if i != column else rhs[j] for i in range(3)] for j, row in enumerate(m)]
        return (
            cols[0][0] * (cols[1][1] * cols[2][2] - cols[1][2] * cols[2][1])
            - cols[0][1] * (cols[1][0] * cols[2][2] - cols[1][2] * cols[2][0])
            + cols[0][2] * (cols[1][0] * cols[2][1] - cols[1][1] * cols[2][0])
        ) / det

    a, b, c = _solve(0), _solve(1), _solve(2)
    residuals = [y - (a + b * x + c * x * x) for x, y in zip(xs, ys, strict=True)]
    variance = sum(r * r for r in residuals) / max(n - 3, 1)
    # Var(c) is the (2,2) entry of variance·(XᵀX)⁻¹; that cofactor over det.
    cofactor = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    if det == 0 or cofactor / det <= 0:
        return None
    stderr_c = (variance * cofactor / det) ** 0.5
    hours = span / 3600.0
    return 2.0 * c * hours, 2.0 * stderr_c * hours


def _segment_rates(pairs: list[tuple[float, float]], parts: int = 3) -> tuple[tuple[float, float], ...]:
    """The rate over consecutive, NON-OVERLAPPING parts of the window.

    Split by TIME, not by sample count, so an uneven write rate cannot make one
    part cover twice the hours of another and look like a change that is really
    a difference in how much was measured.

    Overlapping windows would be worse than useless here: sharing most of their
    samples, their errors are not independent, and comparing them makes a small
    difference look significant. That mistake is easy to make by hand — I made
    it against this very channel before checking.
    """
    if len(pairs) < parts * 4:
        return ()
    start, end = pairs[0][0], pairs[-1][0]
    if end <= start:
        return ()
    width = (end - start) / parts
    out: list[tuple[float, float]] = []
    for index in range(parts):
        lo = start + width * index
        hi = end if index == parts - 1 else start + width * (index + 1)
        # HALF-OPEN, so a sample sitting exactly on an internal boundary lands
        # in one part and not in both. Sharing it makes the parts' errors
        # correlated — the very thing this docstring promises they are not —
        # and lets one boundary outlier bend two of the three rates.
        if index == parts - 1:
            chunk = [pair for pair in pairs if lo <= pair[0] <= hi]
        else:
            chunk = [pair for pair in pairs if lo <= pair[0] < hi]
        fitted = _fit_rate(chunk)
        if fitted is None:
            return ()
        out.append(fitted)
    return tuple(out)


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
                    "limit_per_channel": _TREND_POINT_BUDGET,
                    # BUY THE WINDOW. Ten thousand rows against a channel
                    # written every two seconds reach back five and a half
                    # hours, so a six-hour request came back covering 5.6 and a
                    # twenty-four-hour request would have come back covering the
                    # same 5.6. The assistant told an operator "+0.1/ч за 5.6 ч"
                    # and, asked whether the rate was decaying, could not say —
                    # it had no window long enough to hold an answer. Bucketing
                    # returns the newest real sample per bucket, never an
                    # average, so the span is honest and the values are real.
                    "bucket_s": _trend_bucket(window_minutes),
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
        # THE CURRENT REGIME, NOT THE WHOLE WINDOW. Everything above describes
        # the window as asked for; the shape below describes only what has held
        # since the last change, because that is the stretch whose beginning
        # carries the answer.
        split = _regime_start(pairs)
        regime = pairs[split:] if split is not None else pairs
        regime_hours = (regime[-1][0] - regime[0][0]) / 3600.0 if len(regime) > 1 else None
        return ChannelTrend(
            channel=channel,
            window_minutes=window_minutes,
            n_samples=len(pairs),
            first_value=ys[0],
            last_value=ys[-1],
            span_s=span_s,
            rate_per_hour=slope_per_s * 3600.0,
            slope_stderr_per_hour=slope_stderr_per_s * 3600.0,
            segments=_segment_rates(pairs),
            slope_change=_centred_quadratic(pairs),
            regime_hours=regime_hours,
            shape=_shape_of_rise(regime),
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
