"""Pure same-cut composition for backend-owned operator snapshots.

This module samples seven narrow observational authorities synchronously and
maps them to the eight neutral operator summaries.  It owns no task, transport,
GUI object, command path, or actuator capability.  A complete provisional
snapshot is validated before the durable revision allocator is touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AlarmAttentionAuthority,
    AlarmAttentionReceipt,
    AuthorityAvailability,
    CommonCut,
    CooldownAuthority,
    CooldownReceipt,
    ExperimentAuthority,
    ExperimentReceipt,
    InfrastructureAuthority,
    InfrastructureReceipt,
    IntegrityPersistenceAuthority,
    IntegrityPersistenceReceipt,
    SafetyReadinessAuthority,
    SafetyReadinessReceipt,
    SupportAuthority,
    SupportReceipt,
    require_common_cut,
)
from cryodaq.operator_snapshot import (
    STATE_PRECEDENCE,
    AttentionItem,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessBlocker,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
)
from cryodaq.storage.operator_snapshot_revision import SnapshotRevision

_LEADERSHIP_RE = re.compile(r"[0-9a-f]{32}")
_ALARM_STATE = {
    "INFO": OperatorPresentationState.CAUTION,
    "WARNING": OperatorPresentationState.WARNING,
    "CRITICAL": OperatorPresentationState.FAULT,
}
_OPTIONAL_UNAVAILABLE_REASONS = {
    AlarmAttentionReceipt: "attention_authority_unavailable",
    CooldownReceipt: "cooldown_authority_unavailable",
    InfrastructureReceipt: "infrastructure_authority_unavailable",
    SupportReceipt: "support_authority_unavailable",
}


class SnapshotRevisionAllocator(Protocol):
    """The only persistence capability visible to the composer."""

    async def allocate_async(self, *, not_before: datetime | None = None) -> SnapshotRevision: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _exact_utc(value: object, *, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{field} must be an exact timezone-aware datetime")
    normalized = value.astimezone(UTC)
    return datetime(
        normalized.year,
        normalized.month,
        normalized.day,
        normalized.hour,
        normalized.minute,
        normalized.second,
        normalized.microsecond,
        tzinfo=UTC,
        fold=normalized.fold,
    )


def _max_state(
    states: tuple[OperatorPresentationState, ...], *, empty: OperatorPresentationState
) -> OperatorPresentationState:
    return max(states, key=STATE_PRECEDENCE.__getitem__, default=empty)


def _status(
    state: OperatorPresentationState,
    source_age_s: float,
    reason_codes: tuple[str, ...],
    operator_text: str,
) -> SummaryStatus:
    return SummaryStatus(state, source_age_s, 0.0, reason_codes, operator_text)


@dataclass(frozen=True, slots=True)
class _Receipts:
    safety: SafetyReadinessReceipt
    attention: AlarmAttentionReceipt
    experiment: ExperimentReceipt
    integrity: IntegrityPersistenceReceipt
    cooldown: CooldownReceipt
    infrastructure: InfrastructureReceipt
    support: SupportReceipt


@dataclass(frozen=True, slots=True)
class _PreparedCut:
    """Completely validated detached evidence awaiting durable commit."""

    owner: object
    receipts: _Receipts


class OperatorSnapshotComposer:
    """Fail-closed LIVE snapshot preparation and commit service.

    One instance represents one engine leadership lifetime.  Its source and
    mode cannot change, and every composition attempt consumes a common-cut
    generation even when a provider or allocation fails.  Durable revisions
    are owned by the injected allocator and are never cached or reused here.
    """

    def __init__(
        self,
        *,
        safety: SafetyReadinessAuthority,
        attention: AlarmAttentionAuthority,
        experiment: ExperimentAuthority,
        integrity: IntegrityPersistenceAuthority,
        cooldown: CooldownAuthority,
        infrastructure: InfrastructureAuthority,
        support: SupportAuthority,
        revision_allocator: SnapshotRevisionAllocator,
        leadership_id: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        leadership_id = secrets.token_hex(16) if leadership_id is None else leadership_id
        if type(leadership_id) is not str or _LEADERSHIP_RE.fullmatch(leadership_id) is None:
            raise ValueError("leadership_id must be exactly 128 bits of lowercase hexadecimal")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(getattr(revision_allocator, "allocate_async", None)):
            raise TypeError("revision_allocator must expose callable allocate_async")
        self._safety = safety
        self._attention = attention
        self._experiment = experiment
        self._integrity = integrity
        self._cooldown = cooldown
        self._infrastructure = infrastructure
        self._support = support
        self._revision_allocator = revision_allocator
        self._clock = clock
        self._source = f"engine/operator-snapshot-v1/{leadership_id}"
        self._generation = 0
        self._owner = object()
        self._compose_lock = asyncio.Lock()

    @property
    def source(self) -> str:
        return self._source

    @property
    def mode(self) -> SnapshotMode:
        return SnapshotMode.LIVE

    def prepare(self, observed_at: datetime) -> _PreparedCut:
        """Synchronously sample and completely validate one same-loop cut."""
        observed = _exact_utc(observed_at, field="observed_at")
        sampled_at = _exact_utc(self._clock(), field="clock result")
        if observed > sampled_at:
            raise ValueError("observed_at must not be in the future")

        self._generation += 1
        generation = self._generation
        digest = hashlib.sha256(f"{self._source}:{generation}:{observed.isoformat()}".encode()).hexdigest()
        common_cut = CommonCut(generation, f"cut-v1:{generation}:{digest}", observed)

        # No await or callback is permitted between these same-loop samples.
        receipts = _Receipts(
            safety=self._safety.snapshot_for_cut(common_cut),
            attention=self._attention.snapshot_for_cut(common_cut),
            experiment=self._experiment.snapshot_for_cut(common_cut),
            integrity=self._integrity.snapshot_for_cut(common_cut),
            cooldown=self._cooldown.snapshot_for_cut(common_cut),
            infrastructure=self._infrastructure.snapshot_for_cut(common_cut),
            support=self._support.snapshot_for_cut(common_cut),
        )
        self._validate_receipts(common_cut, receipts)

        # Build the full object graph before allocation.  This proves that all
        # provider data and mappings satisfy the public protocol without
        # consuming a durable revision on validation failure.
        provisional = SnapshotRevision(1, observed)
        self._build_snapshot(receipts, provisional)
        return _PreparedCut(self._owner, receipts)

    def finalize(self, prepared: _PreparedCut, allocation: SnapshotRevision) -> OperatorSnapshot:
        """Purely detach one committed allocation onto a validated cut."""
        if type(prepared) is not _PreparedCut or prepared.owner is not self._owner:
            raise TypeError("prepared cut must belong to this composer")
        if type(allocation) is not SnapshotRevision:
            raise TypeError("revision allocator must return an exact SnapshotRevision")
        observed = prepared.receipts.safety.cut.observed_at
        if allocation.received_at < observed:
            raise ValueError("allocated received_at predates the common cut")
        detached = SnapshotRevision(allocation.revision, allocation.received_at)
        return self._build_snapshot(prepared.receipts, detached)

    async def compose(self, observed_at: datetime) -> OperatorSnapshot:
        """Prepare without interleaving, allocate off-loop, then finalize."""
        async with self._compose_lock:
            prepared = self.prepare(observed_at)
            observed = prepared.receipts.safety.cut.observed_at
            allocation = await self._revision_allocator.allocate_async(not_before=observed)
            return self.finalize(prepared, allocation)

    @staticmethod
    def _validate_receipts(cut: CommonCut, receipts: _Receipts) -> None:
        exact = (
            (receipts.safety, SafetyReadinessReceipt),
            (receipts.attention, AlarmAttentionReceipt),
            (receipts.experiment, ExperimentReceipt),
            (receipts.integrity, IntegrityPersistenceReceipt),
            (receipts.cooldown, CooldownReceipt),
            (receipts.infrastructure, InfrastructureReceipt),
            (receipts.support, SupportReceipt),
        )
        if any(type(receipt) is not expected for receipt, expected in exact):
            raise TypeError("each authority must return its exact detached receipt type")
        require_common_cut(cut, *(receipt for receipt, _expected in exact))

        for receipt in (receipts.safety, receipts.experiment, receipts.integrity):
            if receipt.availability is not AuthorityAvailability.AVAILABLE:
                raise ValueError("mandatory operator-snapshot authority is unavailable")
        for receipt in (receipts.attention, receipts.cooldown, receipts.infrastructure, receipts.support):
            if receipt.availability is AuthorityAvailability.UNAVAILABLE:
                expected_reason = _OPTIONAL_UNAVAILABLE_REASONS[type(receipt)]
                if receipt.unavailable_reason != expected_reason:
                    raise ValueError("unavailable optional authority has an unreviewed reason")

        if receipts.safety.readiness is ReadinessTruth.READY and receipts.safety.verified_off is not True:
            raise ValueError("READY requires verified-OFF authority")

    def _build_snapshot(self, receipts: _Receipts, allocation: SnapshotRevision) -> OperatorSnapshot:
        cut = SnapshotCut(
            allocation.revision,
            receipts.safety.cut.observed_at,
            allocation.received_at,
            self._source,
            SnapshotMode.LIVE,
            receipts.experiment.experiment_id or "no-active-experiment",
            self._source,
        )
        source_age = (cut.received_at - cut.observed_at).total_seconds()

        blockers = tuple(
            ReadinessBlocker(item.code, item.state, item.operator_text, item.required_evidence)
            for item in receipts.safety.blockers
        )
        readiness_state = {
            ReadinessTruth.READY: OperatorPresentationState.OK,
            ReadinessTruth.BLOCKED: _max_state(
                tuple(item.state for item in blockers), empty=OperatorPresentationState.FAULT
            ),
            ReadinessTruth.UNKNOWN: OperatorPresentationState.CAUTION,
        }[receipts.safety.readiness]
        readiness_reasons = () if receipts.safety.readiness is ReadinessTruth.READY else ("readiness_not_ready",)
        readiness = ReadinessSummary(
            cut,
            _status(readiness_state, source_age, readiness_reasons, "Backend readiness authority"),
            receipts.safety.readiness,
            blockers,
            receipts.safety.lifecycle,
        )

        plant_items = tuple(
            PlantHealthItem(item.subsystem_id, item.display_name, item.state, (item.reason_code,))
            for item in receipts.safety.plant_health
        )
        plant_state = _max_state(tuple(item.state for item in plant_items), empty=OperatorPresentationState.CAUTION)
        plant_reasons = (
            () if plant_items and plant_state is OperatorPresentationState.OK else ("plant_health_attention",)
        )
        plant_health = PlantHealthSummary(
            cut,
            _status(plant_state, source_age, plant_reasons, "Backend plant-health authority"),
            plant_items,
        )

        attention_items: list[AttentionItem] = []
        if receipts.attention.availability is AuthorityAvailability.AVAILABLE:
            for alarm in receipts.attention.alarms:
                alarm_key = hashlib.sha256(alarm.alarm_id.encode()).hexdigest()[:32]
                attention_items.append(
                    AttentionItem(
                        f"alarm:{alarm_key}",
                        _ALARM_STATE[alarm.level],
                        f"Active {alarm.level} alarm",
                        alarm.alarm_id,
                        alarm.triggered_at,
                    )
                )
            attention_items.extend(
                AttentionItem(item.attention_id, item.state, item.title, item.detail, item.observed_at)
                for item in receipts.attention.attention
            )
            attention_state = _max_state(
                tuple(item.state for item in attention_items), empty=OperatorPresentationState.OK
            )
            attention_reasons = () if not attention_items else ("operator_attention_required",)
        else:
            attention_state = OperatorPresentationState.CAUTION
            attention_reasons = (receipts.attention.unavailable_reason,)  # type: ignore[arg-type]
        attention = AttentionQueue(
            cut,
            _status(attention_state, source_age, attention_reasons, "Backend attention authority"),
            tuple(attention_items),
        )

        experiment_state = (
            OperatorPresentationState.CAUTION
            if receipts.experiment.recording is RecordingTruth.UNKNOWN
            else OperatorPresentationState.OK
        )
        experiment_reasons = () if experiment_state is OperatorPresentationState.OK else ("recording_unknown",)
        experiment = ExperimentOperatingState(
            cut,
            _status(experiment_state, source_age, experiment_reasons, "Backend experiment authority"),
            receipts.experiment.experiment_id,
            receipts.experiment.experiment_name,
            receipts.experiment.phase,
            receipts.experiment.recording,
            receipts.experiment.recording_session_id,
        )

        assert receipts.integrity.persisted_revision is not None
        assert receipts.integrity.pending_records is not None
        assert receipts.integrity.dropped_records is not None
        if receipts.integrity.storage is not AvailabilityTruth.AVAILABLE:
            integrity_state = OperatorPresentationState.WARNING
            integrity_reasons = ("storage_unavailable",)
        elif receipts.integrity.dropped_records:
            integrity_state = OperatorPresentationState.WARNING
            integrity_reasons = ("records_dropped",)
        elif receipts.integrity.pending_records:
            integrity_state = OperatorPresentationState.CAUTION
            integrity_reasons = ("records_pending",)
        else:
            integrity_state = OperatorPresentationState.OK
            integrity_reasons = ()
        data_integrity = DataIntegritySummary(
            cut,
            _status(integrity_state, source_age, integrity_reasons, "Backend persistence authority"),
            receipts.integrity.persisted_revision,
            receipts.integrity.archive_revision,
            receipts.integrity.pending_records,
            receipts.integrity.dropped_records,
            receipts.integrity.storage,
        )

        cooldown_samples: tuple[CooldownSample, ...] = ()
        reference_samples: tuple[CooldownSample, ...] = ()
        reference_id = None
        if receipts.cooldown.availability is AuthorityAvailability.AVAILABLE:
            cooldown_samples = tuple(
                CooldownSample(item.elapsed_s, item.temperature_k) for item in receipts.cooldown.samples
            )
            reference_samples = tuple(
                CooldownSample(item.elapsed_s, item.temperature_k) for item in receipts.cooldown.reference_samples
            )
            reference_id = receipts.cooldown.reference_id
            cooldown_state = OperatorPresentationState.OK if cooldown_samples else OperatorPresentationState.CAUTION
            cooldown_reasons = () if cooldown_samples else ("cooldown_history_empty",)
        else:
            cooldown_state = OperatorPresentationState.CAUTION
            cooldown_reasons = (receipts.cooldown.unavailable_reason,)  # type: ignore[arg-type]
        cooldown = CooldownHistorySummary(
            cut,
            _status(cooldown_state, source_age, cooldown_reasons, "Backend cooldown-history authority"),
            cooldown_samples,
            reference_id,
            reference_samples,
        )

        infrastructure_nodes: tuple[InfrastructureNode, ...] = ()
        if receipts.infrastructure.availability is AuthorityAvailability.AVAILABLE:
            infrastructure_nodes = tuple(
                InfrastructureNode(item.node_id, item.display_name, item.state, (item.reason_code,))
                for item in receipts.infrastructure.nodes
            )
            infrastructure_state = _max_state(
                tuple(item.state for item in infrastructure_nodes), empty=OperatorPresentationState.CAUTION
            )
            infrastructure_reasons = (
                ()
                if infrastructure_nodes and infrastructure_state is OperatorPresentationState.OK
                else ("infrastructure_attention",)
            )
        else:
            infrastructure_state = OperatorPresentationState.CAUTION
            infrastructure_reasons = (receipts.infrastructure.unavailable_reason,)  # type: ignore[arg-type]
        infrastructure = InfrastructureNodeHealth(
            cut,
            _status(infrastructure_state, source_age, infrastructure_reasons, "Backend infrastructure authority"),
            infrastructure_nodes,
        )

        manifest = None
        if receipts.support.manifest is not None:
            manifest = SupportBundleManifest(
                receipts.support.manifest.bundle_id,
                receipts.support.manifest.created_at,
                tuple(
                    SupportBundleEntry(item.logical_path, item.size_bytes, item.sha256)
                    for item in receipts.support.manifest.entries
                ),
            )
        if receipts.support.availability is AuthorityAvailability.UNAVAILABLE:
            support_availability = AvailabilityTruth.UNKNOWN
            support_state = OperatorPresentationState.CAUTION
            support_reasons = (receipts.support.unavailable_reason,)  # type: ignore[arg-type]
        elif manifest is not None:
            support_availability = AvailabilityTruth.AVAILABLE
            support_state = OperatorPresentationState.OK
            support_reasons = ()
        else:
            support_availability = AvailabilityTruth.UNAVAILABLE
            support_state = OperatorPresentationState.CAUTION
            support_reasons = ("support_bundle_not_captured",)
        support_bundle = SupportBundleSummary(
            cut,
            _status(support_state, source_age, support_reasons, "Backend support-bundle authority"),
            support_availability,
            manifest,
        )

        return OperatorSnapshot(
            cut,
            readiness,
            plant_health,
            infrastructure,
            attention,
            experiment,
            data_integrity,
            cooldown,
            support_bundle,
        )


__all__ = ["OperatorSnapshotComposer", "SnapshotRevisionAllocator"]
