"""Shared classification of ambiguous mutation-command outcomes.

Both ``ExperimentOverlay`` and the Keithley panel need to tell the operator
when a mutation command's true server-side outcome is unresolved, as opposed
to a truthful rejection, so the UI never reports a plain "refused" when the
hazardous action may in fact have taken effect.
"""

from __future__ import annotations

from cryodaq.core.command_reply_contract import (
    COMMAND_REPLY_COMMIT_STATES,
    COMMAND_REPLY_DELIVERY_STATES,
)

# Error-prose substrings recognized only as a fallback, for reply shapes
# that carry none of the structured settlement keys below at all (legacy /
# handler-local paths with no transport vocabulary).
_PROSE_UNKNOWN_MARKERS = (
    "timeout",
    "timed out",
    "тайм-аут",
    "не отвечает",
    "may still be running",
    "исход неизвестен",
)

# `commit_state` / `delivery_state` values that mean the transport genuinely
# does not know what happened server-side. "not_committed" / "not_dispatched"
# are truthful, resolved refusals (e.g. mutation_protocol_incompatible,
# command_authority_quarantined) and must never be folded in here.
_UNKNOWN_COMMIT_STATES = frozenset({"unknown"})
_UNKNOWN_DELIVERY_STATES = frozenset({"unknown"})
_STRUCTURED_SETTLEMENT_KEYS = (
    "_handler_timeout",
    "outcome_unknown",
    "commit_state",
    "delivery_state",
)


def _structured_outcome_unknown(key: str, value: object) -> bool | None:
    """Return the settlement decision, or None for malformed evidence."""

    if key in {"_handler_timeout", "outcome_unknown"}:
        if type(value) is not bool:
            return None
        return value
    if key == "commit_state":
        if type(value) is not str or value not in COMMAND_REPLY_COMMIT_STATES:
            return None
        return value in _UNKNOWN_COMMIT_STATES
    if type(value) is not str or value not in COMMAND_REPLY_DELIVERY_STATES:
        return None
    return value in _UNKNOWN_DELIVERY_STATES


def result_outcome_unknown(result: object) -> bool:
    """Return whether a mutation command reply's true outcome is unresolved.

    Structured transport evidence (``outcome_unknown``, ``commit_state``,
    ``delivery_state``) is checked FIRST, before any error-prose matching.
    Several real failure paths -- command_endpoint_unavailable,
    command_forward_failed, command_handler_failed, command_dispatch_failed,
    command_reply_serialization_failed, and the client-side
    cancellation/timeout-after-dispatch replies in zmq_client.py -- carry
    `outcome_unknown: True` and/or `commit_state`/`delivery_state: "unknown"`
    with error prose that names none of the six markers below. Checking
    prose first misclassified those as plain rejections: for
    ``keithley_start`` that told the operator a hazardous source was
    refused when it may actually be ON. The `_handler_timeout` flag and the
    prose fallback are kept for reply shapes that carry no structured
    settlement vocabulary at all; removing them would regress those paths.

    A structured key decides the question only when its value is recognised:
    ``True``/``"unknown"`` means unknown, while a recognised settled value
    (such as ``commit_state: "not_committed"`` or
    ``delivery_state: "not_dispatched"``) means resolved. Missing, malformed,
    or unrecognised structured evidence is unknown. Prose matching runs only
    when no structured settlement key is present at all, so a resolved refusal
    whose prose contains a timeout-shaped substring cannot be reclassified as
    unknown.
    """

    if not isinstance(result, dict):
        return True
    structured_keys = tuple(key for key in _STRUCTURED_SETTLEMENT_KEYS if key in result)
    if structured_keys:
        decisions = tuple(_structured_outcome_unknown(key, result[key]) for key in structured_keys)
        if None in decisions or any(decisions):
            return True
        return False
    error = str(result.get("error") or "").casefold()
    return any(marker in error for marker in _PROSE_UNKNOWN_MARKERS)
