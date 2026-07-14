from __future__ import annotations

import inspect
import pickle
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
from itertools import permutations

import pytest

from cryodaq.engine_wiring.experiment_recording_owner import (
    AcquisitionLifecycle,
    AcquisitionLifecycleReceipt,
    ExperimentOperation,
    ExperimentOperationOutcome,
    ExperimentRecordingOwner,
    PersistenceLifecycle,
    RecordingFeedAuthority,
    RecordingFeedKind,
    RecordingWorkerOutcomeEnvelope,
)
from cryodaq.operator_snapshot import RecordingTruth

KEY = b"recording-feed-test-key-32-bytes!!"


def _different_generation(generation_id: str) -> str:
    prefix = "0" if generation_id[0] != "0" else "1"
    return prefix + generation_id[1:]


@pytest.fixture()
def authority() -> RecordingFeedAuthority:
    return RecordingFeedAuthority("engine-feed", KEY)


@pytest.fixture()
def owner(authority: RecordingFeedAuthority) -> ExperimentRecordingOwner:
    return ExperimentRecordingOwner("experiment-owner", authority.generation_id, authority)


def _active(
    authority: RecordingFeedAuthority, revision: int = 1, experiment_id: str = "exp-1"
) -> ExperimentOperationOutcome:
    return authority.experiment(
        revision,
        f"operation-{revision}",
        ExperimentOperation.ACTIVE,
        experiment_id,
        f"Experiment {experiment_id}",
        "cooldown",
    )


def _ready(owner: ExperimentRecordingOwner, authority: RecordingFeedAuthority) -> None:
    owner.feed_experiment(_active(authority))
    owner.feed_acquisition(authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acq-1"))
    owner.feed_persistence(authority.persistence(1, PersistenceLifecycle.LOSSLESS, "store-1"))


def test_active_experiment_alone_never_means_recording(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    owner.feed_experiment(_active(authority))
    snapshot = owner.snapshot()
    assert snapshot.experiment_id == "exp-1"
    assert snapshot.recording is RecordingTruth.NOT_RECORDING
    assert snapshot.recording_session_id is None
    assert owner.begin_recording_epoch() is False


def test_cold_start_is_honestly_inactive_and_unavailable_is_explicit() -> None:
    authority = RecordingFeedAuthority("cold-feed", KEY)
    owner = ExperimentRecordingOwner("cold-owner", authority.generation_id, authority)
    cold = owner.snapshot()
    assert cold.experiment_operation is ExperimentOperation.INACTIVE
    assert cold.experiment_id is None
    assert cold.recording is RecordingTruth.NOT_RECORDING

    owner.feed_experiment(authority.experiment(1, "operation-unavailable", ExperimentOperation.UNAVAILABLE))
    unavailable = owner.snapshot()
    assert unavailable.experiment_operation is ExperimentOperation.UNAVAILABLE
    assert unavailable.experiment_id is None
    assert unavailable.recording is RecordingTruth.NOT_RECORDING
    assert unavailable.reason == "experiment_unavailable"

    owner.feed_experiment(_active(authority, 2))
    assert owner.snapshot().experiment_operation is ExperimentOperation.ACTIVE


@pytest.mark.parametrize("operation", [ExperimentOperation.INACTIVE, ExperimentOperation.UNAVAILABLE])
def test_no_active_or_unavailable_ends_recording_and_recovery_never_auto_resumes(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
    operation: ExperimentOperation,
) -> None:
    _ready(owner, authority)
    assert owner.begin_recording_epoch() is True
    owner.feed_experiment(authority.experiment(2, "operation-ended", operation))
    snapshot = owner.snapshot()
    assert snapshot.experiment_operation is operation
    assert snapshot.experiment_id is None
    assert snapshot.recording is RecordingTruth.NOT_RECORDING
    assert snapshot.reason == f"experiment_{operation.value}"

    owner.feed_experiment(_active(authority, 3))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
    assert owner.begin_recording_epoch() is True


def test_recording_requires_explicit_epoch_after_all_current_receipts(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    _ready(owner, authority)
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
    assert owner.begin_recording_epoch() is True
    snapshot = owner.snapshot()
    assert snapshot.recording is RecordingTruth.RECORDING
    assert snapshot.recording_session_id is not None
    assert len(snapshot.recording_session_id.encode()) <= 128
    assert owner.begin_recording_epoch() is True
    assert owner.snapshot() is snapshot


@pytest.mark.parametrize("state", [PersistenceLifecycle.LOSS, PersistenceLifecycle.UNAVAILABLE])
def test_persistence_loss_ends_epoch_and_recovery_never_auto_resumes(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
    state: PersistenceLifecycle,
) -> None:
    _ready(owner, authority)
    owner.begin_recording_epoch()
    first_session = owner.snapshot().recording_session_id
    owner.feed_persistence(authority.persistence(2, state))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING

    owner.feed_persistence(authority.persistence(3, PersistenceLifecycle.LOSSLESS, "store-2"))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
    assert owner.snapshot().recording_session_id is None
    assert owner.begin_recording_epoch() is True
    assert owner.snapshot().recording_session_id != first_session


@pytest.mark.parametrize("state", [AcquisitionLifecycle.STOPPED, AcquisitionLifecycle.UNAVAILABLE])
def test_acquisition_stop_or_unavailable_ends_epoch_without_latent_rearm(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
    state: AcquisitionLifecycle,
) -> None:
    _ready(owner, authority)
    owner.begin_recording_epoch()
    owner.feed_acquisition(authority.acquisition(2, state))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
    owner.feed_acquisition(authority.acquisition(3, AcquisitionLifecycle.RUNNING, "acq-2"))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING


def test_experiment_replacement_and_finalize_end_epoch(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    _ready(owner, authority)
    owner.begin_recording_epoch()
    owner.feed_experiment(_active(authority, 2, "exp-2"))
    replaced = owner.snapshot()
    assert replaced.experiment_id == "exp-2"
    assert replaced.recording is RecordingTruth.NOT_RECORDING

    assert owner.begin_recording_epoch() is True
    owner.feed_experiment(authority.experiment(3, "finalize-3", ExperimentOperation.FINALIZED, "exp-2"))
    finalized = owner.snapshot()
    assert finalized.experiment_operation is ExperimentOperation.FINALIZED
    assert finalized.experiment_id is None
    assert finalized.recording is RecordingTruth.NOT_RECORDING


def test_mismatched_finalization_is_rejected_without_partial_mutation(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    owner.feed_experiment(_active(authority))
    before = owner.snapshot()
    with pytest.raises(ValueError, match="requires the exact active"):
        owner.feed_experiment(authority.experiment(2, "finalize-other", ExperimentOperation.FINALIZED, "other"))
    assert owner.snapshot() is before
    owner.feed_experiment(_active(authority, 2, "exp-2"))
    assert owner.snapshot().experiment_id == "exp-2"


@pytest.mark.parametrize("prior", ["cold", "inactive", "unavailable", "finalized"])
def test_finalization_requires_exact_current_active_state(prior: str) -> None:
    authority = RecordingFeedAuthority(f"{prior}-feed", KEY)
    owner = ExperimentRecordingOwner(f"{prior}-owner", authority.generation_id, authority)
    revision = 1
    if prior in {"inactive", "unavailable"}:
        operation = ExperimentOperation.INACTIVE if prior == "inactive" else ExperimentOperation.UNAVAILABLE
        owner.feed_experiment(authority.experiment(revision, f"{prior}-state", operation))
        revision += 1
    elif prior == "finalized":
        owner.feed_experiment(_active(authority, revision))
        revision += 1
        owner.feed_experiment(
            authority.experiment(revision, "finalize-current", ExperimentOperation.FINALIZED, "exp-1")
        )
        revision += 1

    before = owner.snapshot()
    with pytest.raises(ValueError, match="requires the exact active"):
        owner.feed_experiment(authority.experiment(revision, "stale-finalize", ExperimentOperation.FINALIZED, "exp-1"))
    assert owner.snapshot() is before
    owner.feed_experiment(_active(authority, revision))
    assert owner.snapshot().experiment_operation is ExperimentOperation.ACTIVE


def test_running_or_lossless_epoch_replacement_ends_old_session(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    _ready(owner, authority)
    owner.begin_recording_epoch()
    owner.feed_acquisition(authority.acquisition(2, AcquisitionLifecycle.RUNNING, "acq-new"))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
    owner.begin_recording_epoch()
    owner.feed_persistence(authority.persistence(2, PersistenceLifecycle.LOSSLESS, "store-new"))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING


def test_all_same_loop_feed_orderings_remain_dark_until_explicit_begin() -> None:
    for domains in permutations(("experiment", "acquisition", "persistence")):
        authority = RecordingFeedAuthority("ordered-feed", KEY)
        feeds = {
            "experiment": _active(authority),
            "acquisition": authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acq-1"),
            "persistence": authority.persistence(1, PersistenceLifecycle.LOSSLESS, "store-1"),
        }
        owner = ExperimentRecordingOwner("ordered-owner", authority.generation_id, authority)
        for domain in domains:
            outcome = feeds[domain]
            getattr(owner, f"feed_{domain}")(outcome)
            assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING
        assert owner.begin_recording_epoch() is True


def test_revisions_are_monotonic_idempotent_and_cannot_equivocate(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    first = _active(authority, 2)
    owner.feed_experiment(first)
    accepted = owner.snapshot()
    owner.feed_experiment(first)
    assert owner.snapshot() is accepted
    with pytest.raises(ValueError, match="equivocation"):
        owner.feed_experiment(_active(authority, 2, "exp-other"))
    assert owner.snapshot() is accepted
    with pytest.raises(ValueError, match="regression"):
        owner.feed_experiment(_active(authority, 1))


@pytest.mark.parametrize("domain", ["experiment", "acquisition", "persistence"])
def test_cross_authority_and_forged_provenance_are_rejected_without_mutation(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
    domain: str,
) -> None:
    foreign = RecordingFeedAuthority("foreign", b"foreign-recording-key-32-bytes!!!")
    outcome = {
        "experiment": _active(foreign),
        "acquisition": foreign.acquisition(1, AcquisitionLifecycle.RUNNING, "acq"),
        "persistence": foreign.persistence(1, PersistenceLifecycle.LOSSLESS, "store"),
    }[domain]
    before = owner.snapshot()
    with pytest.raises(ValueError, match="provenance"):
        getattr(owner, f"feed_{domain}")(outcome)
    assert owner.snapshot() is before

    forged = replace(outcome, issuer_id=authority.issuer_id)
    with pytest.raises(ValueError, match="provenance"):
        getattr(owner, f"feed_{domain}")(forged)
    assert owner.snapshot() is before


def test_receipt_subclasses_and_alias_objects_are_rejected(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    class AcquisitionSubclass(AcquisitionLifecycleReceipt):
        pass

    genuine = authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acq")
    subclass = AcquisitionSubclass(
        genuine.issuer_id,
        genuine.generation_id,
        genuine.revision,
        genuine.state,
        genuine.acquisition_epoch_id,
        genuine.provenance,
    )
    with pytest.raises(ValueError, match="provenance"):
        owner.feed_acquisition(subclass)
    with pytest.raises(ValueError, match="provenance"):
        owner.feed_persistence({"state": "lossless"})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        {"revision": True},
        {"operation_id": " hostile "},
        {"operation": "active"},
        {"experiment_id": ""},
        {"experiment_name": "\ud800"},
        {"phase": "bad\nphase"},
        {"provenance": "feed-v1:" + "G" * 64},
    ],
)
def test_experiment_outcome_mutation_matrix_rejects_non_contract_values(
    authority: RecordingFeedAuthority,
    mutation: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError, UnicodeError)):
        replace(_active(authority), **mutation)


@pytest.mark.parametrize("operation", [ExperimentOperation.INACTIVE, ExperimentOperation.UNAVAILABLE])
def test_identity_free_operations_reject_fabricated_identity(
    authority: RecordingFeedAuthority,
    operation: ExperimentOperation,
) -> None:
    with pytest.raises(ValueError, match="carries no experiment identity"):
        authority.experiment(1, "operation", operation, "fabricated")


@pytest.mark.parametrize(
    ("factory", "mutation"),
    [
        ("acquisition", {"state": "running"}),
        ("acquisition", {"acquisition_epoch_id": None}),
        ("acquisition", {"revision": 0}),
        ("persistence", {"state": "lossless"}),
        ("persistence", {"persistence_epoch_id": None}),
        ("persistence", {"revision": -1}),
    ],
)
def test_lifecycle_receipt_mutation_matrix_rejects_non_contract_values(
    authority: RecordingFeedAuthority,
    factory: str,
    mutation: dict[str, object],
) -> None:
    receipt = (
        authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acq")
        if factory == "acquisition"
        else authority.persistence(1, PersistenceLifecycle.LOSSLESS, "store")
    )
    with pytest.raises((TypeError, ValueError)):
        replace(receipt, **mutation)


def test_snapshot_and_outcomes_are_detached_immutable_values(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    outcome = _active(authority)
    owner.feed_experiment(outcome)
    snapshot = owner.snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.phase = "measurement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        outcome.phase = "measurement"  # type: ignore[misc]
    assert owner.snapshot() is snapshot
    assert owner.snapshot().phase == "cooldown"


def test_future_worker_envelope_is_typed_but_does_not_schedule_work(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    outcome = _active(authority)
    envelope = RecordingWorkerOutcomeEnvelope(1, RecordingFeedKind.EXPERIMENT, outcome)
    owner.feed_worker_outcome(envelope)
    assert owner.snapshot().experiment_id == "exp-1"
    with pytest.raises(TypeError, match="requires"):
        RecordingWorkerOutcomeEnvelope(2, RecordingFeedKind.PERSISTENCE, outcome)


def test_contract_is_pure_constant_time_cached_and_has_no_control_authority() -> None:
    import cryodaq.engine_wiring.experiment_recording_owner as module

    source = inspect.getsource(module)
    forbidden = (
        "ExperimentManager",
        "import asyncio",
        ".to_thread(",
        "threading",
        "multiprocessing",
        "pathlib",
        "sqlite",
        "open(",
        "request_run",
        "request_stop",
        "emergency_off",
        "cryodaq.gui",
        "cryodaq.storage",
    )
    for name in forbidden:
        assert name not in source
    assert ExperimentRecordingOwner.grants_control_authority is False
    assert not inspect.iscoroutinefunction(ExperimentRecordingOwner.snapshot)
    assert not inspect.iscoroutinefunction(ExperimentRecordingOwner.feed_worker_outcome)


def test_exact_types_do_not_authorize_by_truthiness() -> None:
    with pytest.raises(ValueError):
        RecordingFeedAuthority("feed", b"short")
    with pytest.raises(TypeError):
        ExperimentRecordingOwner("owner", "0" * 32, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RecordingWorkerOutcomeEnvelope(0, RecordingFeedKind.EXPERIMENT, object())  # type: ignore[arg-type]


def test_session_ids_are_unique_across_epochs_and_owner_ids(
    authority: RecordingFeedAuthority,
) -> None:
    first = ExperimentRecordingOwner("owner-a", authority.generation_id, authority)
    _ready(first, authority)
    first.begin_recording_epoch()
    first_id = first.snapshot().recording_session_id
    first.feed_persistence(authority.persistence(2, PersistenceLifecycle.LOSS))
    first.feed_persistence(authority.persistence(3, PersistenceLifecycle.LOSSLESS, "store-2"))
    first.begin_recording_epoch()

    second_authority = RecordingFeedAuthority("second-feed", b"second-recording-key-32-bytes!!!")
    second = ExperimentRecordingOwner("owner-b", second_authority.generation_id, second_authority)
    _ready(second, second_authority)
    second.begin_recording_epoch()
    assert len({first_id, first.snapshot().recording_session_id, second.snapshot().recording_session_id}) == 3


def test_receipt_payload_does_not_retain_caller_mutable_objects(
    authority: RecordingFeedAuthority,
) -> None:
    mutable = bytearray(KEY)
    copied = RecordingFeedAuthority("copy-feed", bytes(mutable))
    receipt = copied.persistence(1, PersistenceLifecycle.LOSSLESS, "store")
    mutable[:] = b"x" * len(mutable)
    assert copied.verifies(receipt)
    assert authority.issuer_id == "engine-feed"


def test_recreated_same_owner_rejects_prior_generation_and_never_collides_sessions() -> None:
    old_authority = RecordingFeedAuthority("feed", KEY)
    old_owner = ExperimentRecordingOwner("same-owner", old_authority.generation_id, old_authority)
    old_active = _active(old_authority)
    old_acquisition = old_authority.acquisition(1, AcquisitionLifecycle.RUNNING, "acq-1")
    old_persistence = old_authority.persistence(1, PersistenceLifecycle.LOSSLESS, "store-1")
    old_owner.feed_experiment(old_active)
    old_owner.feed_acquisition(old_acquisition)
    old_owner.feed_persistence(old_persistence)
    assert old_owner.begin_recording_epoch() is True
    old_session = old_owner.snapshot().recording_session_id
    old_owner.feed_persistence(old_authority.persistence(2, PersistenceLifecycle.LOSS))

    new_authority = RecordingFeedAuthority("feed", KEY)
    new_owner = ExperimentRecordingOwner("same-owner", new_authority.generation_id, new_authority)
    initial = new_owner.snapshot()
    for method, stale in (
        (new_owner.feed_experiment, old_active),
        (new_owner.feed_acquisition, old_acquisition),
        (new_owner.feed_persistence, old_persistence),
    ):
        with pytest.raises(ValueError, match="provenance"):
            method(stale)  # type: ignore[arg-type]
        assert new_owner.snapshot() is initial

    _ready(new_owner, new_authority)
    assert new_owner.begin_recording_epoch() is True
    assert new_owner.snapshot().recording_session_id != old_session
    assert new_authority.generation_id in (new_owner.snapshot().recording_session_id or "")


def test_generation_mutation_cannot_rebind_a_signed_receipt(
    owner: ExperimentRecordingOwner,
    authority: RecordingFeedAuthority,
) -> None:
    receipt = _active(authority)
    rebound = replace(receipt, generation_id=_different_generation(authority.generation_id))
    with pytest.raises(ValueError, match="provenance"):
        owner.feed_experiment(rebound)
    assert owner.snapshot().revision == 0
    for invalid in ("", "A" * 32, "1" * 31, "1" * 33, True):
        with pytest.raises(ValueError, match="generation_id"):
            replace(receipt, generation_id=invalid)


def test_owner_requires_exact_matching_generation(authority: RecordingFeedAuthority) -> None:
    with pytest.raises(ValueError, match="exactly match"):
        ExperimentRecordingOwner("owner", _different_generation(authority.generation_id), authority)
    with pytest.raises(ValueError, match="generation_id"):
        ExperimentRecordingOwner("owner", "not-a-generation", authority)


def test_one_generation_cannot_be_reused_for_a_second_owner_lifetime() -> None:
    authority = RecordingFeedAuthority("feed", KEY)
    ExperimentRecordingOwner("owner", authority.generation_id, authority)
    with pytest.raises(RuntimeError, match="already claimed"):
        ExperimentRecordingOwner("owner", authority.generation_id, authority)


def test_production_authorities_receive_fresh_secure_generations() -> None:
    first = RecordingFeedAuthority("feed", KEY)
    second = RecordingFeedAuthority("feed", KEY)
    assert first.generation_id != second.generation_id
    assert len(first.generation_id) == len(second.generation_id) == 32


def test_runtime_api_has_no_deterministic_generation_or_cloning_seam() -> None:
    signature = inspect.signature(RecordingFeedAuthority)
    assert tuple(signature.parameters) == ("issuer_id", "provenance_key")
    assert not hasattr(RecordingFeedAuthority, "_for_test_generation")
    source = inspect.getsource(RecordingFeedAuthority)
    assert "object.__new__" not in source
    assert "__init_values" not in source
    assert not any(isinstance(value, classmethod) for value in RecordingFeedAuthority.__dict__.values())


def test_authority_rejects_copy_pickle_and_inherited_process_use(
    authority: RecordingFeedAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = ExperimentRecordingOwner("process-owner", authority.generation_id, authority)
    for clone in (copy, deepcopy, pickle.dumps):
        with pytest.raises(TypeError, match="cannot be"):
            clone(authority)

    import cryodaq.engine_wiring.experiment_recording_owner as module

    creator_pid = module.os.getpid()
    monkeypatch.setattr(module.os, "getpid", lambda: creator_pid + 1)
    with pytest.raises(RuntimeError, match="process boundary"):
        authority.experiment(1, "operation-1", ExperimentOperation.ACTIVE, "exp-1", "Experiment")
    with pytest.raises(RuntimeError, match="process boundary"):
        authority.verifies(object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="process boundary"):
        owner.snapshot()
    with pytest.raises(RuntimeError, match="process boundary"):
        owner.begin_recording_epoch()


def test_entropy_repetition_cannot_clone_a_live_generation(
    authority: RecordingFeedAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.engine_wiring.experiment_recording_owner as module

    monkeypatch.setattr(module.secrets, "token_hex", lambda _size: authority.generation_id)
    with pytest.raises(RuntimeError, match="unique recording-owner generation"):
        RecordingFeedAuthority("clone-attempt", KEY)


def _assert_owner_not_cloneable(owner: ExperimentRecordingOwner) -> None:
    before = owner.snapshot()
    for clone in (copy, deepcopy, pickle.dumps):
        with pytest.raises(TypeError, match="cannot be"):
            clone(owner)
        assert owner.snapshot() is before
    with pytest.raises(TypeError, match="no serializable state"):
        owner.__getstate__()
    with pytest.raises(TypeError, match="cannot restore"):
        owner.__setstate__({})
    assert owner.snapshot() is before


def test_owner_rejects_copy_and_pickle_when_cold_and_remains_valid() -> None:
    authority = RecordingFeedAuthority("cold-feed", KEY)
    owner = ExperimentRecordingOwner("cold-owner", authority.generation_id, authority)
    _assert_owner_not_cloneable(owner)
    _ready(owner, authority)
    assert owner.begin_recording_epoch() is True


def test_owner_rejects_copy_and_pickle_when_ready_and_remains_valid() -> None:
    authority = RecordingFeedAuthority("ready-feed", KEY)
    owner = ExperimentRecordingOwner("ready-owner", authority.generation_id, authority)
    _ready(owner, authority)
    _assert_owner_not_cloneable(owner)
    assert owner.begin_recording_epoch() is True


def test_owner_rejects_copy_and_pickle_while_recording_and_remains_valid() -> None:
    authority = RecordingFeedAuthority("recording-feed", KEY)
    owner = ExperimentRecordingOwner("recording-owner", authority.generation_id, authority)
    _ready(owner, authority)
    assert owner.begin_recording_epoch() is True
    session_id = owner.snapshot().recording_session_id
    _assert_owner_not_cloneable(owner)
    assert owner.snapshot().recording_session_id == session_id
    owner.feed_persistence(authority.persistence(2, PersistenceLifecycle.LOSS))
    assert owner.snapshot().recording is RecordingTruth.NOT_RECORDING


def test_detached_worker_envelope_remains_intentionally_serializable() -> None:
    authority = RecordingFeedAuthority("worker-feed", KEY)
    envelope = RecordingWorkerOutcomeEnvelope(1, RecordingFeedKind.EXPERIMENT, _active(authority))
    restored = pickle.loads(pickle.dumps(envelope))
    assert type(restored) is RecordingWorkerOutcomeEnvelope
    assert restored == envelope
