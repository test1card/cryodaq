"""Pure live-channel presentation derived only from canonical identity.

No configuration, YAML, ChannelManager, driver, GUI, or I/O dependency is
allowed here.  A descriptor contributes presentation text only after its own
immutable contract and exact channel identity have been verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cryodaq.channels.descriptors import ChannelCatalog, ChannelDescriptorError, ChannelDescriptorV1


class LiveDisplayProvenance(StrEnum):
    """Closed provenance vocabulary for one live channel label."""

    CANONICAL_ID_ONLY = "canonical_id_only"
    VERIFIED_DESCRIPTOR = "verified_descriptor"


@dataclass(frozen=True, slots=True)
class LiveChannelPresentation:
    """Stable human label that always retains the canonical channel ID."""

    channel_id: str
    label: str
    provenance: LiveDisplayProvenance

    @property
    def descriptor_available(self) -> bool:
        return self.provenance is LiveDisplayProvenance.VERIFIED_DESCRIPTOR

    @property
    def grants_control_authority(self) -> bool:
        return False


def live_channel_presentation(
    channel_id: str,
    descriptor: ChannelDescriptorV1 | None,
) -> LiveChannelPresentation:
    """Return canonical-ID-only or canonical-ID plus verified display name.

    Absence is an ordinary cold/legacy state and never triggers a local lookup.
    A present descriptor must be a valid authoritative descriptor for the exact
    requested channel; mismatches fail closed instead of relabeling a reading.
    """

    if type(channel_id) is not str:
        raise TypeError("channel_id must be exactly a string")
    try:
        encoded = channel_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("channel_id must be valid UTF-8") from exc
    if not encoded or len(encoded) > 128:
        raise ValueError("channel_id must contain 1..128 UTF-8 bytes")
    if descriptor is None:
        return LiveChannelPresentation(
            channel_id=channel_id,
            label=channel_id,
            provenance=LiveDisplayProvenance.CANONICAL_ID_ONLY,
        )
    if type(descriptor) is not ChannelDescriptorV1:
        raise TypeError("descriptor must be exactly ChannelDescriptorV1 or None")
    try:
        verified = ChannelCatalog([descriptor]).by_channel_id[descriptor.channel_id]
    except (TypeError, ChannelDescriptorError) as exc:
        raise ValueError(f"descriptor is not authoritative: {exc}") from exc
    if verified.channel_id != channel_id:
        raise ValueError("descriptor channel_id does not match requested channel_id")
    return LiveChannelPresentation(
        channel_id=channel_id,
        label=f"{channel_id} · {verified.display_name}",
        provenance=LiveDisplayProvenance.VERIFIED_DESCRIPTOR,
    )


__all__ = [
    "LiveChannelPresentation",
    "LiveDisplayProvenance",
    "live_channel_presentation",
]
