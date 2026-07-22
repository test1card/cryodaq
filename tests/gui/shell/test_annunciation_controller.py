from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.annunciation_controller import AnnunciationController, decode_projection


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _status(
    *,
    engine: str = "engine-a",
    revision: int = 1,
    activations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "ok": True,
        "engine_instance_id": engine,
        "snapshot_revision": revision,
        "activations": activations or [],
    }


def _activation(identifier: str = "a1", *, acknowledged: bool = False) -> dict[str, object]:
    return {
        "activation_id": identifier,
        "source": "safety_fault",
        "source_key": "safety_manager",
        "severity": "CRITICAL",
        "activated_at": 12.0,
        "acknowledged": acknowledged,
    }


def _ack_reply(identifier: str = "a1", *, revision: int = 2) -> dict[str, object]:
    return {
        "ok": True,
        "activation_id": identifier,
        "event_emitted": True,
        "snapshot_revision": revision,
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


def test_new_engine_defaults_fail_loud_until_a_newer_valid_projection() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    assert controller.accept_status(_status(engine="engine-b", revision=0, activations=[]))
    assert controller.audible
    assert controller.accept_status(_status(engine="engine-b", revision=1, activations=[]))
    assert not controller.audible


def test_exact_successful_acknowledgement_can_silence_but_old_engine_cannot() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation()]))
    assert not controller.accept_acknowledgement(_ack_reply(), "other-engine", "a1")
    assert controller.audible
    assert controller.accept_acknowledgement(_ack_reply(), "engine-a", "a1")
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

    assert not controller.accept_acknowledgement(reply, "engine-a", "a1")
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


def test_shutdown_stops_timers_settles_owned_workers_and_rejects_late_work() -> None:
    class _Worker:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_called = False

        def isFinished(self) -> bool:
            return False

        def requestInterruption(self) -> None:
            self.interrupted = True

        def quit(self) -> None:
            self.quit_called = True

        def wait(self, timeout_ms: int) -> bool:
            assert timeout_ms <= 1_500
            return True

    beeps: list[str] = []
    controller = _controller(beeps)
    status = _Worker()
    acknowledgement = _Worker()
    controller._status_worker = status
    controller._ack_worker = acknowledgement

    assert controller.shutdown()
    assert not controller._poll_timer.isActive()
    assert not controller._beep_timer.isActive()
    assert status.interrupted and status.quit_called
    assert acknowledgement.interrupted and acknowledgement.quit_called
    assert not controller.acknowledge("a1", operator="operator", reason="reason")
    assert not controller.accept_status(_status())


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
    controller.poll()
    assert started.wait(1.0)

    started_at = time.monotonic()
    assert controller.shutdown(timeout_ms=1_000)
    assert time.monotonic() - started_at < 1.0
    assert controller._status_worker is not None
    assert controller._status_worker.isFinished()


def test_event_emitted_false_does_not_silence() -> None:
    beeps: list[str] = []
    controller = _controller(beeps)
    assert controller.accept_status(_status(activations=[_activation("activation-1")]))
    assert controller.audible

    accepted = controller.accept_acknowledgement(
        {
            "ok": True,
            "activation_id": "activation-1",
            "event_emitted": False,
            "snapshot_revision": 2,
        },
        "engine-a",
        "activation-1",
    )

    assert accepted is False
    assert controller.audible
    assert controller.shutdown()
