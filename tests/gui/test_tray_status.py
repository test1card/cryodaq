from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow

from cryodaq.gui.tray_status import TrayController, TrayLevel, resolve_tray_status


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_resolve_tray_status_marks_fault_on_alarm() -> None:
    status = resolve_tray_status(connected=True, safety_state="running", alarm_count=2)

    assert status.level is TrayLevel.FAULT
    assert "Тревоги: 2" in status.tooltip


def test_resolve_tray_status_marks_warning_on_missing_truth() -> None:
    status = resolve_tray_status(connected=False, safety_state=None, alarm_count=0)

    assert status.level is TrayLevel.WARNING
    assert "Нет полной информации" in status.tooltip


def test_resolve_tray_status_marks_healthy_only_for_known_safe_state() -> None:
    status = resolve_tray_status(connected=True, safety_state="safe_off", alarm_count=0)

    assert status.level is TrayLevel.HEALTHY
    assert "Безопасность: safe_off" in status.tooltip


def test_tray_controller_gracefully_disables_when_tray_unavailable(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.tray_status.QSystemTrayIcon.isSystemTrayAvailable", lambda: False
    )

    controller = TrayController(QMainWindow())

    assert controller.available is False
