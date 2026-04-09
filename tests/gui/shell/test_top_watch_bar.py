"""Smoke tests for TopWatchBar (Phase UI-1 v2 Block A)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.top_watch_bar import TopWatchBar


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_top_watch_bar_constructs() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    assert bar.height() > 0
    assert bar._engine_label is not None


def test_experiment_click_emits_signal() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    fired = []
    bar.experiment_clicked.connect(lambda: fired.append(True))
    bar._exp_label.clicked.emit()
    assert fired == [True]


def test_alarms_click_emits_signal() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    fired = []
    bar.alarms_clicked.connect(lambda: fired.append(True))
    bar._alarms_label.clicked.emit()
    assert fired == [True]


def test_set_alarm_count_updates_label() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar.set_alarm_count(0)
    assert "0" in bar._alarms_label.text()
    bar.set_alarm_count(3)
    assert "3" in bar._alarms_label.text()
