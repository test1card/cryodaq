"""Cached, read-only fleet-health authority for operator snapshots.

Health producers are sampled explicitly outside the composer's no-await cut.
``snapshot_for_cut`` only projects the last validated immutable sample and can
never call a device, start work, or grant control authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
    InfrastructureEvidence,
    InfrastructureReceipt,
)
from cryodaq.health.contract import (
    HealthAlarmSeverity,
    HealthFreshness,
    HealthQuality,
    HealthTelemetryReader,
    HealthTelemetrySnapshot,
    _IssuedHealthTelemetryReader,  # noqa: PLC2701 - exact factory boundary
)
from cryodaq.health.simulator import DeterministicFleetHealthSimulator, FleetHealthFrame
from cryodaq.operator_snapshot import MAX_FLEET_DEVICES, STATE_PRECEDENCE, OperatorPresentationState

_UNAVAILABLE = "infrastructure_authority_unavailable"
_FRESHNESS_STATE = {
    HealthFreshness.FRESH: OperatorPresentationState.OK,
    HealthFreshness.STALE: OperatorPresentationState.STALE,
    HealthFreshness.DISCONNECTED: OperatorPresentationState.DISCONNECTED,
}
_FRESHNESS_REASON = {
    HealthFreshness.FRESH: "health_fresh",
    HealthFreshness.STALE: "health_stale",
    HealthFreshness.DISCONNECTED: "health_disconnected",
}
_ALARM_STATE = {
    HealthAlarmSeverity.CAUTION: OperatorPresentationState.CAUTION,
    HealthAlarmSeverity.WARNING: OperatorPresentationState.WARNING,
    HealthAlarmSeverity.FAULT: OperatorPresentationState.FAULT,
}
_METRIC_STATE = {
    HealthQuality.OK: OperatorPresentationState.OK,
    HealthQuality.DEGRADED: OperatorPresentationState.CAUTION,
    HealthQuality.FAULT: OperatorPresentationState.FAULT,
    HealthQuality.UNKNOWN: OperatorPresentationState.STALE,
}


def _freshness_at(snapshot: HealthTelemetrySnapshot, observed_time_s: float) -> HealthFreshness:
    age = observed_time_s - snapshot.heartbeat_time_s
    if age <= snapshot.descriptor.stale_after_s:
        return HealthFreshness.FRESH
    if age <= snapshot.descriptor.disconnected_after_s:
        return HealthFreshness.STALE
    return HealthFreshness.DISCONNECTED


def _state_reason(snapshot: HealthTelemetrySnapshot, observed_time_s: float) -> tuple[OperatorPresentationState, str]:
    freshness = _freshness_at(snapshot, observed_time_s)
    candidates = [(_FRESHNESS_STATE[freshness], _FRESHNESS_REASON[freshness])]
    candidates.extend(
        (_ALARM_STATE[alarm.severity], f"health_alarm_{alarm.severity.value}")
        for alarm in snapshot.alarms
        if alarm.active
    )
    candidates.extend(
        (_METRIC_STATE[metric.quality], f"health_metric_{metric.quality.value}")
        for metric in snapshot.metrics
        if metric.quality is not HealthQuality.OK
    )
    return max(candidates, key=lambda item: STATE_PRECEDENCE[item[0]])


def _evidence(snapshot: HealthTelemetrySnapshot, observed_time_s: float) -> InfrastructureEvidence:
    state, reason = _state_reason(snapshot, observed_time_s)
    return InfrastructureEvidence(
        snapshot.descriptor.device_id,
        snapshot.descriptor.device_id,
        state,
        reason,
    )


def _snapshot_payload(snapshot: HealthTelemetrySnapshot) -> list[object]:
    """Canonical source evidence used for replay/equivocation fencing."""

    return [
        snapshot.descriptor.device_id,
        snapshot.revision,
        snapshot.observed_time_s,
        snapshot.heartbeat_time_s,
        snapshot.mode,
        [
            [
                metric.descriptor.metric_id,
                metric.descriptor.kind.value,
                metric.value,
                metric.quality.value,
                metric.source_time_s,
            ]
            for metric in snapshot.metrics
        ],
        [
            [alarm.alarm_id, alarm.severity.value, alarm.active, alarm.message, alarm.source_time_s]
            for alarm in snapshot.alarms
        ],
    ]


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _CachedFrame:
    revision: int
    observed_time_s: float
    snapshots: tuple[HealthTelemetrySnapshot, ...]
    source_evidence: tuple[tuple[str, int, str], ...]


class _CachedHealthAuthority:
    __slots__ = ("_cached", "_last_sources", "_revision")

    grants_control_authority = False

    def __init__(self) -> None:
        self._cached: _CachedFrame | None = None
        self._last_sources: dict[str, tuple[int, str]] = {}
        self._revision = 0

    def _cache(self, snapshots: tuple[HealthTelemetrySnapshot, ...]) -> None:
        if len(snapshots) > MAX_FLEET_DEVICES or any(type(value) is not HealthTelemetrySnapshot for value in snapshots):
            self._cached = None
            return
        ids = tuple(value.descriptor.device_id for value in snapshots)
        if len(ids) != len(set(ids)):
            self._cached = None
            return
        source_evidence = tuple(
            (value.descriptor.device_id, value.revision, _digest(_snapshot_payload(value))) for value in snapshots
        )
        for source_id, revision, evidence_digest in source_evidence:
            previous = self._last_sources.get(source_id)
            if previous is not None and (
                revision < previous[0] or (revision == previous[0] and evidence_digest != previous[1])
            ):
                self._cached = None
                return
        self._revision += 1
        self._last_sources = {source_id: (revision, digest) for source_id, revision, digest in source_evidence}
        self._cached = _CachedFrame(
            self._revision,
            max((value.observed_time_s for value in snapshots), default=0.0),
            snapshots,
            source_evidence,
        )

    @staticmethod
    def _token(
        cut: CommonCut,
        cached: _CachedFrame | None,
        nodes: tuple[InfrastructureEvidence, ...] = (),
    ) -> str:
        payload: object = [
            cut.generation,
            cut.token,
            cut.observed_at.isoformat(),
            _UNAVAILABLE
            if cached is None
            else [
                cached.revision,
                cached.source_evidence,
                [[node.node_id, node.display_name, node.state.value, node.reason_code] for node in nodes],
            ],
        ]
        revision = 0 if cached is None else cached.revision
        return f"authority-v1:{revision}:{_digest(payload)}"

    def snapshot_for_cut(self, cut: CommonCut) -> InfrastructureReceipt:
        if type(cut) is not CommonCut:
            raise TypeError("cut must be an exact CommonCut")
        cached = self._cached
        if cached is None or cached.observed_time_s > cut.observed_at.timestamp():
            return InfrastructureReceipt(
                cut=cut,
                revision=0,
                token=self._token(cut, None),
                availability=AuthorityAvailability.UNAVAILABLE,
                unavailable_reason=_UNAVAILABLE,
            )
        nodes = tuple(_evidence(snapshot, cut.observed_at.timestamp()) for snapshot in cached.snapshots)
        return InfrastructureReceipt(
            cut=cut,
            revision=cached.revision,
            token=self._token(cut, cached, nodes),
            availability=AuthorityAvailability.AVAILABLE,
            nodes=nodes,
        )


class SimulatorHealthAuthority(_CachedHealthAuthority):
    """Cached adapter for the deterministic, observational fleet simulator."""

    __slots__ = ("_simulator",)

    def __init__(self, simulator: DeterministicFleetHealthSimulator) -> None:
        if type(simulator) is not DeterministicFleetHealthSimulator:
            raise TypeError("simulator must be an exact DeterministicFleetHealthSimulator")
        super().__init__()
        self._simulator = simulator

    def presample(self) -> None:
        """Advance and validate the simulator outside the composer cut."""

        try:
            frame = self._simulator.frame()
            if type(frame) is not FleetHealthFrame or frame.grants_control_authority:
                raise TypeError("invalid fleet-health frame")
            self._cache(frame.devices)
        except Exception:
            self._cached = None


class ReaderPoolHealthAuthority(_CachedHealthAuthority):
    """Cached adapter over a frozen pool of factory-issued passive readers."""

    __slots__ = ("_readers",)

    def __init__(self, readers: Sequence[HealthTelemetryReader]) -> None:
        if len(readers) > MAX_FLEET_DEVICES:
            raise ValueError(f"reader pool exceeds MAX_FLEET_DEVICES ({MAX_FLEET_DEVICES})")
        readers_tuple = tuple(readers)
        if len(readers_tuple) != len(readers):
            raise ValueError("reader pool changed during construction")
        for reader in readers_tuple:
            if type(reader) is not _IssuedHealthTelemetryReader:
                raise TypeError("each reader must be factory-issued by issue_health_telemetry_reader")
            # These accessors re-check the issuer key and per-entry issuance token.
            if reader.grants_control_authority:
                raise ValueError("health reader must not grant control authority")
            reader.descriptor
        ids = tuple(reader.descriptor.device_id for reader in readers_tuple)
        if len(ids) != len(set(ids)):
            raise ValueError("reader pool contains duplicate device identities")
        super().__init__()
        self._readers = readers_tuple

    def presample(self, *, observed_time_s: float) -> None:
        """Poll readers explicitly outside the composer's no-await snapshot cut."""

        if isinstance(observed_time_s, bool) or not isinstance(observed_time_s, (int, float)):
            raise TypeError("observed_time_s must be a finite non-negative number")
        observed = float(observed_time_s)
        if not math.isfinite(observed) or observed < 0:
            raise ValueError("observed_time_s must be a finite non-negative number")
        try:
            self._cache(tuple(reader.snapshot(observed_time_s=observed) for reader in self._readers))
        except Exception:
            self._cached = None


__all__ = ["ReaderPoolHealthAuthority", "SimulatorHealthAuthority"]
