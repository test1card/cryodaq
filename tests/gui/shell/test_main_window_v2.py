"""Smoke tests for MainWindowV2 (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.operator_components import NavigationIntent
from cryodaq.gui.shell.views.operator_display import OperatorDisplay


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
    assert w._overlay.currentWidget() is w._operator_display
    assert isinstance(w._operator_display, OperatorDisplay)
    assert w._top_bar.isHidden()
    assert w._bottom_bar.isHidden()
    assert w.windowTitle() == "CryoDAQ"


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
    assert w._overlay.currentWidget() is w._operator_display
    assert w._overlay.current_overlay == "home"
    assert w._tool_rail._buttons["home"]._active is True
    assert w._top_bar.isHidden()
    assert w._bottom_bar.isHidden()
