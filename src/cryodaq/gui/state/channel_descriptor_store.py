"""GUI-thread owner for verified live channel-descriptor revisions.

The store is observational.  It owns no lookup, transport, persistence,
publication, safety, or control capability and emits only when presentation
authority changes, never for every Reading.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from PySide6.QtCore import QObject, QThread, Signal

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    validate_catalog_update,
)
from cryodaq.channels.live_display import LiveChannelPresentation, live_channel_presentation
from cryodaq.core.descriptor_transport import (
    DescriptorEnvelopeIssue,
    DescriptorQualifiedReading,
)

_MAX_COUNTER: Final = (1 << 64) - 1


class DescriptorStoreDecision(StrEnum):
    """Bounded outcome of one qualified-reading observation."""

    ABSENT = "absent"
    ADDED = "added"
    ADVANCED = "advanced"
    IDEMPOTENT = "idempotent"
    REFUSED = "refused"


class DescriptorStoreIssue(StrEnum):
    """Bounded diagnostics; deliberately no unbounded per-channel issue log."""

    UPSTREAM_MALFORMED = "upstream_malformed"
    UPSTREAM_IDENTITY_MISMATCH = "upstream_identity_mismatch"
    INVALID_CARRIER = "invalid_carrier"
    INVALID_DESCRIPTOR = "invalid_descriptor"
    UNQUALIFIED_IDENTITY = "unqualified_identity"
    REVISION_REGRESSION = "revision_regression"
    REVISION_EQUIVOCATION = "revision_equivocation"
    REVISION_INCOMPATIBLE = "revision_incompatible"
    CAPACITY_EXCEEDED = "capacity_exceeded"


class ChannelDescriptorStore(QObject):
    """One GUI-root-owned, GUI-thread-affine descriptor revision store."""

    descriptor_changed = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._descriptors: dict[str, ChannelDescriptorV1] = {}
        self._issue_count = 0
        self._absence_count = 0
        self._change_count = 0
        self._last_issue: DescriptorStoreIssue | None = None
        self._last_decision: DescriptorStoreDecision | None = None

    @property
    def descriptors(self) -> Mapping[str, ChannelDescriptorV1]:
        return MappingProxyType(dict(self._descriptors))

    @property
    def issue_count(self) -> int:
        return self._issue_count

    @property
    def absence_count(self) -> int:
        """Benign descriptor-absent observations, separate from issues."""

        return self._absence_count

    @property
    def change_count(self) -> int:
        return self._change_count

    @property
    def last_issue(self) -> DescriptorStoreIssue | None:
        return self._last_issue

    @property
    def last_decision(self) -> DescriptorStoreDecision | None:
        return self._last_decision

    @property
    def grants_control_authority(self) -> bool:
        return False

    def descriptor_for(self, channel_id: str) -> ChannelDescriptorV1 | None:
        return self._descriptors.get(channel_id)

    def presentation_for(self, channel_id: str) -> LiveChannelPresentation:
        return live_channel_presentation(channel_id, self.descriptor_for(channel_id))

    def accept(self, candidate: object) -> DescriptorStoreDecision:
        """Observe one carrier; mutate only for a verified forward revision."""

        self._require_owner_thread()
        if type(candidate) is not DescriptorQualifiedReading:
            return self._refuse(DescriptorStoreIssue.INVALID_CARRIER)

        descriptor = candidate.descriptor
        upstream_issue = candidate.descriptor_issue
        if descriptor is None:
            if upstream_issue is None:
                self._absence_count = _increment(self._absence_count)
                return self._decide(DescriptorStoreDecision.ABSENT)
            if upstream_issue is DescriptorEnvelopeIssue.MALFORMED:
                return self._refuse(DescriptorStoreIssue.UPSTREAM_MALFORMED)
            if upstream_issue is DescriptorEnvelopeIssue.IDENTITY_MISMATCH:
                return self._refuse(DescriptorStoreIssue.UPSTREAM_IDENTITY_MISMATCH)
            return self._refuse(DescriptorStoreIssue.INVALID_CARRIER)
        if upstream_issue is not None or type(descriptor) is not ChannelDescriptorV1:
            return self._refuse(DescriptorStoreIssue.INVALID_CARRIER)

        try:
            verified = ChannelCatalog([descriptor]).by_channel_id[descriptor.channel_id]
        except (TypeError, ChannelDescriptorError):
            return self._refuse(DescriptorStoreIssue.INVALID_DESCRIPTOR)
        reading = candidate.reading
        if (
            verified.channel_id != reading.channel
            or verified.instrument_id != reading.instrument_id
            or verified.unit != reading.unit
        ):
            return self._refuse(DescriptorStoreIssue.UNQUALIFIED_IDENTITY)

        current = self._descriptors.get(verified.channel_id)
        if current is None:
            if len(self._descriptors) >= MAX_CATALOG_DESCRIPTORS:
                return self._refuse(DescriptorStoreIssue.CAPACITY_EXCEEDED)
            return self._store(verified, DescriptorStoreDecision.ADDED)
        if verified.descriptor_revision < current.descriptor_revision:
            return self._refuse(DescriptorStoreIssue.REVISION_REGRESSION)
        if verified.descriptor_revision == current.descriptor_revision:
            if (
                verified.descriptor_hash == current.descriptor_hash
                and verified.canonical_json == current.canonical_json
            ):
                return self._decide(DescriptorStoreDecision.IDEMPOTENT)
            return self._refuse(DescriptorStoreIssue.REVISION_EQUIVOCATION)
        try:
            validate_catalog_update([current], [verified])
        except (TypeError, ChannelDescriptorError):
            return self._refuse(DescriptorStoreIssue.REVISION_INCOMPATIBLE)
        return self._store(verified, DescriptorStoreDecision.ADVANCED)

    def _store(
        self,
        descriptor: ChannelDescriptorV1,
        decision: DescriptorStoreDecision,
    ) -> DescriptorStoreDecision:
        self._descriptors[descriptor.channel_id] = descriptor
        self._change_count = _increment(self._change_count)
        self._last_issue = None
        self._last_decision = decision
        self.descriptor_changed.emit(descriptor.channel_id, descriptor)
        return decision

    def _decide(self, decision: DescriptorStoreDecision) -> DescriptorStoreDecision:
        self._last_decision = decision
        return decision

    def _refuse(self, issue: DescriptorStoreIssue) -> DescriptorStoreDecision:
        self._issue_count = _increment(self._issue_count)
        self._last_issue = issue
        return self._decide(DescriptorStoreDecision.REFUSED)

    def _require_owner_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("channel descriptor store mutation requires its GUI thread")


def _increment(value: int) -> int:
    return min(_MAX_COUNTER, value + 1)


__all__ = [
    "ChannelDescriptorStore",
    "DescriptorStoreDecision",
    "DescriptorStoreIssue",
]
