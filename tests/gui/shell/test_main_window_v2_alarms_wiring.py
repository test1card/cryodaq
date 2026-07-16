"""MainWindowV2 wiring for the authoritative v2 alarm overlay."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.overlays.alarm_panel import AlarmPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(window: MainWindowV2) -> None:
    for timer in window.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def test_alarm_panel_is_eager_and_registered():
    _app()
    window = MainWindowV2()
    try:
        assert isinstance(window._alarm_panel, AlarmPanel)
        window._overlay.show_overlay("alarms")
        assert window._overlay.currentWidget() is window._alarm_panel
    finally:
        _stop_timers(window)


def test_tick_mirrors_connection_state_to_alarm_panel(monkeypatch):
    _app()
    window = MainWindowV2()
    try:
        frozen = 100_000.0
        window._last_reading_time = frozen
        monkeypatch.setattr("time.monotonic", lambda: frozen + 0.5)
        window._tick_status()
        assert window._alarm_panel._connected is True
        window._last_reading_time = frozen - 10.0
        monkeypatch.setattr("time.monotonic", lambda: frozen)
        window._tick_status()
        assert window._alarm_panel._connected is False
    finally:
        _stop_timers(window)


def test_v2_count_signal_forwards_to_top_bar():
    app = _app()
    window = MainWindowV2()
    try:
        window._alarm_panel.update_v2_status(
            {
                "ok": True,
                "engine_instance_id": "engine-a",
                "snapshot_revision": 1,
                "active": {
                    "a": {
                        "level": "CRITICAL",
                        "activation_id": "a1",
                        "message": "hot",
                        "channels": ["T11"],
                        "triggered_at": 1.0,
                        "acknowledged": False,
                    },
                    "b": {
                        "level": "WARNING",
                        "activation_id": "b1",
                        "message": "warm",
                        "channels": ["T12"],
                        "triggered_at": 2.0,
                        "acknowledged": False,
                    },
                },
            }
        )
        app.processEvents()
        assert window._alarm_panel.get_active_v2_count() == 2
        assert "2" in window._top_bar._alarms_label.text()
        assert theme.STATUS_FAULT in window._top_bar._alarms_label.styleSheet()
    finally:
        _stop_timers(window)
