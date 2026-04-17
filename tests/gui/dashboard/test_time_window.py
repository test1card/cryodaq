"""Tests for TimeWindow enum (Phase UI-1 v2 Block B.2)."""

from cryodaq.gui.dashboard.time_window import TimeWindow


def test_default_is_all():
    # Batch A: long-horizon signal (pressure pump-down, cooldown trends)
    # is what the operator cares about, so initial window is "Всё".
    assert TimeWindow.default() == TimeWindow.ALL
    assert TimeWindow.default().label == "Всё"


def test_all_options_returns_five():
    opts = TimeWindow.all_options()
    assert len(opts) == 5
    assert opts[0] == TimeWindow.MIN_1
    assert opts[-1] == TimeWindow.ALL
