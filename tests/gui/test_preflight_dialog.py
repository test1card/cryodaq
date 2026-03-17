"""Tests for PreFlightDialog — pre-experiment readiness checklist."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.preflight_dialog import PreFlightCheck, PreFlightDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_dialog(monkeypatch, safety_result=None, extra_cmds=None):
    """Создать PreFlightDialog с замоканным send_command."""
    _app()

    default_safety = {"ok": True, "state": "SAFE_OFF"}
    safety_resp = safety_result if safety_result is not None else default_safety

    responses = {
        "safety_status": safety_resp,
        "experiment_status": {"ok": True, "instruments": {}},
        "alarm_list": {"ok": True, "alarms": []},
        "readings_snapshot": {"ok": False},
    }
    if extra_cmds:
        responses.update(extra_cmds)

    def _fake_send(payload: dict) -> dict:
        return responses.get(payload.get("cmd", ""), {"ok": False})

    monkeypatch.setattr("cryodaq.gui.widgets.preflight_dialog.send_command", _fake_send)
    return PreFlightDialog()


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
    # Manually set all checks to ok to isolate the logic
    dialog._checks = [
        PreFlightCheck("Engine подключён", "ok", ""),
        PreFlightCheck("Safety state", "ok", "SAFE_OFF"),
        PreFlightCheck("Диск", "ok", "500 ГБ свободно"),
    ]
    dialog._build_ui()
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_warnings_allow_start(monkeypatch) -> None:
    """Только предупреждения → кнопка Начать enabled."""
    dialog = _make_dialog(monkeypatch)
    dialog._checks = [
        PreFlightCheck("Engine подключён", "ok", ""),
        PreFlightCheck("Приборы", "warning", "1 из 2 не отвечает"),
        PreFlightCheck("Диск", "warning", "8.5 ГБ"),
    ]
    dialog._build_ui()
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_fault_state_is_error(monkeypatch) -> None:
    """Safety state FAULT → error check → кнопка disabled."""
    dialog = _make_dialog(
        monkeypatch,
        safety_result={"ok": True, "state": "FAULT_LATCHED"},
    )
    error_checks = [c for c in dialog._checks if c.status == "error"]
    assert len(error_checks) >= 1
    assert not dialog._start_btn.isEnabled()
