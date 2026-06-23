"""Tests for MilestoneList widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui.dashboard.phase_content.milestone_list import MilestoneList


def test_milestone_list_shows_empty_state(app):
    w = MilestoneList()
    w.set_milestones([])
    assert not w._empty_label.isHidden()


def test_milestone_list_renders_completed_phases(app):
    w = MilestoneList()
    w.set_milestones(
        [
            {"phase": "preparation", "duration_s": 3600},
            {"phase": "vacuum", "duration_s": 7200},
        ]
    )
    assert w._empty_label.isHidden()
    assert len(w._row_labels) == 2
    # Row texts must contain the Russian phase labels and formatted durations.
    text0 = w._row_labels[0].text()
    text1 = w._row_labels[1].text()
    assert "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430" in text0, (
        f"Expected '\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430' in row 0, got {text0!r}"
    )
    assert "1\u0447" in text0, f"Expected '1\u0447' (3600 s) in row 0, got {text0!r}"
    assert "\u041e\u0442\u043a\u0430\u0447\u043a\u0430" in text1, (
        f"Expected '\u041e\u0442\u043a\u0430\u0447\u043a\u0430' in row 1, got {text1!r}"
    )
    assert "2\u0447" in text1, f"Expected '2\u0447' (7200 s) in row 1, got {text1!r}"


def test_milestone_list_formats_duration_ru(app):
    w = MilestoneList()
    w.set_milestones([{"phase": "cooldown", "duration_s": 51600}])
    text = w._row_labels[0].text()
    # 51600 s = 14 h 20 min; both components must appear.
    assert "14\u0447 20\u043c\u0438\u043d" in text, (
        f"Expected '14\u0447 20\u043c\u0438\u043d' in row text, got {text!r}"
    )
    # Phase label must also appear.
    phase_label = "\u0417\u0430\u0445\u043e\u043b\u0430\u0436\u0438\u0432\u0430\u043d\u0438\u0435"
    assert phase_label in text, f"Expected {phase_label!r} in row text, got {text!r}"
