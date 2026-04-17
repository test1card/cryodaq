"""Tests for PhaseStepper widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui.dashboard.phase_stepper import PhaseStepper


def test_phase_stepper_highlights_current_phase(app):
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    assert s._current_phase == "cooldown"


def test_phase_stepper_marks_completed_phases(app):
    s = PhaseStepper()
    s.set_current_phase("measurement")
    # preparation, vacuum, cooldown should be past
    assert s._current_phase == "measurement"


def test_phase_stepper_none_resets_all(app):
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    s.set_current_phase(None)
    assert s._current_phase is None


def test_pill_tooltip_shows_phase_name(app):
    from cryodaq.core.phase_labels import PHASE_LABELS_RU

    s = PhaseStepper()
    for phase, pill in s._pills.items():
        assert pill.toolTip() == PHASE_LABELS_RU[phase]


def test_pill_height_compact(app):
    s = PhaseStepper()
    for pill in s._pills.values():
        assert pill.maximumHeight() == 24
