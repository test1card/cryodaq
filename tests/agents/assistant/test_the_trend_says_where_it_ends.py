"""A rate computed from yesterday's archive is not a rate about now.

The window is asked for as "the last N minutes"; the archive answers with
whatever it holds. A channel whose persistence stopped answers a 24-hour
request with samples 23 and 22 hours old, and the rate computed from them is
real — it is just not a statement about the present. `ChannelTrend` carried no
time for its last sample, so the dynamics line was printed under a header that
said "прямо сейчас".

The field is an INSTANT, not an age. It held a duration for three rounds of
review and each round found the same defect in a new place: measured at the
request it was short by the query; measured on arrival it was short by however
long the composite then waited for its other channels and by the retrieval that
runs before the line is rendered. Any stored duration is a frozen clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.query import agent as agent_module
from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
from cryodaq.agents.assistant.query.agent import _SNAPSHOT_FRESH_S, _format_trends
from cryodaq.agents.assistant.query.schemas import ChannelTrend

STALE = "это не темп на сейчас"
UNKNOWN = "не считать это темпом на сейчас"


def _client(reply: dict) -> AsyncMock:
    client = AsyncMock()
    client.call = AsyncMock(return_value=reply)
    return client


def _now() -> float:
    return datetime.now(UTC).timestamp()


def _ramp_ending(*, seconds_ago: float, span_s: int, rate_per_hour: float = 0.1) -> list[list[float]]:
    """A ramp whose LAST sample sits `seconds_ago` before now."""
    end = _now() - seconds_ago
    start = end - span_s
    return [[start + t, rate_per_hour * (t / 3600.0)] for t in range(0, span_s + 1, 30)]


def _trend(*, last_ts: object, window_minutes: int = 180) -> ChannelTrend:
    return ChannelTrend(
        channel="P",
        window_minutes=window_minutes,
        n_samples=100,
        first_value=0.0,
        last_value=1.0,
        span_s=window_minutes * 60,
        rate_per_hour=0.1,
        slope_stderr_per_hour=0.001,
        last_sample_ts=last_ts,  # type: ignore[arg-type]
        unit="mbar",
    )


def _aged(seconds: float, **kwargs) -> ChannelTrend:
    return _trend(last_ts=_now() - seconds, **kwargs)


# --- the call site: the adapter must actually record it ---------------------


async def test_the_adapter_records_when_the_last_sample_was() -> None:
    """The load-bearing half. A renderer that formats a timestamp nothing
    supplies would say "unknown" for ever and look like it worked."""
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": _ramp_ending(seconds_ago=20, span_s=3600)}}))

    trend = await adapter.trend("P", 180)

    assert trend is not None and trend.available
    assert trend.last_sample_ts is not None
    assert trend.last_sample_ts == pytest.approx(_now() - 20, abs=5.0)


async def test_an_archive_that_stopped_yesterday_says_so() -> None:
    """sol's probe: samples 23 and 22 hours old came back available, with a
    rate, and nothing saying the data ended a day ago."""
    stale = _ramp_ending(seconds_ago=22 * 3600, span_s=3600)
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": stale}}))

    trend = await adapter.trend("P", 1440)

    assert trend is not None and trend.available
    rendered = _format_trends({"давление": trend})
    assert STALE in rendered
    assert "22.0 ч" in rendered


# --- the clock is read where the sentence is written ------------------------


def test_a_trend_goes_stale_while_it_waits_to_be_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE REASON THIS FIELD IS AN INSTANT.

    Between the adapter returning and this line being written, the composite
    waits for its other channels and the pipeline runs retrieval — minutes. A
    stored age is frozen at the adapter and can never cross the limit; a
    timestamp crosses it on its own.
    """
    trend = _aged(_SNAPSHOT_FRESH_S - 1.0)
    assert STALE not in _format_trends({"P": trend}), "fresh at the moment it was fetched"

    later = _now() + 120.0
    monkeypatch.setattr(agent_module, "_now_s", lambda: later)

    assert STALE in _format_trends({"P": trend}), "the same object, two minutes later"


def test_every_trend_in_one_block_is_aged_against_the_same_moment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clock read per channel lets two trends whose last samples arrived
    together land either side of the limit — a difference made by the loop
    rather than by the data. A constant fake would hide that, so this clock
    JUMPS past the limit on its second reading."""
    base = _now()
    readings = iter([base, base + 120.0, base + 240.0])
    calls = 0

    def moving_clock() -> float:
        nonlocal calls
        calls += 1
        return next(readings)

    monkeypatch.setattr(agent_module, "_now_s", moving_clock)

    same_age = base - (_SNAPSHOT_FRESH_S - 1.0)
    rendered = _format_trends({"A": _trend(last_ts=same_age), "B": _trend(last_ts=same_age)})

    assert calls == 1, f"the clock was read {calls} times for one block"
    assert STALE not in rendered, "one of two identical trends was called stale"
    assert rendered.count("+0.1/ч") == 2


# --- the limit --------------------------------------------------------------


def test_a_long_window_does_not_buy_a_longer_grace() -> None:
    """The length of the history asked for is not a budget for how stale its
    end may be. Scaled by a tenth of the window, the composite's own 24-hour
    request called a trend that stopped 2 h 24 min ago fresh."""
    assert STALE in _format_trends({"P": _aged(2 * 3600, window_minutes=1440)})


def test_the_same_limit_applies_whatever_the_window() -> None:
    for window in (5, 60, 180, 1440):
        assert STALE not in _format_trends({"P": _aged(30.0, window_minutes=window)}), window
        assert STALE in _format_trends({"P": _aged(120.0, window_minutes=window)}), window


def test_a_trend_that_reaches_the_present_carries_no_caveat() -> None:
    """The mark is a warning, not decoration: on current data it must be
    absent, or it stops meaning anything when it appears."""
    assert "[" not in _format_trends({"давление": _aged(20.0)})


# --- failing closed ---------------------------------------------------------


async def test_a_timestamp_from_the_future_is_not_perfect_freshness() -> None:
    """Clamping a negative age at zero turned a clock moved forward into an age
    of 0.0, which reads as current."""
    adapter = SQLiteAdapter(_client({"ok": True, "data": {"P": _ramp_ending(seconds_ago=-3600.0, span_s=1800)}}))

    trend = await adapter.trend("P", 180)

    assert trend is not None and trend.last_sample_ts is not None
    assert UNKNOWN in _format_trends({"P": trend})


@pytest.mark.parametrize(
    ("last_ts", "what"),
    [
        (None, "never populated"),
        (float("nan"), "did not compute"),
        (float("inf"), "not finite"),
        (True, "not a measurement of time"),
        ("1200", "a string that never subtracts"),
        (10**1000, "an int too large to be a float"),
    ],
)
def test_a_timestamp_that_is_not_a_plain_number_fails_closed(last_ts: object, what: str) -> None:
    assert UNKNOWN in _format_trends({"P": _trend(last_ts=last_ts)}), what


def test_an_unavailable_trend_is_not_given_a_freshness_caveat() -> None:
    """It already says it is unavailable; a second caveat on top of that would
    read as though there were a rate to qualify."""
    unavailable = ChannelTrend(
        channel="P",
        window_minutes=180,
        n_samples=0,
        first_value=0.0,
        last_value=0.0,
        span_s=0.0,
        rate_per_hour=0.0,
        available=False,
        stale=True,
        reason="истории за окно нет",
    )

    line = _format_trends({"P": unavailable})

    assert "динамика недоступна" in line
    assert "темп на сейчас" not in line


def test_the_caveat_does_not_disturb_the_numbers_beside_it() -> None:
    line = _format_trends({"P": _aged(22 * 3600, window_minutes=1440)})

    assert "+0.1/ч" in line
    assert "за 24.0 ч" in line
