"""A reading without a derivative cannot answer "куда оно идёт".

On 2026-09-07 the assistant called a pressure that had risen at a
dead-constant +0.106 mbar/h for six hours "стоит на месте". It was not wrong
about the level. `RangeStats` fetches (timestamp, value) pairs and keeps min,
max, mean and std — the timestamps are thrown away, so nothing downstream had
a slope to be right about.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter


def _client(reply: dict) -> AsyncMock:
    client = AsyncMock()
    client.call = AsyncMock(return_value=reply)
    return client


def _ramp(rate_per_hour: float, *, start: float, seconds: int, step: int = 30) -> list[list[float]]:
    return [[float(t), start + rate_per_hour * (t / 3600.0)] for t in range(0, seconds, step)]


async def test_a_steady_ramp_reports_its_rate() -> None:
    """The measured case: +0.106 mbar/h over six hours."""
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": _ramp(0.106, start=0.06, seconds=6 * 3600)}}))

    trend = await adapter.trend("P", 360)

    assert trend is not None and trend.available
    assert trend.rate_per_hour == pytest.approx(0.106, rel=1e-6)
    assert trend.significance is not None and trend.significance > 3
    assert trend.span_hours == pytest.approx(6.0, rel=0.01)


async def test_noise_around_a_level_is_not_movement() -> None:
    """Т12 wobbling by hundredths is stable, and must not be reported as a trend."""
    samples = [[float(t), 298.6 + (0.01 if t % 60 else -0.01)] for t in range(0, 3600, 30)]
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"Т12": samples}}))

    trend = await adapter.trend("Т12", 60)

    assert trend is not None and trend.available
    assert trend.significance is not None and trend.significance < 2


async def test_one_noisy_endpoint_does_not_decide_the_answer() -> None:
    """Least squares, not last-minus-first.

    A flat window whose final sample spikes would read as a steep ramp under
    endpoint arithmetic, which is exactly the reading an operator would act on.
    """
    samples = [[float(t), 1.0] for t in range(0, 3600, 30)]
    samples[-1][1] = 5.0
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": samples}}))

    trend = await adapter.trend("P", 60)

    assert trend is not None and trend.available
    # The number nobody reads is not the test. Review, 2026-09-07: this
    # asserted only that the rate was under half the endpoint difference, and
    # passed while `direction` — the word the operator actually sees — still
    # said "растёт" on the strength of one bad sample.
    assert trend.significance is not None and trend.significance < 2, (
        f"one spike produced a significant-looking slope: rate {trend.rate_per_hour}, "
        f"stderr {trend.slope_stderr_per_hour}, z={trend.significance}"
    )


async def test_a_window_with_no_time_span_has_no_slope() -> None:
    """Every sample at one instant is not a rate of zero — it is no rate."""
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": [[100.0, 1.0], [100.0, 2.0]]}}))

    trend = await adapter.trend("P", 60)

    assert trend is not None and not trend.available
    assert "time span" in (trend.reason or "")
    assert trend.significance is None


async def test_an_unavailable_history_says_why() -> None:
    adapter = SQLiteAdapter(_client({"ok": False, "error": "engine busy"}))

    trend = await adapter.trend("P", 60)

    assert trend is not None and not trend.available
    assert trend.reason


async def test_a_small_drift_in_noise_is_still_a_drift() -> None:
    """The gate must not be deaf, only sober.

    Review, 2026-09-07: the first gate compared the total fitted change against
    ONE SAMPLE's scatter and so ignored how many samples there were. A genuine
    0.03-unit drift across 3600 noisy points — a slope more than five standard
    errors from zero — was reported "стабильно". The standard error of a slope
    falls as the square root of the sample count, and that term was missing.
    """
    import random

    random.seed(7)
    samples = [[float(t), 1.0 + 0.03 * (t / 3600.0) + random.gauss(0, 0.01)] for t in range(3600)]
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": samples}}))

    trend = await adapter.trend("P", 60)

    assert trend is not None and trend.available
    assert trend.rate_per_hour == pytest.approx(0.03, abs=0.005)
    assert trend.significance is not None and trend.significance > 5, "a five-sigma drift did not read as significant"


async def test_pure_noise_is_not_a_drift() -> None:
    """The other half of the same claim, so the gate is not merely permissive."""
    import random

    random.seed(11)
    samples = [[float(t), 1.0 + random.gauss(0, 0.01)] for t in range(3600)]
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": samples}}))

    trend = await adapter.trend("P", 60)

    assert trend is not None and trend.available
    assert trend.significance is not None and trend.significance < 2
