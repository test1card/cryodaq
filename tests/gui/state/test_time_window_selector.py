"""Phase III.B — TimeWindowSelector tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
    reset_time_window_controller,
)
from cryodaq.gui.state.time_window_selector import TimeWindowSelector


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_controller(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def test_selector_has_default_four_buttons(app):
    sel = TimeWindowSelector()
    assert set(sel._buttons.keys()) == {
        TimeWindow.MIN_1,
        TimeWindow.HOUR_1,
        TimeWindow.HOUR_24,
        TimeWindow.ALL,
    }


def test_selector_show_6h_adds_button(app):
    sel = TimeWindowSelector(show_6h=True)
    assert TimeWindow.HOUR_6 in sel._buttons


def test_click_broadcasts_to_controller(app):
    sel = TimeWindowSelector()
    controller = get_time_window_controller()
    seen: list[TimeWindow] = []
    controller.window_changed.connect(seen.append)
    sel._buttons[TimeWindow.MIN_1].click()
    assert seen == [TimeWindow.MIN_1]
    assert controller.get_window() is TimeWindow.MIN_1


def test_initial_checked_reflects_controller(app):
    sel = TimeWindowSelector()
    # Default window is ALL.
    assert sel._buttons[TimeWindow.ALL].isChecked() is True
    assert sel._buttons[TimeWindow.MIN_1].isChecked() is False


def test_external_change_updates_checked_state(app):
    sel = TimeWindowSelector()
    controller = get_time_window_controller()
    controller.set_window(TimeWindow.HOUR_1)
    assert sel._buttons[TimeWindow.HOUR_1].isChecked() is True
    assert sel._buttons[TimeWindow.ALL].isChecked() is False


def test_checked_button_uses_accent_not_status_ok(app):
    sel = TimeWindowSelector()
    checked_btn = sel._buttons[TimeWindow.ALL]  # default
    ss = checked_btn.styleSheet()
    assert theme.ACCENT in ss
    assert theme.STATUS_OK not in ss
