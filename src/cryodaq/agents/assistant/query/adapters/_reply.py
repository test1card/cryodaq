"""Small reply-shape predicates shared by engine-query adapters."""

from __future__ import annotations

from typing import Any


def reply_is_success(reply: object) -> bool:
    return isinstance(reply, dict) and reply.get("ok") is True


def reply_declares_absence(reply: object, field: str) -> bool:
    return reply_is_success(reply) and field in reply and reply[field] is None


def reply_declares_empty_sequence(reply: object, field: str, key: str | None = None) -> bool:
    if not reply_is_success(reply):
        return False
    value: Any = reply.get(field)
    if key is not None:
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return isinstance(value, list) and not value


def reply_declares_no_data(reply: object) -> bool:
    return reply_is_success(reply) and reply.get("status") == "no_data"


def reply_failure_reason(reply: object, fallback: str) -> str:
    if isinstance(reply, dict) and isinstance(reply.get("error"), str) and reply["error"].strip():
        return reply["error"].strip()
    return fallback
