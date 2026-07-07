"""Sweep-A (A3): steady_state GUI feeds gate on ``reading.is_usable()``.

Where a live ``Reading`` (with status) reaches a ``SteadyStatePredictor``
feed, a finite value carrying an error status must NOT reach ``add_point`` —
the NaN-doctrine makes *status* the discriminator, not float finiteness.

Buffer-replay feeds that see only floats (RThermalLiveWidget) are out of
scope by design and keep their float-finiteness gate.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel
from cryodaq.gui.shell.views.analytics_widgets import (
    CooldownPredictionWidget,
    TemperatureSteadyStateWidget,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _reading(channel: str, value: float, status: ChannelStatus, unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="test",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def test_cooldown_prediction_widget_gates_on_status() -> None:
    _app()
    w = CooldownPredictionWidget()
    # Spy only add_point so the widget's own refresh path keeps working.
    w._ss_predictor.add_point = MagicMock()

    # Finite value, but error status → must NOT reach add_point.
    w.set_cold_temperature_reading(_reading("Т12", 5.0, ChannelStatus.SENSOR_ERROR))
    w._ss_predictor.add_point.assert_not_called()

    # Healthy reading → does reach add_point.
    w.set_cold_temperature_reading(_reading("Т12", 5.0, ChannelStatus.OK))
    w._ss_predictor.add_point.assert_called_once()


def test_temperature_steady_state_widget_gates_on_status() -> None:
    _app()
    w = TemperatureSteadyStateWidget()
    key = w._key_for_short_id("Т12")
    assert key is not None
    w._predictors[key].add_point = MagicMock()

    w.set_temperature_readings({"Т12": _reading("Т12", 5.0, ChannelStatus.SENSOR_ERROR)})
    w._predictors[key].add_point.assert_not_called()

    w.set_temperature_readings({"Т12": _reading("Т12", 5.0, ChannelStatus.OK)})
    w._predictors[key].add_point.assert_called_once()


def test_conductivity_panel_gates_on_status() -> None:
    _app()
    p = ConductivityPanel()
    p._predictor.add_point = MagicMock()
    # Inject a usable channel id so _resolve_channel_id succeeds.
    p._checkboxes["Т1"] = None  # type: ignore[assignment]

    p._handle_reading(_reading("Т1", 5.0, ChannelStatus.SENSOR_ERROR))
    p._predictor.add_point.assert_not_called()

    p._handle_reading(_reading("Т1", 5.0, ChannelStatus.OK))
    p._predictor.add_point.assert_called_once()
