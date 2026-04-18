from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.main_window import MainWindow


class _SubscriberStub:
    def __init__(self) -> None:
        self._callback = None


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _process_events(timeout_ms: int = 500) -> None:
    """Process Qt events until workers finish or timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _dispose_window(window: MainWindow) -> None:
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.close()
    window.deleteLater()
    _process_events()


class _TrayStub:
    def __init__(self, _window) -> None:
        self.statuses: list[object] = []

    def update(self, status) -> None:
        self.statuses.append(status)


def _fake_workspace_send(payload: dict) -> dict:
    if payload["cmd"] == "experiment_status":
        return {
            "ok": True,
            "app_mode": "experiment",
            "active_experiment": None,
            "templates": [{"id": "custom", "name": "Custom", "custom_fields": []}],
        }
    if payload["cmd"] == "log_get":
        return {"ok": True, "entries": []}
    return {"ok": True}


def _patch_all_sends(monkeypatch) -> None:
    """Patch send_command at the zmq_client level (used by ZmqCommandWorker) and
    at the widget module level (used by blocking calls like refresh_state)."""
    monkeypatch.setattr("cryodaq.gui.zmq_client.send_command", _fake_workspace_send)
    monkeypatch.setattr("cryodaq.gui.zmq_client.ZmqCommandWorker.start", lambda self: None)
    monkeypatch.setattr("cryodaq.gui.zmq_client.ZmqCommandWorker.isRunning", lambda self: False)
    monkeypatch.setattr(
        "cryodaq.gui.widgets.experiment_workspace.send_command", _fake_workspace_send
    )
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)


def test_main_window_instantiates_with_calibration_tab(monkeypatch) -> None:
    _app()
    _patch_all_sends(monkeypatch)

    window = MainWindow(_SubscriberStub())
    _process_events()

    labels = [window._tabs.tabText(index) for index in range(window._tabs.count())]
    assert "Калибровка" in labels
    assert window._tabs.widget(labels.index("Калибровка")) is window._calibration_panel
    _dispose_window(window)


def test_main_window_exposes_expected_tab_set_and_switching(monkeypatch) -> None:
    _app()
    _patch_all_sends(monkeypatch)

    window = MainWindow(_SubscriberStub())
    _process_events()

    labels = [window._tabs.tabText(index) for index in range(window._tabs.count())]
    assert labels == [
        "Обзор",
        "Эксперимент",
        "Источник мощности",
        "Аналитика",
        "Теплопроводность",
        "Алармы",
        "Служебный лог",
        "Архив",
        "Калибровка",
        "Приборы",
    ]
    for index in range(window._tabs.count()):
        window._tabs.setCurrentIndex(index)
        assert window._tabs.currentIndex() == index
    _dispose_window(window)


def test_main_window_routes_nonlocalized_temperature_readings_to_calibration(monkeypatch) -> None:
    _app()
    _patch_all_sends(monkeypatch)

    window = MainWindow(_SubscriberStub())
    _process_events()

    # CalibrationPanel v2 routes readings via on_reading()
    window._dispatch_reading(
        Reading.now(channel="Stage_A", value=4.2, unit="K", instrument_id="LS218_1")
    )

    # Verify panel didn't crash on reading (v2 panel handles readings gracefully)
    assert window._calibration_panel._current_mode == "setup"
    _dispose_window(window)


def test_main_window_updates_tray_from_backend_truth(monkeypatch) -> None:
    _app()
    _patch_all_sends(monkeypatch)

    window = MainWindow(_SubscriberStub())
    _process_events()

    window._dispatch_reading(
        Reading.now(
            channel="analytics/safety_state",
            value=1.0,
            unit="",
            instrument_id="safety_manager",
            metadata={"state": "running"},
        )
    )
    window._dispatch_reading(
        Reading.now(
            channel="analytics/alarm_count",
            value=0.0,
            unit="",
            instrument_id="alarm_engine",
        )
    )
    window._connected = True
    window._refresh_tray_status()

    assert window._tray_controller.statuses[-1].level.value == "healthy"
    _dispose_window(window)


def test_main_window_alarm_signal_updates_internal_count(monkeypatch) -> None:
    _app()
    _patch_all_sends(monkeypatch)

    window = MainWindow(_SubscriberStub())
    _process_events()

    window._alarm_panel.v2_alarm_count_changed.emit(3)
    _process_events()

    assert window._alarm_count == 3
    _dispose_window(window)


def test_main_window_experiment_failures_use_status_bar(monkeypatch) -> None:
    _app()

    def _fail_send(payload: dict) -> dict:
        if payload["cmd"] == "experiment_status":
            return {"ok": False, "error": "experiment backend offline"}
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.zmq_client.send_command", _fail_send)
    monkeypatch.setattr("cryodaq.gui.zmq_client.ZmqCommandWorker.start", lambda self: None)
    monkeypatch.setattr("cryodaq.gui.zmq_client.ZmqCommandWorker.isRunning", lambda self: False)
    monkeypatch.setattr("cryodaq.gui.widgets.experiment_workspace.send_command", _fail_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)

    window = MainWindow(_SubscriberStub())
    _process_events()
    window._on_start_experiment()
    assert window.statusBar().currentMessage() == "experiment backend offline"

    window._on_finalize_experiment()
    assert window.statusBar().currentMessage() == "experiment backend offline"
    _dispose_window(window)
