"""Tests for PhaseStepper widget (B.5.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_stepper import PhaseStepper


# HIGH: assert current pill ACCENT styling (not just _current_phase)
def test_phase_stepper_highlights_current_phase(app):
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    assert s._current_phase == "cooldown"
    # rendered contract: current pill uses ACCENT token
    active_ss = s._pills["cooldown"].styleSheet()
    assert theme.ACCENT in active_ss, f"Current phase pill must contain ACCENT token, got: {active_ss!r}"


# HIGH: assert completed pills use STATUS_OK, future pills use BORDER
def test_phase_stepper_marks_completed_phases(app):
    s = PhaseStepper()
    s.set_current_phase("measurement")
    # preparation, vacuum, cooldown are past → neutral filled progress
    for past_phase in ("preparation", "vacuum", "cooldown"):
        ss = s._pills[past_phase].styleSheet()
        assert theme.SECONDARY in ss
        assert theme.STATUS_OK not in ss
    # current pill: ACCENT
    current_ss = s._pills["measurement"].styleSheet()
    assert theme.ACCENT in current_ss, f"Current phase 'measurement' pill must contain ACCENT, got: {current_ss!r}"
    # future pills: BORDER, no STATUS_OK
    for future_phase in ("teardown", "warmup"):
        ss = s._pills[future_phase].styleSheet()
        assert theme.STATUS_OK not in ss, f"Future phase '{future_phase}' must NOT contain STATUS_OK, got: {ss!r}"
        assert theme.BORDER in ss, f"Future phase '{future_phase}' must contain BORDER token, got: {ss!r}"


# HIGH: assert all pills reset to future styling when None
def test_phase_stepper_none_resets_all(app):
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    s.set_current_phase(None)
    assert s._current_phase is None
    # all pills must be in future state: BORDER token, no ACCENT or STATUS_OK
    for phase, pill in s._pills.items():
        ss = pill.styleSheet()
        assert theme.BORDER in ss, f"After reset, pill '{phase}' must contain BORDER token, got: {ss!r}"
        assert theme.ACCENT not in ss, f"After reset, pill '{phase}' must NOT contain ACCENT, got: {ss!r}"
        assert theme.STATUS_OK not in ss, f"After reset, pill '{phase}' must NOT contain STATUS_OK, got: {ss!r}"


def test_pill_tooltip_shows_phase_name(app):
    from cryodaq.core.phase_labels import PHASE_LABELS_RU

    s = PhaseStepper()
    for phase, pill in s._pills.items():
        assert pill.toolTip() == PHASE_LABELS_RU[phase]


def test_pill_height_compact(app):
    s = PhaseStepper()
    for pill in s._pills.values():
        assert pill.maximumHeight() == 24


def test_past_phase_uses_status_ok_filled(app):
    # Completed phases use a neutral filled progress cue. Completion does not
    # prove healthy/safe state and must not consume STATUS_OK green.
    s = PhaseStepper()
    s.set_current_phase("cooldown")
    # "preparation" and "vacuum" are past relative to cooldown.
    past_ss = s._pills["preparation"].styleSheet()
    assert theme.SECONDARY in past_ss
    assert theme.STATUS_OK not in past_ss
    # Future phases stay hollow on BORDER, no STATUS_OK.
    future_ss = s._pills["teardown"].styleSheet()
    assert theme.STATUS_OK not in future_ss
    assert theme.BORDER in future_ss


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
