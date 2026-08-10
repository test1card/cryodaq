"""GUI-only freshness overlay for the neutral operator snapshot protocol."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime

from cryodaq import operator_snapshot as _protocol
from cryodaq.channels.descriptors import ChannelDescriptorV1, ChannelQuantity
from cryodaq.core.operator_log import AttentionHistoryPage
from cryodaq.operator_snapshot import *  # noqa: F403
from cryodaq.operator_snapshot import (
    MAX_ID_UTF8_BYTES,
    MAX_LIVE_SOURCES_PER_SESSION,
    MAX_NONNEGATIVE_INT,
    STATE_PRECEDENCE,
    AttentionItem,
    AttentionQueue,
    AvailabilityTruth,
    CooldownChannelBinding,
    CooldownSample,
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
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
    _OperatorSummary,
)

__all__ = [
    *_protocol.__all__,
    "CooldownMission",
    "CooldownMissionGap",
    "CooldownMissionPoint",
    "OperatorSnapshotStore",
    "build_cooldown_mission",
    "dump_cooldown_mission",
]

_TRANSPORT_DISCONNECTED = "transport_disconnected"
_SNAPSHOT_STALE = "snapshot_stale"
_COOLDOWN_MISSION_SCHEMA = "cryodaq.cooldown-mission-evidence"
_COOLDOWN_MISSION_VERSION = 2


def _mission_number(
    value: object,
    *,
    field_name: str,
    non_negative: bool,
) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{field_name} must be finite")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(normalized) or (non_negative and normalized < 0):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _mission_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field_name} must be stable non-empty text")
    if len(value.encode("utf-8")) > MAX_ID_UTF8_BYTES:
        raise ValueError(f"{field_name} exceeds {MAX_ID_UTF8_BYTES} UTF-8 bytes")
    return value


def _attention_order_key(item: AttentionItem) -> tuple[int, float, str]:
    return (
        -STATE_PRECEDENCE[item.state],
        -item.observed_at.timestamp(),
        item.attention_id,
    )


@dataclass(frozen=True, slots=True)
class CooldownMissionPoint:
    """One observed sample with comparison truth from an exact reference time."""

    sample: CooldownSample
    reference_temperature_k: float | None
    deviation_k: float | None
    comparison_missing_reason: str | None

    def __post_init__(self) -> None:
        if type(self.sample) is not CooldownSample:
            raise TypeError("sample must be an exact CooldownSample")
        if self.reference_temperature_k is None:
            if self.deviation_k is not None or self.comparison_missing_reason not in {
                "no_reference",
                "no_exact_reference_sample",
            }:
                raise ValueError("missing comparison must carry one explicit reason")
            return
        reference = _mission_number(
            self.reference_temperature_k,
            field_name="reference_temperature_k",
            non_negative=True,
        )
        deviation = _mission_number(
            self.deviation_k,
            field_name="deviation_k",
            non_negative=False,
        )
        if self.comparison_missing_reason is not None or deviation != self.sample.temperature_k - reference:
            raise ValueError("available comparison must carry its exact deviation")
        object.__setattr__(self, "reference_temperature_k", reference)
        object.__setattr__(self, "deviation_k", deviation)


@dataclass(frozen=True, slots=True)
class CooldownMissionGap:
    """Explicit absence between two real samples; it never carries a value."""

    after_elapsed_s: float
    before_elapsed_s: float
    missing_reason: str = "cadence_gap"

    def __post_init__(self) -> None:
        after = _mission_number(
            self.after_elapsed_s,
            field_name="after_elapsed_s",
            non_negative=True,
        )
        before = _mission_number(
            self.before_elapsed_s,
            field_name="before_elapsed_s",
            non_negative=True,
        )
        if before <= after:
            raise ValueError("cooldown mission gap must span increasing elapsed time")
        if self.missing_reason != "cadence_gap":
            raise ValueError("cooldown mission gap reason must be cadence_gap")
        object.__setattr__(self, "after_elapsed_s", after)
        object.__setattr__(self, "before_elapsed_s", before)


@dataclass(frozen=True, slots=True)
class CooldownMission:
    """One immutable observational cooldown decision projection."""

    cut: SnapshotCut
    cooldown_status: SummaryStatus
    attention_status: SummaryStatus
    experiment_id: str
    trajectory_channel: CooldownChannelBinding | None
    trajectory_channel_descriptor: ChannelDescriptorV1 = field(compare=False, repr=False)
    trajectory_channel_missing_reason: str | None
    attention_history_revision: int
    phase: str | None
    phase_missing_reason: str | None
    expected_cadence_s: float
    trajectory: tuple[CooldownMissionPoint | CooldownMissionGap, ...]
    trajectory_missing_reason: str | None
    relevant_attention: tuple[AttentionItem, ...]
    recent_history: AttentionHistoryPage
    reference_id: str | None

    def __post_init__(self) -> None:
        if type(self.cut) is not SnapshotCut:
            raise TypeError("cut must be an exact SnapshotCut")
        if type(self.cooldown_status) is not SummaryStatus:
            raise TypeError("cooldown_status must be an exact SummaryStatus")
        if type(self.attention_status) is not SummaryStatus:
            raise TypeError("attention_status must be an exact SummaryStatus")
        _mission_id(self.experiment_id, field_name="experiment_id")
        if self.cut.experiment_id != self.experiment_id:
            raise ValueError("mission experiment_id must match its coherent cut")
        if type(self.trajectory_channel_descriptor) is not ChannelDescriptorV1:
            raise TypeError("trajectory_channel_descriptor must be an exact ChannelDescriptorV1")
        if (
            self.trajectory_channel_descriptor.quantity is not ChannelQuantity.TEMPERATURE
            or self.trajectory_channel_descriptor.unit != "K"
        ):
            raise ValueError("trajectory_channel_descriptor must describe temperature in K")
        if self.trajectory_channel is None:
            if self.trajectory_channel_missing_reason != "channel_identity_missing":
                raise ValueError("mission channel identity absence must be explicit")
        else:
            if type(self.trajectory_channel) is not CooldownChannelBinding:
                raise TypeError("trajectory_channel must be an exact CooldownChannelBinding or None")
            if self.trajectory_channel_descriptor.anchor != self.trajectory_channel.anchor:
                raise ValueError("trajectory channel identity does not match cooldown evidence")
            if self.trajectory_channel_missing_reason is not None:
                raise ValueError("mission channel identity absence must be explicit")
        if (
            type(self.attention_history_revision) is not int
            or not 0 <= self.attention_history_revision <= MAX_NONNEGATIVE_INT
        ):
            raise ValueError("attention_history_revision must be an exact bounded non-negative integer")
        if self.phase is None:
            if self.phase_missing_reason != "no_phase":
                raise ValueError("mission phase absence must be explicit")
        elif _mission_id(self.phase, field_name="phase") != self.phase or self.phase_missing_reason is not None:
            raise ValueError("mission phase absence must be explicit")
        cadence = _mission_number(
            self.expected_cadence_s,
            field_name="expected_cadence_s",
            non_negative=True,
        )
        if cadence == 0:
            raise ValueError("expected_cadence_s must be positive")
        object.__setattr__(self, "expected_cadence_s", cadence)
        if type(self.trajectory) is not tuple or any(
            type(item) not in {CooldownMissionPoint, CooldownMissionGap} for item in self.trajectory
        ):
            raise TypeError("trajectory must be a tuple of exact mission entries")
        if not self.trajectory:
            if self.trajectory_missing_reason != "no_samples":
                raise ValueError("trajectory absence must be explicit")
        elif self.trajectory_missing_reason is not None:
            raise ValueError("trajectory absence must be explicit")
        points = tuple(item for item in self.trajectory if type(item) is CooldownMissionPoint)
        if points and self.trajectory_channel is None:
            raise ValueError("mission trajectory evidence requires stable channel identity")
        if any(later.sample.elapsed_s <= earlier.sample.elapsed_s for earlier, later in zip(points, points[1:])):
            raise ValueError("mission samples must remain strictly ordered")
        expected_trajectory: list[CooldownMissionPoint | CooldownMissionGap] = []
        for point in points:
            if expected_trajectory:
                previous = expected_trajectory[-1]
                if type(previous) is CooldownMissionGap:
                    previous = expected_trajectory[-2]
                delta = point.sample.elapsed_s - previous.sample.elapsed_s
                if delta > cadence:
                    expected_trajectory.append(
                        CooldownMissionGap(
                            after_elapsed_s=previous.sample.elapsed_s,
                            before_elapsed_s=point.sample.elapsed_s,
                        )
                    )
            expected_trajectory.append(point)
        if self.trajectory != tuple(expected_trajectory):
            raise ValueError("mission gap must exist exactly when cadence evidence is missing")
        if self.reference_id is None:
            if any(point.comparison_missing_reason != "no_reference" for point in points):
                raise ValueError("mission reference identity must match comparison evidence")
        else:
            _mission_id(self.reference_id, field_name="reference_id")
            if any(point.comparison_missing_reason == "no_reference" for point in points):
                raise ValueError("mission reference identity must match comparison evidence")
        if type(self.relevant_attention) is not tuple or any(
            type(item) is not AttentionItem for item in self.relevant_attention
        ):
            raise TypeError("relevant_attention must contain exact AttentionItem values")
        if self.relevant_attention != tuple(sorted(self.relevant_attention, key=_attention_order_key)):
            raise ValueError("mission attention order is not deterministic")
        if len({item.attention_id for item in self.relevant_attention}) != len(self.relevant_attention):
            raise ValueError("mission attention ids must be unique")
        if any(item.observed_at > self.cut.observed_at for item in self.relevant_attention):
            raise ValueError("mission attention cut excludes future evidence")
        if any(
            item.transport_reason_codes != self.attention_status.transport_reason_codes
            for item in self.relevant_attention
        ):
            raise ValueError("mission attention transport evidence is inconsistent")
        required_attention_state = max(
            (STATE_PRECEDENCE[item.state] for item in self.relevant_attention),
            default=0,
        )
        if STATE_PRECEDENCE[self.attention_status.state] < required_attention_state:
            raise ValueError("mission attention state understates relevant evidence")
        if type(self.recent_history) is not AttentionHistoryPage:
            raise TypeError("recent_history must be an exact AttentionHistoryPage")
        if self.recent_history.experiment_id != self.experiment_id:
            raise ValueError("attention history experiment identity is inconsistent")
        if self.recent_history.through_revision != self.attention_history_revision:
            raise ValueError("attention history revision is not bound to the mission cut")
        if self.recent_history.as_of != self.cut.observed_at:
            raise ValueError("attention history is not bound to the mission cut")

    @property
    def trajectory_channel_id(self) -> str | None:
        return None if self.trajectory_channel is None else self.trajectory_channel.channel_id


def build_cooldown_mission(
    snapshot: OperatorSnapshot,
    attention_history: AttentionHistoryPage,
    *,
    trajectory_channel: ChannelDescriptorV1,
    expected_cadence_s: float,
) -> CooldownMission:
    """Project one coherent cut plus durable annotations without new authority."""

    if type(snapshot) is not OperatorSnapshot:
        raise TypeError("snapshot must be an exact OperatorSnapshot")
    if type(attention_history) is not AttentionHistoryPage:
        raise TypeError("attention_history must be an exact AttentionHistoryPage")
    if type(trajectory_channel) is not ChannelDescriptorV1:
        raise TypeError("trajectory_channel must be an exact ChannelDescriptorV1")
    if trajectory_channel.quantity is not ChannelQuantity.TEMPERATURE or trajectory_channel.unit != "K":
        raise ValueError("trajectory_channel must describe temperature in K")
    authoritative_channel = snapshot.cooldown_history.trajectory_channel
    if authoritative_channel is not None and trajectory_channel.anchor != authoritative_channel.anchor:
        raise ValueError("trajectory channel identity does not match cooldown evidence")
    experiment_id = snapshot.experiment.experiment_id
    if experiment_id is None or experiment_id != snapshot.cut.experiment_id:
        raise ValueError("cooldown mission requires one active stable experiment")
    if attention_history.experiment_id != experiment_id:
        raise ValueError("attention history belongs to a different experiment")
    attention_history_revision = snapshot.attention.history_revision
    if attention_history_revision is None:
        raise ValueError("durable attention history revision is unavailable at the mission cut")
    if attention_history.through_revision != attention_history_revision:
        raise ValueError("attention history revision is not bound to the mission cut")
    cadence = _mission_number(
        expected_cadence_s,
        field_name="expected_cadence_s",
        non_negative=True,
    )
    if cadence == 0:
        raise ValueError("expected_cadence_s must be positive")

    reference = {sample.elapsed_s: sample.temperature_k for sample in snapshot.cooldown_history.reference_samples}
    trajectory: list[CooldownMissionPoint | CooldownMissionGap] = []
    previous: CooldownSample | None = None
    for sample in snapshot.cooldown_history.samples:
        if previous is not None and sample.elapsed_s - previous.elapsed_s > cadence:
            trajectory.append(
                CooldownMissionGap(
                    after_elapsed_s=previous.elapsed_s,
                    before_elapsed_s=sample.elapsed_s,
                )
            )
        reference_temperature = reference.get(sample.elapsed_s)
        if reference_temperature is None:
            missing_reason = (
                "no_reference" if snapshot.cooldown_history.reference_id is None else "no_exact_reference_sample"
            )
            deviation = None
        else:
            missing_reason = None
            deviation = sample.temperature_k - reference_temperature
        trajectory.append(
            CooldownMissionPoint(
                sample=sample,
                reference_temperature_k=reference_temperature,
                deviation_k=deviation,
                comparison_missing_reason=missing_reason,
            )
        )
        previous = sample

    return CooldownMission(
        cut=snapshot.cut,
        cooldown_status=snapshot.cooldown_history.status,
        attention_status=snapshot.attention.status,
        experiment_id=experiment_id,
        trajectory_channel=authoritative_channel,
        trajectory_channel_descriptor=trajectory_channel,
        trajectory_channel_missing_reason=("channel_identity_missing" if authoritative_channel is None else None),
        attention_history_revision=attention_history_revision,
        phase=snapshot.experiment.phase,
        phase_missing_reason=("no_phase" if snapshot.experiment.phase is None else None),
        expected_cadence_s=cadence,
        trajectory=tuple(trajectory),
        trajectory_missing_reason=("no_samples" if not snapshot.cooldown_history.samples else None),
        relevant_attention=tuple(sorted(snapshot.attention.items, key=_attention_order_key)),
        recent_history=attention_history,
        reference_id=snapshot.cooldown_history.reference_id,
    )


def _mission_status_payload(status: SummaryStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "source_age_s": status.source_age_s,
        "transport_age_s": status.transport_age_s,
        "reason_codes": list(status.reason_codes),
        "operator_text": status.operator_text,
        "transport_reason_codes": list(status.transport_reason_codes),
    }


def dump_cooldown_mission(mission: CooldownMission) -> str:
    """Export deterministic observational evidence with stable identities."""

    if type(mission) is not CooldownMission:
        raise TypeError("mission must be an exact CooldownMission")
    trajectory: list[dict[str, object]] = []
    for entry in mission.trajectory:
        if type(entry) is CooldownMissionGap:
            trajectory.append(
                {
                    "kind": "missing",
                    "after_elapsed_s": entry.after_elapsed_s,
                    "before_elapsed_s": entry.before_elapsed_s,
                    "missing_reason": entry.missing_reason,
                }
            )
        else:
            trajectory.append(
                {
                    "kind": "sample",
                    "elapsed_s": entry.sample.elapsed_s,
                    "temperature_k": entry.sample.temperature_k,
                    "reference_temperature_k": entry.reference_temperature_k,
                    "deviation_k": entry.deviation_k,
                    "comparison_missing_reason": entry.comparison_missing_reason,
                }
            )
    payload = {
        "schema": _COOLDOWN_MISSION_SCHEMA,
        "version": _COOLDOWN_MISSION_VERSION,
        "cut": {
            "revision": mission.cut.revision,
            "observed_at": mission.cut.observed_at.isoformat(),
            "received_at": mission.cut.received_at.isoformat(),
            "source": mission.cut.source,
            "mode": mission.cut.mode.value,
            "experiment_id": mission.cut.experiment_id,
            "producer_id": mission.cut.producer_id,
        },
        "experiment_id": mission.experiment_id,
        "trajectory_channel_id": mission.trajectory_channel_id,
        "trajectory_channel": (
            None
            if mission.trajectory_channel is None
            else {
                "channel_id": mission.trajectory_channel.channel_id,
                "instrument_id": mission.trajectory_channel.instrument_id,
                "source_key": mission.trajectory_channel.source_key,
            }
        ),
        "trajectory_channel_missing_reason": mission.trajectory_channel_missing_reason,
        "attention_history_revision": mission.attention_history_revision,
        "phase": mission.phase,
        "phase_missing_reason": mission.phase_missing_reason,
        "expected_cadence_s": mission.expected_cadence_s,
        "cooldown_status": _mission_status_payload(mission.cooldown_status),
        "attention_status": _mission_status_payload(mission.attention_status),
        "reference_id": mission.reference_id,
        "trajectory": trajectory,
        "trajectory_missing_reason": mission.trajectory_missing_reason,
        "relevant_attention": [
            {
                "attention_id": item.attention_id,
                "state": item.state.value,
                "title": item.title,
                "detail": item.detail,
                "observed_at": item.observed_at.isoformat(),
                "transport_reason_codes": list(item.transport_reason_codes),
            }
            for item in mission.relevant_attention
        ],
        "recent_history": {
            "experiment_id": mission.recent_history.experiment_id,
            "item_revisions": list(mission.recent_history.item_revisions),
            "truncated_before": mission.recent_history.truncated_before,
            "through_revision": mission.recent_history.through_revision,
            "as_of": (None if mission.recent_history.as_of is None else mission.recent_history.as_of.isoformat()),
            "global_capacity_exhausted_at": (
                None
                if mission.recent_history.capacity_exhausted_at is None
                else mission.recent_history.capacity_exhausted_at.isoformat()
            ),
            "items": [item.to_payload() for item in mission.recent_history.items],
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
