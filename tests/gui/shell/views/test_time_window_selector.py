"""Unit tests for TimeWindowSelector."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from cryodaq.gui.state.time_window import TimeWindow
from cryodaq.gui.widgets.shared.time_window_selector import TimeWindowSelector


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_selector_default_is_hour_1(app):
    sel = TimeWindowSelector()
    assert sel.get_window() is TimeWindow.HOUR_1


def test_selector_emits_signal_on_set(app):
    sel = TimeWindowSelector()
    received = []
    sel.window_changed.connect(received.append)
    sel.set_window(TimeWindow.HOUR_24)
    assert received == [TimeWindow.HOUR_24]


def test_selector_idempotent_set(app):
    sel = TimeWindowSelector()
    received = []
    sel.window_changed.connect(received.append)
    sel.set_window(TimeWindow.HOUR_1)  # already default
    sel.set_window(TimeWindow.HOUR_1)
    assert len(received) == 0


def test_selector_button_count_and_labels(app):
    sel = TimeWindowSelector()
    buttons = sel.findChildren(QPushButton)
    assert len(buttons) == 5
    labels = [b.text() for b in buttons]
    assert labels == ["1мин", "1ч", "6ч", "24ч", "Всё"]
