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


# --- what the second reviewer found ----------------------------------------


def _concatenate(*pieces) -> list[tuple[float, float]]:
    """Segments laid end to end, each continuing from the last one's value."""

    out: list[tuple[float, float]] = []
    clock = 0.0
    for fn, hours in pieces:
        base = out[-1][1] if out else 0.0
        for i in range(int(hours * 3600 / _STEP)):
            out.append((clock, base + fn(i * _STEP / 3600.0)))
            clock += _STEP
    return out


def test_the_regime_is_the_last_change_not_the_clearest_one() -> None:
    """A single best split answers the wrong question.

    Over "plateau, rise, plateau" the most prominent break is the START of the
    rise, so the current regime was reported as beginning there — and then
    spanned two physical regimes, whose combined shape looks like one steady
    flow. What is wanted is the most recent change, which is where the current
    regime actually began.
    """

    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import _last_regime_start

    series = _concatenate(
        (lambda h: 0.0, 6.0),
        (lambda h: 0.105 * h, 20.0),
        (lambda h: 0.0, 4.0),
    )
    split = _last_regime_start(series)

    assert split is not None
    hours = series[split][0] / 3600.0
    assert abs(hours - 26.0) < 1.5, (
        f"the regime was placed at {hours:.1f} h, which is the start of the rise "
        f"rather than the plateau that followed it"
    )


async def test_a_falling_pressure_has_no_shape_of_a_rise() -> None:
    """The pump working is not a leak signature.

    The three laws describe a source filling a closed volume. On a FALLING
    series a straight line beats sqrt and log by enormous factors simply
    because nothing is depleting — measured at 70x and 172x on a gentle
    pump-down. The formatter calls that "форма подъёма" and the prompt reads a
    straight line as constant inflow, so the agent would report the signature
    of a leak while the pressure fell.
    """

    from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
    from cryodaq.agents.assistant.query.agent import _format_trends

    falling = _concatenate((lambda h: 0.0, 6.0), (lambda h: -0.1 * h, 18.0))
    pairs = [[t, 3.0 + v] for t, v in falling]

    class _Client:
        async def call(self, _cmd: dict) -> dict:
            return {"ok": True, "data": {"VSP63D_1/pressure": pairs}}

    trend = await SQLiteAdapter(_Client()).trend("VSP63D_1/pressure", 1440)

    assert trend is not None and trend.available
    assert trend.rate_per_hour < 0.0, "the fixture does not actually fall"
    assert trend.shape is None, "a falling pressure was given the shape of a rise"
    assert "форма подъёма" not in _format_trends({"давление": trend})


@pytest.mark.parametrize(
    "channel, expected",
    [
        ("VSP63D_1/pressure", True),
        ("давление", False),
        ("Т1", False),
        ("Т12 2-я ступень", False),
    ],
)
def test_the_shape_is_only_reported_for_a_pressure(channel: str, expected: bool) -> None:
    """The three laws describe a source filling a closed volume.

    On a temperature they describe nothing — but the formatter printed them for
    any channel with a shape, and the prompt reads a straight line as a flow
    that does not decay. A sensor warming steadily would have been handed to the
    operator wearing the signature of a vacuum leak.
    """

    from cryodaq.agents.assistant.query.agent import _format_trends
    from cryodaq.agents.assistant.query.schemas import ChannelTrend

    trend = ChannelTrend(
        channel=channel,
        window_minutes=1440,
        n_samples=2000,
        first_value=294.0,
        last_value=298.0,
        span_s=20 * 3600,
        rate_per_hour=0.2,
        slope_stderr_per_hour=0.001,
        regime_hours=16.0,
        shape=(0.01, 0.12, 0.30),
    )

    text = _format_trends({channel: trend})

    assert ("форма подъёма" in text) is expected, text[:160]
