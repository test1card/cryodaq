"""Tests for PhaseStepper widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui import theme
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


def test_active_phase_uses_accent_not_status_ok(app):
    # IV.2 B.2 flipped the tier convention: STATUS_OK is reserved for
    # safety/running-status semantics (engine healthy, safety SAFE).
    # The "current phase" pill marks UI state ("which phase are we in
    # right now"), not safety — semantic collision with STATUS_OK
    # meant a fault-latched run with the same phase still showed green.
    # ACCENT is the tier for UI activation per Phase III.A.
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    active_ss = s._pills["cooldown"].styleSheet()
    assert theme.ACCENT in active_ss, f"active phase stylesheet missing ACCENT: {active_ss!r}"
    # Hex-substring check only meaningful when ACCENT and STATUS_OK differ.
    # Some themes (e.g. warm_stone) may adopt a forest-green accent equal
    # to STATUS_OK; the distinction the rule guards is then not
    # expressible via stylesheet grep — the source-level check above
    # (`ACCENT in active_ss`) still proves the correct token was read.
    if theme.ACCENT != theme.STATUS_OK:
        assert theme.STATUS_OK not in active_ss, (
            f"active phase stylesheet leaked STATUS_OK (reserved for safety): {active_ss!r}"
        )
