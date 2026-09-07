"""The agent must be able to see a day, not just an hour.

A leak and an outgassing transient are indistinguishable over one hour: both are
a pressure going up. Over twenty-four they are obvious — outgassing decays, a
leak does not. Without the day the agent cannot answer the only question a
pumped-down chamber raises, however good its reasoning is.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder


def _builder(reader) -> ContextBuilder:
    return ContextBuilder(reader, experiment_manager=None)


async def test_the_day_is_sampled_with_to_ts_not_asked_for_as_one_window() -> None:
    """The trap this section exists to avoid.

    `read_readings_history` is ORDER BY timestamp DESC LIMIT n. Asking it for
    "the last 24 hours" returns the newest n points — about forty minutes at
    this cadence — and a rate computed from that would carry a span it does not
    cover. Each anchor must therefore pin `to_ts`.
    """
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"P": [[0.0, 1.0]]})

    await _builder(reader)._build_history_section()

    calls = reader.read_readings_history.await_args_list
    assert calls, "no history was requested at all"
    for call in calls:
        assert "to_ts" in call.kwargs, "an anchor asked for a window instead of a moment"
        span = call.kwargs["to_ts"] - call.kwargs["from_ts"]
        assert span <= 3600.0, f"the anchor box is {span}s wide; it is not a moment"


async def test_every_anchor_across_the_day_is_requested() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"P": [[0.0, 1.0]]})

    await _builder(reader)._build_history_section()

    anchors = [c.kwargs["to_ts"] for c in reader.read_readings_history.await_args_list]
    newest, oldest = max(anchors), min(anchors)
    assert (newest - oldest) / 3600.0 >= 23.0, "the sampled span is under a day"


async def test_a_channel_is_rendered_across_the_anchors() -> None:
    values = iter([0.06, 0.60, 0.95, 1.10, 1.20, 1.26])
    reader = AsyncMock()

    async def _history(**_kwargs):
        return {"VSP63D_1/pressure": [[0.0, next(values)]]}

    reader.read_readings_history = _history

    section = await _builder(reader)._build_history_section()

    assert "VSP63D_1/pressure" in section
    assert "0.06" in section and "1.26" in section
    assert "→" in section, "the anchors were not laid out as a progression"


async def test_one_blind_anchor_does_not_cost_the_whole_day() -> None:
    """A single failed query must lose one column, not the section."""
    calls = {"n": 0}

    async def _history(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("engine busy")
        return {"P": [[0.0, 1.0]]}

    reader = AsyncMock()
    reader.read_readings_history = _history

    section = await _builder(reader)._build_history_section()

    assert "P" in section
    assert "истории за сутки нет" not in section


async def test_a_completely_blind_reader_says_so_rather_than_inventing() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(side_effect=RuntimeError("engine down"))

    assert await _builder(reader)._build_history_section() == "истории за сутки нет"


async def test_a_single_anchor_is_not_rendered_as_a_trend() -> None:
    """One point is a reading, not a shape. It must not imply a progression."""
    calls = {"n": 0}

    async def _history(**_kwargs):
        calls["n"] += 1
        return {"P": [[0.0, 1.0]]} if calls["n"] == 1 else {}

    reader = AsyncMock()
    reader.read_readings_history = _history

    assert await _builder(reader)._build_history_section() == "истории за сутки нет"


def test_the_prompt_actually_receives_the_day() -> None:
    """A section built and never rendered is the bug this repo keeps hitting."""
    from cryodaq.agents.assistant.live.context_builder import PeriodicReportContext
    from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_USER

    assert "{history_section}" in PERIODIC_REPORT_USER, "the day never reaches the model"
    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id=None,
        active_experiment_phase=None,
        history_section="P: 24ч назад 0.06 → сейчас 1.26",
    )
    rendered = PERIODIC_REPORT_USER.format(**ctx.to_template_dict(), window_minutes=60)
    assert "0.06" in rendered and "1.26" in rendered
