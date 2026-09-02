"""An ambiguous delivery must be able to stop being ambiguous.

``mark_delivery_unknown`` appended to ``unresolved_delivery`` and nothing ever
removed an entry. One Telegram send that timed out with an unknown outcome was
therefore recorded forever:

* health stayed ``degraded_delivery_unknown`` -- "awaiting reconciliation",
  while no reconciliation path existed;
* the launcher reported ``H3_RUNTIME_UNAVAILABLE``, i.e. the runtime is
  unreachable, about a runtime that was alive and delivering successfully;
* at ``MAX_UNRESOLVED_DELIVERIES`` entries ``_deliver`` stops and periodic
  reporting ends permanently.

Observed on the stand: one entry from 2026-08-31 still degrading health on
2026-09-02, with every report since delivered successfully.

The ledger records the operator's knowledge: "we cannot say whether you
received this report". A LATER success to the SAME destination answers that --
the channel works and a periodic snapshot is replaced by the newer one. These
tests pin that supersession, and much more importantly pin what it must refuse
to retire.
"""

from __future__ import annotations

import pytest

from cryodaq.periodic_state import (
    PeriodicStateDocument,
    PeriodicStatus,
    resolve_superseded_unknowns,
)

DEST = "sha256:" + "b7" * 32
OTHER_DEST = "sha256:" + "c4" * 32
SLOT_OLD = 1_788_181_200
SLOT_NEW = 1_788_339_600


def _slot_id(n: int) -> str:
    """The same identity the document validator requires (_require_slot_identity)."""
    import hashlib  # noqa: PLC0415

    return "sha256:" + hashlib.sha256(f"periodic-png/v1:{n}".encode("ascii")).hexdigest()


def _entry(slot_end: int, *, destination: str = DEST) -> dict:
    return {
        "slot_id": _slot_id(slot_end),
        "slot_end": slot_end,
        "generation_id": "0" * 32,
        "destination_fingerprint": destination,
        "artifact_sha256": "sha256:" + "9e" * 32,
        "ambiguity_at": float(slot_end + 15),
        "error_code": "telegram_timeout_unknown",
        "error_text": "Telegram delivery timed out with unknown outcome",
    }


def _terminal(slot_end: int, *, status: str, destination: str = DEST) -> dict:
    return {
        "slot_id": _slot_id(slot_end),
        "slot_end": slot_end,
        "generation_id": "1" * 32,
        "destination_fingerprint": destination,
        "artifact_sha256": "sha256:" + "be" * 32,
        "finished_at": float(slot_end + 128),
        "status": status,
        "certainty": None,
        "error_code": None,
        "error_text": "",
        "failure_phase": None,
        "receipt": {"kind": "telegram", "receipt_id": "1960", "acknowledgement_sha256": None},
    }


def _doc(*, ledger: list[dict], terminal: dict | None, active: dict | None = None) -> PeriodicStateDocument:
    return PeriodicStateDocument(
        {
            "schema": 2,
            "active": active,
            "last_terminal": terminal,
            "unresolved_delivery": list(ledger),
            "high_water_slot_end": SLOT_NEW,
            "health": {
                "status": "degraded_delivery_unknown",
                "error_code": "periodic_delivery_unresolved",
                "error_text": "periodic delivery outcome is unresolved and awaiting reconciliation",
                "updated_at": float(SLOT_NEW),
            },
            "updated_at": float(SLOT_NEW + 200),
        }
    )


# ---------------------------------------------------------------------------
# It resolves
# ---------------------------------------------------------------------------


def test_a_later_success_retires_an_older_ambiguity():
    doc = _doc(
        ledger=[_entry(SLOT_OLD)],
        terminal=_terminal(SLOT_NEW, status=PeriodicStatus.SUCCEEDED.value),
    )

    resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert len(retired) == 1
    assert retired[0]["slot_end"] == SLOT_OLD
    assert resolved.payload["unresolved_delivery"] == []


def test_the_retired_entries_are_returned_not_dropped_silently():
    """The caller must be able to record what it retired."""
    doc = _doc(
        ledger=[_entry(SLOT_OLD), _entry(SLOT_OLD - 3600)],
        terminal=_terminal(SLOT_NEW, status=PeriodicStatus.SUCCEEDED.value),
    )

    _resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert {e["slot_end"] for e in retired} == {SLOT_OLD, SLOT_OLD - 3600}
    assert all(e["error_code"] == "telegram_timeout_unknown" for e in retired)


# ---------------------------------------------------------------------------
# What it must refuse to retire -- this removes durable evidence
# ---------------------------------------------------------------------------


def test_an_ambiguous_later_delivery_resolves_nothing():
    """Only SUCCEEDED proves anything. A later unknown cannot resolve an earlier one.

    last_terminal admits only SUCCEEDED or DELIVERY_UNKNOWN (_TERMINAL_STATUSES),
    and a DELIVERY_UNKNOWN terminal must carry its own matching ledger entry.
    """
    unknown_terminal = _terminal(SLOT_NEW, status=PeriodicStatus.DELIVERY_UNKNOWN.value)
    unknown_terminal["receipt"] = None
    unknown_terminal["error_code"] = "telegram_timeout_unknown"
    unknown_terminal["error_text"] = "Telegram delivery timed out with unknown outcome"
    unknown_terminal["failure_phase"] = "delivery"
    unknown_terminal["certainty"] = "unknown"
    matching = {
        "slot_id": unknown_terminal["slot_id"],
        "slot_end": unknown_terminal["slot_end"],
        "generation_id": unknown_terminal["generation_id"],
        "destination_fingerprint": unknown_terminal["destination_fingerprint"],
        "artifact_sha256": unknown_terminal["artifact_sha256"],
        "ambiguity_at": unknown_terminal["finished_at"],
        "error_code": unknown_terminal["error_code"],
        "error_text": unknown_terminal["error_text"],
    }
    doc = _doc(ledger=[_entry(SLOT_OLD), matching], terminal=unknown_terminal)

    resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert retired == [], "an unknown outcome cannot prove an earlier one"
    assert len(resolved.payload["unresolved_delivery"]) == 2


def test_a_success_to_a_different_destination_resolves_nothing():
    """Delivery to another chat says nothing about this one."""
    doc = _doc(
        ledger=[_entry(SLOT_OLD, destination=OTHER_DEST)],
        terminal=_terminal(SLOT_NEW, status=PeriodicStatus.SUCCEEDED.value),
    )

    _resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert retired == []


def test_an_equally_recent_ambiguity_is_not_retired():
    """Only entries STRICTLY older than the proven success.

    The terminal's own slot is also the one its summary is validated against,
    so it is protected twice over.
    """
    doc = _doc(
        ledger=[_entry(SLOT_NEW)],
        terminal=_terminal(SLOT_NEW, status=PeriodicStatus.SUCCEEDED.value),
    )

    _resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 7200))

    assert retired == []


def test_no_terminal_at_all_resolves_nothing():
    doc = _doc(ledger=[_entry(SLOT_OLD)], terminal=None)

    _resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert retired == []


def test_an_empty_ledger_is_a_no_op():
    doc = _doc(ledger=[], terminal=_terminal(SLOT_NEW, status=PeriodicStatus.SUCCEEDED.value))

    resolved, retired = resolve_superseded_unknowns(doc, now=float(SLOT_NEW + 400))

    assert retired == []
    assert resolved.payload["unresolved_delivery"] == []
