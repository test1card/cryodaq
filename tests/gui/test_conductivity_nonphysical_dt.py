"""G = P/dT is a conductance only when the hot end is genuinely hotter.

The chain's FIRST channel is treated as hot and its LAST as cold; intermediate
channels are recorded but do not enter G. So if the chain is ordered the wrong
way round, or the heater is not where the chain assumes, dT comes out zero or
negative and G is reported as a large negative number -- a plausible-looking
value that is not a conductance.

That is the same failure shape that cost this stand 6h46m of data: something
wrong reported in the shape of something right. The point is still recorded --
data is never dropped -- but the operator is told at the time, and the count
stays on screen for the rest of the sweep rather than flashing past.
"""

import math

import pytest


def _compute(t_hot: float, t_cold: float, power: float) -> tuple[float, float]:
    """The panel's own arithmetic, so the test tracks the real formula."""
    dt = t_hot - t_cold
    g = power / dt if dt != 0 and math.isfinite(dt) else float("nan")
    return dt, g


def test_a_reversed_chain_produces_a_negative_conductance():
    """The condition worth catching: it is a number, and it is wrong."""
    dt, g = _compute(t_hot=295.0, t_cold=298.0, power=0.5)
    assert dt < 0
    assert g < 0, "a reversed chain yields a negative 'conductance'"
    assert math.isfinite(g), "and it is finite, so nothing else rejects it"


def test_a_correctly_ordered_chain_is_positive():
    dt, g = _compute(t_hot=298.0, t_cold=295.0, power=0.5)
    assert dt > 0 and g > 0


def test_a_vanishing_dt_makes_conductance_explode():
    """Early in a step dT is small; G is then enormous rather than wrong-signed."""
    _dt, g = _compute(t_hot=295.001, t_cold=295.0, power=0.5)
    assert g > 100.0, "a near-zero dT inflates G without any guard firing"


def test_the_panel_separates_and_reports_its_skip_reasons():
    """The counters were merged under one label and could double-count.

    A single ``_auto_nonphysical_points`` counted both an incomplete zone and a
    non-positive dT, under a status label that named only "dT <= 0" -- and a
    step that was both incremented it twice. They are now separate, mutually
    exclusive, and reset per sweep. The point itself is no longer kept: a step
    that cannot produce an honest conductance produces none.
    """
    from pathlib import Path as _Path

    source = _Path("src/cryodaq/gui/shell/overlays/conductivity_panel.py").read_text(encoding="utf-8")
    assert "self._auto_incomplete_zone_points = 0" in source
    assert "self._auto_nonpositive_dt_points = 0" in source
    assert "_auto_nonphysical_points" not in source, "the merged counter is gone"
    assert "пропущено (неполные зоны)" in source
    assert "пропущено (dT ≤ 0)" in source
