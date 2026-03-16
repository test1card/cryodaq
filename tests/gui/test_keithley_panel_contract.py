from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.keithley_panel import KeithleyPanel


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


def test_keithley_panel_exposes_both_channels() -> None:
    _app()
    panel = KeithleyPanel()
    assert set(panel._smu_panels.keys()) == {"smua", "smub"}


def test_smua_reading_updates_only_smua_panel() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(Reading.now(channel="K1/smua/power", value=1.2, unit="W", instrument_id="K1"))

    assert panel._smu_panels["smua"]._value_labels["power"].text() == "1.2"
    assert panel._smu_panels["smub"]._value_labels["power"].text() == "—"


def test_smub_reading_updates_only_smub_panel() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(Reading.now(channel="K1/smub/current", value=0.12, unit="A", instrument_id="K1"))

    assert panel._smu_panels["smub"]._value_labels["current"].text() == "0.12"
    assert panel._smu_panels["smua"]._value_labels["current"].text() == "—"


def test_backend_channel_state_controls_visual_status() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(_channel_state_reading("smua", "on"))
    panel.on_reading(_channel_state_reading("smub", "fault"))

    assert panel._smu_panels["smua"]._state_label.text() == "ВКЛ"
    assert panel._smu_panels["smub"]._state_label.text() == "АВАРИЯ"


def test_command_success_does_not_force_visual_on(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", lambda _payload: {"ok": True})

    panel._smu_panels["smua"]._on_start()

    assert panel._smu_panels["smua"]._state_label.text() == "ВЫКЛ"


def test_zero_readings_do_not_turn_channel_on_without_backend_state() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(Reading.now(channel="K1/smua/power", value=5.0, unit="W", instrument_id="K1"))
    panel.on_reading(Reading.now(channel="K1/smua/current", value=0.1, unit="A", instrument_id="K1"))

    assert panel._smu_panels["smua"]._state_label.text() == "ВЫКЛ"


def test_both_channels_can_be_on_simultaneously_from_backend_state() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(_channel_state_reading("smua", "on"))
    panel.on_reading(_channel_state_reading("smub", "on"))

    assert panel._smu_panels["smua"]._state_label.text() == "ВКЛ"
    assert panel._smu_panels["smub"]._state_label.text() == "ВКЛ"
