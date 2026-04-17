"""Tests for canonical phase labels module (B.6)."""

from __future__ import annotations

from cryodaq.core.experiment import ExperimentPhase
from cryodaq.core.phase_labels import (
    PHASE_LABELS_RU,
    PHASE_ORDER,
    label_for,
)


def test_label_for_returns_dash_for_none():
    assert label_for(None) == "\u2014"


def test_label_for_handles_enum_input():
    result = label_for(ExperimentPhase.COOLDOWN)
    assert result == PHASE_LABELS_RU["cooldown"]
    assert result != "\u2014"


def test_label_for_handles_string_input():
    result = label_for("preparation")
    assert result == PHASE_LABELS_RU["preparation"]
    assert result != "\u2014"


def test_label_for_returns_dash_for_unknown_string():
    assert label_for("nonsense") == "\u2014"


def test_phase_labels_ru_covers_all_enum_members():
    for phase in ExperimentPhase:
        assert phase.value in PHASE_LABELS_RU, f"Missing label for {phase.value}"
        assert PHASE_LABELS_RU[phase.value]  # non-empty


def test_phase_order_matches_enum():
    enum_values = [p.value for p in ExperimentPhase]
    assert list(PHASE_ORDER) == enum_values
