"""A step that cannot produce an honest conductance produces none.

_zone_mean drops missing or non-finite members, and the point was published
anyway: a dT computed from ONE surviving sensor per side went into the CSV, the
graph and the summary indistinguishable from a full four-sensor measurement.
A non-positive dT became a finite, plottable "conductance" that is not one.
Both were counted, logged, and kept.

Raw acquisition is untouched -- every temperature and power reading is still
recorded by the engine. What is refused is the DERIVED row, because a number
that cannot be trusted is worse in a result table than a gap.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel  # noqa: E402


@pytest.fixture
def panel():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    p = ConductivityPanel()
    p._auto_confirmed_hot = ("Т1", "Т14")
    p._auto_confirmed_cold = ("Т13", "Т3")
    p._auto_step_temperature_channels = ("Т1", "Т14", "Т13", "Т3")
    p._auto_step_power_value = 0.05
    p._auto_run_writer = _Writer()
    yield p
    # The panel closes its writer on teardown; make that harmless.
    p._auto_run_writer = None


class _Writer:
    """Minimal stand-in: the panel appends points to it and closes it."""

    def __init__(self) -> None:
        self.points: list = []

    def append_point(self, point):
        self.points.append(point)
        return len(self.points)

    def append_binding(self, experiment_id):
        return {}

    def append_terminal(self, *args, **kwargs):
        return {}

    def close(self):
        return None


def _values(**kwargs) -> dict[str, float]:
    base = {"Т1": 307.55, "Т14": 307.45, "Т13": 295.05, "Т3": 294.95}
    base.update(kwargs)
    return base


def test_a_missing_zone_member_publishes_no_point(panel):
    panel._auto_step_temperature_values = _values(Т14=float("nan"))
    before = panel._auto_incomplete_zone_points

    assert panel._auto_record_point() is True, "the sweep continues"

    assert panel._auto_incomplete_zone_points == before + 1
    assert panel._auto_pending_point_result is None, "no G/R point may be published"


def test_a_non_positive_dt_publishes_no_point(panel):
    # Hot and cold swapped: dT <= 0 under power.
    panel._auto_step_temperature_values = {
        "Т1": 295.05, "Т14": 294.95, "Т13": 307.55, "Т3": 307.45,
    }
    before = panel._auto_nonpositive_dt_points

    assert panel._auto_record_point() is True

    assert panel._auto_nonpositive_dt_points == before + 1
    assert panel._auto_pending_point_result is None


def test_the_two_reasons_are_counted_separately(panel):
    panel._auto_step_temperature_values = _values(Т14=float("nan"))
    panel._auto_record_point()

    assert panel._auto_incomplete_zone_points == 1
    assert panel._auto_nonpositive_dt_points == 0, "an incomplete zone is not a dT<=0 report"


def test_one_step_is_never_counted_twice(panel):
    """Incomplete AND inverted at once still counts once."""
    panel._auto_step_temperature_values = {
        "Т1": 295.05, "Т14": float("nan"), "Т13": 307.55, "Т3": 307.45,
    }
    panel._auto_record_point()

    total = panel._auto_incomplete_zone_points + panel._auto_nonpositive_dt_points
    assert total == 1, f"one step, one reason: {total}"


def test_the_operator_is_told_why_the_point_was_skipped(panel):
    panel._auto_step_temperature_values = _values(Т3=float("nan"))
    panel._auto_record_point()

    assert panel._auto_last_skip_reason
    assert "зон" in panel._auto_last_skip_reason


def test_a_complete_step_still_publishes(panel):
    """The containment must not swallow good measurements."""
    panel._auto_step_temperature_values = _values()

    panel._auto_record_point()

    assert panel._auto_incomplete_zone_points == 0
    assert panel._auto_nonpositive_dt_points == 0
    result = panel._auto_pending_point_result
    assert result is not None
    assert math.isclose(result["T_hot"], 307.50, abs_tol=1e-6)
    assert math.isclose(result["T_cold"], 295.00, abs_tol=1e-6)
