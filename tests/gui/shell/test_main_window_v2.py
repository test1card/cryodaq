"""Smoke tests for MainWindowV2 (Phase UI-1 v2 Block A)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.main_window_v2 import MainWindowV2


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
    assert w.windowTitle() == "CryoDAQ"


def test_tool_rail_click_switches_overlay() -> None:
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    # "alarms" is eagerly registered (it feeds the watch bar count), so
    # opening it doesn't trigger lazy construction of any other panel.
    w._on_tool_clicked("alarms")
    assert w._overlay.current_overlay == "alarms"
    assert w._tool_rail._buttons["alarms"]._active is True
    w._on_tool_clicked("home")
    assert w._overlay.current_overlay == "home"
    assert w._tool_rail._buttons["home"]._active is True

