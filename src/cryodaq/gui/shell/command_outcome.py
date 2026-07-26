"""Shared classification of ambiguous mutation-command outcomes.

Both ``ExperimentOverlay`` and the Keithley panel need to tell the operator
when a mutation command's true server-side outcome is unresolved, as opposed
to a truthful rejection, so the UI never reports a plain "refused" when the
hazardous action may in fact have taken effect.
"""

from __future__ import annotations

from cryodaq.core.command_reply_contract import MUTATION_COMMAND_SETTLED_REPLY_TUPLES

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

_STRUCTURED_SETTLEMENT_KEYS = (
    "_handler_timeout",
    "outcome_unknown",
    "commit_state",
    "delivery_state",
)


def _structured_outcome_unknown(result: dict[object, object]) -> bool:
    """Fail closed unless structured evidence proves one terminal tuple."""

    for key in ("_handler_timeout", "outcome_unknown"):
        if key not in result:
            continue
        value = result[key]
        if type(value) is not bool or value:
            return True

    delivery_present = "delivery_state" in result
    commit_present = "commit_state" in result
    if not (delivery_present or commit_present):
        # A false boolean flag reports no uncertainty, but it is not terminal
        # commit evidence on its own.
        return True

    delivery_state = result.get("delivery_state")
    commit_state = result.get("commit_state")
    if delivery_present and type(delivery_state) is not str:
        return True
    if commit_present and type(commit_state) is not str:
        return True
    return (delivery_state, commit_state) not in MUTATION_COMMAND_SETTLED_REPLY_TUPLES


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

    Structured evidence resolves only when its typed
    ``(delivery_state, commit_state)`` tuple is one of the mutation terminal
    tuples in the shared core contract. A delivery state alone, a read/audit
    value, malformed evidence, or an incoherent pair is unknown. Prose
    matching runs only when no structured settlement key is present at all, so
    a resolved refusal whose prose contains a timeout-shaped substring cannot
    be reclassified as unknown.
    """

    if not isinstance(result, dict):
        return True
    structured_keys = tuple(key for key in _STRUCTURED_SETTLEMENT_KEYS if key in result)
    if structured_keys:
        return _structured_outcome_unknown(result)
    error = str(result.get("error") or "").casefold()
    return any(marker in error for marker in _PROSE_UNKNOWN_MARKERS)
