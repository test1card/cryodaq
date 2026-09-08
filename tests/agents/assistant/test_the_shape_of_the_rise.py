"""The agent must be able to tell a constant source from a decaying one.

On 2026-09-08 the operator asked whether the pressure rise was outgassing from
the insulation or a leak through a gap. The agent answered, correctly for what
it had, that the mechanism does not separate: its window is a fixed 24 hours
and it was looking at the middle of a rise, where a constant source and a
slowly decaying one are nearly the same line.

They separate in two places, and the agent had neither:

  - the BEGINNING of the rise, where a decaying source is steepest. Twenty
    minutes after the chamber was isolated the rate was already at its full
    0.105 mbar/h and it never decayed;
  - the SHAPE, compared against laws rather than eyeballed. Over the real
    window the straight line leaves a residual thirty times smaller than a
    logarithmic one.
"""

from __future__ import annotations

import math

import pytest

from cryodaq.agents.assistant.query.adapters.sqlite_adapter import (
    _regime_start,
    _shape_of_rise,
)

_STEP = 30.0


def _series(fn, hours: float, start: float = 0.0) -> list[tuple[float, float]]:
    n = int(hours * 3600 / _STEP)
    return [(start + i * _STEP, fn(i * _STEP / 3600.0)) for i in range(n)]


def test_a_flat_stretch_then_a_rise_is_a_change_of_regime() -> None:
    """The stand's own history: pressure held by the pump, then isolated."""

    flat = _series(lambda h: 0.057, hours=6.0)
    rise = _series(lambda h: 0.057 + 0.105 * h, hours=10.0, start=flat[-1][0] + _STEP)
    split = _regime_start(flat + rise)

    assert split is not None, "the isolation was not noticed"
    found = (flat + rise)[split][0]
    assert abs(found - rise[0][0]) < 1800.0, (
        f"regime placed {abs(found - rise[0][0]) / 60:.0f} min from the isolation"
    )


@pytest.mark.parametrize(
    "curve, what",
    [
        (lambda h: 0.09 + 0.105 * h - 0.0000175 * h * h, "the stand's own 3% fall across a day"),
        (lambda h: 0.09 + 0.4 * math.sqrt(h + 0.5), "a pure sqrt rise — a depleting source"),
        (lambda h: 0.09 + 0.4 * math.log(h + 100), "a logarithm whose source is old"),
        (lambda h: 0.09 + 0.02 * h * h, "a rise that accelerates"),
    ],
)
def test_a_smooth_curve_is_never_a_change_of_regime(curve, what: str) -> None:
    """Review's counterexamples, and the reason the criterion needed a third leg.

    Two straight pieces fit ANY bend better than one straight line, wherever the
    cut falls — so a residual test, even with a slope test beside it, called a
    textbook depleting source a change of regime at 6.9 h. From that false start
    the shape then reported the straight line as the better fit: a sqrt rise
    turned into evidence for a leak.

    The break must beat a parabola, which bends without breaking.
    """

    assert _regime_start(_series(curve, hours=24.0)) is None, (
        f"{what} was reported as a change of regime"
    )


def test_a_curve_is_not_a_change_of_regime() -> None:
    """The control that the first version of this failed.

    Two straight pieces always fit a CURVE better than one, so a residual test
    on its own invented a change of regime in the stand's real pressure — which
    falls about 3% across a day — at an hour when nothing had happened.
    """

    # 0.105/h decaying 3% over 30 h, exactly the real shape.
    curved = _series(lambda h: 0.09 + 0.105 * h - 0.0000175 * h * h, hours=30.0)

    assert _regime_start(curved) is None, "gentle curvature was reported as a new regime"


def test_a_constant_source_fits_a_straight_line_best() -> None:
    rise = _series(lambda h: 0.09 + 0.105 * h, hours=30.0)
    linear, root, log = _shape_of_rise(rise)

    assert linear < root and linear < log
    assert log / max(linear, 1e-12) > 5.0, "a straight rise did not stand out from log(t)"


def test_a_depleting_source_fits_a_logarithm_best() -> None:
    """A source that empties as 1/t integrates to log(t). If the agent cannot
    see this it cannot say "desorption" either — the tool has to be able to
    reach both answers, not just the one the stand happens to have.
    """

    decay = _series(lambda h: 0.09 + 0.4 * math.log(h + 0.5), hours=30.0)
    linear, root, log = _shape_of_rise(decay)

    assert log < linear, "a decaying source was fitted better by a straight line"
    assert log < root


def test_the_ratios_are_reported_not_a_verdict() -> None:
    """Three numbers, no word. The reading rule lives in the prompt, where the
    model can weigh it against everything else it knows — the same reason the
    categorical trend verdict was deleted from this schema."""

    rise = _series(lambda h: 0.09 + 0.105 * h, hours=30.0)
    shape = _shape_of_rise(rise)

    assert isinstance(shape, tuple) and len(shape) == 3
    assert all(isinstance(value, float) and math.isfinite(value) for value in shape)


@pytest.mark.parametrize("hours", [0.05, 0.1])
def test_too_short_a_window_says_nothing(hours: float) -> None:
    tiny = _series(lambda h: 0.09 + 0.105 * h, hours=hours)
    assert _regime_start(tiny) is None


# --- the call site, not the helpers ----------------------------------------


async def test_the_adapter_fills_the_shape_and_the_text_shows_it() -> None:
    """Every helper above can be right while nothing reaches the operator.

    Three defects survived today because their tests asserted a helper instead
    of the path that uses it. This drives the adapter and then the formatter.
    """

    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
    from cryodaq.agents.assistant.query.agent import _format_trends

    flat = _series(lambda h: 0.057, hours=8.0)
    rise = _series(lambda h: 0.057 + 0.105 * h, hours=16.0, start=flat[-1][0] + _STEP)
    pairs = [[t, v] for t, v in flat + rise]

    class _Client:
        async def call(self, _cmd: dict) -> dict:
            return {"ok": True, "data": {"VSP63D_1/pressure": pairs}}

    trend = await SQLiteAdapter(_Client()).trend("VSP63D_1/pressure", 1440)

    assert trend is not None and trend.available
    assert trend.shape is not None, "the adapter did not compute the shape"
    assert trend.regime_hours is not None, "the adapter did not find the regime"
    assert abs(trend.regime_hours - 16.0) < 1.0, (
        f"the regime was measured as {trend.regime_hours:.1f} h, not the 16 h that rose"
    )

    text = _format_trends({"давление": trend})

    assert "форма подъёма" in text, "the shape never reached the operator's text"
    assert "режим идёт" in text
    linear, root, log = trend.shape
    assert f"{log / linear:.1f}" in text, "the ratio that answers the question is missing"


async def test_no_observed_beginning_means_no_shape_at_all() -> None:
    """The deepest of review's two blockers.

    The three laws are anchored at the first sample, so they measure the age of
    the SOURCE. A window that opens long after the source started cannot know
    that age: a genuine logarithmic rise begun a hundred hours earlier is very
    nearly straight across one day, and the ratios then said "linear better by
    17x" — a constant flow, the signature of a leak — about a source that is
    plainly depleting.

    There is no fix inside the fit. If the beginning was not seen, the honest
    output is nothing.
    """

    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
    from cryodaq.agents.assistant.query.agent import _format_trends

    old_source = [[t, v] for t, v in _series(lambda h: 0.09 + 0.4 * math.log(h + 100), hours=24.0)]

    class _Client:
        async def call(self, _cmd: dict) -> dict:
            return {"ok": True, "data": {"VSP63D_1/pressure": old_source}}

    trend = await SQLiteAdapter(_Client()).trend("VSP63D_1/pressure", 1440)

    assert trend is not None and trend.available
    assert trend.shape is None, "a shape was reported for a rise whose start was never seen"
    assert trend.regime_hours is None, "the window's length was passed off as the regime's age"
    assert "форма подъёма" not in _format_trends({"давление": trend})
