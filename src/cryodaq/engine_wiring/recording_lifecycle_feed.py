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

from cryodaq.engine_wiring.experiment_recording_owner import (
    AcquisitionLifecycle,
    ExperimentOperation,
    ExperimentRecordingOwner,
    ExperimentRecordingSnapshot,
    RecordingFeedAuthority,
)


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
        "__thread_id",
    )
    grants_control_authority = False

    def __init__(self) -> None:
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
        return self.__owner.snapshot()

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
