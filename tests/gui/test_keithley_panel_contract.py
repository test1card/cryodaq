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
    assert panel._smu_panels["smub"]._value_labels["power"].text() != "1.2"


def test_smub_reading_updates_only_smub_panel() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(Reading.now(channel="K1/smub/current", value=0.12, unit="A", instrument_id="K1"))

    assert panel._smu_panels["smub"]._value_labels["current"].text() == "0.12"
    assert panel._smu_panels["smua"]._value_labels["current"].text() != "0.12"


def test_backend_channel_state_controls_visual_status() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(_channel_state_reading("smua", "on"))
    panel.on_reading(_channel_state_reading("smub", "fault"))

    assert panel._smu_panels["smua"]._channel_state == "on"
    assert panel._smu_panels["smub"]._channel_state == "fault"


def test_command_success_does_not_force_visual_on(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", lambda _payload: {"ok": True})
    initial_label = panel._smu_panels["smua"]._state_label.text()

    panel._smu_panels["smua"]._on_start()

    assert panel._smu_panels["smua"]._channel_state == "off"
    assert panel._smu_panels["smua"]._state_label.text() == initial_label


def test_zero_readings_do_not_turn_channel_on_without_backend_state() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(Reading.now(channel="K1/smua/power", value=5.0, unit="W", instrument_id="K1"))
    panel.on_reading(Reading.now(channel="K1/smua/current", value=0.1, unit="A", instrument_id="K1"))

    assert panel._smu_panels["smua"]._channel_state == "off"


def test_both_channels_can_be_on_simultaneously_from_backend_state() -> None:
    _app()
    panel = KeithleyPanel()

    panel.on_reading(_channel_state_reading("smua", "on"))
    panel.on_reading(_channel_state_reading("smub", "on"))

    assert panel._smu_panels["smua"]._channel_state == "on"
    assert panel._smu_panels["smub"]._channel_state == "on"


def test_command_failure_shows_inline_error(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.keithley_panel.send_command",
        lambda _payload: {"ok": False, "error": "backend unavailable"},
    )

    panel._smu_panels["smua"]._on_start()

    assert panel._smu_panels["smua"]._status_banner.text() == "backend unavailable"
    assert panel._smu_panels["smua"]._channel_state == "off"


def test_command_success_shows_pending_status_without_forcing_state(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", lambda _payload: {"ok": True})

    panel._smu_panels["smua"]._on_start()

    assert "A" in panel._smu_panels["smua"]._status_banner.text()
    assert panel._smu_panels["smua"]._channel_state == "off"


def test_start_validation_blocks_zero_target_without_backend_call(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    called = False

    def _send_command(_payload):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", _send_command)
    panel._smu_panels["smua"]._p_spin.setValue(0.0)

    panel._smu_panels["smua"]._on_start()

    assert called is False
    assert "больше нуля" in panel._smu_panels["smua"]._status_banner.text()
    assert panel._smu_panels["smua"]._channel_state == "off"


def test_start_when_backend_already_on_skips_command(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    called = False

    def _send_command(_payload):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", _send_command)
    panel.on_reading(_channel_state_reading("smua", "on"))

    panel._smu_panels["smua"]._on_start()

    assert called is False
    assert "уже включен" in panel._smu_panels["smua"]._status_banner.text()
    assert panel._smu_panels["smua"]._channel_state == "on"


def test_stop_when_backend_already_off_skips_command(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    called = False

    def _send_command(_payload):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", _send_command)

    panel._smu_panels["smua"]._on_stop()

    assert called is False
    assert "уже выключен" in panel._smu_panels["smua"]._status_banner.text()
    assert panel._smu_panels["smua"]._channel_state == "off"


def test_emergency_failure_shows_inline_error() -> None:
    _app()
    panel = KeithleyPanel()

    panel._smu_panels["smua"]._on_emergency_result({"ok": False, "error": "trip failed"})

    assert panel._smu_panels["smua"]._status_banner.text() == "trip failed"


def test_group_actions_show_panel_level_feedback(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", lambda _payload: {"ok": True})

    panel._on_start_both()

    assert "A+B" in panel._status_banner.text()
    assert panel._smu_panels["smua"]._status_banner.text().strip() == ""
    assert panel._smu_panels["smub"]._status_banner.text().strip() == ""
    assert panel._smu_panels["smua"]._channel_state == "off"
    assert panel._smu_panels["smub"]._channel_state == "off"


def test_group_start_without_dispatch_shows_panel_warning(monkeypatch) -> None:
    _app()
    panel = KeithleyPanel()
    called = False

    def _send_command(_payload):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.keithley_panel.send_command", _send_command)
    panel._smu_panels["smua"]._p_spin.setValue(0.0)
    panel._smu_panels["smub"]._p_spin.setValue(0.0)

    panel._on_start_both()

    assert called is False
    assert "не отправлена" in panel._status_banner.text()
    assert "больше нуля" in panel._smu_panels["smua"]._status_banner.text()
    assert "больше нуля" in panel._smu_panels["smub"]._status_banner.text()
