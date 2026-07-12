"""Fail-closed legacy-shell authority and replay read-only regressions."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop(window: MainWindowV2) -> None:
    for timer in window.findChildren(QTimer):
        timer.stop()


def _reading(channel: str = "Т1", *, state: str | None = None) -> Reading:
    metadata = {} if state is None else {"state": state, "reason": ""}
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="engine",
        channel=channel,
        value=4.2,
        unit="K" if state is None else "",
        metadata=metadata,
    )


def test_source_cold_start_has_no_safety_authority() -> None:
    _app()
    window = MainWindowV2()
    try:
        window._ensure_overlay("source")
        panel = window._keithley_panel
        assert panel is not None
        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled() is False
        assert panel._start_both_btn.isEnabled() is False
        assert "нет авторитетного" in panel._gate_reason_label.text().casefold()
    finally:
        _stop(window)


def test_recent_reading_before_safety_cannot_enable_source() -> None:
    _app()
    window = MainWindowV2()
    try:
        window._dispatch_reading(_reading())
        window._ensure_overlay("source")
        panel = window._keithley_panel
        assert panel is not None and panel._connected
        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled() is False
        assert panel._start_both_btn.isEnabled() is False
    finally:
        _stop(window)


def test_authoritative_live_safety_transition_enables_then_revokes_source() -> None:
    _app()
    window = MainWindowV2()
    try:
        window._dispatch_reading(_reading("analytics/safety_state", state="ready"))
        window._ensure_overlay("source")
        panel = window._keithley_panel
        assert panel is not None
        assert panel._smua_block._start_btn.isEnabled() is True
        assert panel._start_both_btn.isEnabled() is True

        window._dispatch_reading(_reading("analytics/safety_state", state="fault_latched"))
        assert panel._smua_block._start_btn.isEnabled() is False
        assert panel._start_both_btn.isEnabled() is False
    finally:
        _stop(window)


def test_replay_recent_readings_leave_every_mutating_panel_read_only(monkeypatch) -> None:
    _app()
    window = MainWindowV2(replay_mode=True)
    try:
        assert window._top_bar._app_mode == "replay"
        assert window._top_bar._mode_badge.text() == "REPLAY"
        window._top_bar._update_mode_badge("experiment", {"app_mode": "experiment"})
        assert window._top_bar._app_mode == "replay"
        window._dispatch_reading(_reading("analytics/safety_state", state="ready"))
        for route in ("source", "experiment", "alarms", "log"):
            window._on_tool_clicked(route)

        source = window._keithley_panel
        experiment = window._experiment_overlay
        log = window._operator_log_panel
        alarm = window._alarm_panel
        assert source is not None and experiment is not None and log is not None

        assert source._connected and source._safety_ready and source._read_only
        assert source._smua_block._start_btn.isEnabled() is False
        assert source._smua_block._emergency_btn.isEnabled() is False
        assert source._start_both_btn.isEnabled() is False
        assert source._emergency_both_btn.isEnabled() is False
        assert experiment._read_only
        assert experiment._landing_create_btn.isEnabled() is False
        assert experiment._save_btn.isEnabled() is False
        assert experiment._finalize_btn.isEnabled() is False
        assert experiment._more_btn.isEnabled() is False
        assert alarm._read_only
        assert log._read_only
        assert log._submit_btn.isEnabled() is False
        assert log._message_edit.isEnabled() is False
        dashboard = window._overview_panel
        assert dashboard._phase_widget._create_btn.isEnabled() is False
        assert dashboard._phase_widget._back_btn.isEnabled() is False
        assert dashboard._phase_widget._forward_btn.isEnabled() is False
        assert dashboard._phase_widget._jump_combo.isEnabled() is False
        assert dashboard._quick_log._input.isEnabled() is False
        assert dashboard._quick_log._send_btn.isEnabled() is False

        def forbidden_worker(*_args, **_kwargs):
            raise AssertionError("read-only replay attempted to construct a command worker")

        monkeypatch.setattr(
            "cryodaq.gui.shell.overlays.keithley_panel.ZmqCommandWorker",
            forbidden_worker,
        )
        monkeypatch.setattr(
            "cryodaq.gui.shell.overlays.alarm_panel.ZmqCommandWorker",
            forbidden_worker,
        )
        monkeypatch.setattr(
            "cryodaq.gui.shell.overlays.operator_log_panel.ZmqCommandWorker",
            forbidden_worker,
        )
        source._smua_block._on_start_clicked()
        source._on_start_both()
        alarm._acknowledge("alarm")
        alarm._acknowledge_v2("alarm-v2")
        log._message_edit.setPlainText("forbidden")
        log._on_submit_clicked()
        experiment._send_advance("cooldown")
        experiment._on_save_card()
        experiment._on_finalize_clicked()
        dashboard._on_phase_transition_requested("cooldown")
        dashboard._on_log_entry_submitted("forbidden")
    finally:
        _stop(window)


def test_replay_shell_rejects_direct_mutating_routes(monkeypatch) -> None:
    _app()
    window = MainWindowV2(replay_mode=True)
    try:
        calls: list[str] = []
        monkeypatch.setattr(window, "_show_new_experiment_dialog", lambda: calls.append("new"))
        monkeypatch.setattr(window, "_restart_engine", lambda: calls.append("restart"))
        for route in ("new_experiment", "restart_engine", "settings", "calibration"):
            window._on_tool_clicked(route)
        window._on_create_experiment({"name": "forbidden"})
        assert calls == []
        assert window._overlay.current_overlay == "home"
    finally:
        _stop(window)


def test_recent_reading_timestamp_does_not_stand_in_for_safety_authority() -> None:
    _app()
    window = MainWindowV2()
    try:
        window._last_reading_time = time.monotonic()
        window._ensure_overlay("source")
        panel = window._keithley_panel
        assert panel is not None and panel._connected
        assert panel._safety_ready is False
        assert panel._smua_block._start_btn.isEnabled() is False
    finally:
        _stop(window)


def test_launcher_propagates_replay_mode_into_embedded_shell() -> None:
    source = Path("src/cryodaq/launcher.py").read_text(encoding="utf-8")
    assert "replay_mode=self._replay_source is not None" in source
