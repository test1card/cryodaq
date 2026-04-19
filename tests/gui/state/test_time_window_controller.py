"""Phase III.B — global time-window controller tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.state.time_window import (
    GlobalTimeWindowController,
    TimeWindow,
    get_time_window_controller,
    reset_time_window_controller,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_controller(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def test_controller_singleton_across_calls(app):
    c1 = get_time_window_controller()
    c2 = get_time_window_controller()
    assert c1 is c2


def test_reset_controller_drops_singleton(app):
    c1 = get_time_window_controller()
    reset_time_window_controller()
    c2 = get_time_window_controller()
    assert c1 is not c2


def test_default_window_is_all(app):
    c = get_time_window_controller()
    assert c.get_window() is TimeWindow.ALL


def test_set_window_emits_signal(app):
    c = get_time_window_controller()
    seen: list[TimeWindow] = []
    c.window_changed.connect(seen.append)
    c.set_window(TimeWindow.HOUR_1)
    assert seen == [TimeWindow.HOUR_1]
    assert c.get_window() is TimeWindow.HOUR_1


def test_set_same_window_is_noop(app):
    c = get_time_window_controller()
    c.set_window(TimeWindow.HOUR_6)
    seen: list[TimeWindow] = []
    c.window_changed.connect(seen.append)
    c.set_window(TimeWindow.HOUR_6)
    assert seen == []


@pytest.mark.parametrize(
    "window",
    [TimeWindow.MIN_1, TimeWindow.HOUR_1, TimeWindow.HOUR_6, TimeWindow.HOUR_24, TimeWindow.ALL],
)
def test_all_enum_options_roundtrip(app, window):
    c = get_time_window_controller()
    # Start from a different window so each parametrization actually emits.
    starting = TimeWindow.MIN_1 if window is not TimeWindow.MIN_1 else TimeWindow.HOUR_1
    c.set_window(starting)
    seen: list[TimeWindow] = []
    c.window_changed.connect(seen.append)
    c.set_window(window)
    assert seen == [window]
    assert c.get_window() is window


def test_controller_is_qobject(app):
    c = get_time_window_controller()
    assert isinstance(c, GlobalTimeWindowController)


def test_time_window_label_and_seconds():
    assert TimeWindow.MIN_1.label == "1мин"
    assert TimeWindow.MIN_1.seconds == 60.0
    assert TimeWindow.HOUR_24.seconds == 86400.0
    assert TimeWindow.ALL.seconds == float("inf")


def test_all_options_order():
    opts = TimeWindow.all_options()
    assert opts == [
        TimeWindow.MIN_1,
        TimeWindow.HOUR_1,
        TimeWindow.HOUR_6,
        TimeWindow.HOUR_24,
        TimeWindow.ALL,
    ]
