from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


class _TrayStub:
    def __init__(self, _window) -> None:
        self.statuses: list[object] = []

    def update(self, status) -> None:
        self.statuses.append(status)


def test_main_window_instantiates_with_calibration_tab(monkeypatch) -> None:
    _app()

    def _fake_archive_send(_payload: dict) -> dict:
        return {"ok": True, "entries": []}

    def _fake_log_send(payload: dict) -> dict:
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_archive_send)
    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_log_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)

    window = MainWindow(_SubscriberStub())

    labels = [window._tabs.tabText(index) for index in range(window._tabs.count())]
    assert "Калибровка" in labels
    assert window._tabs.widget(labels.index("Калибровка")) is window._calibration_panel
    window.close()
    window.deleteLater()


def test_main_window_exposes_expected_tab_set_and_switching(monkeypatch) -> None:
    _app()

    def _fake_archive_send(_payload: dict) -> dict:
        return {"ok": True, "entries": []}

    def _fake_log_send(payload: dict) -> dict:
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_archive_send)
    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_log_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)

    window = MainWindow(_SubscriberStub())

    labels = [window._tabs.tabText(index) for index in range(window._tabs.count())]
    assert labels == [
        "Обзор",
        "Keithley 2604B",
        "Аналитика",
        "Теплопроводность",
        "Автоизмерение",
        "Алармы",
        "Журнал оператора",
        "Архив",
        "Калибровка",
        "Приборы",
    ]
    for index in range(window._tabs.count()):
        window._tabs.setCurrentIndex(index)
        assert window._tabs.currentIndex() == index
    window.close()
    window.deleteLater()


def test_main_window_routes_nonlocalized_temperature_readings_to_calibration(monkeypatch) -> None:
    _app()

    def _fake_archive_send(_payload: dict) -> dict:
        return {"ok": True, "entries": []}

    def _fake_log_send(payload: dict) -> dict:
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_archive_send)
    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_log_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)

    window = MainWindow(_SubscriberStub())
    window._calibration_panel._reference_combo.setCurrentIndex(0)
    window._calibration_panel._targets_table.selectRow(1)

    window._dispatch_reading(
        Reading.now(channel="Stage_A", value=4.2, unit="K", instrument_id="LS218_1")
    )

    assert window._calibration_panel._latest_temperatures["Stage_A"] == 4.2
    window.close()
    window.deleteLater()


def test_main_window_updates_tray_from_backend_truth(monkeypatch) -> None:
    _app()

    def _fake_archive_send(_payload: dict) -> dict:
        return {"ok": True, "entries": []}

    def _fake_log_send(payload: dict) -> dict:
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_archive_send)
    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_log_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)

    window = MainWindow(_SubscriberStub())

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
    window.close()
    window.deleteLater()


def test_main_window_experiment_failures_use_status_bar(monkeypatch) -> None:
    _app()

    def _fake_archive_send(_payload: dict) -> dict:
        return {"ok": True, "entries": []}

    def _fake_log_send(payload: dict) -> dict:
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        return {"ok": True}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_archive_send)
    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_log_send)
    monkeypatch.setattr("cryodaq.gui.main_window.TrayController", _TrayStub)
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.send_command",
        lambda payload: {"ok": False, "error": "experiment backend offline"}
        if payload["cmd"] in {"experiment_templates", "experiment_status"}
        else {"ok": True},
    )

    window = MainWindow(_SubscriberStub())
    window._on_start_experiment()
    assert window.statusBar().currentMessage() == "experiment backend offline"

    window._on_finalize_experiment()
    assert window.statusBar().currentMessage() == "experiment backend offline"
    window.close()
    window.deleteLater()
