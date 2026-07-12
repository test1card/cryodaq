"""Dark lifecycle seam for observational operator-snapshot publication.

The service owns no socket and no engine/GUI/control capability.  A future
engine wiring slice may supervise exactly one ``run`` coroutine and inject the
already-authoritative composer plus the sole :class:`ZMQPublisher` instance.
Until then this module is deliberately unwired.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from cryodaq.operator_snapshot import OperatorSnapshot


class SnapshotComposer(Protocol):
    async def compose(self, observed_at: datetime) -> OperatorSnapshot: ...


class SnapshotPublisher(Protocol):
    async def publish_operator_snapshot(self, snapshot: OperatorSnapshot) -> bool: ...


class SnapshotPublicationErrorCode(StrEnum):
    COMPOSITION_FAILED = "composition_failed"
    INVALID_SNAPSHOT_SEQUENCE = "invalid_snapshot_sequence"
    PUBLICATION_FAILED = "publication_failed"


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


class OperatorSnapshotPublicationService:
    """One-owner, bounded-cadence publication loop for complete snapshots."""

    def __init__(
        self,
        *,
        composer: SnapshotComposer,
        publisher: SnapshotPublisher,
        cadence_hz: float = 1.0,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(getattr(composer, "compose", None)):
            raise TypeError("composer must expose callable compose")
        if not callable(getattr(publisher, "publish_operator_snapshot", None)):
            raise TypeError("publisher must expose callable publish_operator_snapshot")
        if type(cadence_hz) not in (int, float) or not math.isfinite(cadence_hz):
            raise TypeError("cadence_hz must be a finite exact number")
        if cadence_hz <= 0 or cadence_hz > 2:
            raise ValueError("cadence_hz must be greater than zero and at most 2 Hz")
        if not callable(clock) or not callable(monotonic):
            raise TypeError("clock and monotonic must be callable")
        self._composer = composer
        self._publisher = publisher
        self._cadence_hz = float(cadence_hz)
        self._interval_s = 1.0 / self._cadence_hz
        if not math.isfinite(self._interval_s) or self._interval_s <= 0:
            raise ValueError("cadence_hz must have a finite positive interval")
        self._clock = clock
        self._monotonic = monotonic
        self._stop_requested = asyncio.Event()
        self._owner_task: asyncio.Task[object] | None = None
        self._attempt_lock = asyncio.Lock()
        self._next_due = 0.0
        self._last_monotonic: float | None = None
        self._source: str | None = None
        self._last_composed_revision = 0
        self._last_composed_received_at: datetime | None = None
        self._last_published_revision = 0
        self._composition_failure_count = 0
        self._publication_failure_count = 0
        self._coalesced_count = 0
        self._last_error_code: SnapshotPublicationErrorCode | None = None

    @property
    def cadence_hz(self) -> float:
        return self._cadence_hz

    @property
    def running(self) -> bool:
        return self._owner_task is not None

    @property
    def composition_failure_count(self) -> int:
        return self._composition_failure_count

    @property
    def publication_failure_count(self) -> int:
        return self._publication_failure_count

    @property
    def coalesced_count(self) -> int:
        return self._coalesced_count

    @property
    def last_published_revision(self) -> int:
        return self._last_published_revision

    @property
    def last_error_code(self) -> SnapshotPublicationErrorCode | None:
        return self._last_error_code

    def request_stop(self) -> None:
        """Ask the sole supervised ``run`` owner to settle at a safe boundary."""
        self._stop_requested.set()

    async def run(self) -> None:
        """Run until stopped or cancelled; a second lifecycle owner is refused."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("publication service requires an asyncio task")
        if self._owner_task is not None:
            raise RuntimeError("operator snapshot publication already has an owner")
        self._owner_task = task
        self._stop_requested.clear()
        try:
            self._next_due = self._monotonic_now()
            while not self._stop_requested.is_set():
                await self._publish_if_due()
                delay = max(0.0, self._next_due - self._monotonic_now())
                if delay == 0:
                    await asyncio.sleep(0)
                    continue
                try:
                    async with asyncio.timeout(delay):
                        await self._stop_requested.wait()
                except TimeoutError:
                    pass
        finally:
            self._owner_task = None

    async def _publish_if_due(self) -> bool:
        """Attempt one complete cut; overlapping/early triggers coalesce."""
        async with self._attempt_lock:
            started = self._monotonic_now()
            if started < self._next_due:
                self._coalesced_count += 1
                return False
            task = asyncio.current_task()
            cancellation_baseline = task.cancelling() if task is not None else 0
            cancelled = False
            try:
                try:
                    observed_at = _exact_utc(self._clock(), field="clock result")
                    snapshot = await self._composer.compose(observed_at)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._composition_failure_count += 1
                    self._last_error_code = SnapshotPublicationErrorCode.COMPOSITION_FAILED
                    return False

                try:
                    self._validate_sequence(snapshot)
                except (TypeError, ValueError):
                    self._composition_failure_count += 1
                    self._last_error_code = SnapshotPublicationErrorCode.INVALID_SNAPSHOT_SEQUENCE
                    return False

                try:
                    published = await self._publisher.publish_operator_snapshot(snapshot)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    published = False
                if published is not True:
                    self._publication_failure_count += 1
                    self._last_error_code = SnapshotPublicationErrorCode.PUBLICATION_FAILED
                    return False
                self._last_published_revision = snapshot.cut.revision
                self._last_error_code = None
                return True
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                # Never catch up with a burst after a slow/failing attempt.
                # Cancellation has priority over an injected-clock failure.
                newly_cancelling = task is not None and task.cancelling() > cancellation_baseline
                if not cancelled and not newly_cancelling:
                    self._next_due = self._monotonic_now() + self._interval_s

    def _monotonic_now(self) -> float:
        raw = self._monotonic()
        if type(raw) not in (int, float):
            raise TypeError("monotonic result must be an exact int or float")
        try:
            value = float(raw)
        except (OverflowError, ValueError) as exc:
            raise ValueError("monotonic result must be finite") from exc
        if not math.isfinite(value):
            raise ValueError("monotonic result must be finite")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic result regressed")
        self._last_monotonic = value
        return value

    def _validate_sequence(self, snapshot: object) -> None:
        if type(snapshot) is not OperatorSnapshot:
            raise TypeError("composer must return an exact OperatorSnapshot")
        cut = snapshot.cut
        received_at = _exact_utc(cut.received_at, field="snapshot received_at")
        if self._source is None:
            self._source = cut.source
        elif cut.source != self._source:
            raise ValueError("snapshot leadership source changed")
        if cut.revision <= self._last_composed_revision:
            raise ValueError("snapshot revision did not increase")
        if self._last_composed_received_at is not None and received_at < self._last_composed_received_at:
            raise ValueError("snapshot received_at regressed")
        self._last_composed_revision = cut.revision
        self._last_composed_received_at = received_at


__all__ = [
    "OperatorSnapshotPublicationService",
    "SnapshotPublicationErrorCode",
]
