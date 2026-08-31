"""Verified append-only channel descriptor storage for daily SQLite files.

This module owns metadata persistence only.  It does not activate drivers,
publish readings, infer vendor semantics, or grant source/control authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import struct
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Final
from weakref import WeakKeyDictionary

import yaml

from cryodaq._owned_yaml import OwnedSafeLoader
from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    UNBOUND_CHANNEL_ID,
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    unbound_channel_descriptor,
    validate_catalog_update,
)
from cryodaq.channels.persistence import (
    MAX_PERSISTED_ENVELOPE_BYTES,
    PersistedChannelEnvelopeError,
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
    resolve_persisted_channel,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage._windows_secure_read import SecureRelativeReadError, read_secure_relative_bytes

CATALOG_SCHEMA_VERSION: Final = 1
MAX_CATALOG_ENVELOPE_BYTES: Final = MAX_CATALOG_DESCRIPTORS * MAX_PERSISTED_ENVELOPE_BYTES
MAX_LIVE_METADATA_DEPTH: Final = 8
MAX_LIVE_METADATA_ITEMS: Final = 1024
MAX_LIVE_METADATA_TEXT_BYTES: Final = 65_536
MAX_LIVE_METADATA_AGGREGATE_BYTES: Final = 1_048_576
MAX_LIVE_READING_TEXT_BYTES: Final = 1024
MAX_PERSISTED_READING_ID_BYTES: Final = 256
MAX_PERSISTED_READING_UNIT_BYTES: Final = 64
MAX_LIVE_DESCRIPTOR_CONFIG_BYTES: Final = 256 * 1024
MAX_LIVE_DESCRIPTOR_CONFIG_DEPTH: Final = 8

_LIVE_DESCRIPTOR_ROOT_KEYS: Final = frozenset({"schema_version", "descriptors", "bindings"})
_LIVE_DESCRIPTOR_KEYS: Final = frozenset(
    {
        "schema_version",
        "channel_id",
        "instrument_id",
        "source_key",
        "quantity",
        "unit",
        "role",
        "safety_class",
        "display_group",
        "display_name",
        "visible_by_default",
        "display_order",
        "descriptor_revision",
    }
)
_LIVE_BINDING_KEYS: Final = frozenset({"instrument_id", "emitted_channel", "channel_id"})
_BOUND_READING_PROVENANCE: Final = object()
_DURABLE_UNBOUND_TEXT_NAMESPACE: Final = "~sha256b64:"
_DURABLE_UNBOUND_CHANNEL_SUFFIX: Final = re.compile(r"~sha256:[0-9a-f]{64}$")
_MAX_AUTHORITATIVE_CHANNEL_ID_BYTES: Final = 128

SCHEMA_DESCRIPTOR_META: Final = """
CREATE TABLE IF NOT EXISTS channel_descriptor_meta (
    singleton      INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1)
);
"""

SCHEMA_DESCRIPTORS: Final = """
CREATE TABLE IF NOT EXISTS channel_descriptors (
    descriptor_hash     TEXT    PRIMARY KEY,
    channel_id          TEXT    NOT NULL,
    instrument_id       TEXT    NOT NULL,
    source_key          TEXT    NOT NULL,
    descriptor_revision INTEGER NOT NULL CHECK (descriptor_revision >= 1),
    envelope_json       BLOB    NOT NULL,
    UNIQUE (channel_id, descriptor_revision),
    UNIQUE (instrument_id, source_key, descriptor_revision)
);
"""

INDEX_DESCRIPTORS_CHANNEL_REVISION: Final = """
CREATE INDEX IF NOT EXISTS idx_channel_descriptors_channel_revision
ON channel_descriptors (channel_id, descriptor_revision);
"""

INDEX_READINGS_DESCRIPTOR_HASH: Final = """
CREATE INDEX IF NOT EXISTS idx_readings_descriptor_hash
ON readings (descriptor_hash);
"""

_TRIGGERS: Final[dict[str, str]] = {
    "channel_descriptors_no_update": """
        CREATE TRIGGER channel_descriptors_no_update
        BEFORE UPDATE ON channel_descriptors
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor catalog is append-only');
        END;
    """,
    "channel_descriptors_no_delete": """
        CREATE TRIGGER channel_descriptors_no_delete
        BEFORE DELETE ON channel_descriptors
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor catalog is append-only');
        END;
    """,
    "channel_descriptor_meta_no_update": """
        CREATE TRIGGER channel_descriptor_meta_no_update
        BEFORE UPDATE ON channel_descriptor_meta
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor metadata is immutable');
        END;
    """,
    "channel_descriptor_meta_no_delete": """
        CREATE TRIGGER channel_descriptor_meta_no_delete
        BEFORE DELETE ON channel_descriptor_meta
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor metadata is immutable');
        END;
    """,
}

_META_COLUMNS: Final = (
    ("singleton", "INTEGER", 0, None, 1),
    ("schema_version", "INTEGER", 1, None, 0),
)
_DESCRIPTOR_COLUMNS: Final = (
    ("descriptor_hash", "TEXT", 0, None, 1),
    ("channel_id", "TEXT", 1, None, 0),
    ("instrument_id", "TEXT", 1, None, 0),
    ("source_key", "TEXT", 1, None, 0),
    ("descriptor_revision", "INTEGER", 1, None, 0),
    ("envelope_json", "BLOB", 1, None, 0),
)
_LEGACY_READING_COLUMNS: Final = (
    ("id", "INTEGER", 0, None, 1),
    ("timestamp", "REAL", 1, None, 0),
    ("instrument_id", "TEXT", 1, None, 0),
    ("channel", "TEXT", 1, None, 0),
    ("value", "REAL", 1, None, 0),
    ("unit", "TEXT", 1, None, 0),
    ("status", "TEXT", 1, None, 0),
)
_V1_READING_COLUMNS: Final = (*_LEGACY_READING_COLUMNS, ("descriptor_hash", "TEXT", 0, None, 0))
_PROTECTED_TEMP_NAMES: Final = {
    "channel_descriptor_meta",
    "channel_descriptors",
    "readings",
    "idx_channel_descriptors_channel_revision",
    "idx_readings_descriptor_hash",
    *_TRIGGERS,
}
_MIGRATED_READINGS_SQL: Final = """
CREATE TABLE readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
, descriptor_hash TEXT REFERENCES channel_descriptors(descriptor_hash))
"""


UNBOUND_DESCRIPTOR_HASH: Final[str] = unbound_channel_descriptor().descriptor_hash
"""Identity a reading carries when the catalog describes no channel for it.

Published from THIS module on purpose. The archive reader needs to recognise such a row,
and importing the channel contract there would give a second file a dependency the inert-
activation guard exists to keep narrow. This module already owns that dependency and is
registered for it, so the identity travels through the adapter instead of widening the
guard. Recognition is exact equality on an opaque value; nothing here interprets it.
"""


def catalog_with_reserved_descriptor(catalog: object) -> ChannelCatalog:
    """Return a persistence catalog that carries the canonical reserved descriptor.

    The reserved descriptor belongs to SQLite persistence rather than to a live
    driver roster. Keep both its construction and its channel-id interpretation
    in this adapter, so generic writer code receives only a ready-to-install
    catalog.
    """

    snapshot = snapshot_catalog(catalog)
    if _carries_reserved_entry(snapshot):
        return snapshot
    return snapshot_catalog(ChannelCatalog([*snapshot.descriptors, unbound_channel_descriptor()]))


def is_reserved_descriptor(descriptor: object) -> bool:
    """Whether an opaque persisted descriptor is the canonical reserved entry.

    Callers may use this result to preserve an emitted label. They must not
    identify the entry by inspecting a channel id themselves.
    """

    return type(descriptor) is ChannelDescriptorV1 and descriptor.descriptor_hash == UNBOUND_DESCRIPTOR_HASH


class ChannelDescriptorStorageError(RuntimeError):
    """The SQLite descriptor authority is malformed, corrupt, or ambiguous."""


class ChannelNotDescribedError(ChannelDescriptorStorageError):
    """The catalog describes no channel under this identity at all.

    Distinct from every other descriptor failure, and distinct for one reason: an
    ABSENT channel has no descriptor to contradict, while a channel the catalog DOES
    describe, whose instrument or unit disagrees, may not be the quantity the descriptor
    names. Callers that answer the two cases differently must tell them apart through
    this type, never by comparing channel spellings themselves -- the spelling sweep
    (tests/test_c2_repo_wide_spelling_sweep.py) rejects membership tests over identity,
    and it is right to: the declaring authority for "is this channel described" is the
    catalog, not the caller.

    It remains a ChannelDescriptorStorageError, so every existing handler that fails
    closed on the base class keeps failing closed on this one.
    """


_CHANNEL_DESCRIPTOR_PROJECTION_PROVENANCE: Final = object()


@dataclass(frozen=True, slots=True, init=False)
class ChannelDescriptorProjection:
    """Passive data-only projection of one verified channel descriptor."""

    channel_id: str
    instrument_id: str
    source_key: str
    quantity: str
    unit: str
    descriptor_hash: str
    descriptor_revision: int
    canonical_json: bytes
    envelope_json: bytes
    _provenance: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("channel descriptor projections are issued only by the descriptor adapter")

    @classmethod
    def _issue(
        cls,
        descriptor: ChannelDescriptorV1,
        *,
        envelope_json: bytes,
    ) -> ChannelDescriptorProjection:
        projection = object.__new__(cls)
        object.__setattr__(projection, "channel_id", descriptor.channel_id)
        object.__setattr__(projection, "instrument_id", descriptor.instrument_id)
        object.__setattr__(projection, "source_key", descriptor.source_key)
        object.__setattr__(projection, "quantity", descriptor.quantity.value)
        object.__setattr__(projection, "unit", descriptor.unit)
        object.__setattr__(projection, "descriptor_hash", descriptor.descriptor_hash)
        object.__setattr__(projection, "descriptor_revision", descriptor.descriptor_revision)
        object.__setattr__(projection, "canonical_json", descriptor.canonical_json)
        object.__setattr__(projection, "envelope_json", envelope_json)
        object.__setattr__(projection, "_provenance", _CHANNEL_DESCRIPTOR_PROJECTION_PROVENANCE)
        return projection

    def envelope_payload(self) -> dict[str, object]:
        """Return a fresh JSON-data copy of the verified persisted envelope."""

        if self._provenance is not _CHANNEL_DESCRIPTOR_PROJECTION_PROVENANCE:
            raise ChannelDescriptorStorageError("channel descriptor projection provenance is invalid")
        payload = json.loads(self.envelope_json)
        if type(payload) is not dict:
            raise ChannelDescriptorStorageError("channel descriptor envelope projection is not an object")
        return payload


def _project_channel_descriptor_envelope(envelope: PersistedChannelEnvelopeV1) -> ChannelDescriptorProjection:
    descriptor = envelope.descriptor
    if envelope.canonical_json != PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json:
        raise ChannelDescriptorStorageError("channel descriptor envelope projection is not canonical")
    return ChannelDescriptorProjection._issue(descriptor, envelope_json=envelope.canonical_json)


def project_channel_descriptor(candidate: object) -> ChannelDescriptorProjection:
    """Validate a descriptor at the approved passive adapter boundary."""

    if type(candidate) is ChannelDescriptorProjection:
        if candidate._provenance is not _CHANNEL_DESCRIPTOR_PROJECTION_PROVENANCE:
            raise ChannelDescriptorStorageError("channel descriptor projection provenance is invalid")
        return candidate
    try:
        envelope = PersistedChannelEnvelopeV1.from_descriptor(candidate)
        verified = decode_persisted_channel_envelope(envelope.canonical_json)
    except (TypeError, ValueError, ChannelDescriptorError, PersistedChannelEnvelopeError) as exc:
        raise ChannelDescriptorStorageError("channel descriptor projection is invalid") from exc
    return _project_channel_descriptor_envelope(verified)


def project_channel_descriptor_payload(payload: object) -> ChannelDescriptorProjection:
    """Decode one exact canonical persisted-envelope JSON object to passive data."""

    if type(payload) is not dict:
        raise ChannelDescriptorStorageError("channel descriptor envelope projection must be an object")
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        envelope = decode_persisted_channel_envelope(encoded)
    except (TypeError, ValueError, PersistedChannelEnvelopeError) as exc:
        raise ChannelDescriptorStorageError("channel descriptor envelope projection is invalid") from exc
    if encoded != envelope.canonical_json:
        raise ChannelDescriptorStorageError("channel descriptor envelope projection is not canonical")
    return _project_channel_descriptor_envelope(envelope)


class _StrictDescriptorLoader(OwnedSafeLoader):
    """Bounded YAML grammar with neither aliases nor duplicate mapping keys.

    Derives from the SHARED owned loader rather than repeating its table copies.
    An earlier version of this class copied them locally, which read as
    equivalent and is not: a later hardening that replaces `OwnedSafeLoader`'s
    copies with package-owned pristine constructors would have left this loader
    behind on the old, pre-import-poisonable path while the register recorded
    the class as handled.  `tests/core/test_yaml_loader_table_ownership.py`
    asserts the subclass relationship so the sharing claim stays checkable
    rather than asserted.
    """

    def __init__(self, stream: object) -> None:
        super().__init__(stream)
        self._descriptor_depth = 0

    def compose_node(self, parent: yaml.Node | None, index: int | None) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a descriptor manifest",
                getattr(event, "start_mark", None),
                "YAML aliases are not allowed",
                getattr(event, "start_mark", None),
            )
        self._descriptor_depth += 1
        if self._descriptor_depth > MAX_LIVE_DESCRIPTOR_CONFIG_DEPTH:
            self._descriptor_depth -= 1
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                "while composing a descriptor manifest",
                getattr(event, "start_mark", None),
                "descriptor manifest nesting exceeds its limit",
                getattr(event, "start_mark", None),
            )
        try:
            return super().compose_node(parent, index)
        finally:
            self._descriptor_depth -= 1

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[object, object]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from None
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found a duplicate key",
                    key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _read_live_descriptor_config(path: Path) -> bytes:
    """Read one immutable regular-file snapshot under a hard byte ceiling."""

    selected = Path(path)
    absolute = Path(os.path.abspath(os.fspath(selected)))
    if os.name == "nt":
        try:
            raw = read_secure_relative_bytes(
                absolute.parent,
                absolute.name,
                max_bytes=MAX_LIVE_DESCRIPTOR_CONFIG_BYTES,
            )
        except SecureRelativeReadError as exc:
            detail = str(exc)
            cause = exc.__cause__
            if isinstance(cause, FileNotFoundError) or getattr(cause, "winerror", None) in {2, 3}:
                message = "live descriptor manifest is unavailable"
            elif "exactly one hard link" in detail:
                message = "live descriptor manifest must be a single-link regular file"
            elif "exceeds max_bytes" in detail:
                message = "live descriptor manifest exceeds its bounded file grammar"
            elif "reparse point" in detail:
                message = "live descriptor manifest authority path must be symlink-free"
            else:
                message = "live descriptor manifest cannot be read safely"
            raise ChannelDescriptorStorageError(message) from None
        if not raw:
            raise ChannelDescriptorStorageError("live descriptor manifest exceeds its bounded file grammar")
        return raw

    directory_fd: int | None = None
    fd: int | None = None
    try:
        supports_dirfd_walk = hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd
        if not supports_dirfd_walk:
            raise ChannelDescriptorStorageError("live descriptor manifest cannot be read safely on this platform")
        parts = absolute.parts
        if len(parts) < 2:
            raise ChannelDescriptorStorageError("live descriptor manifest path is invalid")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        directory_fd = os.open(parts[0], directory_flags)
        for component in parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        filename = parts[-1]
        before = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ChannelDescriptorStorageError("live descriptor manifest must be a single-link regular file")
        if before.st_size <= 0 or before.st_size > MAX_LIVE_DESCRIPTOR_CONFIG_BYTES:
            raise ChannelDescriptorStorageError("live descriptor manifest exceeds its bounded file grammar")
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        fd = os.open(filename, file_flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(fd)
            changed_before_reading = (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                != (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            )
            if changed_before_reading:
                raise ChannelDescriptorStorageError("live descriptor manifest changed before reading")
            chunks: list[bytes] = []
            remaining = MAX_LIVE_DESCRIPTOR_CONFIG_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 65_536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            finished = os.fstat(fd)
            if (
                finished.st_dev,
                finished.st_ino,
                finished.st_size,
                finished.st_mtime_ns,
                finished.st_ctime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ):
                raise ChannelDescriptorStorageError("live descriptor manifest changed while reading")
        finally:
            os.close(fd)
            fd = None
    except ChannelDescriptorStorageError:
        raise
    except FileNotFoundError:
        raise ChannelDescriptorStorageError("live descriptor manifest is unavailable") from None
    except OSError:
        raise ChannelDescriptorStorageError("live descriptor manifest cannot be read safely") from None
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)
    raw = b"".join(chunks)
    if not raw or len(raw) > MAX_LIVE_DESCRIPTOR_CONFIG_BYTES:
        raise ChannelDescriptorStorageError("live descriptor manifest exceeds its bounded file grammar")
    return raw


def _parse_live_descriptor_manifest(
    path: Path,
) -> tuple[ChannelCatalog, Mapping[tuple[str, str], str]]:
    raw = _read_live_descriptor_config(path)
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = yaml.load(text, Loader=_StrictDescriptorLoader)
    except Exception:
        raise ChannelDescriptorStorageError("live descriptor manifest is not valid strict UTF-8 YAML") from None
    if type(payload) is not dict or set(payload) != _LIVE_DESCRIPTOR_ROOT_KEYS:
        raise ChannelDescriptorStorageError("live descriptor manifest root schema is not exact")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ChannelDescriptorStorageError("live descriptor manifest schema_version must be integer 1")
    descriptor_rows = payload["descriptors"]
    binding_rows = payload["bindings"]
    if type(descriptor_rows) is not list or not 1 <= len(descriptor_rows) <= MAX_CATALOG_DESCRIPTORS:
        raise ChannelDescriptorStorageError("live descriptor manifest descriptors are not a bounded list")
    if type(binding_rows) is not list or len(binding_rows) != len(descriptor_rows):
        raise ChannelDescriptorStorageError("live descriptor manifest bindings must match descriptor count")

    descriptors: list[ChannelDescriptorV1] = []
    for row in descriptor_rows:
        if type(row) is not dict or set(row) != _LIVE_DESCRIPTOR_KEYS:
            raise ChannelDescriptorStorageError("live descriptor entry schema is not exact")
        try:
            quantity = ChannelQuantity(row["quantity"]) if type(row["quantity"]) is str else None
            role = ChannelRole(row["role"]) if type(row["role"]) is str else None
            safety_class = ChannelSafetyClass(row["safety_class"]) if type(row["safety_class"]) is str else None
            if quantity is None or role is None or safety_class is None:
                raise TypeError
            descriptor = ChannelDescriptorV1(
                schema_version=row["schema_version"],
                channel_id=row["channel_id"],
                instrument_id=row["instrument_id"],
                source_key=row["source_key"],
                quantity=quantity,
                unit=row["unit"],
                role=role,
                safety_class=safety_class,
                display_group=row["display_group"],
                display_name=row["display_name"],
                visible_by_default=row["visible_by_default"],
                display_order=row["display_order"],
                descriptor_revision=row["descriptor_revision"],
            )
        except (TypeError, ValueError, ChannelDescriptorError):
            raise ChannelDescriptorStorageError("live descriptor entry violates canonical contracts") from None
        descriptors.append(descriptor)

    bindings: dict[tuple[str, str], str] = {}
    for row in binding_rows:
        if type(row) is not dict or set(row) != _LIVE_BINDING_KEYS:
            raise ChannelDescriptorStorageError("live descriptor binding schema is not exact")
        instrument_id = _bounded_live_text(
            row["instrument_id"],
            field="binding instrument_id",
            maximum=MAX_LIVE_READING_TEXT_BYTES,
        )
        emitted_channel = _bounded_live_text(
            row["emitted_channel"],
            field="binding emitted_channel",
            maximum=MAX_LIVE_READING_TEXT_BYTES,
        )
        channel_id = _bounded_live_text(
            row["channel_id"],
            field="binding channel_id",
            maximum=MAX_LIVE_READING_TEXT_BYTES,
        )
        pair = (instrument_id, emitted_channel)
        if pair in bindings or channel_id in bindings.values():
            raise ChannelDescriptorStorageError("live descriptor bindings are not one-to-one")
        bindings[pair] = channel_id
    try:
        catalog = ChannelCatalog(descriptors)
    except (TypeError, ValueError, ChannelDescriptorError):
        raise ChannelDescriptorStorageError("live descriptor catalog violates canonical contracts") from None
    return catalog, MappingProxyType(bindings)


def load_live_channel_descriptor_catalog(
    base_path: Path,
    *,
    local_path: Path | None = None,
) -> LiveChannelDescriptorCatalog:
    """Load one strict whole-file descriptor authority.

    A supplied local manifest is a complete replacement, never a partial merge.
    It must exist and validate; malformed or missing local configuration never
    falls back to the tracked base.  This bounded synchronous loader owns no
    runtime resources and must be called off the engine event loop when wired.
    """

    selected = Path(local_path) if local_path is not None else Path(base_path)
    catalog, bindings = _parse_live_descriptor_manifest(selected)
    return LiveChannelDescriptorCatalog(catalog, bindings=bindings)


@dataclass(frozen=True, slots=True)
class ResolvedSQLiteReading:
    """One immutable hot reading row paired with its resolved descriptor."""

    id: int
    timestamp: float
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: str
    descriptor: ChannelDescriptorV1 | None


@dataclass(frozen=True, slots=True)
class _FrozenList:
    items: tuple[_FrozenValue, ...]


@dataclass(frozen=True, slots=True)
class _FrozenTuple:
    items: tuple[_FrozenValue, ...]


@dataclass(frozen=True, slots=True)
class _FrozenDict:
    items: tuple[tuple[str, _FrozenValue], ...]


type _FrozenValue = None | bool | int | float | str | _FrozenList | _FrozenTuple | _FrozenDict


@dataclass(frozen=True, slots=True)
class _OwnedLiveReading:
    """Recursively immutable, data-only snapshot of one validated Reading."""

    timestamp_iso: str
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus
    raw: float | None
    metadata: _FrozenDict


@dataclass(frozen=True, slots=True)
class _ReceiptIntegrity:
    """Owner-private issuance record for one exact observational receipt."""

    payload: _OwnedLiveReading
    descriptor: ChannelDescriptorV1
    payload_fingerprint: tuple[object, ...]
    descriptor_envelope: bytes
    token: object


def _frozen_value_fingerprint(value: _FrozenValue) -> object:
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        return ("float64", struct.pack(">d", value))
    if type(value) is str:
        return ("text", value)
    if type(value) is _FrozenList:
        return ("list", tuple(_frozen_value_fingerprint(item) for item in value.items))
    if type(value) is _FrozenTuple:
        return ("tuple", tuple(_frozen_value_fingerprint(item) for item in value.items))
    if type(value) is _FrozenDict:
        return (
            "dict",
            tuple((key, _frozen_value_fingerprint(item)) for key, item in value.items),
        )
    raise ChannelDescriptorStorageError("receipt payload contains a non-canonical frozen value")


def _owned_live_reading_fingerprint(value: object) -> tuple[object, ...]:
    if type(value) is not _OwnedLiveReading:
        raise ChannelDescriptorStorageError("receipt payload is not an exact owned reading")
    if type(value.timestamp_iso) is not str:
        raise ChannelDescriptorStorageError("receipt timestamp fingerprint is malformed")
    if any(type(item) is not str for item in (value.instrument_id, value.channel, value.unit)):
        raise ChannelDescriptorStorageError("receipt text fingerprint is malformed")
    if type(value.value) is not float or (value.raw is not None and type(value.raw) is not float):
        raise ChannelDescriptorStorageError("receipt numeric fingerprint is malformed")
    if type(value.status) is not ChannelStatus or type(value.metadata) is not _FrozenDict:
        raise ChannelDescriptorStorageError("receipt status or metadata fingerprint is malformed")
    return (
        value.timestamp_iso,
        value.instrument_id,
        value.channel,
        struct.pack(">d", value.value),
        value.unit,
        value.status.value,
        None if value.raw is None else struct.pack(">d", value.raw),
        _frozen_value_fingerprint(value.metadata),
    )


def _bounded_live_text(value: object, *, field: str, maximum: int) -> str:
    if type(value) is not str:
        raise ChannelDescriptorStorageError(f"{field} must be an exact string")
    if unicodedata.normalize("NFC", value) != value:
        raise ChannelDescriptorStorageError(f"{field} must be NFC-normalized")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ChannelDescriptorStorageError(f"{field} contains a Unicode control character")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChannelDescriptorStorageError(f"{field} is not valid Unicode text") from exc
    if not encoded or len(encoded) > maximum:
        raise ChannelDescriptorStorageError(f"{field} exceeds its bounded text grammar")
    return value


def _durable_unbound_text(value: str, *, maximum: int) -> str:
    """Return one bounded, namespace-disjoint spelling for unbound row text.

    Reserved admission cannot refuse an otherwise valid batch merely because a live
    identifier is wider than a durable reader field. The generated spelling starts in
    an explicit namespace and carries the full SHA-256 digest plus a UTF-8-safe visible
    prefix. A short emitted value already in that namespace is encoded too, so it cannot
    alias the generated spelling of another value.
    """

    encoded = value.encode("utf-8")
    if len(encoded) <= maximum and not value.startswith(_DURABLE_UNBOUND_TEXT_NAMESPACE):
        return value
    digest = base64.urlsafe_b64encode(hashlib.sha256(encoded).digest()).rstrip(b"=").decode("ascii")
    header = f"{_DURABLE_UNBOUND_TEXT_NAMESPACE}{digest}:"
    prefix_budget = maximum - len(header.encode("ascii"))
    if prefix_budget < 0:
        raise AssertionError("durable unbound text bound cannot carry the reserved namespace")
    visible_prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
    return header + visible_prefix


def _durable_unbound_channel_text(value: str) -> str:
    """Keep the pre-upgrade durable channel spelling and escape its namespace.

    The earlier deployed representation is a UTF-8-safe prefix followed by a full
    hexadecimal SHA-256 suffix.  It is always longer than the 128-byte descriptor-ID
    grammar, so a generated unbound identity cannot alias an authoritative channel.
    A literal emitted value already ending in that generated suffix is encoded again,
    keeping emitted and generated spellings disjoint.
    """

    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_PERSISTED_READING_ID_BYTES and _DURABLE_UNBOUND_CHANNEL_SUFFIX.search(value) is None:
        return value
    suffix = f"~sha256:{hashlib.sha256(encoded).hexdigest()}"
    prefix_budget = MAX_PERSISTED_READING_ID_BYTES - len(suffix.encode("ascii"))
    prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
    return prefix + suffix


def durable_unbound_reading_fields(
    instrument_id: str,
    channel: str,
    unit: str,
) -> tuple[str, str, str]:
    """Return the one durable text representation for an unbound reading.

    Both the receipt-bearing live path and the legacy immediate-write path can
    admit an undescribed reading.  Keeping the three persisted fields behind
    this single helper prevents either path from storing text that the bounded
    reader must quarantine, while retaining a collision-resistant identity for
    every original value.
    """

    for field, value in (
        ("instrument_id", instrument_id),
        ("channel", channel),
        ("unit", unit),
    ):
        if type(value) is not str:
            raise ChannelDescriptorStorageError(f"unbound reading {field} must be an exact string")

    return (
        _durable_unbound_text(instrument_id, maximum=MAX_PERSISTED_READING_ID_BYTES),
        _durable_unbound_channel_text(channel),
        _durable_unbound_text(unit, maximum=MAX_PERSISTED_READING_UNIT_BYTES),
    )


def normalize_persisted_unbound_channel(channel: str) -> str:
    """Return the bounded identity of one pre-contract persisted unbound channel."""

    if type(channel) is not str:
        raise ChannelDescriptorStorageError("persisted unbound reading channel must be an exact string")
    encoded_length = len(channel.encode("utf-8"))
    if encoded_length <= _MAX_AUTHORITATIVE_CHANNEL_ID_BYTES:
        # A valid authoritative-width label could be persisted literally before
        # this suffix became a generated namespace. The persistence codec escapes
        # that literal exactly once.
        return _durable_unbound_channel_text(channel)
    if encoded_length <= MAX_PERSISTED_READING_ID_BYTES:
        return channel
    return _durable_unbound_channel_text(channel)


def persisted_unbound_channel_alias(channel: str) -> str | None:
    """Return the current escaped alias for a possibly legacy literal spelling."""

    if type(channel) is not str:
        raise ChannelDescriptorStorageError("persisted unbound reading channel must be an exact string")
    alias = _durable_unbound_channel_text(channel)
    return alias if alias != channel else None


def persisted_unbound_channel_may_have_alias(channel: str) -> bool:
    """Return whether an identity may have an older persisted raw spelling."""

    return persisted_unbound_channel_alias(channel) is not None


def normalize_persisted_unbound_reading_fields(
    instrument_id: str,
    channel: str,
    unit: str,
) -> tuple[str, str, str]:
    """Bound pre-contract reserved rows without rewriting current durable text."""

    fields = (
        ("instrument_id", instrument_id, MAX_PERSISTED_READING_ID_BYTES),
        ("channel", channel, MAX_PERSISTED_READING_ID_BYTES),
        ("unit", unit, MAX_PERSISTED_READING_UNIT_BYTES),
    )
    normalized: list[str] = []
    for field, value, maximum in fields:
        if type(value) is not str:
            raise ChannelDescriptorStorageError(f"persisted unbound reading {field} must be an exact string")
        if field == "channel":
            normalized.append(normalize_persisted_unbound_channel(value))
        elif len(value.encode("utf-8")) <= maximum:
            normalized.append(value)
        else:
            normalized.append(_durable_unbound_text(value, maximum=maximum))
    return normalized[0], normalized[1], normalized[2]


def _freeze_live_metadata(value: object) -> _FrozenDict:
    """Validate and freeze the bounded Reading metadata data grammar.

    The accepted grammar is deliberately narrower than ``Any``: exact null,
    bool, signed-64-bit int, float, UTF-8 text, list, tuple and string-keyed
    dict values.  Container identity is tracked only along the active path so
    ordinary repeated immutable/scalar values are accepted while cycles are
    rejected.  The global item budget bounds both work and retained memory.
    """

    if type(value) is not dict:
        raise ChannelDescriptorStorageError("reading metadata must be an exact string-keyed dict")
    remaining = [MAX_LIVE_METADATA_ITEMS]
    remaining_bytes = [MAX_LIVE_METADATA_AGGREGATE_BYTES]
    active: set[int] = set()

    def consume_bytes(count: int) -> None:
        remaining_bytes[0] -= count
        if remaining_bytes[0] < 0:
            raise ChannelDescriptorStorageError("reading metadata exceeds its aggregate byte limit")

    def freeze(item: object, depth: int) -> _FrozenValue:
        remaining[0] -= 1
        if remaining[0] < 0:
            raise ChannelDescriptorStorageError("reading metadata exceeds its item limit")
        if depth > MAX_LIVE_METADATA_DEPTH:
            raise ChannelDescriptorStorageError("reading metadata exceeds its depth limit")
        if item is None or type(item) in (bool, float):
            consume_bytes(8)
            return item  # type: ignore[return-value]
        if type(item) is int:
            if not -(2**63) <= item <= 2**63 - 1:
                raise ChannelDescriptorStorageError("reading metadata integer exceeds signed 64-bit range")
            consume_bytes(8)
            return item
        if type(item) is str:
            text = _bounded_live_text(item, field="metadata text", maximum=MAX_LIVE_METADATA_TEXT_BYTES)
            consume_bytes(len(text.encode("utf-8")) + 8)
            return text
        if type(item) not in (list, tuple, dict):
            raise ChannelDescriptorStorageError("reading metadata contains a non-data value")

        consume_bytes(8)

        identity = id(item)
        if identity in active:
            raise ChannelDescriptorStorageError("reading metadata contains a cycle")
        active.add(identity)
        try:
            if type(item) is list:
                return _FrozenList(tuple(freeze(child, depth + 1) for child in item))
            if type(item) is tuple:
                return _FrozenTuple(tuple(freeze(child, depth + 1) for child in item))
            pairs: list[tuple[str, _FrozenValue]] = []
            for key, child in item.items():
                if type(key) is not str:
                    raise ChannelDescriptorStorageError("reading metadata must be an exact string-keyed dict")
                key = _bounded_live_text(
                    key,
                    field="metadata key",
                    maximum=MAX_LIVE_METADATA_TEXT_BYTES,
                )
                consume_bytes(len(key.encode("utf-8")) + 8)
                pairs.append((key, freeze(child, depth + 1)))
            return _FrozenDict(tuple(pairs))
        finally:
            active.remove(identity)

    frozen = freeze(value, 0)
    assert isinstance(frozen, _FrozenDict)
    return frozen


def _thaw_live_metadata(value: _FrozenValue) -> object:
    if isinstance(value, _FrozenList):
        return [_thaw_live_metadata(item) for item in value.items]
    if isinstance(value, _FrozenTuple):
        return tuple(_thaw_live_metadata(item) for item in value.items)
    if isinstance(value, _FrozenDict):
        return {key: _thaw_live_metadata(item) for key, item in value.items}
    return value


def _own_live_reading(reading: object) -> _OwnedLiveReading:
    if type(reading) is not Reading:
        raise TypeError("descriptor binding requires an exact Reading")
    if type(reading.timestamp) is not datetime or type(reading.timestamp.tzinfo) is not timezone:
        raise ChannelDescriptorStorageError("reading timestamp must use an exact timezone-aware datetime")
    if type(reading.value) is not float:
        raise ChannelDescriptorStorageError("reading value must be an exact float")
    if reading.raw is not None and type(reading.raw) is not float:
        raise ChannelDescriptorStorageError("reading raw must be None or an exact float")
    if type(reading.status) is not ChannelStatus:
        raise ChannelDescriptorStorageError("reading status must be an exact ChannelStatus")
    return _OwnedLiveReading(
        timestamp_iso=reading.timestamp.isoformat(),
        instrument_id=_bounded_live_text(
            reading.instrument_id,
            field="instrument_id",
            maximum=MAX_LIVE_READING_TEXT_BYTES,
        ),
        channel=_bounded_live_text(
            reading.channel,
            field="channel",
            maximum=MAX_LIVE_READING_TEXT_BYTES,
        ),
        value=reading.value,
        unit=_bounded_live_text(reading.unit, field="unit", maximum=MAX_LIVE_READING_TEXT_BYTES),
        status=reading.status,
        raw=reading.raw,
        metadata=_freeze_live_metadata(reading.metadata),
    )


def _restore_live_reading(owned: _OwnedLiveReading) -> Reading:
    metadata = _thaw_live_metadata(owned.metadata)
    assert type(metadata) is dict
    return Reading(
        timestamp=datetime.fromisoformat(owned.timestamp_iso),
        instrument_id=owned.instrument_id,
        channel=owned.channel,
        value=owned.value,
        unit=owned.unit,
        status=owned.status,
        raw=owned.raw,
        metadata=metadata,
    )


@dataclass(frozen=True, slots=True, init=False, eq=False, weakref_slot=True)
class DescriptorBoundReading:
    """An owned live reading paired with one verified descriptor revision.

    The pair is observational data only.  It contains no driver, transport,
    credential, callback, source adapter, or control authority.  ``reading``
    returns a fresh exact ``Reading`` so a consumer cannot mutate the owned
    metadata snapshot shared with another consumer.
    """

    _payload: _OwnedLiveReading
    descriptor: ChannelDescriptorV1
    _owner_key: object
    _provenance: object
    _integrity_token: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("descriptor-bound readings are issued only by LiveChannelDescriptorCatalog")

    @classmethod
    def _issue(
        cls,
        payload: _OwnedLiveReading,
        descriptor: ChannelDescriptorV1,
        *,
        owner_key: object,
        integrity_token: object,
    ) -> DescriptorBoundReading:
        issued = object.__new__(cls)
        object.__setattr__(issued, "_payload", payload)
        object.__setattr__(issued, "descriptor", descriptor)
        object.__setattr__(issued, "_owner_key", owner_key)
        object.__setattr__(issued, "_provenance", _BOUND_READING_PROVENANCE)
        object.__setattr__(issued, "_integrity_token", integrity_token)
        return issued

    @property
    def reading(self) -> Reading:
        return _restore_live_reading(self._payload)

    @property
    def grants_control_authority(self) -> bool:
        return False


def _carries_reserved_entry(catalog: ChannelCatalog) -> bool:
    """Whether this catalog already carries the reserved entry.

    EXACT EQUALITY, NOT MEMBERSHIP. The repository-wide spelling sweep refuses a membership
    test over identity, and it is right to: selecting by looking a spelling up in a mapping
    is how a channel gets identified by its name instead of by its declaration. Comparing a
    descriptor's own channel_id with a fixed constant is the permitted form -- an exact
    comparison of opaque values, with no lookup and no inference.
    """

    return any(descriptor.channel_id == UNBOUND_CHANNEL_ID for descriptor in catalog.descriptors)


def _reserved_entry_of(catalog: ChannelCatalog) -> ChannelDescriptorV1:
    """The reserved entry this catalog carries, selected by exact equality."""

    for descriptor in catalog.descriptors:
        if descriptor.channel_id == UNBOUND_CHANNEL_ID:
            return descriptor
    raise ChannelDescriptorStorageError("this catalog carries no reserved entry")


class LiveChannelDescriptorCatalog:
    """Explicit, immutable catalog owner for later runtime activation.

    Production manifests resolve an exact ``(instrument_id, emitted channel)``
    compatibility binding to a stable ``channel_id``.  This keeps today's
    LakeShore human-label emissions intact while the descriptor identity stays
    whitespace-free.  The emitted label is retained only as an exact lookup
    key; display names, vendor names, units and aliases are never identity
    fallbacks.  Direct ``ChannelCatalog`` construction uses an identity binding
    for pure contract tests.  An unknown live channel never synthesizes a
    legacy descriptor.  Runtime wiring remains a separate atom.
    """

    __slots__ = ("_bindings", "_catalog", "_issued", "_owner_key")

    def __init__(
        self,
        catalog: object,
        *,
        bindings: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self._catalog = snapshot_catalog(catalog)
        # STRIP THE RESERVED ENTRY ON THE WAY IN -- but only OURS. This catalog can arrive
        # from another live catalog's snapshot, which already carries it, while the caller's
        # bindings describe only the caller's own channels. Validating those bindings against
        # a catalog holding an entry the caller never declared refused seven manifest tests
        # with "live descriptor bindings must cover every current descriptor exactly once".
        # The entry is added back after every check below: it is this class's to add, never
        # the caller's to account for.
        #
        # An earlier version stripped ANY descriptor carrying the reserved channel_id. A
        # caller whose configured manifest legitimately declares a channel under that id had
        # it silently deleted and replaced by the canonical entry -- a configuration mistake
        # that looked accepted, with the declared channel gone from the public roster. So the
        # strip accepts exactly the canonical reserved entry and refuses anything else.
        # THE SOFTWARE NEVER REFUSES applies to operators facing a missing description, not
        # to a namespace collision between two different declared channels.
        if _carries_reserved_entry(self._catalog):
            supplied = _reserved_entry_of(self._catalog)
            if supplied != unbound_channel_descriptor():
                raise ChannelDescriptorStorageError(
                    "reserved namespace collision -- a configured descriptor claims the reserved "
                    f"channel_id ({UNBOUND_CHANNEL_ID!r}) with foreign fields; rename it or declare "
                    "the canonical reserved entry exactly"
                )
            self._catalog = snapshot_catalog(
                ChannelCatalog(
                    [
                        descriptor
                        for descriptor in self._catalog.descriptors
                        if descriptor.channel_id != UNBOUND_CHANNEL_ID
                    ]
                )
            )
        self._owner_key = object()
        self._issued: WeakKeyDictionary[DescriptorBoundReading, _ReceiptIntegrity] = WeakKeyDictionary()
        if bindings is None:
            configured = {
                (descriptor.instrument_id, descriptor.channel_id): descriptor.channel_id
                for descriptor in self._catalog.descriptors
            }
        else:
            configured = dict(bindings)
            if len(configured) != len(bindings):
                raise ChannelDescriptorStorageError("live descriptor bindings contain a duplicate pair")
            if set(configured.values()) != set(self._catalog.by_channel_id):
                raise ChannelDescriptorStorageError(
                    "live descriptor bindings must cover every current descriptor exactly once"
                )
            if len(configured) != len(self._catalog.descriptors):
                raise ChannelDescriptorStorageError("live descriptor bindings must be unique and complete")
            for (instrument_id, emitted_channel), channel_id in configured.items():
                if type(instrument_id) is not str or type(emitted_channel) is not str or type(channel_id) is not str:
                    raise ChannelDescriptorStorageError("live descriptor binding fields must be exact strings")
                descriptor = self._catalog.by_channel_id.get(channel_id)
                if descriptor is None or descriptor.instrument_id != instrument_id:
                    raise ChannelDescriptorStorageError(
                        "live descriptor binding instrument_id disagrees with its descriptor"
                    )
        # THE RESERVED ENTRY JOINS LAST, AND ON PURPOSE. `admit` binds an undescribed
        # reading against it so one such reading costs its own identity and not the whole
        # batch, and that binding must be owned by this catalog or the receipt path's
        # ownership check refuses it.
        #
        # It is added AFTER every check above. An earlier version added it before, and the
        # caller's own bindings then no longer covered the catalog: seven manifest tests
        # refused with "live descriptor bindings must cover every current descriptor exactly
        # once". The caller's bindings describe the CALLER's catalog; this entry is not the
        # caller's and must not be measured against them.
        # IT JOINS THE CATALOG, NOT THE BINDINGS, and the difference is the whole point.
        # The bindings are what the tracked manifest DECLARES: which emitted label belongs to
        # which channel of which instrument. The reserved entry declares nothing -- it exists
        # so that a reading with no declaration has a real descriptor to reference, which the
        # foreign key requires. Putting it in the bindings made the live catalog claim a
        # channel the manifest never declared, and the manifest guards said so: the binding
        # count moved by one and the declared set no longer matched.
        #
        # `admit` reaches the entry through the catalog directly. `bind` never resolves it,
        # which is correct: nothing emits it, so nothing should look it up.
        if not _carries_reserved_entry(self._catalog):
            self._catalog = snapshot_catalog(ChannelCatalog([*self._catalog.descriptors, unbound_channel_descriptor()]))
        self._bindings = MappingProxyType(configured)

    @property
    def grants_control_authority(self) -> bool:
        return False

    @property
    def instrument_ids(self) -> frozenset[str]:
        """Configured instrument identities, detached from binding internals.

        The reserved entry cannot appear here and needs no exclusion: it joins the catalog
        and never the bindings, and this set is derived from the bindings. An earlier version
        put it in both and had to filter it out again, after startup refused with
        "instrument mismatch (missing=[], extra=['cryodaq'])".
        """

        return frozenset(instrument_id for instrument_id, _ in self._bindings)

    def storage_catalog_snapshot(self) -> ChannelCatalog:
        """Return a defensive catalog value for one persistence transaction.

        The returned value carries descriptor data only.  It cannot bind a
        live reading or establish source/control authority; those operations
        remain owned by this instance.

        THE RESERVED ENTRY IS WITHHELD. It is a persistence concern -- a real descriptor for
        a reading whose channel nothing declares, which the readings foreign key requires --
        and it is NOT a live channel. Callers read this snapshot to build rosters of channels
        that exist: `validate_safety_pattern_liveness` derives its canonical-id set from it,
        so leaving the reserved identity in made an alarm that referenced it look live at
        startup while remaining inert, since no driver emits that spelling and undescribed
        readings keep their own labels. A configuration mistake that looks accepted is worse
        than one that is refused.

        The writer installs the entry itself, so withholding it here costs the persistence
        path nothing.
        """

        return snapshot_catalog(
            ChannelCatalog(
                [descriptor for descriptor in self._catalog.descriptors if descriptor.channel_id != UNBOUND_CHANNEL_ID]
            )
        )

    def emitted_channel_for_channel_id(self, channel_id: str) -> str:
        """Return the exact pre-bind emitted label for one declared channel."""
        if type(channel_id) is not str:
            raise TypeError("channel_id must be an exact string")
        for (_instrument_id, emitted_channel), bound_channel_id in self._bindings.items():
            if bound_channel_id == channel_id:
                return emitted_channel
        raise ChannelDescriptorStorageError("declared channel has no emitted-channel binding")

    def require_exact_instruments(self, instrument_ids: object) -> None:
        """Fail startup unless manifest and driver configuration agree exactly."""

        if type(instrument_ids) not in (tuple, list, frozenset, set):
            raise TypeError("configured instrument ids must be an explicit finite collection")
        configured = tuple(instrument_ids)
        if any(type(item) is not str for item in configured) or len(set(configured)) != len(configured):
            raise ChannelDescriptorStorageError("configured instrument ids are malformed or duplicated")
        expected = frozenset(configured)
        if self.instrument_ids != expected:
            missing = sorted(expected - self.instrument_ids)
            extra = sorted(self.instrument_ids - expected)
            raise ChannelDescriptorStorageError(
                f"live descriptor manifest instrument mismatch (missing={missing}, extra={extra})"
            )

    def bind(self, reading: object) -> DescriptorBoundReading:
        owned = _own_live_reading(reading)
        channel_id = self._bindings.get((owned.instrument_id, owned.channel))
        if channel_id is None:
            canonical_descriptor = self._catalog.by_channel_id.get(owned.channel)
            collides_with_declared_channel = any(
                emitted_channel == owned.channel for _, emitted_channel in self._bindings
            )
            if (
                canonical_descriptor is not None and canonical_descriptor.channel_id != UNBOUND_CHANNEL_ID
            ) or collides_with_declared_channel:
                raise ChannelDescriptorStorageError(
                    "live reading instrument_id disagrees with the explicit descriptor binding"
                )
            raise ChannelNotDescribedError(
                "live reading channel is unavailable in the explicit descriptor catalog bindings"
            )
        descriptor = self._catalog.by_channel_id[channel_id]
        descriptor_hash_for_reading(
            self._catalog,
            instrument_id=owned.instrument_id,
            channel=channel_id,
            unit=owned.unit,
        )
        # The emitted label above is only a lookup key. Every reading this
        # owner issues (and therefore every receipted/published Reading) must
        # carry the canonical descriptor.channel_id in `.channel`, matching
        # entry.channel_id and the persisted SQLite row exactly.
        if owned.channel != channel_id:
            owned = replace(owned, channel=channel_id)
        # Snapshot the selected descriptor independently of the catalog owner.
        envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
        selected = decode_persisted_channel_envelope(envelope.canonical_json).descriptor
        integrity_token = object()
        issued = DescriptorBoundReading._issue(
            owned,
            selected,
            owner_key=self._owner_key,
            integrity_token=integrity_token,
        )
        self._issued[issued] = _ReceiptIntegrity(
            payload=owned,
            descriptor=selected,
            payload_fingerprint=_owned_live_reading_fingerprint(owned),
            descriptor_envelope=PersistedChannelEnvelopeV1.from_descriptor(selected).canonical_json,
            token=integrity_token,
        )
        return issued

    def admit(self, reading: object) -> DescriptorBoundReading:
        """Bind a reading, or admit it against the reserved entry when nothing describes it.

        `bind` deliberately remains fail-closed for every direct caller. This is what the
        WRITE PATH uses, and the difference is the cost of a refusal.

        Measured 2026-08-21 on the real path, with a control: a batch of two readings, one
        on a channel the catalog does not describe, raised at admission and left NO DATABASE
        FILE AT ALL -- the described reading died with the undescribed one, on every
        acquisition cycle, for as long as the catalog gap lasted. A re-wired sensor or one
        added mid-campaign produces exactly that gap in an ordinary laboratory week.

        TWO CASES, AND ONLY ONE OF THEM CHANGES. A channel with no binding at all has no
        identity to contradict: it is admitted against the reserved entry, which grants no
        canonical identity and states that the channel is not described. A channel the
        catalog DOES describe under another instrument still raises -- that reading may not
        be the quantity the descriptor names, and storing it would put a wrong number under
        a real identity.
        """

        try:
            return self.bind(reading)
        except ChannelNotDescribedError:
            pass
        owned = _own_live_reading(reading)
        instrument_id, channel, unit = durable_unbound_reading_fields(
            owned.instrument_id,
            owned.channel,
            owned.unit,
        )
        owned = replace(owned, instrument_id=instrument_id, channel=channel, unit=unit)
        descriptor = _reserved_entry_of(self._catalog)
        envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
        selected = decode_persisted_channel_envelope(envelope.canonical_json).descriptor
        integrity_token = object()
        issued = DescriptorBoundReading._issue(
            owned,
            selected,
            owner_key=self._owner_key,
            integrity_token=integrity_token,
        )
        self._issued[issued] = _ReceiptIntegrity(
            payload=owned,
            descriptor=selected,
            payload_fingerprint=_owned_live_reading_fingerprint(owned),
            descriptor_envelope=PersistedChannelEnvelopeV1.from_descriptor(selected).canonical_json,
            token=integrity_token,
        )
        return issued

    def owns(self, candidate: object) -> bool:
        """Return whether this exact owner issued an intact observational receipt."""

        if type(candidate) is not DescriptorBoundReading:
            return False
        integrity = self._issued.get(candidate)
        if integrity is None:
            return False
        try:
            envelope = PersistedChannelEnvelopeV1.from_descriptor(candidate.descriptor)
            catalog_descriptor = self._catalog.by_channel_id.get(candidate.descriptor.channel_id)
            return (
                candidate._provenance is _BOUND_READING_PROVENANCE
                and candidate._owner_key is self._owner_key
                and candidate._integrity_token is integrity.token
                and candidate._payload is integrity.payload
                and candidate.descriptor is integrity.descriptor
                and _owned_live_reading_fingerprint(candidate._payload) == integrity.payload_fingerprint
                and envelope.canonical_json == integrity.descriptor_envelope
                and catalog_descriptor is not None
                and catalog_descriptor.canonical_json == candidate.descriptor.canonical_json
            )
        except (AttributeError, TypeError, ValueError, ChannelDescriptorError, ChannelDescriptorStorageError):
            return False


def _enable_foreign_keys(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    if conn.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise ChannelDescriptorStorageError("SQLite foreign keys could not be enabled")


def _columns(conn: sqlite3.Connection, table: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (row[1], str(row[2]).upper(), row[3], row[4], row[5])
        for row in conn.execute(f"PRAGMA main.table_info({table})")
    )


def _reject_temp_shadowing(conn: sqlite3.Connection) -> None:
    placeholders = ", ".join("?" for _ in _PROTECTED_TEMP_NAMES)
    protected = tuple(sorted(_PROTECTED_TEMP_NAMES))
    row = conn.execute(
        "SELECT type, name, tbl_name FROM sqlite_temp_master "
        f"WHERE name IN ({placeholders}) OR tbl_name IN ({placeholders}) LIMIT 1",
        (*protected, *protected),
    ).fetchone()
    if row is not None:
        raise ChannelDescriptorStorageError("temporary SQLite object shadows descriptor authority")


def _normalize_sql(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().rstrip(";")).casefold()
    return re.sub(r"\bif not exists ", "", normalized)


def _verify_object_sql(conn: sqlite3.Connection, object_type: str, name: str, expected_sql: str) -> None:
    row = conn.execute(
        "SELECT sql FROM main.sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    if row is None or type(row[0]) is not str or _normalize_sql(row[0]) != _normalize_sql(expected_sql):
        raise ChannelDescriptorStorageError(f"descriptor storage {object_type} {name!r} integrity mismatch")


def _verify_index(
    conn: sqlite3.Connection,
    name: str,
    columns: tuple[str, ...],
    expected_sql: str,
) -> None:
    row = conn.execute(
        "SELECT type FROM main.sqlite_master WHERE name = ?",
        (name,),
    ).fetchone()
    actual = tuple(item[2] for item in conn.execute(f"PRAGMA main.index_info({name})"))
    if row != ("index",) or actual != columns:
        raise ChannelDescriptorStorageError(f"descriptor storage index {name!r} integrity mismatch")
    _verify_object_sql(conn, "index", name, expected_sql)


def _verify_schema(conn: sqlite3.Connection) -> None:
    _reject_temp_shadowing(conn)
    if _columns(conn, "channel_descriptor_meta") != _META_COLUMNS:
        raise ChannelDescriptorStorageError("channel_descriptor_meta schema integrity mismatch")
    if _columns(conn, "channel_descriptors") != _DESCRIPTOR_COLUMNS:
        raise ChannelDescriptorStorageError("channel_descriptors schema integrity mismatch")
    if _columns(conn, "readings") != _V1_READING_COLUMNS:
        raise ChannelDescriptorStorageError("readings descriptor migration integrity mismatch")
    _verify_object_sql(conn, "table", "channel_descriptor_meta", SCHEMA_DESCRIPTOR_META)
    _verify_object_sql(conn, "table", "channel_descriptors", SCHEMA_DESCRIPTORS)
    _verify_object_sql(conn, "table", "readings", _MIGRATED_READINGS_SQL)

    meta = conn.execute("SELECT singleton, schema_version FROM main.channel_descriptor_meta").fetchall()
    if meta != [(1, CATALOG_SCHEMA_VERSION)]:
        raise ChannelDescriptorStorageError("channel descriptor metadata singleton integrity mismatch")

    for name, expected_sql in _TRIGGERS.items():
        row = conn.execute(
            "SELECT sql FROM main.sqlite_master WHERE type = 'trigger' AND name = ?",
            (name,),
        ).fetchone()
        if row is None or not isinstance(row[0], str) or _normalize_sql(row[0]) != _normalize_sql(expected_sql):
            raise ChannelDescriptorStorageError(f"descriptor storage trigger {name!r} integrity mismatch")

    actual_triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'trigger' "
            "AND tbl_name IN ('channel_descriptor_meta', 'channel_descriptors', 'readings')"
        )
    }
    if actual_triggers != set(_TRIGGERS):
        raise ChannelDescriptorStorageError("descriptor storage trigger set integrity mismatch")

    _verify_index(
        conn,
        "idx_channel_descriptors_channel_revision",
        ("channel_id", "descriptor_revision"),
        INDEX_DESCRIPTORS_CHANNEL_REVISION,
    )
    _verify_index(
        conn,
        "idx_readings_descriptor_hash",
        ("descriptor_hash",),
        INDEX_READINGS_DESCRIPTOR_HASH,
    )
    foreign_keys = [(row[2], row[3], row[4]) for row in conn.execute("PRAGMA main.foreign_key_list(readings)")]
    if foreign_keys != [("channel_descriptors", "descriptor_hash", "descriptor_hash")]:
        raise ChannelDescriptorStorageError("readings descriptor foreign-key integrity mismatch")


def initialize_descriptor_storage(conn: sqlite3.Connection) -> None:
    """Idempotently migrate one exact legacy readings schema to descriptor v1."""

    if conn.in_transaction:
        raise ChannelDescriptorStorageError("descriptor migration requires a clean transaction boundary")
    _enable_foreign_keys(conn)
    _reject_temp_shadowing(conn)

    reading_columns = _columns(conn, "readings")
    if reading_columns not in (_LEGACY_READING_COLUMNS, _V1_READING_COLUMNS):
        raise ChannelDescriptorStorageError("readings schema is neither exact legacy nor descriptor v1")
    if reading_columns == _V1_READING_COLUMNS:
        _verify_schema(conn)
        _load_envelopes(conn)
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")
        return

    try:
        conn.execute("BEGIN IMMEDIATE")
        # Another process may have completed the migration while this
        # connection waited for the write lock.  Re-read the authoritative
        # schema under the lock before issuing ALTER TABLE.
        reading_columns = _columns(conn, "readings")
        if reading_columns == _V1_READING_COLUMNS:
            _verify_schema(conn)
            _load_envelopes(conn)
            if conn.execute("PRAGMA main.foreign_key_check").fetchall():
                raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")
            conn.commit()
            return
        if reading_columns != _LEGACY_READING_COLUMNS:
            raise ChannelDescriptorStorageError("readings schema changed during descriptor migration")
        conn.execute(SCHEMA_DESCRIPTOR_META)
        conn.execute(SCHEMA_DESCRIPTORS)
        conn.execute(INDEX_DESCRIPTORS_CHANNEL_REVISION)
        for statement in _TRIGGERS.values():
            conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO main.channel_descriptor_meta (singleton, schema_version) VALUES (1, ?)",
            (CATALOG_SCHEMA_VERSION,),
        )
        conn.execute(
            "ALTER TABLE main.readings ADD COLUMN descriptor_hash TEXT REFERENCES channel_descriptors(descriptor_hash)"
        )
        conn.execute(INDEX_READINGS_DESCRIPTOR_HASH)
        _verify_schema(conn)
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor migration foreign-key check failed")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def snapshot_catalog(catalog: object) -> ChannelCatalog:
    """Copy and revalidate an exact catalog without retaining caller objects."""

    if type(catalog) is not ChannelCatalog:
        raise TypeError("channel_catalog must be exactly ChannelCatalog")
    envelopes = tuple(PersistedChannelEnvelopeV1.from_descriptor(item) for item in catalog.descriptors)
    descriptors = tuple(decode_persisted_channel_envelope(item.canonical_json).descriptor for item in envelopes)
    return ChannelCatalog(descriptors)


def _load_envelopes(conn: sqlite3.Connection) -> tuple[PersistedChannelEnvelopeV1, ...]:
    count, total_bytes, largest = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(length(envelope_json)), 0), "
        "COALESCE(MAX(length(envelope_json)), 0) FROM main.channel_descriptors"
    ).fetchone()
    if type(count) is not int or type(total_bytes) is not int or type(largest) is not int:
        raise ChannelDescriptorStorageError("descriptor catalog bounds are not integral")
    if (
        count > MAX_CATALOG_DESCRIPTORS
        or largest > MAX_PERSISTED_ENVELOPE_BYTES
        or total_bytes > MAX_CATALOG_ENVELOPE_BYTES
    ):
        raise ChannelDescriptorStorageError("descriptor catalog exceeds bounded storage limits")

    result: list[PersistedChannelEnvelopeV1] = []
    rows = conn.execute(
        "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
        "descriptor_revision, envelope_json FROM main.channel_descriptors "
        "ORDER BY channel_id, descriptor_revision"
    )
    for sql_hash, channel_id, instrument_id, source_key, revision, payload in rows:
        if type(payload) is not bytes:
            raise ChannelDescriptorStorageError("descriptor envelope is not stored as exact bytes")
        try:
            envelope = decode_persisted_channel_envelope(payload)
        except (TypeError, PersistedChannelEnvelopeError) as exc:
            raise ChannelDescriptorStorageError("persisted descriptor envelope is corrupt") from exc
        if payload != envelope.canonical_json:
            raise ChannelDescriptorStorageError("persisted descriptor envelope is not exact canonical bytes")
        repeated = (sql_hash, channel_id, instrument_id, source_key, revision)
        expected = (
            envelope.descriptor_hash,
            envelope.channel_id,
            envelope.instrument_id,
            envelope.source_key,
            envelope.descriptor_revision,
        )
        if repeated != expected:
            raise ChannelDescriptorStorageError("descriptor SQL indexes disagree with envelope authority")
        result.append(envelope)
    try:
        validate_catalog_update((), tuple(item.descriptor for item in result))
    except ChannelDescriptorError as exc:
        raise ChannelDescriptorStorageError("persisted descriptor history is invalid") from exc
    return tuple(result)


def install_catalog(
    conn: sqlite3.Connection,
    catalog: ChannelCatalog,
    *,
    within_transaction: bool = False,
) -> None:
    """Verify history and append an idempotent current catalog transactionally."""

    _enable_foreign_keys(conn)
    _verify_schema(conn)
    configured = snapshot_catalog(catalog)
    if type(within_transaction) is not bool:
        raise TypeError("within_transaction must be exactly bool")
    if within_transaction != conn.in_transaction:
        raise ChannelDescriptorStorageError("catalog transaction ownership mismatch")
    try:
        if not within_transaction:
            conn.execute("BEGIN IMMEDIATE")
        existing = _load_envelopes(conn)
        history = tuple(item.descriptor for item in existing)
        try:
            validate_catalog_update(history, configured.descriptors)
            ChannelCatalog(configured.descriptors, historical=history)
        except ChannelDescriptorError as exc:
            raise ChannelDescriptorStorageError(
                "configured descriptor catalog conflicts with persisted history"
            ) from exc
        for descriptor in configured.descriptors:
            envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
            prior = conn.execute(
                "SELECT channel_id, instrument_id, source_key, descriptor_revision, envelope_json "
                "FROM main.channel_descriptors WHERE descriptor_hash = ?",
                (envelope.descriptor_hash,),
            ).fetchone()
            if prior is not None:
                expected = (
                    envelope.channel_id,
                    envelope.instrument_id,
                    envelope.source_key,
                    envelope.descriptor_revision,
                    envelope.canonical_json,
                )
                if prior != expected:
                    raise ChannelDescriptorStorageError("descriptor hash collision or non-idempotent row")
                continue
            conn.execute(
                "INSERT INTO main.channel_descriptors "
                "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    envelope.descriptor_hash,
                    envelope.channel_id,
                    envelope.instrument_id,
                    envelope.source_key,
                    envelope.descriptor_revision,
                    envelope.canonical_json,
                ),
            )
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor catalog foreign-key check failed")
        # Validate the exact post-insert state before any commit.  This catches
        # unexpected trigger side effects and canonical/history corruption in
        # the same transaction that introduced it.
        _verify_schema(conn)
        _load_envelopes(conn)
        if not within_transaction:
            conn.commit()
    except Exception:
        if not within_transaction:
            conn.rollback()
        raise

    if not within_transaction:
        _verify_schema(conn)
        _load_envelopes(conn)


def verify_descriptor_storage(conn: sqlite3.Connection) -> None:
    """Verify the complete hot descriptor authority at the current cut."""

    _enable_foreign_keys(conn)
    _verify_schema(conn)
    _load_envelopes(conn)
    if conn.execute("PRAGMA main.foreign_key_check").fetchall():
        raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")


def descriptor_hash_for_reading(
    catalog: ChannelCatalog,
    *,
    instrument_id: object,
    channel: object,
    unit: object,
) -> str:
    """Bind a reading to the configured current descriptor or fail closed."""

    if any(type(item) is not str for item in (instrument_id, channel, unit)):
        raise ChannelDescriptorStorageError("descriptor-required reading identity must use exact strings")
    descriptor = catalog.by_channel_id.get(channel)
    if descriptor is None:
        raise ChannelNotDescribedError("descriptor-required reading has an unknown channel_id")
    if descriptor.instrument_id != instrument_id:
        raise ChannelDescriptorStorageError("reading instrument_id disagrees with descriptor")
    if descriptor.unit != unit:
        raise ChannelDescriptorStorageError("reading unit disagrees with descriptor")
    return descriptor.descriptor_hash


def _verify_present_descriptor_envelope(
    conn: sqlite3.Connection,
    descriptor_hash: object,
) -> PersistedChannelEnvelopeV1:
    """Verify one PRESENT descriptor reference down to its exact stored bytes.

    Schema, catalog envelopes, triggers and foreign keys are all checked, then the
    stored row must decode to canonical bytes whose indexes agree with the reference
    hash. This is the integrity half of :func:`resolve_sqlite_descriptor`, shared with
    the reserved-row shortcut in :func:`read_sqlite_reading` so that no reader can
    certify a database the full verifier rejects.
    """

    if type(descriptor_hash) is not str:
        raise ChannelDescriptorStorageError("present descriptor_hash is not an exact string")
    _verify_schema(conn)
    _load_envelopes(conn)
    if conn.execute("PRAGMA main.foreign_key_check").fetchall():
        raise ChannelDescriptorStorageError("present descriptor reference fails foreign-key integrity")
    row = conn.execute(
        "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
        "descriptor_revision, envelope_json FROM main.channel_descriptors WHERE descriptor_hash = ?",
        (descriptor_hash,),
    ).fetchone()
    if row is None:
        raise ChannelDescriptorStorageError("present descriptor_hash has no catalog row")
    sql_hash, channel_id, instrument_id, source_key, revision, payload = row
    if type(payload) is not bytes:
        raise ChannelDescriptorStorageError("present descriptor envelope is not exact bytes")
    try:
        envelope = decode_persisted_channel_envelope(payload)
    except (TypeError, PersistedChannelEnvelopeError) as exc:
        raise ChannelDescriptorStorageError("present descriptor envelope is corrupt") from exc
    if payload != envelope.canonical_json:
        raise ChannelDescriptorStorageError("present descriptor envelope is not exact canonical bytes")
    if (
        sql_hash,
        channel_id,
        instrument_id,
        source_key,
        revision,
    ) != (
        envelope.descriptor_hash,
        envelope.channel_id,
        envelope.instrument_id,
        envelope.source_key,
        envelope.descriptor_revision,
    ):
        raise ChannelDescriptorStorageError("present descriptor indexes disagree with envelope")
    return envelope


def resolve_sqlite_descriptor(
    conn: sqlite3.Connection,
    descriptor_hash: object,
    *,
    legacy_instrument_id: object,
    legacy_channel: object,
    legacy_unit: object,
) -> ChannelDescriptorV1:
    """Resolve one hot row; only SQL NULL is allowed to select legacy."""

    _enable_foreign_keys(conn)
    if descriptor_hash is None:
        reading_columns = _columns(conn, "readings")
        if reading_columns == _V1_READING_COLUMNS:
            _verify_schema(conn)
            _load_envelopes(conn)
            if conn.execute("PRAGMA main.foreign_key_check").fetchall():
                raise ChannelDescriptorStorageError("legacy row database fails foreign-key integrity")
        elif reading_columns != _LEGACY_READING_COLUMNS:
            raise ChannelDescriptorStorageError("legacy row belongs to an unknown readings schema")
        return resolve_persisted_channel(
            None,
            legacy_instrument_id=legacy_instrument_id,
            legacy_channel=legacy_channel,
            legacy_unit=legacy_unit,
        )
    envelope = _verify_present_descriptor_envelope(conn, descriptor_hash)
    if (
        envelope.instrument_id != legacy_instrument_id
        or envelope.channel_id != legacy_channel
        or envelope.descriptor.unit != legacy_unit
    ):
        raise ChannelDescriptorStorageError("reading identity disagrees with present descriptor")
    return envelope.descriptor


def _resolve_hot_row_descriptor(
    conn: sqlite3.Connection,
    descriptor_hash: object,
    *,
    instrument_id: str,
    channel: str,
    unit: str,
) -> ChannelDescriptorV1 | None:
    """Resolve one V1 hot row's descriptor, earning the reserved shortcut first.

    The shortcut returns ``None`` for a row referencing the reserved entry -- that entry
    deliberately describes no real channel, so the reading-identity comparison would
    refuse exactly the rows it exists to keep. But the shortcut used to bypass the
    storage verification entirely: review mutated the stored reserved envelope while
    keeping its hash column and this reader returned the row normally while
    :func:`verify_descriptor_storage` rejected the same database as corrupt. The
    integrity check now runs FIRST and the stored envelope must be the canonical
    reserved one, so no public reader certifies bytes the authority layer calls broken.
    """

    if descriptor_hash == UNBOUND_DESCRIPTOR_HASH:
        envelope = _verify_present_descriptor_envelope(conn, descriptor_hash)
        if envelope.descriptor != unbound_channel_descriptor():
            raise ChannelDescriptorStorageError(
                "reserved descriptor reference disagrees with the canonical reserved entry"
            )
        return None
    return resolve_sqlite_descriptor(
        conn,
        descriptor_hash,
        legacy_instrument_id=instrument_id,
        legacy_channel=channel,
        legacy_unit=unit,
    )


def read_sqlite_reading(conn: sqlite3.Connection, reading_id: object) -> ResolvedSQLiteReading:
    """Read one hot row and return an owned reading-plus-descriptor value."""

    _enable_foreign_keys(conn)
    if type(reading_id) is not int or reading_id < 1:
        raise TypeError("reading_id must be a positive exact integer")
    reading_columns = _columns(conn, "readings")
    if reading_columns == _LEGACY_READING_COLUMNS:
        row = conn.execute(
            "SELECT id, timestamp, instrument_id, channel, value, unit, status FROM main.readings WHERE id = ?",
            (reading_id,),
        ).fetchone()
        if row is not None:
            row = (*row, None)
    elif reading_columns == _V1_READING_COLUMNS:
        row = conn.execute(
            "SELECT id, timestamp, instrument_id, channel, value, unit, status, descriptor_hash "
            "FROM main.readings WHERE id = ?",
            (reading_id,),
        ).fetchone()
    else:
        raise ChannelDescriptorStorageError("hot reading belongs to an unknown readings schema")
    if row is None:
        raise ChannelDescriptorStorageError("hot reading row does not exist")
    row_id, timestamp, instrument_id, channel, value, unit, status, descriptor_hash = row
    if (
        type(row_id) is not int
        or type(timestamp) not in (int, float)
        or type(instrument_id) is not str
        or type(channel) is not str
        or type(value) not in (int, float)
        or type(unit) is not str
        or type(status) is not str
    ):
        raise ChannelDescriptorStorageError("hot reading row has invalid SQLite value types")
    descriptor = (
        None
        if reading_columns == _LEGACY_READING_COLUMNS
        else _resolve_hot_row_descriptor(
            conn,
            descriptor_hash,
            instrument_id=instrument_id,
            channel=channel,
            unit=unit,
        )
    )
    return ResolvedSQLiteReading(
        id=row_id,
        timestamp=float(timestamp),
        instrument_id=instrument_id,
        channel=channel,
        value=float(value),
        unit=unit,
        status=status,
        descriptor=descriptor,
    )


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "MAX_CATALOG_ENVELOPE_BYTES",
    "MAX_LIVE_DESCRIPTOR_CONFIG_BYTES",
    "MAX_LIVE_DESCRIPTOR_CONFIG_DEPTH",
    "MAX_LIVE_METADATA_AGGREGATE_BYTES",
    "MAX_LIVE_METADATA_DEPTH",
    "MAX_LIVE_METADATA_ITEMS",
    "MAX_LIVE_METADATA_TEXT_BYTES",
    "MAX_LIVE_READING_TEXT_BYTES",
    "MAX_PERSISTED_READING_ID_BYTES",
    "MAX_PERSISTED_READING_UNIT_BYTES",
    "ChannelDescriptorProjection",
    "ChannelDescriptorStorageError",
    "DescriptorBoundReading",
    "LiveChannelDescriptorCatalog",
    "ResolvedSQLiteReading",
    "descriptor_hash_for_reading",
    "durable_unbound_reading_fields",
    "initialize_descriptor_storage",
    "install_catalog",
    "load_live_channel_descriptor_catalog",
    "normalize_persisted_unbound_channel",
    "persisted_unbound_channel_alias",
    "persisted_unbound_channel_may_have_alias",
    "normalize_persisted_unbound_reading_fields",
    "project_channel_descriptor",
    "project_channel_descriptor_payload",
    "read_sqlite_reading",
    "resolve_sqlite_descriptor",
    "snapshot_catalog",
    "verify_descriptor_storage",
]
