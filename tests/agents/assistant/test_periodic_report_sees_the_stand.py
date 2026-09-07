"""The hourly bulletin must be able to mention what the stand is doing.

Found by review on 2026-09-07: `build_periodic_report_context` read the
operator log and the sensor-health digest and nothing else, and the template
had no slot for readings. So the most interesting fact on the stand — a
pressure rising at a constant +0.106 mbar/h for seven hours — could not appear
in the assistant's own report unless an alarm happened to fire.

Worse, the report was skipped entirely whenever the log was empty. The log line
read "periodic report skipped (idle: 0 events)" while the gauge climbed. A
quiet log is not a quiet stand.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.agent import _readings_are_moving
from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext


class _Ctx:
    def __init__(self, section: str) -> None:
        self.readings_section = section


def test_a_moving_reading_is_news_even_with_an_empty_log() -> None:
    assert _readings_are_moving(_Ctx("VSP63D_1/pressure: 0.757 (+0.106/ч за 6.0 ч)"))


def test_a_settled_stand_still_skips_the_report() -> None:
    """An assistant that pings on nothing is an assistant that gets muted."""
    assert not _readings_are_moving(_Ctx("ничего не движется: 33 каналов держат уровень за 60 мин"))
    assert not _readings_are_moving(_Ctx("показаний за окно нет"))
    assert not _readings_are_moving(_Ctx("показания недоступны: engine busy"))
    assert not _readings_are_moving(_Ctx(""))


async def test_the_section_names_what_moves_and_counts_what_does_not() -> None:
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

    assert "VSP63D_1/pressure" in section, "the one channel that moved is missing"
    assert "+0.11" in section or "+0.110" in section
    assert "Т12" not in section, "a channel holding its level was listed as news"
    assert "держат уровень" in section


async def test_an_hour_with_nothing_moving_says_so_once() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"Т12": [[0.0, 298.60], [3600.0, 298.61]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "ничего не движется" in section


async def test_an_unavailable_history_does_not_cost_the_report() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(side_effect=RuntimeError("engine busy"))
    builder = ContextBuilder(reader, experiment_manager=None)

    section = await builder._build_readings_section(60)

    assert "недоступны" in section
    assert "engine busy" in section


def test_the_template_dict_carries_the_section() -> None:
    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id="exp",
        active_experiment_phase="preparation",
        readings_section="VSP63D_1/pressure: 0.757 (+0.106/ч за 6.0 ч)",
    )
    assert "readings_section" in ctx.to_template_dict()
    assert "0.106" in ctx.to_template_dict()["readings_section"]
