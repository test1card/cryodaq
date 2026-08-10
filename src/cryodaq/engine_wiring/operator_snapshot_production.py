"""Production construction for the sole live operator-snapshot path."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cryodaq.core.alarm_v2 import AlarmStateManager
from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.engine_wiring.operator_safety_snapshot import OperatorSafetySnapshot
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    UnavailableAlarmAttentionAuthority,
    UnavailableCooldownAuthority,
    UnavailableInfrastructureAuthority,
    UnavailableSupportAuthority,
)
from cryodaq.engine_wiring.operator_snapshot_composer import OperatorSnapshotComposer
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    SAFETY_SNAPSHOT_FRESHNESS_BUDGET_S,
    DurableAttentionHistoryFeed,
    LiveAlarmAttentionAuthority,
    LiveIntegrityPersistenceAuthority,
    LiveRecordingExperimentAuthority,
    LiveSafetyReadinessAuthority,
)
from cryodaq.engine_wiring.operator_snapshot_publisher import OperatorSnapshotPublicationService
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.storage.operator_snapshot_revision import OperatorSnapshotRevisionAllocator


class SafetySnapshotOwner(Protocol):
    def snapshot_operator_safety(self) -> OperatorSafetySnapshot: ...


def build_operator_snapshot_publication_service(
    *,
    safety_owner: SafetySnapshotOwner,
    recording_feed: RecordingLifecycleFeed,
    publisher: ZMQPublisher,
    data_root: Path,
    alarm_state_owner: AlarmStateManager | None = None,
    attention_history_feed: DurableAttentionHistoryFeed | None = None,
    cadence_hz: float = 1.0,
) -> OperatorSnapshotPublicationService:
    """Build one fail-dark service from exact loop-owned production feeds."""

    if type(recording_feed) is not RecordingLifecycleFeed:
        raise TypeError("recording_feed must be the exact engine RecordingLifecycleFeed")
    if type(publisher) is not ZMQPublisher:
        raise TypeError("publisher must be the exact engine ZMQPublisher")
    if not isinstance(data_root, Path):
        raise TypeError("data_root must be pathlib.Path")
    if (alarm_state_owner is None) is not (attention_history_feed is None):
        raise ValueError("alarm state owner and attention history feed must be supplied together")
    if alarm_state_owner is not None and type(alarm_state_owner) is not AlarmStateManager:
        raise TypeError("alarm_state_owner must be the exact engine AlarmStateManager")
    if attention_history_feed is not None and type(attention_history_feed) is not DurableAttentionHistoryFeed:
        raise TypeError("attention_history_feed must be the exact engine DurableAttentionHistoryFeed")
    composer = OperatorSnapshotComposer(
        safety=LiveSafetyReadinessAuthority(
            safety_owner,
            freshness_budget_s=SAFETY_SNAPSHOT_FRESHNESS_BUDGET_S,
        ),
        attention=LiveAlarmAttentionAuthority(
            alarm_state_owner,
            attention_history_feed,
        )
        if alarm_state_owner is not None and attention_history_feed is not None
        else UnavailableAlarmAttentionAuthority(),
        experiment=LiveRecordingExperimentAuthority(recording_feed),
        integrity=LiveIntegrityPersistenceAuthority(recording_feed),
        cooldown=UnavailableCooldownAuthority(),
        infrastructure=UnavailableInfrastructureAuthority(),
        support=UnavailableSupportAuthority(),
        revision_allocator=OperatorSnapshotRevisionAllocator(data_root),
    )
    return OperatorSnapshotPublicationService(
        composer=composer,
        publisher=publisher,
        cadence_hz=cadence_hz,
    )


__all__ = ["build_operator_snapshot_publication_service"]
