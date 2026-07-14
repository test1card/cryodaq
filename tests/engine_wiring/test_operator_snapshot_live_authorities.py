from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager, OperatorExperimentSnapshot
from cryodaq.engine_wiring.experiment_recording_owner import (
    AcquisitionLifecycle,
    ExperimentOperation,
    ExperimentRecordingOwner,
    PersistenceLifecycle,
    RecordingFeedAuthority,
)
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
)
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    LiveExperimentAuthority,
    LiveIntegrityPersistenceAuthority,
    LiveRecordingExperimentAuthority,
    LiveSafetyReadinessAuthority,
)
from cryodaq.engine_wiring.persistence_authority_owner import (
    PersistenceAuthorityOwner,
    PersistenceOutcomeAuthority,
    PersistenceOwnerLifecycle,
)
from cryodaq.operator_snapshot import MAX_NONNEGATIVE_INT, AvailabilityTruth, RecordingTruth

NOW = datetime(2026, 7, 12, 5, 0, tzinfo=UTC)
CUT = CommonCut(1, f"cut-v1:1:{'a' * 64}", NOW)


@pytest.fixture()
def manager(tmp_path: Path) -> ExperimentManager:
    instruments = tmp_path / "instruments.yaml"
    instruments.write_text(yaml.safe_dump({"instruments": []}), encoding="utf-8")
    templates = tmp_path / "templates"
    templates.mkdir()
    return ExperimentManager(tmp_path, instruments, templates_dir=templates)


def test_cold_manager_exposes_initialized_detached_unknown_recording_cut(
    manager: ExperimentManager,
) -> None:
    snapshot = manager.snapshot_operator_experiment()
    assert snapshot == OperatorExperimentSnapshot(1, None, None, None)
    receipt = LiveExperimentAuthority(manager).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.recording is RecordingTruth.UNKNOWN
    assert receipt.recording_session_id is None


def test_active_experiment_identity_and_phase_are_cached_without_sampling_io(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = manager.start_experiment("Cooldown", "operator", template_id="custom")
    started = manager.snapshot_operator_experiment()
    assert started.experiment_id == experiment_id
    assert started.experiment_name == "Cooldown"
    assert started.phase is None

    manager.advance_phase("cooldown")
    phased = manager.snapshot_operator_experiment()
    assert phased.revision == started.revision + 1
    assert phased.phase == "cooldown"

    monkeypatch.setattr(
        manager,
        "_read_metadata_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sampling performed I/O")),
    )
    assert manager.snapshot_operator_experiment() is phased


def test_experiment_snapshot_has_no_mutable_metadata_paths_or_control(
    manager: ExperimentManager,
) -> None:
    snapshot = manager.snapshot_operator_experiment()
    assert tuple(snapshot.__slots__) == (
        "revision",
        "experiment_id",
        "experiment_name",
        "phase",
    )
    with pytest.raises((AttributeError, TypeError)):
        snapshot.phase = "measurement"  # type: ignore[misc]


def test_experiment_receipt_never_infers_recording_from_active_card(
    manager: ExperimentManager,
) -> None:
    manager.start_experiment("Cooldown", "operator", template_id="custom")
    receipt = LiveExperimentAuthority(manager).snapshot_for_cut(CUT)
    assert receipt.experiment_id is not None
    assert receipt.recording is RecordingTruth.UNKNOWN
    assert receipt.recording_session_id is None


def test_experiment_cut_tracks_in_memory_lifecycle_when_state_write_fails(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager.start_experiment("Cooldown", "operator", template_id="custom")
    info = manager.active_experiment
    assert info is not None

    monkeypatch.setattr(
        manager,
        "_write_state",
        lambda: (_ for _ in ()).throw(OSError("state write failed")),
    )
    with pytest.raises(OSError, match="state write failed"):
        manager._clear_active()
    cleared = manager.snapshot_operator_experiment()
    assert manager.active_experiment is None
    assert cleared.experiment_id is None

    with pytest.raises(OSError, match="state write failed"):
        manager._set_active(info)
    restored = manager.snapshot_operator_experiment()
    assert manager.active_experiment is info
    assert restored.experiment_id == info.experiment_id
    assert restored.revision == cleared.revision + 1


def test_experiment_revision_regression_fails_closed() -> None:
    class Owner:
        snapshot = OperatorExperimentSnapshot(2, None, None, None)

        def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
            return self.snapshot

    owner = Owner()
    authority = LiveExperimentAuthority(owner)
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.AVAILABLE
    owner.snapshot = OperatorExperimentSnapshot(1, None, None, None)
    rejected = authority.snapshot_for_cut(CUT)
    assert rejected.availability is AuthorityAvailability.UNAVAILABLE
    assert rejected.unavailable_reason == "experiment_identity_revision_unavailable"


def test_experiment_same_revision_cannot_equivocate_identity() -> None:
    class Owner:
        snapshot = OperatorExperimentSnapshot(7, "exp-a", "A", None)

        def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
            return self.snapshot

    owner = Owner()
    authority = LiveExperimentAuthority(owner)
    first = authority.snapshot_for_cut(CUT)
    repeated = authority.snapshot_for_cut(CUT)
    assert first.availability is AuthorityAvailability.AVAILABLE
    assert repeated.token == first.token

    owner.snapshot = OperatorExperimentSnapshot(7, "exp-b", "B", "cooldown")
    equivocation = authority.snapshot_for_cut(CUT)
    assert equivocation.availability is AuthorityAvailability.UNAVAILABLE
    assert equivocation.unavailable_reason == "experiment_identity_revision_unavailable"


@pytest.mark.parametrize("bad_revision", [None, "1", True, 0, -1])
def test_invalid_experiment_revision_is_typed_unavailable(bad_revision: object) -> None:
    class Owner:
        def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
            return OperatorExperimentSnapshot(bad_revision, None, None, None)  # type: ignore[arg-type]

    receipt = LiveExperimentAuthority(Owner()).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE


def test_wrong_owner_snapshot_type_fails_closed_without_alias_inspection() -> None:
    class Owner:
        def snapshot_operator_experiment(self) -> object:
            return {"recording": "recording", "recording_session_id": "forged"}

    receipt = LiveExperimentAuthority(Owner()).snapshot_for_cut(CUT)  # type: ignore[arg-type]
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.recording is RecordingTruth.UNKNOWN


def test_contract_invalid_experiment_identity_fails_closed() -> None:
    class Owner:
        def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
            return OperatorExperimentSnapshot(1, "exp-1", " hostile ", None)

    receipt = LiveExperimentAuthority(Owner()).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.unavailable_reason == "experiment_identity_cut_unavailable"


def test_non_utf8_experiment_identity_is_typed_unavailable() -> None:
    class Owner:
        def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot:
            return OperatorExperimentSnapshot(1, "exp-1", "\ud800", None)

    receipt = LiveExperimentAuthority(Owner()).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.unavailable_reason == "experiment_identity_cut_unavailable"


@pytest.mark.parametrize(
    ("authority", "reason"),
    [
        (
            LiveSafetyReadinessAuthority(object()),
            "safety_verified_off_cut_unavailable",
        ),
    ],
)
def test_unproved_mandatory_owner_never_becomes_available(
    authority: object,
    reason: str,
) -> None:
    receipt = authority.snapshot_for_cut(CUT)  # type: ignore[attr-defined]
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.revision == 0
    assert receipt.unavailable_reason == reason


def test_integrity_does_not_treat_broker_delivery_stats_as_persistence_truth() -> None:
    class ForgedOwner:
        stats = {
            "zmq_publisher": {"queued": 0, "dropped": 0},
            "_total_published": {"count": 999},
        }
        is_disk_full = False

    with pytest.raises(TypeError, match="exact PersistenceAuthorityOwner"):
        LiveIntegrityPersistenceAuthority(ForgedOwner())  # type: ignore[arg-type]


def _recording_owner() -> tuple[ExperimentRecordingOwner, RecordingFeedAuthority]:
    authority = RecordingFeedAuthority("recording-feed", b"r" * 32)
    return ExperimentRecordingOwner("recording-owner", authority.generation_id, authority), authority


def _initialize_recording_owner(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    owner.feed_experiment(
        authority.experiment(
            1,
            "operation-1",
            ExperimentOperation.ACTIVE,
            "experiment-1",
            "Cooldown",
            "cooldown",
        )
    )
    owner.feed_acquisition(authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acquisition-1"))
    owner.feed_persistence(authority.persistence(1, PersistenceLifecycle.LOSSLESS, "persistence-1"))


def _persistence_owner() -> tuple[PersistenceAuthorityOwner, PersistenceOutcomeAuthority]:
    authority = PersistenceOutcomeAuthority("persistence-feed", b"p" * 32)
    return PersistenceAuthorityOwner("persistence-owner", authority.generation_id, authority), authority


def test_live_owner_projections_require_exact_owner_types() -> None:
    with pytest.raises(TypeError, match="exact ExperimentRecordingOwner"):
        LiveRecordingExperimentAuthority(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact PersistenceAuthorityOwner"):
        LiveIntegrityPersistenceAuthority(object())  # type: ignore[arg-type]


def test_recording_projection_stays_unavailable_until_all_three_feeds_exist() -> None:
    owner, authority = _recording_owner()
    adapter = LiveRecordingExperimentAuthority(owner)
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE

    owner.feed_experiment(
        authority.experiment(
            1,
            "operation-1",
            ExperimentOperation.ACTIVE,
            "experiment-1",
            "Cooldown",
        )
    )
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE
    owner.feed_acquisition(authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acquisition-1"))
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE

    owner.feed_persistence(authority.persistence(1, PersistenceLifecycle.LOSSLESS, "persistence-1"))
    receipt = adapter.snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.recording is RecordingTruth.NOT_RECORDING
    assert receipt.experiment_id == "experiment-1"


def test_recording_projection_publishes_only_owner_issued_recording_session() -> None:
    owner, authority = _recording_owner()
    _initialize_recording_owner(owner, authority)
    assert owner.begin_recording_epoch() is True

    receipt = LiveRecordingExperimentAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.recording is RecordingTruth.RECORDING
    assert receipt.recording_session_id == owner.snapshot().recording_session_id
    assert receipt.experiment_id == "experiment-1"
    assert receipt.phase == "cooldown"


def test_recording_projection_accepts_independent_noncontiguous_feed_revisions() -> None:
    owner, authority = _recording_owner()
    owner.feed_experiment(
        authority.experiment(
            100,
            "operation-100",
            ExperimentOperation.ACTIVE,
            "experiment-1",
            "Cooldown",
        )
    )
    owner.feed_acquisition(authority.acquisition(200, AcquisitionLifecycle.RUNNING, "acquisition-1"))
    owner.feed_persistence(authority.persistence(300, PersistenceLifecycle.LOSSLESS, "persistence-1"))
    assert owner.snapshot().revision == 3

    receipt = LiveRecordingExperimentAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.revision == 3
    assert receipt.recording is RecordingTruth.NOT_RECORDING


def test_recording_projection_remains_available_but_not_recording_after_proven_loss() -> None:
    owner, authority = _recording_owner()
    _initialize_recording_owner(owner, authority)
    assert owner.begin_recording_epoch() is True
    adapter = LiveRecordingExperimentAuthority(owner)
    assert adapter.snapshot_for_cut(CUT).recording is RecordingTruth.RECORDING

    owner.feed_persistence(authority.persistence(2, PersistenceLifecycle.LOSS))
    receipt = adapter.snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.recording is RecordingTruth.NOT_RECORDING
    assert receipt.recording_session_id is None


def test_recording_projection_rejects_session_not_bound_to_owner_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, authority = _recording_owner()
    _initialize_recording_owner(owner, authority)
    assert owner.begin_recording_epoch() is True
    monkeypatch.setattr(
        owner,
        "_ExperimentRecordingOwner__snapshot",
        replace(owner.snapshot(), recording_session_id=f"recording-v1:{'0' * 32}:1"),
    )
    receipt = LiveRecordingExperimentAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.recording is RecordingTruth.UNKNOWN


def test_recording_projection_rejects_regression_and_same_revision_equivocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, authority = _recording_owner()
    _initialize_recording_owner(owner, authority)
    adapter = LiveRecordingExperimentAuthority(owner)
    accepted = adapter.snapshot_for_cut(CUT)
    assert adapter.snapshot_for_cut(CUT).token == accepted.token
    snapshot = owner.snapshot()

    monkeypatch.setattr(
        owner,
        "_ExperimentRecordingOwner__snapshot",
        replace(snapshot, phase="measurement"),
    )
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE
    monkeypatch.setattr(
        owner,
        "_ExperimentRecordingOwner__snapshot",
        replace(snapshot, revision=snapshot.revision - 1),
    )
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE


@pytest.mark.parametrize(
    "mutation",
    [
        {"revision": True},
        {"experiment_revision": 0},
        {"recording": "recording"},
        {"recording_session_id": "forged-session"},
        {"owner_id": " hostile "},
        {"owner_id": "x" * 300},
        {"reason": "bad\nreason"},
    ],
)
def test_recording_projection_rejects_corrupt_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
) -> None:
    owner, authority = _recording_owner()
    _initialize_recording_owner(owner, authority)
    monkeypatch.setattr(
        owner,
        "_ExperimentRecordingOwner__snapshot",
        replace(owner.snapshot(), **mutation),
    )
    receipt = LiveRecordingExperimentAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.recording is RecordingTruth.UNKNOWN


def test_persistence_projection_is_cold_until_lifecycle_receipt_then_preserves_unknown_storage() -> None:
    owner, authority = _persistence_owner()
    adapter = LiveIntegrityPersistenceAuthority(owner)
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE

    owner.feed(authority.lifecycle(1, "epoch-1", PersistenceOwnerLifecycle.STARTED))
    receipt = adapter.snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.storage is AvailabilityTruth.UNKNOWN
    assert receipt.persisted_revision == 0
    assert receipt.pending_records == 0
    assert receipt.dropped_records == 0


def test_persistence_projection_maps_owner_counters_and_storage_without_inference() -> None:
    owner, authority = _persistence_owner()
    owner.feed(authority.lifecycle(1, "epoch-1", PersistenceOwnerLifecycle.STARTED))
    owner.feed(authority.durable_append(2, "epoch-1", "append-1", "sqlite-1", 3))
    owner.feed(
        authority.materialized(
            3,
            "epoch-1",
            "append-1",
            "sqlite-1",
            7,
            3,
            append_revision=2,
        )
    )
    receipt = LiveIntegrityPersistenceAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.storage is AvailabilityTruth.AVAILABLE
    assert receipt.persisted_revision == 7
    assert receipt.pending_records == 3
    assert receipt.dropped_records == 0


def test_storage_unavailable_is_available_authority_evidence() -> None:
    owner, authority = _persistence_owner()
    owner.feed(authority.lifecycle(1, "epoch-1", PersistenceOwnerLifecycle.STARTED))
    owner.feed(authority.lifecycle(2, "epoch-1", PersistenceOwnerLifecycle.STOPPED))
    receipt = LiveIntegrityPersistenceAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.storage is AvailabilityTruth.UNAVAILABLE
    assert receipt.persisted_revision == 0
    assert receipt.pending_records == 0


def test_persistence_projection_rejects_regression_and_same_revision_equivocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, authority = _persistence_owner()
    owner.feed(authority.lifecycle(1, "epoch-1", PersistenceOwnerLifecycle.STARTED))
    adapter = LiveIntegrityPersistenceAuthority(owner)
    accepted = adapter.snapshot_for_cut(CUT)
    assert adapter.snapshot_for_cut(CUT).token == accepted.token
    snapshot = owner.snapshot()

    monkeypatch.setattr(
        owner,
        "_PersistenceAuthorityOwner__snapshot",
        replace(snapshot, storage=AvailabilityTruth.UNAVAILABLE),
    )
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE
    monkeypatch.setattr(
        owner,
        "_PersistenceAuthorityOwner__snapshot",
        replace(snapshot, revision=0),
    )
    assert adapter.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE


@pytest.mark.parametrize(
    "mutation",
    [
        {"revision": True},
        {"receipt_revision": 0},
        {"pending_count": -1},
        {"pending_count": MAX_NONNEGATIVE_INT + 1},
        {"dropped_or_rejected_count": True},
        {"committed_materialization_revision": -1},
        {"archive_revision": 0},
        {"storage": "available"},
        {"recording_epoch_id": " hostile "},
        {"recording_epoch_id": "x" * 300},
        {"reason": "bad\nreason"},
    ],
)
def test_persistence_projection_rejects_corrupt_counts_and_types(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
) -> None:
    owner, authority = _persistence_owner()
    owner.feed(authority.lifecycle(1, "epoch-1", PersistenceOwnerLifecycle.STARTED))
    monkeypatch.setattr(
        owner,
        "_PersistenceAuthorityOwner__snapshot",
        replace(owner.snapshot(), **mutation),
    )
    receipt = LiveIntegrityPersistenceAuthority(owner).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.storage is AvailabilityTruth.UNKNOWN
    assert receipt.persisted_revision is None


def test_live_authority_module_has_no_gui_replay_driver_or_command_imports() -> None:
    source = inspect.getsource(inspect.getmodule(LiveExperimentAuthority))
    for forbidden in (
        "cryodaq.gui",
        "cryodaq.replay_engine",
        "cryodaq.drivers",
        "request_run",
        "request_stop",
        "emergency_off",
    ):
        assert forbidden not in source
