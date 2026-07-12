"""Bounded storage-only adapter for archived channel descriptor envelopes.

This leaf translates the pure channel identity contract into immutable storage
rows.  It grants no acquisition, publication, source, safety, or control
authority and keeps cold rotation independent of the channel package.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelDescriptorError,
    validate_catalog_update,
)
from cryodaq.channels.persistence import (
    MAX_PERSISTED_ENVELOPE_BYTES,
    PersistedChannelEnvelopeError,
    decode_persisted_channel_envelope,
)
from cryodaq.storage._sqlite import sqlite3

MAX_ARCHIVE_DESCRIPTORS: Final = MAX_CATALOG_DESCRIPTORS
MAX_ARCHIVE_DESCRIPTOR_BYTES: Final = MAX_CATALOG_DESCRIPTORS * MAX_PERSISTED_ENVELOPE_BYTES


class DescriptorArchiveError(RuntimeError):
    """Descriptor archive authority is missing, malformed, or ambiguous."""


@dataclass(frozen=True, slots=True)
class ArchivedDescriptor:
    descriptor_hash: str
    channel_id: str
    instrument_id: str
    source_key: str
    descriptor_revision: int
    envelope_json: bytes

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class ResolvedStorageDescriptor:
    descriptor_hash: str
    channel_id: str
    instrument_id: str
    source_key: str
    descriptor_revision: int
    quantity: str
    unit: str
    role: str
    safety_class: str
    display_group: str
    display_name: str
    visible_by_default: bool
    display_order: int
    envelope_json: bytes | None
    legacy: bool

    @property
    def grants_control_authority(self) -> bool:
        return False


def _verified_rows(
    rows: Iterable[ArchivedDescriptor],
) -> tuple[tuple[ArchivedDescriptor, ResolvedStorageDescriptor], ...]:
    materialized: list[ArchivedDescriptor] = []
    total_bytes = 0
    for row in rows:
        if len(materialized) >= MAX_ARCHIVE_DESCRIPTORS:
            raise DescriptorArchiveError("descriptor archive row count is out of bounds")
        if type(row) is not ArchivedDescriptor or type(row.envelope_json) is not bytes:
            raise DescriptorArchiveError("descriptor archive row types are not exact")
        envelope_size = len(row.envelope_json)
        if envelope_size > MAX_PERSISTED_ENVELOPE_BYTES:
            raise DescriptorArchiveError("descriptor archive envelope exceeds byte bound")
        total_bytes += envelope_size
        if total_bytes > MAX_ARCHIVE_DESCRIPTOR_BYTES:
            raise DescriptorArchiveError("descriptor archive exceeds envelope byte bound")
        materialized.append(row)
    if not materialized:
        raise DescriptorArchiveError("descriptor archive row count is out of bounds")
    descriptors = []
    resolved: list[tuple[ArchivedDescriptor, ResolvedStorageDescriptor]] = []
    hashes: list[str] = []
    for row in materialized:
        try:
            envelope = decode_persisted_channel_envelope(row.envelope_json)
        except (TypeError, PersistedChannelEnvelopeError) as exc:
            raise DescriptorArchiveError("descriptor archive envelope is corrupt") from exc
        if row.envelope_json != envelope.canonical_json:
            raise DescriptorArchiveError("descriptor archive envelope is not canonical")
        if (
            row.descriptor_hash,
            row.channel_id,
            row.instrument_id,
            row.source_key,
            row.descriptor_revision,
        ) != (
            envelope.descriptor_hash,
            envelope.channel_id,
            envelope.instrument_id,
            envelope.source_key,
            envelope.descriptor_revision,
        ):
            raise DescriptorArchiveError("descriptor archive anchors disagree with envelope")
        hashes.append(row.descriptor_hash)
        descriptors.append(envelope.descriptor)
        descriptor = envelope.descriptor
        resolved.append(
            (
                row,
                ResolvedStorageDescriptor(
                    descriptor_hash=descriptor.descriptor_hash,
                    channel_id=descriptor.channel_id,
                    instrument_id=descriptor.instrument_id,
                    source_key=descriptor.source_key,
                    descriptor_revision=descriptor.descriptor_revision,
                    quantity=descriptor.quantity.value,
                    unit=descriptor.unit,
                    role=descriptor.role.value,
                    safety_class=descriptor.safety_class.value,
                    display_group=descriptor.display_group,
                    display_name=descriptor.display_name,
                    visible_by_default=descriptor.visible_by_default,
                    display_order=descriptor.display_order,
                    envelope_json=row.envelope_json,
                    legacy=False,
                ),
            )
        )
    if hashes != sorted(hashes) or len(set(hashes)) != len(hashes):
        raise DescriptorArchiveError("descriptor archive hashes are not unique and sorted")
    try:
        validate_catalog_update((), tuple(descriptors))
    except ChannelDescriptorError as exc:
        raise DescriptorArchiveError("descriptor archive history is invalid") from exc
    return tuple(resolved)


def load_referenced_descriptors(
    conn: sqlite3.Connection,
    referenced_hashes: set[str],
) -> tuple[ArchivedDescriptor, ...]:
    """Load and verify full hot history, returning sorted referenced rows only."""
    if not referenced_hashes:
        return ()
    if len(referenced_hashes) > MAX_ARCHIVE_DESCRIPTORS:
        raise DescriptorArchiveError("referenced descriptor set exceeds bound")
    table = conn.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='channel_descriptors'"
    ).fetchone()
    if table is None:
        raise DescriptorArchiveError("descriptor-bearing readings have no descriptor catalog")
    count, total_bytes, largest = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(length(envelope_json)), 0), "
        "COALESCE(MAX(length(envelope_json)), 0) FROM main.channel_descriptors"
    ).fetchone()
    if any(type(value) is not int for value in (count, total_bytes, largest)):
        raise DescriptorArchiveError("descriptor catalog bounds are not integral")
    if (
        count > MAX_ARCHIVE_DESCRIPTORS
        or total_bytes > MAX_ARCHIVE_DESCRIPTOR_BYTES
        or largest > MAX_PERSISTED_ENVELOPE_BYTES
    ):
        raise DescriptorArchiveError("descriptor catalog exceeds archive bounds")
    verified = _verified_rows(
        ArchivedDescriptor(*row)
        for row in conn.execute(
            "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
            "descriptor_revision, envelope_json FROM main.channel_descriptors ORDER BY descriptor_hash"
        )
    )
    by_hash = {row.descriptor_hash: row for row, _resolved in verified}
    if not referenced_hashes.issubset(by_hash):
        raise DescriptorArchiveError("reading references a missing descriptor")
    return tuple(by_hash[item] for item in sorted(referenced_hashes))


def verify_archived_descriptors(
    rows: Iterable[ArchivedDescriptor],
    referenced_hashes: set[str],
) -> tuple[ArchivedDescriptor, ...]:
    """Verify one reopened sidecar and its exact readings reference set."""
    verified = _verified_rows(rows)
    if {row.descriptor_hash for row, _resolved in verified} != referenced_hashes:
        raise DescriptorArchiveError("descriptor sidecar does not match referenced hash set")
    return tuple(row for row, _resolved in verified)


def resolve_archived_descriptors(
    rows: Iterable[ArchivedDescriptor],
    referenced_hashes: set[str],
) -> dict[str, ResolvedStorageDescriptor]:
    """Verify and resolve a sidecar to neutral, observational storage values."""
    verified = _verified_rows(rows)
    result = {row.descriptor_hash: resolved for row, resolved in verified}
    if set(result) != referenced_hashes:
        raise DescriptorArchiveError("descriptor sidecar does not match referenced hash set")
    return result


def resolve_legacy_descriptor(
    instrument_id: object,
    channel: object,
    unit: object,
) -> ResolvedStorageDescriptor:
    """Return the deterministic neutral form of a synthetic legacy descriptor."""
    from cryodaq.channels.descriptors import legacy_unknown_descriptor

    descriptor = legacy_unknown_descriptor(instrument_id, channel, unit)
    return ResolvedStorageDescriptor(
        descriptor_hash=descriptor.descriptor_hash,
        channel_id=descriptor.channel_id,
        instrument_id=descriptor.instrument_id,
        source_key=descriptor.source_key,
        descriptor_revision=descriptor.descriptor_revision,
        quantity=descriptor.quantity.value,
        unit=descriptor.unit,
        role=descriptor.role.value,
        safety_class=descriptor.safety_class.value,
        display_group=descriptor.display_group,
        display_name=descriptor.display_name,
        visible_by_default=descriptor.visible_by_default,
        display_order=descriptor.display_order,
        envelope_json=None,
        legacy=True,
    )


__all__ = [
    "MAX_ARCHIVE_DESCRIPTORS",
    "MAX_ARCHIVE_DESCRIPTOR_BYTES",
    "ArchivedDescriptor",
    "ResolvedStorageDescriptor",
    "DescriptorArchiveError",
    "PersistedChannelEnvelopeError",
    "decode_persisted_channel_envelope",
    "load_referenced_descriptors",
    "resolve_archived_descriptors",
    "resolve_legacy_descriptor",
    "verify_archived_descriptors",
]
