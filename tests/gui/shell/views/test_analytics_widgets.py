"""Phase III.C — analytics widget registry + individual widget smoke tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views import analytics_widgets as aw
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
    w = aw.TemperatureOverviewWidget()
    readings = {
        "Т1": Reading(
            timestamp=datetime.now(UTC),
            instrument_id="LS218_1",
            channel="Т1",
            value=295.0,
            unit="K",
            metadata={},
        )
    }
    w.set_temperature_readings(readings)
    assert "Т1" in w._curves


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
    assert "1.234" in w._value_label.text()
    assert "+0.050" in w._delta_label.text()


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


@pytest.mark.parametrize(
    "widget_id",
    [
        "r_thermal_placeholder",
        # temperature_trajectory wired in F3-Cycle2 — no longer a PlaceholderCard
        # cooldown_history wired in F3-Cycle3 — no longer a PlaceholderCard
        "experiment_summary",  # F3-Cycle4 still pending
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
