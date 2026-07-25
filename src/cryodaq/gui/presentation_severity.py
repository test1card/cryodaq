"""Presentation-only compatibility for operator severity vocabulary."""

from __future__ import annotations

from cryodaq.operator_snapshot import OperatorPresentationState


def operator_state_for_display(state: OperatorPresentationState) -> OperatorPresentationState:
    """Collapse legacy warning into the canonical operator caution state."""

    if not isinstance(state, OperatorPresentationState):
        raise TypeError("state must be an OperatorPresentationState")
    return OperatorPresentationState.CAUTION if state is OperatorPresentationState.WARNING else state


def alarm_level_for_display(level: str) -> str:
    """Return the canonical alarm display level without changing source truth."""

    if not isinstance(level, str):
        raise TypeError("alarm level must be a string")
    normalized = level.strip().upper()
    if normalized in {"WARNING", "CAUTION"}:
        return "CAUTION"
    if normalized in {"CRITICAL", "INFO"}:
        return normalized
    return "UNKNOWN"
