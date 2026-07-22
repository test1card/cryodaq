"""Single GUI-thread owner joining decoded cuts to presentation freshness."""

from __future__ import annotations

import math
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from cryodaq.gui.state.operator_view_models import OperatorSnapshotStore
from cryodaq.operator_snapshot import OperatorSnapshot

_DEFAULT_STALE_AFTER_S = 10.0
_HEALTH_POLL_INTERVAL_S = 0.5
_MAX_COUNTER = (1 << 64) - 1


class OperatorSnapshotIngressOwner(QObject):
    """Own exactly one store and mutate it only through queued GUI slots."""

    snapshot_changed = Signal(object)
    _snapshot_queued = Signal(int, object)
    _transport_queued = Signal(int)
    _failure_queued = Signal(int)

    def __init__(
        self,
        bridge: Any,
        *,
        stale_after_s: float = _DEFAULT_STALE_AFTER_S,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not callable(getattr(bridge, "poll_operator_snapshots", None)):
            raise TypeError("bridge must expose poll_operator_snapshots")
        if not callable(getattr(bridge, "snapshot_flow_age_s", None)):
            raise TypeError("bridge must expose snapshot_flow_age_s")
        if not callable(getattr(bridge, "is_alive", None)):
            raise TypeError("bridge must expose is_alive")
        self._stale_after_s = _positive_number(stale_after_s, field="stale_after_s")
        self._bridge = bridge
        self._store = OperatorSnapshotStore()
        self._active = False
        self._epoch = 0
        self._next_health_poll = 0.0
        self._last_monotonic: float | None = None
        self._last_transport_age = 0.0
        self._last_accepted_snapshot: OperatorSnapshot | None = None
        self._accepted_count = 0
        self._rejected_count = 0
        self._snapshot_queued.connect(
            self._apply_snapshot_batch,
            Qt.ConnectionType.QueuedConnection,
        )
        self._transport_queued.connect(
            self._apply_transport,
            Qt.ConnectionType.QueuedConnection,
        )
        self._failure_queued.connect(
            self._apply_failure,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def snapshot(self) -> OperatorSnapshot | None:
        """Read-only presented truth; mutation capability remains private."""
        return self._store.snapshot

    @property
    def active(self) -> bool:
        return self._active

    @property
    def accepted_count(self) -> int:
        return self._accepted_count

    @property
    def rejected_count(self) -> int:
        return self._rejected_count

    def start(self) -> None:
        self._require_owner_thread()
        if self._active:
            return
        self._epoch += 1
        self._active = True
        self._next_health_poll = 0.0

    def pump(self) -> None:
        """Drain the bounded queue and request one ordered GUI-thread update."""
        self._require_owner_thread()
        if not self._active:
            return
        epoch = self._epoch
        try:
            snapshots = self._bridge.poll_operator_snapshots()
        except Exception:
            self._failure_queued.emit(epoch)
            return
        try:
            now = self._monotonic_now()
        except RuntimeError:
            self._failure_queued.emit(epoch)
            return
        if snapshots:
            # A latest-state queue is not an audit log, but every drained
            # element still belongs to one generation-bound batch.  Validate
            # the whole immutable batch before its newest cut may replace the
            # current authority.
            self._snapshot_queued.emit(epoch, tuple(snapshots))
            self._next_health_poll = now + _HEALTH_POLL_INTERVAL_S
        elif now >= self._next_health_poll:
            self._transport_queued.emit(epoch)
            self._next_health_poll = now + _HEALTH_POLL_INTERVAL_S

    def invalidate_transport(self) -> None:
        """Invalidate old queued work before an externally decided bridge restart."""
        self._require_owner_thread()
        if not self._active:
            return
        self._epoch += 1
        try:
            self._bridge.poll_operator_snapshots()
        except Exception:
            pass
        finally:
            self._degrade_current(connected=False)
        self._next_health_poll = 0.0

    def stop(self) -> None:
        """Settle queued work, drain IPC, and leave current truth disconnected."""
        self._require_owner_thread()
        if not self._active:
            return
        try:
            self._bridge.poll_operator_snapshots()
        except Exception:
            pass
        self._degrade_current(connected=False)
        self._epoch += 1
        self._active = False

    @Slot(int, object)
    def _apply_snapshot_batch(self, epoch: int, candidate: object) -> None:
        """Accept and freshness-qualify one cut before emitting it once."""
        if type(candidate) is not tuple or not candidate:
            self._reject_snapshot_batch()
            return
        previous = self._last_accepted_snapshot
        previous_revision = previous.cut.revision if previous is not None else -1
        for item in candidate:
            if type(item) is not OperatorSnapshot or item.cut.revision < previous_revision:
                self._reject_snapshot_batch()
                return
            if item.cut.revision == previous_revision:
                if item != previous:
                    self._reject_snapshot_batch()
                    return
                continue
            previous = item
            previous_revision = item.cut.revision
        accepted = self._apply_snapshot(epoch, candidate[-1])
        if accepted and self._active and epoch == self._epoch:
            self._apply_transport(epoch)

    def _apply_snapshot(self, epoch: int, candidate: object) -> bool:
        self._require_owner_thread()
        if not self._active or epoch != self._epoch:
            return False
        if type(candidate) is not OperatorSnapshot:
            self._reject_snapshot_batch()
            return False
        if self._last_accepted_snapshot is not None:
            previous_revision = self._last_accepted_snapshot.cut.revision
            if candidate.cut.revision < previous_revision:
                self._reject_snapshot_batch()
                return False
            if candidate.cut.revision == previous_revision:
                if candidate == self._last_accepted_snapshot:
                    return False
                self._reject_snapshot_batch()
                return False
        try:
            accepted = self._store.accept_snapshot(candidate)
        except Exception:
            self._reject_snapshot_batch()
            return False
        self._last_accepted_snapshot = candidate
        self._accepted_count = min(_MAX_COUNTER, self._accepted_count + 1)
        self._last_transport_age = max(summary.transport_age_s for summary in accepted.summaries())
        return True

    @Slot(int)
    def _apply_transport(self, epoch: int) -> None:
        self._require_owner_thread()
        if not self._active or epoch != self._epoch or self._store.snapshot is None:
            return
        try:
            age = self._bridge.snapshot_flow_age_s()
            connected = self._bridge.is_alive() and age is not None
            if age is None:
                age = self._last_transport_age
            else:
                age = max(
                    self._last_transport_age,
                    _nonnegative_number(age, field="snapshot_flow_age_s"),
                )
            presented = self._store.observe_transport(
                connected=connected,
                transport_age_s=age,
                stale_after_s=self._stale_after_s,
            )
        except Exception:
            self._reject_and_degrade()
            return
        self._last_transport_age = age
        self.snapshot_changed.emit(presented)

    @Slot(int)
    def _apply_failure(self, epoch: int) -> None:
        self._require_owner_thread()
        if not self._active or epoch != self._epoch:
            return
        self._reject_and_degrade()

    def _reject_and_degrade(self) -> None:
        self._rejected_count = min(_MAX_COUNTER, self._rejected_count + 1)
        self._degrade_current(connected=False)

    def _reject_snapshot_batch(self) -> None:
        # Invalidate the remainder of this queued batch, including its health
        # event, so rejected input cannot re-freshen the prior cut.
        self._epoch += 1
        self._reject_and_degrade()

    def _degrade_current(self, *, connected: bool) -> None:
        if self._store.snapshot is None:
            return
        presented = self._store.observe_transport(
            connected=connected,
            transport_age_s=self._last_transport_age,
            stale_after_s=self._stale_after_s,
        )
        self.snapshot_changed.emit(presented)

    def _monotonic_now(self) -> float:
        value = time.monotonic()
        if type(value) is not float or not math.isfinite(value):
            raise RuntimeError("monotonic clock unavailable")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise RuntimeError("monotonic clock regressed")
        self._last_monotonic = value
        return value

    def _require_owner_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("operator snapshot store mutation requires its GUI thread")


def start_operator_snapshot_ingress(bridge: Any, window: Any) -> OperatorSnapshotIngressOwner:
    """Compose the one GUI-thread snapshot owner used by either launch root."""
    owner = OperatorSnapshotIngressOwner(bridge, parent=window)
    owner.snapshot_changed.connect(window.render_operator_snapshot)
    owner.start()
    return owner


def _positive_number(value: object, *, field: str) -> float:
    normalized = _nonnegative_number(value, field=field)
    if normalized == 0:
        raise ValueError(f"{field} must be positive")
    return normalized


def _nonnegative_number(value: object, *, field: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{field} must be an exact finite number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be finite and non-negative") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


__all__ = ["OperatorSnapshotIngressOwner"]
