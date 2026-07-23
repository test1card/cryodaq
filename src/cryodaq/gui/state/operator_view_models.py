"""GUI-only freshness overlay for the neutral operator snapshot protocol."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime

from cryodaq import operator_snapshot as _protocol
from cryodaq.operator_snapshot import *  # noqa: F403
from cryodaq.operator_snapshot import (
    MAX_LIVE_SOURCES_PER_SESSION,
    STATE_PRECEDENCE,
    AttentionQueue,
    AvailabilityTruth,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotMode,
    SupportBundleSummary,
    _OperatorSummary,
)

__all__ = [
    *_protocol.__all__,
    "OperatorSnapshotStore",
]

_TRANSPORT_DISCONNECTED = "transport_disconnected"
_SNAPSHOT_STALE = "snapshot_stale"


class OperatorSnapshotStore:
    """One GUI-session owner for raw cuts and conservative transport history.

    A store is created empty and lives for one GUI session. Creating another
    store deliberately starts another session; within one store no public API
    can reset same-cut invalidation. Presentation is always computed and is
    never accepted from callers.
    """

    __slots__ = (
        "_connected",
        "_invalidated",
        "_live_observed_high_water",
        "_live_producer_id",
        "_live_producer_replacement_pending",
        "_raw",
        "_retired_live_producer_ids",
        "_stale_after_s",
        "_transport_age_s",
    )
    __hash__ = None

    def __init__(self) -> None:
        self._raw: OperatorSnapshot | None = None
        self._connected: bool | None = None
        self._transport_age_s = 0.0
        self._stale_after_s: float | None = None
        self._invalidated = False
        self._live_observed_high_water: dict[str, datetime] = {}
        self._live_producer_id: str | None = None
        self._live_producer_replacement_pending = False
        self._retired_live_producer_ids: set[str] = set()

    def __copy__(self) -> OperatorSnapshotStore:
        raise TypeError("OperatorSnapshotStore is a single-owner GUI session")

    def __deepcopy__(self, memo: dict[int, object]) -> OperatorSnapshotStore:
        del memo
        raise TypeError("OperatorSnapshotStore is a single-owner GUI session")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("OperatorSnapshotStore is an in-process GUI-session owner")

    @property
    def snapshot(self) -> OperatorSnapshot | None:
        raw = self._raw
        if raw is None:
            return None
        if self._connected is None:
            return raw
        assert self._stale_after_s is not None
        if not self._connected or self._transport_age_s >= self._stale_after_s:
            return _degrade_snapshot(raw, connected=self._connected, age_s=self._transport_age_s)
        if self._invalidated:
            return _recover_snapshot(raw, self._transport_age_s)
        return _replace_transport_age(raw, self._transport_age_s)

    def _require_snapshot(self) -> OperatorSnapshot:
        snapshot = self.snapshot
        if snapshot is None:
            raise RuntimeError("operator snapshot store has no backend cut")
        return snapshot

    def accept_snapshot(self, snapshot: OperatorSnapshot) -> OperatorSnapshot:
        """Accept the first cut or a strictly newer backend-owned raw cut."""

        if not isinstance(snapshot, OperatorSnapshot):
            raise TypeError("snapshot must be an OperatorSnapshot")
        if any(summary.transport_reason_codes for summary in snapshot.summaries()):
            raise ValueError("transport-overlaid snapshot cannot be accepted as raw authority")
        replacement = snapshot.cut.mode is SnapshotMode.LIVE and self._live_producer_replacement_pending
        if replacement and snapshot.cut.producer_id in self._retired_live_producer_ids:
            raise ValueError("retired live producer cannot become the replacement generation")
        current = self._raw
        if current is not None and not replacement:
            if snapshot.cut == current.cut:
                if self._invalidated:
                    raise ValueError("same-cut raw snapshot cannot reset invalidated authority")
                if snapshot != current:
                    raise ValueError("same cut cannot carry different raw snapshot truth")
                return self._require_snapshot()
            if snapshot.cut.revision <= current.cut.revision:
                raise ValueError("backend snapshot revision must be strictly newer")
            if snapshot.cut.received_at < current.cut.received_at:
                raise ValueError("backend snapshot received_at cannot move backwards")
        if snapshot.cut.mode is SnapshotMode.LIVE:
            if replacement:
                self._live_producer_id = snapshot.cut.producer_id
                self._live_observed_high_water.clear()
                self._live_producer_replacement_pending = False
            elif self._live_producer_id is None:
                self._live_producer_id = snapshot.cut.producer_id
            elif snapshot.cut.producer_id != self._live_producer_id:
                raise ValueError("live snapshot producer incarnation changed without explicit replacement")
            previous_observed = self._live_observed_high_water.get(snapshot.cut.source)
            if previous_observed is None:
                if len(self._live_observed_high_water) >= MAX_LIVE_SOURCES_PER_SESSION:
                    raise ValueError("live source cardinality exceeds the reviewed session bound")
            elif snapshot.cut.observed_at < previous_observed:
                raise ValueError("live observed_at cannot move backwards for the same source")
        self._raw = snapshot
        if snapshot.cut.mode is SnapshotMode.LIVE:
            self._live_observed_high_water[snapshot.cut.source] = snapshot.cut.observed_at
        self._connected = None
        self._transport_age_s = max(summary.transport_age_s for summary in snapshot.summaries())
        self._stale_after_s = None
        self._invalidated = False
        return snapshot

    def begin_live_producer_replacement(self) -> None:
        """Authorize one new producer only after the current cut is disconnected."""

        current_producer = self._live_producer_id
        if self._raw is not None and self._raw.cut.mode is SnapshotMode.LIVE and self._connected is not False:
            raise RuntimeError("live producer replacement requires disconnected transport evidence")
        if current_producer is not None:
            if (
                current_producer not in self._retired_live_producer_ids
                and len(self._retired_live_producer_ids) >= MAX_LIVE_SOURCES_PER_SESSION
            ):
                raise RuntimeError("retired live producer bound is exhausted; start a new GUI session")
            self._retired_live_producer_ids.add(current_producer)
        self._live_producer_id = None
        self._live_observed_high_water.clear()
        self._live_producer_replacement_pending = True

    def observe_transport(
        self,
        *,
        connected: bool,
        transport_age_s: float,
        stale_after_s: float,
    ) -> OperatorSnapshot:
        """Apply one monotonic transport observation to the owned current cut."""

        if self._raw is None:
            raise RuntimeError("operator snapshot store has no backend cut")
        if not isinstance(connected, bool):
            raise TypeError("connected must be a boolean")
        age_s = _transport_number(transport_age_s, field_name="transport_age_s")
        threshold_s = _transport_number(stale_after_s, field_name="stale_after_s")
        if threshold_s == 0:
            raise ValueError("stale_after_s must be positive")
        if age_s < self._transport_age_s:
            raise ValueError("transport_age_s cannot decrease for the same snapshot cut")
        if not connected or age_s >= threshold_s:
            self._invalidated = True
        self._connected = connected
        self._transport_age_s = age_s
        self._stale_after_s = threshold_s
        return self._require_snapshot()

    @property
    def cut(self):
        return self._require_snapshot().cut

    @property
    def readiness(self):
        return self._require_snapshot().readiness

    @property
    def plant_health(self):
        return self._require_snapshot().plant_health

    @property
    def infrastructure(self):
        return self._require_snapshot().infrastructure

    @property
    def attention(self):
        return self._require_snapshot().attention

    @property
    def experiment(self):
        return self._require_snapshot().experiment

    @property
    def data_integrity(self):
        return self._require_snapshot().data_integrity

    @property
    def cooldown_history(self):
        return self._require_snapshot().cooldown_history

    @property
    def support_bundle(self):
        return self._require_snapshot().support_bundle

    def summaries(self) -> tuple[_OperatorSummary, ...]:
        return self._require_snapshot().summaries()


def _degrade_snapshot(
    raw: OperatorSnapshot,
    *,
    connected: bool,
    age_s: float,
) -> OperatorSnapshot:
    reason = _SNAPSHOT_STALE if connected else _TRANSPORT_DISCONNECTED

    def degrade(index: int, summary: _OperatorSummary) -> _OperatorSummary:
        old = summary.status
        transport_state = OperatorPresentationState.STALE if connected else OperatorPresentationState.DISCONNECTED
        backend_summary = raw.summaries()[index]
        state = _primary_state(backend_summary.state, transport_state)
        changes: dict[str, object] = {
            "status": replace(
                old,
                state=state,
                transport_age_s=age_s,
                transport_reason_codes=(reason,),
            )
        }
        if isinstance(summary, ReadinessSummary):
            changes["readiness"] = ReadinessTruth.UNKNOWN
            changes["lifecycle"] = SafetyLifecycle.UNKNOWN
            changes["blockers"] = tuple(
                replace(
                    item,
                    state=_degraded_nested_state(backend_item.state, connected=connected),
                    transport_reason_codes=(reason,),
                )
                for item, backend_item in zip(
                    summary.blockers,
                    raw.readiness.blockers,
                    strict=True,
                )
            )
        elif isinstance(summary, ExperimentOperatingState) and summary.mode is SnapshotMode.LIVE:
            changes["recording"] = RecordingTruth.UNKNOWN
            changes["recording_session_id"] = None
        elif isinstance(summary, DataIntegritySummary):
            changes["storage"] = AvailabilityTruth.UNKNOWN
        elif isinstance(summary, SupportBundleSummary):
            changes["availability"] = AvailabilityTruth.UNKNOWN
            changes["manifest"] = None
        elif isinstance(summary, PlantHealthSummary):
            changes["subsystems"] = tuple(
                replace(
                    item,
                    state=_degraded_nested_state(backend_item.state, connected=connected),
                    transport_reason_codes=(reason,),
                )
                for item, backend_item in zip(
                    summary.subsystems,
                    raw.plant_health.subsystems,
                    strict=True,
                )
            )
        elif isinstance(summary, InfrastructureNodeHealth):
            changes["nodes"] = tuple(
                replace(
                    item,
                    state=_degraded_nested_state(backend_item.state, connected=connected),
                    transport_reason_codes=(reason,),
                )
                for item, backend_item in zip(
                    summary.nodes,
                    raw.infrastructure.nodes,
                    strict=True,
                )
            )
        elif isinstance(summary, AttentionQueue):
            changes["items"] = tuple(
                replace(
                    item,
                    state=_degraded_nested_state(backend_item.state, connected=connected),
                    transport_reason_codes=(reason,),
                )
                for item, backend_item in zip(
                    summary.items,
                    raw.attention.items,
                    strict=True,
                )
            )
        return replace(summary, **changes)

    result = _replace_summaries(
        raw,
        tuple(degrade(index, summary) for index, summary in enumerate(raw.summaries())),
    )
    return result


def _transport_number(value: float, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite and non-negative")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field_name} must be finite and non-negative") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return normalized


def _degraded_nested_state(
    backend_state: OperatorPresentationState,
    *,
    connected: bool,
) -> OperatorPresentationState:
    transport_state = OperatorPresentationState.STALE if connected else OperatorPresentationState.DISCONNECTED
    return _primary_state(backend_state, transport_state)


def _primary_state(
    backend_state: OperatorPresentationState,
    transport_state: OperatorPresentationState,
) -> OperatorPresentationState:
    return max((backend_state, transport_state), key=STATE_PRECEDENCE.__getitem__)


def _recover_snapshot(raw: OperatorSnapshot, age_s: float) -> OperatorSnapshot:
    """Clear recovered transport cues without resurrecting invalidated authority.

    A same-cut recovery cannot reconstruct a removed recording session or
    support manifest. Backend urgent states and reason codes are retained;
    transport-generated stale/disconnected presentation becomes conservative
    stale until a newer authoritative cut arrives.
    """

    def recover(index: int, summary: _OperatorSummary) -> _OperatorSummary:
        raw_summary = raw.summaries()[index]
        changes: dict[str, object] = {
            "status": replace(
                summary.status,
                state=_primary_state(
                    raw_summary.state,
                    OperatorPresentationState.STALE,
                ),
                transport_age_s=age_s,
                transport_reason_codes=(),
            )
        }
        if isinstance(summary, ReadinessSummary):
            changes["readiness"] = ReadinessTruth.UNKNOWN
            changes["lifecycle"] = SafetyLifecycle.UNKNOWN
            changes["blockers"] = tuple(
                replace(
                    item,
                    state=_primary_state(backend_item.state, OperatorPresentationState.STALE),
                    transport_reason_codes=(),
                )
                for item, backend_item in zip(
                    raw.readiness.blockers,
                    raw.readiness.blockers,
                    strict=True,
                )
            )
        elif isinstance(summary, ExperimentOperatingState) and summary.mode is SnapshotMode.LIVE:
            changes["recording"] = RecordingTruth.UNKNOWN
            changes["recording_session_id"] = None
        elif isinstance(summary, DataIntegritySummary):
            changes["storage"] = AvailabilityTruth.UNKNOWN
        elif isinstance(summary, SupportBundleSummary):
            changes["availability"] = AvailabilityTruth.UNKNOWN
            changes["manifest"] = None
        elif isinstance(summary, PlantHealthSummary):
            changes["subsystems"] = tuple(
                replace(
                    item,
                    state=_primary_state(backend_item.state, OperatorPresentationState.STALE),
                    transport_reason_codes=(),
                )
                for item, backend_item in zip(
                    raw.plant_health.subsystems,
                    raw.plant_health.subsystems,
                    strict=True,
                )
            )
        elif isinstance(summary, InfrastructureNodeHealth):
            changes["nodes"] = tuple(
                replace(
                    item,
                    state=_primary_state(backend_item.state, OperatorPresentationState.STALE),
                    transport_reason_codes=(),
                )
                for item, backend_item in zip(
                    raw.infrastructure.nodes,
                    raw.infrastructure.nodes,
                    strict=True,
                )
            )
        elif isinstance(summary, AttentionQueue):
            changes["items"] = tuple(
                replace(
                    item,
                    state=_primary_state(backend_item.state, OperatorPresentationState.STALE),
                    transport_reason_codes=(),
                )
                for item, backend_item in zip(
                    raw.attention.items,
                    raw.attention.items,
                    strict=True,
                )
            )
        return replace(summary, **changes)

    return _replace_summaries(
        raw,
        tuple(recover(index, summary) for index, summary in enumerate(raw.summaries())),
    )


def _replace_transport_age(snapshot: OperatorSnapshot, age_s: float) -> OperatorSnapshot:
    return _replace_summaries(
        snapshot,
        tuple(
            replace(summary, status=replace(summary.status, transport_age_s=age_s)) for summary in snapshot.summaries()
        ),
    )


def _replace_summaries(snapshot: OperatorSnapshot, summaries: tuple[_OperatorSummary, ...]) -> OperatorSnapshot:
    return OperatorSnapshot(snapshot.cut, *summaries)
