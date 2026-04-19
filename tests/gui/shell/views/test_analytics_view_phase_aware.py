"""Phase III.C — phase-aware AnalyticsView layout tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views import analytics_widgets
from cryodaq.gui.shell.views.analytics_view import (
    AnalyticsView,
    CooldownData,
    RThermalData,
)
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


# ----------------------------------------------------------------------
# Layout — initial / per-phase / fallback
# ----------------------------------------------------------------------


def test_initial_layout_uses_fallback(app):
    view = AnalyticsView()
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "temperature_overview"
    assert analytics_widgets.id_of(slots["top_right"]) == "pressure_current"
    assert analytics_widgets.id_of(slots["bottom_right"]) == "sensor_health_summary"


def test_preparation_layout_matches_yaml(app):
    view = AnalyticsView()
    view.set_phase("preparation")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "temperature_overview"
    assert analytics_widgets.id_of(slots["top_right"]) == "pressure_current"
    assert analytics_widgets.id_of(slots["bottom_right"]) == "sensor_health_summary"


def test_vacuum_layout_swaps_main_to_prediction(app):
    view = AnalyticsView()
    view.set_phase("vacuum")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "vacuum_prediction"
    assert analytics_widgets.id_of(slots["top_right"]) == "temperature_overview"
    assert analytics_widgets.id_of(slots["bottom_right"]) == "pressure_current"


def test_cooldown_layout_main_is_cooldown_prediction(app):
    view = AnalyticsView()
    view.set_phase("cooldown")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "cooldown_prediction"


def test_measurement_layout_main_is_r_thermal_live(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "r_thermal_live"
    assert analytics_widgets.id_of(slots["bottom_right"]) == "keithley_power"


def test_disassembly_layout_has_empty_right_slots(app):
    view = AnalyticsView()
    view.set_phase("disassembly")
    slots = view.active_widgets()
    # Main present, right slots None.
    assert analytics_widgets.id_of(slots["main"]) == "experiment_summary"
    assert "top_right" not in slots
    assert "bottom_right" not in slots


def test_unknown_phase_falls_back(app):
    view = AnalyticsView()
    view.set_phase("foo_bar_nonexistent")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "temperature_overview"


def test_teardown_alias_maps_to_disassembly(app):
    view = AnalyticsView()
    view.set_phase("teardown")
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "experiment_summary"


# ----------------------------------------------------------------------
# Widget reuse / disposal
# ----------------------------------------------------------------------


def test_widget_preserved_when_same_id_across_phases(app):
    view = AnalyticsView()
    # Fallback has top_right == pressure_current.
    orig_pressure = view.active_widgets()["top_right"]
    # Preparation reuses top_right == pressure_current.
    view.set_phase("preparation")
    same_pressure = view.active_widgets()["top_right"]
    assert orig_pressure is same_pressure


def test_inactive_widget_discarded_on_phase_change(app):
    view = AnalyticsView()
    view.set_phase("vacuum")
    slots_before = view.active_widgets()
    # vacuum: bottom_right = pressure_current.
    pressure_in_vacuum = slots_before["bottom_right"]
    view.set_phase("measurement")
    slots_after = view.active_widgets()
    # measurement: bottom_right = keithley_power. Pressure gone.
    assert analytics_widgets.id_of(slots_after["bottom_right"]) == "keithley_power"
    assert pressure_in_vacuum is not slots_after["bottom_right"]


def test_set_same_phase_is_noop(app):
    view = AnalyticsView()
    view.set_phase("preparation")
    before = view.active_widgets()
    view.set_phase("preparation")
    after = view.active_widgets()
    # Widget instances unchanged.
    for slot in before:
        assert before[slot] is after[slot]


def test_set_phase_none_returns_to_fallback(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    view.set_phase(None)
    slots = view.active_widgets()
    assert analytics_widgets.id_of(slots["main"]) == "temperature_overview"


# ----------------------------------------------------------------------
# Data forwarding
# ----------------------------------------------------------------------


def test_set_cooldown_forwards_to_cooldown_prediction_widget(app):
    view = AnalyticsView()
    view.set_phase("cooldown")
    data = CooldownData(
        t_hours=4.0,
        ci_hours=0.3,
        phase="phase1",
        progress_pct=42.0,
        actual_trajectory=[(0.0, 295.0), (3600.0, 150.0)],
        predicted_trajectory=[(3600.0, 150.0), (14400.0, 50.0)],
        ci_trajectory=[(3600.0, 148.0, 152.0), (14400.0, 45.0, 55.0)],
    )
    view.set_cooldown(data)
    main = view.active_widgets()["main"]
    inner = getattr(main, "_inner", None)
    assert inner is not None
    # History populated.
    xs, _ = inner._history_curve.getData()
    assert len(xs) == 2


def test_set_r_thermal_forwards_to_live_widget(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    data = RThermalData(
        current_value=2.345,
        delta_per_minute=-0.012,
        last_updated_ts=1000.0,
    )
    view.set_r_thermal(data)
    main = view.active_widgets()["main"]
    assert "2.345" in main._value_label.text()


def test_set_r_thermal_none_shows_dash(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    view.set_r_thermal(None)
    main = view.active_widgets()["main"]
    assert main._value_label.text() == "—"


def test_set_pressure_reading_forwards_to_pressure_widget(app):
    view = AnalyticsView()
    # Fallback has pressure_current in top_right.
    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=1e-5,
        unit="мбар",
        metadata={},
    )
    view.set_pressure_reading(reading)
    pressure_widget = view.active_widgets()["top_right"]
    assert len(pressure_widget._series) == 1


def test_set_instrument_health_forwards_to_sensor_widget(app):
    view = AnalyticsView()
    view.set_instrument_health({"Т1": "OK", "Т2": "WARNING"})
    sensor_widget = view.active_widgets()["bottom_right"]
    assert "Т1" in sensor_widget._chips
    assert "Т2" in sensor_widget._chips


def test_setter_on_widget_without_method_does_not_raise(app):
    """Duck-typing: a setter whose forwarded method nobody implements
    should silently no-op, not crash."""
    view = AnalyticsView()
    # sensor_health_summary has no set_cooldown_data method, yet it is
    # in the fallback bottom_right slot. Calling set_cooldown on view
    # must be safe.
    data = CooldownData(t_hours=1.0, ci_hours=0.1, phase="phase1", progress_pct=10.0)
    view.set_cooldown(data)  # no exception


# ----------------------------------------------------------------------
# Replay on phase swap
# ----------------------------------------------------------------------


def test_phase_swap_does_not_duplicate_samples_in_preserved_widget(app):
    """Regression guard (III.C Codex fix): the preserved append-style
    pressure_current widget must NOT receive a cached-data replay when
    the layout preserves it across a phase swap — otherwise the series
    would duplicate on every phase transition."""
    view = AnalyticsView()
    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=1e-5,
        unit="мбар",
        metadata={},
    )
    view.set_pressure_reading(reading)
    pressure_widget = view.active_widgets()["top_right"]
    before = len(pressure_widget._series)
    assert before == 1
    # Fallback → preparation: top_right stays pressure_current
    # (preserved instance), bottom_right stays sensor_health_summary
    # (preserved), main stays temperature_overview (preserved). No
    # fresh widgets → no replay into preserved instances.
    view.set_phase("preparation")
    assert len(pressure_widget._series) == before


def test_phase_swap_replays_cached_cooldown(app):
    view = AnalyticsView()
    data = CooldownData(
        t_hours=2.0,
        ci_hours=0.2,
        phase="phase1",
        progress_pct=25.0,
        actual_trajectory=[(0.0, 295.0), (600.0, 200.0)],
        predicted_trajectory=[(600.0, 200.0), (3600.0, 100.0)],
        ci_trajectory=[(600.0, 198.0, 202.0), (3600.0, 95.0, 105.0)],
    )
    # Push before the relevant widget is mounted.
    view.set_cooldown(data)
    view.set_phase("cooldown")  # mounts CooldownPredictionWidget
    main = view.active_widgets()["main"]
    xs, _ = main._inner._history_curve.getData()
    assert len(xs) == 2
