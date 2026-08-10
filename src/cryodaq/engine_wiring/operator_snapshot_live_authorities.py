"""Fail-closed adapters from current live owners to F36 authority receipts.

Receipt adapters project immutable, constant-time owner cuts without I/O.  The
engine-owned attention feed separately settles durable incident annotations;
it never owns or mutates canonical alarm state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from cryodaq.core.alarm_v2 import AlarmCanonicalSnapshot, AlarmStateManager
from cryodaq.core.event_bus import EngineEvent
from cryodaq.core.experiment import OperatorExperimentSnapshot
from cryodaq.core.operator_log import AttentionHistoryItem
from cryodaq.engine_wiring.experiment_recording_owner import (
    ExperimentOperation,
    ExperimentRecordingOwner,
    ExperimentRecordingSnapshot,
)
from cryodaq.engine_wiring.operator_safety_snapshot import OperatorSafetySnapshot
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AlarmAttentionReceipt,
    AlarmEvidence,
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
from cryodaq.storage.sqlite_writer import SQLiteWriter

_GENERATION_RE = re.compile(r"[0-9a-f]{32}")
logger = logging.getLogger(__name__)

_NO_ACTIVE_EXPERIMENT_ID = "no-active-experiment"

# The SafetyManager refreshes its immutable operator cut once per second.  A
# live receipt may survive at most three missed refresh periods; beyond that
# the adapter must stop projecting even an otherwise valid READY snapshot.
SAFETY_SNAPSHOT_FRESHNESS_BUDGET_S = 3.0


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


class DurableAttentionHistoryFeed:
    """Persist alarm incidents before EventBus fanout and retain one revision."""

    __slots__ = ("__writer", "__lock", "__started", "__pending", "__revision", "__failure_latched")

    def __init__(self, writer: SQLiteWriter) -> None:
        if type(writer) is not SQLiteWriter:
            raise TypeError("writer must be the exact engine SQLiteWriter")
        self.__writer = writer
        self.__lock = asyncio.Lock()
        self.__started = False
        self.__pending = 0
        self.__revision: int | None = None
        self.__failure_latched = False

    async def start(self) -> None:
        if self.__started:
            raise RuntimeError("durable attention history feed is already started")
        page = await self.__writer.get_attention_history(
            experiment_id=_NO_ACTIVE_EXPERIMENT_ID,
            limit=1,
        )
        self.__revision = page.through_revision
        self.__failure_latched = False
        self.__started = True

    def stop(self) -> None:
        if self.__pending:
            raise RuntimeError("durable attention history feed still owns pending persistence")
        self.__started = False
        self.__revision = None
        self.__failure_latched = False

    @property
    def current_revision(self) -> int | None:
        if not self.__started or self.__pending or self.__failure_latched:
            return None
        return self.__revision

    async def persist_event(self, event: EngineEvent) -> None:
        """Settle exact alarm persistence through cancellation before returning."""

        if type(event) is not EngineEvent:
            raise TypeError("attention persistence requires an exact EngineEvent")
        if event.event_type != "alarm_fired":
            return
        if not self.__started:
            raise RuntimeError("durable attention history feed is not started")
        if event.experiment_id is not None and (type(event.experiment_id) is not str or not event.experiment_id):
            raise ValueError("attention event experiment identity is invalid")
        persisted_event = EngineEvent(
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload,
            experiment_id=event.experiment_id or _NO_ACTIVE_EXPERIMENT_ID,
        )
        self.__pending += 1
        owner = asyncio.create_task(
            self.__persist_owned(persisted_event),
            name="durable_attention_history_append",
        )
        cancellation_seen = False
        persistence_failure: Exception | None = None
        try:
            while not owner.done():
                try:
                    await asyncio.shield(owner)
                except asyncio.CancelledError:
                    cancellation_seen = True
                except Exception:
                    pass
            try:
                owner.result()
            except Exception as exc:
                persistence_failure = exc
        finally:
            self.__pending -= 1
        if persistence_failure is not None:
            logger.error(
                "Durable attention history unavailable; exception=%s",
                type(persistence_failure).__name__,
            )
        if cancellation_seen:
            raise asyncio.CancelledError

    async def annotate_acknowledgement(
        self,
        incident: AttentionHistoryItem,
        *,
        actor: str,
        note: str,
        timestamp: datetime,
    ) -> AttentionHistoryItem:
        """Append operator awareness while retaining the new durable cut."""

        if not self.__started:
            raise RuntimeError("durable attention history feed is not started")
        self.__pending += 1
        owner = asyncio.create_task(
            self.__annotate_owned(
                incident,
                actor=actor,
                note=note,
                timestamp=timestamp,
            ),
            name="durable_attention_history_acknowledgement",
        )
        cancellation_seen = False
        try:
            while not owner.done():
                try:
                    await asyncio.shield(owner)
                except asyncio.CancelledError:
                    cancellation_seen = True
            annotation = owner.result()
        finally:
            self.__pending -= 1
        if cancellation_seen:
            raise asyncio.CancelledError
        return annotation

    async def __persist_owned(self, event: EngineEvent) -> None:
        async with self.__lock:
            failure: BaseException | None = None
            try:
                await self.__writer.append_attention_event(event)
            except BaseException as exc:  # retain failure through revision refresh
                failure = exc
            try:
                page = await self.__writer.get_attention_history(
                    experiment_id=event.experiment_id or _NO_ACTIVE_EXPERIMENT_ID,
                    limit=1,
                )
                revision = page.through_revision
                if self.__revision is not None and revision < self.__revision:
                    raise RuntimeError("durable attention history revision regressed")
                self.__revision = revision
            except BaseException:
                self.__revision = None
                self.__failure_latched = True
                raise
            if failure is not None:
                self.__failure_latched = True
                raise failure

    async def __annotate_owned(
        self,
        incident: AttentionHistoryItem,
        *,
        actor: str,
        note: str,
        timestamp: datetime,
    ) -> AttentionHistoryItem:
        async with self.__lock:
            failure: BaseException | None = None
            annotation: AttentionHistoryItem | None = None
            try:
                annotation = await self.__writer.annotate_attention_acknowledgement(
                    incident,
                    actor=actor,
                    note=note,
                    timestamp=timestamp,
                )
            except BaseException as exc:  # retain failure through revision refresh
                failure = exc
            try:
                page = await self.__writer.get_attention_history(
                    experiment_id=incident.experiment_id,
                    limit=1,
                )
                revision = page.through_revision
                if self.__revision is not None and revision < self.__revision:
                    raise RuntimeError("durable attention history revision regressed")
                self.__revision = revision
            except BaseException:
                self.__revision = None
                self.__failure_latched = True
                raise
            if failure is not None:
                self.__failure_latched = True
                raise failure
            if annotation is None:
                raise RuntimeError("attention acknowledgement produced no durable item")
            return annotation


class LiveAlarmAttentionAuthority:
    """Project the exact canonical alarm cut at the durable history revision."""

    __slots__ = (
        "__owner",
        "__history_feed",
        "__last_state_revision",
        "__last_history_revision",
        "__last_payload",
        "__receipt_revision",
    )

    def __init__(
        self,
        owner: AlarmStateManager,
        history_feed: DurableAttentionHistoryFeed,
    ) -> None:
        if type(owner) is not AlarmStateManager:
            raise TypeError("owner must be the exact AlarmStateManager")
        if type(history_feed) is not DurableAttentionHistoryFeed:
            raise TypeError("history_feed must be the exact DurableAttentionHistoryFeed")
        self.__owner = owner
        self.__history_feed = history_feed
        self.__last_state_revision = 0
        self.__last_history_revision = 0
        self.__last_payload: str | None = None
        self.__receipt_revision = 0

    def snapshot_for_cut(self, cut: CommonCut) -> AlarmAttentionReceipt:
        try:
            snapshot = self.__owner.snapshot_active_canonical()
            if type(snapshot) is not AlarmCanonicalSnapshot:
                raise TypeError("wrong canonical alarm snapshot type")
            state_revision = _exact_revision(snapshot.state_revision)
            history_revision = self.__history_feed.current_revision
            if history_revision is None:
                raise ValueError("durable attention history cut is unavailable")
            history_revision = _exact_revision(history_revision)
            _exact_text(snapshot.state_token)
            if state_revision < self.__last_state_revision or history_revision < self.__last_history_revision:
                raise ValueError("alarm or attention history revision regressed")
            if type(snapshot.active) is not dict:
                raise TypeError("canonical active alarm mapping is invalid")
            alarms: list[AlarmEvidence] = []
            for alarm_id in sorted(snapshot.active):
                item = snapshot.active[alarm_id]
                if type(item) is not dict or set(item) != {
                    "level",
                    "triggered_at",
                    "channels",
                    "acknowledged",
                    "acknowledged_at",
                }:
                    raise ValueError("canonical active alarm item is invalid")
                alarms.append(
                    AlarmEvidence(
                        alarm_id,
                        item["level"],
                        datetime.fromtimestamp(item["triggered_at"], UTC),
                        item["acknowledged"],
                    )
                )
            payload = json.dumps(
                [state_revision, snapshot.state_token, history_revision],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if payload != self.__last_payload:
                if self.__receipt_revision >= MAX_NONNEGATIVE_INT:
                    raise OverflowError("alarm attention authority revision exhausted")
                receipt_revision = self.__receipt_revision + 1
            else:
                receipt_revision = self.__receipt_revision
            if receipt_revision < 1:
                raise ValueError("alarm attention authority revision is unavailable")
            receipt = AlarmAttentionReceipt(
                cut=cut,
                revision=receipt_revision,
                token=_token(receipt_revision, "alarm-attention", payload),
                availability=AuthorityAvailability.AVAILABLE,
                alarms=tuple(alarms),
                history_revision=history_revision,
            )
        except Exception:
            return AlarmAttentionReceipt(**_unavailable(cut, "attention_authority_unavailable"))
        self.__last_state_revision = state_revision
        self.__last_history_revision = history_revision
        self.__last_payload = payload
        self.__receipt_revision = receipt_revision
        return receipt


class LiveSafetyReadinessAuthority:
    """Map the SafetyManager's immutable cached proof cut conservatively."""

    __slots__ = (
        "__owner",
        "__freshness_budget_s",
        "__monotonic",
        "__last_revision",
        "__last_observed",
        "__last_token",
    )

    def __init__(
        self,
        owner: _SafetyOwner,
        *,
        freshness_budget_s: float = SAFETY_SNAPSHOT_FRESHNESS_BUDGET_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(freshness_budget_s) is not float or not math.isfinite(freshness_budget_s) or freshness_budget_s <= 0.0:
            raise ValueError("freshness_budget_s must be an exact finite positive float")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        self.__owner = owner
        self.__freshness_budget_s = freshness_budget_s
        self.__monotonic = monotonic
        self.__last_revision = 0
        self.__last_observed = 0.0
        self.__last_token: str | None = None

    def snapshot_for_cut(self, cut: CommonCut) -> SafetyReadinessReceipt:
        try:
            snapshot = self.__owner.snapshot_operator_safety()
            if type(snapshot) is not OperatorSafetySnapshot:
                raise TypeError("wrong safety snapshot type")
            sampled_monotonic = self.__monotonic()
            if type(sampled_monotonic) not in (int, float):
                raise ValueError("monotonic clock must return an exact finite non-negative number")
            sampled_monotonic_s = float(sampled_monotonic)
            age_s = sampled_monotonic_s - snapshot.observed_monotonic_s
            if (
                not math.isfinite(sampled_monotonic_s)
                or sampled_monotonic_s < 0.0
                or not math.isfinite(age_s)
                or age_s < 0.0
                or age_s > self.__freshness_budget_s
            ):
                raise ValueError("safety snapshot is expired or is dated in the future")
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
                lifecycle=snapshot.lifecycle,
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
    "DurableAttentionHistoryFeed",
    "LiveAlarmAttentionAuthority",
    "LiveExperimentAuthority",
    "LiveIntegrityPersistenceAuthority",
    "LiveRecordingExperimentAuthority",
    "LiveSafetyReadinessAuthority",
    "SAFETY_SNAPSHOT_FRESHNESS_BUDGET_S",
]
