"""Tests for PreFlightDialog — pre-experiment readiness checklist."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.preflight_dialog import PreFlightCheck, PreFlightDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _process_workers(dialog: PreFlightDialog, timeout_ms: int = 5000) -> None:
    """Process Qt events until all async preflight checks complete."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while dialog._pending_checks > 0 and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _make_dialog(monkeypatch, safety_result=None, extra_cmds=None):
    """Создать PreFlightDialog с замоканным send_command."""
    _app()

    default_safety = {"ok": True, "state": "safe_off"}
    safety_resp = safety_result if safety_result is not None else default_safety

    responses = {
        "safety_status": safety_resp,
        "alarm_v2_status": {"ok": True, "active": {}, "history": []},
        "get_sensor_diagnostics": {"ok": False, "error": "mock"},
    }
    if extra_cmds:
        responses.update(extra_cmds)

    def _fake_send(payload: dict) -> dict:
        return responses.get(payload.get("cmd", ""), {"ok": False, "error": "unknown"})

    # Monkeypatch send_command where ZmqCommandWorker calls it
    monkeypatch.setattr("cryodaq.gui.zmq_client.send_command", _fake_send)
    dialog = PreFlightDialog()
    _process_workers(dialog)
    return dialog


def test_dialog_creates_without_crash(monkeypatch) -> None:
    dialog = _make_dialog(monkeypatch)
    assert dialog is not None


def test_checks_list_not_empty(monkeypatch) -> None:
    dialog = _make_dialog(monkeypatch)
    assert len(dialog._checks) > 0


def test_error_disables_start(monkeypatch) -> None:
    """Engine недоступен → error → кнопка Начать disabled."""
    dialog = _make_dialog(monkeypatch, safety_result={"ok": False, "error": "timeout"})
    assert dialog._start_btn is not None
    assert not dialog._start_btn.isEnabled()


def test_all_ok_enables_start(monkeypatch) -> None:
    """Все проверки ok → кнопка Начать enabled."""
    dialog = _make_dialog(monkeypatch)
    # Manually set all checks to ok and rebuild
    dialog._checks = [
        PreFlightCheck("Engine подключён", "ok", ""),
        PreFlightCheck("Safety state", "ok", "safe_off"),
        PreFlightCheck("Диск", "ok", "500 ГБ свободно"),
    ]
    dialog._rebuild_checks_ui()
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_warnings_allow_start(monkeypatch) -> None:
    """Только предупреждения → кнопка Начать enabled."""
    dialog = _make_dialog(monkeypatch)
    dialog._checks = [
        PreFlightCheck("Engine подключён", "ok", ""),
        PreFlightCheck("Алармы", "warning", "1 активных: test_alarm"),
        PreFlightCheck("Диск", "warning", "8.5 ГБ"),
    ]
    dialog._rebuild_checks_ui()
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_fault_state_is_error(monkeypatch) -> None:
    """Safety state fault_latched → error check → кнопка disabled."""
    dialog = _make_dialog(
        monkeypatch,
        safety_result={"ok": True, "state": "fault_latched"},
    )
    error_checks = [c for c in dialog._checks if c.status == "error"]
    assert len(error_checks) >= 1
    assert not dialog._start_btn.isEnabled()


def test_active_alarms_warning(monkeypatch) -> None:
    """Active alarms → warning check."""
    dialog = _make_dialog(
        monkeypatch,
        extra_cmds={
            "alarm_v2_status": {
                "ok": True,
                "active": {"test_alarm": {"severity": "warning"}},
                "history": [],
            },
        },
    )
    alarm_checks = [c for c in dialog._checks if c.name == "Алармы"]
    assert len(alarm_checks) == 1
    assert alarm_checks[0].status == "warning"
