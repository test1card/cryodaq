"""Pure durable contracts for periodic PNG scheduling and delivery.

The transition functions in this module never perform I/O.  Runtime owners
must hold the periodic coordinator lease, apply one fenced transition, and
persist it with :func:`write_periodic_state`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.periodic_delivery_receipt import PeriodicDeliveryReceipt

PERIODIC_STATE_SCHEMA = 2
PERIODIC_INPUT_SCHEMA = 1
PERIODIC_RESULT_SCHEMA = 1
PERIODIC_LEADER_LOCK = ".report-locks/periodic-coordinator.lock"
PERIODIC_RENDER_LOCK = ".report-locks/periodic.lock"
MAX_UNRESOLVED_DELIVERIES = 16

_MAX_STATE_BYTES = 128 * 1024
_MAX_FUTURE_SKEW_S = 300.0
_MAX_ERROR_TEXT_BYTES = 2_048
_MAX_CAPTION_CODEPOINTS = 1_024
_MAX_CAPTION_BYTES = 4_096
_MAX_PNG_BYTES = 10 * 1024 * 1024
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_TOKEN = re.compile(r"[0-9a-f]{32}")
_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_HEALTH = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_DISPLAY_TIME = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}:[0-9]{2}")
_BOT_URL = re.compile(r"api\.telegram\.org/bot", re.IGNORECASE)
_BOT_TOKEN_SHAPE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")

_TOP_KEYS = {
    "schema",
    "high_water_slot_end",
    "active",
    "last_terminal",
    "unresolved_delivery",
    "health",
    "updated_at",
}
_HEALTH_KEYS = {"status", "error_code", "error_text", "updated_at"}
_ACTIVE_KEYS = {
    "slot_id",
    "slot_start",
    "slot_end",
    "interval_s",
    "window_start",
    "window_end",
    "display_time",
    "config_fingerprint",
    "destination_fingerprint",
    "generation_id",
    "owner_token",
    "status",
    "render_attempt_count",
    "delivery_attempt_count",
    "max_render_attempts",
    "max_delivery_attempts",
    "not_before",
    "artifact",
    "caption",
    "receipt",
    "failure_phase",
    "retryable",
    "certainty",
    "error_code",
    "error_text",
    "created_at",
    "updated_at",
    "finished_at",
}
_ARTIFACT_KEYS = {"path", "sha256", "size", "width", "height", "mime"}
_TERMINAL_KEYS = {
    "slot_id",
    "slot_end",
    "generation_id",
    "status",
    "destination_fingerprint",
    "artifact_sha256",
    "receipt",
    "failure_phase",
    "certainty",
    "error_code",
    "error_text",
    "finished_at",
}
_V1_ACTIVE_KEYS = (_ACTIVE_KEYS - {"receipt"}) | {"telegram_message_id"}
_V1_TERMINAL_KEYS = (_TERMINAL_KEYS - {"receipt"}) | {"telegram_message_id"}
_RECEIPT_KEYS = {"kind", "receipt_id", "acknowledgement_sha256"}
_UNKNOWN_KEYS = {
    "slot_id",
    "slot_end",
    "generation_id",
    "destination_fingerprint",
    "artifact_sha256",
    "ambiguity_at",
    "error_code",
    "error_text",
}
_TERMINAL_STATUSES = {"SUCCEEDED", "DELIVERY_UNKNOWN"}
_CERTAINTIES = {"not_applicable", "not_sent", "rejected", "unknown"}
_FAILURE_PHASES = {"render", "delivery", "scheduler", "config"}


class PeriodicContractError(ValueError):
    """The periodic state or requested transition violates the contract."""


class PeriodicIOError(OSError):
    """Periodic state could not be read or durably persisted."""


class PeriodicStatus(StrEnum):
    PENDING = "PENDING"
    RENDERING = "RENDERING"
    READY = "READY"
    DELIVERING = "DELIVERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"


@dataclass(frozen=True, slots=True)
class PeriodicArtifact:
    path: str
    sha256: str
    size: int
    width: int
    height: int
    mime: Literal["image/png"]


@dataclass(frozen=True, slots=True)
class PeriodicSlot:
    slot_id: str
    slot_start: int
    slot_end: int
    interval_s: int


@dataclass(frozen=True, slots=True)
class PeriodicStateDocument:
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        validated = _validate_document(self.payload)
        object.__setattr__(self, "payload", validated)


def periodic_root(data_dir: Path, *, create: bool = False) -> Path:
    """Return the contained ``reporting`` root after checking path authority."""

    data = Path(data_dir)
    if create:
        try:
            data.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PeriodicIOError("periodic data directory cannot be created") from exc
    _require_safe_directory(data, required=create)
    root = data / "reporting"
    if create:
        try:
            root.mkdir(exist_ok=True)
        except OSError as exc:
            raise PeriodicIOError("periodic reporting directory cannot be created") from exc
    _require_safe_directory(root, required=create)
    if root.exists():
        try:
            resolved_root = root.resolve(strict=True)
            resolved_data = data.resolve(strict=True)
        except OSError as exc:
            raise PeriodicIOError("periodic reporting path cannot be resolved") from exc
        if resolved_root.parent != resolved_data:
            raise PeriodicContractError("periodic reporting path escapes the data directory")
    return root


def periodic_state_path(data_dir: Path) -> Path:
    return periodic_root(data_dir) / "periodic_state.json"


def periodic_input_path(data_dir: Path, generation_id: str) -> Path:
    generation = _validated_token(generation_id, "generation_id")
    root = periodic_root(data_dir)
    parent = _safe_derived_directory(root, "periodic", "inputs")
    return parent / f"{generation}.json"


def periodic_staging_dir(data_dir: Path, generation_id: str) -> Path:
    generation = _validated_token(generation_id, "generation_id")
    root = periodic_root(data_dir)
    return _safe_derived_directory(root, "periodic", ".staging") / generation


def periodic_generation_dir(data_dir: Path, generation_id: str) -> Path:
    generation = _validated_token(generation_id, "generation_id")
    root = periodic_root(data_dir)
    return _safe_derived_directory(root, "periodic", "generations") / generation


def load_periodic_state(data_dir: Path) -> PeriodicStateDocument:
    """Load one exact state document, returning a pure empty state if absent."""

    root = periodic_root(data_dir)
    path = root / "periodic_state.json"
    if not os.path.lexists(path):
        return PeriodicStateDocument(_empty_payload(0.0))
    raw = _read_state_file(path)
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        PeriodicContractError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        raise PeriodicContractError("periodic state is not valid closed JSON") from None
    if not isinstance(payload, dict):
        raise PeriodicContractError("periodic state root must be an object")
    return PeriodicStateDocument(payload)


def write_periodic_state(
    data_dir: Path,
    state: PeriodicStateDocument,
    *,
    expected_slot_id: str | None = None,
    expected_owner_token: str | None = None,
    expected_status: PeriodicStatus | None = None,
) -> None:
    """Persist validated state with an optional exact active-owner fence."""

    expected = (expected_slot_id, expected_owner_token, expected_status)
    if any(item is not None for item in expected) and not all(item is not None for item in expected):
        raise PeriodicContractError("periodic state fence requires slot, owner, and status")
    if expected_status is not None and not isinstance(expected_status, PeriodicStatus):
        raise PeriodicContractError("periodic state fence status is invalid")
    validated = PeriodicStateDocument(state.payload)
    root = periodic_root(data_dir, create=True)
    path = root / "periodic_state.json"
    current: Mapping[str, object] | None = None
    if os.path.lexists(path):
        current = load_periodic_state(data_dir).payload
        _enforce_durable_transition(current, validated.payload)
    else:
        _enforce_initial_durable_state(validated.payload)
    if all(item is not None for item in expected):
        if current is None:
            raise PeriodicContractError("periodic state changed before fenced write")
        active = current["active"]
        if not isinstance(active, dict) or (
            active["slot_id"] != expected_slot_id
            or active["owner_token"] != expected_owner_token
            or active["status"] != expected_status.value
        ):
            raise PeriodicContractError("periodic state changed before fenced write")
    if current is not None:
        _require_safe_regular_file(path)
    text = _json_text(validated.payload)
    try:
        _atomic_write_state_strict(path, text)
        _fsync_directory_strict(root)
    except OSError as exc:
        raise PeriodicIOError("periodic state could not be persisted") from exc


def latest_completed_slot(now_epoch: float, interval_s: int) -> PeriodicSlot:
    """Return the latest UTC epoch-aligned completed slot."""

    now = _finite_time(now_epoch, "now_epoch")
    if type(interval_s) is not int or interval_s <= 0:
        raise PeriodicContractError("interval_s must be a positive integer")
    slot_end = math.floor(now / interval_s) * interval_s
    slot_start = slot_end - interval_s
    key = f"periodic-png/v1:{slot_end}".encode("ascii")
    return PeriodicSlot(
        slot_id="sha256:" + hashlib.sha256(key).hexdigest(),
        slot_start=slot_start,
        slot_end=slot_end,
        interval_s=interval_s,
    )


def allocate_pending(
    state: PeriodicStateDocument,
    slot: PeriodicSlot,
    config: PeriodicPngConfig,
    *,
    generation_id: str,
    owner_token: str,
    display_time: str,
    now: float,
    destination_fingerprint: str | None = None,
) -> PeriodicStateDocument:
    """Allocate a newer slot, or a new render attempt for one retryable slot."""

    payload = _copy_payload(state)
    timestamp = _transition_time(payload, now)
    generation = _validated_token(generation_id, "generation_id")
    owner = _validated_token(owner_token, "owner_token")
    display = _validated_display_time(display_time)
    _validate_slot(slot)
    if not isinstance(config, PeriodicPngConfig) or not config.enabled:
        raise PeriodicContractError("a validated enabled periodic config is required")
    active = payload["active"]
    high_water = payload["high_water_slot_end"]
    retry = False
    render_count = 0
    delivery_count = 0
    created_at = timestamp
    if active is not None:
        if not (
            isinstance(active, dict)
            and active["status"] == PeriodicStatus.FAILED.value
            and active["retryable"] is True
            and active["failure_phase"] == "render"
            and active["slot_id"] == slot.slot_id
            and active["slot_end"] == slot.slot_end
            and timestamp >= active["not_before"]
        ):
            raise PeriodicContractError("an active periodic slot must be rotated before allocation")
        if active["render_attempt_count"] >= active["max_render_attempts"]:
            raise PeriodicContractError("render attempts are exhausted")
        retry = True
        render_count = active["render_attempt_count"]
        delivery_count = active["delivery_attempt_count"]
        created_at = active["created_at"]
        if display != active["display_time"]:
            raise PeriodicContractError("render retry display_time must match durable slot identity")
    if retry:
        if high_water != slot.slot_end:
            raise PeriodicContractError("retry slot does not match high water")
    else:
        if high_water is not None and slot.slot_end <= high_water:
            raise PeriodicContractError("slot does not advance periodic high water")
        if active is not None:
            raise PeriodicContractError("active periodic slot blocks allocation")
        payload["high_water_slot_end"] = slot.slot_end

    destination = (
        periodic_telegram_destination_fingerprint(config.telegram_chat_id)
        if destination_fingerprint is None
        else _validated_hash(destination_fingerprint, "destination_fingerprint")
    )
    payload["active"] = {
        "slot_id": slot.slot_id,
        "slot_start": slot.slot_start,
        "slot_end": slot.slot_end,
        "interval_s": slot.interval_s,
        "window_start": slot.slot_end - config.chart_window_s,
        "window_end": slot.slot_end,
        "display_time": display,
        "config_fingerprint": config.config_fingerprint,
        "destination_fingerprint": destination,
        "generation_id": generation,
        "owner_token": owner,
        "status": PeriodicStatus.PENDING.value,
        "render_attempt_count": render_count,
        "delivery_attempt_count": delivery_count,
        "max_render_attempts": config.max_render_attempts,
        "max_delivery_attempts": config.max_delivery_attempts,
        "not_before": timestamp,
        "artifact": None,
        "caption": "",
        "receipt": None,
        "failure_phase": None,
        "retryable": None,
        "certainty": None,
        "error_code": None,
        "error_text": "",
        "created_at": created_at,
        "updated_at": timestamp,
        "finished_at": None,
    }
    payload["updated_at"] = timestamp
    return PeriodicStateDocument(payload)


def mark_rendering(
    state: PeriodicStateDocument, *, slot_id: str, owner_token: str, now: float
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(state, slot_id, owner_token, now, allowed={PeriodicStatus.PENDING})
    if active["render_attempt_count"] >= active["max_render_attempts"]:
        raise PeriodicContractError("render attempts are exhausted")
    active["status"] = PeriodicStatus.RENDERING.value
    active["render_attempt_count"] += 1
    _clear_failure(active)
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_ready(
    state: PeriodicStateDocument,
    artifact: PeriodicArtifact,
    caption: str,
    *,
    slot_id: str,
    owner_token: str,
    now: float,
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(
        state, slot_id, owner_token, now, allowed={PeriodicStatus.RENDERING}
    )
    if not isinstance(artifact, PeriodicArtifact):
        raise PeriodicContractError("artifact must be a PeriodicArtifact")
    active["artifact"] = _validate_artifact(
        {
            "path": artifact.path,
            "sha256": artifact.sha256,
            "size": artifact.size,
            "width": artifact.width,
            "height": artifact.height,
            "mime": artifact.mime,
        },
        generation_id=active["generation_id"],
    )
    active["caption"] = _validated_caption(caption)
    active["status"] = PeriodicStatus.READY.value
    active["not_before"] = timestamp
    _clear_failure(active)
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_retryable_failure(
    state: PeriodicStateDocument,
    *,
    phase: str,
    certainty: str,
    code: str,
    text: str,
    not_before: float,
    slot_id: str,
    owner_token: str,
    now: float,
) -> PeriodicStateDocument:
    phase_value, certainty_value = _validate_failure_fields(phase, certainty)
    if phase_value not in {"render", "delivery"}:
        raise PeriodicContractError("scheduler and config failures cannot be retryable")
    allowed = (
        {PeriodicStatus.PENDING, PeriodicStatus.RENDERING} if phase_value == "render" else {PeriodicStatus.DELIVERING}
    )
    payload, active, timestamp = _transition_context(
        state,
        slot_id,
        owner_token,
        now,
        allowed=allowed,
    )
    _require_phase_certainty(phase_value, certainty_value)
    if phase_value == "render" and active["status"] == PeriodicStatus.PENDING.value:
        # Input construction is part of the bounded render attempt.  Without
        # this increment a repeated pre-child I/O failure could retry forever
        # while render_attempt_count remained zero.
        active["render_attempt_count"] += 1
    attempt_count = active["render_attempt_count"] if phase_value == "render" else active["delivery_attempt_count"]
    attempt_limit = active["max_render_attempts"] if phase_value == "render" else active["max_delivery_attempts"]
    if attempt_count >= attempt_limit:
        raise PeriodicContractError("retry attempts are exhausted")
    retry_at = _finite_time(not_before, "not_before")
    if retry_at < timestamp:
        raise PeriodicContractError("retry time precedes transition time")
    active["status"] = PeriodicStatus.FAILED.value
    active["failure_phase"] = phase_value
    active["retryable"] = True
    active["certainty"] = certainty_value
    active["error_code"] = _validated_code(code, required=True)
    active["error_text"] = _validated_text(text)
    active["not_before"] = retry_at
    active["finished_at"] = None
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_terminal_failure(
    state: PeriodicStateDocument,
    *,
    phase: str,
    certainty: str,
    code: str,
    text: str,
    slot_id: str,
    owner_token: str,
    now: float,
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(
        state,
        slot_id,
        owner_token,
        now,
        allowed={
            PeriodicStatus.PENDING,
            PeriodicStatus.RENDERING,
            PeriodicStatus.READY,
            PeriodicStatus.DELIVERING,
            PeriodicStatus.FAILED,
        },
    )
    if active["status"] == PeriodicStatus.FAILED.value and active["retryable"] is not True:
        raise PeriodicContractError("periodic slot is already terminal")
    previous_status = PeriodicStatus(active["status"])
    phase_value, certainty_value = _validate_failure_fields(phase, certainty)
    _require_phase_certainty(phase_value, certainty_value)
    if previous_status is PeriodicStatus.DELIVERING and phase_value != "delivery":
        raise PeriodicContractError("an in-flight delivery requires an exact delivery outcome")
    if phase_value == "delivery" and previous_status not in {
        PeriodicStatus.DELIVERING,
        PeriodicStatus.FAILED,
    }:
        raise PeriodicContractError("delivery failure is invalid from this status")
    if phase_value == "render" and previous_status not in {
        PeriodicStatus.PENDING,
        PeriodicStatus.RENDERING,
        PeriodicStatus.FAILED,
    }:
        raise PeriodicContractError("render failure is invalid from this status")
    if previous_status is PeriodicStatus.FAILED and active["failure_phase"] != phase_value:
        raise PeriodicContractError("terminal exhaustion must preserve the retry phase")
    if phase_value == "render" and previous_status is PeriodicStatus.PENDING:
        if active["render_attempt_count"] < active["max_render_attempts"]:
            active["render_attempt_count"] += 1
    active["status"] = PeriodicStatus.FAILED.value
    active["failure_phase"] = phase_value
    active["retryable"] = False
    active["certainty"] = certainty_value
    active["error_code"] = _validated_code(code, required=True)
    active["error_text"] = _validated_text(text)
    active["finished_at"] = timestamp
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_delivering(
    state: PeriodicStateDocument, *, slot_id: str, owner_token: str, now: float
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(
        state,
        slot_id,
        owner_token,
        now,
        allowed={PeriodicStatus.READY, PeriodicStatus.FAILED},
    )
    if active["status"] == PeriodicStatus.FAILED.value and not (
        active["retryable"] is True and active["failure_phase"] == "delivery" and timestamp >= active["not_before"]
    ):
        raise PeriodicContractError("only a due delivery failure can be redelivered")
    if active["artifact"] is None:
        raise PeriodicContractError("delivery requires a verified artifact")
    if len(payload["unresolved_delivery"]) >= MAX_UNRESOLVED_DELIVERIES:
        active["status"] = PeriodicStatus.READY.value
        active["not_before"] = timestamp
        _clear_failure(active)
        payload["health"] = _health_payload(
            "paused_unknown_capacity",
            "delivery_paused_unknown_capacity",
            "delivery paused because unresolved evidence capacity is full",
            timestamp,
        )
        _touch(payload, active, timestamp)
        return PeriodicStateDocument(payload)
    if active["delivery_attempt_count"] >= active["max_delivery_attempts"]:
        raise PeriodicContractError("delivery attempts are exhausted")
    active["status"] = PeriodicStatus.DELIVERING.value
    active["delivery_attempt_count"] += 1
    _clear_failure(active)
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_succeeded(
    state: PeriodicStateDocument,
    *,
    receipt: PeriodicDeliveryReceipt,
    slot_id: str,
    owner_token: str,
    now: float,
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(
        state, slot_id, owner_token, now, allowed={PeriodicStatus.DELIVERING}
    )
    if not isinstance(receipt, PeriodicDeliveryReceipt):
        raise PeriodicContractError("a validated delivery receipt is required")
    active["status"] = PeriodicStatus.SUCCEEDED.value
    active["receipt"] = receipt.as_dict()
    active["finished_at"] = timestamp
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def mark_delivery_unknown(
    state: PeriodicStateDocument,
    *,
    code: str,
    text: str,
    slot_id: str,
    owner_token: str,
    now: float,
) -> PeriodicStateDocument:
    payload, active, timestamp = _transition_context(
        state, slot_id, owner_token, now, allowed={PeriodicStatus.DELIVERING}
    )
    ledger = payload["unresolved_delivery"]
    if len(ledger) >= MAX_UNRESOLVED_DELIVERIES:
        raise PeriodicContractError("unresolved delivery ledger has no safe capacity")
    error_code = _validated_code(code, required=True)
    error_text = _validated_text(text)
    artifact = active["artifact"]
    if not isinstance(artifact, dict):
        raise PeriodicContractError("ambiguous delivery lacks artifact evidence")
    entry = {
        "slot_id": active["slot_id"],
        "slot_end": active["slot_end"],
        "generation_id": active["generation_id"],
        "destination_fingerprint": active["destination_fingerprint"],
        "artifact_sha256": artifact["sha256"],
        "ambiguity_at": timestamp,
        "error_code": error_code,
        "error_text": error_text,
    }
    if any(item["slot_id"] == active["slot_id"] for item in ledger):
        raise PeriodicContractError("unresolved delivery evidence already exists")
    ledger.append(entry)
    active["status"] = PeriodicStatus.DELIVERY_UNKNOWN.value
    active["failure_phase"] = "delivery"
    active["retryable"] = False
    active["certainty"] = "unknown"
    active["error_code"] = error_code
    active["error_text"] = error_text
    active["finished_at"] = timestamp
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def supersede_active(state: PeriodicStateDocument, *, newer_slot_end: int, now: float) -> PeriodicStateDocument:
    payload = _copy_payload(state)
    active = payload["active"]
    timestamp = _transition_time(payload, now)
    if not isinstance(active, dict):
        raise PeriodicContractError("there is no active periodic slot")
    if type(newer_slot_end) is not int or newer_slot_end <= active["slot_end"]:
        raise PeriodicContractError("supersession requires a strictly newer slot")
    if active["status"] == PeriodicStatus.DELIVERING.value:
        raise PeriodicContractError("an in-flight delivery cannot be superseded")
    if _is_terminal(active):
        raise PeriodicContractError("terminal periodic slot must be rotated")
    if (
        active["status"] == PeriodicStatus.READY.value
        and len(payload["unresolved_delivery"]) >= MAX_UNRESOLVED_DELIVERIES
    ):
        payload["health"] = _health_payload(
            "paused_unknown_capacity",
            "delivery_paused_unknown_capacity",
            "delivery paused because unresolved evidence capacity is full",
            timestamp,
        )
        _touch(payload, active, timestamp)
        return PeriodicStateDocument(payload)
    active["status"] = PeriodicStatus.FAILED.value
    active["failure_phase"] = "scheduler"
    active["retryable"] = False
    active["certainty"] = "not_applicable"
    active["error_code"] = "superseded_by_newer_slot"
    active["error_text"] = "slot was superseded by a newer completed interval"
    active["finished_at"] = timestamp
    _touch(payload, active, timestamp)
    return PeriodicStateDocument(payload)


def rotate_terminal_active(state: PeriodicStateDocument, *, now: float) -> PeriodicStateDocument:
    payload = _copy_payload(state)
    active = payload["active"]
    timestamp = _transition_time(payload, now)
    if not isinstance(active, dict) or not _is_terminal(active):
        raise PeriodicContractError("only a terminal periodic slot can be rotated")
    payload["last_terminal"] = _terminal_summary(active)
    payload["active"] = None
    payload["updated_at"] = timestamp
    return PeriodicStateDocument(payload)


def set_periodic_health(
    state: PeriodicStateDocument,
    *,
    status: str,
    code: str | None,
    text: str,
    now: float,
) -> PeriodicStateDocument:
    payload = _copy_payload(state)
    timestamp = _transition_time(payload, now)
    payload["health"] = _health_payload(status, code, text, timestamp)
    payload["updated_at"] = timestamp
    return PeriodicStateDocument(payload)


def _empty_payload(now: float) -> dict[str, object]:
    return {
        "schema": PERIODIC_STATE_SCHEMA,
        "high_water_slot_end": None,
        "active": None,
        "last_terminal": None,
        "unresolved_delivery": [],
        "health": _health_payload("starting", None, "", now),
        "updated_at": now,
    }


def _copy_payload(state: PeriodicStateDocument) -> dict[str, Any]:
    if not isinstance(state, PeriodicStateDocument):
        raise PeriodicContractError("state must be a PeriodicStateDocument")
    return copy.deepcopy(_validate_document(state.payload))


def _transition_context(
    state: PeriodicStateDocument,
    slot_id: str,
    owner_token: str,
    now: float,
    *,
    allowed: set[PeriodicStatus],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    payload = _copy_payload(state)
    active = payload["active"]
    timestamp = _transition_time(payload, now)
    if not isinstance(active, dict):
        raise PeriodicContractError("there is no active periodic slot")
    if active["slot_id"] != _validated_hash(slot_id, "slot_id"):
        raise PeriodicContractError("periodic slot fence does not match")
    if active["owner_token"] != _validated_token(owner_token, "owner_token"):
        raise PeriodicContractError("periodic owner fence does not match")
    if PeriodicStatus(active["status"]) not in allowed:
        raise PeriodicContractError("periodic transition is not allowed from this status")
    if timestamp < active["updated_at"]:
        raise PeriodicContractError("transition time precedes active state")
    return payload, active, timestamp


def _touch(payload: dict[str, Any], active: dict[str, Any], now: float) -> None:
    active["updated_at"] = now
    payload["updated_at"] = now


def _clear_failure(active: dict[str, Any]) -> None:
    active["failure_phase"] = None
    active["retryable"] = None
    active["certainty"] = None
    active["error_code"] = None
    active["error_text"] = ""
    active["finished_at"] = None


def _validate_document(value: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _TOP_KEYS:
        raise PeriodicContractError("periodic state has an invalid top-level schema")
    payload = copy.deepcopy(dict(value))
    if type(payload["schema"]) is not int:
        raise PeriodicContractError("unsupported periodic state schema")
    if payload["schema"] == 1:
        payload = _migrate_v1_document(payload)
    elif payload["schema"] != PERIODIC_STATE_SCHEMA:
        raise PeriodicContractError("unsupported periodic state schema")
    high_water = payload["high_water_slot_end"]
    if high_water is not None and (type(high_water) is not int or high_water < 0):
        raise PeriodicContractError("invalid periodic high water")
    active = payload["active"]
    if active is not None:
        payload["active"] = _validate_active(active, high_water)
    terminal = payload["last_terminal"]
    if terminal is not None:
        payload["last_terminal"] = _validate_terminal(terminal, high_water)
    ledger = payload["unresolved_delivery"]
    if not isinstance(ledger, list) or len(ledger) > MAX_UNRESOLVED_DELIVERIES:
        raise PeriodicContractError("invalid unresolved delivery ledger")
    validated_ledger = [_validate_unknown(item, high_water) for item in ledger]
    slot_ids = [item["slot_id"] for item in validated_ledger]
    if len(slot_ids) != len(set(slot_ids)):
        raise PeriodicContractError("unresolved delivery ledger contains duplicate slots")
    payload["unresolved_delivery"] = validated_ledger
    payload["health"] = _validate_health(payload["health"])
    updated = _finite_time(payload["updated_at"], "updated_at")
    payload["updated_at"] = updated
    if payload["health"]["updated_at"] > updated:
        raise PeriodicContractError("health timestamp exceeds state timestamp")
    if isinstance(payload["active"], dict) and payload["active"]["updated_at"] > updated:
        raise PeriodicContractError("active timestamp exceeds state timestamp")
    if isinstance(payload["last_terminal"], dict) and payload["last_terminal"]["finished_at"] > updated:
        raise PeriodicContractError("terminal timestamp exceeds state timestamp")
    if any(item["ambiguity_at"] > updated for item in validated_ledger):
        raise PeriodicContractError("unresolved evidence timestamp exceeds state timestamp")
    if isinstance(payload["active"], dict) and payload["active"]["status"] == "DELIVERY_UNKNOWN":
        evidence = _evidence_for_slot(validated_ledger, payload["active"]["slot_id"])
        if evidence is None:
            raise PeriodicContractError("unknown active state lacks durable evidence")
        _require_unknown_matches_active(payload["active"], evidence)
    if isinstance(payload["last_terminal"], dict) and payload["last_terminal"]["status"] == "DELIVERY_UNKNOWN":
        evidence = _evidence_for_slot(validated_ledger, payload["last_terminal"]["slot_id"])
        if evidence is None:
            raise PeriodicContractError("unknown terminal summary lacks durable evidence")
        _require_unknown_matches_terminal(payload["last_terminal"], evidence)
    if isinstance(payload["active"], dict) and payload["active"]["status"] == "DELIVERING":
        if len(validated_ledger) >= MAX_UNRESOLVED_DELIVERIES:
            raise PeriodicContractError("DELIVERING state lacks ambiguity capacity")
        if payload["active"]["slot_id"] in slot_ids:
            raise PeriodicContractError("DELIVERING state already has ambiguity evidence")
    try:
        encoded = _json_text(payload).encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise PeriodicContractError("periodic state contains invalid UTF-8") from None
    if len(encoded) > _MAX_STATE_BYTES:
        raise PeriodicContractError("periodic state exceeds 128 KiB")
    return payload


def _migrate_v1_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the closed v1 shape and return its exact in-memory v2 meaning."""

    migrated = copy.deepcopy(payload)
    active = migrated["active"]
    if active is not None:
        if not isinstance(active, dict) or set(active) != _V1_ACTIVE_KEYS:
            raise PeriodicContractError("v1 active periodic slot has an invalid schema")
        message_id = active.pop("telegram_message_id")
        active["receipt"] = _migrated_telegram_receipt(message_id)
    terminal = migrated["last_terminal"]
    if terminal is not None:
        if not isinstance(terminal, dict) or set(terminal) != _V1_TERMINAL_KEYS:
            raise PeriodicContractError("v1 terminal summary has an invalid schema")
        message_id = terminal.pop("telegram_message_id")
        terminal["receipt"] = _migrated_telegram_receipt(message_id)
    migrated["schema"] = PERIODIC_STATE_SCHEMA
    return migrated


def _migrated_telegram_receipt(value: object) -> dict[str, str | None] | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= 9_223_372_036_854_775_807:
        raise PeriodicContractError("v1 Telegram message ID is invalid")
    return PeriodicDeliveryReceipt("telegram", str(value), None).as_dict()


def _validate_receipt(value: object) -> dict[str, str | None] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_KEYS:
        raise PeriodicContractError("delivery receipt has an invalid schema")
    try:
        receipt = PeriodicDeliveryReceipt(
            kind=value["kind"],  # type: ignore[arg-type]
            receipt_id=value["receipt_id"],  # type: ignore[arg-type]
            acknowledgement_sha256=value["acknowledgement_sha256"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        raise PeriodicContractError("delivery receipt is invalid") from None
    return receipt.as_dict()


def _validate_active(value: object, high_water: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ACTIVE_KEYS:
        raise PeriodicContractError("active periodic slot has an invalid schema")
    active = dict(value)
    slot_id = _validated_hash(active["slot_id"], "slot_id")
    slot_start = _exact_int(active["slot_start"], "slot_start")
    slot_end = _exact_int(active["slot_end"], "slot_end")
    interval = _exact_int(active["interval_s"], "interval_s", minimum=1)
    if slot_end <= slot_start or slot_end - slot_start != interval:
        raise PeriodicContractError("active slot interval is inconsistent")
    if slot_end % interval != 0:
        raise PeriodicContractError("active slot is not UTC epoch aligned")
    expected_slot_id = "sha256:" + hashlib.sha256(f"periodic-png/v1:{slot_end}".encode("ascii")).hexdigest()
    if slot_id != expected_slot_id:
        raise PeriodicContractError("active slot identity is inconsistent")
    window_start = _exact_int(active["window_start"], "window_start")
    window_end = _exact_int(active["window_end"], "window_end")
    if window_end != slot_end or window_start >= window_end:
        raise PeriodicContractError("active chart window is inconsistent")
    active["display_time"] = _validated_display_time(active["display_time"])
    if high_water is None or slot_end > high_water:
        raise PeriodicContractError("active slot exceeds periodic high water")
    active["slot_id"] = slot_id
    active["config_fingerprint"] = _validated_hash(active["config_fingerprint"], "config_fingerprint")
    active["destination_fingerprint"] = _validated_hash(active["destination_fingerprint"], "destination_fingerprint")
    generation = _validated_token(active["generation_id"], "generation_id")
    active["generation_id"] = generation
    active["owner_token"] = _validated_token(active["owner_token"], "owner_token")
    try:
        status = PeriodicStatus(active["status"])
    except (ValueError, TypeError):
        raise PeriodicContractError("active periodic status is invalid") from None
    for field in ("render_attempt_count", "delivery_attempt_count"):
        active[field] = _exact_int(active[field], field, minimum=0, maximum=10)
    for field in ("max_render_attempts", "max_delivery_attempts"):
        active[field] = _exact_int(active[field], field, minimum=1, maximum=10)
    if (
        active["render_attempt_count"] > active["max_render_attempts"]
        or active["delivery_attempt_count"] > active["max_delivery_attempts"]
    ):
        raise PeriodicContractError("periodic attempt count exceeds its limit")
    active["not_before"] = _finite_time(active["not_before"], "not_before")
    artifact = active["artifact"]
    active["artifact"] = None if artifact is None else _validate_artifact(artifact, generation_id=generation)
    active["caption"] = _validated_caption(active["caption"])
    receipt = _validate_receipt(active["receipt"])
    active["receipt"] = receipt
    active["failure_phase"] = _optional_choice(active["failure_phase"], _FAILURE_PHASES, "failure_phase")
    retryable = active["retryable"]
    if retryable is not None and type(retryable) is not bool:
        raise PeriodicContractError("retryable must be a boolean or null")
    active["certainty"] = _optional_choice(active["certainty"], _CERTAINTIES, "certainty")
    active["error_code"] = _validated_code(active["error_code"], required=False)
    active["error_text"] = _validated_text(active["error_text"])
    created = _finite_time(active["created_at"], "created_at")
    updated = _finite_time(active["updated_at"], "updated_at")
    finished = active["finished_at"]
    if finished is not None:
        finished = _finite_time(finished, "finished_at")
    if updated < created or (finished is not None and finished < updated):
        raise PeriodicContractError("active timestamps are inconsistent")
    active["created_at"], active["updated_at"], active["finished_at"] = created, updated, finished

    needs_artifact = status in {
        PeriodicStatus.READY,
        PeriodicStatus.DELIVERING,
        PeriodicStatus.SUCCEEDED,
        PeriodicStatus.DELIVERY_UNKNOWN,
    } or (status is PeriodicStatus.FAILED and active["failure_phase"] == "delivery")
    if needs_artifact and active["artifact"] is None:
        raise PeriodicContractError("active status requires a verified artifact")
    if status in {PeriodicStatus.PENDING, PeriodicStatus.RENDERING} and (
        active["artifact"] is not None or active["caption"]
    ):
        raise PeriodicContractError("pre-render state contains artifact evidence")
    if status is PeriodicStatus.SUCCEEDED:
        if receipt is None or finished is None:
            raise PeriodicContractError("SUCCEEDED state lacks terminal evidence")
    elif receipt is not None:
        raise PeriodicContractError("only SUCCEEDED may contain a delivery receipt")
    if status is PeriodicStatus.FAILED:
        if (
            active["failure_phase"] is None
            or type(active["retryable"]) is not bool
            or active["certainty"] is None
            or active["error_code"] is None
        ):
            raise PeriodicContractError("FAILED state lacks exact failure evidence")
        _require_phase_certainty(active["failure_phase"], active["certainty"])
        if active["retryable"] is True and finished is not None:
            raise PeriodicContractError("retryable FAILED state cannot be terminal")
        if active["retryable"] is False and finished is None:
            raise PeriodicContractError("terminal FAILED state lacks finished_at")
        if active["retryable"] is True:
            if active["failure_phase"] not in {"render", "delivery"}:
                raise PeriodicContractError("only render or delivery failures may be retryable")
            attempts = (
                active["render_attempt_count"]
                if active["failure_phase"] == "render"
                else active["delivery_attempt_count"]
            )
            limit = (
                active["max_render_attempts"]
                if active["failure_phase"] == "render"
                else active["max_delivery_attempts"]
            )
            if attempts >= limit:
                raise PeriodicContractError("retryable FAILED state has exhausted attempts")
    elif status is PeriodicStatus.DELIVERY_UNKNOWN:
        if not (
            active["failure_phase"] == "delivery"
            and active["retryable"] is False
            and active["certainty"] == "unknown"
            and active["error_code"] is not None
            and finished is not None
        ):
            raise PeriodicContractError("DELIVERY_UNKNOWN lacks exact ambiguity evidence")
    elif (
        any(active[field] is not None for field in ("failure_phase", "retryable", "certainty", "error_code"))
        or active["error_text"]
    ):
        raise PeriodicContractError("non-failure state contains failure evidence")
    if status not in {PeriodicStatus.SUCCEEDED, PeriodicStatus.FAILED, PeriodicStatus.DELIVERY_UNKNOWN}:
        if finished is not None:
            raise PeriodicContractError("nonterminal state contains finished_at")
    if (
        status
        in {
            PeriodicStatus.RENDERING,
            PeriodicStatus.READY,
            PeriodicStatus.DELIVERING,
            PeriodicStatus.SUCCEEDED,
            PeriodicStatus.DELIVERY_UNKNOWN,
        }
        and active["render_attempt_count"] < 1
    ):
        raise PeriodicContractError("active status lacks render-attempt evidence")
    if (
        status
        in {
            PeriodicStatus.DELIVERING,
            PeriodicStatus.SUCCEEDED,
            PeriodicStatus.DELIVERY_UNKNOWN,
        }
        and active["delivery_attempt_count"] < 1
    ):
        raise PeriodicContractError("active status lacks delivery-attempt evidence")
    if status is PeriodicStatus.FAILED and active["failure_phase"] == "delivery":
        if active["delivery_attempt_count"] < 1:
            raise PeriodicContractError("delivery failure lacks attempt evidence")
    if status is PeriodicStatus.FAILED and active["failure_phase"] == "render":
        if active["render_attempt_count"] < 1:
            raise PeriodicContractError("render failure lacks attempt evidence")
        if active["artifact"] is not None or active["caption"]:
            raise PeriodicContractError("render failure contains artifact evidence")
    return active


def _validate_artifact(value: object, *, generation_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ARTIFACT_KEYS:
        raise PeriodicContractError("periodic artifact has an invalid schema")
    artifact = dict(value)
    expected_path = f"periodic/generations/{generation_id}/periodic.png"
    if artifact["path"] != expected_path:
        raise PeriodicContractError("periodic artifact path is not authoritative")
    artifact["sha256"] = _validated_hash(artifact["sha256"], "artifact sha256")
    artifact["size"] = _exact_int(artifact["size"], "artifact size", minimum=33, maximum=_MAX_PNG_BYTES)
    artifact["width"] = _exact_int(artifact["width"], "artifact width", minimum=100, maximum=10_000)
    artifact["height"] = _exact_int(artifact["height"], "artifact height", minimum=100, maximum=10_000)
    if artifact["width"] + artifact["height"] > 10_000 or artifact["width"] * artifact["height"] > 50_000_000:
        raise PeriodicContractError("periodic artifact dimensions exceed delivery bounds")
    if artifact["mime"] != "image/png":
        raise PeriodicContractError("periodic artifact MIME type is invalid")
    return artifact


def _validate_terminal(value: object, high_water: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _TERMINAL_KEYS:
        raise PeriodicContractError("last terminal summary has an invalid schema")
    item = dict(value)
    item["slot_id"] = _validated_hash(item["slot_id"], "terminal slot_id")
    item["slot_end"] = _exact_int(item["slot_end"], "terminal slot_end")
    _require_slot_identity(item["slot_id"], item["slot_end"])
    if high_water is None or item["slot_end"] > high_water:
        raise PeriodicContractError("last terminal summary exceeds high water")
    item["generation_id"] = _validated_token(item["generation_id"], "terminal generation_id")
    if item["status"] not in _TERMINAL_STATUSES | {"FAILED"}:
        raise PeriodicContractError("last terminal status is invalid")
    item["destination_fingerprint"] = _validated_hash(
        item["destination_fingerprint"], "terminal destination fingerprint"
    )
    if item["artifact_sha256"] is not None:
        item["artifact_sha256"] = _validated_hash(item["artifact_sha256"], "terminal artifact hash")
    receipt = _validate_receipt(item["receipt"])
    item["receipt"] = receipt
    item["failure_phase"] = _optional_choice(item["failure_phase"], _FAILURE_PHASES, "failure_phase")
    item["certainty"] = _optional_choice(item["certainty"], _CERTAINTIES, "certainty")
    item["error_code"] = _validated_code(item["error_code"], required=False)
    item["error_text"] = _validated_text(item["error_text"])
    item["finished_at"] = _finite_time(item["finished_at"], "finished_at")
    if item["status"] == "SUCCEEDED" and (
        receipt is None
        or item["artifact_sha256"] is None
        or item["failure_phase"] is not None
        or item["certainty"] is not None
        or item["error_code"] is not None
        or item["error_text"]
    ):
        raise PeriodicContractError("SUCCEEDED terminal summary is inconsistent")
    if item["status"] != "SUCCEEDED" and receipt is not None:
        raise PeriodicContractError("failed terminal summary contains delivery receipt")
    if item["status"] == "FAILED" and (
        item["failure_phase"] is None or item["certainty"] is None or item["error_code"] is None
    ):
        raise PeriodicContractError("FAILED terminal summary lacks failure evidence")
    if item["status"] == "FAILED":
        _require_phase_certainty(item["failure_phase"], item["certainty"])
    if item["status"] == "DELIVERY_UNKNOWN" and not (
        item["failure_phase"] == "delivery"
        and item["certainty"] == "unknown"
        and item["error_code"] is not None
        and item["artifact_sha256"] is not None
    ):
        raise PeriodicContractError("unknown terminal summary lacks ambiguity evidence")
    return item


def _validate_unknown(value: object, high_water: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _UNKNOWN_KEYS:
        raise PeriodicContractError("unresolved delivery entry has an invalid schema")
    item = dict(value)
    item["slot_id"] = _validated_hash(item["slot_id"], "unresolved slot_id")
    item["slot_end"] = _exact_int(item["slot_end"], "unresolved slot_end")
    _require_slot_identity(item["slot_id"], item["slot_end"])
    if high_water is None or item["slot_end"] > high_water:
        raise PeriodicContractError("unresolved entry exceeds high water")
    item["generation_id"] = _validated_token(item["generation_id"], "unresolved generation_id")
    item["destination_fingerprint"] = _validated_hash(
        item["destination_fingerprint"], "unresolved destination fingerprint"
    )
    item["artifact_sha256"] = _validated_hash(item["artifact_sha256"], "unresolved artifact hash")
    item["ambiguity_at"] = _finite_time(item["ambiguity_at"], "ambiguity_at")
    item["error_code"] = _validated_code(item["error_code"], required=True)
    item["error_text"] = _validated_text(item["error_text"])
    return item


def _evidence_for_slot(ledger: list[dict[str, Any]], slot_id: str) -> dict[str, Any] | None:
    return next((item for item in ledger if item["slot_id"] == slot_id), None)


def _require_unknown_matches_active(active: Mapping[str, object], evidence: Mapping[str, object]) -> None:
    artifact = active["artifact"]
    if not isinstance(artifact, Mapping):
        raise PeriodicContractError("unknown active state lacks artifact evidence")
    expected = {
        "slot_id": active["slot_id"],
        "slot_end": active["slot_end"],
        "generation_id": active["generation_id"],
        "destination_fingerprint": active["destination_fingerprint"],
        "artifact_sha256": artifact["sha256"],
        "ambiguity_at": active["finished_at"],
        "error_code": active["error_code"],
        "error_text": active["error_text"],
    }
    if dict(evidence) != expected:
        raise PeriodicContractError("unknown active state does not match durable evidence")


def _require_unknown_matches_terminal(terminal: Mapping[str, object], evidence: Mapping[str, object]) -> None:
    expected = {
        "slot_id": terminal["slot_id"],
        "slot_end": terminal["slot_end"],
        "generation_id": terminal["generation_id"],
        "destination_fingerprint": terminal["destination_fingerprint"],
        "artifact_sha256": terminal["artifact_sha256"],
        "ambiguity_at": terminal["finished_at"],
        "error_code": terminal["error_code"],
        "error_text": terminal["error_text"],
    }
    if dict(evidence) != expected:
        raise PeriodicContractError("unknown terminal summary does not match durable evidence")


def _validate_health(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _HEALTH_KEYS:
        raise PeriodicContractError("periodic health has an invalid schema")
    return _health_payload(value["status"], value["error_code"], value["error_text"], value["updated_at"])


def _health_payload(status: object, code: object, text: object, now: object) -> dict[str, Any]:
    if not isinstance(status, str) or not _HEALTH.fullmatch(status):
        raise PeriodicContractError("periodic health status is invalid")
    return {
        "status": status,
        "error_code": _validated_code(code, required=False),
        "error_text": _validated_text(text),
        "updated_at": _finite_time(now, "health updated_at"),
    }


def _terminal_summary(active: dict[str, Any]) -> dict[str, Any]:
    artifact = active["artifact"]
    return {
        "slot_id": active["slot_id"],
        "slot_end": active["slot_end"],
        "generation_id": active["generation_id"],
        "status": active["status"],
        "destination_fingerprint": active["destination_fingerprint"],
        "artifact_sha256": artifact["sha256"] if isinstance(artifact, dict) else None,
        "receipt": active["receipt"],
        "failure_phase": active["failure_phase"],
        "certainty": active["certainty"],
        "error_code": active["error_code"],
        "error_text": active["error_text"],
        "finished_at": active["finished_at"],
    }


def _is_terminal(active: Mapping[str, object]) -> bool:
    return active["status"] in _TERMINAL_STATUSES or (
        active["status"] == PeriodicStatus.FAILED.value and active["retryable"] is False
    )


def periodic_telegram_destination_fingerprint(chat_id: int | str) -> str:
    canonical = json.dumps(
        {"schema": "periodic-png-destination/v1", "chat_id": chat_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def periodic_local_destination_fingerprint(nonce: str) -> str:
    if type(nonce) is not str or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise PeriodicContractError("soak-local destination nonce is invalid")
    return "sha256:" + hashlib.sha256(f"soak-local/v1:{nonce}".encode("ascii")).hexdigest()


def _validate_slot(slot: PeriodicSlot) -> None:
    if not isinstance(slot, PeriodicSlot):
        raise PeriodicContractError("slot must be a PeriodicSlot")
    _validated_hash(slot.slot_id, "slot_id")
    if type(slot.slot_start) is not int or type(slot.slot_end) is not int or type(slot.interval_s) is not int:
        raise PeriodicContractError("slot boundaries must be integers")
    if slot.slot_end - slot.slot_start != slot.interval_s or slot.interval_s <= 0:
        raise PeriodicContractError("slot interval is inconsistent")
    expected = latest_completed_slot(float(slot.slot_end), slot.interval_s)
    if expected != slot:
        raise PeriodicContractError("slot is not UTC epoch aligned")


def _validated_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise PeriodicContractError(f"{field} is invalid")
    return value


def _validated_token(value: object, field: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise PeriodicContractError(f"{field} is invalid")
    return value


def _validated_display_time(value: object) -> str:
    if not isinstance(value, str) or not _DISPLAY_TIME.fullmatch(value):
        raise PeriodicContractError("display_time must use DD.MM.YYYY HH:MM")
    try:
        datetime(
            int(value[6:10]),
            int(value[3:5]),
            int(value[0:2]),
            int(value[11:13]),
            int(value[14:16]),
        )
    except ValueError:
        raise PeriodicContractError("display_time is not a valid calendar time") from None
    return value


def _validated_code(value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise PeriodicContractError("periodic error code is invalid")
    return value


def _validated_text(value: object) -> str:
    if not isinstance(value, str):
        raise PeriodicContractError("periodic error text is invalid or oversized")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise PeriodicContractError("periodic error text is invalid or oversized") from None
    if len(encoded) > _MAX_ERROR_TEXT_BYTES:
        raise PeriodicContractError("periodic error text is invalid or oversized")
    if _BOT_URL.search(value) or _BOT_TOKEN_SHAPE.search(value):
        raise PeriodicContractError("sensitive text is not permitted in periodic state")
    return value


def _validated_caption(value: object) -> str:
    if not isinstance(value, str):
        raise PeriodicContractError("periodic caption must be a string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise PeriodicContractError("periodic caption is not valid UTF-8") from None
    if len(value) > _MAX_CAPTION_CODEPOINTS or len(encoded) > _MAX_CAPTION_BYTES:
        raise PeriodicContractError("periodic caption exceeds delivery bounds")
    if _BOT_URL.search(value) or _BOT_TOKEN_SHAPE.search(value):
        raise PeriodicContractError("sensitive text is not permitted in periodic caption")
    return value


def _validate_failure_fields(phase: object, certainty: object) -> tuple[str, str]:
    phase_value = _optional_choice(phase, _FAILURE_PHASES, "failure_phase")
    certainty_value = _optional_choice(certainty, _CERTAINTIES, "certainty")
    if phase_value is None or certainty_value is None:
        raise PeriodicContractError("failure phase and certainty are required")
    return phase_value, certainty_value


def _require_phase_certainty(phase: str, certainty: str) -> None:
    if certainty == "unknown":
        raise PeriodicContractError("ambiguous delivery must use DELIVERY_UNKNOWN")
    if phase == "delivery":
        if certainty not in {"not_sent", "rejected"}:
            raise PeriodicContractError("delivery failure has an invalid certainty")
    elif certainty != "not_applicable":
        raise PeriodicContractError("non-delivery failure has an invalid certainty")


def _require_slot_identity(slot_id: str, slot_end: int) -> None:
    expected = "sha256:" + hashlib.sha256(f"periodic-png/v1:{slot_end}".encode("ascii")).hexdigest()
    if slot_id != expected:
        raise PeriodicContractError("periodic slot identity does not match its end")


def _optional_choice(value: object, choices: set[str], field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in choices:
        raise PeriodicContractError(f"{field} is invalid")
    return value


def _exact_int(value: object, field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if type(value) is not int:
        raise PeriodicContractError(f"{field} must be an integer")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise PeriodicContractError(f"{field} is outside its range")
    return value


def _finite_time(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PeriodicContractError(f"{field} must be a finite timestamp")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise PeriodicContractError(f"{field} must be a finite timestamp") from None
    if not math.isfinite(result) or result < 0:
        raise PeriodicContractError(f"{field} must be a finite nonnegative timestamp")
    return result


def _transition_time(payload: Mapping[str, object], value: object) -> float:
    result = _finite_time(value, "now")
    previous = _finite_time(payload["updated_at"], "updated_at")
    if result < previous:
        raise PeriodicContractError("transition time precedes durable state")
    return result


_FAILURE_DELTA_FIELDS = {
    "failure_phase",
    "retryable",
    "certainty",
    "error_code",
    "error_text",
    "finished_at",
}
_ACTIVE_EDGE_DELTAS: dict[tuple[str, str], set[str]] = {
    ("PENDING", "RENDERING"): {"status", "render_attempt_count", "updated_at"},
    ("PENDING", "FAILED"): {
        "status",
        "render_attempt_count",
        "not_before",
        "updated_at",
    }
    | _FAILURE_DELTA_FIELDS,
    ("RENDERING", "READY"): {
        "status",
        "not_before",
        "artifact",
        "caption",
        "updated_at",
    },
    ("RENDERING", "FAILED"): {"status", "not_before", "updated_at"} | _FAILURE_DELTA_FIELDS,
    ("READY", "READY"): {"not_before", "updated_at"},
    ("READY", "DELIVERING"): {"status", "delivery_attempt_count", "updated_at"},
    ("READY", "FAILED"): {"status", "updated_at"} | _FAILURE_DELTA_FIELDS,
    ("DELIVERING", "SUCCEEDED"): {
        "status",
        "receipt",
        "updated_at",
        "finished_at",
    },
    ("DELIVERING", "FAILED"): {"status", "not_before", "updated_at"} | _FAILURE_DELTA_FIELDS,
    ("DELIVERING", "DELIVERY_UNKNOWN"): {"status", "updated_at"} | _FAILURE_DELTA_FIELDS,
    ("FAILED", "PENDING"): {
        "window_start",
        "config_fingerprint",
        "destination_fingerprint",
        "generation_id",
        "owner_token",
        "status",
        "max_render_attempts",
        "max_delivery_attempts",
        "not_before",
        "artifact",
        "caption",
        "receipt",
        "updated_at",
    }
    | _FAILURE_DELTA_FIELDS,
    ("FAILED", "READY"): {"status", "not_before", "updated_at"} | _FAILURE_DELTA_FIELDS,
    ("FAILED", "DELIVERING"): {
        "status",
        "delivery_attempt_count",
        "updated_at",
    }
    | _FAILURE_DELTA_FIELDS,
    ("FAILED", "FAILED"): {"updated_at"} | _FAILURE_DELTA_FIELDS,
}


def _enforce_durable_transition(current: Mapping[str, object], candidate: Mapping[str, object]) -> None:
    """Require candidate to be one exact pure-helper successor of current."""

    if candidate["updated_at"] < current["updated_at"]:
        raise PeriodicContractError("periodic durable time cannot decrease")
    old_high = current["high_water_slot_end"]
    new_high = candidate["high_water_slot_end"]
    if old_high is not None and (new_high is None or new_high < old_high):
        raise PeriodicContractError("periodic high water cannot decrease")
    if old_high != new_high and not (
        current["active"] is None
        and isinstance(candidate["active"], Mapping)
        and candidate["active"]["status"] == PeriodicStatus.PENDING.value
        and candidate["active"]["slot_end"] == new_high
    ):
        raise PeriodicContractError("periodic high water may advance only with a matching new PENDING slot")
    old_entries = current["unresolved_delivery"]
    new_entries = candidate["unresolved_delivery"]
    assert isinstance(old_entries, list) and isinstance(new_entries, list)
    if new_entries[: len(old_entries)] != old_entries:
        raise PeriodicContractError("unresolved delivery evidence is immutable")
    if len(new_entries) - len(old_entries) not in {0, 1}:
        raise PeriodicContractError("only one unresolved delivery may be recorded atomically")
    if len(new_entries) == len(old_entries) + 1:
        before = current["active"]
        after = candidate["active"]
        if not (
            isinstance(before, Mapping)
            and isinstance(after, Mapping)
            and before["status"] == PeriodicStatus.DELIVERING.value
            and after["status"] == PeriodicStatus.DELIVERY_UNKNOWN.value
        ):
            raise PeriodicContractError("unresolved delivery evidence requires exact DELIVERING recovery")

    if candidate == current:
        return
    if _matches_health_only_transition(current, candidate):
        return

    before = current["active"]
    after = candidate["active"]
    if before is None:
        if isinstance(after, Mapping) and after["status"] == PeriodicStatus.PENDING.value:
            _require_new_pending_transition(current, candidate)
            return
        raise PeriodicContractError("periodic durable transition is not allowed")
    if not isinstance(before, Mapping):
        raise PeriodicContractError("periodic current active state is invalid")
    if after is None:
        if _is_terminal(before):
            expected = rotate_terminal_active(PeriodicStateDocument(current), now=candidate["updated_at"])
            _require_exact_successor(expected.payload, candidate)
            return
        raise PeriodicContractError("only a terminal active slot may be rotated")
    if not isinstance(after, Mapping):
        raise PeriodicContractError("periodic candidate active state is invalid")

    edge = (str(before["status"]), str(after["status"]))
    allowed = _ACTIVE_EDGE_DELTAS.get(edge)
    if allowed is None:
        raise PeriodicContractError(f"periodic durable edge {edge[0]}->{edge[1]} is not allowed")
    _require_only_field_deltas(before, after, allowed, context=f"active edge {edge[0]}->{edge[1]}")
    _require_replayed_active_edge(current, candidate, edge)


def _matches_health_only_transition(current: Mapping[str, object], candidate: Mapping[str, object]) -> bool:
    if any(current[key] != candidate[key] for key in _TOP_KEYS - {"health", "updated_at"}):
        return False
    if current["health"] == candidate["health"]:
        return False
    health = candidate["health"]
    assert isinstance(health, Mapping)
    expected = set_periodic_health(
        PeriodicStateDocument(current),
        status=str(health["status"]),
        code=health["error_code"],  # type: ignore[arg-type]
        text=str(health["error_text"]),
        now=candidate["updated_at"],
    )
    _require_exact_successor(expected.payload, candidate)
    return True


def _require_new_pending_transition(current: Mapping[str, object], candidate: Mapping[str, object]) -> None:
    _require_only_field_deltas(
        current,
        candidate,
        {"high_water_slot_end", "active", "updated_at"},
        context="new PENDING allocation",
    )
    active = candidate["active"]
    assert isinstance(active, Mapping)
    old_high = current["high_water_slot_end"]
    new_high = candidate["high_water_slot_end"]
    if new_high is None or (old_high is not None and new_high <= old_high):
        raise PeriodicContractError("new PENDING allocation must advance high water")
    if active["slot_end"] != new_high:
        raise PeriodicContractError("new PENDING allocation does not match high water")
    _require_fresh_pending_shape(active, candidate["updated_at"], attempts=(0, 0))


def _require_retry_pending_transition(current: Mapping[str, object], candidate: Mapping[str, object]) -> None:
    _require_only_field_deltas(
        current,
        candidate,
        {"active", "updated_at"},
        context="render retry allocation",
    )
    before = current["active"]
    after = candidate["active"]
    assert isinstance(before, Mapping) and isinstance(after, Mapping)
    if not (
        before["status"] == PeriodicStatus.FAILED.value
        and before["retryable"] is True
        and before["failure_phase"] == "render"
        and candidate["updated_at"] >= before["not_before"]
    ):
        raise PeriodicContractError("render retry allocation is not due")
    for field in (
        "slot_id",
        "slot_start",
        "slot_end",
        "interval_s",
        "window_end",
        "display_time",
        "render_attempt_count",
        "delivery_attempt_count",
        "created_at",
    ):
        if before[field] != after[field]:
            raise PeriodicContractError(f"render retry allocation changed {field}")
    _require_fresh_pending_shape(
        after,
        candidate["updated_at"],
        attempts=(before["render_attempt_count"], before["delivery_attempt_count"]),
    )


def _require_fresh_pending_shape(active: Mapping[str, object], now: object, *, attempts: tuple[object, object]) -> None:
    expected = {
        "status": PeriodicStatus.PENDING.value,
        "render_attempt_count": attempts[0],
        "delivery_attempt_count": attempts[1],
        "not_before": now,
        "artifact": None,
        "caption": "",
        "receipt": None,
        "failure_phase": None,
        "retryable": None,
        "certainty": None,
        "error_code": None,
        "error_text": "",
        "updated_at": now,
        "finished_at": None,
    }
    if any(active[field] != value for field, value in expected.items()):
        raise PeriodicContractError("PENDING allocation has invalid transition evidence")
    if attempts == (0, 0) and active["created_at"] != now:
        raise PeriodicContractError("new PENDING allocation has invalid creation time")


def _require_replayed_active_edge(
    current: Mapping[str, object],
    candidate: Mapping[str, object],
    edge: tuple[str, str],
) -> None:
    before = current["active"]
    after = candidate["active"]
    assert isinstance(before, Mapping) and isinstance(after, Mapping)
    if edge == ("FAILED", "PENDING"):
        _require_retry_pending_transition(current, candidate)
        return

    document = PeriodicStateDocument(current)
    slot_id = str(before["slot_id"])
    owner_token = str(before["owner_token"])
    now = candidate["updated_at"]
    candidates: list[PeriodicStateDocument] = []

    def attempt(factory) -> None:
        try:
            candidates.append(factory())
        except PeriodicContractError:
            pass

    if edge == ("PENDING", "RENDERING"):
        attempt(lambda: mark_rendering(document, slot_id=slot_id, owner_token=owner_token, now=now))
    elif edge == ("RENDERING", "READY"):
        artifact = after["artifact"]
        assert isinstance(artifact, Mapping)
        value = PeriodicArtifact(
            path=str(artifact["path"]),
            sha256=str(artifact["sha256"]),
            size=artifact["size"],  # type: ignore[arg-type]
            width=artifact["width"],  # type: ignore[arg-type]
            height=artifact["height"],  # type: ignore[arg-type]
            mime=artifact["mime"],  # type: ignore[arg-type]
        )
        attempt(
            lambda: mark_ready(
                document,
                value,
                str(after["caption"]),
                slot_id=slot_id,
                owner_token=owner_token,
                now=now,
            )
        )
    elif edge in {
        ("PENDING", "FAILED"),
        ("RENDERING", "FAILED"),
        ("DELIVERING", "FAILED"),
    }:
        if after["retryable"] is True:
            attempt(
                lambda: mark_retryable_failure(
                    document,
                    phase=str(after["failure_phase"]),
                    certainty=str(after["certainty"]),
                    code=str(after["error_code"]),
                    text=str(after["error_text"]),
                    not_before=after["not_before"],  # type: ignore[arg-type]
                    slot_id=slot_id,
                    owner_token=owner_token,
                    now=now,
                )
            )
        else:
            attempt(lambda: _replay_terminal_failure(document, after, slot_id, owner_token, now))
    elif edge in {("READY", "READY"), ("READY", "DELIVERING"), ("FAILED", "READY"), ("FAILED", "DELIVERING")}:
        attempt(lambda: mark_delivering(document, slot_id=slot_id, owner_token=owner_token, now=now))
        if edge == ("READY", "READY"):
            attempt(
                lambda: supersede_active(
                    document,
                    newer_slot_end=int(before["slot_end"]) + 1,
                    now=now,
                )
            )
    elif edge == ("READY", "FAILED"):
        attempt(lambda: _replay_terminal_failure(document, after, slot_id, owner_token, now))
        attempt(
            lambda: supersede_active(
                document,
                newer_slot_end=int(before["slot_end"]) + 1,
                now=now,
            )
        )
    elif edge == ("DELIVERING", "SUCCEEDED"):
        attempt(
            lambda: mark_succeeded(
                document,
                receipt=PeriodicDeliveryReceipt(**after["receipt"]),  # type: ignore[arg-type]
                slot_id=slot_id,
                owner_token=owner_token,
                now=now,
            )
        )
    elif edge == ("DELIVERING", "DELIVERY_UNKNOWN"):
        attempt(
            lambda: mark_delivery_unknown(
                document,
                code=str(after["error_code"]),
                text=str(after["error_text"]),
                slot_id=slot_id,
                owner_token=owner_token,
                now=now,
            )
        )
    elif edge == ("FAILED", "FAILED"):
        attempt(lambda: _replay_terminal_failure(document, after, slot_id, owner_token, now))
        attempt(
            lambda: supersede_active(
                document,
                newer_slot_end=int(before["slot_end"]) + 1,
                now=now,
            )
        )
    else:
        raise PeriodicContractError(f"periodic durable edge {edge[0]}->{edge[1]} is not replayable")

    if not any(result.payload == candidate for result in candidates):
        raise PeriodicContractError(f"periodic durable edge {edge[0]}->{edge[1]} is not an exact helper transition")


def _replay_terminal_failure(
    document: PeriodicStateDocument,
    after: Mapping[str, object],
    slot_id: str,
    owner_token: str,
    now: object,
) -> PeriodicStateDocument:
    return mark_terminal_failure(
        document,
        phase=str(after["failure_phase"]),
        certainty=str(after["certainty"]),
        code=str(after["error_code"]),
        text=str(after["error_text"]),
        slot_id=slot_id,
        owner_token=owner_token,
        now=now,  # type: ignore[arg-type]
    )


def _require_only_field_deltas(
    before: Mapping[str, object],
    after: Mapping[str, object],
    allowed: set[str],
    *,
    context: str,
) -> None:
    changed = {key for key in before if before[key] != after[key]}
    unexpected = changed - allowed
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise PeriodicContractError(f"{context} changed forbidden fields: {names}")


def _require_exact_successor(expected: Mapping[str, object], candidate: Mapping[str, object]) -> None:
    if expected != candidate:
        raise PeriodicContractError("periodic candidate is not the exact helper successor")


def _enforce_initial_durable_state(candidate: Mapping[str, object]) -> None:
    if candidate["unresolved_delivery"] or candidate["last_terminal"] is not None:
        raise PeriodicContractError("initial periodic state contains fabricated history")
    baseline = PeriodicStateDocument(_empty_payload(0.0)).payload
    high_water = candidate["high_water_slot_end"]
    if high_water is None:
        if candidate == baseline or _matches_health_only_transition(baseline, candidate):
            return
        raise PeriodicContractError("initial periodic state is not an exact empty-state successor")
    active = candidate["active"]
    if not (
        isinstance(active, Mapping)
        and active["status"] == PeriodicStatus.PENDING.value
        and active["slot_end"] == high_water
    ):
        raise PeriodicContractError("initial high water requires a matching new PENDING slot")
    if candidate["health"] != baseline["health"]:
        raise PeriodicContractError("initial PENDING state changed health before persistence")
    _require_fresh_pending_shape(active, candidate["updated_at"], attempts=(0, 0))


def _read_state_file(path: Path) -> bytes:
    before = _require_safe_regular_file(path)
    if before.st_size > _MAX_STATE_BYTES:
        raise PeriodicContractError("periodic state exceeds 128 KiB")
    if before.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
        raise PeriodicContractError("periodic state is future-dated")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise PeriodicContractError("periodic state file is unsafe")
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise PeriodicContractError("periodic state changed while reading")
            if opened.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
                raise PeriodicContractError("periodic state is future-dated")
            snapshot = _stat_snapshot(opened)
            raw = _read_bounded_fd(fd, _MAX_STATE_BYTES)
            finished = os.fstat(fd)
            if _stat_snapshot(finished) != snapshot:
                raise PeriodicContractError("periodic state changed while reading")
            if finished.st_mtime > time.time() + _MAX_FUTURE_SKEW_S:
                raise PeriodicContractError("periodic state is future-dated")
        finally:
            os.close(fd)
    except PeriodicContractError:
        raise
    except OSError as exc:
        raise PeriodicIOError("periodic state cannot be read safely") from exc
    if len(raw) > _MAX_STATE_BYTES:
        raise PeriodicContractError("periodic state exceeds 128 KiB")
    return raw


def _require_safe_regular_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PeriodicIOError("periodic state path is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PeriodicContractError("periodic state must be a regular single-link file")
    return info


def _require_safe_directory(path: Path, *, required: bool) -> None:
    if not os.path.lexists(path):
        if required:
            raise PeriodicIOError("required periodic directory is absent")
        return
    try:
        info = path.lstat()
    except OSError as exc:
        raise PeriodicIOError("periodic directory is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PeriodicContractError("periodic directory must be a real directory")


def _safe_derived_directory(root: Path, *parts: str) -> Path:
    current = root
    for part in parts:
        current /= part
        _require_safe_directory(current, required=False)
    return current


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PeriodicContractError("periodic state contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise PeriodicContractError("periodic state contains a non-finite number")


def _json_text(payload: Mapping[str, object]) -> str:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError):
        raise PeriodicContractError("periodic state is not JSON serializable") from None


def _atomic_write_state_strict(path: Path, content: str) -> None:
    """Replace one state file only after a successful file fsync.

    The general project helper intentionally tolerates fsync failures for
    non-critical metadata.  H3 delivery authority cannot: reporting success
    for a non-durable DELIVERING write could authorize an HTTP send and later
    reboot into READY, causing a duplicate.
    """

    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _fsync_directory_strict(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_bounded_fd(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _stat_snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
