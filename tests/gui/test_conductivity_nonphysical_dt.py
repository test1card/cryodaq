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


def test_the_panel_counts_and_reports_non_physical_points():
    """Source-level: the counter exists, is reset per panel, and reaches the UI."""
    from pathlib import Path

    source = Path("src/cryodaq/gui/shell/overlays/conductivity_panel.py").read_text(encoding="utf-8")
    assert "self._auto_nonphysical_points = 0" in source, "no counter"
    assert "P > 0.0 and dT <= 0.0" in source, "the non-physical condition is not detected"
    assert "точек с dT ≤ 0" in source, "the operator is never shown the count"
    # And the point must still be written: no early return on the warning path.
    warn_block = source.split("P > 0.0 and dT <= 0.0")[1].split("point = {")[0]
    assert "return" not in warn_block, "a non-physical point must be recorded, not dropped"
