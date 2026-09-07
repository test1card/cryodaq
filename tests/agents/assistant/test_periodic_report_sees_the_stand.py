"""The hourly bulletin must see the whole stand, and must always run.

Found by review on 2026-09-07: `build_periodic_report_context` read the
operator log and the sensor-health digest and nothing else, and the template
had no slot for readings. So the most interesting fact on the stand — a
pressure rising at a constant +0.106 mbar/h for seven hours — could not appear
in the assistant's own report unless an alarm happened to fire.

Worse, the report was skipped entirely whenever the log was empty. The log line
read "periodic report skipped (idle: 0 events)" while the gauge climbed. A
quiet log is not a quiet stand.

The first fix replaced the event gate with a movement gate, and the movement
gate was wrong too — it ranked channels by RELATIVE change, which this stand's
constant leak defeats by itself: the leak's relative size shrinks as the
pressure it rides on grows, so the same physical leak would have gone unreported
once the baseline was large enough. Both versions had code taking a judgement
that belongs to the agent.

So: no gate at all. Every hour, every channel, value and rate. The agent reads
them and decides what is worth saying — including that nothing is.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext


async def test_every_channel_is_listed_with_its_value_and_rate() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(
        return_value={
            "VSP63D_1/pressure": [[0.0, 0.60], [3600.0, 0.71]],
            "Т12": [[0.0, 298.60], [3600.0, 298.61]],
            "Т11": [[0.0, 296.63], [3600.0, 296.64]],
        }
    )
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    for channel in ("VSP63D_1/pressure", "Т12", "Т11"):
        assert channel in section, f"{channel} was withheld from the agent"
    assert "+0.11" in section or "+0.110" in section
    assert "держат уровень" not in section, "the section is still summarising for the agent"


async def test_a_steady_channel_is_shown_rather_than_counted() -> None:
    """A channel holding its level is a fact, not a number to be collapsed."""
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"Т12": [[0.0, 298.60], [3600.0, 298.61]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "Т12" in section
    assert "298.6" in section
    assert "ничего не движется" not in section


async def test_a_slow_leak_on_a_large_baseline_is_still_reported() -> None:
    """The regression the relative gate would have caused.

    A week of leaking at 0.105 mbar/h puts the chamber near 18 mbar, where that
    same leak is a 0.58%/h rise — under the 1% bar the old gate used. The leak
    has not changed; only the number it rides on has.
    """
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"VSP63D_1/pressure": [[0.0, 18.00], [3600.0, 18.105]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "VSP63D_1/pressure" in section, "the leak went quiet because the baseline grew"
    assert "+0.105" in section


async def test_an_unavailable_history_does_not_cost_the_report() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(side_effect=RuntimeError("engine busy"))
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "недоступны" in section
    assert "engine busy" in section


async def test_an_empty_window_says_so_rather_than_inventing() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={})
    builder = ContextBuilder(reader, experiment_manager=None)

    assert "показаний за окно нет" in await builder._build_readings_section(60)


def test_the_template_dict_carries_the_section() -> None:
    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id="exp",
        active_experiment_phase="preparation",
        readings_section="VSP63D_1/pressure: 0.757 (+0.106/ч за 6.0 ч)",
    )
    assert "readings_section" in ctx.to_template_dict()
    assert "0.106" in ctx.to_template_dict()["readings_section"]
