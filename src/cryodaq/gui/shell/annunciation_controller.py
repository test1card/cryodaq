"""GUI-owned presentation of the engine's audible-annunciation projection.

The engine remains the sole owner of alarm and acknowledgement truth.  This
controller merely polls its bounded read-only projection and keeps sounding
until a newer valid projection (or the exact successful audio acknowledgement)
permits silence.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.core.alarm_ack_codec import (
    deterministic_alarm_ack_request_id,
    deterministic_safety_audio_ack_request_id,
    is_canonical_engine_instance_id,
    validate_alarm_ack_wire_result,
    validate_safety_audio_ack_wire_result,
)
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION, gui_worker_poll_in_flight

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
    if type(payload) is not dict or payload.get("ok") is not True:
        return None
    if set(payload) != {"ok", "engine_instance_id", "snapshot_revision", "activations", "proto"}:
        return None
    if type(payload.get("proto")) is not int or payload["proto"] != CLIENT_PROTOCOL_VERSION:
        return None
    engine_instance_id = payload.get("engine_instance_id")
    revision = payload.get("snapshot_revision")
    rows = payload.get("activations")
    if (
        not is_canonical_engine_instance_id(engine_instance_id)
        or type(revision) is not int
        or revision < 0
        or not isinstance(rows, list)
    ):
        return None
    if len(rows) > _MAX_ACTIVATIONS:
        return None

    activations: list[AnnunciationActivation] = []
    activation_ids: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
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
        self._required_projection_revision: int | None = None
        self._activations: tuple[AnnunciationActivation, ...] = ()
        self._authoritative_projection: AnnunciationProjection | None = None
        self._engine_transition_pending = False
        self._transport_generation = 0
        # No status is not evidence of an empty activation set.  Cold start
        # and freshness expiry therefore begin fail-loud and stay that way
        # until one exact engine projection is accepted.
        self._audible_keys: frozenset[str] = frozenset({"annunciation-unknown"})
        self._status_state = "unknown"
        self._last_accepted_monotonic: float | None = None
        self._closing = False
        self._shutdown_hold_started = False
        self._shutdown_terminal = False
        self._status_worker: Any | None = None
        self._ack_worker: Any | None = None
        self._pending_alarm_ack_commands: dict[str, dict[str, str]] = {}

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
        if gui_worker_poll_in_flight(self._status_worker):
            return
        factory = self._worker_factory
        if factory is None:
            from cryodaq.gui.zmq_client import ZmqCommandWorker

            factory = ZmqCommandWorker
        transport_generation = self._transport_generation
        self._status_worker = factory({"cmd": "annunciation_status"}, parent=self)
        self._status_worker.finished.connect(
            lambda payload, expected=transport_generation: self.accept_status(
                payload,
                expected_transport_generation=expected,
            )
        )
        self._status_worker.start()

    def accept_status(
        self,
        payload: object,
        *,
        expected_transport_generation: int | None = None,
    ) -> bool:
        """Accept a valid monotonic projection; never silence on bad input."""
        if self._closing or not self._transport_callback_is_current(expected_transport_generation):
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
        required_revision = self._required_projection_revision
        if required_revision is not None and candidate.snapshot_revision < required_revision:
            return False
        if candidate.snapshot_revision < self._snapshot_revision:
            return False
        if candidate.snapshot_revision == self._snapshot_revision:
            if candidate != self._authoritative_projection:
                return False
            # An unchanged authoritative cut is still fresh liveness evidence.
            # Re-derive the presentation projection so retained alarm-ACK
            # holds survive without letting them contaminate raw authority.
            self._accept(candidate, restart=False)
            return True
        self._engine_transition_pending = False
        self._accept(candidate, restart=False)
        return True

    def acknowledge(self, activation_id: str, *, operator: str, reason: str) -> bool:
        """Request an exact engine-owned audio acknowledgement for one activation."""
        normalized_operator = operator.strip() if type(operator) is str else ""
        normalized_reason = reason.strip() if type(reason) is str else ""
        if (
            self._closing
            or self._status_state != "known"
            or self._engine_instance_id is None
            or _bounded_text(activation_id) is None
            or _bounded_text(normalized_operator) is None
            or _bounded_text(normalized_reason) is None
            or gui_worker_poll_in_flight(self._ack_worker)
        ):
            return False
        retained_command = self._pending_alarm_ack_commands.get(activation_id)
        activation = next((item for item in self._activations if item.activation_id == activation_id), None)
        if retained_command is None:
            if activation is None or activation.acknowledged:
                return False
        elif (
            retained_command.get("cmd") != "alarm_v2_ack"
            or retained_command.get("engine_instance_id") != self._engine_instance_id
            or retained_command.get("activation_id") != activation_id
            or type(retained_command.get("alarm_name")) is not str
            or (
                activation is not None
                and (activation.source != "alarm_v2" or activation.source_key != retained_command["alarm_name"])
            )
        ):
            return False
        factory = self._worker_factory
        if factory is None:
            from cryodaq.gui.zmq_client import ZmqCommandWorker

            factory = ZmqCommandWorker
        engine_instance_id = self._engine_instance_id
        transport_generation = self._transport_generation
        if retained_command is not None or (activation is not None and activation.source == "alarm_v2"):
            alarm_name = retained_command["alarm_name"] if retained_command is not None else activation.source_key
            candidate_command = {
                "cmd": "alarm_v2_ack",
                "alarm_name": alarm_name,
                "engine_instance_id": engine_instance_id,
                "activation_id": activation_id,
                "operator": normalized_operator,
                "reason": normalized_reason,
                "request_id": deterministic_alarm_ack_request_id(
                    alarm_name=alarm_name,
                    engine_instance_id=engine_instance_id,
                    activation_id=activation_id,
                    operator=normalized_operator,
                    reason=normalized_reason,
                ),
            }
            command = retained_command
            if command is None:
                if len(self._pending_alarm_ack_commands) >= _MAX_ACTIVATIONS:
                    return False
                command = candidate_command
                self._pending_alarm_ack_commands[activation_id] = command
            elif command != candidate_command:
                # A retry owns the original semantic request. Never hide a
                # changed attribution behind its retained idempotency key.
                return False
            self._ack_worker = factory(command, parent=self)
            self._ack_worker.finished.connect(
                lambda payload, expected=transport_generation: self.accept_alarm_acknowledgement(
                    payload,
                    engine_instance_id,
                    activation_id,
                    command,
                    expected_transport_generation=expected,
                )
            )
        else:
            command = {
                "cmd": "annunciation_ack",
                "engine_instance_id": engine_instance_id,
                "activation_id": activation_id,
                "operator": normalized_operator,
                "reason": normalized_reason,
                "request_id": deterministic_safety_audio_ack_request_id(
                    engine_instance_id=engine_instance_id,
                    activation_id=activation_id,
                    operator=normalized_operator,
                    reason=normalized_reason,
                ),
            }
            self._ack_worker = factory(
                command,
                parent=self,
            )
            self._ack_worker.finished.connect(
                lambda payload, expected=transport_generation: self.accept_acknowledgement(
                    payload,
                    engine_instance_id,
                    activation_id,
                    command,
                    expected_transport_generation=expected,
                )
            )
        self._ack_worker.start()
        return True

    def accept_alarm_acknowledgement(
        self,
        payload: object,
        engine_instance_id: str,
        activation_id: str,
        command: dict[str, str],
        *,
        expected_transport_generation: int | None = None,
    ) -> bool:
        """Silence an alarm only after its exact durable publication settles."""

        if (
            not self._transport_callback_is_current(expected_transport_generation)
            or self._pending_alarm_ack_commands.get(activation_id) is not command
        ):
            return False
        settlement = validate_alarm_ack_wire_result(
            payload,
            command,
            expected_proto=CLIENT_PROTOCOL_VERSION,
        )
        if (
            self._closing
            or self._engine_instance_id != engine_instance_id
            or activation_id != command.get("activation_id")
        ):
            return False
        if settlement == "aborted":
            del self._pending_alarm_ack_commands[activation_id]
            projection = self._authoritative_projection
            if projection is not None and projection.engine_instance_id == self._engine_instance_id:
                self._activations = self._activations_with_pending_alarm_holds(projection)
                self._update_sound(restart=False)
            return False
        if settlement != "published":
            return False
        del self._pending_alarm_ack_commands[activation_id]
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
        self._update_sound(restart=False)
        return True

    def accept_acknowledgement(
        self,
        payload: object,
        engine_instance_id: str,
        activation_id: str,
        command: dict[str, str],
        *,
        expected_transport_generation: int | None = None,
    ) -> bool:
        """Silence only the exact current activation after an exact success."""
        if (
            self._closing
            or not self._transport_callback_is_current(expected_transport_generation)
            or not validate_safety_audio_ack_wire_result(
                payload,
                command,
                expected_proto=CLIENT_PROTOCOL_VERSION,
            )
            or type(payload) is not dict
            or payload.get("activation_id") != activation_id
            or type(payload.get("snapshot_revision")) is not int
            or payload["snapshot_revision"] < 0
            or self._engine_instance_id != engine_instance_id
            or self._snapshot_revision is None
            or payload["snapshot_revision"]
            <= max(
                self._snapshot_revision,
                self._required_projection_revision
                if self._required_projection_revision is not None
                else self._snapshot_revision,
            )
            or activation_id not in {item.activation_id for item in self._activations if not item.acknowledged}
        ):
            return False
        projection = self._authoritative_projection
        if projection is None or projection.engine_instance_id != engine_instance_id:
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
        # This receipt proves one mutation and its revision, not the complete
        # activation set at that revision. Fence out older status while
        # remaining unknown/fail-loud until the full authoritative cut arrives.
        self._required_projection_revision = payload["snapshot_revision"]
        self._last_accepted_monotonic = None
        self._status_state = "unknown"
        self._update_sound(restart=False)
        return True

    def _transport_callback_is_current(self, expected_generation: int | None) -> bool:
        """Accept direct current-cut calls or one exact captured worker generation."""

        if expected_generation is None:
            return True
        return type(expected_generation) is int and expected_generation == self._transport_generation

    def invalidate_transport(self) -> None:
        """Synchronously revoke one bridge/producer cut and remain fail-loud."""

        if self._shutdown_terminal:
            return
        generation = self._transport_generation
        if type(generation) is not int or generation < 0:
            raise RuntimeError("annunciation transport generation is invalid")
        self._transport_generation = generation + 1
        revision = self._snapshot_revision
        if revision is not None:
            required = revision + 1
            if self._required_projection_revision is not None:
                required = max(required, self._required_projection_revision)
            self._required_projection_revision = required
        self._last_accepted_monotonic = None
        self._status_state = "unknown"
        self._update_sound(restart=True)

    def _accept(self, projection: AnnunciationProjection, *, restart: bool) -> None:
        if self._engine_instance_id is not None and projection.engine_instance_id != self._engine_instance_id:
            self._pending_alarm_ack_commands.clear()
        self._engine_instance_id = projection.engine_instance_id
        self._snapshot_revision = projection.snapshot_revision
        self._required_projection_revision = None
        self._authoritative_projection = projection
        self._activations = self._activations_with_pending_alarm_holds(projection)
        self._last_accepted_monotonic = time.monotonic()
        self._status_state = "known"
        self._update_sound(restart=restart)

    def _activations_with_pending_alarm_holds(
        self,
        projection: AnnunciationProjection,
    ) -> tuple[AnnunciationActivation, ...]:
        """Mask optimistic status ACKs while exact publication is unresolved."""

        held: list[AnnunciationActivation] = []
        for item in projection.activations:
            command = self._pending_alarm_ack_commands.get(item.activation_id)
            if (
                command is not None
                and command.get("cmd") == "alarm_v2_ack"
                and command.get("engine_instance_id") == projection.engine_instance_id
                and command.get("alarm_name") == item.source_key
                and item.source == "alarm_v2"
            ):
                item = AnnunciationActivation(
                    item.activation_id,
                    item.source,
                    item.source_key,
                    item.severity,
                    item.activated_at,
                    False,
                )
            held.append(item)
        return tuple(held)

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

    def begin_shutdown_hold(self) -> None:
        """Quiesce new work while retaining a fail-loud root-owned sentinel."""

        if self._shutdown_terminal:
            raise RuntimeError("annunciation shutdown is already terminal")
        self._closing = True
        self._shutdown_hold_started = True
        self._poll_timer.stop()
        self._status_state = "unknown"
        self._audible_keys = frozenset({*self._audible_keys, "shutdown-hold"})
        if not self._beep_timer.isActive():
            self._beep()
            self._beep_timer.start()

    def settle_for_shutdown(self, *, timeout_ms: int = _WORKER_SETTLE_MS) -> bool:
        """Attempt every worker, retaining HOLD sound until root completion."""

        if type(timeout_ms) is not int or timeout_ms < 0:
            raise ValueError("timeout_ms must be a non-negative integer")
        if self._shutdown_terminal:
            return True
        self.begin_shutdown_hold()
        settled = True
        for worker in (self._status_worker, self._ack_worker):
            if worker is None:
                continue
            try:
                finished = worker.isFinished()
                if type(finished) is not bool:
                    settled = False
                    continue
                if not finished:
                    request = getattr(worker, "requestInterruption", None)
                    if callable(request):
                        request()
                    quit_worker = getattr(worker, "quit", None)
                    if callable(quit_worker):
                        quit_worker()
                    wait = getattr(worker, "wait", None)
                    if not callable(wait) or not wait(timeout_ms):
                        settled = False
                        continue
                    finished = worker.isFinished()
                    if type(finished) is not bool or not finished:
                        settled = False
            except (AttributeError, RuntimeError):
                settled = False
        self.begin_shutdown_hold()
        return settled

    def complete_root_shutdown(self) -> None:
        """Release sound only after the composition root proves terminality."""

        if self._shutdown_terminal:
            return
        if not self._shutdown_hold_started:
            raise RuntimeError("annunciation shutdown HOLD was not established")
        for worker in (self._status_worker, self._ack_worker):
            if worker is None:
                continue
            try:
                finished = worker.isFinished()
            except (AttributeError, RuntimeError) as exc:
                raise RuntimeError("annunciation worker terminality is unavailable") from exc
            if type(finished) is not bool or not finished:
                raise RuntimeError("annunciation worker remains active")
        self._poll_timer.stop()
        self._beep_timer.stop()
        self._audible_keys = frozenset()
        self._shutdown_terminal = True

    def _update_sound(self, *, restart: bool) -> None:
        keys = {
            *(item.activation_id for item in self._activations if not item.acknowledged),
            *self._pending_alarm_ack_commands,
        }
        if self._engine_transition_pending:
            keys.add("engine-instance-change")
        if self._status_state == "unknown":
            keys.add("annunciation-unknown")
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
