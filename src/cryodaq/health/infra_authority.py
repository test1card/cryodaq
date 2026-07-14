"""Fleet-health -> InfrastructureAuthority bridge for F36.4.

Bridges the read-only HealthTelemetryDevice contract / DeterministicFleetHealthSimulator
to the operator-snapshot InfrastructureAuthority protocol.  No control path,
no tasks, no queues, no automatic remediation.

The bridge is the ONLY place that converts HealthFreshness -> OperatorPresentationState.
It is deliberately narrow: it calls simulator.frame() (or issues HealthTelemetryReader
snapshots), translates each device to InfrastructureEvidence, and returns a bounded
InfrastructureReceipt.  Nothing in this module can start, stop, reset, vent, purge, or
set anything on any device.

Safety guarantee: HealthTelemetryReader.grants_control_authority is always False;
the bridge asserts this before emitting any evidence so a future code mutation cannot
silently widen the authority boundary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
    InfrastructureEvidence,
    InfrastructureReceipt,
)
from cryodaq.health.contract import (
    HealthFreshness,
    HealthTelemetryReader,
    HealthTelemetrySnapshot,
)
from cryodaq.health.simulator import DeterministicFleetHealthSimulator, FleetHealthFrame
from cryodaq.operator_snapshot import MAX_FLEET_DEVICES, OperatorPresentationState

# Freshness -> OperatorPresentationState mapping.  Disconnected is more severe
# than stale; both are more severe than fresh/OK.  This is the ONLY place this
# mapping lives; GUI views must not re-derive it.
_FRESHNESS_STATE: dict[HealthFreshness, OperatorPresentationState] = {
    HealthFreshness.FRESH: OperatorPresentationState.OK,
    HealthFreshness.STALE: OperatorPresentationState.STALE,
    HealthFreshness.DISCONNECTED: OperatorPresentationState.DISCONNECTED,
}

# Freshness -> operator reason_code for InfrastructureEvidence
_FRESHNESS_REASON: dict[HealthFreshness, str] = {
    HealthFreshness.FRESH: "health_fresh",
    HealthFreshness.STALE: "health_stale",
    HealthFreshness.DISCONNECTED: "health_disconnected",
}


def _snapshot_to_evidence(snapshot: HealthTelemetrySnapshot) -> InfrastructureEvidence:
    """Convert one HealthTelemetrySnapshot to InfrastructureEvidence.

    The display_name is the device_id (already bounded to MAX_ID_BYTES <= MAX_TEXT_UTF8_BYTES).
    Any active alarm escalates state to at least CAUTION regardless of freshness.
    """
    freshness = snapshot.freshness
    state = _FRESHNESS_STATE[freshness]
    reason = _FRESHNESS_REASON[freshness]

    # Active alarms escalate state — read-only observation, never remediation.
    if any(alarm.active for alarm in snapshot.alarms):
        if state is OperatorPresentationState.OK:
            state = OperatorPresentationState.CAUTION
        reason = "health_alarm_active"

    return InfrastructureEvidence(
        node_id=snapshot.descriptor.device_id,
        display_name=snapshot.descriptor.device_id,
        state=state,
        reason_code=reason,
    )


def _make_receipt_token(cut: CommonCut, revision: int) -> str:
    """Derive a deterministic authority token from cut token + revision."""
    digest = hashlib.sha256(f"{cut.token}:{revision}".encode()).hexdigest()
    return f"authority-v1:{revision}:{digest}"


class SimulatorHealthAuthority:
    """Read-only InfrastructureAuthority backed by the deterministic fleet simulator.

    Instantiate once; call snapshot_for_cut() on every composer cycle.  Each call
    advances the simulator clock by one cadence interval and returns a bounded
    InfrastructureReceipt.  There are no tasks, queues, callbacks, or write paths.

    Safety: grants_control_authority is unconditionally False on both this class and
    the underlying FleetHealthFrame.  The simulator never accepts commands.
    """

    __slots__ = ("_revision", "_simulator")

    grants_control_authority = False  # class-level, immutable

    def __init__(self, simulator: DeterministicFleetHealthSimulator) -> None:
        if not isinstance(simulator, DeterministicFleetHealthSimulator):
            raise TypeError("simulator must be a DeterministicFleetHealthSimulator")
        self._simulator = simulator
        self._revision = 0

    def snapshot_for_cut(self, cut: CommonCut) -> InfrastructureReceipt:
        """Sample one deterministic frame and return a bounded InfrastructureReceipt.

        The frame is immediately discarded after evidence extraction; no history accumulates.
        """
        frame: FleetHealthFrame = self._simulator.frame()

        # Safety assertion: the frame must never grant control authority.
        assert not frame.grants_control_authority, (
            "FleetHealthFrame.grants_control_authority must be False; safety boundary violated"
        )

        self._revision += 1
        revision = self._revision

        nodes = tuple(
            _snapshot_to_evidence(device)
            for device in frame.devices
            if len(frame.devices) <= MAX_FLEET_DEVICES  # guard: reject oversized frames
        )

        # If frame is oversized, emit unavailable rather than silently truncating.
        if len(frame.devices) > MAX_FLEET_DEVICES:
            return InfrastructureReceipt(
                cut=cut,
                revision=0,
                token=_make_receipt_token(cut, 0),
                availability=AuthorityAvailability.UNAVAILABLE,
                unavailable_reason="health_fleet_exceeds_max_devices",
            )

        return InfrastructureReceipt(
            cut=cut,
            revision=revision,
            token=_make_receipt_token(cut, revision),
            availability=AuthorityAvailability.AVAILABLE,
            nodes=nodes,
        )


class ReaderPoolHealthAuthority:
    """Read-only InfrastructureAuthority backed by a fixed pool of HealthTelemetryReaders.

    The pool is set at construction and is FROZEN: no reader can be added or removed
    after construction, and no reader exposes control authority.  Each snapshot_for_cut()
    call samples every reader synchronously and returns a bounded InfrastructureReceipt.

    Safety: every reader must have grants_control_authority == False.  This is verified
    at construction time and re-asserted at each snapshot call.  A reader that returns
    True is rejected and the authority emits unavailable for that cycle.
    """

    __slots__ = ("_readers", "_revision")

    grants_control_authority = False  # class-level, immutable

    def __init__(self, readers: Sequence[HealthTelemetryReader]) -> None:
        readers_tuple = tuple(readers)
        if len(readers_tuple) > MAX_FLEET_DEVICES:
            raise ValueError(f"reader pool exceeds MAX_FLEET_DEVICES ({MAX_FLEET_DEVICES}); got {len(readers_tuple)}")
        for reader in readers_tuple:
            if not isinstance(reader, HealthTelemetryReader):
                raise TypeError("each reader must conform to HealthTelemetryReader protocol")
            if reader.grants_control_authority:
                raise ValueError(
                    f"reader {reader.descriptor.device_id!r} grants_control_authority=True; "
                    "no read-only pool member may hold control authority"
                )
        # Freeze: tuple is immutable; no append/remove path exists.
        self._readers: tuple[HealthTelemetryReader, ...] = readers_tuple
        self._revision = 0

    def snapshot_for_cut(self, cut: CommonCut) -> InfrastructureReceipt:
        """Sample all readers at the cut's observed_at timestamp and return one receipt."""
        observed_time_s = cut.observed_at.timestamp()
        nodes: list[InfrastructureEvidence] = []
        for reader in self._readers:
            # Re-assert at call time: a reader that somehow gains control authority
            # after construction is rejected and makes the whole receipt unavailable.
            if reader.grants_control_authority:
                return InfrastructureReceipt(
                    cut=cut,
                    revision=0,
                    token=_make_receipt_token(cut, 0),
                    availability=AuthorityAvailability.UNAVAILABLE,
                    unavailable_reason="health_reader_gained_control_authority",
                )
            snapshot = reader.snapshot(observed_time_s=observed_time_s)
            nodes.append(_snapshot_to_evidence(snapshot))

        self._revision += 1
        revision = self._revision
        return InfrastructureReceipt(
            cut=cut,
            revision=revision,
            token=_make_receipt_token(cut, revision),
            availability=AuthorityAvailability.AVAILABLE,
            nodes=tuple(nodes),
        )


__all__ = [
    "ReaderPoolHealthAuthority",
    "SimulatorHealthAuthority",
]
