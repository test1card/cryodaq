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
    view.set_phase(None)  # new contract: layout applied on first set_phase call
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


def test_measurement_layout_main_is_temperature_steady_state(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    slots = view.active_widgets()
    # v0.55.6.1: temperature_steady_state replaces r_thermal_live as the
    # measurement-phase headline (architect 2026-05-07: «в фазе измерения
    # до сих пор R, а не прогноз по температуре»). R_thermal demoted to
    # top_right, temperature_overview occupies bottom_right.
    assert analytics_widgets.id_of(slots["main"]) == "temperature_steady_state"
    assert analytics_widgets.id_of(slots["top_right"]) == "r_thermal_live"
    assert analytics_widgets.id_of(slots["bottom_right"]) == "temperature_overview"


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
    view.set_phase(None)  # new contract: layout applied on first set_phase call
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
    # v0.55.6.1: measurement bottom_right is now temperature_overview
    # (was r_thermal_placeholder pre-v0.55.6.1; was keithley_power
    # before v0.55.2 A2).
    assert analytics_widgets.id_of(slots_after["bottom_right"]) == "temperature_overview"
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
    # v0.55+ contract: CooldownData.actual_trajectory is empty by design (cold-
    # stage readings flow via set_cold_temperature_reading). set_cooldown forwards
    # predicted_trajectory → set_prediction → central curve, and ci_trajectory →
    # lower/upper bands. Assert the actual values, not just point count, so a
    # wrong/swapped trajectory or dropped CI band would be caught.
    cx, cy = inner._central_curve.getData()
    assert list(cx) == [3600.0, 14400.0]
    assert list(cy) == [150.0, 50.0]
    _, ly = inner._lower_curve.getData()
    assert list(ly) == [148.0, 45.0]
    _, uy = inner._upper_curve.getData()
    assert list(uy) == [152.0, 55.0]


def test_set_r_thermal_forwards_to_live_widget(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    data = RThermalData(
        current_value=2.345,
        delta_per_minute=-0.012,
        last_updated_ts=1000.0,
    )
    view.set_r_thermal(data)
    # v0.55.6.1 — r_thermal_live moved from main to top_right when
    # temperature_steady_state took the headline slot.
    r_thermal = view.active_widgets()["top_right"]
    assert "2.345" in r_thermal._value_label.text()


def test_set_r_thermal_none_shows_dash(app):
    view = AnalyticsView()
    view.set_phase("measurement")
    view.set_r_thermal(None)
    # v0.55.6.1 — r_thermal_live is the top_right widget in measurement.
    r_thermal = view.active_widgets()["top_right"]
    assert r_thermal._value_label.text() == "—"


def test_set_pressure_reading_forwards_to_pressure_widget(app):
    # MED: assert stored (ts, value) pair + PressurePlot rendered series,
    # not just len(_series)==1.
    view = AnalyticsView()
    view.set_phase(None)  # new contract: layout applied on first set_phase call
    # Fallback has pressure_current in top_right.
    ts_dt = datetime(2026, 4, 15, 10, 30, 0, tzinfo=UTC)
    reading = Reading(
        timestamp=ts_dt,
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=1e-5,
        unit="мбар",
        metadata={},
    )
    view.set_pressure_reading(reading)
    pressure_widget = view.active_widgets()["top_right"]
    assert len(pressure_widget._series) == 1
    # Assert stored (ts, value) pair is correct.
    stored_ts, stored_val = pressure_widget._series[0]
    assert stored_ts == pytest.approx(ts_dt.timestamp())
    assert stored_val == pytest.approx(1e-5)
    # Assert PressurePlot rendered series reflects the data.
    # PressurePlot clamps values and plots log10 on Y; 1e-5 → -5.0.
    xs, ys = pressure_widget._plot._curve.getData()
    assert xs is not None and len(xs) >= 1
    import math

    assert ys[-1] == pytest.approx(math.log10(1e-5))


def test_set_instrument_health_forwards_to_sensor_widget(app):
    # MED: assert grid labels + SeverityChip rendered state (text/color),
    # not just chip key presence.
    from cryodaq.gui import theme
    from cryodaq.gui.widgets.shared import pressure_plot  # noqa: F401 (ensure import ok)

    view = AnalyticsView()
    view.set_phase(None)  # new contract: layout applied on first set_phase call
    view.set_instrument_health({"Т1": "OK", "Т2": "WARNING"})
    sensor_widget = view.active_widgets()["bottom_right"]
    assert "Т1" in sensor_widget._chips
    assert "Т2" in sensor_widget._chips
    # Grid must have 2 rows (one per sensor, sorted).
    # sorted({"Т1": "OK", "Т2": "WARNING"}) → [("Т1", "OK"), ("Т2", "WARNING")]
    assert sensor_widget._grid.rowCount() == 2
    # Name labels in column 0: find by iterating grid items.
    name_labels = []
    for row in range(sensor_widget._grid.rowCount()):
        item = sensor_widget._grid.itemAtPosition(row, 0)
        if item and item.widget():
            name_labels.append(item.widget().text())
    assert "Т1" in name_labels and "Т2" in name_labels
    # Legacy WARNING is accepted but uses the canonical caution presentation.
    chip_t2 = sensor_widget._chips["Т2"]
    assert theme.STATUS_CAUTION in chip_t2.styleSheet(), (
        f"WARNING chip missing STATUS_CAUTION compatibility color: {chip_t2.styleSheet()!r}"
    )
    assert chip_t2.text() == "ВНИМ"
    # SeverityChip text: "OK" severity falls back to severity[:4] = "OK  "
    # but the chip label for "OK" renders as the raw text since it's not in
    # _SEVERITY_LABELS — check it contains the severity text.
    chip_t1 = sensor_widget._chips["Т1"]
    assert chip_t1.text() != "", "OK chip text must not be empty"


def test_setter_on_widget_without_method_does_not_raise(app):
    """Duck-typing: a setter whose forwarded method nobody implements
    should silently no-op, not crash.
    MED: call set_phase(None) first so fallback layout is actually applied
    (the old test never applied a layout, so it was a guarded pass).
    """
    view = AnalyticsView()
    view.set_phase(None)  # ensure fallback layout is mounted
    # sensor_health_summary (bottom_right) has no set_cooldown method.
    # Calling set_cooldown on view must silently no-op for that widget.
    data = CooldownData(t_hours=1.0, ci_hours=0.1, phase="phase1", progress_pct=10.0)
    view.set_cooldown(data)  # no exception
    # Verify fallback layout is actually active (not just empty).
    slots = view.active_widgets()
    assert "main" in slots and "bottom_right" in slots


# ----------------------------------------------------------------------
# Replay on phase swap
# ----------------------------------------------------------------------


def test_phase_swap_does_not_duplicate_samples_in_preserved_widget(app):
    """Regression guard (III.C): the preserved append-style
    pressure_current widget must NOT receive a cached-data replay when
    the layout preserves it across a phase swap — otherwise the series
    would duplicate on every phase transition."""
    view = AnalyticsView()
    view.set_phase(None)  # new contract: layout applied on first set_phase call
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
    # Cached cooldown must replay on mount with the SAME values that were pushed
    # pre-mount — assert the actual replayed trajectory + CI band, not just count,
    # so a replay that drops/garbles the cached data would be caught.
    cx, cy = main._inner._central_curve.getData()
    assert list(cx) == [600.0, 3600.0]
    assert list(cy) == [200.0, 100.0]
    _, ly = main._inner._lower_curve.getData()
    assert list(ly) == [198.0, 95.0]
    _, uy = main._inner._upper_curve.getData()
    assert list(uy) == [202.0, 105.0]
