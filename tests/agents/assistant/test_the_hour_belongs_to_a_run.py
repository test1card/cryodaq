"""An hour is a different fact on day one than on day eight.

The operator asked for the hourly summary "в контексте всего эксперимента". The
agent had the hour and a fixed twenty-four-hour window, and this run began on
31 August — so it was shown one eighth of the experiment with no way to know
what it was missing. "Давление выросло на 0.1 за час" means one thing on the
first morning of a run and another on its eighth day.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.context_builder import (
    ContextBuilder,
    _describe_run,
    _humanise_hours,
    _run_started_at,
)


class _Manager:
    def __init__(self, phases, phase="preparation", name="карбид кремния", exp="6ce6"):
        self._phases = phases
        self._phase = phase
        self.active_experiment_name = name
        self.active_experiment_id = exp

    def get_current_phase(self):
        return self._phase

    def get_phase_history(self):
        return self._phases


def _phase(name: str, ago_hours: float) -> dict:
    return {
        "phase": name,
        "started_at": (datetime.now(UTC) - timedelta(hours=ago_hours)).isoformat(),
    }


# --- the framing ------------------------------------------------------------


def test_the_run_says_what_it_is_and_how_long_it_has_gone() -> None:
    em = _Manager([_phase("preparation", 192.0), _phase("vacuum", 100.0), _phase("preparation", 23.2)])

    described = _describe_run(em, _run_started_at(em))

    assert "карбид кремния" in described
    assert "8 сут" in described, described
    assert "фаза preparation" in described
    assert "в ней 23" in described


def test_the_phases_are_listed_in_order_without_repeats() -> None:
    em = _Manager(
        [
            _phase("preparation", 192.0),
            _phase("preparation", 191.0),
            _phase("vacuum", 100.0),
            _phase("cooldown", 60.0),
            _phase("preparation", 23.0),
        ]
    )

    described = _describe_run(em, _run_started_at(em))

    assert "preparation → vacuum → cooldown → preparation" in described


def test_no_run_says_so_rather_than_inventing_one() -> None:
    class _None:
        active_experiment_name = None
        active_experiment_id = None

        def get_current_phase(self):
            return None

        def get_phase_history(self):
            return []

    assert _describe_run(_None(), None) == "активного эксперимента нет"


def test_a_broken_manager_does_not_cost_the_report() -> None:
    class _Broken:
        active_experiment_name = "что-то"

        def get_current_phase(self):
            raise RuntimeError("нет связи")

        def get_phase_history(self):
            raise RuntimeError("нет связи")

    assert "что-то" in _describe_run(_Broken(), None)
    assert _run_started_at(_Broken()) is None


def test_durations_read_without_arithmetic() -> None:
    assert _humanise_hours(0.5) == "30 мин"
    assert _humanise_hours(3.5) == "3.5 ч"
    assert _humanise_hours(50.0) == "2 сут 2 ч"


# --- the anchors follow the run --------------------------------------------


async def test_a_long_run_is_sampled_across_its_whole_length() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"P": [[0.0, 1.0]]})
    builder = ContextBuilder(reader, experiment_manager=None)
    started = time.time() - 8 * 24 * 3600.0

    await builder._build_history_section(started)

    anchors = [c.kwargs["to_ts"] for c in reader.read_readings_history.await_args_list]
    span_h = (max(anchors) - min(anchors)) / 3600.0
    assert span_h > 24 * 6, f"an eight-day run was sampled across only {span_h / 24:.1f} days"


async def test_a_short_run_keeps_the_recent_anchors() -> None:
    """Fractions of a four-hour run would crowd into the same few minutes."""
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"P": [[0.0, 1.0]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    await builder._build_history_section(time.time() - 4 * 3600.0)

    anchors = [c.kwargs["to_ts"] for c in reader.read_readings_history.await_args_list]
    span_h = (max(anchors) - min(anchors)) / 3600.0
    assert 20.0 < span_h < 30.0, f"expected the fixed day anchors, got {span_h:.1f} h"


async def test_no_run_keeps_the_recent_anchors() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={"P": [[0.0, 1.0]]})
    builder = ContextBuilder(reader, experiment_manager=None)

    await builder._build_history_section(None)

    anchors = [c.kwargs["to_ts"] for c in reader.read_readings_history.await_args_list]
    assert 20.0 < (max(anchors) - min(anchors)) / 3600.0 < 30.0


# --- it reaches the model ---------------------------------------------------


def test_the_prompt_shows_the_run_and_asks_for_the_hour_against_it() -> None:
    from cryodaq.agents.assistant.live.context_builder import PeriodicReportContext
    from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM, PERIODIC_REPORT_USER

    assert "{run_section}" in PERIODIC_REPORT_USER, "the run never reaches the model"
    assert "ЧАС — ЭТО ЧАС ЧЕГО-ТО" in PERIODIC_REPORT_SYSTEM

    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id="6ce6",
        active_experiment_phase="preparation",
        run_section="карбид кремния; идёт 8 сут",
    )
    rendered = PERIODIC_REPORT_USER.format(**ctx.to_template_dict(), window_minutes=60)
    assert "идёт 8 сут" in rendered


async def test_the_context_builder_actually_fills_the_run_section() -> None:
    """Written after a negative control failed to fail, for the third time.

    Every other test here calls `_describe_run` directly or checks the prompt,
    so replacing the builder's call with a constant left them all green. The
    defect would have been in the one line nothing exercised.
    """
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value={})
    reader.get_operator_log = AsyncMock(return_value=[])
    em = _Manager([_phase("preparation", 192.0), _phase("vacuum", 40.0)], phase="vacuum")

    ctx = await ContextBuilder(reader, em).build_periodic_report_context(window_minutes=60)

    assert "карбид кремния" in ctx.run_section, ctx.run_section
    assert "сут" in ctx.run_section, "the run's age never reached the context"
    assert "фаза vacuum" in ctx.run_section
