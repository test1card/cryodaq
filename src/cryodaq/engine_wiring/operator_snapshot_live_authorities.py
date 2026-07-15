"""Fail-closed adapters from current live owners to F36 authority receipts.

The adapters in this module only project immutable, constant-time owner cuts.
They perform no I/O and activate no producer, publisher, engine, or GUI path.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Protocol

from cryodaq.core.experiment import OperatorExperimentSnapshot
from cryodaq.engine_wiring.experiment_recording_owner import (
    ExperimentOperation,
    ExperimentRecordingOwner,
    ExperimentRecordingSnapshot,
)
from cryodaq.engine_wiring.operator_safety_snapshot import OperatorSafetySnapshot
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
    ExperimentReceipt,
    IntegrityPersistenceReceipt,
    PlantHealthEvidence,
    ReadinessEvidence,
    SafetyReadinessReceipt,
)
from cryodaq.engine_wiring.persistence_authority_owner import (
    PersistenceAuthorityOwner,
    PersistenceAuthoritySnapshot,
)
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.operator_snapshot import (
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    MAX_REASON_UTF8_BYTES,
    AvailabilityTruth,
    RecordingTruth,
)

_GENERATION_RE = re.compile(r"[0-9a-f]{32}")


class _ExperimentOwner(Protocol):
    def snapshot_operator_experiment(self) -> OperatorExperimentSnapshot: ...


class _SafetyOwner(Protocol):
    def snapshot_operator_safety(self) -> OperatorSafetySnapshot: ...


def _token(revision: int, domain: str, payload: str) -> str:
    digest = hashlib.sha256(f"{domain}-v1:{revision}:{payload}".encode()).hexdigest()
    return f"authority-v1:{revision}:{digest}"


def _unavailable(cut: CommonCut, reason: str) -> dict[str, object]:
    return {
        "cut": cut,
        "revision": 0,
        "token": _token(0, "unavailable", reason),
        "availability": AuthorityAvailability.UNAVAILABLE,
        "unavailable_reason": reason,
    }


def _exact_revision(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_NONNEGATIVE_INT:
        raise ValueError("revision or count is outside the signed 63-bit contract")
    return value


def _exact_text(
    value: object,
    *,
    limit: int = MAX_ID_UTF8_BYTES,
    optional: bool = False,
) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("owner snapshot identity must be exact non-empty text")
    encoded = value.encode("utf-8")
    if len(encoded) > limit or value != unicodedata.normalize("NFC", value):
        raise ValueError("owner snapshot identity exceeds its bounded text contract")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("owner snapshot identity contains forbidden control text")
    return value


def _generation_id(value: object) -> str:
    generation = _exact_text(value)
    assert generation is not None
    if _GENERATION_RE.fullmatch(generation) is None:
        raise ValueError("owner generation must be exact lowercase 128-bit hex")
    return generation


class LiveSafetyReadinessAuthority:
    """Map the SafetyManager's immutable cached proof cut conservatively."""

    __slots__ = ("__owner", "__last_revision", "__last_observed", "__last_token")

    def __init__(self, owner: _SafetyOwner) -> None:
        self.__owner = owner
        self.__last_revision = 0
        self.__last_observed = 0.0
        self.__last_token: str | None = None

    def snapshot_for_cut(self, cut: CommonCut) -> SafetyReadinessReceipt:
        try:
            snapshot = self.__owner.snapshot_operator_safety()
            if type(snapshot) is not OperatorSafetySnapshot:
                raise TypeError("wrong safety snapshot type")
            blockers = tuple(
                ReadinessEvidence(
                    item.code,
                    item.state,
                    item.operator_text,
                    item.required_evidence,
                )
                for item in snapshot.blockers
            )
            plant = tuple(
                PlantHealthEvidence(
                    item.subsystem_id,
                    item.display_name,
                    item.state,
                    item.reason_code,
                )
                for item in snapshot.plant_health
            )
            payload = json.dumps(
                {
                    "observed_monotonic_s": snapshot.observed_monotonic_s,
                    "lifecycle": snapshot.lifecycle.value,
                    "readiness": snapshot.readiness.value,
                    "verified_off": snapshot.verified_off,
                    "blockers": [
                        [item.code, item.state.value, item.operator_text, item.required_evidence]
                        for item in snapshot.blockers
                    ],
                    "plant_health": [
                        [item.subsystem_id, item.display_name, item.state.value, item.reason_code]
                        for item in snapshot.plant_health
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            token = _token(snapshot.revision, "safety", payload)
            if snapshot.revision < self.__last_revision:
                raise ValueError("safety revision regressed")
            if snapshot.observed_monotonic_s < self.__last_observed:
                raise ValueError("safety observed time regressed")
            if snapshot.revision == self.__last_revision and token != self.__last_token:
                raise ValueError("safety revision equivocated")
            receipt = SafetyReadinessReceipt(
                cut=cut,
                revision=snapshot.revision,
                token=token,
                availability=AuthorityAvailability.AVAILABLE,
                readiness=snapshot.readiness,
                verified_off=snapshot.verified_off,
                blockers=blockers,
                plant_health=plant,
            )
        except Exception:
            return SafetyReadinessReceipt(**_unavailable(cut, "safety_verified_off_cut_unavailable"))
        self.__last_revision = snapshot.revision
        self.__last_observed = snapshot.observed_monotonic_s
        self.__last_token = token
        return receipt


class LiveExperimentAuthority:
    """Map the experiment manager's immutable identity cut conservatively."""

    __slots__ = ("__owner", "__last_revision", "__last_token")

    def __init__(self, owner: _ExperimentOwner) -> None:
        self.__owner = owner
        self.__last_revision = 0
        self.__last_token: str | None = None

    def snapshot_for_cut(self, cut: CommonCut) -> ExperimentReceipt:
        snapshot = self.__owner.snapshot_operator_experiment()
        if type(snapshot) is not OperatorExperimentSnapshot:
            return ExperimentReceipt(**_unavailable(cut, "experiment_identity_cut_unavailable"))
        if type(snapshot.revision) is not int or snapshot.revision < 1:
            return ExperimentReceipt(**_unavailable(cut, "experiment_identity_revision_unavailable"))
        if any(
            value is not None and type(value) is not str
            for value in (
                snapshot.experiment_id,
                snapshot.experiment_name,
                snapshot.phase,
            )
        ):
            return ExperimentReceipt(**_unavailable(cut, "experiment_identity_cut_unavailable"))
        try:
            payload = json.dumps(
                [snapshot.experiment_id, snapshot.experiment_name, snapshot.phase],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            token = _token(snapshot.revision, "experiment", payload)
            receipt = ExperimentReceipt(
                cut=cut,
                revision=snapshot.revision,
                token=token,
                availability=AuthorityAvailability.AVAILABLE,
                experiment_id=snapshot.experiment_id,
                experiment_name=snapshot.experiment_name,
                phase=snapshot.phase,
                recording=RecordingTruth.UNKNOWN,
                recording_session_id=None,
            )
        except (TypeError, UnicodeError, ValueError):
            return ExperimentReceipt(**_unavailable(cut, "experiment_identity_cut_unavailable"))
        if snapshot.revision < self.__last_revision or (
            snapshot.revision == self.__last_revision and token != self.__last_token
        ):
            return ExperimentReceipt(**_unavailable(cut, "experiment_identity_revision_unavailable"))
        self.__last_revision = snapshot.revision
        self.__last_token = token
        return receipt


class LiveRecordingExperimentAuthority:
    """Project the recording owner's complete three-feed cut conservatively."""

    __slots__ = ("__owner", "__last_revision", "__last_token")

    def __init__(self, owner: ExperimentRecordingOwner | RecordingLifecycleFeed) -> None:
        if type(owner) not in (ExperimentRecordingOwner, RecordingLifecycleFeed):
            raise TypeError("owner must be an exact ExperimentRecordingOwner or exact RecordingLifecycleFeed")
        self.__owner = owner
        self.__last_revision = 0
        self.__last_token: str | None = None

    def snapshot_for_cut(self, cut: CommonCut) -> ExperimentReceipt:
        try:
            snapshot = self.__owner.snapshot()
            if type(snapshot) is not ExperimentRecordingSnapshot:
                raise TypeError("wrong recording snapshot type")
            revision = _exact_revision(snapshot.revision, minimum=1)
            feed_revisions = (
                _exact_revision(snapshot.experiment_revision, minimum=1),
                _exact_revision(snapshot.acquisition_revision, minimum=1),
                _exact_revision(snapshot.persistence_revision, minimum=1),
            )
            _exact_text(snapshot.owner_id)
            generation_id = _generation_id(snapshot.generation_id)
            _exact_text(snapshot.acquisition_epoch_id, optional=True)
            _exact_text(snapshot.persistence_epoch_id, optional=True)
            _exact_text(snapshot.reason, limit=MAX_REASON_UTF8_BYTES)
            if type(snapshot.experiment_operation) is not ExperimentOperation:
                raise TypeError("wrong experiment operation type")
            if type(snapshot.recording) is not RecordingTruth:
                raise TypeError("wrong recording truth type")
            if snapshot.experiment_operation is ExperimentOperation.ACTIVE:
                _exact_text(snapshot.experiment_id)
                _exact_text(snapshot.experiment_name)
                _exact_text(snapshot.phase, optional=True)
            elif any(value is not None for value in (snapshot.experiment_id, snapshot.experiment_name, snapshot.phase)):
                raise ValueError("inactive experiment snapshot carries identity")
            if snapshot.experiment_operation is ExperimentOperation.UNAVAILABLE:
                raise ValueError("experiment operation is unavailable")
            if snapshot.recording is RecordingTruth.RECORDING:
                if (
                    snapshot.experiment_operation is not ExperimentOperation.ACTIVE
                    or snapshot.acquisition_epoch_id is None
                    or snapshot.persistence_epoch_id is None
                ):
                    raise ValueError("recording lacks active experiment/acquisition/persistence proof")
                session_id = _exact_text(snapshot.recording_session_id)
                assert session_id is not None
                prefix = f"recording-v1:{generation_id}:"
                if not session_id.startswith(prefix):
                    raise ValueError("recording session does not belong to the owner generation")
                counter = session_id.removeprefix(prefix)
                if re.fullmatch(r"[1-9a-f][0-9a-f]*", counter) is None or int(counter, 16) > MAX_NONNEGATIVE_INT:
                    raise ValueError("recording session counter is invalid")
            elif snapshot.recording_session_id is not None:
                raise ValueError("non-recording snapshot carries a recording session")
            payload = json.dumps(
                [
                    snapshot.owner_id,
                    snapshot.generation_id,
                    *feed_revisions,
                    snapshot.acquisition_epoch_id,
                    snapshot.persistence_epoch_id,
                    snapshot.experiment_operation.value,
                    snapshot.experiment_id,
                    snapshot.experiment_name,
                    snapshot.phase,
                    snapshot.recording.value,
                    snapshot.recording_session_id,
                    snapshot.reason,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            token = _token(revision, "experiment-recording", payload)
            if revision < self.__last_revision or (revision == self.__last_revision and token != self.__last_token):
                raise ValueError("recording revision regressed or equivocated")
            receipt = ExperimentReceipt(
                cut=cut,
                revision=revision,
                token=token,
                availability=AuthorityAvailability.AVAILABLE,
                experiment_id=snapshot.experiment_id,
                experiment_name=snapshot.experiment_name,
                phase=snapshot.phase,
                recording=snapshot.recording,
                recording_session_id=snapshot.recording_session_id,
            )
        except Exception:
            return ExperimentReceipt(**_unavailable(cut, "experiment_recording_cut_unavailable"))
        self.__last_revision = revision
        self.__last_token = token
        return receipt


class LiveIntegrityPersistenceAuthority:
    """Project the persistence owner's coherent receipt/counter cut."""

    __slots__ = ("__owner", "__last_revision", "__last_token")

    def __init__(self, owner: PersistenceAuthorityOwner | RecordingLifecycleFeed) -> None:
        if type(owner) not in (PersistenceAuthorityOwner, RecordingLifecycleFeed):
            raise TypeError("owner must be an exact PersistenceAuthorityOwner or exact RecordingLifecycleFeed")
        self.__owner = owner
        self.__last_revision = 0
        self.__last_token: str | None = None

    def snapshot_for_cut(self, cut: CommonCut) -> IntegrityPersistenceReceipt:
        try:
            snapshot = (
                self.__owner.persistence_snapshot()
                if type(self.__owner) is RecordingLifecycleFeed
                else self.__owner.snapshot()
            )
            if type(snapshot) is not PersistenceAuthoritySnapshot:
                raise TypeError("wrong persistence snapshot type")
            revision = _exact_revision(snapshot.revision, minimum=1)
            receipt_revision = _exact_revision(snapshot.receipt_revision, minimum=1)
            if revision > receipt_revision:
                raise ValueError("persistence owner revision exceeds receipt sequence")
            _exact_text(snapshot.owner_id)
            _generation_id(snapshot.generation_id)
            _exact_text(snapshot.recording_epoch_id)
            _exact_text(snapshot.reason, limit=MAX_REASON_UTF8_BYTES)
            persisted_revision = _exact_revision(snapshot.committed_materialization_revision)
            archive_revision = (
                None if snapshot.archive_revision is None else _exact_revision(snapshot.archive_revision, minimum=1)
            )
            pending_records = _exact_revision(snapshot.pending_count)
            dropped_records = _exact_revision(snapshot.dropped_or_rejected_count)
            if type(snapshot.storage) is not AvailabilityTruth:
                raise TypeError("wrong persistence storage truth type")
            payload = json.dumps(
                [
                    snapshot.owner_id,
                    snapshot.generation_id,
                    receipt_revision,
                    snapshot.recording_epoch_id,
                    persisted_revision,
                    archive_revision,
                    pending_records,
                    dropped_records,
                    snapshot.storage.value,
                    snapshot.reason,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            token = _token(revision, "integrity-persistence", payload)
            if revision < self.__last_revision or (revision == self.__last_revision and token != self.__last_token):
                raise ValueError("persistence revision regressed or equivocated")
            receipt = IntegrityPersistenceReceipt(
                cut=cut,
                revision=revision,
                token=token,
                availability=AuthorityAvailability.AVAILABLE,
                persisted_revision=persisted_revision,
                archive_revision=archive_revision,
                pending_records=pending_records,
                dropped_records=dropped_records,
                storage=snapshot.storage,
            )
        except Exception:
            return IntegrityPersistenceReceipt(**_unavailable(cut, "persistence_coherent_cut_unavailable"))
        self.__last_revision = revision
        self.__last_token = token
        return receipt


__all__ = [
    "LiveExperimentAuthority",
    "LiveIntegrityPersistenceAuthority",
    "LiveRecordingExperimentAuthority",
    "LiveSafetyReadinessAuthority",
]
