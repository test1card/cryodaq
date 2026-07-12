"""Fail-closed adapters from current live owners to F36 authority receipts.

Only the experiment owner presently exposes a constant-time immutable cut.
Safety lacks explicit verified-OFF/transition proof, and persistence lacks a
coherent durable revision/pending/drop owner.  Those adapters therefore emit
typed UNAVAILABLE receipts so the mandatory composer remains dark.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from cryodaq.core.experiment import OperatorExperimentSnapshot
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
from cryodaq.operator_snapshot import RecordingTruth


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


class LiveIntegrityPersistenceAuthority:
    """Deliberately dark until one persistence coordinator owns all counters."""

    __slots__ = ("__owner",)

    def __init__(self, owner: object) -> None:
        self.__owner = owner

    def snapshot_for_cut(self, cut: CommonCut) -> IntegrityPersistenceReceipt:
        _ = self.__owner
        return IntegrityPersistenceReceipt(**_unavailable(cut, "persistence_coherent_cut_unavailable"))


__all__ = [
    "LiveExperimentAuthority",
    "LiveIntegrityPersistenceAuthority",
    "LiveSafetyReadinessAuthority",
]
