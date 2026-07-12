from __future__ import annotations

import inspect
import pickle
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
from itertools import permutations

import pytest

import cryodaq.engine_wiring.persistence_authority_owner as module
from cryodaq.engine_wiring.persistence_authority_owner import (
    DurableAppendReceipt,
    PersistenceAuthorityOwner,
    PersistenceFailureKind,
    PersistenceOutcomeAuthority,
    PersistenceOwnerLifecycle,
)
from cryodaq.operator_snapshot import MAX_NONNEGATIVE_INT, AvailabilityTruth

KEY = b"persistence-presentation-owner-key!"
EPOCH = "recording-epoch-1"


@pytest.fixture()
def authority() -> PersistenceOutcomeAuthority:
    return PersistenceOutcomeAuthority("persistence-feed", KEY)


@pytest.fixture()
def owner(authority: PersistenceOutcomeAuthority) -> PersistenceAuthorityOwner:
    return PersistenceAuthorityOwner("persistence-owner", authority.generation_id, authority)


def _start(owner: PersistenceAuthorityOwner, authority: PersistenceOutcomeAuthority, revision: int = 1) -> None:
    owner.feed(authority.lifecycle(revision, EPOCH, PersistenceOwnerLifecycle.STARTED))


def test_crash_boundary_requires_durable_append_then_matching_materialization_and_ack(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    started = owner.snapshot()
    assert started.storage is AvailabilityTruth.UNKNOWN
    assert started.reason == "epoch_started_no_storage_proof"

    owner.feed(authority.durable_append(2, EPOCH, "append-1", "sqlite-main"))
    appended = owner.snapshot()
    assert appended.pending_count == 1
    assert appended.committed_materialization_revision == 0
    assert appended.storage is AvailabilityTruth.AVAILABLE

    owner.feed(authority.materialized(3, EPOCH, "append-1", "sqlite-main", 7))
    materialized = owner.snapshot()
    assert materialized.pending_count == 1
    assert materialized.committed_materialization_revision == 7

    owner.feed(authority.acknowledged(4, EPOCH, "append-1", "sqlite-main", 7))
    acknowledged = owner.snapshot()
    assert acknowledged.pending_count == 0
    assert acknowledged.reason == "spool_acknowledged"


def test_materialization_alone_never_decrements_and_ack_needs_exact_join(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "append-1", "sqlite-main"))
    owner.feed(authority.materialized(3, EPOCH, "append-1", "sqlite-main", 8))
    before = owner.snapshot()

    with pytest.raises(ValueError, match="exact append/materialization"):
        owner.feed(authority.acknowledged(4, EPOCH, "append-1", "wrong-destination", 8))
    assert owner.snapshot() is before
    with pytest.raises(ValueError, match="exact append/materialization"):
        owner.feed(authority.acknowledged(5, EPOCH, "append-1", "sqlite-main", 9))
    assert owner.snapshot() is before

    owner.feed(authority.acknowledged(6, EPOCH, "append-1", "sqlite-main", 8))
    accepted = owner.snapshot()
    with pytest.raises(ValueError, match="exact append/materialization"):
        owner.feed(authority.acknowledged(7, EPOCH, "append-1", "sqlite-main", 8))
    assert owner.snapshot() is accepted


def test_rejection_and_pending_failure_are_counted_without_optimistic_storage(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(
        authority.failure(
            2,
            EPOCH,
            "reject-1",
            PersistenceFailureKind.REJECTION,
            None,
            "append_rejected",
        )
    )
    rejected = owner.snapshot()
    assert rejected.pending_count == 0
    assert rejected.dropped_or_rejected_count == 1
    assert rejected.storage is AvailabilityTruth.UNAVAILABLE
    assert rejected.reason == "append_rejected"

    owner.feed(authority.durable_append(3, EPOCH, "append-1", "sqlite-main"))
    owner.feed(
        authority.failure(
            4,
            EPOCH,
            "failure-1",
            PersistenceFailureKind.FAILURE,
            "append-1",
            "materialization_failed",
        )
    )
    failed = owner.snapshot()
    assert failed.pending_count == 0
    assert failed.dropped_or_rejected_count == 2
    assert failed.storage is AvailabilityTruth.UNAVAILABLE


def test_unknown_failure_identity_cannot_underflow_pending_count(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    before = owner.snapshot()
    receipt = authority.failure(
        2,
        EPOCH,
        "failure-1",
        PersistenceFailureKind.FAILURE,
        "missing-append",
        "write_failed",
    )
    with pytest.raises(ValueError, match="pending durable append"):
        owner.feed(receipt)
    assert owner.snapshot() is before


def test_archive_revision_is_optional_then_strictly_monotonic(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    assert owner.snapshot().archive_revision is None
    owner.feed(authority.archive(2, EPOCH, 5, "archive-index"))
    accepted = owner.snapshot()
    assert accepted.archive_revision == 5
    with pytest.raises(ValueError, match="archive revision"):
        owner.feed(authority.archive(3, EPOCH, 5, "archive-index"))
    assert owner.snapshot() is accepted


def test_materialization_revision_is_global_monotonic_within_epoch(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db"))
    owner.feed(authority.materialized(3, EPOCH, "a", "db", 4))
    owner.feed(authority.durable_append(4, EPOCH, "b", "db"))
    before = owner.snapshot()
    with pytest.raises(ValueError, match="materialization revision"):
        owner.feed(authority.materialized(5, EPOCH, "b", "db", 3))
    assert owner.snapshot() is before


@pytest.mark.parametrize(
    "terminal,reason",
    [
        (PersistenceOwnerLifecycle.STOPPED, "lifecycle_stopped"),
        (PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS, "cancellation_ambiguous"),
    ],
)
def test_stop_and_cancellation_ambiguity_are_unavailable_not_guessed(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    terminal: PersistenceOwnerLifecycle,
    reason: str,
) -> None:
    _start(owner, authority)
    owner.feed(authority.lifecycle(2, EPOCH, terminal))
    snapshot = owner.snapshot()
    assert snapshot.storage is AvailabilityTruth.UNAVAILABLE
    assert snapshot.reason == reason


def test_lifecycle_cannot_replace_epoch_with_unsettled_pending_append(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db"))
    owner.feed(authority.lifecycle(3, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    stopped = owner.snapshot()
    with pytest.raises(ValueError, match="pending append"):
        owner.feed(authority.lifecycle(4, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot() is stopped


def test_post_stop_ack_can_settle_known_materialization_without_restoring_availability(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db"))
    owner.feed(authority.materialized(3, EPOCH, "a", "db", 1))
    owner.feed(authority.lifecycle(4, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    owner.feed(authority.acknowledged(5, EPOCH, "a", "db", 1))
    snapshot = owner.snapshot()
    assert snapshot.pending_count == 0
    assert snapshot.storage is AvailabilityTruth.UNAVAILABLE
    assert snapshot.reason == "spool_acknowledged_after_stop"


@pytest.mark.parametrize(
    "terminal",
    [PersistenceOwnerLifecycle.STOPPED, PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS],
)
def test_terminal_epoch_accepts_late_materialization_and_ack_then_allows_distinct_epoch(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    terminal: PersistenceOwnerLifecycle,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db", 4))
    owner.feed(authority.lifecycle(3, EPOCH, terminal))
    owner.feed(authority.materialized(4, EPOCH, "a", "db", 1, 4))
    assert owner.snapshot().storage is AvailabilityTruth.UNAVAILABLE
    assert owner.snapshot().reason == "materialization_committed_after_stop"
    owner.feed(authority.acknowledged(5, EPOCH, "a", "db", 1, 4))
    assert owner.snapshot().pending_count == 0
    assert owner.snapshot().storage is AvailabilityTruth.UNAVAILABLE
    owner.feed(authority.lifecycle(6, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot().recording_epoch_id == "recording-epoch-2"
    assert owner.snapshot().storage is AvailabilityTruth.UNKNOWN


def test_terminal_epoch_accepts_late_failure_then_allows_distinct_epoch(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db", 7))
    owner.feed(authority.lifecycle(3, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    owner.feed(
        authority.failure(
            4,
            EPOCH,
            "late-failure",
            PersistenceFailureKind.FAILURE,
            "a",
            "late_write_failure",
            7,
        )
    )
    assert owner.snapshot().pending_count == 0
    assert owner.snapshot().dropped_or_rejected_count == 7
    assert owner.snapshot().storage is AvailabilityTruth.UNAVAILABLE
    owner.feed(authority.lifecycle(5, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot().recording_epoch_id == "recording-epoch-2"


def test_epoch_counts_reset_only_on_settled_explicit_new_start(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.failure(2, EPOCH, "r", PersistenceFailureKind.REJECTION, None, "rejected"))
    owner.feed(authority.lifecycle(3, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    owner.feed(authority.lifecycle(4, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    snapshot = owner.snapshot()
    assert snapshot.recording_epoch_id == "recording-epoch-2"
    assert snapshot.pending_count == 0
    assert snapshot.dropped_or_rejected_count == 0
    assert snapshot.archive_revision is None


def test_used_epoch_and_completed_append_id_cannot_replay_or_reset_counts(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db"))
    owner.feed(authority.materialized(3, EPOCH, "a", "db", 1))
    owner.feed(authority.acknowledged(4, EPOCH, "a", "db", 1))
    owner.feed(authority.lifecycle(5, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    stopped = owner.snapshot()
    with pytest.raises(ValueError, match="epoch identity was already used"):
        owner.feed(authority.lifecycle(6, EPOCH, PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot() is stopped

    owner.feed(authority.lifecycle(7, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    before = owner.snapshot()
    with pytest.raises(ValueError, match="append identity was already used"):
        owner.feed(authority.durable_append(8, "recording-epoch-2", "a", "db"))
    assert owner.snapshot() is before


def test_failure_identity_is_retained_and_deduplicated_for_owner_lifetime(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.failure(2, EPOCH, "failure-1", PersistenceFailureKind.REJECTION, None, "reject"))
    accepted = owner.snapshot()
    with pytest.raises(ValueError, match="failure identity was already used"):
        owner.feed(authority.failure(3, EPOCH, "failure-1", PersistenceFailureKind.REJECTION, None, "reject"))
    assert owner.snapshot() is accepted


def test_counts_represent_records_not_operations_and_require_exact_count_join(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "batch", "db", 25))
    assert owner.snapshot().pending_count == 25
    with pytest.raises(ValueError, match="matching pending destination"):
        owner.feed(authority.materialized(3, EPOCH, "batch", "db", 1, 24))
    assert owner.snapshot().pending_count == 25
    owner.feed(authority.materialized(4, EPOCH, "batch", "db", 1, 25))
    with pytest.raises(ValueError, match="exact append/materialization"):
        owner.feed(authority.acknowledged(5, EPOCH, "batch", "db", 1, 24))
    owner.feed(authority.acknowledged(6, EPOCH, "batch", "db", 1, 25))
    assert owner.snapshot().pending_count == 0

    owner.feed(authority.failure(7, EPOCH, "reject-batch", PersistenceFailureKind.REJECTION, None, "reject", 9))
    assert owner.snapshot().dropped_or_rejected_count == 9


@pytest.mark.parametrize("count", [0, -1, True, MAX_NONNEGATIVE_INT + 1])
def test_record_count_is_an_exact_bounded_positive_integer(
    authority: PersistenceOutcomeAuthority,
    count: object,
) -> None:
    with pytest.raises(ValueError, match="record_count"):
        authority.durable_append(1, EPOCH, "a", "db", count)  # type: ignore[arg-type]


def test_record_count_sums_fail_closed_at_numeric_boundary() -> None:
    authority = PersistenceOutcomeAuthority("feed", KEY)
    owner = PersistenceAuthorityOwner("owner", authority.generation_id, authority)
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "max-batch", "db", MAX_NONNEGATIVE_INT))
    pending_max = owner.snapshot()
    assert pending_max.pending_count == MAX_NONNEGATIVE_INT
    with pytest.raises(OverflowError, match="pending append count"):
        owner.feed(authority.durable_append(3, EPOCH, "overflow-batch", "db", 1))
    assert owner.snapshot() is pending_max

    other_authority = PersistenceOutcomeAuthority("other-feed", KEY)
    other = PersistenceAuthorityOwner("other-owner", other_authority.generation_id, other_authority)
    _start(other, other_authority)
    other.feed(
        other_authority.failure(
            2,
            EPOCH,
            "max-rejection",
            PersistenceFailureKind.REJECTION,
            None,
            "reject",
            MAX_NONNEGATIVE_INT,
        )
    )
    dropped_max = other.snapshot()
    assert dropped_max.dropped_or_rejected_count == MAX_NONNEGATIVE_INT
    with pytest.raises(OverflowError, match="dropped/rejected count"):
        other.feed(
            other_authority.failure(
                3,
                EPOCH,
                "overflow-rejection",
                PersistenceFailureKind.REJECTION,
                None,
                "reject",
                1,
            )
        )
    assert other.snapshot() is dropped_max


def test_materialization_and_archive_revisions_are_epoch_global_across_destinations(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db-a"))
    owner.feed(authority.durable_append(3, EPOCH, "b", "db-b"))
    owner.feed(authority.materialized(4, EPOCH, "a", "db-a", 5))
    before = owner.snapshot()
    with pytest.raises(ValueError, match="materialization revision"):
        owner.feed(authority.materialized(5, EPOCH, "b", "db-b", 4))
    assert owner.snapshot() is before
    owner.feed(authority.materialized(6, EPOCH, "b", "db-b", 6))
    with pytest.raises(ValueError, match="exact append/materialization"):
        owner.feed(authority.acknowledged(7, EPOCH, "b", "db-a", 6))
    owner.feed(authority.acknowledged(8, EPOCH, "b", "db-b", 6))

    owner.feed(authority.archive(9, EPOCH, 11, "archive-a"))
    archived = owner.snapshot()
    with pytest.raises(ValueError, match="archive revision"):
        owner.feed(authority.archive(10, EPOCH, 10, "archive-b"))
    assert owner.snapshot() is archived


def test_receipt_revisions_are_idempotent_and_reject_regression_or_equivocation(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    receipt = authority.lifecycle(2, EPOCH, PersistenceOwnerLifecycle.STARTED)
    owner.feed(receipt)
    accepted = owner.snapshot()
    owner.feed(receipt)
    assert owner.snapshot() is accepted
    with pytest.raises(ValueError, match="equivocation"):
        owner.feed(authority.lifecycle(2, "other-epoch", PersistenceOwnerLifecycle.STARTED))
    with pytest.raises(ValueError, match="regression"):
        owner.feed(authority.lifecycle(1, EPOCH, PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot() is accepted


def test_old_generation_and_cross_owner_receipts_are_rejected_after_restart() -> None:
    old_authority = PersistenceOutcomeAuthority("feed", KEY)
    old_owner = PersistenceAuthorityOwner("owner", old_authority.generation_id, old_authority)
    old_receipt = old_authority.lifecycle(1, EPOCH, PersistenceOwnerLifecycle.STARTED)
    old_owner.feed(old_receipt)

    new_authority = PersistenceOutcomeAuthority("feed", KEY)
    new_owner = PersistenceAuthorityOwner("owner", new_authority.generation_id, new_authority)
    before = new_owner.snapshot()
    with pytest.raises(ValueError, match="provenance"):
        new_owner.feed(old_receipt)
    assert new_owner.snapshot() is before


def test_forged_and_subclass_receipts_are_rejected_without_mutation(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    genuine = authority.durable_append(1, EPOCH, "a", "db")
    forged = replace(genuine, append_id="b")
    before = owner.snapshot()
    with pytest.raises(ValueError, match="provenance"):
        owner.feed(forged)

    class Subclass(DurableAppendReceipt):
        pass

    subclass = Subclass(
        genuine.issuer_id,
        genuine.generation_id,
        genuine.revision,
        genuine.recording_epoch_id,
        genuine.append_id,
        genuine.destination_id,
        genuine.record_count,
        genuine.provenance,
    )
    with pytest.raises(TypeError, match="exact persistence outcome"):
        owner.feed(subclass)
    assert owner.snapshot() is before


def test_same_loop_permutations_reject_out_of_order_without_partial_mutation() -> None:
    for order in permutations(("append", "materialize", "ack")):
        authority = PersistenceOutcomeAuthority("feed", KEY)
        owner = PersistenceAuthorityOwner("owner", authority.generation_id, authority)
        _start(owner, authority)
        revisions = {name: index + 2 for index, name in enumerate(order)}
        receipts = {
            "append": authority.durable_append(revisions["append"], EPOCH, "a", "db"),
            "materialize": authority.materialized(revisions["materialize"], EPOCH, "a", "db", 1),
            "ack": authority.acknowledged(revisions["ack"], EPOCH, "a", "db", 1),
        }
        failed = False
        for name in order:
            before = owner.snapshot()
            try:
                owner.feed(receipts[name])
            except ValueError:
                failed = True
                assert owner.snapshot() is before
                break
        if order == ("append", "materialize", "ack"):
            assert not failed
            assert owner.snapshot().pending_count == 0
        else:
            assert failed


def test_all_valid_two_append_same_loop_interleavings_converge_to_same_aggregate() -> None:
    events = ("append-a", "materialize-a", "ack-a", "append-b", "materialize-b", "ack-b")
    valid_orders = [
        order
        for order in permutations(events)
        if order.index("append-a") < order.index("materialize-a") < order.index("ack-a")
        and order.index("append-b") < order.index("materialize-b") < order.index("ack-b")
    ]
    assert len(valid_orders) == 20
    aggregates: set[tuple[object, ...]] = set()
    for order in valid_orders:
        authority = PersistenceOutcomeAuthority("feed", KEY)
        owner = PersistenceAuthorityOwner("owner", authority.generation_id, authority)
        _start(owner, authority)
        materialization_revision = 0
        for revision, event in enumerate(order, start=2):
            operation, append_id = event.split("-")
            if operation == "append":
                receipt = authority.durable_append(revision, EPOCH, append_id, "db")
            elif operation == "materialize":
                materialization_revision += 1
                receipt = authority.materialized(revision, EPOCH, append_id, "db", materialization_revision)
            else:
                expected_revision = 1 if order.index("materialize-a") < order.index("materialize-b") else 2
                if append_id == "b":
                    expected_revision = 1 if expected_revision == 2 else 2
                receipt = authority.acknowledged(revision, EPOCH, append_id, "db", expected_revision)
            owner.feed(receipt)
        snapshot = owner.snapshot()
        aggregates.add(
            (
                snapshot.pending_count,
                snapshot.dropped_or_rejected_count,
                snapshot.committed_materialization_revision,
                snapshot.storage,
            )
        )
    assert aggregates == {(0, 0, 2, AvailabilityTruth.AVAILABLE)}


def test_snapshot_is_cached_frozen_and_constant_shape(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
) -> None:
    first = owner.snapshot()
    assert owner.snapshot() is first
    with pytest.raises(FrozenInstanceError):
        first.pending_count = 2  # type: ignore[misc]
    _start(owner, authority)
    assert owner.snapshot() is not first
    assert owner.snapshot() is owner.snapshot()


@pytest.mark.parametrize("operation", [copy, deepcopy, pickle.dumps])
def test_authority_and_owner_cannot_be_copied_or_serialized(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    operation: object,
) -> None:
    with pytest.raises(TypeError):
        operation(authority)  # type: ignore[operator]
    with pytest.raises(TypeError):
        operation(owner)  # type: ignore[operator]


def test_authority_and_owner_reject_inherited_process_use(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creator_pid = module.os.getpid()
    monkeypatch.setattr(module.os, "getpid", lambda: creator_pid + 1)
    with pytest.raises(RuntimeError, match="process boundary"):
        authority.lifecycle(1, EPOCH, PersistenceOwnerLifecycle.STARTED)
    with pytest.raises(RuntimeError, match="process boundary"):
        authority.verifies(object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="process boundary"):
        owner.snapshot()


def test_detached_receipts_are_pickleable_for_future_worker_return(
    authority: PersistenceOutcomeAuthority,
) -> None:
    receipt = authority.materialized(1, EPOCH, "a", "db", 4)
    restored = pickle.loads(pickle.dumps(receipt))
    assert type(restored) is type(receipt)
    assert restored == receipt


@pytest.mark.parametrize(
    "value",
    ["", " padded", "padded ", "x" * 129, "bad\ntext", True],
)
def test_identifiers_are_strict_bounded_text(value: object, authority: PersistenceOutcomeAuthority) -> None:
    with pytest.raises(ValueError, match="bounded text|non-empty exact text|forbidden control"):
        authority.durable_append(1, EPOCH, value, "db")  # type: ignore[arg-type]


def test_one_authority_generation_can_be_claimed_only_once(authority: PersistenceOutcomeAuthority) -> None:
    PersistenceAuthorityOwner("first", authority.generation_id, authority)
    with pytest.raises(RuntimeError, match="already claimed"):
        PersistenceAuthorityOwner("second", authority.generation_id, authority)


def test_production_authorities_have_fresh_uninjectable_generations() -> None:
    first = PersistenceOutcomeAuthority("feed", KEY)
    second = PersistenceOutcomeAuthority("feed", KEY)
    assert first.generation_id != second.generation_id
    assert tuple(inspect.signature(PersistenceOutcomeAuthority).parameters) == ("issuer_id", "provenance_key")


def test_lifetime_identity_tombstones_fail_closed_at_bounded_capacity(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "MAX_TRACKED_IDENTITIES", 1)
    _start(owner, authority)
    owner.feed(authority.durable_append(2, EPOCH, "a", "db"))
    owner.feed(authority.materialized(3, EPOCH, "a", "db", 1))
    owner.feed(authority.acknowledged(4, EPOCH, "a", "db", 1))
    before_append = owner.snapshot()
    with pytest.raises(OverflowError, match="append identity capacity"):
        owner.feed(authority.durable_append(5, EPOCH, "b", "db"))
    assert owner.snapshot() is before_append

    owner.feed(authority.failure(6, EPOCH, "f1", PersistenceFailureKind.REJECTION, None, "reject"))
    before_failure = owner.snapshot()
    with pytest.raises(OverflowError, match="failure identity capacity"):
        owner.feed(authority.failure(7, EPOCH, "f2", PersistenceFailureKind.REJECTION, None, "reject"))
    assert owner.snapshot() is before_failure

    owner.feed(authority.lifecycle(8, EPOCH, PersistenceOwnerLifecycle.STOPPED))
    before_epoch = owner.snapshot()
    with pytest.raises(OverflowError, match="epoch identity capacity"):
        owner.feed(authority.lifecycle(9, "recording-epoch-2", PersistenceOwnerLifecycle.STARTED))
    assert owner.snapshot() is before_epoch


def test_count_and_authority_revision_overflow_fail_before_mutation(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _start(owner, authority)
    receipt = authority.durable_append(2, EPOCH, "a", "db")
    monkeypatch.setattr(owner, "_PersistenceAuthorityOwner__revision", MAX_NONNEGATIVE_INT)
    before = owner.snapshot()
    with pytest.raises(OverflowError, match="authority revision"):
        owner.feed(receipt)
    assert owner.snapshot() is before


def test_dropped_count_overflow_fails_before_mutation(
    owner: PersistenceAuthorityOwner,
    authority: PersistenceOutcomeAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _start(owner, authority)
    owner.feed(authority.failure(2, EPOCH, "r1", PersistenceFailureKind.REJECTION, None, "rejected"))
    receipt = authority.failure(3, EPOCH, "r2", PersistenceFailureKind.REJECTION, None, "rejected")
    monkeypatch.setattr(owner, "_PersistenceAuthorityOwner__dropped", MAX_NONNEGATIVE_INT)
    before = owner.snapshot()
    with pytest.raises(OverflowError, match="dropped/rejected"):
        owner.feed(receipt)
    assert owner.snapshot() is before


def test_contract_has_no_storage_spool_scheduler_engine_or_control_imports() -> None:
    source = inspect.getsource(module)
    forbidden = (
        "cryodaq.storage",
        "persistence_spool",
        "SQLiteWriter",
        "cryodaq.scheduler",
        "cryodaq.engine import",
        "cryodaq.safety",
        "PySide",
        "zmq",
    )
    assert all(name not in source for name in forbidden)
    assert PersistenceAuthorityOwner.grants_control_authority is False
