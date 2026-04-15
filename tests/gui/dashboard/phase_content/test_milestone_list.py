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
    w.set_milestones([
        {"phase": "preparation", "duration_s": 3600},
        {"phase": "vacuum", "duration_s": 7200},
    ])
    assert w._empty_label.isHidden()
    assert len(w._row_labels) == 2


def test_milestone_list_formats_duration_ru(app):
    w = MilestoneList()
    w.set_milestones([{"phase": "cooldown", "duration_s": 51600}])
    text = w._row_labels[0].text()
    assert "14\u0447" in text
