"""The hourly summary was computed from a sixth of the hour it was labelled with.

Seen in seven consecutive live reports the operator pasted on 2026-09-08, not in
any test. Each said "Сводка за 60 мин" and, honestly, "за 0.3 ч" — because a row
budget buys however much recent time a channel's write rate lets it. At this
stand's two seconds a sample, four hundred rows reach back thirteen minutes.

The rate the agent derived from that scattered between +0.087 and +0.123 per
hour across consecutive reports, where a twelve-hour least-squares fit gives
+0.1034 ± 0.0016. The stand was not changing; the window was too short to see it.

The engine has supported bucketing since the plots hit exactly this — two series
sharing an X axis disagreeing about where history began — and it returns the
newest REAL sample in each bucket, never an average.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder, _bucket_for


def test_a_bucket_makes_the_budget_cover_the_whole_window() -> None:
    for window in (30, 60, 120, 360):
        bucket = _bucket_for(window, budget=400)
        assert window * 60 / bucket <= 400, f"{window} min at {bucket}s still exceeds the budget"


def test_the_bucket_is_rounded_up() -> None:
    """A bucket a shade too small returns more rows than the budget, and the
    reply is refused outright — which costs the entire section, not a point."""
    assert 3600 / _bucket_for(60, budget=400) <= 400
    assert 3600 / _bucket_for(60, budget=7) <= 7


def test_the_bucket_never_goes_below_the_sampling_interval() -> None:
    """Below it the bucket buys nothing and only coarsens a short window."""
    assert _bucket_for(1, budget=400) >= 2.0
    assert _bucket_for(60, budget=100_000) >= 2.0


async def test_the_readings_section_asks_for_the_window_it_reports() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={})
    builder = ContextBuilder(reader, experiment_manager=None)

    await builder._build_readings_section(60)

    kwargs = reader.read_readings_history.await_args.kwargs
    assert kwargs.get("bucket_s"), "the budget still buys the last N rows, not the hour"
    covered = 3600 / float(kwargs["bucket_s"])
    assert covered <= kwargs["limit_per_channel"], (
        "the requested bucket returns more rows than the budget; the reply is refused"
    )


async def test_the_budget_stays_under_the_readers_hard_cap() -> None:
    """500 is the reader's cap; 600 was refused outright once already, and the
    whole section came back as "показания недоступны"."""
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={})
    builder = ContextBuilder(reader, experiment_manager=None)

    await builder._build_readings_section(60)

    assert reader.read_readings_history.await_args.kwargs["limit_per_channel"] <= 500


async def test_a_reader_that_does_not_understand_buckets_does_not_lose_the_section() -> None:
    """An older engine ignores the field rather than failing; the section must
    still render from whatever window it does get."""
    import time

    now = time.time()
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"VSP63D_1/pressure": [[now - 800, 2.0], [now, 2.02]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "VSP63D_1/pressure" in section
    assert "за 0.2 ч" in section, "the span reported must be the one actually received"
