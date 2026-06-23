"""Tests for PreFlightDialog — pre-experiment readiness checklist."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.preflight_dialog import PreFlightDialog


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
    """Dialog creates, has expected title, loading label, disabled start, initial checks."""
    dialog = _make_dialog(monkeypatch)
    assert dialog is not None
    assert dialog.windowTitle() == "Проверка готовности к эксперименту"
    # Loading label hidden after checks complete (all 3 async + disk done)
    assert not dialog._loading_label.isVisible()
    # Start button must exist
    assert dialog._start_btn is not None
    # At least the named checks were populated
    check_names = {c.name for c in dialog._checks}
    assert "Engine подключён" in check_names
    assert "Тревоги" in check_names


def test_checks_list_not_empty(monkeypatch) -> None:
    """Required named checks (safety/disk/alarm) are rendered with statuses."""
    dialog = _make_dialog(monkeypatch)
    # Named required checks must be present
    check_names = {c.name for c in dialog._checks}
    assert "Engine подключён" in check_names, "safety connectivity check missing"
    assert "Тревоги" in check_names, "alarm check missing"
    # Every check must have a valid status
    for c in dialog._checks:
        assert c.status in ("ok", "warning", "error"), f"invalid status {c.status!r} for {c.name}"
    # Summary must be set after checks complete
    assert dialog._summary_label.text() != ""
    # Start button state follows the check results: default safety ok + no alarms → enabled
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_error_disables_start(monkeypatch) -> None:
    """Engine недоступен → error check rendered + failure summary + start disabled."""
    dialog = _make_dialog(monkeypatch, safety_result={"ok": False, "error": "timeout"})
    # Checks must have completed (not still pending)
    assert dialog._pending_checks == 0, (
        f"Checks not complete: _pending_checks={dialog._pending_checks}"
    )
    # At least one error check must exist
    error_checks = [c for c in dialog._checks if c.status == "error"]
    assert len(error_checks) >= 1, (
        f"No error checks found; all checks: {[(c.name, c.status) for c in dialog._checks]}"
    )
    # The engine-connectivity check must be the error
    engine_check = next((c for c in dialog._checks if c.name == "Engine подключён"), None)
    assert engine_check is not None, "Engine подключён check missing"
    assert engine_check.status == "error"
    # Summary must reflect errors
    assert "ошибки" in dialog._summary_label.text().lower() or "❌" in dialog._summary_label.text()
    # Start must be disabled BECAUSE of the error (not merely by default)
    assert dialog._start_btn is not None
    assert not dialog._start_btn.isEnabled()


def test_all_ok_enables_start(monkeypatch) -> None:
    """Successful safety/alarm responses through real async path → start enabled."""
    # _make_dialog drives the real ZmqCommandWorker path with:
    #   safety_status → ok, state=safe_off
    #   alarm_v2_status → ok, active={}
    #   get_sensor_diagnostics → ok=False (→ warning, not error)
    dialog = _make_dialog(monkeypatch)
    # Checks completed
    assert dialog._pending_checks == 0
    # No error checks
    error_checks = [c for c in dialog._checks if c.status == "error"]
    assert len(error_checks) == 0, (
        f"Unexpected errors: {[(c.name, c.status, c.detail) for c in error_checks]}"
    )
    # Summary indicates ready or warnings-only
    summary = dialog._summary_label.text()
    assert "✅" in summary or "⚠️" in summary
    # Start must be enabled
    assert dialog._start_btn is not None
    assert dialog._start_btn.isEnabled()


def test_warnings_allow_start(monkeypatch) -> None:
    """Active alarms → warning via real alarm path → start still enabled."""
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
    # Checks completed
    assert dialog._pending_checks == 0
    # Alarm check must be a warning
    alarm_check = next((c for c in dialog._checks if c.name == "Тревоги"), None)
    assert alarm_check is not None, "Alarm check not found"
    assert alarm_check.status == "warning"
    # Summary shows warnings
    summary = dialog._summary_label.text()
    assert "⚠️" in summary or "предупреждения" in summary.lower()
    # Start must be enabled despite warnings
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
    alarm_checks = [c for c in dialog._checks if c.name == "Тревоги"]
    assert len(alarm_checks) == 1
    assert alarm_checks[0].status == "warning"
