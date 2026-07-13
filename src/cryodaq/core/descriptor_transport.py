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
