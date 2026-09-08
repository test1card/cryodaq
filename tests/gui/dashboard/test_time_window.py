"""Tests for TimeWindow enum (Phase UI-1 v2 Block B.2).

Imports the CANONICAL module. This used to come through a re-export shim in
`gui.dashboard`, kept "while repo consumers migrate" — the migration finished
and the shim had no importer left in the whole tree.
"""

from cryodaq.gui.state.time_window import TimeWindow


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


# LOW: assert full ordered list [MIN_1, HOUR_1, HOUR_6, HOUR_24, ALL]
def test_all_options_full_ordered_list():
    opts = TimeWindow.all_options()
    assert opts == [
        TimeWindow.MIN_1,
        TimeWindow.HOUR_1,
        TimeWindow.HOUR_6,
        TimeWindow.HOUR_24,
        TimeWindow.ALL,
    ], f"Expected ordered [MIN_1, HOUR_1, HOUR_6, HOUR_24, ALL], got {opts!r}"
