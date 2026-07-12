"""Pure persisted channel-identity envelope.

This module defines bytes that storage, archive and replay adapters may carry
later.  It deliberately performs no I/O, imports no driver or storage code,
and grants no acquisition, publication, safety or control authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

from cryodaq.channels.config import ChannelConfigError, parse_channel_descriptor
from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    legacy_unknown_descriptor,
)

MAX_PERSISTED_ENVELOPE_BYTES: Final = 8192
_ENVELOPE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "channel_id",
        "instrument_id",
        "source_key",
        "descriptor_revision",
        "descriptor_hash",
        "descriptor",
    }
)


class PersistedChannelEnvelopeError(ChannelDescriptorError):
    """Persisted descriptor bytes are malformed, ambiguous or corrupted."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PersistedChannelEnvelopeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _verified_descriptor(descriptor: object) -> ChannelDescriptorV1:
    if type(descriptor) is not ChannelDescriptorV1:
        raise TypeError("descriptor must be exactly ChannelDescriptorV1")
    try:
        # Reconstruct into an object owned by this envelope.  Frozen dataclasses
        # can still be mutated with object.__setattr__, so retaining the caller's
        # instance would let later hostile mutation split the descriptor object
        # from the already-frozen canonical envelope bytes.
        verified = ChannelDescriptorV1(
            schema_version=descriptor.schema_version,
            channel_id=descriptor.channel_id,
            instrument_id=descriptor.instrument_id,
            source_key=descriptor.source_key,
            quantity=descriptor.quantity,
            unit=descriptor.unit,
            role=descriptor.role,
            safety_class=descriptor.safety_class,
            display_group=descriptor.display_group,
            display_name=descriptor.display_name,
            visible_by_default=descriptor.visible_by_default,
            display_order=descriptor.display_order,
            descriptor_revision=descriptor.descriptor_revision,
        )
        if descriptor.canonical_json != verified.canonical_json:
            raise PersistedChannelEnvelopeError("descriptor canonical_json integrity mismatch")
        if descriptor.descriptor_hash != verified.descriptor_hash:
            raise PersistedChannelEnvelopeError("descriptor hash integrity mismatch")
        # Synthetic legacy descriptors are migration results, never an
        # authoritative persisted envelope document.
        ChannelCatalog([verified])
        return verified
    except (AttributeError, TypeError, ChannelDescriptorError) as exc:
        raise PersistedChannelEnvelopeError(f"descriptor integrity: {exc}") from exc


@dataclass(frozen=True, slots=True)
class PersistedChannelEnvelopeV1:
    """Self-contained immutable snapshot of one authoritative descriptor.

    The repeated identity fields make indexing possible without interpreting
    the descriptor document.  Construction requires every repeated field to
    match the verified document, so none can become an independent authority.
    """

    schema_version: int
    channel_id: str
    instrument_id: str
    source_key: str
    descriptor_revision: int
    descriptor_hash: str
    descriptor: ChannelDescriptorV1
    canonical_json: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise PersistedChannelEnvelopeError("schema_version must be the integer 1")
        if any(type(value) is not str for value in (self.channel_id, self.instrument_id, self.source_key)):
            raise TypeError("envelope identity anchors must be exact strings")
        if type(self.descriptor_revision) is not int:
            raise TypeError("descriptor_revision must be exactly an integer")
        if type(self.descriptor_hash) is not str:
            raise TypeError("descriptor_hash must be exactly a string")
        verified = _verified_descriptor(self.descriptor)
        expected = (
            verified.channel_id,
            verified.instrument_id,
            verified.source_key,
            verified.descriptor_revision,
            verified.descriptor_hash,
        )
        actual = (
            self.channel_id,
            self.instrument_id,
            self.source_key,
            self.descriptor_revision,
            self.descriptor_hash,
        )
        if actual != expected:
            raise PersistedChannelEnvelopeError("envelope identity does not match descriptor document")

        descriptor_document = json.loads(verified.canonical_json)
        payload = {
            "schema_version": 1,
            "channel_id": verified.channel_id,
            "instrument_id": verified.instrument_id,
            "source_key": verified.source_key,
            "descriptor_revision": verified.descriptor_revision,
            "descriptor_hash": verified.descriptor_hash,
            "descriptor": descriptor_document,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(canonical) > MAX_PERSISTED_ENVELOPE_BYTES:
            raise PersistedChannelEnvelopeError("persisted descriptor envelope exceeds byte limit")
        object.__setattr__(self, "descriptor", verified)
        object.__setattr__(self, "canonical_json", canonical)

    @classmethod
    def from_descriptor(cls, descriptor: ChannelDescriptorV1) -> PersistedChannelEnvelopeV1:
        verified = _verified_descriptor(descriptor)
        return cls(
            schema_version=1,
            channel_id=verified.channel_id,
            instrument_id=verified.instrument_id,
            source_key=verified.source_key,
            descriptor_revision=verified.descriptor_revision,
            descriptor_hash=verified.descriptor_hash,
            descriptor=verified,
        )

    @property
    def grants_control_authority(self) -> bool:
        return False


def decode_persisted_channel_envelope(payload: object) -> PersistedChannelEnvelopeV1:
    """Decode strict canonical-compatible JSON bytes and verify all identity."""

    if type(payload) is not bytes:
        raise TypeError("persisted channel envelope must be bytes")
    if not payload or len(payload) > MAX_PERSISTED_ENVELOPE_BYTES:
        raise PersistedChannelEnvelopeError("persisted channel envelope has invalid byte length")
    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except PersistedChannelEnvelopeError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise PersistedChannelEnvelopeError("persisted channel envelope is not strict UTF-8 JSON") from exc
    if type(decoded) is not dict:
        raise PersistedChannelEnvelopeError("persisted channel envelope must be a JSON object")
    if any(type(key) is not str for key in decoded):
        raise PersistedChannelEnvelopeError("persisted channel envelope keys must be strings")
    keys = set(decoded)
    if keys != _ENVELOPE_FIELDS:
        missing = sorted(_ENVELOPE_FIELDS - keys)
        extra = sorted(keys - _ENVELOPE_FIELDS)
        raise PersistedChannelEnvelopeError(f"persisted channel envelope has missing={missing!r} extra={extra!r}")
    try:
        descriptor = parse_channel_descriptor(decoded["descriptor"], path="persisted.descriptor")
        return PersistedChannelEnvelopeV1(
            schema_version=decoded["schema_version"],
            channel_id=decoded["channel_id"],
            instrument_id=decoded["instrument_id"],
            source_key=decoded["source_key"],
            descriptor_revision=decoded["descriptor_revision"],
            descriptor_hash=decoded["descriptor_hash"],
            descriptor=descriptor,
        )
    except (TypeError, ChannelConfigError, ChannelDescriptorError) as exc:
        raise PersistedChannelEnvelopeError(f"invalid persisted channel envelope: {exc}") from exc


def resolve_persisted_channel(
    payload: bytes | None,
    *,
    legacy_instrument_id: object,
    legacy_channel: object,
    legacy_unit: object,
) -> ChannelDescriptorV1:
    """Resolve a persisted envelope or deterministically classify a legacy row.

    Only absence selects the legacy path.  Present-but-invalid bytes fail
    closed and are never reclassified as trustworthy legacy data.
    """

    if payload is None:
        return legacy_unknown_descriptor(legacy_instrument_id, legacy_channel, legacy_unit)
    return decode_persisted_channel_envelope(payload).descriptor


__all__ = [
    "MAX_PERSISTED_ENVELOPE_BYTES",
    "PersistedChannelEnvelopeError",
    "PersistedChannelEnvelopeV1",
    "decode_persisted_channel_envelope",
    "resolve_persisted_channel",
]
