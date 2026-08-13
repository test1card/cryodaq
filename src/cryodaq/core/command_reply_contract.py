"""Shared finite JSON contract for engine REP replies.

The engine encoder and the GUI-owned subprocess decoder must accept the same
reply language.  Keeping the structural limits here prevents a server-valid
reply from becoming an indeterminate client-side transport failure.
"""

from __future__ import annotations

import math
from typing import Any

COMMAND_REPLY_MAX_WIRE_BYTES = 4 * 1024 * 1024
COMMAND_REPLY_MAX_JSON_DEPTH = 32
# ``readings_history`` is the widest production reply.  The 76,867-row
# production ceiling is derived from the actual compact encoder, not
# representative fixture values: every point may contain the longest finite
# binary64 spellings, and both ``data`` and its persisted-quantity catalog may
# contain all 64 channel keys at the 256-character structural limit (including
# JSON's six-byte control-character escapes).  That complete envelope remains
# below 4 MiB.  Storage is bound to the same total and channel count so a
# producer-valid history reply is always decoder-valid.
COMMAND_REPLY_HISTORY_MAX_ROWS = 76_867
COMMAND_REPLY_MAX_JSON_ITEMS = 4 * COMMAND_REPLY_HISTORY_MAX_ROWS + (2 * 64)
COMMAND_REPLY_MAX_JSON_KEY_CHARS = 256
COMMAND_REPLY_MAX_INTEGER_DIGITS = 128

# Mutation-command settlement vocabulary, deliberately excluding similarly
# named read and assistant-audit states below.
MUTATION_COMMAND_DELIVERY_STATES = frozenset({"dispatched", "not_dispatched", "unknown"})
MUTATION_COMMAND_COMMIT_STATES = frozenset({"committed", "not_committed", "unknown"})

# Only these mutation-command tuples prove a settled outcome to the GUI.
# ``None`` is the legacy absence of ``delivery_state``; it is retained solely
# for old truthful ``commit_state: "not_committed"`` refusals.
MUTATION_COMMAND_SETTLED_REPLY_TUPLES = frozenset(
    {
        ("dispatched", "committed"),
        ("dispatched", "not_committed"),
        ("not_dispatched", "not_committed"),
        (None, "not_committed"),
    }
)

# These similarly named fields describe different domains. They are separate
# from the mutation settlement contract so a read or assistant-audit value can
# never become evidence that a hazardous mutation settled.
READ_COMMAND_DELIVERY_STATES = frozenset({"not_confirmed", "unknown"})
READ_COMMAND_COMMIT_STATES = frozenset({"not_applicable"})
ASSISTANT_AUDIT_DELIVERY_STATES = frozenset({"intent_persisted", "settled"})


def _validate_history_row_bound(value: dict[str, Any]) -> None:
    """Reject a history-shaped reply above the producer's exact row ceiling."""

    data = value.get("data")
    if type(data) is not dict or not data:
        return
    history_shaped = all(
        type(points) is list and all(type(point) in {list, tuple} and len(point) == 2 for point in points)
        for points in data.values()
    )
    if not history_shaped:
        return
    retained = 0
    for points in data.values():
        retained += len(points)
        if retained > COMMAND_REPLY_HISTORY_MAX_ROWS:
            raise ValueError("command reply history contains too many rows")


def validate_command_reply_structure(
    value: object,
    *,
    max_wire_bytes: int = COMMAND_REPLY_MAX_WIRE_BYTES,
    max_depth: int = COMMAND_REPLY_MAX_JSON_DEPTH,
    max_items: int = COMMAND_REPLY_MAX_JSON_ITEMS,
    max_key_chars: int = COMMAND_REPLY_MAX_JSON_KEY_CHARS,
    max_integer_digits: int = COMMAND_REPLY_MAX_INTEGER_DIGITS,
) -> dict[str, Any]:
    """Validate one finite JSON-object reply under explicit resource caps."""

    limits = (max_wire_bytes, max_depth, max_items, max_key_chars, max_integer_digits)
    if any(type(limit) is not int or limit <= 0 for limit in limits):
        raise ValueError("command reply limits are invalid")
    if type(value) is not dict:
        raise ValueError("command reply JSON root must be an object")
    _validate_history_row_bound(value)

    item_count = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        item_count += 1
        if item_count > max_items:
            raise ValueError("command reply contains too many items")
        if depth > max_depth:
            raise ValueError("command reply is nested too deeply")
        if type(current) is dict:
            for key, child in current.items():
                if type(key) is not str or len(key) > max_key_chars:
                    raise ValueError("command reply key is invalid or too long")
                pending.append((child, depth + 1))
        elif type(current) in {list, tuple}:
            pending.extend((child, depth + 1) for child in current)
        elif type(current) is str:
            if len(current.encode("utf-8")) > max_wire_bytes:
                raise ValueError("command reply string is too long")
        elif type(current) is int:
            if len(str(current).removeprefix("-")) > max_integer_digits:
                raise ValueError("command reply integer is too large")
        elif type(current) is float:
            if not math.isfinite(current):
                raise ValueError("non-finite command reply number")
        elif current is not None and type(current) is not bool:
            raise ValueError("command reply contains an unsupported value")
    return value
