"""Pure subprocess-side ordering and bounded-queue ingress for snapshots."""

from __future__ import annotations

import queue
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryodaq.operator_snapshot import OperatorSnapshot
from cryodaq.operator_snapshot_transport import decode_operator_snapshot_frames

_MAX_ENQUEUE_ATTEMPTS = 8


class SnapshotIngressOrderingError(ValueError):
    """A valid snapshot regressed the accepted global cut ordering."""


class SnapshotIngressQueueError(RuntimeError):
    """The bounded IPC queue could not accept the newest complete cut."""


@dataclass(frozen=True, slots=True)
class SnapshotIngressReceipt:
    snapshot: OperatorSnapshot
    dropped_oldest: int


class OperatorSnapshotQueueIngress:
    """Decode exact frames and retain only the newest complete global cut."""

    def __init__(self, snapshot_queue: Any) -> None:
        self._queue = snapshot_queue
        self._last_revision = 0
        self._last_received_at: datetime | None = None

    def accept_frames(self, frames: list[bytes] | tuple[bytes, ...]) -> SnapshotIngressReceipt:
        snapshot = decode_operator_snapshot_frames(frames)
        cut = snapshot.cut
        if cut.revision <= self._last_revision:
            raise SnapshotIngressOrderingError("snapshot revision did not increase")
        if self._last_received_at is not None and cut.received_at < self._last_received_at:
            raise SnapshotIngressOrderingError("snapshot received_at regressed")

        dropped = self._enqueue_latest(snapshot)
        self._last_revision = cut.revision
        self._last_received_at = cut.received_at
        return SnapshotIngressReceipt(snapshot, dropped)

    def _enqueue_latest(self, snapshot: OperatorSnapshot) -> int:
        dropped = 0
        for _attempt in range(_MAX_ENQUEUE_ATTEMPTS):
            try:
                self._queue.put_nowait(snapshot)
                return dropped
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    # The GUI consumer won the race; retry the newest cut.
                    continue
                else:
                    self._queue.task_done()
                    dropped += 1
        raise SnapshotIngressQueueError("snapshot queue did not settle")


__all__ = [
    "OperatorSnapshotQueueIngress",
    "SnapshotIngressOrderingError",
    "SnapshotIngressQueueError",
    "SnapshotIngressReceipt",
]
