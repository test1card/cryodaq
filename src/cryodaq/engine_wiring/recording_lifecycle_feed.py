"""Dark, same-loop lifecycle feed for experiment recording presentation.

This bridge owns the only feed authority and recording owner for its lifetime.
It translates already-successful engine lifecycle outcomes into cached
presentation truth; it performs no I/O, persistence, publication, or control.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import threading
import time
from collections.abc import Callable

from cryodaq.engine_wiring.experiment_recording_owner import (
    AcquisitionLifecycle,
    ExperimentOperation,
    ExperimentRecordingOwner,
    ExperimentRecordingSnapshot,
    PersistenceLifecycle,
    RecordingFeedAuthority,
)
from cryodaq.engine_wiring.persistence_authority_owner import (
    PersistenceAuthorityOwner,
    PersistenceAuthoritySnapshot,
    PersistenceFailureKind,
    PersistenceOutcomeAuthority,
    PersistenceOwnerLifecycle,
)
from cryodaq.storage.sqlite_writer import CommittedBatchReceipt, SQLiteWriter

_DIRECT_DESTINATION_ID = "descriptor-sqlite"
_DEFAULT_PERSISTENCE_FRESHNESS_S = 30.0
_MAX_PERSISTENCE_FRESHNESS_S = 259_200.0


class RecordingLifecycleFeed:
    """Own and feed one recording presentation owner on its creating loop."""

    __slots__ = (
        "__acquisition_revision",
        "__acquisition_payload",
        "__authority",
        "__experiment_revision",
        "__experiment_payload",
        "__loop",
        "__owner",
        "__pid",
        "__persistence_active",
        "__persistence_authority",
        "__persistence_epoch",
        "__persistence_freshness_s",
        "__persistence_last_commit_at",
        "__persistence_latched",
        "__persistence_outcome_revision",
        "__persistence_owner",
        "__persistence_source_revision",
        "__persistence_writer",
        "__clock",
        "__thread_id",
    )
    grants_control_authority = False

    def __init__(
        self,
        writer: SQLiteWriter | None = None,
        *,
        persistence_freshness_s: float = _DEFAULT_PERSISTENCE_FRESHNESS_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("recording lifecycle feed must be created on a running engine loop") from exc
        authority = RecordingFeedAuthority("engine-recording-feed", secrets.token_bytes(32))
        self.__authority = authority
        self.__owner = ExperimentRecordingOwner("engine-recording-owner", authority.generation_id, authority)
        self.__loop = loop
        self.__pid = os.getpid()
        self.__thread_id = threading.get_ident()
        self.__experiment_revision = 0
        self.__acquisition_revision = 0
        self.__experiment_payload: tuple[object, ...] | None = None
        self.__acquisition_payload: tuple[object, ...] | None = None
        if writer is not None and type(writer) is not SQLiteWriter:
            raise TypeError("writer must be an exact SQLiteWriter")
        if (
            type(persistence_freshness_s) is not float
            or not 0.1 <= persistence_freshness_s <= _MAX_PERSISTENCE_FRESHNESS_S
        ):
            raise ValueError(f"persistence_freshness_s must be an exact float in [0.1, {_MAX_PERSISTENCE_FRESHNESS_S}]")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.__persistence_writer = writer
        self.__persistence_freshness_s = persistence_freshness_s
        self.__clock = clock
        self.__persistence_outcome_revision = 0
        self.__persistence_source_revision = 0
        self.__persistence_epoch: str | None = None
        self.__persistence_active = False
        self.__persistence_latched = False
        self.__persistence_last_commit_at: float | None = None
        if writer is None:
            self.__persistence_authority = None
            self.__persistence_owner = None
        else:
            persistence_authority = PersistenceOutcomeAuthority("engine-direct-sqlite-feed", secrets.token_bytes(32))
            self.__persistence_authority = persistence_authority
            self.__persistence_owner = PersistenceAuthorityOwner(
                "engine-direct-sqlite-owner",
                persistence_authority.generation_id,
                persistence_authority,
            )

    def __copy__(self) -> RecordingLifecycleFeed:
        raise TypeError("recording lifecycle feed cannot be copied")

    def __deepcopy__(self, _memo: object) -> RecordingLifecycleFeed:
        raise TypeError("recording lifecycle feed cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("recording lifecycle feed cannot be serialized")

    def __ensure_loop(self) -> None:
        if os.getpid() != self.__pid:
            raise RuntimeError("recording lifecycle feed cannot cross its creating process boundary")
        if threading.get_ident() != self.__thread_id:
            raise RuntimeError("recording lifecycle feed cannot cross its engine-loop thread")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("recording lifecycle feed requires its running engine loop") from exc
        if loop is not self.__loop:
            raise RuntimeError("recording lifecycle feed cannot cross its creating engine loop")

    def snapshot(self) -> ExperimentRecordingSnapshot:
        self.__ensure_loop()
        self.__expire_persistence()
        return self.__owner.snapshot()

    def persistence_snapshot(self) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        self.__expire_persistence()
        _authority, owner, _writer = self.__require_persistence()
        return owner.snapshot()

    def persistence_started(self, epoch_id: str) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        authority, owner, _writer = self.__require_persistence()
        if self.__persistence_active:
            self.__terminalize_persistence(PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS)
            raise ValueError("direct persistence epoch is already active")
        self.__persistence_outcome_revision += 1
        try:
            owner.feed(
                authority.lifecycle(
                    self.__persistence_outcome_revision,
                    epoch_id,
                    PersistenceOwnerLifecycle.STARTED,
                )
            )
        except Exception:
            self.__terminalize_persistence(PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS)
            raise
        self.__persistence_epoch = epoch_id
        self.__persistence_active = True
        self.__persistence_latched = False
        self.__persistence_last_commit_at = None
        return owner.snapshot()

    def persistence_committed(self, receipt: CommittedBatchReceipt) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        authority, owner, writer = self.__require_persistence()
        if not self.__persistence_active or self.__persistence_epoch is None:
            raise ValueError("direct persistence commit requires an active epoch")
        if type(receipt) is not CommittedBatchReceipt or not writer.owns_commit(receipt):
            raise ValueError("direct persistence commit lacks exact SQLiteWriter provenance")
        entries = writer.entries_from_commit(receipt)
        source_revision = receipt.commit_revision
        if source_revision < self.__persistence_source_revision:
            raise ValueError("direct persistence source revision regression")
        if source_revision == self.__persistence_source_revision:
            return owner.snapshot()
        if self.__owner.snapshot().acquisition_epoch_id != self.__persistence_epoch:
            self.__terminalize_persistence(PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS)
            raise ValueError("acquisition epoch does not match direct persistence epoch")
        self.__persistence_outcome_revision += 1
        owner.feed(
            authority.direct_commit(
                self.__persistence_outcome_revision,
                self.__persistence_epoch,
                source_revision,
                _DIRECT_DESTINATION_ID,
                len(entries),
            )
        )
        self.__persistence_source_revision = source_revision
        self.__persistence_last_commit_at = self.__clock()
        if not self.__persistence_latched:
            self.__owner.feed_persistence(
                self.__authority.persistence(
                    self.__persistence_outcome_revision,
                    PersistenceLifecycle.LOSSLESS,
                    self.__persistence_epoch,
                )
            )
            self.__owner.begin_recording_epoch()
        return owner.snapshot()

    def persistence_rejected(self, record_count: int, reason: str) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        authority, owner, _writer = self.__require_persistence()
        if not self.__persistence_active or self.__persistence_epoch is None:
            raise ValueError("direct persistence rejection requires an active epoch")
        if type(record_count) is not int or record_count < 1:
            raise ValueError("record_count must be a positive exact integer")
        self.__persistence_outcome_revision += 1
        owner.feed(
            authority.failure(
                self.__persistence_outcome_revision,
                self.__persistence_epoch,
                f"direct-rejection-{self.__persistence_outcome_revision}",
                PersistenceFailureKind.REJECTION,
                None,
                reason,
                record_count,
            )
        )
        self.__persistence_latched = True
        self.__owner.feed_persistence(
            self.__authority.persistence(self.__persistence_outcome_revision, PersistenceLifecycle.LOSS)
        )
        return owner.snapshot()

    def persistence_ambiguous(self) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        return self.__terminalize_persistence(PersistenceOwnerLifecycle.CANCELLATION_AMBIGUOUS)

    def persistence_stopped(self) -> PersistenceAuthoritySnapshot:
        self.__ensure_loop()
        return self.__terminalize_persistence(PersistenceOwnerLifecycle.STOPPED)

    def __terminalize_persistence(
        self,
        lifecycle: PersistenceOwnerLifecycle,
    ) -> PersistenceAuthoritySnapshot:
        authority, owner, _writer = self.__require_persistence()
        epoch = self.__persistence_epoch
        if self.__persistence_active and epoch is not None:
            self.__persistence_outcome_revision += 1
            owner.feed(authority.lifecycle(self.__persistence_outcome_revision, epoch, lifecycle))
        self.__persistence_active = False
        self.__persistence_latched = True
        self.__persistence_epoch = None
        self.__persistence_last_commit_at = None
        if self.__owner.snapshot().persistence_epoch_id is not None:
            self.__persistence_outcome_revision += 1
            self.__owner.feed_persistence(
                self.__authority.persistence(self.__persistence_outcome_revision, PersistenceLifecycle.UNAVAILABLE)
            )
        return owner.snapshot()

    def __expire_persistence(self) -> None:
        if (
            self.__persistence_active
            and not self.__persistence_latched
            and self.__persistence_last_commit_at is not None
            and self.__clock() - self.__persistence_last_commit_at > self.__persistence_freshness_s
        ):
            self.persistence_ambiguous()

    def __require_persistence(
        self,
    ) -> tuple[PersistenceOutcomeAuthority, PersistenceAuthorityOwner, SQLiteWriter]:
        authority = self.__persistence_authority
        owner = self.__persistence_owner
        writer = self.__persistence_writer
        if authority is None or owner is None or writer is None:
            raise RuntimeError("direct SQLite persistence feed is unavailable")
        return authority, owner, writer

    def experiment_active(
        self, source_revision: int, experiment_id: str, experiment_name: str, phase: str | None = None
    ) -> ExperimentRecordingSnapshot:
        """Create or update the exact active experiment/phase presentation."""

        self.__ensure_loop()
        payload = (ExperimentOperation.ACTIVE, experiment_id, experiment_name, phase)
        if not self.__accept_source(
            source_revision,
            payload,
            current_revision=self.__experiment_revision,
            current_payload=self.__experiment_payload,
            domain="experiment",
        ):
            return self.__owner.snapshot()
        current = self.__owner.snapshot()
        if current.experiment_operation is ExperimentOperation.ACTIVE:
            if current.experiment_id != experiment_id:
                raise ValueError("active experiment cannot be replaced without a terminal lifecycle outcome")
        outcome = self.__authority.experiment(
            source_revision,
            f"experiment-{source_revision}",
            ExperimentOperation.ACTIVE,
            experiment_id,
            experiment_name,
            phase,
        )
        self.__owner.feed_experiment(outcome)
        self.__experiment_revision = source_revision
        self.__experiment_payload = payload
        return self.__owner.snapshot()

    def experiment_finalized(self, source_revision: int, experiment_id: str) -> ExperimentRecordingSnapshot:
        """Publish successful finalization of the exact active experiment."""

        self.__ensure_loop()
        payload = (ExperimentOperation.FINALIZED, experiment_id)
        if not self.__accept_source(
            source_revision,
            payload,
            current_revision=self.__experiment_revision,
            current_payload=self.__experiment_payload,
            domain="experiment",
        ):
            return self.__owner.snapshot()
        current = self.__owner.snapshot()
        self.__require_active_experiment(current, experiment_id, "finalization")
        self.__owner.feed_experiment(
            self.__authority.experiment(
                source_revision,
                f"experiment-{source_revision}",
                ExperimentOperation.FINALIZED,
                experiment_id,
            )
        )
        self.__experiment_revision = source_revision
        self.__experiment_payload = payload
        return self.__owner.snapshot()

    def experiment_aborted(self, source_revision: int, experiment_id: str) -> ExperimentRecordingSnapshot:
        """Publish an abort as conservative inactive experiment truth."""

        self.__ensure_loop()
        payload = (ExperimentOperation.INACTIVE, "aborted", experiment_id)
        if not self.__accept_source(
            source_revision,
            payload,
            current_revision=self.__experiment_revision,
            current_payload=self.__experiment_payload,
            domain="experiment",
        ):
            return self.__owner.snapshot()
        current = self.__owner.snapshot()
        self.__require_active_experiment(current, experiment_id, "abort")
        self.__owner.feed_experiment(
            self.__authority.experiment(source_revision, f"experiment-{source_revision}", ExperimentOperation.INACTIVE)
        )
        self.__experiment_revision = source_revision
        self.__experiment_payload = payload
        return self.__owner.snapshot()

    def experiment_inactive(self, source_revision: int) -> ExperimentRecordingSnapshot:
        """Publish the authoritative absence of an active experiment."""

        self.__ensure_loop()
        payload = (ExperimentOperation.INACTIVE, "inactive")
        if not self.__accept_source(
            source_revision,
            payload,
            current_revision=self.__experiment_revision,
            current_payload=self.__experiment_payload,
            domain="experiment",
        ):
            return self.__owner.snapshot()
        self.__owner.feed_experiment(
            self.__authority.experiment(source_revision, f"experiment-{source_revision}", ExperimentOperation.INACTIVE)
        )
        self.__experiment_revision = source_revision
        self.__experiment_payload = payload
        return self.__owner.snapshot()

    def acquisition_running(self, sequence: int, epoch_id: str) -> ExperimentRecordingSnapshot:
        """Publish acquisition RUNNING while preserving its exact epoch identity."""

        self.__ensure_loop()
        payload = (AcquisitionLifecycle.RUNNING, epoch_id)
        if not self.__accept_source(
            sequence,
            payload,
            current_revision=self.__acquisition_revision,
            current_payload=self.__acquisition_payload,
            domain="acquisition",
        ):
            return self.__owner.snapshot()
        current = self.__owner.snapshot()
        if current.acquisition_epoch_id is not None:
            raise ValueError("running acquisition epoch cannot be replaced before stop or unavailability")
        self.__owner.feed_acquisition(self.__authority.acquisition(sequence, AcquisitionLifecycle.RUNNING, epoch_id))
        self.__acquisition_revision = sequence
        self.__acquisition_payload = payload
        return self.__owner.snapshot()

    def acquisition_stopped(self, sequence: int) -> ExperimentRecordingSnapshot:
        return self.__acquisition_terminal(sequence, AcquisitionLifecycle.STOPPED)

    def acquisition_unavailable(self, sequence: int) -> ExperimentRecordingSnapshot:
        return self.__acquisition_terminal(sequence, AcquisitionLifecycle.UNAVAILABLE)

    def __acquisition_terminal(self, sequence: int, state: AcquisitionLifecycle) -> ExperimentRecordingSnapshot:
        self.__ensure_loop()
        payload = (state,)
        if not self.__accept_source(
            sequence,
            payload,
            current_revision=self.__acquisition_revision,
            current_payload=self.__acquisition_payload,
            domain="acquisition",
        ):
            return self.__owner.snapshot()
        self.__owner.feed_acquisition(self.__authority.acquisition(sequence, state))
        self.__acquisition_revision = sequence
        self.__acquisition_payload = payload
        return self.__owner.snapshot()

    @staticmethod
    def __accept_source(
        revision: int,
        payload: tuple[object, ...],
        *,
        current_revision: int,
        current_payload: tuple[object, ...] | None,
        domain: str,
    ) -> bool:
        if any(type(value) not in {str, type(None), ExperimentOperation, AcquisitionLifecycle} for value in payload):
            raise TypeError(f"{domain} source payload requires exact lifecycle value types")
        if type(revision) is not int or revision < 1:
            raise ValueError(f"{domain} source revision must be a positive exact integer")
        if revision < current_revision:
            raise ValueError(f"{domain} source revision regression")
        if revision == current_revision:
            if payload != current_payload:
                raise ValueError(f"{domain} source same-revision equivocation")
            return False
        return True

    @staticmethod
    def __require_active_experiment(current: ExperimentRecordingSnapshot, experiment_id: str, operation: str) -> None:
        if current.experiment_operation is not ExperimentOperation.ACTIVE or current.experiment_id != experiment_id:
            raise ValueError(f"{operation} requires the exact active experiment")


__all__ = ["RecordingLifecycleFeed"]
