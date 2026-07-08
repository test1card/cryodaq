"""Phase III.C — analytics widget registry + individual widget smoke tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views import analytics_widgets as aw
from cryodaq.gui.shell.views.analytics_widgets import (
    PressureCurrentWidget,
    TemperatureOverviewWidget,
)
from cryodaq.gui.state.time_window import TimeWindow, reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


def test_registry_lists_all_expected_ids(app):
    ids = aw.available_ids()
    for expected in (
        "temperature_overview",
        "vacuum_prediction",
        "cooldown_prediction",
        "r_thermal_live",
        "pressure_current",
        "sensor_health_summary",
        "keithley_power",
        "r_thermal_placeholder",
        "temperature_trajectory",
        "cooldown_history",
        "experiment_summary",
    ):
        assert expected in ids


def test_registry_create_returns_widget_with_id_property(app):
    widget = aw.create("temperature_overview")
    assert widget is not None
    assert aw.id_of(widget) == "temperature_overview"


def test_registry_create_none_returns_none(app):
    assert aw.create(None) is None


def test_registry_create_unknown_raises(app):
    with pytest.raises(KeyError):
        aw.create("not_a_real_widget")


# ----------------------------------------------------------------------
# Individual widgets — construct smoke + setter behaviour
# ----------------------------------------------------------------------


def test_temperature_overview_constructs(app):
    w = aw.TemperatureOverviewWidget()
    assert w._plot is not None


def test_temperature_overview_accepts_readings(app):
    ts = 1_000_000.0
    w = aw.TemperatureOverviewWidget()
    readings = {
        "Т1": Reading(
            timestamp=datetime.fromtimestamp(ts, tz=UTC),
            instrument_id="LS218_1",
            channel="Т1",
            value=295.0,
            unit="K",
            metadata={},
        )
    }
    w.set_temperature_readings(readings)
    assert "Т1" in w._curves
    # Rendered curve must contain the timestamp and value
    xs, ys = w._curves["Т1"].getData()
    assert len(xs) >= 1
    assert ts in [pytest.approx(x, rel=1e-6) for x in xs]
    # The 295.0 value must appear in the ys at the same index
    idx = list(xs).index(min(xs, key=lambda x: abs(x - ts)))
    assert ys[idx] == pytest.approx(295.0, rel=1e-6)


def test_vacuum_prediction_wraps_log_y_prediction(app):
    w = aw.VacuumPredictionWidget()
    inner = w._inner
    assert inner._log_y is True
    assert inner._y_label == "Давление"
    assert inner._y_unit == "мбар"


def test_cooldown_prediction_is_linear_y(app):
    w = aw.CooldownPredictionWidget()
    assert w._inner._log_y is False
    assert w._inner._y_unit == "K"


def test_r_thermal_live_constructs_and_formats(app):
    w = aw.RThermalLiveWidget()
    assert w._value_label.text() == "—"


def test_r_thermal_live_set_data_updates_labels(app):
    from cryodaq.gui.shell.views.analytics_view import RThermalData

    w = aw.RThermalLiveWidget()
    w.set_r_thermal_data(
        RThermalData(current_value=1.234, delta_per_minute=0.05, last_updated_ts=1.0)
    )
    assert w._value_label.text() == "1.234 К/Вт"
    assert w._delta_label.text() == "ΔR / мин: +0.050"


def test_pressure_current_uses_shared_pressure_plot(app):
    from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot

    w = aw.PressureCurrentWidget()
    assert isinstance(w._plot, PressurePlot)


def test_sensor_health_summary_chip_grid(app):
    w = aw.SensorHealthSummaryWidget()
    w.set_instrument_health({"Т1": "OK", "Т2": "WARNING", "Т3": "CRITICAL"})
    assert set(w._chips.keys()) == {"Т1", "Т2", "Т3"}


def test_sensor_health_summary_empty_toggles_label(app):
    w = aw.SensorHealthSummaryWidget()
    assert not w._empty_label.isHidden()
    w.set_instrument_health({"Т1": "OK"})
    assert w._empty_label.isHidden()
    w.set_instrument_health({})
    assert not w._empty_label.isHidden()


def test_keithley_power_smua_smub_grid(app):
    w = aw.KeithleyPowerWidget()
    readings = {
        "Keithley_1/smua/voltage": Reading(
            timestamp=datetime.now(UTC),
            instrument_id="Keithley_1",
            channel="Keithley_1/smua/voltage",
            value=5.0,
            unit="В",
            metadata={},
        ),
        "Keithley_1/smub/power": Reading(
            timestamp=datetime.now(UTC),
            instrument_id="Keithley_1",
            channel="Keithley_1/smub/power",
            value=0.75,
            unit="Вт",
            metadata={},
        ),
    }
    w.set_keithley_readings(readings)
    assert "5" in w._values["A.voltage"].text()
    assert "0.75" in w._values["B.power"].text()


# ----------------------------------------------------------------------
# Placeholder widgets
# ----------------------------------------------------------------------


def test_cooldown_prediction_placeholder_is_pg_textitem(app):
    """CooldownPredictionWidget idle placeholder must be pg.TextItem on the
    plot canvas, not a QLabel above the plot (v0.52.4 UX fix)."""
    import pyqtgraph as pg

    w = aw.CooldownPredictionWidget()
    assert isinstance(w._placeholder, pg.TextItem), (
        "Placeholder must be pg.TextItem, not QLabel — plot should use full vertical space."
    )
    assert w._placeholder.isVisible()


def test_cooldown_prediction_placeholder_hides_on_data(app):
    """Placeholder hides when predicted trajectory arrives."""
    w = aw.CooldownPredictionWidget()
    assert w._placeholder.isVisible()

    data = MagicMock()
    data.actual_trajectory = [(1000.0, 200.0), (2000.0, 100.0)]
    data.predicted_trajectory = [(2000.0, 100.0), (3000.0, 50.0)]
    data.ci_trajectory = [(2000.0, 90.0, 110.0), (3000.0, 40.0, 60.0)]
    w.set_cooldown_data(data)
    assert not w._placeholder.isVisible()


def test_cooldown_prediction_placeholder_shows_when_no_prediction(app):
    """Placeholder re-appears when data arrives with no predicted trajectory."""
    w = aw.CooldownPredictionWidget()
    data = MagicMock()
    data.actual_trajectory = [(1000.0, 200.0)]
    data.predicted_trajectory = []
    data.ci_trajectory = []
    w.set_cooldown_data(data)
    assert w._placeholder.isVisible()


@pytest.mark.parametrize(
    "widget_id",
    [
        "r_thermal_placeholder",
        # temperature_trajectory wired in F3-Cycle2 — no longer a PlaceholderCard
        # cooldown_history wired in F3-Cycle3 — no longer a PlaceholderCard
        # experiment_summary wired in F3-Cycle4 — no longer a PlaceholderCard
    ],
)
def test_placeholder_widget_constructs(app, widget_id):
    w = aw.create(widget_id)
    assert isinstance(w, aw.PlaceholderCard)


def test_temperature_trajectory_is_real_widget_not_placeholder(app):
    """After F3-Cycle2, temperature_trajectory is a TemperatureTrajectoryWidget."""
    from unittest.mock import MagicMock, patch

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = aw.create("temperature_trajectory")
    assert not isinstance(w, aw.PlaceholderCard)
    assert isinstance(w, aw.TemperatureTrajectoryWidget)


def test_cooldown_history_is_real_widget_not_placeholder(app):
    """After F3-Cycle3, cooldown_history is a CooldownHistoryWidget."""
    from unittest.mock import MagicMock, patch

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = aw.create("cooldown_history")
    assert not isinstance(w, aw.PlaceholderCard)
    assert isinstance(w, aw.CooldownHistoryWidget)


def test_experiment_summary_widget_constructs(app):
    w = aw.create("experiment_summary")
    assert isinstance(w, aw.ExperimentSummaryWidget)


# ----------------------------------------------------------------------
# Per-widget time-window selector (v0.52.8)
# ----------------------------------------------------------------------


def test_temperature_overview_has_local_selector_default_1h(app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = TemperatureOverviewWidget()
    assert w._window_selector.get_window() is TimeWindow.HOUR_1


def test_pressure_current_has_local_selector_default_1h(app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = PressureCurrentWidget()
    assert w._window_selector.get_window() is TimeWindow.HOUR_1


def test_temperature_overview_window_change_applies_xrange(app):
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = TemperatureOverviewWidget()
        # Push one fake reading so series exists.
        reading = Reading(
            timestamp=datetime.now(UTC),
            instrument_id="LS218_1",
            channel="Т1",
            value=100.0,
            unit="K",
            metadata={},
        )
        w.set_temperature_readings({"Т1": reading})
        # Change window to HOUR_6 (21600 s).
        w._window_selector.set_window(TimeWindow.HOUR_6)
        pi = w._plot.getPlotItem()
        x_lo, x_hi = pi.getViewBox().viewRange()[0]
        span = x_hi - x_lo
        # Expect span ≈ 21600 s, allow ±10% for autoRange jitter.
        assert 19440 <= span <= 23760, f"Unexpected X span {span} for HOUR_6"


def test_pressure_current_selector_survives_set_series(app):
    """Regression (v0.52.8 FAIL): PressurePlot.set_series() reapplies
    global controller window. Local selector window must be re-applied after
    each set_series call so the operator's choice is not overridden."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = PressureCurrentWidget()
        w._window_selector.set_window(TimeWindow.HOUR_1)
        reading = Reading(
            timestamp=datetime.now(UTC),
            instrument_id="VSP63D_1",
            channel="VSP63D_1/pressure",
            value=1e-6,
            unit="мбар",
            metadata={},
        )
        w.set_pressure_reading(reading)
        pi = w._plot.plot_item.getPlotItem()
        x_lo, x_hi = pi.getViewBox().viewRange()[0]
        span = x_hi - x_lo
        # Expect ≈ 3600 s for HOUR_1 (±10%).
        assert 3240 <= span <= 3960, (
            f"Local HOUR_1 selector overridden by global controller after set_series: span={span}"
        )
