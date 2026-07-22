"""GUI-owned presentation of the engine's audible-annunciation projection.

The engine remains the sole owner of alarm and acknowledgement truth.  This
controller merely polls its bounded read-only projection and keeps sounding
until a newer valid projection (or the exact successful audio acknowledgement)
permits silence.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

_MAX_ACTIVATIONS = 64
_MAX_TEXT = 128
_POLL_INTERVAL_MS = 2_000
_BEEP_INTERVAL_MS = 3_000
_STATUS_FRESHNESS_S = 6.0
_WORKER_SETTLE_MS = 1_500
_VALID_SOURCES = frozenset({"alarm_v2", "safety_fault"})
_VALID_SEVERITIES = frozenset({"INFO", "WARNING", "CRITICAL"})


@dataclass(frozen=True, slots=True)
class AnnunciationActivation:
    """One strict, public engine activation."""

    activation_id: str
    source: str
    source_key: str
    severity: str
    activated_at: float
    acknowledged: bool


@dataclass(frozen=True, slots=True)
class AnnunciationProjection:
    """A strict, monotonic cut through engine-owned annunciation truth."""

    engine_instance_id: str
    snapshot_revision: int
    activations: tuple[AnnunciationActivation, ...]


def _bounded_text(value: object) -> str | None:
    if type(value) is not str or not value or len(value) > _MAX_TEXT or any(ord(char) < 32 for char in value):
        return None
    return value


def decode_projection(payload: object) -> AnnunciationProjection | None:
    """Decode only the exact bounded public ``annunciation_status`` schema."""
    if not isinstance(payload, Mapping) or payload.get("ok") is not True:
        return None
    if set(payload) != {"ok", "engine_instance_id", "snapshot_revision", "activations"}:
        return None
    engine_instance_id = _bounded_text(payload.get("engine_instance_id"))
    revision = payload.get("snapshot_revision")
    rows = payload.get("activations")
    if engine_instance_id is None or type(revision) is not int or revision < 0 or not isinstance(rows, list):
        return None
    if len(rows) > _MAX_ACTIVATIONS:
        return None

    activations: list[AnnunciationActivation] = []
    activation_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "activation_id",
            "source",
            "source_key",
            "severity",
            "activated_at",
            "acknowledged",
        }:
            return None
        activation_id = _bounded_text(row.get("activation_id"))
        source = _bounded_text(row.get("source"))
        source_key = _bounded_text(row.get("source_key"))
        severity = row.get("severity")
        activated_at = row.get("activated_at")
        acknowledged = row.get("acknowledged")
        if (
            activation_id is None
            or activation_id in activation_ids
            or source not in _VALID_SOURCES
            or source_key is None
            or type(severity) is not str
            or severity not in _VALID_SEVERITIES
            or type(activated_at) not in (int, float)
            or not math.isfinite(float(activated_at))
            or type(acknowledged) is not bool
        ):
            return None
        activation_ids.add(activation_id)
        activations.append(
            AnnunciationActivation(
                activation_id=activation_id,
                source=source,
                source_key=source_key,
                severity=severity,
                activated_at=float(activated_at),
                acknowledged=acknowledged,
            )
        )
    return AnnunciationProjection(engine_instance_id, revision, tuple(activations))


class AnnunciationController(QObject):
    """One serial poller and sound owner for the shell.

    Missing, malformed, equivocal, or older replies deliberately preserve the
    prior sound state.  A replacement engine starts fail-loud and needs a
    subsequent newer projection before it can become silent.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        worker_factory: Callable[..., Any] | None = None,
        beep: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker_factory = worker_factory
        self._beep = beep or QApplication.beep
        self._engine_instance_id: str | None = None
        self._snapshot_revision: int | None = None
        self._activations: tuple[AnnunciationActivation, ...] = ()
        self._engine_transition_pending = False
        # No status is not evidence of an empty activation set.  Cold start
        # and freshness expiry therefore begin fail-loud and stay that way
        # until one exact engine projection is accepted.
        self._audible_keys: frozenset[str] = frozenset({"annunciation-unknown"})
        self._status_state = "unknown"
        self._last_accepted_monotonic: float | None = None
        self._closing = False
        self._status_worker: Any | None = None
        self._ack_worker: Any | None = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.poll)
        self._poll_timer.start()
        self._beep_timer = QTimer(self)
        self._beep_timer.setInterval(_BEEP_INTERVAL_MS)
        self._beep_timer.timeout.connect(self._beep)
        self._beep()
        self._beep_timer.start()

    @property
    def audible(self) -> bool:
        return bool(self._audible_keys)

    @property
    def status_state(self) -> str:
        """Bounded presentation state: ``known`` or conservative ``unknown``."""
        return self._status_state

    def poll(self) -> None:
        """Issue exactly one read-only status request at a time."""
        if self._closing:
            return
        self._expire_status_if_needed()
        if self._status_worker is not None and not self._status_worker.isFinished():
            return
        factory = self._worker_factory
        if factory is None:
            from cryodaq.gui.zmq_client import ZmqCommandWorker

            factory = ZmqCommandWorker
        self._status_worker = factory({"cmd": "annunciation_status"}, parent=self)
        self._status_worker.finished.connect(self.accept_status)
        self._status_worker.start()

    def accept_status(self, payload: object) -> bool:
        """Accept a valid monotonic projection; never silence on bad input."""
        if self._closing:
            return False
        candidate = decode_projection(payload)
        if candidate is None:
            self._expire_status_if_needed(force_if_unknown=True)
            return False
        if self._engine_instance_id is None:
            self._accept(candidate, restart=True)
            return True
        if candidate.engine_instance_id != self._engine_instance_id:
            self._engine_transition_pending = True
            self._accept(candidate, restart=True)
            return True
        assert self._snapshot_revision is not None
        if candidate.snapshot_revision < self._snapshot_revision:
            return False
        if candidate.snapshot_revision == self._snapshot_revision:
            return candidate.activations == self._activations
        self._engine_transition_pending = False
        self._accept(candidate, restart=False)
        return True

    def acknowledge(self, activation_id: str, *, operator: str, reason: str) -> bool:
        """Request an exact engine-owned audio acknowledgement for one activation."""
        if (
            self._closing
            or self._engine_instance_id is None
            or _bounded_text(activation_id) is None
            or _bounded_text(operator) is None
            or _bounded_text(reason) is None
            or activation_id not in {item.activation_id for item in self._activations if not item.acknowledged}
            or (self._ack_worker is not None and not self._ack_worker.isFinished())
        ):
            return False
        factory = self._worker_factory
        if factory is None:
            from cryodaq.gui.zmq_client import ZmqCommandWorker

            factory = ZmqCommandWorker
        engine_instance_id = self._engine_instance_id
        self._ack_worker = factory(
            {
                "cmd": "annunciation_ack",
                "engine_instance_id": engine_instance_id,
                "activation_id": activation_id,
                "operator": operator,
                "reason": reason,
            },
            parent=self,
        )
        self._ack_worker.finished.connect(
            lambda payload: self.accept_acknowledgement(payload, engine_instance_id, activation_id)
        )
        self._ack_worker.start()
        return True

    def accept_acknowledgement(
        self,
        payload: object,
        engine_instance_id: str,
        activation_id: str,
    ) -> bool:
        """Silence only the exact current activation after an exact success."""
        if (
            self._closing
            or not isinstance(payload, Mapping)
            or set(payload) != {"ok", "activation_id", "event_emitted", "snapshot_revision"}
            or payload.get("ok") is not True
            or payload.get("activation_id") != activation_id
            or payload.get("event_emitted") is not True
            or type(payload.get("snapshot_revision")) is not int
            or payload["snapshot_revision"] < 0
            or self._engine_instance_id != engine_instance_id
            or self._snapshot_revision is None
            or payload["snapshot_revision"] <= self._snapshot_revision
            or activation_id not in {item.activation_id for item in self._activations if not item.acknowledged}
        ):
            return False
        self._activations = tuple(
            AnnunciationActivation(
                item.activation_id,
                item.source,
                item.source_key,
                item.severity,
                item.activated_at,
                True if item.activation_id == activation_id else item.acknowledged,
            )
            for item in self._activations
        )
        self._snapshot_revision = payload["snapshot_revision"]
        self._update_sound(restart=False)
        return True

    def _accept(self, projection: AnnunciationProjection, *, restart: bool) -> None:
        self._engine_instance_id = projection.engine_instance_id
        self._snapshot_revision = projection.snapshot_revision
        self._activations = projection.activations
        self._last_accepted_monotonic = time.monotonic()
        self._status_state = "known"
        self._update_sound(restart=restart)

    def _expire_status_if_needed(self, *, force_if_unknown: bool = False) -> None:
        accepted = self._last_accepted_monotonic
        if accepted is not None and time.monotonic() - accepted < _STATUS_FRESHNESS_S:
            return
        if accepted is None and not force_if_unknown:
            return
        self._status_state = "unknown"
        self._audible_keys = frozenset({*self._audible_keys, "annunciation-unknown"})
        if not self._beep_timer.isActive():
            self._beep()
            self._beep_timer.start()

    def shutdown(self, *, timeout_ms: int = _WORKER_SETTLE_MS) -> bool:
        """Stop polling and settle owned QThreads before shell destruction."""
        if type(timeout_ms) is not int or timeout_ms < 0:
            raise ValueError("timeout_ms must be a non-negative integer")
        self._closing = True
        self._poll_timer.stop()
        self._beep_timer.stop()
        settled = True
        for worker in (self._status_worker, self._ack_worker):
            if worker is None:
                continue
            try:
                if not worker.isFinished():
                    request = getattr(worker, "requestInterruption", None)
                    if callable(request):
                        request()
                    quit_worker = getattr(worker, "quit", None)
                    if callable(quit_worker):
                        quit_worker()
                    wait = getattr(worker, "wait", None)
                    if not callable(wait) or not wait(timeout_ms):
                        settled = False
            except (AttributeError, RuntimeError):
                settled = False
        return settled

    def _update_sound(self, *, restart: bool) -> None:
        keys = {item.activation_id for item in self._activations if not item.acknowledged}
        if self._engine_transition_pending:
            keys.add("engine-instance-change")
        next_keys = frozenset(keys)
        if not next_keys:
            self._audible_keys = next_keys
            self._beep_timer.stop()
            return
        if not self._audible_keys or restart or next_keys != self._audible_keys:
            self._beep_timer.stop()
            self._beep()
            self._beep_timer.start()
        self._audible_keys = next_keys
