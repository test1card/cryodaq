"""A step that cannot produce an honest conductance produces none -- and moves on.

Two separate requirements, and the second is the one that bites hardest.

WHAT IS REFUSED. _zone_mean drops missing members, and the point was published
anyway: a dT from ONE surviving sensor per side entered the CSV, graph and
summary indistinguishable from a full four-sensor measurement, and a
non-positive dT became a finite, plottable "conductance" that is not one. The
qualification is now explicit -- every confirmed member finite, power finite and
strictly positive, dT finite and strictly positive -- because the earlier form
rejected an inverted gradient while letting a zero, negative, NaN or infinite
power fall through into R and G.

WHAT STILL HAPPENS. A skipped step takes the SAME authoritative transition a
persisted one takes, minus the row. An earlier version returned without it,
which left the tick path re-evaluating the same already-stable POWERED step for
ever: the source held that power indefinitely, the counter incremented on every
tick, and the run could not finish without the operator.

Raw acquisition is untouched throughout; the engine still records every reading.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel  # noqa: E402


class _Writer:
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


@pytest.fixture
def panel(monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    p = ConductivityPanel()
    p._auto_confirmed_hot = ("Т1", "Т14")
    p._auto_confirmed_cold = ("Т13", "Т3")
    p._auto_step_temperature_channels = ("Т1", "Т14", "Т13", "Т3")
    p._auto_step_power_channel = "Keithley_1/smub/power"
    p._auto_step_power_value = 0.05
    p._auto_power_list = [0.05, 0.06]
    p._auto_step = 0
    p._auto_run_writer = _Writer()
    p._sent: list = []
    p._completed: list = []
    monkeypatch.setattr(
        ConductivityPanel, "_send_auto_cmd", lambda self, cmd, **kw: (self._sent.append(cmd), True)[1]
    )
    monkeypatch.setattr(ConductivityPanel, "_auto_complete", lambda self: self._completed.append(True))
    yield p
    p._auto_run_writer = None


def _values(**kwargs) -> dict[str, float]:
    base = {"Т1": 307.55, "Т14": 307.45, "Т13": 295.05, "Т3": 294.95}
    base.update(kwargs)
    return base


def _assert_nothing_published(panel) -> None:
    """Every observable output of a point, not just the pending slot."""
    assert panel._auto_run_writer.points == [], "no conductivity row may be appended"
    assert panel._auto_results == [], "no result may enter the table, graph or summary"
    assert panel._auto_pending_point_result is None


# ---------------------------------------------------------------------------
# It refuses, and it advances exactly once
# ---------------------------------------------------------------------------


def test_a_degraded_step_advances_exactly_once_however_often_the_tick_runs(panel):
    """The defect: the source held its power while the counter climbed."""
    panel._auto_step_temperature_values = _values(Т14=float("nan"))

    for _ in range(5):
        panel._auto_record_point()

    assert panel._auto_step == 1, f"one step, one advance: {panel._auto_step}"
    assert panel._auto_incomplete_zone_points == 1, "and one count, not one per tick"
    # Only target commands are counted. The advance invalidates the step's
    # evidence, so the later calls in this loop take the missing-identity path
    # and ask for a stop -- which is what production would do if a tick somehow
    # arrived without fresh readings. In the real tick path _auto_record_point
    # is not reached again until new evidence has settled.
    targets = [cmd for cmd in panel._sent if cmd.get("cmd") == "keithley_set_target"]
    assert len(targets) == 1, f"the next target is commanded exactly once: {targets}"
    assert targets[0]["p_target"] == 0.06
    _assert_nothing_published(panel)


def test_a_degraded_final_step_completes_instead_of_staying_powered(panel):
    panel._auto_step = 1                       # last index of a two-power sweep
    panel._auto_step_temperature_values = _values(Т3=float("nan"))

    panel._auto_record_point()

    assert panel._completed == [True], "the normal completion must run"
    assert panel._sent == [], "no further target after the last step"
    _assert_nothing_published(panel)


# ---------------------------------------------------------------------------
# What disqualifies a step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_power", [0.0, -0.05, float("nan"), float("inf"), float("-inf")])
def test_an_invalid_power_publishes_no_point(panel, bad_power):
    """R = dT/P and G = P/dT are not defined for these."""
    panel._auto_step_power_value = bad_power
    panel._auto_step_temperature_values = _values()

    panel._auto_record_point()

    _assert_nothing_published(panel)
    assert panel._auto_incomplete_zone_points == 1
    assert panel._auto_step == 1


def test_a_missing_zone_member_publishes_no_point(panel):
    panel._auto_step_temperature_values = _values(Т14=float("nan"))
    panel._auto_record_point()
    _assert_nothing_published(panel)
    assert panel._auto_incomplete_zone_points == 1


def test_a_non_positive_dt_publishes_no_point(panel):
    panel._auto_step_temperature_values = {
        "Т1": 295.05, "Т14": 294.95, "Т13": 307.55, "Т3": 307.45,
    }
    panel._auto_record_point()
    _assert_nothing_published(panel)
    assert panel._auto_nonpositive_dt_points == 1


def test_the_two_reasons_are_counted_separately(panel):
    panel._auto_step_temperature_values = _values(Т14=float("nan"))
    panel._auto_record_point()
    assert panel._auto_incomplete_zone_points == 1
    assert panel._auto_nonpositive_dt_points == 0


def test_one_step_is_never_counted_twice(panel):
    """Incomplete AND inverted at once still counts once."""
    panel._auto_step_temperature_values = {
        "Т1": 295.05, "Т14": float("nan"), "Т13": 307.55, "Т3": 307.45,
    }
    panel._auto_record_point()
    assert panel._auto_incomplete_zone_points + panel._auto_nonpositive_dt_points == 1


def test_the_operator_is_told_why(panel):
    panel._auto_step_temperature_values = _values(Т3=float("nan"))
    panel._auto_record_point()
    assert panel._auto_last_skip_reason and "зон" in panel._auto_last_skip_reason


# ---------------------------------------------------------------------------
# And it must not swallow good measurements
# ---------------------------------------------------------------------------


def test_a_qualifying_step_still_publishes(panel):
    panel._auto_step_temperature_values = _values()

    panel._auto_record_point()

    assert panel._auto_incomplete_zone_points == 0
    assert panel._auto_nonpositive_dt_points == 0
    result = panel._auto_pending_point_result
    assert result is not None
    assert math.isclose(result["T_hot"], 307.50, abs_tol=1e-6)
    assert math.isclose(result["T_cold"], 295.00, abs_tol=1e-6)
    assert math.isclose(result["G"], 0.05 / 12.5, rel_tol=1e-9)
