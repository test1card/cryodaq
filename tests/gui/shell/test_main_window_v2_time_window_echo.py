"""Test TopWatchBar time window echo wiring (Phase UI-1 v2 Block B.2)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.dashboard.time_window import TimeWindow
from cryodaq.gui.shell.main_window_v2 import MainWindowV2


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_time_window_echo_initialized(app):
    w = MainWindowV2()
    from PySide6.QtCore import QTimer
    for t in w.findChildren(QTimer):
        try:
            t.stop()
        except RuntimeError:
            pass
    assert "1ч" in w._top_bar._time_window_echo_label.text()


def test_time_window_echo_updates_on_signal(app):
    w = MainWindowV2()
    from PySide6.QtCore import QTimer
    for t in w.findChildren(QTimer):
        try:
            t.stop()
        except RuntimeError:
            pass
    # Emit signal from temp plot
    if w._overview_panel._temp_plot is not None:
        w._overview_panel._temp_plot.time_window_changed.emit(TimeWindow.HOUR_6)
        assert "6ч" in w._top_bar._time_window_echo_label.text()
