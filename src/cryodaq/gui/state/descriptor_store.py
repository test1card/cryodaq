"""GUI-thread-owned bounded descriptor identity store.

This store is the single identity authority for the shell.  It ingests
:class:`DescriptorQualifiedReading` items drained synchronously on the GUI
thread and resolves each channel's identity to one of three statuses:
authoritative, legacy_absent, or refused.  It never grants control authority.

The store is plain Python (no Qt): the reading drain already runs on the GUI
thread synchronously, so no cross-thread marshalling is needed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelDescriptorV1,
    legacy_unknown_descriptor,
)
from cryodaq.core.descriptor_transport import (
    DescriptorEnvelopeIssue,
    DescriptorQualifiedReading,
)
from cryodaq.drivers.base import Reading

_MAX_DIAGNOSTICS_PER_ENTRY: Final = 16


class IdentityStatus(StrEnum):
    """Presentation-facing classification of a channel's descriptor identity."""

    AUTHORITATIVE = "authoritative"
    LEGACY_ABSENT = "legacy_absent"
    REFUSED = "refused"


class TransportState(StrEnum):
    """Transport freshness of a channel's most recent reading."""

    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class IngestResult(StrEnum):
    """Bounded outcome of one attempted store ingestion."""

    ACCEPTED = "accepted"
    LEGACY_ABSENT = "legacy_absent"
    REFUSED = "refused"
    CAPACITY_EXHAUSTED = "capacity_exhausted"


@dataclass(frozen=True, slots=True)
class DescriptorDiagnostic:
    """Bounded record of one descriptor refusal."""

    reason: str
    incoming_revision: int | None
    descriptor_issue: DescriptorEnvelopeIssue | None


@dataclass(frozen=True, slots=True)
class DescriptorView:
    """Read-only presentation snapshot of one channel's descriptor identity."""

    channel_id: str
    descriptor: ChannelDescriptorV1
    identity_status: IdentityStatus
    transport_state: TransportState
    diagnostics: tuple[DescriptorDiagnostic, ...]

    @property
    def grants_control_authority(self) -> bool:
        return False


class _Entry:
    """Mutable per-channel entry owned exclusively by the store."""

    __slots__ = (
        "descriptor",
        "identity_status",
        "transport_state",
        "diagnostics",
        "_legacy_args",
        "_legacy_cache",
    )

    def __init__(self) -> None:
        self.descriptor: ChannelDescriptorV1 | None = None
        self.identity_status: IdentityStatus | None = None
        self.transport_state: TransportState = TransportState.DISCONNECTED
        self.diagnostics: list[DescriptorDiagnostic] = []
        self._legacy_args: tuple[str, str, str] | None = None
        self._legacy_cache: ChannelDescriptorV1 | None = None

    def presentation_descriptor(self) -> ChannelDescriptorV1:
        if self.descriptor is not None:
            return self.descriptor
        if self._legacy_cache is None:
            assert self._legacy_args is not None
            instrument_id, channel, unit = self._legacy_args
            self._legacy_cache = legacy_unknown_descriptor(instrument_id, channel, unit)
        return self._legacy_cache

    def add_diagnostic(self, diagnostic: DescriptorDiagnostic) -> None:
        if len(self.diagnostics) >= _MAX_DIAGNOSTICS_PER_ENTRY:
            self.diagnostics.pop(0)
        self.diagnostics.append(diagnostic)

    def set_legacy_args(self, reading: Reading) -> None:
        new_args = (reading.instrument_id, reading.channel, reading.unit)
        if self._legacy_args != new_args:
            self._legacy_args = new_args
            self._legacy_cache = None


class DescriptorStore:
    """Single GUI-thread-owned bounded descriptor identity authority.

    The store is created empty and lives for one GUI session.  It ingests
    :class:`DescriptorQualifiedReading` items and resolves each channel's
    identity to authoritative, legacy_absent, or refused.  It never exposes
    or sets control authority.
    """

    __hash__ = None

    def __init__(self, *, max_entries: int = MAX_CATALOG_DESCRIPTORS) -> None:
        if type(max_entries) is not int or not 1 <= max_entries <= MAX_CATALOG_DESCRIPTORS:
            raise ValueError(f"max_entries must be an integer in 1..{MAX_CATALOG_DESCRIPTORS}")
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._owner_thread = threading.current_thread()

    def __copy__(self) -> DescriptorStore:
        raise TypeError("DescriptorStore is a single-owner GUI-session object")

    def __deepcopy__(self, memo: dict[int, object]) -> DescriptorStore:
        del memo
        raise TypeError("DescriptorStore is a single-owner GUI-session object")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("DescriptorStore is an in-process GUI-session owner")

    @property
    def max_entries(self) -> int:
        self._check_owner_thread()
        return self._max_entries

    def _check_owner_thread(self) -> None:
        """Reject mutation from a thread other than the owning GUI thread.

        The store documents single-GUI-thread ownership of the mutable
        ``_entries`` but does not lock it.  This cheap guard turns concurrent
        misuse into a clear error instead of a silent race.
        """
        if threading.current_thread() is not self._owner_thread:
            raise RuntimeError("DescriptorStore may be accessed only from the owning GUI thread")

    def __len__(self) -> int:
        self._check_owner_thread()
        return len(self._entries)

    def __contains__(self, channel_id: object) -> bool:
        self._check_owner_thread()
        return isinstance(channel_id, str) and channel_id in self._entries

    def ingest(self, qualified: DescriptorQualifiedReading) -> IngestResult:
        """Ingest one qualified reading and return its bounded disposition."""
        self._check_owner_thread()
        if type(qualified) is not DescriptorQualifiedReading:
            raise TypeError("qualified must be a DescriptorQualifiedReading")
        reading = qualified.reading
        if type(reading) is not Reading:
            raise TypeError("qualified.reading must be a Reading")
        descriptor = qualified.descriptor
        if descriptor is not None and type(descriptor) is not ChannelDescriptorV1:
            raise TypeError("qualified.descriptor must be ChannelDescriptorV1 or None")
        issue = qualified.descriptor_issue
        if issue is not None and type(issue) is not DescriptorEnvelopeIssue:
            raise TypeError("qualified.descriptor_issue must be DescriptorEnvelopeIssue or None")

        channel_id = reading.channel

        entry = self._entries.get(channel_id)
        if entry is None:
            if len(self._entries) >= self._max_entries:
                return IngestResult.CAPACITY_EXHAUSTED
            entry = _Entry()
            self._entries[channel_id] = entry

        entry.transport_state = TransportState.CONNECTED

        # Refusal precedence: a present descriptor_issue is authoritative for
        # refusal regardless of whether a (possibly forged) descriptor is also
        # present.  DescriptorQualifiedReading does not enforce mutual exclusion
        # between ``descriptor`` and ``descriptor_issue``, so a carrier carrying
        # both must fail closed to refused, never to authoritative/green.  Only
        # ``descriptor is not None AND descriptor_issue is None`` may become
        # authoritative.
        if issue is not None:
            return self._process_refused(
                entry,
                issue,
                reading,
                incoming_revision=descriptor.descriptor_revision if descriptor is not None else None,
            )
        if descriptor is not None and (
            descriptor.channel_id != reading.channel
            or descriptor.instrument_id != reading.instrument_id
            or descriptor.unit != reading.unit
        ):
            return self._process_refused(
                entry,
                DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
                reading,
                incoming_revision=descriptor.descriptor_revision,
            )
        if descriptor is not None:
            return self._process_authoritative(entry, descriptor)
        return self._process_legacy_absent(entry, reading)

    def _process_authoritative(self, entry: _Entry, descriptor: ChannelDescriptorV1) -> IngestResult:
        stored = entry.descriptor
        if stored is not None:
            if (
                descriptor.anchor != stored.anchor
                or descriptor.quantity != stored.quantity
                or descriptor.unit != stored.unit
            ):
                entry.add_diagnostic(
                    DescriptorDiagnostic(
                        reason="equivocation",
                        incoming_revision=descriptor.descriptor_revision,
                        descriptor_issue=None,
                    )
                )
                entry.identity_status = IdentityStatus.REFUSED
                return IngestResult.REFUSED
            if descriptor.descriptor_revision < stored.descriptor_revision:
                entry.add_diagnostic(
                    DescriptorDiagnostic(
                        reason="regression",
                        incoming_revision=descriptor.descriptor_revision,
                        descriptor_issue=None,
                    )
                )
                entry.identity_status = IdentityStatus.REFUSED
                return IngestResult.REFUSED
            if descriptor.descriptor_revision == stored.descriptor_revision:
                if descriptor.canonical_json != stored.canonical_json:
                    entry.add_diagnostic(
                        DescriptorDiagnostic(
                            reason="same_revision_conflict",
                            incoming_revision=descriptor.descriptor_revision,
                            descriptor_issue=None,
                        )
                    )
                    entry.identity_status = IdentityStatus.REFUSED
                    return IngestResult.REFUSED
                entry.identity_status = IdentityStatus.AUTHORITATIVE
                return IngestResult.ACCEPTED
            entry.descriptor = descriptor
        else:
            entry.descriptor = descriptor
            entry._legacy_args = None
            entry._legacy_cache = None
        entry.identity_status = IdentityStatus.AUTHORITATIVE
        return IngestResult.ACCEPTED

    def _process_refused(
        self,
        entry: _Entry,
        issue: DescriptorEnvelopeIssue,
        reading: Reading,
        *,
        incoming_revision: int | None = None,
    ) -> IngestResult:
        entry.add_diagnostic(
            DescriptorDiagnostic(
                reason="refused",
                incoming_revision=incoming_revision,
                descriptor_issue=issue,
            )
        )
        entry.identity_status = IdentityStatus.REFUSED
        if entry.descriptor is None:
            entry.set_legacy_args(reading)
        return IngestResult.REFUSED

    def _process_legacy_absent(self, entry: _Entry, reading: Reading) -> IngestResult:
        if entry.descriptor is not None or entry.identity_status is IdentityStatus.REFUSED:
            return IngestResult.LEGACY_ABSENT
        entry.identity_status = IdentityStatus.LEGACY_ABSENT
        entry.set_legacy_args(reading)
        return IngestResult.LEGACY_ABSENT

    def view(self, channel_id: str) -> DescriptorView | None:
        """Return a frozen presentation snapshot, or ``None`` if unknown."""
        self._check_owner_thread()
        entry = self._entries.get(channel_id)
        if entry is None:
            return None
        assert entry.identity_status is not None
        return DescriptorView(
            channel_id=channel_id,
            descriptor=entry.presentation_descriptor(),
            identity_status=entry.identity_status,
            transport_state=entry.transport_state,
            diagnostics=tuple(entry.diagnostics),
        )

    def identity_status(self, channel_id: str) -> IdentityStatus | None:
        """Return the identity status for a channel, or ``None`` if unknown."""
        self._check_owner_thread()
        entry = self._entries.get(channel_id)
        if entry is None:
            return None
        return entry.identity_status

    def presentation_descriptor(self, channel_id: str) -> ChannelDescriptorV1 | None:
        """Return the presentation descriptor for a channel, or ``None``."""
        self._check_owner_thread()
        entry = self._entries.get(channel_id)
        if entry is None:
            return None
        return entry.presentation_descriptor()

    def invalidate_transport(self) -> None:
        """Mark all entries disconnected after a bridge death/restart.

        Last-known descriptors remain available for explicitly non-authoritative
        presentation.  A matching qualified descriptor must arrive before an
        entry can become authoritative again; descriptor-less legacy traffic
        cannot requalify identity after a restart.
        """
        self._check_owner_thread()
        for entry in self._entries.values():
            entry.transport_state = TransportState.DISCONNECTED
            entry.identity_status = IdentityStatus.REFUSED


__all__ = [
    "DescriptorDiagnostic",
    "DescriptorStore",
    "DescriptorView",
    "IdentityStatus",
    "IngestResult",
    "TransportState",
]
