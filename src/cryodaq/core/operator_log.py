from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

ATTENTION_HISTORY_ITEM_SCHEMA = "cryodaq.attention-history-item"
ATTENTION_HISTORY_ITEM_VERSION = 3
ATTENTION_HISTORY_MAX_ITEMS = 1000
ATTENTION_HISTORY_MAX_ITEM_BYTES = 16 * 1024
_ATTENTION_HISTORY_ID_BYTES = 128
_ATTENTION_HISTORY_TEXT_BYTES = 4096


class AttentionHistoryCapacityError(RuntimeError):
    """Raised after capacity exhaustion has been durably marked."""


def _attention_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str or (not value and not allow_empty):
        raise ValueError(f"{field_name} must be text")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field_name} exceeds its UTF-8 bound")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _attention_event_id(value: object, *, field_name: str) -> str:
    text = _attention_text(value, field_name=field_name, maximum=32)
    if len(text) != 32 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be 32 lowercase hexadecimal characters")
    return text


def _attention_time(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def normalize_operator_log_tags(tags: Any) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        parts = [item.strip() for item in tags.split(",")]
        return tuple(item for item in parts if item)
    if isinstance(tags, (list, tuple, set)):
        normalized = [str(item).strip() for item in tags if str(item).strip()]
        return tuple(normalized)
    raise ValueError("Operator log tags must be a string or a list of strings.")


@dataclass(frozen=True, slots=True)
class AttentionHistoryItem:
    """One immutable incident or operator annotation in the durable timeline."""

    event_id: str
    kind: str
    timestamp: datetime
    experiment_id: str
    alarm_id: str
    level: str
    message: str
    channel_ids: tuple[str, ...]
    activation_id: int | None = None
    annotation_of: str | None = None
    actor: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            _attention_event_id(self.event_id, field_name="event_id"),
        )
        if self.kind not in {"incident", "acknowledgement", "resolution"}:
            raise ValueError("kind must be incident, acknowledgement, or resolution")
        object.__setattr__(
            self,
            "timestamp",
            _attention_time(self.timestamp, field_name="timestamp"),
        )
        for name in ("experiment_id", "alarm_id", "level"):
            object.__setattr__(
                self,
                name,
                _attention_text(
                    getattr(self, name),
                    field_name=name,
                    maximum=_ATTENTION_HISTORY_ID_BYTES,
                ),
            )
        object.__setattr__(
            self,
            "message",
            _attention_text(
                self.message,
                field_name="message",
                maximum=_ATTENTION_HISTORY_TEXT_BYTES,
            ),
        )
        if type(self.channel_ids) is not tuple:
            raise TypeError("channel_ids must be a tuple")
        channels = tuple(
            _attention_text(
                channel_id,
                field_name="channel_id",
                maximum=_ATTENTION_HISTORY_ID_BYTES,
            )
            for channel_id in self.channel_ids
        )
        if len(channels) != len(set(channels)):
            raise ValueError("channel_ids must be unique")
        object.__setattr__(self, "channel_ids", channels)
        if self.activation_id is not None and (type(self.activation_id) is not int or self.activation_id <= 0):
            raise ValueError("activation_id must be a positive exact integer when present")
        object.__setattr__(
            self,
            "actor",
            _attention_text(
                self.actor,
                field_name="actor",
                maximum=_ATTENTION_HISTORY_ID_BYTES,
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "note",
            _attention_text(
                self.note,
                field_name="note",
                maximum=_ATTENTION_HISTORY_TEXT_BYTES,
                allow_empty=True,
            ),
        )
        if self.kind == "incident":
            if self.annotation_of is not None or self.actor or self.note:
                raise ValueError("incident cannot carry annotation fields")
        else:
            if self.activation_id is not None:
                raise ValueError("annotations cannot carry canonical activation identity")
            object.__setattr__(
                self,
                "annotation_of",
                _attention_event_id(
                    self.annotation_of,
                    field_name="annotation_of",
                ),
            )
            if self.kind == "acknowledgement" and not self.actor:
                raise ValueError("acknowledgement requires actor identity")
            if self.kind == "resolution" and (self.actor or self.note):
                raise ValueError("resolution cannot carry operator annotation fields")

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "timestamp": self.timestamp.isoformat(),
            "experiment_id": self.experiment_id,
            "alarm_id": self.alarm_id,
            "level": self.level,
            "message": self.message,
            "channel_ids": list(self.channel_ids),
            "activation_id": self.activation_id,
            "annotation_of": self.annotation_of,
            "actor": self.actor,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class AttentionHistoryPage:
    """Chronological bounded view bound to one durable history revision."""

    items: tuple[AttentionHistoryItem, ...]
    item_revisions: tuple[int, ...]
    experiment_id: str
    truncated_before: bool
    through_revision: int
    as_of: datetime | None
    capacity_exhausted_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or any(type(item) is not AttentionHistoryItem for item in self.items):
            raise TypeError("items must contain exact AttentionHistoryItem values")
        if len(self.items) > ATTENTION_HISTORY_MAX_ITEMS:
            raise ValueError(f"attention history page cannot exceed {ATTENTION_HISTORY_MAX_ITEMS} items")
        if (
            type(self.item_revisions) is not tuple
            or len(self.item_revisions) != len(self.items)
            or any(type(revision) is not int or revision <= 0 for revision in self.item_revisions)
            or len(self.item_revisions) != len(set(self.item_revisions))
        ):
            raise ValueError("item_revisions must uniquely bind every item to a positive revision")
        object.__setattr__(
            self,
            "experiment_id",
            _attention_text(
                self.experiment_id,
                field_name="experiment_id",
                maximum=_ATTENTION_HISTORY_ID_BYTES,
            ),
        )
        if any(item.experiment_id != self.experiment_id for item in self.items):
            raise ValueError("attention history items must match the queried experiment")
        if type(self.truncated_before) is not bool:
            raise TypeError("truncated_before must be a boolean")
        if type(self.through_revision) is not int or self.through_revision < 0:
            raise ValueError("through_revision must be a non-negative integer")
        if self.items and self.through_revision == 0:
            raise ValueError("non-empty attention history requires a positive revision")
        if any(revision > self.through_revision for revision in self.item_revisions):
            raise ValueError("attention history item revision exceeds its page cut")
        if self.as_of is not None:
            object.__setattr__(
                self,
                "as_of",
                _attention_time(self.as_of, field_name="as_of"),
            )
        if self.capacity_exhausted_at is not None:
            object.__setattr__(
                self,
                "capacity_exhausted_at",
                _attention_time(
                    self.capacity_exhausted_at,
                    field_name="capacity_exhausted_at",
                ),
            )
            if self.through_revision == 0:
                raise ValueError("capacity exhaustion requires a positive revision")
        if any(later.timestamp < earlier.timestamp for earlier, later in zip(self.items, self.items[1:])):
            raise ValueError("attention history must be chronological")
        if self.as_of is not None and (any(item.timestamp > self.as_of for item in self.items)):
            raise ValueError("attention history page contains evidence after as_of")
        event_ids = tuple(item.event_id for item in self.items)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("attention history event ids must be unique")


def new_attention_incident(
    *,
    timestamp: datetime,
    experiment_id: str,
    alarm_id: str,
    level: str,
    message: str,
    channel_ids: tuple[str, ...],
    activation_id: int | None = None,
) -> AttentionHistoryItem:
    return AttentionHistoryItem(
        event_id=uuid4().hex,
        kind="incident",
        timestamp=timestamp,
        experiment_id=experiment_id,
        alarm_id=alarm_id,
        level=level,
        message=message,
        channel_ids=channel_ids,
        activation_id=activation_id,
    )


def _with_deterministic_annotation_identity(
    provisional: AttentionHistoryItem,
    *,
    operation: str,
) -> AttentionHistoryItem:
    identity_payload = provisional.to_payload()
    del identity_payload["event_id"]
    canonical_identity = json.dumps(
        {
            "schema": ATTENTION_HISTORY_ITEM_SCHEMA,
            "version": ATTENTION_HISTORY_ITEM_VERSION,
            "operation": operation,
            "item": identity_payload,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return replace(
        provisional,
        event_id=sha256(canonical_identity).hexdigest()[:32],
    )


def new_attention_acknowledgement(
    incident: AttentionHistoryItem,
    *,
    actor: str,
    note: str,
    timestamp: datetime,
) -> AttentionHistoryItem:
    if type(incident) is not AttentionHistoryItem or incident.kind != "incident":
        raise ValueError("attention acknowledgement requires an exact incident")
    if _attention_time(timestamp, field_name="timestamp") < incident.timestamp:
        raise ValueError("attention acknowledgement cannot predate its incident")
    provisional = AttentionHistoryItem(
        event_id="0" * 32,
        kind="acknowledgement",
        timestamp=timestamp,
        experiment_id=incident.experiment_id,
        alarm_id=incident.alarm_id,
        level=incident.level,
        message=incident.message,
        channel_ids=incident.channel_ids,
        annotation_of=incident.event_id,
        actor=actor,
        note=note,
    )
    return _with_deterministic_annotation_identity(
        provisional,
        operation="acknowledgement",
    )


def new_attention_resolution(
    incident: AttentionHistoryItem,
    *,
    timestamp: datetime,
) -> AttentionHistoryItem:
    if type(incident) is not AttentionHistoryItem or incident.kind != "incident":
        raise ValueError("attention resolution requires an exact incident")
    if _attention_time(timestamp, field_name="timestamp") < incident.timestamp:
        raise ValueError("attention resolution cannot predate its incident")
    provisional = AttentionHistoryItem(
        event_id="0" * 32,
        kind="resolution",
        timestamp=timestamp,
        experiment_id=incident.experiment_id,
        alarm_id=incident.alarm_id,
        level=incident.level,
        message=incident.message,
        channel_ids=incident.channel_ids,
        annotation_of=incident.event_id,
    )
    return _with_deterministic_annotation_identity(
        provisional,
        operation="resolution",
    )


def dump_attention_history_item(item: AttentionHistoryItem) -> str:
    if type(item) is not AttentionHistoryItem:
        raise TypeError("item must be an exact AttentionHistoryItem")
    payload = json.dumps(
        {
            "schema": ATTENTION_HISTORY_ITEM_SCHEMA,
            "version": ATTENTION_HISTORY_ITEM_VERSION,
            "item": item.to_payload(),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > ATTENTION_HISTORY_MAX_ITEM_BYTES:
        raise ValueError("attention history item exceeds its wire bound")
    return payload


def load_attention_history_item(payload: str) -> AttentionHistoryItem:
    if type(payload) is not str:
        raise TypeError("payload must be text")
    if len(payload.encode("utf-8")) > ATTENTION_HISTORY_MAX_ITEM_BYTES:
        raise ValueError("attention history item exceeds its wire bound")

    def reject_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise ValueError(f"duplicate attention history key: {key}")
            decoded[key] = value
        return decoded

    try:
        envelope = json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid attention history number: {value}")
            ),
        )
        if type(envelope) is not dict or set(envelope) != {
            "schema",
            "version",
            "item",
        }:
            raise ValueError("attention history envelope keys are invalid")
        if (
            envelope["schema"] != ATTENTION_HISTORY_ITEM_SCHEMA
            or type(envelope["version"]) is not int
            or envelope["version"] != ATTENTION_HISTORY_ITEM_VERSION
        ):
            raise ValueError("attention history schema is unsupported")
        raw = envelope["item"]
        expected = {
            "event_id",
            "kind",
            "timestamp",
            "experiment_id",
            "alarm_id",
            "level",
            "message",
            "channel_ids",
            "activation_id",
            "annotation_of",
            "actor",
            "note",
        }
        if type(raw) is not dict or set(raw) != expected:
            raise ValueError("attention history item keys are invalid")
        raw_timestamp = raw["timestamp"]
        if type(raw_timestamp) is not str:
            raise ValueError("attention history timestamp must be text")
        channels = raw["channel_ids"]
        if type(channels) is not list:
            raise ValueError("attention history channel_ids must be a list")
        return AttentionHistoryItem(
            event_id=raw["event_id"],
            kind=raw["kind"],
            timestamp=datetime.fromisoformat(raw_timestamp),
            experiment_id=raw["experiment_id"],
            alarm_id=raw["alarm_id"],
            level=raw["level"],
            message=raw["message"],
            channel_ids=tuple(channels),
            activation_id=raw["activation_id"],
            annotation_of=raw["annotation_of"],
            actor=raw["actor"],
            note=raw["note"],
        )
    except (KeyError, TypeError, ValueError, OverflowError, UnicodeError):
        raise ValueError("attention history item is invalid") from None


@dataclass(frozen=True, slots=True)
class OperatorLogEntry:
    id: int
    timestamp: datetime
    experiment_id: str | None
    author: str
    source: str
    message: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "experiment_id": self.experiment_id,
            "author": self.author,
            "source": self.source,
            "message": self.message,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class OperatorLogCommitResult:
    """Durable keyed-append result without exposing persistence-private keys."""

    entry: OperatorLogEntry
    replayed: bool


class OperatorLogIdempotencyError(RuntimeError):
    """Base class for durable operator-log idempotency failures."""


class OperatorLogIdempotencyConflictError(OperatorLogIdempotencyError):
    """The request key already belongs to different persisted content."""


class OperatorLogIdempotencyUnavailableError(OperatorLogIdempotencyError):
    """The complete retained-data deduplication view could not be proven."""
