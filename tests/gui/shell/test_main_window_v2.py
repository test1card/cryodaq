"""Smoke tests for MainWindowV2 (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.operator_components import NavigationIntent
from cryodaq.gui.shell.views.operator_display import OperatorDisplay


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _safety_status(engine_instance_id: str, mock: bool) -> dict[str, object]:
    from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION

    return {
        "ok": True,
        "state": "ready",
        "fault_reason": "",
        "fault_revision": 0,
        "fault_activated_at": 0.0,
        "recovery_reason": "",
        "channels_tracked": 0,
        "keithley_connected": False,
        "active_channels": [],
        "mock": mock,
        "engine_instance_id": engine_instance_id,
        "proto": CLIENT_PROTOCOL_VERSION,
    }


def _stop_timers(w: MainWindowV2) -> None:
    """Stop every QTimer in the window subtree.

    The default Qt cleanup is async and the test fixture would otherwise
    leave periodic timers (TopWatchBar 1 s, AlarmPanel 3 s,
    ExperimentStatusWidget 5 s) firing into subsequent tests, where they
    spawn workers that hit later monkeypatched ``send_command``.
    """
    from PySide6.QtCore import QTimer

    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def test_main_window_v2_constructs_with_shell_components() -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    assert w._top_bar is not None
    assert w._tool_rail is not None
    assert w._bottom_bar is not None
    assert w._overlay is not None
    assert w._overlay.current_overlay == "home"
    assert w._overlay.currentWidget() is w._overview_panel
    assert isinstance(w._operator_display, OperatorDisplay)
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()
    assert w.windowTitle() == "CryoDAQ"


def test_mock_launcher_shell_provenance_survives_connection_and_overlay_changes(monkeypatch) -> None:
    """Exercise the existing launcher shell path, not a shell-only mock API."""
    import cryodaq.launcher as launcher

    app = _app()
    host = QMainWindow()
    host._bridge = object()
    host._main_window = None
    host._mock = True
    host._replay_source = None
    host._do_shutdown = lambda: None
    host._on_open_web = lambda: None
    host._on_restart_engine = lambda: None
    host._merge_main_window_menus = lambda: None
    host._build_settings_menu = lambda: None

    monkeypatch.setattr(
        launcher,
        "start_operator_snapshot_ingress",
        lambda _bridge, _window, *, expected_mode, anchor: anchor(object()),
    )
    launcher.LauncherWindow._build_ui(host)
    shell = host._main_window
    assert shell is not None
    _stop_timers(shell)

    mock_labels = [label for label in shell.findChildren(QLabel) if "MOCK" in label.text()]
    assert "MOCK" in shell.windowTitle()
    assert "имитационные данные" in shell.windowTitle().lower()
    assert "не живые измерения" in shell.windowTitle().lower()
    assert len(mock_labels) == 1
    assert not mock_labels[0].isHidden()

    shell._top_bar.set_engine_state(False)
    shell._overlay.show_overlay("alarms")

    assert shell._overlay.current_overlay == "alarms"
    assert not shell._top_bar.isHidden()
    assert not mock_labels[0].isHidden()
    host.deleteLater()
    app.processEvents()


def test_live_and_replay_shells_do_not_present_mock_data() -> None:
    _app()
    live = MainWindowV2()
    replay = MainWindowV2(replay_mode=True)
    _stop_timers(live)
    _stop_timers(replay)

    assert "MOCK" not in live.windowTitle()
    assert all(label.isHidden() for label in live.findChildren(QLabel) if "MOCK" in label.text())
    assert "MOCK" not in replay.windowTitle()
    assert all(label.isHidden() for label in replay.findChildren(QLabel) if "MOCK" in label.text())

    replay._top_bar._update_mode_badge("replay", {"replay_source": "/data/run.db", "replay_speed": 5.0})
    assert "REPLAY" in replay._top_bar._mode_badge.text()
    assert "MOCK" not in replay._top_bar._mode_badge.text()


def test_standalone_shell_latches_verified_engine_mock_provenance_via_status_poll(monkeypatch) -> None:
    """The existing watch-bar poll path upgrades standalone chrome from engine truth."""
    from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION

    class _Signal:
        def __init__(self) -> None:
            self._callbacks = []

        def connect(self, callback) -> None:  # noqa: ANN001
            self._callbacks.append(callback)

        def emit(self, *args: object) -> None:
            for callback in self._callbacks:
                callback(*args)

    payload = {
        "ok": True,
        "state": "ready",
        "fault_reason": "",
        "fault_revision": 0,
        "fault_activated_at": 0.0,
        "recovery_reason": "",
        "channels_tracked": 0,
        "keithley_connected": False,
        "active_channels": [],
        "mock": True,
        "engine_instance_id": "a" * 32,
        "proto": CLIENT_PROTOCOL_VERSION,
    }
    commands: list[dict[str, str]] = []

    class _Worker:
        def __init__(self, command, **_kwargs) -> None:  # noqa: ANN001
            commands.append(command)
            self.command = command
            self.finished = _Signal()
            self.settled = _Signal()

        def deleteLater(self) -> None:
            return None

        def start(self) -> None:
            self.finished.emit(payload if self.command["cmd"] == "safety_status" else {})
            self.settled.emit()

    monkeypatch.setattr("cryodaq.gui.zmq_client.ZmqCommandWorker", _Worker)
    window = MainWindowV2()
    _stop_timers(window)

    window._top_bar._poll_fast()
    assert "MOCK" in window.windowTitle()

    badge = window._top_bar._mock_provenance_badge
    assert commands == [{"cmd": "safety_status"}, {"cmd": "experiment_status"}]
    assert "MOCK" in window.windowTitle()
    assert not badge.isHidden()
    assert badge.text() == "MOCK"
    assert badge.accessibleName() == "MOCK: имитационные данные, не живые измерения"
    assert badge.toolTip() == "MOCK: имитационные данные, не живые измерения"

    payload["mock"] = False
    window._top_bar._poll_fast()
    assert "MOCK" in window.windowTitle()
    assert not badge.isHidden()
    window.close()


def test_mock_top_watch_bar_keeps_adjacent_alarm_and_mode_truth_at_1280() -> None:
    app = _app()
    window = MainWindowV2(mock_mode=True)
    _stop_timers(window)
    bar = window._top_bar
    bar.set_alarm_summary(3, "CRITICAL")
    bar._update_mode_badge("debug")
    window.resize(1280, 800)
    window.show()
    app.processEvents()

    for label in (bar._alarms_label, bar._mode_badge, bar._mock_provenance_badge):
        assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
        assert label.width() >= label.sizeHint().width()
    context_children = (
        bar._ctx_pressure_label,
        bar._ctx_pressure_value,
        bar._ctx_second_stage_label,
        bar._ctx_second_stage_value,
        bar._ctx_n2_plate_label,
        bar._ctx_n2_plate_value,
        *[child for child in bar._context_frame.findChildren(QLabel) if child.text().strip() == "·"],
    )
    assert len(context_children) == 8
    for child in context_children:
        assert child.isVisible()
        assert child.width() >= child.fontMetrics().horizontalAdvance(child.text())
        assert child.height() >= child.fontMetrics().height()
    assert "Тревоги: 3" in bar._alarms_label.text()
    assert bar._mode_badge.text() == "Отладка"
    assert bar._mock_provenance_badge.isVisible()
    window.close()


def test_standalone_safety_status_rebinds_only_after_watchdog_transport_turnover() -> None:
    """The real watchdog turnover admits B once and refuses a late A packet."""
    from cryodaq.gui import app as gui_app

    _app()
    window = MainWindowV2()
    _stop_timers(window)
    bar = window._top_bar
    received: list[bool] = []
    bar.mock_mode_verified.connect(received.append)

    bar._on_mock_safety_result(_safety_status("a" * 32, False))
    assert received == [False]
    assert window.windowTitle() == "CryoDAQ"

    bridge = MagicMock()
    bridge.is_alive.return_value = False
    watchdog = gui_app._BridgeWatchdog()
    watchdog._restart(bridge, window, MagicMock(), shutdown_first=False)

    bar._on_mock_safety_result(_safety_status("b" * 32, True))
    bar._on_mock_safety_result(_safety_status("a" * 32, False))

    assert received == [False, True]
    assert "MOCK" in window.windowTitle()
    assert bar._mock_safety_engine_instance_id == "b" * 32
    window.close()


def test_standalone_same_engine_mock_contradiction_latches_fail_closed_provenance() -> None:
    _app()
    window = MainWindowV2()
    _stop_timers(window)
    bar = window._top_bar

    bar._on_mock_safety_result(_safety_status("a" * 32, False))
    bar._on_mock_safety_result(_safety_status("a" * 32, True))

    assert "MOCK" in window.windowTitle()
    assert not bar._mock_provenance_badge.isHidden()
    window.close()


def test_operator_display_is_fail_closed_home_and_routes_to_drill_down(monkeypatch) -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)

    assert w._operator_display.snapshot is None
    assert w._operator_display.accessibleName() == "Сводка смены"
    assert "недоступны" in w._operator_display.accessibleDescription()

    accepted = []
    monkeypatch.setattr(w._operator_display, "render", accepted.append)
    snapshot = object()
    w.render_operator_snapshot(snapshot)
    assert accepted == [snapshot]

    typed: list[NavigationIntent] = []
    w._operator_display.navigation_requested.connect(typed.append)
    w._operator_display._forward_navigation(w._operator_display.next_action.intent)
    assert typed == [w._operator_display.next_action.intent]
    assert isinstance(typed[0], NavigationIntent)

    w._operator_display.route_requested.emit("alarms")
    assert w._overlay.currentWidget() is w._alarm_panel
    assert w._tool_rail._buttons["alarms"]._active is True
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()

    w._on_tool_clicked("summary")
    assert w._overlay.currentWidget() is w._operator_display
    assert w._overlay.current_overlay == "summary"
    assert w._tool_rail._buttons["more"]._active is True


def test_tool_rail_click_switches_overlay() -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    # "alarms" is eagerly registered (it feeds the watch bar count), so
    # opening it doesn't trigger lazy construction of any other panel.
    # Drive via the real ToolRail button click so tool_clicked signal fires.
    w._tool_rail._buttons["alarms"].click()
    assert w._overlay.currentWidget() is w._alarm_panel
    assert w._overlay.current_overlay == "alarms"
    assert w._tool_rail._buttons["alarms"]._active is True
    w._tool_rail._buttons["home"].click()
    assert w._overlay.currentWidget() is w._overview_panel
    assert w._overlay.current_overlay == "home"
    assert w._tool_rail._buttons["home"]._active is True
    assert not w._top_bar.isHidden()
    assert not w._bottom_bar.isHidden()
