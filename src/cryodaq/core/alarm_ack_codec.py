"""Closed alarm-ack command and wire-result contract.

The engine owns mutation truth; REST and GUI consumers use this pure codec to
prove that a real transport reply is bound to the exact submitted command and
the required-publisher settlement.  No truthy ``ok`` compatibility path exists.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

ALARM_ACK_EVENT_SCHEMA = "alarm_ack_event_v1"
ALARM_ACK_COMMIT_SCHEMA = "alarm_ack_commit_v1"
ALARM_ACK_COMMAND_KEYS = frozenset(
    {
        "cmd",
        "alarm_name",
        "engine_instance_id",
        "activation_id",
        "operator",
        "reason",
        "request_id",
    }
)
ALARM_ACK_EVENT_KEYS = frozenset(
    {
        "schema",
        "request_id",
        "request_fingerprint",
        "alarm_name",
        "activation_id",
        "engine_instance_id",
        "source_activation_id",
        "acknowledged_at",
        "operator",
        "reason",
    }
)
ALARM_ACK_COMMIT_KEYS = frozenset(
    {
        "schema",
        "request_id",
        "request_fingerprint",
        "alarm_name",
        "activation_id",
        "engine_instance_id",
        "source_activation_id",
        "acknowledged_at",
        "committed",
    }
)
ALARM_ACK_PUBLISHED_RESULT_KEYS = frozenset(
    {
        "ok",
        "committed",
        "retry_safe",
        "publication_state",
        "event_emitted",
        "alarm_name",
        "activation_id",
        "engine_instance_id",
        "source_activation_id",
        "request_id",
        "commit_receipt",
        "proto",
    }
)
ALARM_ACK_PENDING_RESULT_KEYS = ALARM_ACK_PUBLISHED_RESULT_KEYS | {"error_code", "error"}
ALARM_ACK_ABORT_TERMINAL_CODES = frozenset({"engine_restart_before_ack_commit", "activation_changed_before_ack_commit"})
ALARM_ACK_ABORTED_RESULT_KEYS = frozenset(
    {
        "ok",
        "committed",
        "retry_safe",
        "publication_state",
        "event_emitted",
        "error_code",
        "error",
        "alarm_name",
        "activation_id",
        "engine_instance_id",
        "source_activation_id",
        "request_id",
        "request_fingerprint",
        "terminal_code",
        "terminal_engine_instance_id",
        "proto",
    }
)
SAFETY_AUDIO_ACK_COMMAND_KEYS = frozenset(
    {"cmd", "engine_instance_id", "activation_id", "operator", "reason", "request_id"}
)
SAFETY_AUDIO_ACK_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "request_id",
        "request_fingerprint",
        "engine_instance_id",
        "activation_id",
        "source_activation_id",
        "entry_id",
        "committed",
    }
)
SAFETY_AUDIO_ACK_RESULT_KEYS = frozenset(
    {
        "ok",
        "engine_instance_id",
        "activation_id",
        "request_id",
        "snapshot_revision",
        "audit_receipt",
        "proto",
    }
)
SOURCE_ACTIVATION_ID_MAX_DIGITS = 64


def _bounded_text(value: object, *, max_chars: int = 256) -> bool:
    return type(value) is str and bool(value) and len(value) <= max_chars and value.isprintable()


def is_canonical_engine_instance_id(value: object) -> bool:
    """Return whether ``value`` is one exact engine-incarnation identity."""

    return bool(type(value) is str and len(value) == 32 and all(char in "0123456789abcdef" for char in value))


def is_canonical_source_activation_id(value: object) -> bool:
    """Accept one bounded, positive, canonical ASCII decimal identity."""

    return bool(
        type(value) is str
        and 1 <= len(value) <= SOURCE_ACTIVATION_ID_MAX_DIGITS
        and value.isascii()
        and value.isdecimal()
        and not value.startswith("0")
    )


def alarm_ack_request_fingerprint(command: object) -> str:
    """Return the engine-identical fingerprint for one exact ACK command."""

    if type(command) is not dict or set(command) != ALARM_ACK_COMMAND_KEYS:
        raise ValueError("alarm ACK command schema is invalid")
    if command.get("cmd") != "alarm_v2_ack":
        raise ValueError("alarm ACK command action is invalid")
    request_id = command.get("request_id")
    if (
        type(request_id) is not str
        or len(request_id) != 32
        or any(char not in "0123456789abcdef" for char in request_id)
    ):
        raise ValueError("alarm ACK request identity is invalid")
    for field in ("alarm_name", "engine_instance_id", "activation_id", "operator", "reason"):
        value = command.get(field)
        if field in {"operator", "reason"} and type(value) is str and value != value.strip():
            raise ValueError(f"alarm ACK {field} must be canonical without surrounding whitespace")
        if (
            not _bounded_text(value)
            or (field == "engine_instance_id" and not is_canonical_engine_instance_id(value))
            or (field in {"operator", "reason"} and not value.strip())
        ):
            raise ValueError(f"alarm ACK {field} is invalid")
    semantic = {key: value for key, value in command.items() if key != "request_id"}
    canonical = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deterministic_alarm_ack_request_id(
    *,
    alarm_name: str,
    engine_instance_id: str,
    activation_id: str,
    operator: str,
    reason: str,
) -> str:
    """Derive one stable idempotency key from immutable ACK semantics."""

    provisional = {
        "cmd": "alarm_v2_ack",
        "alarm_name": alarm_name,
        "engine_instance_id": engine_instance_id,
        "activation_id": activation_id,
        "operator": operator,
        "reason": reason,
        "request_id": "0" * 32,
    }
    return alarm_ack_request_fingerprint(provisional)[:32]


def safety_audio_ack_request_fingerprint(command: object) -> str:
    """Return a fingerprint for the separate safety-audio audit mutation."""

    if type(command) is not dict or set(command) != SAFETY_AUDIO_ACK_COMMAND_KEYS:
        raise ValueError("safety audio ACK command schema is invalid")
    if command.get("cmd") != "annunciation_ack":
        raise ValueError("safety audio ACK action is invalid")
    request_id = command.get("request_id")
    if (
        type(request_id) is not str
        or len(request_id) != 32
        or any(char not in "0123456789abcdef" for char in request_id)
    ):
        raise ValueError("safety audio ACK request identity is invalid")
    for field in ("engine_instance_id", "activation_id", "operator", "reason"):
        value = command.get(field)
        if field in {"operator", "reason"} and type(value) is str and value != value.strip():
            raise ValueError(f"safety audio ACK {field} must be canonical without surrounding whitespace")
        if (
            not _bounded_text(value)
            or (field == "engine_instance_id" and not is_canonical_engine_instance_id(value))
            or (field in {"operator", "reason"} and not value.strip())
        ):
            raise ValueError(f"safety audio ACK {field} is invalid")
    semantic = {key: value for key, value in command.items() if key != "request_id"}
    canonical = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deterministic_safety_audio_ack_request_id(
    *,
    engine_instance_id: str,
    activation_id: str,
    operator: str,
    reason: str,
) -> str:
    provisional = {
        "cmd": "annunciation_ack",
        "engine_instance_id": engine_instance_id,
        "activation_id": activation_id,
        "operator": operator,
        "reason": reason,
        "request_id": "0" * 32,
    }
    return safety_audio_ack_request_fingerprint(provisional)[:32]


def validate_safety_audio_ack_wire_result(
    result: object,
    command: object,
    *,
    expected_proto: int,
) -> bool:
    """Prove the exact durable safety-audio audit receipt on the real wire."""

    if type(expected_proto) is not int:
        raise TypeError("expected_proto must be exactly int")
    try:
        fingerprint = safety_audio_ack_request_fingerprint(command)
    except (TypeError, ValueError):
        return False
    assert type(command) is dict
    if (
        type(result) is not dict
        or set(result) != SAFETY_AUDIO_ACK_RESULT_KEYS
        or result.get("ok") is not True
        or type(result.get("proto")) is not int
        or result.get("proto") != expected_proto
        or result.get("engine_instance_id") != command.get("engine_instance_id")
        or result.get("activation_id") != command.get("activation_id")
        or result.get("request_id") != command.get("request_id")
        or type(result.get("snapshot_revision")) is not int
        or result["snapshot_revision"] < 0
    ):
        return False
    receipt = result.get("audit_receipt")
    source_activation_id = receipt.get("source_activation_id") if type(receipt) is dict else None
    return bool(
        type(receipt) is dict
        and set(receipt) == SAFETY_AUDIO_ACK_RECEIPT_KEYS
        and receipt.get("schema") == "safety_audio_ack_v1"
        and receipt.get("request_id") == command.get("request_id")
        and receipt.get("request_fingerprint") == fingerprint
        and receipt.get("engine_instance_id") == command.get("engine_instance_id")
        and receipt.get("activation_id") == command.get("activation_id")
        and is_canonical_source_activation_id(source_activation_id)
        and type(receipt.get("entry_id")) is int
        and receipt["entry_id"] > 0
        and receipt.get("committed") is True
    )


def validate_alarm_ack_wire_result(
    result: object,
    command: object,
    *,
    expected_proto: int,
) -> Literal["published", "pending", "aborted"] | None:
    """Accept only an exact real-wire result bound to ``command``."""

    if type(expected_proto) is not int:
        raise TypeError("expected_proto must be exactly int")
    try:
        fingerprint = alarm_ack_request_fingerprint(command)
    except (TypeError, ValueError):
        return None
    assert type(command) is dict
    if type(result) is not dict:
        return None
    state = result.get("publication_state")
    if state == "published":
        expected_keys = ALARM_ACK_PUBLISHED_RESULT_KEYS
        expected_ok = True
        expected_emitted = True
    elif state == "pending":
        expected_keys = ALARM_ACK_PENDING_RESULT_KEYS
        expected_ok = False
        expected_emitted = False
    elif state == "aborted":
        expected_keys = ALARM_ACK_ABORTED_RESULT_KEYS
        expected_ok = False
        expected_emitted = False
    else:
        return None
    if (
        set(result) != expected_keys
        or result.get("ok") is not expected_ok
        or result.get("committed") is not (state != "aborted")
        or result.get("retry_safe") is not False
        or result.get("event_emitted") is not expected_emitted
        or type(result.get("proto")) is not int
        or result.get("proto") != expected_proto
    ):
        return None
    if state in {"pending", "aborted"} and (
        result.get("error_code") != ("alarm_ack_publication_pending" if state == "pending" else "alarm_ack_aborted")
        or type(result.get("error")) is not str
        or not result["error"]
        or len(result["error"]) > 512
        or not result["error"].isprintable()
    ):
        return None
    source_activation_id = result.get("source_activation_id")
    if (
        not is_canonical_source_activation_id(source_activation_id)
        or result.get("alarm_name") != command.get("alarm_name")
        or result.get("activation_id") != command.get("activation_id")
        or result.get("engine_instance_id") != command.get("engine_instance_id")
        or result.get("request_id") != command.get("request_id")
    ):
        return None
    if state == "aborted":
        terminal_code = result.get("terminal_code")
        terminal_engine_instance_id = result.get("terminal_engine_instance_id")
        if (
            result.get("request_fingerprint") != fingerprint
            or type(result.get("request_fingerprint")) is not str
            or type(terminal_code) is not str
            or terminal_code not in ALARM_ACK_ABORT_TERMINAL_CODES
            or not is_canonical_engine_instance_id(terminal_engine_instance_id)
            or (
                terminal_code == "activation_changed_before_ack_commit"
                and terminal_engine_instance_id != command.get("engine_instance_id")
            )
            or (
                terminal_code == "engine_restart_before_ack_commit"
                and terminal_engine_instance_id == command.get("engine_instance_id")
            )
        ):
            return None
        return state
    receipt = result.get("commit_receipt")
    if type(receipt) is not dict or set(receipt) != ALARM_ACK_COMMIT_KEYS:
        return None
    acknowledged_at = receipt.get("acknowledged_at")
    if (
        receipt.get("schema") != ALARM_ACK_COMMIT_SCHEMA
        or receipt.get("request_id") != command.get("request_id")
        or receipt.get("request_fingerprint") != fingerprint
        or receipt.get("alarm_name") != command.get("alarm_name")
        or receipt.get("activation_id") != command.get("activation_id")
        or receipt.get("engine_instance_id") != command.get("engine_instance_id")
        or receipt.get("source_activation_id") != source_activation_id
        or type(acknowledged_at) is not float
        or not math.isfinite(acknowledged_at)
        or acknowledged_at <= 0.0
        or receipt.get("committed") is not True
    ):
        return None
    return state
