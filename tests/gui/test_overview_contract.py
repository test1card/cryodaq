from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.overview_panel import KeithleyStrip, StatusStrip


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _channel_state_reading(channel: str, state: str) -> Reading:
    return Reading.now(
        channel=f"analytics/keithley_channel_state/{channel}",
        value={"off": 0.0, "on": 1.0, "fault": -1.0}[state],
        unit="",
        instrument_id="safety_manager",
        metadata={"state": state, "channel": channel},
    )


def test_status_strip_accepts_lowercase_safety_state() -> None:
    _app()
    widget = StatusStrip()

    widget.set_safety_state("safe_off")
    assert widget._safety_label.text() == "SAFE_OFF"

    widget.set_safety_state("fault_latched")
    assert widget._safety_label.text() == "FAULT_LATCHED"


def test_keithley_strip_hides_on_lowercase_safe_off() -> None:
    _app()
    widget = KeithleyStrip()
    widget.set_channel_state("smua", "on")
    widget.setVisible(True)

    widget.set_safety_state("safe_off")

    assert not widget.isVisible()


def test_keithley_strip_backend_state_controls_visual_status() -> None:
    _app()
    widget = KeithleyStrip()

    widget.set_channel_state("smua", "on")
    widget.set_channel_state("smub", "fault")

    assert "smua: ВКЛ" in widget._smua_label.text()
    assert "smub: АВАРИЯ" in widget._smub_label.text()


def test_keithley_strip_telemetry_does_not_force_on_state() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=1.0, unit="W", instrument_id="K1"))

    assert "smua: ВЫКЛ" in widget._smua_label.text()


def test_keithley_strip_updates_both_channels_independently() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=1.0, unit="W", instrument_id="K1"))
    widget.on_reading(Reading.now(channel="K1/smub/power", value=2.0, unit="W", instrument_id="K1"))
    widget.set_channel_state("smua", "on")
    widget.set_channel_state("smub", "on")

    assert "P=1.00" in widget._smua_label.text()
    assert "P=2.00" in widget._smub_label.text()


def test_backend_state_off_controls_visual_off_even_with_nonzero_telemetry() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=3.0, unit="W", instrument_id="K1"))
    widget.set_channel_state("smua", "off")

    assert "smua: ВЫКЛ" in widget._smua_label.text()
