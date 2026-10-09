"""Provider-neutral descriptor qualification for observational readings.

This module owns no socket, queue, topic, publication, persistence, safety, or
control authority.  It only verifies an optional persisted descriptor envelope
against the exact identity tuple carried by one :class:`Reading`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cryodaq.channels.descriptors import ChannelDescriptorV1
from cryodaq.channels.persistence import (
    PersistedChannelEnvelopeError,
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
)
from cryodaq.drivers.base import Reading


class DescriptorEnvelopeIssue(StrEnum):
    """Bounded, provider-neutral reason that a present descriptor was refused."""

    MALFORMED = "malformed"
    IDENTITY_MISMATCH = "identity_mismatch"


@dataclass(frozen=True, slots=True)
class DescriptorQualifiedReading:
    """One immutable reading plus a verified observational descriptor, if any.

    Absence is not an error: old/non-opted publishers produce ``descriptor=None``
    and ``descriptor_issue=None``.  A present envelope that is malformed,
    oversized, or does not match the exact channel/instrument/unit tuple keeps
    the Reading but carries a bounded visible issue and no descriptor.
    """

    reading: Reading
    descriptor: ChannelDescriptorV1 | None
    descriptor_issue: DescriptorEnvelopeIssue | None = None

    @property
    def grants_control_authority(self) -> bool:
        return False


def encode_descriptor_envelope(descriptor: ChannelDescriptorV1) -> bytes:
    """Return the canonical envelope bytes for one descriptor.

    This is the encode half of the translation whose decode half is
    :func:`qualify_reading_descriptor`.  It lives here so that callers which
    only need to COMPARE descriptor identity — the interlock engine binding its
    declared sensors, for instance — can hold opaque bytes without importing the
    channel contract itself.  Comparing bytes produced here against bytes taken
    off the wire is the whole point: a caller that imported the envelope type
    could also reach the descriptor's fields, and a safety component that can
    read a descriptor's fields can be tempted to act on them.

    Owns no persistence authority: this synthesises nothing and stores nothing,
    it serialises a descriptor the caller already holds.
    """

    return PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json


def qualify_reading_descriptor(
    reading: Reading,
    payload: object,
    *,
    envelope_present: bool | None = None,
    malformed_at_boundary: bool = False,
) -> DescriptorQualifiedReading:
    """Verify one optional descriptor envelope without lookup or synthesis.

    ``envelope_present`` distinguishes an absent old-wire field from a present
    null value.  Boundary adapters that have already dropped malformed bytes
    may set ``malformed_at_boundary`` while passing ``payload=None``.
    """

    present = payload is not None if envelope_present is None else envelope_present
    if not present:
        return DescriptorQualifiedReading(reading=reading, descriptor=None)
    if malformed_at_boundary or type(payload) is not bytes:
        return DescriptorQualifiedReading(
            reading=reading,
            descriptor=None,
            descriptor_issue=DescriptorEnvelopeIssue.MALFORMED,
        )
    try:
        envelope = decode_persisted_channel_envelope(payload)
    except (TypeError, PersistedChannelEnvelopeError):
        return DescriptorQualifiedReading(
            reading=reading,
            descriptor=None,
            descriptor_issue=DescriptorEnvelopeIssue.MALFORMED,
        )
    descriptor = envelope.descriptor
    if (
        envelope.channel_id != reading.channel
        or envelope.instrument_id != reading.instrument_id
        or descriptor.unit != reading.unit
    ):
        return DescriptorQualifiedReading(
            reading=reading,
            descriptor=None,
            descriptor_issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
        )
    return DescriptorQualifiedReading(reading=reading, descriptor=descriptor)
