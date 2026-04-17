"""Tests for TimeWindow enum (Phase UI-1 v2 Block B.2)."""

from cryodaq.gui.dashboard.time_window import TimeWindow


def test_default_is_hour_1():
    assert TimeWindow.default() == TimeWindow.HOUR_1
    assert TimeWindow.default().label == "1ч"


def test_all_options_returns_five():
    opts = TimeWindow.all_options()
    assert len(opts) == 5
    assert opts[0] == TimeWindow.MIN_1
    assert opts[-1] == TimeWindow.ALL
