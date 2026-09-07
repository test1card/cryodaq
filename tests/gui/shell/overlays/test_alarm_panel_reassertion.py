"""The alarm history validator must admit a restatement (PI-11).

`_valid_v2_history` rejects the WHOLE payload on one unrecognised transition —
`else: return False`. The engine now emits `REASSERTED` history records for a
CRITICAL that has stayed active past its reassert interval, so a validator that
did not know the word would blank the operator's entire alarm history the first
time a condition held for an hour. That is a strictly worse outcome than the
silence PI-11 set out to fix, and it is the exact shape of failure the operator
named: two halves of one contract, each correct alone.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryodaq.gui.shell.overlays.alarm_panel import _valid_v2_history


def _row(transition: str) -> dict:
    row = {
        "alarm_id": "vacuum_loss_cold",
        "transition": transition,
        "at": 1_000_000.0,
        "level": "CRITICAL",
    }
    if transition != "CLEARED":
        row["message"] = "давление выше порога"
    return row


def test_a_reassertion_is_admitted() -> None:
    assert _valid_v2_history([_row("REASSERTED")]), "a REASSERTED history row must be accepted — the engine emits it"


def test_one_reassertion_does_not_invalidate_the_whole_history() -> None:
    history = [_row("TRIGGERED"), _row("REASSERTED"), _row("CLEARED")]
    assert _valid_v2_history(history), (
        "the validator rejects the entire payload on one unknown transition, so "
        "an unrecognised restatement would blank the operator's alarm history"
    )


def test_a_reassertion_without_a_message_is_still_rejected() -> None:
    """Admitting the word must not weaken the shape it admits."""
    row = _row("REASSERTED")
    del row["message"]
    assert not _valid_v2_history([row])


def test_a_genuinely_unknown_transition_is_still_rejected() -> None:
    assert not _valid_v2_history([_row("REASSERTED_MAYBE")])
