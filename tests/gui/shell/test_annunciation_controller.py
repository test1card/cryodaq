from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_SCHEMA,
    alarm_ack_request_fingerprint,
    deterministic_alarm_ack_request_id,
    deterministic_safety_audio_ack_request_id,
    safety_audio_ack_request_fingerprint,
)
from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer
from cryodaq.gui.shell.annunciation_controller import AnnunciationController, decode_projection

_ENGINE_A = "a" * 32
_ENGINE_B = "b" * 32
_OTHER_ENGINE = "c" * 32


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _status(
    *,
    engine: str = _ENGINE_A,
    revision: int = 1,
    activations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "ok": True,
        "proto": PROTOCOL_VERSION,
        "engine_instance_id": engine,
        "snapshot_revision": revision,
        "activations": activations or [],
    }


def _activation(
    identifier: str = "a1",
    *,
    acknowledged: bool = False,
    source: str = "safety_fault",
    source_key: str = "safety_manager",
) -> dict[str, object]:
    return {
        "activation_id": identifier,
        "source": source,
        "source_key": source_key,
        "severity": "CRITICAL",
        "activated_at": 12.0,
        "acknowledged": acknowledged,
    }


def _ack_command(identifier: str = "a1", *, engine: str = _ENGINE_A) -> dict[str, str]:
    operator = "operator-a"
    reason = "observed locally"
    return {
        "cmd": "annunciation_ack",
        "engine_instance_id": engine,
        "activation_id": identifier,
        "operator": operator,
        "reason": reason,
        "request_id": deterministic_safety_audio_ack_request_id(
            engine_instance_id=engine,
            activation_id=identifier,
            operator=operator,
            reason=reason,
        ),
    }


def _ack_reply(
    identifier: str = "a1",
    *,
    revision: int = 2,
    command: dict[str, str] | None = None,
) -> dict[str, object]:
    command = command or _ack_command(identifier)
    return {
        "ok": True,
        "proto": PROTOCOL_VERSION,
        "engine_instance_id": command["engine_instance_id"],
        "activation_id": command["activation_id"],
        "request_id": command["request_id"],
        "snapshot_revision": revision,
        "audit_receipt": {
            "schema": "safety_audio_ack_v1",
            "request_id": command["request_id"],
            "request_fingerprint": safety_audio_ack_request_fingerprint(command),
            "engine_instance_id": command["engine_instance_id"],
            "activation_id": command["activation_id"],
            "source_activation_id": "9",
            "entry_id": 12,
            "committed": True,
        },
    }


def _alarm_ack_command(identifier: str = "a1", *, engine: str = _ENGINE_A) -> dict[str, str]:
    alarm_name = "pressure_high"
    operator = "operator-a"
    reason = "observed locally"
    return {
        "cmd": "alarm_v2_ack",
        "alarm_name": alarm_name,
        "engine_instance_id": engine,
        "activation_id": identifier,
        "operator": operator,
        "reason": reason,
        "request_id": deterministic_alarm_ack_request_id(
            alarm_name=alarm_name,
            engine_instance_id=engine,
            activation_id=identifier,
            operator=operator,
            reason=reason,
        ),
    }


def _alarm_ack_reply(command: dict[str, str]) -> dict[str, object]:
    fingerprint = alarm_ack_request_fingerprint(command)
    receipt = {
        "schema": ALARM_ACK_COMMIT_SCHEMA,
        "request_id": command["request_id"],
        "request_fingerprint": fingerprint,
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "acknowledged_at": 123.5,
        "committed": True,
    }
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "event_emitted": True,
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "request_id": command["request_id"],
        "commit_receipt": receipt,
        "proto": PROTOCOL_VERSION,
    }


def _alarm_ack_pending_reply(command: dict[str, str]) -> dict[str, object]:
    return {
        **_alarm_ack_reply(command),
        "ok": False,
        "publication_state": "pending",
        "event_emitted": False,
        "error_code": "alarm_ack_publication_pending",
        "error": "alarm acknowledgement is committed; publication settlement is pending",
    }


def _controller(beeps: list[str]) -> AnnunciationController:
    _app()
    controller = AnnunciationController(beep=lambda: beeps.append("beep"))
    controller._poll_timer.stop()
    return controller


def test_decoder_rejects_unbounded_unknown_and_duplicate_activation_schema() -> None:
    assert decode_projection(_status(activations=[_activation(), _activation()])) is None
    malformed = _status(activations=[{**_activation(), "extra": "no"}])
    assert decode_projection(malformed) is None
    assert (
        decode_projection({"ok": True, "engine_instance_id": "a", "snapshot_revision": 1, "activations": [], "x": 1})
        is None
    )


@pytest.mark.parametrize("malformed_engine_id", ["short", "A" * 32, "g" * 32])
def test_malformed_replacement_engine_cannot_erase_last_known_audible_truth(malformed_engine_id: str) -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    assert controller.audible

    replacement = _status(engine=malformed_engine_id, revision=2, activations=[])
    assert decode_projection(replacement) is None
    assert not controller.accept_status(replacement)
    assert controller.audible
    assert controller._engine_instance_id == _ENGINE_A
    assert [item.activation_id for item in controller._activations] == ["a1"]
    assert controller.settle_for_shutdown()


def test_real_zmq_encoder_status_and_ack_are_accepted_without_handler_forged_proto() -> None:
    import json

    beeps: list[str] = []
    controller = _controller(beeps)
    status_handler_result = _status(activations=[_activation()])
    status_handler_result.pop("proto")
    assert "proto" not in status_handler_result
    status_wire = json.loads(ZMQCommandServer()._encode_reply(status_handler_result))

    assert controller.accept_status(status_wire)
    assert controller.audible

    command = _ack_command()
    ack_handler_result = _ack_reply(command=command)
    ack_handler_result.pop("proto")
    assert "proto" not in ack_handler_result
    ack_wire = json.loads(ZMQCommandServer()._encode_reply(ack_handler_result))

    assert controller.accept_acknowledgement(ack_wire, _ENGINE_A, "a1", command)
    assert controller.status_state == "unknown"
    assert controller.audible

    complete_handler_result = _status(revision=2, activations=[_activation(acknowledged=True)])
    complete_handler_result.pop("proto")
    complete_wire = json.loads(ZMQCommandServer()._encode_reply(complete_handler_result))
    assert controller.accept_status(complete_wire)
    assert not controller.audible


@pytest.mark.parametrize("proto", [None, True, 1, 3, "2"])
def test_missing_bool_wrong_or_text_wire_proto_cannot_silence(proto: object) -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    initial = _status(activations=[_activation()])
    assert controller.accept_status(initial)

    command = _ack_command()
    malformed = _ack_reply(command=command)
    if proto is None:
        malformed.pop("proto")
    else:
        malformed["proto"] = proto

    assert not controller.accept_acknowledgement(malformed, _ENGINE_A, "a1", command)
    assert controller.audible


def test_new_unacknowledged_activation_starts_and_restarts_sound() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.audible and controller.status_state == "unknown"
    assert controller.accept_status(_status(activations=[_activation()]))
    assert controller.audible and beeps == ["beep", "beep"]
    assert controller.accept_status(_status(revision=2, activations=[_activation(), _activation("a2")]))
    assert beeps == ["beep", "beep", "beep"]


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False},
        _status(revision=0, activations=[]),
        _status(revision=1, activations=[]),
        _status(revision=2, activations=[{**_activation(), "severity": "UNKNOWN"}]),
    ],
)
def test_bad_or_older_or_equivocal_status_cannot_silence(payload: object) -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    assert not controller.accept_status(payload)
    assert controller.audible


def test_unchanged_authoritative_revision_refreshes_freshness_after_expiry() -> None:
    """Stable truth must refresh liveness even when its revision does not change."""
    beeps: list[str] = []
    controller = _controller(beeps)
    unchanged = _status(revision=1, activations=[])
    assert controller.accept_status(unchanged)
    assert controller.status_state == "known"
    assert not controller.audible

    controller._last_accepted_monotonic = time.monotonic() - 60.0
    controller._expire_status_if_needed()
    assert controller.status_state == "unknown"
    assert controller.audible

    assert controller.accept_status(unchanged)
    assert controller.status_state == "known"
    assert not controller.audible


def test_transport_invalidation_fences_old_status_and_ack_until_new_complete_cut() -> None:
    """A producer turnover must become unknown and fail-loud synchronously."""
    beeps: list[str] = []
    controller = _controller(beeps)
    old_generation = controller._transport_generation

    assert controller.accept_status(_status(revision=7, activations=[]))
    assert controller.status_state == "known"
    assert not controller.audible

    controller.invalidate_transport()
    current_generation = controller._transport_generation
    assert current_generation == old_generation + 1
    assert controller.status_state == "unknown"
    assert controller.audible

    assert not controller.accept_status(
        _status(revision=8, activations=[]),
        expected_transport_generation=old_generation,
    )
    assert not controller.accept_status(_status(revision=7, activations=[]))
    assert controller.status_state == "unknown"
    assert controller.audible

    assert controller.accept_status(
        _status(revision=8, activations=[_activation()]),
        expected_transport_generation=current_generation,
    )
    assert controller.status_state == "known"
    assert controller.audible

    command = _ack_command()
    assert not controller.accept_acknowledgement(
        _ack_reply(revision=9, command=command),
        _ENGINE_A,
        "a1",
        command,
        expected_transport_generation=old_generation,
    )
    assert controller.status_state == "known"
    assert controller.audible

    assert controller.accept_status(
        _status(revision=9, activations=[]),
        expected_transport_generation=current_generation,
    )
    assert controller.status_state == "known"
    assert not controller.audible


def test_safety_ack_revision_requires_full_same_revision_status_before_truth_is_known() -> None:
    """A partial ACK receipt cannot synthesize a complete canonical projection."""
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(revision=1, activations=[_activation()]))
    command = _ack_command()
    assert controller.accept_acknowledgement(
        _ack_reply(revision=2, command=command),
        _ENGINE_A,
        "a1",
        command,
    )
    assert controller.status_state == "unknown"
    assert controller.audible
    acknowledged = _status(revision=2, activations=[_activation(acknowledged=True)])

    assert controller.accept_status(acknowledged)
    assert controller.status_state == "known"
    assert not controller.audible
    assert not controller.accept_status(_status(revision=2, activations=[_activation("different", acknowledged=True)]))

    controller._last_accepted_monotonic = time.monotonic() - 60.0
    controller._expire_status_if_needed()
    assert controller.accept_status(acknowledged)
    assert controller.status_state == "known"
    assert not controller.audible


def test_partial_safety_ack_cannot_hide_concurrent_alarm_in_same_revision_cut() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(revision=1, activations=[_activation()]))
    command = _ack_command()

    assert controller.accept_acknowledgement(
        _ack_reply(revision=3, command=command),
        _ENGINE_A,
        "a1",
        command,
    )
    assert controller.status_state == "unknown"
    assert controller.audible

    complete_cut = _status(
        revision=3,
        activations=[
            _activation(acknowledged=True),
            _activation(
                "alarm-b",
                source="alarm_v2",
                source_key="pressure_high",
            ),
        ],
    )
    assert controller.accept_status(complete_cut)
    assert controller.status_state == "known"
    assert controller.audible


def test_new_engine_defaults_fail_loud_until_a_newer_valid_projection() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    assert controller.accept_status(_status(engine=_ENGINE_B, revision=0, activations=[]))
    assert controller.audible
    assert controller.accept_status(_status(engine=_ENGINE_B, revision=1, activations=[]))
    assert not controller.audible


def test_exact_successful_acknowledgement_requires_full_projection_and_old_engine_cannot_advance() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    command = _ack_command()
    assert not controller.accept_acknowledgement(_ack_reply(command=command), _OTHER_ENGINE, "a1", command)
    assert controller.audible
    assert controller.accept_acknowledgement(_ack_reply(command=command), _ENGINE_A, "a1", command)
    assert controller.status_state == "unknown"
    assert controller.audible
    assert controller.accept_status(_status(revision=2, activations=[_activation(acknowledged=True)]))
    assert not controller.audible


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": True},
        {**_ack_reply(), "event_emitted": False},
        {**_ack_reply(), "activation_id": "other"},
        {**_ack_reply(), "snapshot_revision": 1},
        {**_ack_reply(), "unexpected": "field"},
    ],
)
def test_malformed_or_stale_ack_reply_cannot_silence(reply: object) -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(revision=1, activations=[_activation()]))

    assert not controller.accept_acknowledgement(reply, _ENGINE_A, "a1", _ack_command())
    assert controller.audible


def test_poller_is_serial_and_uses_only_the_exact_read_only_status_command() -> None:
    class _Signal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback):  # noqa: ANN001
            self.callback = callback

    class _Worker:
        commands: list[dict[str, object]] = []

        def __init__(self, command, parent=None) -> None:  # noqa: ANN001
            self.commands.append(command)
            self.finished = _Signal()
            self.running = False

        def isFinished(self) -> bool:
            return not self.running

        def start(self) -> None:
            self.running = True

    _app()
    controller = AnnunciationController(worker_factory=_Worker, beep=lambda: None)
    controller._poll_timer.stop()
    controller.poll()
    controller.poll()
    assert _Worker.commands == [{"cmd": "annunciation_status"}]


def test_shutdown_holds_sound_until_root_completes_after_owned_workers_settle() -> None:
    class _Worker:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_called = False
            self.finished = False

        def isFinished(self) -> bool:
            return self.finished

        def requestInterruption(self) -> None:
            self.interrupted = True

        def quit(self) -> None:
            self.quit_called = True

        def wait(self, timeout_ms: int) -> bool:
            assert timeout_ms <= 1_500
            self.finished = True
            return True

    beeps: list[str] = []
    controller = _controller(beeps)
    status = _Worker()
    acknowledgement = _Worker()
    controller._status_worker = status
    controller._ack_worker = acknowledgement
    controller._beep_timer.stop()

    assert controller.settle_for_shutdown()
    assert not controller._poll_timer.isActive()
    assert controller._beep_timer.isActive()
    assert controller._shutdown_hold_started
    assert not controller._shutdown_terminal
    assert status.interrupted and status.quit_called
    assert acknowledgement.interrupted and acknowledgement.quit_called
    assert not controller.acknowledge("a1", operator="operator", reason="reason")
    assert not controller.accept_status(_status())

    controller.complete_root_shutdown()
    assert not controller._beep_timer.isActive()
    assert controller._shutdown_terminal


def test_unsettled_worker_keeps_shutdown_hold_audible_across_retry() -> None:
    class _Worker:
        finished = False

        def isFinished(self) -> bool:
            return self.finished

        def requestInterruption(self) -> None:
            pass

        def quit(self) -> None:
            pass

        def wait(self, timeout_ms: int) -> bool:  # noqa: ARG002
            return self.finished

    beeps: list[str] = []
    controller = _controller(beeps)
    worker = _Worker()
    controller._status_worker = worker
    controller._beep_timer.stop()

    assert not controller.settle_for_shutdown(timeout_ms=0)
    assert controller._beep_timer.isActive()
    assert "shutdown-hold" in controller._audible_keys
    with pytest.raises(RuntimeError, match="remains active"):
        controller.complete_root_shutdown()

    before = len(beeps)
    controller._beep_timer.timeout.emit()
    assert len(beeps) == before + 1

    worker.finished = True
    assert controller.settle_for_shutdown(timeout_ms=0)
    assert controller._beep_timer.isActive()
    controller.complete_root_shutdown()
    assert not controller._beep_timer.isActive()
    assert controller._audible_keys == frozenset()


def test_real_status_worker_cancels_and_settles_during_shutdown(monkeypatch, real_zmq_worker) -> None:
    """A real QThread must not wait for the normal 65-second command limit."""
    from cryodaq.gui import zmq_client

    started = threading.Event()

    def blocked_status(_command, *, cancellation_requested=None):  # noqa: ANN001
        started.set()
        assert cancellation_requested is not None
        while not cancellation_requested.wait(0.01):
            pass
        return {"ok": False, "error": "cancelled"}

    monkeypatch.setattr(zmq_client, "send_command", blocked_status)
    beeps: list[str] = []
    controller = _controller(beeps)
    root_completed = False
    try:
        controller.poll()
        assert started.wait(1.0)

        started_at = time.monotonic()
        assert controller.settle_for_shutdown(timeout_ms=1_000)
        assert time.monotonic() - started_at < 1.0
        assert controller._status_worker is not None
        assert controller._status_worker.isFinished()
        assert controller._beep_timer.isActive()
        controller.complete_root_shutdown()
        root_completed = True
        assert not controller._beep_timer.isActive()
    finally:
        if not root_completed:
            assert controller.settle_for_shutdown(timeout_ms=5_000)
            controller.complete_root_shutdown()


def test_pending_alarm_ack_retry_rejects_changed_attribution_and_reuses_exact_command() -> None:
    class _Signal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:  # noqa: ANN001
            self.callback = callback

    class _Worker:
        commands: list[dict[str, str]] = []

        def __init__(self, command, *, parent=None) -> None:  # noqa: ANN001, ARG002
            self.commands.append(command)
            self.command = command
            self.finished = _Signal()
            self.running = False

        def isFinished(self) -> bool:
            return not self.running

        def start(self) -> None:
            self.running = True

    _app()
    _Worker.commands = []
    controller = AnnunciationController(worker_factory=_Worker, beep=lambda: None)
    controller._poll_timer.stop()
    controller._beep_timer.stop()
    assert controller.accept_status(
        _status(activations=[_activation("activation-1", source="alarm_v2", source_key="pressure_high")])
    )

    assert controller.acknowledge("activation-1", operator="operator-a", reason="observed locally")
    retained = controller._pending_alarm_ack_commands["activation-1"]
    controller._ack_worker.running = False

    assert not controller.acknowledge("activation-1", operator="operator-b", reason="different reason")
    assert _Worker.commands == [retained]
    assert controller._pending_alarm_ack_commands["activation-1"] is retained

    assert controller.acknowledge("activation-1", operator="operator-a", reason="observed locally")
    assert len(_Worker.commands) == 2
    assert _Worker.commands[1] is retained
    controller._ack_worker.running = False


def test_pending_alarm_ack_survives_acknowledged_projection_until_exact_publication() -> None:
    class _Signal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:  # noqa: ANN001
            self.callback = callback

    class _Worker:
        commands: list[dict[str, str]] = []

        def __init__(self, command, *, parent=None) -> None:  # noqa: ANN001, ARG002
            self.commands.append(command)
            self.finished = _Signal()
            self.running = False

        def isFinished(self) -> bool:
            return not self.running

        def start(self) -> None:
            self.running = True

    _app()
    _Worker.commands = []
    controller = AnnunciationController(worker_factory=_Worker, beep=lambda: None)
    controller._poll_timer.stop()
    controller._beep_timer.stop()
    activation = _activation("activation-1", source="alarm_v2", source_key="pressure_high")
    assert controller.accept_status(_status(revision=1, activations=[activation]))
    assert controller.acknowledge("activation-1", operator="operator-a", reason="observed locally")
    command = controller._pending_alarm_ack_commands["activation-1"]
    controller._ack_worker.running = False

    assert not controller.accept_alarm_acknowledgement(
        _alarm_ack_pending_reply(command),
        _ENGINE_A,
        "activation-1",
        command,
    )
    assert controller.accept_status(
        _status(
            revision=2,
            activations=[
                _activation(
                    "activation-1",
                    acknowledged=True,
                    source="alarm_v2",
                    source_key="pressure_high",
                )
            ],
        )
    )

    assert controller._pending_alarm_ack_commands["activation-1"] is command
    assert controller.audible
    assert controller.acknowledge("activation-1", operator="operator-a", reason="observed locally")
    assert _Worker.commands[-1] is command
    controller._ack_worker.running = False

    assert controller.accept_alarm_acknowledgement(
        _alarm_ack_reply(command),
        _ENGINE_A,
        "activation-1",
        command,
    )
    assert controller._pending_alarm_ack_commands == {}
    assert not controller.audible


def test_alarm_ack_terminal_reply_requires_exact_retained_command_object() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(
        _status(activations=[_activation("activation-1", source="alarm_v2", source_key="pressure_high")])
    )
    retained = _alarm_ack_command("activation-1")
    controller._pending_alarm_ack_commands["activation-1"] = retained
    equivalent_but_unowned = dict(retained)

    assert not controller.accept_alarm_acknowledgement(
        _alarm_ack_reply(equivalent_but_unowned),
        _ENGINE_A,
        "activation-1",
        equivalent_but_unowned,
    )
    assert controller._pending_alarm_ack_commands["activation-1"] is retained
    assert controller.audible

    assert controller.accept_alarm_acknowledgement(
        _alarm_ack_reply(retained),
        _ENGINE_A,
        "activation-1",
        retained,
    )
    assert controller._pending_alarm_ack_commands == {}
    assert not controller.audible
    assert controller.settle_for_shutdown()


def test_event_emitted_false_does_not_silence() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(
        _status(
            activations=[
                _activation(
                    "activation-1",
                    source="alarm_v2",
                    source_key="pressure_high",
                )
            ]
        )
    )
    assert controller.audible

    command = _alarm_ack_command("activation-1")
    controller._pending_alarm_ack_commands["activation-1"] = command
    published = _alarm_ack_reply(command)
    accepted = controller.accept_alarm_acknowledgement(
        {**published, "event_emitted": False},
        _ENGINE_A,
        "activation-1",
        command,
    )

    assert accepted is False
    assert controller.audible
    assert controller.accept_alarm_acknowledgement(published, _ENGINE_A, "activation-1", command)
    assert not controller.audible
    assert controller.settle_for_shutdown()
