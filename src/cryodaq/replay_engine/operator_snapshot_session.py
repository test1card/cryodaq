"""Pure, unwired replay operator-snapshot session contract.

The current replay engine has no reviewed typed authorities for attention,
plant health, infrastructure, persistence, or support bundles.  This module
therefore does not inspect readings, command payloads, GUI state, or source
private fields.  It accepts only an explicit detached archive-evidence receipt
and emits a conservative complete REPLAY snapshot through the existing neutral
protocol.  ``ReplayEngine`` wiring remains a later reviewed atom.
"""

from __future__ import annotations

import asyncio
import math
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cryodaq.operator_snapshot import (
    MAX_NONNEGATIVE_INT,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_NONCE_RE = re.compile(r"[0-9a-f]{32}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReplaySnapshotEvidenceAdapter(Protocol):
    """Future archive adapter boundary; no implementation is activated yet."""

    def snapshot_evidence(self, *, epoch: int) -> ReplaySnapshotEvidence: ...


class ReplaySnapshotPublisher(Protocol):
    async def publish_operator_snapshot(self, snapshot: OperatorSnapshot) -> bool: ...


class ReplaySnapshotPublicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReplaySnapshotEvidence:
    """Detached historical facts an archive adapter may truthfully provide."""

    observed_at: datetime
    experiment_id: str | None = None
    experiment_name: str | None = None
    phase: str | None = None
    cooldown_samples: tuple[CooldownSample, ...] = ()
    cooldown_reference_id: str | None = None
    cooldown_reference: tuple[CooldownSample, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observed_at",
            _exact_utc(self.observed_at, field="observed_at"),
        )
        for field in ("experiment_id", "experiment_name", "phase", "cooldown_reference_id"):
            value = getattr(self, field)
            if value is not None and (type(value) is not str or not value or value != value.strip()):
                raise ValueError(f"{field} must be a non-empty exact string without surrounding whitespace")
        _exact_samples(self.cooldown_samples, field="cooldown_samples")
        _exact_samples(self.cooldown_reference, field="cooldown_reference")
        if self.cooldown_reference and self.cooldown_reference_id is None:
            raise ValueError("cooldown reference samples require reference identity")


class ReplayOperatorSnapshotSession:
    """One replay leadership session with explicit seek epochs and ordering."""

    def __init__(
        self,
        *,
        archive_fingerprint: str,
        session_nonce: str | None = None,
        initial_revision: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(archive_fingerprint) is not str or _SHA256_RE.fullmatch(archive_fingerprint) is None:
            raise ValueError("archive_fingerprint must be 64 lowercase hexadecimal characters")
        nonce = secrets.token_hex(16) if session_nonce is None else session_nonce
        if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
            raise ValueError("session_nonce must be 128 bits of lowercase hexadecimal")
        if type(initial_revision) is not int or not 0 <= initial_revision <= MAX_NONNEGATIVE_INT:
            raise ValueError("initial_revision must be an exact bounded non-negative integer")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._fingerprint = archive_fingerprint
        self._nonce = nonce
        self._clock = _utc_now if clock is None else clock
        self._revision = initial_revision
        self._epoch = 0
        self._last_received_at: datetime | None = None
        self._closed = False
        self._publish_lock = asyncio.Lock()
        self._state_lock = threading.Lock()

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def source(self) -> str:
        return f"replay/operator-v1/{self._fingerprint[:32]}/{self._nonce}/{self._epoch:016x}"

    def begin_seek_epoch(self) -> str:
        """Start an explicit source epoch without resetting global revision."""
        self._begin_operation()
        try:
            if self._epoch >= MAX_NONNEGATIVE_INT:
                raise OverflowError("replay seek epoch exhausted")
            self._epoch += 1
            return self.source
        finally:
            self._end_operation()

    def compose(self, evidence: ReplaySnapshotEvidence) -> OperatorSnapshot:
        """Compose one conservative complete cut without reading hidden state."""
        self._begin_operation()
        try:
            return self._compose_owned(evidence)
        finally:
            self._end_operation()

    def compose_from(self, adapter: ReplaySnapshotEvidenceAdapter) -> OperatorSnapshot:
        self._begin_operation()
        try:
            if not callable(getattr(adapter, "snapshot_evidence", None)):
                raise TypeError("adapter must expose snapshot_evidence")
            epoch = self._epoch
            source = self.source
            evidence = adapter.snapshot_evidence(epoch=epoch)
            if self._epoch != epoch or self.source != source:
                raise RuntimeError("replay epoch changed during adapter snapshot")
            return self._compose_owned(evidence)
        finally:
            self._end_operation()

    async def compose_and_publish(
        self,
        evidence: ReplaySnapshotEvidence,
        publisher: ReplaySnapshotPublisher,
    ) -> OperatorSnapshot:
        """Publish once through the existing observational publisher authority."""
        if not callable(getattr(publisher, "publish_operator_snapshot", None)):
            raise TypeError("publisher must expose publish_operator_snapshot")
        async with self._publish_lock:
            self._begin_operation()
            try:
                snapshot = self._compose_owned(evidence)
                try:
                    published = await publisher.publish_operator_snapshot(snapshot)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise ReplaySnapshotPublicationError("replay snapshot publication failed") from exc
                if published is not True:
                    raise ReplaySnapshotPublicationError("replay snapshot publication failed")
                return snapshot
            finally:
                self._end_operation()

    def close(self) -> None:
        if self._closed:
            return
        self._begin_operation()
        try:
            self._closed = True
        finally:
            self._end_operation()

    def _compose_owned(self, evidence: ReplaySnapshotEvidence) -> OperatorSnapshot:
        if type(evidence) is not ReplaySnapshotEvidence:
            raise TypeError("adapter must return an exact ReplaySnapshotEvidence")
        if self._revision >= MAX_NONNEGATIVE_INT:
            raise OverflowError("replay snapshot revision exhausted")
        received_at = _exact_utc(self._clock(), field="clock result")
        if self._last_received_at is not None and received_at <= self._last_received_at:
            raise ValueError("replay received_at must increase strictly")
        if evidence.observed_at > received_at:
            raise ValueError("replay observed_at cannot be later than received_at")
        revision = self._revision + 1
        snapshot = _build_replay_snapshot(
            evidence,
            revision=revision,
            received_at=received_at,
            source=self.source,
        )
        self._revision = revision
        self._last_received_at = received_at
        return snapshot

    def _begin_operation(self) -> None:
        if not self._state_lock.acquire(blocking=False):
            raise RuntimeError("replay snapshot session operation already in progress")
        try:
            self._require_open()
        except BaseException:
            self._state_lock.release()
            raise

    def _end_operation(self) -> None:
        self._state_lock.release()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("replay snapshot session is closed")


def _build_replay_snapshot(
    evidence: ReplaySnapshotEvidence,
    *,
    revision: int,
    received_at: datetime,
    source: str,
) -> OperatorSnapshot:
    cut = SnapshotCut(
        revision,
        evidence.observed_at,
        received_at,
        source,
        SnapshotMode.REPLAY,
        evidence.experiment_id or "no-active-experiment",
        source,
    )
    source_age = (received_at - evidence.observed_at).total_seconds()

    def status(reason: str, text: str) -> SummaryStatus:
        return SummaryStatus(
            OperatorPresentationState.STALE,
            source_age,
            0.0,
            (reason,),
            text,
        )

    return OperatorSnapshot(
        cut,
        ReadinessSummary(
            cut,
            status("replay_readiness_unavailable", "Replay cannot authorize readiness"),
            ReadinessTruth.UNKNOWN,
            (),
            SafetyLifecycle.UNKNOWN,
        ),
        PlantHealthSummary(
            cut,
            status("replay_plant_authority_unavailable", "Current plant health unavailable in replay"),
            (),
        ),
        InfrastructureNodeHealth(
            cut,
            status(
                "infrastructure_authority_unavailable",
                "Infrastructure authority unavailable in replay",
            ),
            (),
        ),
        AttentionQueue(
            cut,
            status("attention_authority_unavailable", "Attention history authority unavailable in replay"),
            (),
        ),
        ExperimentOperatingState(
            cut,
            status("replay_historical_context", "Historical replay context"),
            evidence.experiment_id,
            evidence.experiment_name,
            evidence.phase,
            RecordingTruth.REPLAY_ONLY,
            None,
        ),
        DataIntegritySummary(
            cut,
            status("replay_storage_authority_unavailable", "Current storage authority unavailable in replay"),
            0,
            None,
            0,
            0,
            AvailabilityTruth.UNKNOWN,
        ),
        CooldownHistorySummary(
            cut,
            status("replay_historical_context", "Historical cooldown evidence"),
            evidence.cooldown_samples,
            evidence.cooldown_reference_id,
            evidence.cooldown_reference,
        ),
        SupportBundleSummary(
            cut,
            status("support_authority_unavailable", "Support authority unavailable in replay"),
            AvailabilityTruth.UNKNOWN,
            None,
        ),
    )


def _exact_utc(value: object, *, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{field} must be an exact timezone-aware datetime")
    normalized = value.astimezone(UTC)
    return datetime(
        normalized.year,
        normalized.month,
        normalized.day,
        normalized.hour,
        normalized.minute,
        normalized.second,
        normalized.microsecond,
        tzinfo=UTC,
        fold=normalized.fold,
    )


def _exact_samples(samples: object, *, field: str) -> None:
    if type(samples) is not tuple or any(type(sample) is not CooldownSample for sample in samples):
        raise TypeError(f"{field} must be an exact tuple of CooldownSample")
    elapsed = tuple(sample.elapsed_s for sample in samples)
    if any(not math.isfinite(value) for value in elapsed):
        raise ValueError(f"{field} elapsed values must be finite")


__all__ = [
    "ReplayOperatorSnapshotSession",
    "ReplaySnapshotEvidence",
    "ReplaySnapshotEvidenceAdapter",
    "ReplaySnapshotPublicationError",
]
