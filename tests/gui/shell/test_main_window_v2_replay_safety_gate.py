"""Fail-closed legacy-shell authority and replay read-only regressions."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.operator_snapshot import SnapshotMode


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


@pytest.mark.parametrize("invalid", [0, 1, None, "true", object()])
def test_main_window_replay_mode_requires_exact_bool_before_owner_anchor(invalid: object) -> None:
    _app()
    anchored: list[MainWindowV2] = []
    with pytest.raises(TypeError, match="replay_mode must be an exact bool"):
        MainWindowV2(replay_mode=invalid, owner_anchor=anchored.append)
    assert anchored == []


def test_owner_anchor_sees_teardown_safe_fields_before_later_construction_failure(
    monkeypatch,
    _isolate_shell_test: int,
) -> None:
    app = _app()
    anchored: list[MainWindowV2] = []

    def shutdown_request() -> None:
        return None

    def fail_build(_window: MainWindowV2) -> None:
        raise RuntimeError("controlled build failure")

    monkeypatch.setattr(MainWindowV2, "_build_ui", fail_build)
    with pytest.raises(RuntimeError, match="controlled build failure"):
        MainWindowV2(
            replay_mode=True,
            owner_anchor=anchored.append,
            shutdown_request=shutdown_request,
        )

    assert len(anchored) == 1
    partial = anchored[0]
    assert partial._replay_mode is True
    assert partial._root_shutdown_request is shutdown_request
    assert partial._status_timer is None
    assert partial._annunciation_controller is None
    assert partial._create_exp_worker is None
    partial.invalidate_descriptor_transport()
    partial.invalidate_descriptor_transport()
    from cryodaq.gui import zmq_client

    zmq_client.revoke_gui_command_worker_admission(_isolate_shell_test)
    assert partial.settle_owned_workers() is True
    assert partial.settle_owned_workers() is True
    _stop(partial)
    partial.deleteLater()
    app.processEvents()


def test_launcher_root_completes_idempotent_shutdown_of_partial_main_window(
    monkeypatch,
    _isolate_shell_test: int,
) -> None:
    app = _app()
    import cryodaq.launcher as launcher

    anchored: list[MainWindowV2] = []

    def fail_build(_window: MainWindowV2) -> None:
        raise RuntimeError("controlled build failure")

    monkeypatch.setattr(MainWindowV2, "_build_ui", fail_build)
    with pytest.raises(RuntimeError, match="controlled build failure"):
        MainWindowV2(replay_mode=True, owner_anchor=anchored.append)
    partial = anchored[0]

    host = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_phase=launcher._ShutdownPhase.RUNNING,
        _shutdown_settled={
            "assistant",
            "engine",
            "bridge_shutdown",
            "safety_worker",
            "bridge_terminal",
            "bridge_registration",
            "soak_artifact",
            "soak_bridge",
        },
        _shutdown_last_errors={},
        _shutdown_attempt_active=False,
        _shutdown_retry_pending=False,
        _shutdown_retry_index=0,
        _shutdown_quiesced=False,
        _shutdown_failure_notified=False,
        _gui_worker_session_epoch=_isolate_shell_test,
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=1,
        _restart_pending=False,
        _assistant_restart_pending=False,
        _stop_engine_down_alarm=lambda: None,
        _invalidate_engine_producer=lambda: None,
        _snapshot_ingress=None,
        _main_window=partial,
        _stop_assistant=lambda: None,
        _stop_engine=lambda: None,
        _bridge=None,
        _safety_worker=None,
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _loop=None,
        _app=SimpleNamespace(quit=lambda: None),
        _tray=None,
    )
    monkeypatch.setattr(launcher.LauncherWindow, "_advance_restart_generation", lambda _host: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_start_shutdown_hold_alarm", lambda _host: None)
    monkeypatch.setattr(launcher.LauncherWindow, "_stop_shutdown_hold_alarm", lambda _host: None)
    monkeypatch.setattr(
        launcher.LauncherWindow,
        "_set_shutdown_tray_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(launcher.LauncherWindow, "_schedule_shutdown_retry", lambda _host: None)

    assert launcher.LauncherWindow._do_shutdown(host) is True
    assert launcher.LauncherWindow._do_shutdown(host) is True
    assert host._shutdown_phase is launcher._ShutdownPhase.COMPLETE

    _stop(partial)
    partial.deleteLater()
    app.processEvents()


def test_launcher_close_during_ui_construction_hold_keeps_only_surface_visible() -> None:
    import cryodaq.launcher as launcher

    calls: list[str] = []
    partial = SimpleNamespace(
        _tray=None,
        hide=lambda: calls.append("hide"),
    )
    event = SimpleNamespace(ignore=lambda: calls.append("ignore"))

    launcher.LauncherWindow.closeEvent(partial, event)

    assert calls == ["ignore"]


def test_real_replay_shell_has_no_live_annunciation_or_alarm_pollers(monkeypatch) -> None:
    app = _app()
    beeps: list[str] = []
    worker_commands: list[dict] = []

    def forbidden_worker(command, **_kwargs):  # noqa: ANN001
        worker_commands.append(dict(command))
        raise AssertionError("replay attempted to construct a live alarm worker")

    monkeypatch.setattr(QApplication, "beep", lambda: beeps.append("beep"))
    monkeypatch.setattr(
        "cryodaq.gui.shell.overlays.alarm_panel.ZmqCommandWorker",
        forbidden_worker,
    )
    window = MainWindowV2(replay_mode=True)
    try:
        assert window._annunciation_controller is None
        assert beeps == []
        assert window._alarm_panel._live_authority is False
        assert window._alarm_panel._live_capable is False
        assert window._alarm_panel._v2_poll_timer is None
        assert window._alarm_panel._cooldown_poll_timer is None

        window._dispatch_reading(_reading())
        window._tick_status()
        assert window._alarm_panel._connected is True
        assert window._alarm_panel._v2_poll_timer is None
        assert window._alarm_panel._cooldown_poll_timer is None
        with pytest.raises(RuntimeError, match="cannot be promoted"):
            window._alarm_panel.set_live_authority(True)
        window._alarm_panel._poll_v2_status()
        window._alarm_panel._poll_cooldown_status()
        app.processEvents()
        assert worker_commands == []
        assert beeps == []
    finally:
        _stop(window)


def test_real_live_shell_annunciation_still_starts_fail_loud(monkeypatch) -> None:
    _app()
    beeps: list[str] = []
    monkeypatch.setattr(QApplication, "beep", lambda: beeps.append("beep"))

    window = MainWindowV2(replay_mode=False)
    try:
        controller = window._annunciation_controller
        assert controller is not None
        assert controller.audible is True
        assert controller.status_state == "unknown"
        assert controller._poll_timer.isActive()
        assert controller._beep_timer.isActive()
        assert beeps == ["beep"]
        assert window._alarm_panel._live_authority is True
    finally:
        _stop(window)


def test_replay_shell_without_controller_completes_shutdown_without_late_live_poll(
    monkeypatch,
    _isolate_shell_test: int,
) -> None:
    from PySide6.QtGui import QCloseEvent

    import cryodaq.gui.zmq_client as zmq_client

    app = _app()
    worker_commands: list[dict] = []

    def forbidden_worker(command, **_kwargs):  # noqa: ANN001
        worker_commands.append(dict(command))
        raise AssertionError("replay shutdown attempted to construct a live alarm worker")

    monkeypatch.setattr(
        "cryodaq.gui.shell.overlays.alarm_panel.ZmqCommandWorker",
        forbidden_worker,
    )
    window = MainWindowV2(replay_mode=True)
    assert window._annunciation_controller is None
    window._dispatch_reading(_reading())
    QTimer.singleShot(0, window._alarm_panel._poll_v2_status)
    zmq_client.revoke_gui_command_worker_admission(_isolate_shell_test)

    event = QCloseEvent()
    window.closeEvent(event)
    app.processEvents()

    assert event.isAccepted()
    assert window._shutting_down is True
    assert worker_commands == []


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


def test_telemetry_safety_state_cannot_enable_source_mutations() -> None:
    _app()
    window = MainWindowV2()
    try:
        window._dispatch_reading(_reading("analytics/safety_state", state="ready"))
        window._ensure_overlay("source")
        panel = window._keithley_panel
        assert panel is not None
        # A telemetry reading is not Safety-owner authority.  The controls
        # remain fail-closed until a coherent typed readiness receipt arrives.
        assert panel._smua_block._start_btn.isEnabled() is False
        assert panel._start_both_btn.isEnabled() is False

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
        for route in ("source", "experiment", "alarms", "log", "multiline"):
            window._on_tool_clicked(route)

        source = window._keithley_panel
        experiment = window._experiment_overlay
        log = window._operator_log_panel
        multiline = window._multiline_panel
        alarm = window._alarm_panel
        assert source is not None and experiment is not None and log is not None and multiline is not None

        assert not source._connected
        assert not source._safety_ready
        assert source._read_only
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
        assert multiline._read_only
        assert multiline._burst_button.isEnabled() is False
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


@pytest.mark.parametrize(
    ("source", "expected_title", "expected_replay"),
    [
        (
            None,
            "CryoDAQ \u2014 \u041a\u0440\u0438\u043e\u0433\u0435\u043d\u043d\u0430\u044f "
            "\u043b\u0430\u0431\u043e\u0440\u0430\u0442\u043e\u0440\u0438\u044f "
            "\u0410\u041a\u0426 \u0424\u0418\u0410\u041d",
            False,
        ),
        (
            Path("C:/evidence/run-17.sqlite"),
            "CryoDAQ \u2014 REPLAY: run-17.sqlite",
            True,
        ),
    ],
)
def test_launcher_runtime_title_and_replay_mode_propagation(
    monkeypatch,
    source: Path | None,
    expected_title: str,
    expected_replay: bool,
) -> None:
    app = _app()
    import cryodaq.launcher as launcher

    bridge = SimpleNamespace(start=lambda: None)
    captures: list[dict[str, object]] = []
    ingress_calls: list[tuple[object, object, SnapshotMode]] = []

    class CapturingMainWindow(QWidget):
        def __init__(  # noqa: ANN001
            self,
            *,
            bridge,
            embedded,
            replay_mode,
            owner_anchor,
            shutdown_request,
        ) -> None:
            super().__init__()
            captures.append(
                {
                    "widget": self,
                    "bridge": bridge,
                    "embedded": embedded,
                    "replay_mode": replay_mode,
                    "shutdown_request": shutdown_request,
                }
            )
            owner_anchor(self)

    def controlled_construction_step(self, phase: str, action):  # noqa: ANN001
        if phase == "bridge_bootstrap":
            self._bridge = bridge
        elif phase == "ui":
            return action()
        return None

    def capture_ingress(actual_bridge, window, *, expected_mode, anchor) -> None:  # noqa: ANN001
        _ = anchor
        ingress_calls.append((actual_bridge, window, expected_mode))

    monkeypatch.setattr(
        launcher,
        "_assistant_runtime_decision",
        lambda *, experiment_mode: (False, False),
    )
    monkeypatch.setattr(launcher, "open_gui_command_worker_admission", lambda: 1)
    monkeypatch.setattr(launcher, "MainWindow", CapturingMainWindow)
    monkeypatch.setattr(launcher, "start_operator_snapshot_ingress", capture_ingress)
    monkeypatch.setattr(
        launcher.LauncherWindow,
        "_run_construction_step",
        controlled_construction_step,
    )
    monkeypatch.setattr(
        launcher.LauncherWindow,
        "_publish_replay_ui_authority",
        lambda self: None,
    )
    monkeypatch.setattr(
        launcher.LauncherWindow,
        "_merge_main_window_menus",
        lambda self: None,
    )
    monkeypatch.setattr(
        launcher.LauncherWindow,
        "_build_settings_menu",
        lambda self: None,
    )

    window = launcher.LauncherWindow(app, replay_source=source)
    window._tray = SimpleNamespace(isVisible=lambda: False)
    try:
        assert window.windowTitle() == expected_title
        assert len(captures) == 1
        captured = captures[0]
        assert captured["bridge"] is bridge
        assert captured["embedded"] is True
        assert captured["replay_mode"] is expected_replay
        assert callable(captured["shutdown_request"])
        assert window._main_window is captured["widget"]
        assert ingress_calls == [
            (
                bridge,
                captured["widget"],
                SnapshotMode.REPLAY if expected_replay else SnapshotMode.LIVE,
            )
        ]
    finally:
        window.deleteLater()
        app.processEvents()
