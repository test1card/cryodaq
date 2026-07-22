import copy
import json
import pickle
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.gui.state import operator_view_models as view_models
from cryodaq.gui.state.operator_view_models import OperatorSnapshotStore
from cryodaq.operator_snapshot import (
    MAX_LIVE_SOURCES_PER_SESSION,
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
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
    decode_operator_snapshot,
    dump_operator_snapshot,
    encode_operator_snapshot,
    load_operator_snapshot,
)

SUMMARY_TYPES = (
    ReadinessSummary,
    PlantHealthSummary,
    InfrastructureNodeHealth,
    AttentionQueue,
    ExperimentOperatingState,
    DataIntegritySummary,
    CooldownHistorySummary,
    SupportBundleSummary,
)


def apply_transport_freshness(
    value: OperatorSnapshot | OperatorSnapshotStore,
    **arguments: object,
) -> OperatorSnapshotStore:
    """Test shorthand around the transition-owning GUI-session store."""

    store = value if isinstance(value, OperatorSnapshotStore) else OperatorSnapshotStore()
    if isinstance(value, OperatorSnapshot):
        store.accept_snapshot(value)
    store.observe_transport(**arguments)
    return store


def _present(store: OperatorSnapshotStore) -> OperatorSnapshot:
    snapshot = store.snapshot
    assert snapshot is not None
    return snapshot


def _snapshot(
    *,
    state: OperatorPresentationState = OperatorPresentationState.OK,
    mode: SnapshotMode = SnapshotMode.LIVE,
) -> OperatorSnapshot:
    observed_at = datetime(2026, 7, 11, 1, 2, tzinfo=UTC)
    cut = SnapshotCut(
        revision=42,
        observed_at=observed_at,
        received_at=observed_at + timedelta(seconds=1),
        source="engine/operator-snapshot-v1",
        mode=mode,
        experiment_id="exp-7",
        producer_id="engine/operator-snapshot-v1",
    )
    effective_state = (
        OperatorPresentationState.STALE
        if mode is SnapshotMode.REPLAY and state is OperatorPresentationState.OK
        else state
    )
    status = SummaryStatus(
        state=effective_state,
        source_age_s=1.0,
        transport_age_s=0.25,
        reason_codes=("authoritative_snapshot",),
        operator_text="Состояние подтверждено движком",
    )
    urgent = effective_state in {
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    }
    blocker = (
        ReadinessBlocker(
            "vacuum_not_ready",
            effective_state,
            "Вакуум не готов",
            "Подтвержденное давление ниже порога",
        )
        if urgent
        else None
    )
    manifest = SupportBundleManifest(
        "bundle-42",
        cut.received_at,
        (SupportBundleEntry("status.json", 123, "a" * 64),),
    )
    current = effective_state not in {
        OperatorPresentationState.STALE,
        OperatorPresentationState.DISCONNECTED,
    }
    recording = (
        RecordingTruth.REPLAY_ONLY
        if mode is SnapshotMode.REPLAY
        else RecordingTruth.RECORDING
        if effective_state in {OperatorPresentationState.OK, OperatorPresentationState.CAUTION}
        else RecordingTruth.NOT_RECORDING
        if current
        else RecordingTruth.UNKNOWN
    )
    available = (
        AvailabilityTruth.UNKNOWN
        if mode is SnapshotMode.REPLAY
        else AvailabilityTruth.AVAILABLE
        if current
        else AvailabilityTruth.UNKNOWN
    )
    readiness = (
        ReadinessTruth.UNKNOWN
        if mode is SnapshotMode.REPLAY
        else ReadinessTruth.BLOCKED
        if urgent
        else (
            ReadinessTruth.UNKNOWN
            if effective_state
            in {
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }
            else ReadinessTruth.READY
        )
    )
    lifecycle = {
        ReadinessTruth.READY: SafetyLifecycle.READY,
        ReadinessTruth.BLOCKED: SafetyLifecycle.FAULT_LATCHED,
        ReadinessTruth.UNKNOWN: SafetyLifecycle.UNKNOWN,
    }[readiness]
    return OperatorSnapshot(
        cut=cut,
        readiness=ReadinessSummary(
            cut,
            status,
            readiness,
            () if blocker is None else (blocker,),
            lifecycle,
        ),
        plant_health=PlantHealthSummary(
            cut,
            status,
            (PlantHealthItem("vacuum", "Вакуум", effective_state, ("authoritative_snapshot",)),),
        ),
        infrastructure=InfrastructureNodeHealth(
            cut,
            status,
            (
                InfrastructureNode("ups-a", "ИБП A", effective_state, ("telemetry_current",)),
                InfrastructureNode("chiller-a", "Чиллер A", effective_state, ("telemetry_current",)),
            ),
        ),
        attention=AttentionQueue(
            cut,
            status,
            (
                ()
                if not urgent
                else (
                    AttentionItem("alarm-1", effective_state, "Вакуум", "Проверить насос", observed_at),
                    AttentionItem(
                        "alarm-2",
                        effective_state,
                        "Хранилище",
                        "Проверить место",
                        observed_at,
                    ),
                )
            ),
        ),
        experiment=ExperimentOperatingState(
            cut,
            status,
            "exp-7",
            "Cooldown 7",
            "cooldown",
            recording,
            "rec-9" if recording is RecordingTruth.RECORDING else None,
        ),
        data_integrity=DataIntegritySummary(cut, status, 42, 41, 3, 0, available),
        cooldown_history=CooldownHistorySummary(
            cut,
            status,
            (CooldownSample(0, 300), CooldownSample(60, 250)),
            "reference-a",
            (CooldownSample(0, 300), CooldownSample(60, 245)),
        ),
        support_bundle=SupportBundleSummary(
            cut,
            status,
            available,
            manifest if available is AvailabilityTruth.AVAILABLE else None,
        ),
    )


def _recut(snapshot: OperatorSnapshot, **changes: object) -> OperatorSnapshot:
    cut = replace(snapshot.cut, **changes)
    return OperatorSnapshot(cut, *(replace(summary, cut=cut) for summary in snapshot.summaries()))


def test_presentation_vocabulary_is_exact_design_system_contract() -> None:
    assert {state.value for state in OperatorPresentationState} == {
        "ok",
        "caution",
        "warning",
        "fault",
        "stale",
        "disconnected",
    }


def test_summary_specific_schema_carries_all_operator_decision_evidence() -> None:
    snapshot = _snapshot(state=OperatorPresentationState.CAUTION)

    assert snapshot.readiness.blockers[0].required_evidence
    assert len(snapshot.attention.items) == 2
    assert snapshot.experiment.experiment_id == "exp-7"
    assert snapshot.experiment.recording_session_id == "rec-9"
    assert len(snapshot.infrastructure.nodes) == 2
    assert snapshot.data_integrity.persisted_revision == 42
    assert snapshot.cooldown_history.reference_id == "reference-a"
    assert snapshot.support_bundle.manifest.entries[0].sha256 == "a" * 64
    assert not any("fact" in field.name for summary in snapshot.summaries() for field in fields(summary))


def test_snapshot_and_nested_values_are_immutable() -> None:
    snapshot = _snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.cut.revision = 43  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.attention.items = ()  # type: ignore[misc]
    with pytest.raises(TypeError, match="tuple of AttentionItem"):
        AttentionQueue(snapshot.cut, snapshot.attention.status, [])  # type: ignore[arg-type]


def test_each_summary_exposes_provenance_independent_ages_reason_revision_and_time() -> None:
    snapshot = _snapshot()

    for summary in snapshot.summaries():
        assert summary.revision == 42
        assert summary.observed_at == snapshot.cut.observed_at
        assert summary.provenance == "engine/operator-snapshot-v1"
        assert summary.source_age_s == 1.0
        assert summary.transport_age_s == 0.25
        assert summary.reason_codes == ("authoritative_snapshot",)
        assert summary.transport_reason_codes == ()
        assert summary.state is OperatorPresentationState.OK


def test_snapshot_rejects_mixed_revision_or_provenance_cut() -> None:
    snapshot = _snapshot()
    other_cut = SnapshotCut(
        revision=43,
        observed_at=snapshot.cut.observed_at,
        received_at=snapshot.cut.received_at,
        source=snapshot.cut.source,
        mode=SnapshotMode.LIVE,
        experiment_id=snapshot.cut.experiment_id,
        producer_id=snapshot.cut.producer_id,
    )

    with pytest.raises(ValueError, match="same snapshot cut"):
        OperatorSnapshot(
            cut=snapshot.cut,
            readiness=ReadinessSummary(
                other_cut,
                snapshot.readiness.status,
                ReadinessTruth.READY,
                (),
                SafetyLifecycle.READY,
            ),
            plant_health=snapshot.plant_health,
            infrastructure=snapshot.infrastructure,
            attention=snapshot.attention,
            experiment=snapshot.experiment,
            data_integrity=snapshot.data_integrity,
            cooldown_history=snapshot.cooldown_history,
            support_bundle=snapshot.support_bundle,
        )


def test_live_future_source_timestamp_fails_closed_but_historical_replay_is_valid() -> None:
    receipt = datetime(2026, 7, 11, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="live observed_at"):
        SnapshotCut(1, receipt + timedelta(seconds=1), receipt, "engine", SnapshotMode.LIVE, "exp-7", "engine")

    replay = SnapshotCut(
        1,
        datetime(2001, 1, 1, tzinfo=UTC),
        receipt,
        "archive",
        SnapshotMode.REPLAY,
        "exp-7",
        "archive",
    )
    assert replay.observed_at.year == 2001


def test_disconnected_transport_is_idempotent_and_does_not_change_cut() -> None:
    snapshot = _snapshot(state=OperatorPresentationState.OK)
    first = apply_transport_freshness(snapshot, connected=False, transport_age_s=8, stale_after_s=5)
    second = apply_transport_freshness(first, connected=False, transport_age_s=8, stale_after_s=5)

    assert first.readiness.readiness is ReadinessTruth.UNKNOWN
    assert first.readiness.lifecycle is SafetyLifecycle.UNKNOWN
    assert second.readiness.lifecycle is SafetyLifecycle.UNKNOWN

    assert first.cut == snapshot.cut
    assert second == first
    for summary in second.summaries():
        assert summary.state is OperatorPresentationState.DISCONNECTED
        assert summary.transport_age_s == 8
        assert summary.reason_codes == ("authoritative_snapshot",)
        assert summary.transport_reason_codes == ("transport_disconnected",)
        assert summary.status.operator_text == "Состояние подтверждено движком"


@pytest.mark.parametrize(
    "urgent_state",
    [
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    ],
)
def test_disconnection_preserves_urgent_last_known_truth_with_secondary_cue(
    urgent_state: OperatorPresentationState,
) -> None:
    result = apply_transport_freshness(
        _snapshot(state=urgent_state),
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )

    assert {summary.state for summary in result.summaries()} == {urgent_state}
    assert all(summary.transport_reason_codes == ("transport_disconnected",) for summary in result.summaries())
    assert all(summary.status.operator_text == "Состояние подтверждено движком" for summary in result.summaries())

    assert result.readiness.readiness is ReadinessTruth.UNKNOWN
    assert result.experiment.recording is RecordingTruth.UNKNOWN
    assert result.experiment.recording_session_id is None
    assert result.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert result.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert result.support_bundle.manifest is None
    assert {item.state for item in result.plant_health.subsystems} == {urgent_state}
    assert {item.state for item in result.infrastructure.nodes} == {urgent_state}


@pytest.mark.parametrize(
    ("connected", "expected"),
    [
        (True, OperatorPresentationState.STALE),
        (False, OperatorPresentationState.DISCONNECTED),
    ],
)
def test_transport_degradation_invalidates_current_truth_and_nested_ok_items(
    connected: bool,
    expected: OperatorPresentationState,
) -> None:
    result = apply_transport_freshness(
        _snapshot(),
        connected=connected,
        transport_age_s=8,
        stale_after_s=5,
    )

    assert result.readiness.readiness is ReadinessTruth.UNKNOWN
    assert result.experiment.recording is RecordingTruth.UNKNOWN
    assert result.experiment.recording_session_id is None
    assert result.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert result.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert result.support_bundle.manifest is None
    assert {item.state for item in result.plant_health.subsystems} == {expected}
    assert {item.state for item in result.infrastructure.nodes} == {expected}
    assert all(
        item.transport_reason_codes == (("snapshot_stale" if connected else "transport_disconnected"),)
        for item in (*result.plant_health.subsystems, *result.infrastructure.nodes)
    )


@pytest.mark.parametrize(
    "initial",
    [
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
        OperatorPresentationState.STALE,
        OperatorPresentationState.DISCONNECTED,
    ],
)
@pytest.mark.parametrize("connected", [True, False])
def test_transport_degrades_nested_blockers_and_attention_with_explicit_cue(
    initial: OperatorPresentationState,
    connected: bool,
) -> None:
    snapshot = _snapshot()
    nested_status = replace(snapshot.readiness.status, state=initial)
    blocker = ReadinessBlocker("nested", initial, "Причина", "Доказательство")
    attention = AttentionItem("nested", initial, "Причина", "Подробность", snapshot.cut.observed_at)
    snapshot = replace(
        snapshot,
        readiness=replace(
            snapshot.readiness,
            status=nested_status,
            readiness=ReadinessTruth.BLOCKED,
            blockers=(blocker,),
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
        ),
        attention=replace(snapshot.attention, status=nested_status, items=(attention,)),
    )

    result = apply_transport_freshness(
        snapshot,
        connected=connected,
        transport_age_s=8,
        stale_after_s=5,
    )
    repeated = apply_transport_freshness(
        result,
        connected=connected,
        transport_age_s=8,
        stale_after_s=5,
    )
    expected = (
        initial
        if initial
        in {
            OperatorPresentationState.CAUTION,
            OperatorPresentationState.WARNING,
            OperatorPresentationState.FAULT,
        }
        else OperatorPresentationState.DISCONNECTED
        if not connected or initial is OperatorPresentationState.DISCONNECTED
        else OperatorPresentationState.STALE
    )
    reason = "snapshot_stale" if connected else "transport_disconnected"

    assert result.readiness.blockers[0].state is expected
    assert result.attention.items[0].state is expected
    assert result.readiness.blockers[0].transport_reason_codes == (reason,)
    assert result.attention.items[0].transport_reason_codes == (reason,)
    assert repeated == result


@pytest.mark.parametrize("connected", [True, False])
def test_transport_evidence_never_evicts_full_backend_reason_budget(connected: bool) -> None:
    snapshot = _snapshot()
    reasons = tuple(f"backend_{index}" for index in range(4))
    max_text = "я" * 128
    status = replace(snapshot.readiness.status, reason_codes=reasons, operator_text=max_text)
    plant = replace(snapshot.plant_health.subsystems[0], reason_codes=reasons)
    node = replace(snapshot.infrastructure.nodes[0], reason_codes=reasons)
    snapshot = replace(
        snapshot,
        readiness=replace(snapshot.readiness, status=status),
        plant_health=replace(snapshot.plant_health, status=status, subsystems=(plant,)),
        infrastructure=replace(snapshot.infrastructure, status=status, nodes=(node,)),
        attention=replace(snapshot.attention, status=status),
        experiment=replace(snapshot.experiment, status=status),
        data_integrity=replace(snapshot.data_integrity, status=status),
        cooldown_history=replace(snapshot.cooldown_history, status=status),
        support_bundle=replace(snapshot.support_bundle, status=status),
    )

    result = apply_transport_freshness(
        snapshot,
        connected=connected,
        transport_age_s=8,
        stale_after_s=5,
    )
    reason = "snapshot_stale" if connected else "transport_disconnected"
    repeated = apply_transport_freshness(
        result,
        connected=connected,
        transport_age_s=8,
        stale_after_s=5,
    )

    assert all(summary.reason_codes == reasons for summary in result.summaries())
    assert all(summary.status.operator_text == max_text for summary in result.summaries())
    assert all(summary.transport_reason_codes == (reason,) for summary in result.summaries())
    assert result.plant_health.subsystems[0].reason_codes == reasons
    assert result.infrastructure.nodes[0].reason_codes == reasons
    assert result.plant_health.subsystems[0].transport_reason_codes == (reason,)
    assert result.infrastructure.nodes[0].transport_reason_codes == (reason,)
    assert load_operator_snapshot(dump_operator_snapshot(result.snapshot)) == result.snapshot
    assert repeated == result


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        (OperatorPresentationState.OK, OperatorPresentationState.STALE),
        (OperatorPresentationState.CAUTION, OperatorPresentationState.CAUTION),
        (OperatorPresentationState.WARNING, OperatorPresentationState.WARNING),
        (OperatorPresentationState.FAULT, OperatorPresentationState.FAULT),
        (OperatorPresentationState.STALE, OperatorPresentationState.STALE),
        (OperatorPresentationState.DISCONNECTED, OperatorPresentationState.DISCONNECTED),
    ],
)
def test_stale_transport_never_upgrades_or_hides_more_urgent_truth(
    initial: OperatorPresentationState,
    expected: OperatorPresentationState,
) -> None:
    result = apply_transport_freshness(
        _snapshot(state=initial),
        connected=True,
        transport_age_s=10,
        stale_after_s=5,
    )

    assert {summary.state for summary in result.summaries()} == {expected}
    assert all(summary.transport_reason_codes == ("snapshot_stale",) for summary in result.summaries())


def test_fresh_transport_uses_explicit_age_and_never_compares_source_wall_clock() -> None:
    snapshot = _snapshot(state=OperatorPresentationState.WARNING, mode=SnapshotMode.REPLAY)
    result = apply_transport_freshness(snapshot, connected=True, transport_age_s=1, stale_after_s=5)

    assert result.cut.mode is SnapshotMode.REPLAY
    assert result.readiness.state is OperatorPresentationState.WARNING
    assert result.readiness.transport_age_s == 1


def test_same_cut_disconnect_then_connected_stale_replaces_disconnected_cue() -> None:
    disconnected = apply_transport_freshness(
        _snapshot(),
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    connected_stale = apply_transport_freshness(
        disconnected,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )

    assert {summary.state for summary in connected_stale.summaries()} == {OperatorPresentationState.STALE}
    assert all(summary.transport_reason_codes == ("snapshot_stale",) for summary in connected_stale.summaries())
    assert {
        item.state
        for item in (
            *connected_stale.plant_health.subsystems,
            *connected_stale.infrastructure.nodes,
        )
    } == {OperatorPresentationState.STALE}
    assert load_operator_snapshot(dump_operator_snapshot(connected_stale.snapshot)) == connected_stale.snapshot
    assert (
        apply_transport_freshness(
            connected_stale,
            connected=True,
            transport_age_s=8,
            stale_after_s=5,
        )
        == connected_stale
    )


def test_same_cut_transport_transition_matrix_is_coherent() -> None:
    store = apply_transport_freshness(
        _snapshot(),
        connected=True,
        transport_age_s=1,
        stale_after_s=5,
    )
    fresh = _present(store)
    apply_transport_freshness(
        store,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )
    stale = _present(store)
    apply_transport_freshness(
        store,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    disconnected = _present(store)
    apply_transport_freshness(
        store,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )
    connected_stale = _present(store)

    assert {summary.state for summary in fresh.summaries()} == {OperatorPresentationState.OK}
    assert {summary.state for summary in stale.summaries()} == {OperatorPresentationState.STALE}
    assert {summary.state for summary in disconnected.summaries()} == {OperatorPresentationState.DISCONNECTED}
    assert {summary.state for summary in connected_stale.summaries()} == {OperatorPresentationState.STALE}
    assert [
        stage.readiness.transport_reason_codes
        for stage in (
            fresh,
            stale,
            disconnected,
            connected_stale,
        )
    ] == [
        (),
        ("snapshot_stale",),
        ("transport_disconnected",),
        ("snapshot_stale",),
    ]


@pytest.mark.parametrize("backend_state", list(OperatorPresentationState))
def test_raw_backend_state_survives_full_same_cut_transport_matrix(
    backend_state: OperatorPresentationState,
) -> None:
    raw = _snapshot(state=backend_state)

    def primary(transport_state: OperatorPresentationState) -> OperatorPresentationState:
        return max((backend_state, transport_state), key=STATE_PRECEDENCE.__getitem__)

    store = apply_transport_freshness(
        raw,
        connected=True,
        transport_age_s=1,
        stale_after_s=5,
    )
    fresh = _present(store)
    apply_transport_freshness(
        store,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )
    stale = _present(store)
    apply_transport_freshness(
        store,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    disconnected = _present(store)
    apply_transport_freshness(
        store,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )
    connected_stale = _present(store)
    apply_transport_freshness(
        store,
        connected=True,
        transport_age_s=8,
        stale_after_s=10,
    )
    connected_fresh_same_cut = _present(store)

    assert {summary.state for summary in fresh.summaries()} == {backend_state}
    assert {summary.state for summary in stale.summaries()} == {primary(OperatorPresentationState.STALE)}
    assert {summary.state for summary in disconnected.summaries()} == {primary(OperatorPresentationState.DISCONNECTED)}
    assert {summary.state for summary in connected_stale.summaries()} == {primary(OperatorPresentationState.STALE)}
    assert {summary.state for summary in connected_fresh_same_cut.summaries()} == {
        primary(OperatorPresentationState.STALE)
    }
    for stage, expected in (
        (stale, primary(OperatorPresentationState.STALE)),
        (disconnected, primary(OperatorPresentationState.DISCONNECTED)),
        (connected_stale, primary(OperatorPresentationState.STALE)),
        (connected_fresh_same_cut, primary(OperatorPresentationState.STALE)),
    ):
        assert {item.state for item in stage.plant_health.subsystems} == {expected}
        assert {item.state for item in stage.infrastructure.nodes} == {expected}
        if stage.readiness.blockers:
            assert {item.state for item in stage.readiness.blockers} == {expected}
        if stage.attention.items:
            assert {item.state for item in stage.attention.items} == {expected}
    assert all(summary.transport_reason_codes == ("snapshot_stale",) for summary in connected_stale.summaries())
    assert all(summary.transport_reason_codes == () for summary in connected_fresh_same_cut.summaries())
    assert connected_fresh_same_cut.readiness.readiness is ReadinessTruth.UNKNOWN
    assert connected_fresh_same_cut.experiment.recording is RecordingTruth.UNKNOWN
    assert connected_fresh_same_cut.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert connected_fresh_same_cut.support_bundle.availability is AvailabilityTruth.UNKNOWN


def test_newer_raw_cut_alone_restores_current_authority_after_same_cut_degradation() -> None:
    store = apply_transport_freshness(
        _snapshot(),
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    assert store.experiment.recording is RecordingTruth.UNKNOWN

    raw = _snapshot()
    newer_cut = replace(raw.cut, revision=raw.cut.revision + 1)
    newer = OperatorSnapshot(
        newer_cut,
        *(replace(summary, cut=newer_cut) for summary in raw.summaries()),
    )
    store.accept_snapshot(newer)
    store.observe_transport(connected=True, transport_age_s=1, stale_after_s=5)

    assert store.cut.revision == 43
    assert {summary.state for summary in store.summaries()} == {OperatorPresentationState.OK}
    assert store.readiness.readiness is ReadinessTruth.READY
    assert store.experiment.recording is RecordingTruth.RECORDING
    assert store.data_integrity.storage is AvailabilityTruth.AVAILABLE
    assert store.support_bundle.availability is AvailabilityTruth.AVAILABLE


def test_store_is_empty_single_owner_and_has_no_public_overlay_value() -> None:
    store = OperatorSnapshotStore()

    assert store.snapshot is None
    assert not hasattr(view_models, "TransportOverlayState")
    assert not hasattr(view_models, "apply_transport_freshness")
    assert not hasattr(store, "raw_snapshot")
    with pytest.raises(TypeError):
        OperatorSnapshotStore(_snapshot())
    with pytest.raises(RuntimeError, match="no backend cut"):
        store.observe_transport(connected=True, transport_age_s=1, stale_after_s=5)
    with pytest.raises(TypeError, match="single-owner"):
        copy.copy(store)
    with pytest.raises(TypeError, match="single-owner"):
        copy.deepcopy(store)
    with pytest.raises(TypeError, match="GUI-session owner"):
        pickle.dumps(store)
    with pytest.raises(TypeError):
        hash(store)


def test_same_cut_raw_cannot_reset_authority_after_disconnect() -> None:
    raw = _snapshot()
    store = OperatorSnapshotStore()
    store.accept_snapshot(raw)
    disconnected = store.observe_transport(connected=False, transport_age_s=8, stale_after_s=5)

    assert disconnected.experiment.recording is RecordingTruth.UNKNOWN
    with pytest.raises(ValueError, match="same-cut raw snapshot cannot reset"):
        store.accept_snapshot(raw)
    decoded_raw = load_operator_snapshot(dump_operator_snapshot(raw))
    with pytest.raises(ValueError, match="same-cut raw snapshot cannot reset"):
        store.accept_snapshot(decoded_raw)
    assert store.experiment.recording is RecordingTruth.UNKNOWN
    assert {summary.state for summary in store.summaries()} == {OperatorPresentationState.DISCONNECTED}


def test_equal_cut_identical_raw_is_idempotent_only_before_invalidation() -> None:
    raw = _snapshot()
    decoded = load_operator_snapshot(dump_operator_snapshot(raw))
    store = OperatorSnapshotStore()

    assert store.accept_snapshot(raw) == raw
    assert store.accept_snapshot(decoded) == raw
    store.observe_transport(connected=True, transport_age_s=1, stale_after_s=5)
    assert store.accept_snapshot(decoded).cut == raw.cut
    store.observe_transport(connected=True, transport_age_s=8, stale_after_s=5)
    with pytest.raises(ValueError, match="same-cut raw snapshot cannot reset"):
        store.accept_snapshot(decoded)


def test_same_cut_different_truth_and_nonmonotonic_new_cuts_are_rejected() -> None:
    raw = _snapshot()
    store = OperatorSnapshotStore()
    store.accept_snapshot(raw)

    same_cut_fault = _snapshot(state=OperatorPresentationState.FAULT)
    with pytest.raises(ValueError, match="same cut cannot carry different"):
        store.accept_snapshot(same_cut_fault)

    later_time = raw.cut.received_at + timedelta(seconds=1)
    equal_revision_later_time = replace(
        raw.cut,
        observed_at=later_time,
        received_at=later_time,
    )
    equal_revision = OperatorSnapshot(
        equal_revision_later_time,
        *(replace(summary, cut=equal_revision_later_time) for summary in raw.summaries()),
    )
    with pytest.raises(ValueError, match="revision must be strictly newer"):
        store.accept_snapshot(equal_revision)

    backwards_time = replace(
        raw.cut,
        revision=43,
        received_at=raw.cut.received_at - timedelta(seconds=1),
    )
    backwards = OperatorSnapshot(
        backwards_time,
        *(replace(summary, cut=backwards_time) for summary in raw.summaries()),
    )
    with pytest.raises(ValueError, match="received_at cannot move backwards"):
        store.accept_snapshot(backwards)

    backwards_live_time = replace(
        raw.cut,
        revision=43,
        observed_at=raw.cut.observed_at - timedelta(seconds=1),
        received_at=raw.cut.received_at + timedelta(seconds=1),
    )
    backwards_live = OperatorSnapshot(
        backwards_live_time,
        *(replace(summary, cut=backwards_live_time) for summary in raw.summaries()),
    )
    with pytest.raises(ValueError, match="live observed_at cannot move backwards"):
        store.accept_snapshot(backwards_live)


def test_strict_newer_replay_and_live_cuts_preserve_mode_authority() -> None:
    live = _snapshot()
    store = OperatorSnapshotStore()
    store.accept_snapshot(live)
    store.observe_transport(connected=False, transport_age_s=8, stale_after_s=5)

    replay = _snapshot(mode=SnapshotMode.REPLAY)
    replay_cut = replace(replay.cut, revision=43)
    replay = OperatorSnapshot(
        replay_cut,
        *(replace(summary, cut=replay_cut) for summary in replay.summaries()),
    )
    store.accept_snapshot(replay)
    assert store.cut.mode is SnapshotMode.REPLAY
    assert store.experiment.recording is RecordingTruth.REPLAY_ONLY
    assert store.readiness.readiness is ReadinessTruth.UNKNOWN

    newer_live_cut = replace(live.cut, revision=44)
    newer_live = OperatorSnapshot(
        newer_live_cut,
        *(replace(summary, cut=newer_live_cut) for summary in live.summaries()),
    )
    store.accept_snapshot(newer_live)
    assert store.cut.mode is SnapshotMode.LIVE
    assert store.experiment.recording is RecordingTruth.RECORDING
    assert store.readiness.readiness is ReadinessTruth.READY


def test_live_old_replay_older_seek_live_preserves_temporal_and_mode_authority() -> None:
    live = _snapshot()
    store = OperatorSnapshotStore()
    store.accept_snapshot(live)
    store.observe_transport(connected=False, transport_age_s=8, stale_after_s=5)

    replay_base = _snapshot(mode=SnapshotMode.REPLAY)
    old_replay_cut = replace(
        replay_base.cut,
        revision=43,
        observed_at=datetime(2001, 1, 1, tzinfo=UTC),
        received_at=live.cut.received_at + timedelta(seconds=1),
        source="replay/session-a",
    )
    old_replay = OperatorSnapshot(
        old_replay_cut,
        *(replace(summary, cut=old_replay_cut) for summary in replay_base.summaries()),
    )
    store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(old_replay)))
    assert store.cut.source == "replay/session-a"
    assert store.cut.observed_at.year == 2001
    assert store.readiness.readiness is ReadinessTruth.UNKNOWN
    assert store.experiment.recording is RecordingTruth.REPLAY_ONLY
    assert store.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert store.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert all(summary.state is not OperatorPresentationState.OK for summary in store.summaries())

    store.observe_transport(connected=True, transport_age_s=1, stale_after_s=5)
    older_seek_cut = replace(
        old_replay_cut,
        revision=44,
        observed_at=datetime(1997, 1, 1, tzinfo=UTC),
        received_at=old_replay_cut.received_at + timedelta(seconds=1),
    )
    older_seek = OperatorSnapshot(
        older_seek_cut,
        *(replace(summary, cut=older_seek_cut) for summary in replay_base.summaries()),
    )
    store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(older_seek)))
    assert store.cut.source == "replay/session-a"
    assert store.cut.observed_at.year == 1997
    assert store.experiment.recording is RecordingTruth.REPLAY_ONLY

    return_live_cut = replace(
        live.cut,
        revision=45,
        observed_at=live.cut.observed_at + timedelta(seconds=1),
        received_at=older_seek_cut.received_at + timedelta(seconds=1),
    )
    return_live = OperatorSnapshot(
        return_live_cut,
        *(replace(summary, cut=return_live_cut) for summary in live.summaries()),
    )
    store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(return_live)))
    assert store.cut.source == live.cut.source
    assert store.cut.mode is SnapshotMode.LIVE
    assert store.readiness.readiness is ReadinessTruth.READY
    assert store.experiment.recording is RecordingTruth.RECORDING

    regressed_live_cut = replace(
        live.cut,
        revision=46,
        observed_at=live.cut.observed_at - timedelta(seconds=1),
        received_at=return_live_cut.received_at + timedelta(seconds=1),
    )
    regressed_live = OperatorSnapshot(
        regressed_live_cut,
        *(replace(summary, cut=regressed_live_cut) for summary in live.summaries()),
    )
    with pytest.raises(ValueError, match="live observed_at cannot move backwards"):
        store.accept_snapshot(regressed_live)


def test_live_source_high_water_survives_other_live_source_and_replay() -> None:
    base = _snapshot()
    live_a = _recut(base, source="live/a")
    live_b = _recut(
        base,
        revision=43,
        observed_at=base.cut.observed_at + timedelta(seconds=2),
        received_at=base.cut.received_at + timedelta(seconds=2),
        source="live/b",
    )
    replay = _recut(
        _snapshot(mode=SnapshotMode.REPLAY),
        revision=44,
        observed_at=datetime(2000, 1, 1, tzinfo=UTC),
        received_at=base.cut.received_at + timedelta(seconds=3),
        source="replay/x",
    )
    store = OperatorSnapshotStore()
    for snapshot in (live_a, live_b, replay):
        store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(snapshot)))

    regressed_a = _recut(
        base,
        revision=45,
        observed_at=base.cut.observed_at - timedelta(seconds=1),
        received_at=base.cut.received_at + timedelta(seconds=4),
        source="live/a",
    )
    with pytest.raises(ValueError, match="live observed_at cannot move backwards"):
        store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(regressed_a)))
    assert store.cut == replay.cut
    assert store.experiment.recording is RecordingTruth.REPLAY_ONLY

    newer_a = _recut(
        base,
        revision=45,
        observed_at=base.cut.observed_at + timedelta(seconds=1),
        received_at=base.cut.received_at + timedelta(seconds=4),
        source="live/a",
    )
    store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(newer_a)))
    assert store.cut == newer_a.cut
    assert store.experiment.recording is RecordingTruth.RECORDING


def test_live_source_churn_limit_fails_closed_without_clearing_invalidation() -> None:
    base = _snapshot()
    store = OperatorSnapshotStore()
    for index in range(MAX_LIVE_SOURCES_PER_SESSION):
        snapshot = _recut(
            base,
            revision=base.cut.revision + index,
            observed_at=base.cut.observed_at + timedelta(seconds=index),
            received_at=base.cut.received_at + timedelta(seconds=index),
            source=f"live/{index}",
        )
        store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(snapshot)))

    disconnected = store.observe_transport(connected=False, transport_age_s=8, stale_after_s=5)
    current_cut = store.cut
    overflow = _recut(
        base,
        revision=current_cut.revision + 1,
        observed_at=base.cut.observed_at + timedelta(seconds=8),
        received_at=current_cut.received_at + timedelta(seconds=1),
        source="live/overflow",
    )
    with pytest.raises(ValueError, match="source cardinality exceeds"):
        store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(overflow)))
    assert store.cut == current_cut
    assert store.snapshot == disconnected
    assert store.experiment.recording is RecordingTruth.UNKNOWN

    forgotten_history_attack = _recut(
        base,
        revision=current_cut.revision + 1,
        observed_at=base.cut.observed_at - timedelta(seconds=1),
        received_at=current_cut.received_at + timedelta(seconds=1),
        source="live/0",
    )
    with pytest.raises(ValueError, match="live observed_at cannot move backwards"):
        store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(forgotten_history_attack)))
    assert store.cut == current_cut
    assert store.snapshot == disconnected

    recovered = _recut(
        base,
        revision=current_cut.revision + 1,
        observed_at=base.cut.observed_at + timedelta(seconds=1),
        received_at=current_cut.received_at + timedelta(seconds=1),
        source="live/0",
    )
    store.accept_snapshot(load_operator_snapshot(dump_operator_snapshot(recovered)))
    assert store.cut == recovered.cut
    assert store.experiment.recording is RecordingTruth.RECORDING


def test_new_store_is_explicit_new_gui_session_boundary() -> None:
    raw = _snapshot()
    first_session = apply_transport_freshness(
        raw,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    second_session = OperatorSnapshotStore()
    second_session.accept_snapshot(raw)

    assert first_session.experiment.recording is RecordingTruth.UNKNOWN
    assert second_session.experiment.recording is RecordingTruth.RECORDING


def test_connected_fresh_overlay_cannot_hide_raw_fault_authority() -> None:
    overlay = apply_transport_freshness(
        _snapshot(state=OperatorPresentationState.FAULT),
        connected=True,
        transport_age_s=1,
        stale_after_s=5,
    )

    assert {summary.state for summary in overlay.summaries()} == {OperatorPresentationState.FAULT}
    assert overlay.readiness.readiness is ReadinessTruth.BLOCKED
    assert overlay.experiment.recording is RecordingTruth.NOT_RECORDING
    assert overlay.experiment.recording_session_id is None
    assert all(summary.transport_age_s == 1 for summary in overlay.summaries())
    assert all(not summary.transport_reason_codes for summary in overlay.summaries())


def test_neutral_snapshot_has_no_wire_invisible_behavioral_fields() -> None:
    names = tuple(item.name for item in fields(OperatorSnapshot))

    assert names == (
        "cut",
        "readiness",
        "plant_health",
        "infrastructure",
        "attention",
        "experiment",
        "data_integrity",
        "cooldown_history",
        "support_bundle",
    )


def test_replace_derived_snapshot_cannot_carry_history_into_new_fault_cut() -> None:
    raw = _snapshot()
    degraded = apply_transport_freshness(
        raw,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    fault_raw = _snapshot(state=OperatorPresentationState.FAULT)
    newer_cut = replace(fault_raw.cut, revision=43)
    fault_summaries = tuple(replace(summary, cut=newer_cut) for summary in fault_raw.summaries())

    carried = replace(
        degraded.snapshot,
        cut=newer_cut,
        **{
            name: summary
            for name, summary in zip(
                (
                    "readiness",
                    "plant_health",
                    "infrastructure",
                    "attention",
                    "experiment",
                    "data_integrity",
                    "cooldown_history",
                    "support_bundle",
                ),
                fault_summaries,
                strict=True,
            )
        },
    )

    assert carried.cut.revision == 43
    assert {summary.state for summary in carried.summaries()} == {OperatorPresentationState.FAULT}
    authoritative = OperatorSnapshot(newer_cut, *fault_summaries)
    assert carried == authoritative
    assert hash(carried) == hash(authoritative)
    result = apply_transport_freshness(
        carried,
        connected=True,
        transport_age_s=8,
        stale_after_s=5,
    )
    assert {summary.state for summary in result.summaries()} == {OperatorPresentationState.FAULT}
    assert {item.state for item in result.plant_health.subsystems} == {OperatorPresentationState.FAULT}
    assert {item.state for item in result.infrastructure.nodes} == {OperatorPresentationState.FAULT}


def test_raw_snapshot_cache_round_trip_has_equal_hash_and_equal_overlay_result() -> None:
    raw = _snapshot()
    decoded = load_operator_snapshot(dump_operator_snapshot(raw))

    assert decoded == raw
    assert hash(decoded) == hash(raw)
    first = apply_transport_freshness(
        raw,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    second = apply_transport_freshness(
        decoded,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    assert first.snapshot == second.snapshot


def test_decoded_transport_presentation_cannot_be_reused_as_raw_authority() -> None:
    disconnected = apply_transport_freshness(
        _snapshot(),
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    decoded = load_operator_snapshot(dump_operator_snapshot(disconnected.snapshot))

    assert decoded == disconnected.snapshot
    assert hash(decoded) == hash(disconnected.snapshot)
    receiver = OperatorSnapshotStore()
    with pytest.raises(ValueError, match="cannot be accepted as raw authority"):
        receiver.accept_snapshot(decoded)


def test_same_cut_connected_fresh_clears_transport_cue_but_not_invalidated_authority() -> None:
    backend_reasons = tuple(f"backend_{index}" for index in range(4))
    snapshot = _snapshot()
    summaries = tuple(
        replace(summary, status=replace(summary.status, reason_codes=backend_reasons))
        for summary in snapshot.summaries()
    )
    snapshot = OperatorSnapshot(snapshot.cut, *summaries)
    disconnected = apply_transport_freshness(
        snapshot,
        connected=False,
        transport_age_s=8,
        stale_after_s=5,
    )
    recovered = apply_transport_freshness(
        disconnected,
        connected=True,
        transport_age_s=8,
        stale_after_s=10,
    )

    assert {summary.state for summary in recovered.summaries()} == {OperatorPresentationState.STALE}
    assert all(summary.transport_reason_codes == () for summary in recovered.summaries())
    assert all(summary.reason_codes == backend_reasons for summary in recovered.summaries())
    assert recovered.readiness.readiness is ReadinessTruth.UNKNOWN
    assert recovered.experiment.recording is RecordingTruth.UNKNOWN
    assert recovered.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert recovered.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert load_operator_snapshot(dump_operator_snapshot(recovered.snapshot)) == recovered.snapshot
    assert (
        apply_transport_freshness(
            recovered,
            connected=True,
            transport_age_s=8,
            stale_after_s=10,
        )
        == recovered
    )


def test_same_cut_transport_age_cannot_decrease() -> None:
    snapshot = apply_transport_freshness(_snapshot(), connected=True, transport_age_s=4, stale_after_s=5)

    with pytest.raises(ValueError, match="cannot decrease"):
        apply_transport_freshness(snapshot, connected=True, transport_age_s=3.999, stale_after_s=5)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("transport_age_s", 10**1_000),
        ("stale_after_s", 10**1_000),
        ("transport_age_s", True),
        ("stale_after_s", False),
        ("transport_age_s", float("nan")),
        ("stale_after_s", float("inf")),
        ("transport_age_s", float("-inf")),
        ("transport_age_s", -1),
        ("stale_after_s", 0),
    ],
)
def test_transport_numbers_fail_closed_with_stable_value_error(field_name: str, value: object) -> None:
    arguments = {"connected": True, "transport_age_s": 1, "stale_after_s": 5}
    arguments[field_name] = value

    with pytest.raises(ValueError, match=f"{field_name} must be"):
        apply_transport_freshness(_snapshot(), **arguments)


def test_transport_numbers_accept_exact_finite_boundaries() -> None:
    snapshot = _snapshot()
    zero_age = OperatorSnapshot(
        snapshot.cut,
        *(replace(summary, status=replace(summary.status, transport_age_s=0)) for summary in snapshot.summaries()),
    )
    assert apply_transport_freshness(
        zero_age,
        connected=True,
        transport_age_s=0,
        stale_after_s=float.fromhex("0x1.0p-1022"),
    )


def test_codec_live_and_replay_round_trip_is_strict_and_json_compatible() -> None:
    for mode in SnapshotMode:
        snapshot = _snapshot(mode=mode)
        envelope = encode_operator_snapshot(snapshot)
        wire = dump_operator_snapshot(snapshot)

        assert json.loads(json.dumps(envelope, allow_nan=False)) == envelope
        assert decode_operator_snapshot(envelope) == snapshot
        assert load_operator_snapshot(wire) == snapshot
        assert "datetime" not in wire
        assert snapshot.cut.observed_at.isoformat() not in wire
        assert not any(key.startswith("_") for key in envelope["snapshot"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(version=True),
        lambda value: value.update(version=1),
        lambda value: value["snapshot"]["cut"].update(extra="x"),
        lambda value: value["snapshot"]["cut"].update(mode="future"),
        lambda value: value["snapshot"]["cut"].update(revision=True),
        lambda value: value["snapshot"]["readiness"]["status"].update(source_age_s=float("nan")),
        lambda value: value["snapshot"]["readiness"].update(readiness=1),
        lambda value: value["snapshot"]["attention"].update(items={}),
        lambda value: value["snapshot"]["support_bundle"]["manifest"].update(created_at="yesterday"),
    ],
)
def test_codec_rejects_unknown_keys_wrong_types_nonfinite_and_invalid_enums(mutate) -> None:
    envelope = copy.deepcopy(encode_operator_snapshot(_snapshot()))
    mutate(envelope)

    with pytest.raises((TypeError, ValueError)):
        decode_operator_snapshot(envelope)


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: SummaryStatus(OperatorPresentationState.OK, -0.1, 0, (), "ok"),
        lambda: SummaryStatus(OperatorPresentationState.OK, 0, float("nan"), (), "ok"),
        lambda: SummaryStatus(OperatorPresentationState.OK, 0, 0, ("dup", "dup"), "ok"),
        lambda: SupportBundleEntry("x", 1, "not-a-sha"),
        lambda: CooldownSample(-1, 4),
        lambda: CooldownSample(10**1_000, 4),
    ],
)
def test_invalid_authority_metadata_fails_closed(constructor) -> None:
    with pytest.raises(ValueError):
        constructor()


def test_contract_has_no_command_or_control_surface() -> None:
    snapshot = _snapshot()
    public_names = {
        name
        for contract in (OperatorSnapshot, *SUMMARY_TYPES)
        for name in (*contract.__dict__, *(field.name for field in fields(contract)))
    }

    assert snapshot.authority_boundary == "observation_only"
    assert not any(
        term in name.lower()
        for name in public_names
        for term in ("command", "control", "start", "stop", "setpoint", "acknowledge")
    )
