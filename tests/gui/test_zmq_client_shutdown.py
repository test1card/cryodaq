from __future__ import annotations

import contextlib
import gc
import os
import queue
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.gui.zmq_client import ZmqBridge


@dataclass
class _FakeProcess:
    exit_after: str | None
    calls: list[str] = field(default_factory=list)
    exitcode: int | None = None
    _alive: bool = True

    def is_alive(self) -> bool:
        self.calls.append("is_alive")
        return self._alive

    def join(self, timeout: float) -> None:
        self.calls.append(f"join:{timeout:g}")
        if self.exit_after == "join" and self.calls.count("join:3") == 1:
            self._exit(0)
        elif self.exit_after == "terminate" and "terminate" in self.calls:
            self._exit(-15)
        elif self.exit_after == "kill" and "kill" in self.calls:
            self._exit(-9)

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")

    def _exit(self, exitcode: int) -> None:
        self._alive = False
        self.exitcode = exitcode


class _FakeReplyConsumer:
    def __init__(self, *, stops: bool = True) -> None:
        self._alive = True
        self._stops = stops
        self.calls: list[str] = []

    def is_alive(self) -> bool:
        self.calls.append("is_alive")
        return self._alive

    def join(self, timeout: float) -> None:
        self.calls.append(f"join:{timeout:g}")
        if self._stops:
            self._alive = False


class _FeederTerminalProofProbe:
    def __init__(self) -> None:
        self.join_calls = 0
        self.alive_proof: object = False

    def join(self, timeout: float) -> None:
        assert timeout == 2.0
        self.join_calls += 1

    def is_alive(self) -> object:
        return self.alive_proof


class _QueueTerminalProofProbe:
    def __init__(self) -> None:
        self._thread = _FeederTerminalProofProbe()
        self.close_calls = 0
        self.join_thread_calls = 0
        self._valid_join = self._thread.join
        self._valid_is_alive = self._thread.is_alive
        self._valid_join_thread = self.join_thread

    @staticmethod
    def get_nowait() -> object:
        raise queue.Empty

    @staticmethod
    def task_done() -> None:
        return None

    def close(self) -> None:
        self.close_calls += 1

    def join_thread(self) -> None:
        self.join_thread_calls += 1

    def invalidate_terminal_proof(self, failure: str) -> None:
        if failure == "noncallable_join":
            self._thread.join = None  # type: ignore[method-assign]
        elif failure == "noncallable_is_alive":
            self._thread.is_alive = None  # type: ignore[method-assign]
        elif failure == "non_boolean_is_alive":
            self._thread.alive_proof = 0
        elif failure == "noncallable_join_thread":
            self.join_thread = None  # type: ignore[method-assign]
        else:  # pragma: no cover - test helper contract
            raise AssertionError(f"unknown terminal proof failure: {failure}")

    def repair_terminal_proof(self) -> None:
        self._thread.join = self._valid_join  # type: ignore[method-assign]
        self._thread.is_alive = self._valid_is_alive  # type: ignore[method-assign]
        self._thread.alive_proof = False
        self.join_thread = self._valid_join_thread  # type: ignore[method-assign]


def _bridge(process: _FakeProcess, *, reply_stops: bool = True) -> tuple[ZmqBridge, _FakeReplyConsumer]:
    bridge = ZmqBridge()
    reply = _FakeReplyConsumer(stops=reply_stops)
    bridge._process = process  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = reply  # type: ignore[assignment]
    bridge._reply_consumer_started = True
    bridge._command_admission_open = True
    bridge._bridge_instance_id = "f" * 32
    bridge._last_snapshot_time = 123.0
    return bridge, reply


@pytest.mark.parametrize(
    ("exit_after", "expected_process_calls"),
    [
        ("join", ["join:3"]),
        ("terminate", ["join:3", "terminate", "join:2"]),
        ("kill", ["join:3", "terminate", "join:2", "kill", "join:2"]),
    ],
)
def test_shutdown_clears_ownership_only_after_process_and_reply_consumer_settle(
    exit_after: str,
    expected_process_calls: list[str],
) -> None:
    process = _FakeProcess(exit_after=exit_after)
    bridge, reply = _bridge(process)

    bridge.shutdown()

    assert [call for call in process.calls if call != "is_alive"] == expected_process_calls
    assert reply.calls == ["join:3", "is_alive"]
    assert bridge._process is None
    assert bridge._reply_consumer is None
    assert bridge._last_snapshot_time == 0.0

    # A proven shutdown remains idempotent.
    bridge.shutdown()


def test_shutdown_retains_process_handle_when_child_survives_kill() -> None:
    process = _FakeProcess(exit_after=None)
    bridge, _reply = _bridge(process)

    with pytest.raises(RuntimeError, match="subprocess remained alive after kill and join"):
        bridge.shutdown()

    assert [call for call in process.calls if call != "is_alive"] == [
        "join:3",
        "terminate",
        "join:2",
        "kill",
        "join:2",
    ]
    assert process.exitcode is None
    assert bridge._process is process
    assert bridge._last_snapshot_time == 0.0


def test_shutdown_retains_ownership_when_reply_consumer_does_not_stop() -> None:
    process = _FakeProcess(exit_after="join")
    bridge, reply = _bridge(process, reply_stops=False)

    with pytest.raises(RuntimeError, match="reply consumer remained alive after join"):
        bridge.shutdown()

    assert reply._alive is True
    assert process._alive is False
    assert bridge._reply_consumer is reply
    assert bridge._process is process


def test_start_refuses_to_replace_ownership_when_old_reply_consumer_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(exit_after=None)
    process._exit(0)
    bridge, reply = _bridge(process, reply_stops=False)
    old_snapshot_queue = bridge._snapshot_queue
    process_factory = MagicMock(name="Process")
    thread_factory = MagicMock(name="Thread")
    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", process_factory)
    monkeypatch.setattr("cryodaq.gui.zmq_client.threading.Thread", thread_factory)

    with pytest.raises(
        RuntimeError,
        match="previous ZMQ runtime settlement incomplete: ordinary reply consumer remained alive after join",
    ):
        bridge.start()

    assert bridge._last_snapshot_time == 0.0
    assert bridge._reply_consumer is reply
    assert bridge._reply_stop.is_set()
    assert bridge._process is process
    assert bridge._snapshot_queue is old_snapshot_queue
    assert reply.calls == ["is_alive", "join:3", "is_alive"]
    process_factory.assert_not_called()
    thread_factory.assert_not_called()


def test_terminal_close_settles_then_closes_all_parent_queues() -> None:
    process = _FakeProcess(exit_after="join")
    bridge, _reply = _bridge(process)

    bridge.close()

    assert bridge._terminal_closed is True
    assert bridge._terminal_queues_closed == {
        "data",
        "command",
        "safe_command",
        "reply",
        "safe_reply",
        "snapshot",
    }
    assert bridge._terminal_queues_joined == {
        "data",
        "command",
        "safe_command",
        "reply",
        "safe_reply",
        "snapshot",
    }
    assert bridge._process is None
    assert bridge._reply_consumer is None
    bridge.close()  # exact terminal close is idempotent
    with pytest.raises(RuntimeError, match="terminally closed"):
        bridge.start()


def test_terminal_close_retains_queues_when_process_survives() -> None:
    process = _FakeProcess(exit_after=None)
    bridge, _reply = _bridge(process)

    with pytest.raises(RuntimeError, match="subprocess remained alive"):
        bridge.close()

    assert bridge._terminal_closed is False
    assert bridge._terminal_queues_closed == set()
    assert bridge._terminal_queues_joined == set()
    assert bridge._process is process


def test_terminal_close_refuses_to_abandon_unresolved_mutation_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    request_id = "unresolved-mutation"
    owner: Future[dict[str, object]] = Future()
    bridge._outcome_unknown[request_id] = owner
    bridge._request_generation[request_id] = bridge._generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        bridge._generation,
        zmq_client.CommandClass.MUTATION,
        "experiment_finalize",
    )
    monkeypatch.setattr(bridge, "shutdown", lambda: None)

    try:
        with pytest.raises(RuntimeError, match="unresolved mutation reconciliation"):
            bridge.close()

        assert bridge._terminal_closed is False
        assert bridge._terminal_queues_closed == set()
        assert bridge._terminal_queues_joined == set()
        assert bridge._outcome_unknown[request_id] is owner
        assert bridge._request_bindings[request_id].generation == bridge._generation
    finally:
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_terminal_close_refuses_unreconciled_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    request_id = "terminal-unreconciled"
    bridge._late_results[request_id] = zmq_client.LateCommandResult(
        request_id,
        bridge._generation,
        {"ok": True, "scope": "global"},
        zmq_client.CommandClass.SAFE_DIRECTION,
        "keithley_emergency_off",
        "global",
    )
    monkeypatch.setattr(bridge, "shutdown", lambda: None)

    try:
        with pytest.raises(RuntimeError, match="unresolved mutation reconciliation"):
            bridge.close()

        assert bridge._terminal_closed is False
        assert bridge._terminal_queues_closed == set()
        assert bridge._late_results[request_id].reply == {"ok": True, "scope": "global"}
    finally:
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_start_retains_live_process_when_retired_owner_settlement_is_incomplete() -> None:
    bridge = ZmqBridge()

    class _LiveProcess:
        @staticmethod
        def is_alive() -> bool:
            return True

    bridge._process = _LiveProcess()
    bridge._process_started = True
    bridge._command_admission_open = False
    try:
        with pytest.raises(RuntimeError, match="previous ZMQ runtime settlement incomplete"):
            bridge.start()
        assert bridge._process is not None
        assert bridge._command_admission_open is False
    finally:
        bridge._process = None
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_safe_reply_consumer_death_closes_admission_and_invalidates_bridge_health() -> None:
    bridge = ZmqBridge()
    retired_safe_queue = bridge._safe_reply_queue
    request_id = "a" * 32
    owner: Future[dict[str, object]] = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = bridge._generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        bridge._generation,
        zmq_client.CommandClass.SAFE_DIRECTION,
        "keithley_emergency_off",
        "global",
    )

    class _LiveProcess:
        exitcode = None

        @staticmethod
        def is_alive() -> bool:
            return True

    class _BrokenSafeReplyQueue:
        @staticmethod
        def get(timeout=None):
            del timeout
            raise EOFError("safe reply pipe closed")

    bridge._process = _LiveProcess()  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = MagicMock(name="live_ordinary_consumer")
    bridge._reply_consumer.is_alive.return_value = True
    bridge._reply_consumer_started = True
    bridge._safe_reply_consumer = MagicMock(name="live_safe_consumer")
    bridge._safe_reply_consumer.is_alive.return_value = True
    bridge._safe_reply_consumer_started = True
    bridge._safe_reply_queue = _BrokenSafeReplyQueue()  # type: ignore[assignment]
    bridge._last_heartbeat = time.monotonic()
    bridge._command_admission_open = True
    bridge._reply_stop.clear()
    assert bridge.is_alive() is True
    assert bridge.is_healthy() is True
    consumer = threading.Thread(target=bridge._consume_safe_replies, daemon=True)
    bridge._safe_reply_consumer = consumer
    consumer.start()
    consumer.join(1.0)

    try:
        assert consumer.is_alive() is False
        assert bridge._command_admission_open is False
        assert bridge._shutdown_event.is_set()
        assert bridge.is_alive() is False
        assert bridge.is_healthy() is False
        assert request_id not in bridge._pending
        assert bridge._outcome_unknown[request_id] is owner
        assert owner.result(timeout=1.0)["outcome_unknown"] is True
    finally:
        bridge._process = None
        bridge._process_started = False
        bridge._reply_consumer = None
        bridge._reply_consumer_started = False
        bridge._safe_reply_consumer = None
        bridge._safe_reply_consumer_started = False
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            retired_safe_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_real_safe_reply_pipe_eof_retires_healthy_generation_without_reply_timeout() -> None:
    bridge = ZmqBridge()
    request_id = "d" * 32
    owner: Future[dict[str, object]] = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = bridge._generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        bridge._generation,
        zmq_client.CommandClass.SAFE_DIRECTION,
        "keithley_emergency_off",
        "global",
    )

    class _LiveProcess:
        exitcode = None

        @staticmethod
        def is_alive() -> bool:
            return True

    bridge._process = _LiveProcess()  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = MagicMock(name="live_ordinary_consumer")
    bridge._reply_consumer.is_alive.return_value = True
    bridge._reply_consumer_started = True
    bridge._safe_reply_consumer = MagicMock(name="live_safe_consumer")
    bridge._safe_reply_consumer.is_alive.return_value = True
    bridge._safe_reply_consumer_started = True
    bridge._last_heartbeat = time.monotonic()
    bridge._command_admission_open = True
    bridge._reply_stop.clear()
    assert bridge.is_alive() is True
    assert bridge.is_healthy() is True

    bridge._safe_reply_child_sender.close()
    consumer = threading.Thread(target=bridge._consume_safe_replies, daemon=True)
    bridge._safe_reply_consumer = consumer
    started_at = time.monotonic()
    consumer.start()
    consumer.join(1.0)
    elapsed = time.monotonic() - started_at

    try:
        assert elapsed < 1.0
        assert consumer.is_alive() is False
        assert bridge._command_admission_open is False
        assert bridge._shutdown_event.is_set()
        assert bridge.is_alive() is False
        assert bridge.is_healthy() is False
        assert bridge._generation_fatal is not None
        assert bridge._generation_fatal.lane == "safe"
        assert request_id not in bridge._pending
        assert bridge._outcome_unknown[request_id] is owner
        assert owner.result(timeout=0.1)["outcome_unknown"] is True
    finally:
        bridge._process = None
        bridge._process_started = False
        bridge._reply_consumer = None
        bridge._reply_consumer_started = False
        bridge._safe_reply_consumer = None
        bridge._safe_reply_consumer_started = False
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_real_safe_command_pipe_failure_retires_generation_and_retains_unknown_owner() -> None:
    bridge = ZmqBridge()

    class _LiveProcess:
        exitcode = None

        @staticmethod
        def is_alive() -> bool:
            return True

    bridge._process = _LiveProcess()  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = MagicMock(name="live_ordinary_consumer")
    bridge._reply_consumer.is_alive.return_value = True
    bridge._reply_consumer_started = True
    bridge._safe_reply_consumer = MagicMock(name="live_safe_consumer")
    bridge._safe_reply_consumer.is_alive.return_value = True
    bridge._safe_reply_consumer_started = True
    bridge._last_heartbeat = time.monotonic()
    bridge._command_admission_open = True
    bridge._reply_stop.clear()
    assert bridge.is_alive() is True
    assert bridge.is_healthy() is True

    bridge._safe_cmd_child_receiver.close()
    started_at = time.monotonic()
    result = bridge.send_command({"cmd": "keithley_emergency_off"})
    elapsed = time.monotonic() - started_at

    try:
        assert elapsed < 1.0
        assert result["outcome_unknown"] is True
        assert result["dispatched"] is True
        request_id = result["request_id"]
        assert bridge._command_admission_open is False
        assert bridge._shutdown_event.is_set()
        assert bridge.is_alive() is False
        assert bridge.is_healthy() is False
        assert bridge._generation_fatal is not None
        assert bridge._generation_fatal.lane == "safe_command"
        assert request_id in bridge._outcome_unknown
    finally:
        bridge._process = None
        bridge._process_started = False
        bridge._reply_consumer = None
        bridge._reply_consumer_started = False
        bridge._safe_reply_consumer = None
        bridge._safe_reply_consumer_started = False
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_shutdown_closes_admission_before_reply_consumers_observe_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()

    class _LiveProcess:
        exitcode = None

        @staticmethod
        def is_alive() -> bool:
            return True

    observations: list[bool] = []
    real_stop = threading.Event()

    class _ObservedStop:
        def set(self) -> None:
            observations.append(bridge._command_admission_open)
            real_stop.set()

        def is_set(self) -> bool:
            return real_stop.is_set()

        def clear(self) -> None:
            real_stop.clear()

    bridge._process = _LiveProcess()  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = MagicMock(name="ordinary_consumer")
    bridge._reply_consumer.is_alive.return_value = True
    bridge._reply_consumer_started = True
    bridge._safe_reply_consumer = MagicMock(name="safe_consumer")
    bridge._safe_reply_consumer.is_alive.return_value = True
    bridge._safe_reply_consumer_started = True
    bridge._command_admission_open = True
    bridge._reply_stop = _ObservedStop()  # type: ignore[assignment]
    monkeypatch.setattr(bridge, "_settle_runtime_owners_locked", lambda **_kwargs: 0)

    assert bridge.is_alive() is True
    bridge.shutdown()

    assert observations == [False]
    assert bridge._command_admission_open is False
    assert bridge.is_alive() is False


def test_stop_set_defensively_rejects_dispatch_even_if_admission_flag_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    cancelled = threading.Event()

    class _DispatchProbe:
        def __init__(self) -> None:
            self.items: list[dict[str, object]] = []

        def put(self, item, timeout=None) -> None:  # noqa: ANN001
            del timeout
            self.items.append(item)
            cancelled.set()

        def put_nowait(self, item) -> None:  # noqa: ANN001
            self.put(item)

    dispatch = _DispatchProbe()
    bridge._cmd_queue = dispatch  # type: ignore[assignment]
    bridge._command_admission_open = True
    bridge._reply_stop.set()
    monkeypatch.setattr(bridge, "is_alive", lambda: True)

    result = bridge._send_command_once(
        {"cmd": "safety_status"},
        cancellation_requested=cancelled,
    )

    assert result["error_code"] == "bridge_lifecycle_retired"
    assert result["delivery_state"] == "not_dispatched"
    assert dispatch.items == []


@pytest.mark.parametrize(
    ("failure_owner", "failure_phase"),
    [
        ("process", "process start"),
        ("zmq-reply-consumer", "ordinary reply consumer start"),
        ("zmq-safe-reply-consumer", "safe reply consumer start"),
    ],
)
def test_start_failure_rolls_back_every_started_owner_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure_owner: str,
    failure_phase: str,
) -> None:
    bridge = ZmqBridge()
    controller = SimpleNamespace(failure_owner=failure_owner)
    processes: list[object] = []
    consumers: list[object] = []

    class _Process:
        pid = 7319
        exitcode: int | None = None

        def __init__(self, *, args, **_kwargs) -> None:  # noqa: ANN001
            self.shutdown_event = args[5]
            self.started = False
            self.alive = False
            processes.append(self)

        def start(self) -> None:
            if controller.failure_owner == "process":
                raise RuntimeError("process start failed")
            self.started = True
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout=None) -> None:
            del timeout
            if not self.started:
                raise AssertionError("never-started process must not be joined")
            if self.shutdown_event.is_set():
                self.alive = False
                self.exitcode = 0

        def terminate(self) -> None:
            self.alive = False
            self.exitcode = -15

        def kill(self) -> None:
            self.alive = False
            self.exitcode = -9

    class _Thread:
        def __init__(self, *, name: str, **_kwargs) -> None:
            self.name = name
            self.started = False
            self.alive = False
            consumers.append(self)

        def start(self) -> None:
            if controller.failure_owner == self.name:
                raise RuntimeError(f"{self.name} start failed")
            self.started = True
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout=None) -> None:
            del timeout
            if self.started:
                self.alive = False

    monkeypatch.setattr(zmq_client.mp, "Process", _Process)
    monkeypatch.setattr(zmq_client.threading, "Thread", _Thread)

    try:
        with pytest.raises(RuntimeError, match="startup failed"):
            bridge.start()

        assert bridge._command_admission_open is False
        assert bridge._process is None
        assert bridge._reply_consumer is None
        assert bridge._safe_reply_consumer is None
        assert all(not owner.alive for owner in [*processes, *consumers])
        failed_generation = bridge._generation
        assert bridge._generation_fatal == zmq_client._BridgeGenerationFatal(
            failed_generation,
            failure_phase,
            "RuntimeError",
        )

        controller.failure_owner = None
        bridge.start()
        assert bridge._generation > failed_generation
        assert bridge._generation_fatal is None
        assert bridge._process is not None
        assert bridge._reply_consumer is not None
        assert bridge._safe_reply_consumer is not None
        assert bridge._command_admission_open is True
        bridge.shutdown()
        assert bridge._process is None
        assert bridge._reply_consumer is None
        assert bridge._safe_reply_consumer is None
    finally:
        bridge._process = None
        bridge._reply_consumer = None
        bridge._safe_reply_consumer = None
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


@pytest.mark.parametrize(
    ("command", "queue_name"),
    [
        ({"cmd": "protocol_version"}, "_cmd_queue"),
        ({"cmd": "experiment_finalize"}, "_cmd_queue"),
        ({"cmd": "keithley_emergency_off"}, "_safe_cmd_queue"),
        (
            {
                "cmd": "launcher_shutdown",
                "engine_instance_id": "a" * 32,
                "request_id": "c" * 32,
                "shutdown_capability": "b" * 64,
            },
            "_safe_cmd_queue",
        ),
    ],
)
def test_shutdown_admission_cut_rejects_every_command_before_retiring_generation(
    monkeypatch: pytest.MonkeyPatch,
    command: dict[str, str],
    queue_name: str,
) -> None:
    bridge = ZmqBridge()
    monkeypatch.setattr(bridge, "is_alive", lambda: True)
    bridge._mutation_receipt = {
        "schema": "mutation_compatibility_v1",
        "accepted": True,
        "server_protocol_major": 1,
        "required_capability": "cryodaq_mutation_v1",
        "capability_token": "a" * 32,
    }

    join_entered = threading.Event()
    allow_join = threading.Event()

    class _BlockingConsumer:
        def is_alive(self) -> bool:
            return not allow_join.is_set()

        def join(self, timeout: float) -> None:
            join_entered.set()
            assert allow_join.wait(timeout)

    cancellation_requested = threading.Event()

    class _RecordingQueue:
        def __init__(self) -> None:
            self.items: list[dict[str, object]] = []

        def put(self, item: dict[str, object], timeout: float) -> None:
            del timeout
            self.items.append(item)
            cancellation_requested.set()

    bridge._reply_consumer = _BlockingConsumer()
    bridge._reply_consumer_started = True
    dispatch = _RecordingQueue()
    setattr(bridge, queue_name, dispatch)
    shutdown_error: list[BaseException] = []

    def _shutdown() -> None:
        try:
            bridge.shutdown()
        except BaseException as exc:
            shutdown_error.append(exc)

    shutdown_owner = threading.Thread(target=_shutdown, name="bridge-shutdown-owner")
    shutdown_owner.start()
    assert join_entered.wait(1.0)
    try:
        result = bridge.send_command(
            command,
            cancellation_requested=cancellation_requested,
        )
        assert result["ok"] is False
        assert result["error_code"] == "bridge_lifecycle_retired"
        assert result["dispatched"] is False
        assert result["delivery_state"] == "not_dispatched"
        assert result["commit_state"] == "not_committed"
        assert dispatch.items == []
    finally:
        allow_join.set()
        shutdown_owner.join(5.0)
        assert not shutdown_owner.is_alive()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()

    assert shutdown_error == []
    assert bridge._pending == {}
    assert bridge._outcome_unknown == {}


def test_restart_settles_old_reply_consumer_before_queue_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()
    bridge._last_snapshot_time = 123.0
    bridge._bridge_instance_id = "e" * 32
    assert bridge.bridge_instance_id is not None
    close_attempted = threading.Event()

    class BlockingReplyQueue:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def get(self, timeout=None):
            self.entered.set()
            self.release.wait()
            raise queue.Empty

        def get_nowait(self):
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            close_attempted.set()

    old_queue = BlockingReplyQueue()
    bridge._reply_queue = old_queue
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    bridge._reply_consumer_started = True
    assert old_queue.entered.wait(1.0)

    real_join = consumer.join
    consumer.join = lambda timeout=None: real_join(0)  # type: ignore[method-assign]
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.mp.Process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("restart reached process spawn before old reply owner settled")
        ),
    )

    try:
        with pytest.raises(RuntimeError, match="ordinary reply consumer remained alive after join"):
            bridge.start()
        assert bridge._last_snapshot_time == 0.0
        assert bridge.bridge_instance_id is None
        assert bridge._reply_queue is old_queue
        assert not close_attempted.is_set()
        assert consumer.is_alive()
    finally:
        bridge._reply_stop.set()
        old_queue.release.set()
        real_join(1.0)
        assert not consumer.is_alive()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


@pytest.mark.parametrize(
    ("attribute", "drain_before_close", "task_done"),
    [
        ("_snapshot_queue", True, True),
        ("_data_queue", True, False),
        ("_cmd_queue", True, False),
        ("_reply_queue", False, False),
    ],
    ids=["snapshot", "data", "command", "reply"],
)
def test_restart_queue_close_failure_preserves_exact_owner_for_retry(
    attribute: str,
    drain_before_close: bool,
    task_done: bool,
) -> None:
    bridge = ZmqBridge()
    original = getattr(bridge, attribute)

    class _RetryCloseQueue:
        def __init__(self) -> None:
            self.close_calls = 0
            self.cancel_calls = 0
            self.join_calls = 0
            self.fail_close = True

        @staticmethod
        def get_nowait():  # noqa: ANN205
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            self.cancel_calls += 1

        def close(self) -> None:
            self.close_calls += 1
            if self.fail_close:
                raise OSError("retired queue close failed")

        def join_thread(self) -> None:
            self.join_calls += 1

    retired = _RetryCloseQueue()
    setattr(bridge, attribute, retired)
    try:
        with pytest.raises(OSError, match="retired queue close failed"):
            bridge._close_retired_mp_queue_locked(
                attribute,
                drain_before_close=drain_before_close,
                task_done=task_done,
            )

        assert getattr(bridge, attribute) is retired
        assert attribute not in bridge._restart_queue_closure_proofs
        assert retired.close_calls == 1

        retired.fail_close = False
        bridge._close_retired_mp_queue_locked(
            attribute,
            drain_before_close=drain_before_close,
            task_done=task_done,
        )

        assert getattr(bridge, attribute) is retired
        assert attribute in bridge._restart_queue_closure_proofs
        assert retired.close_calls == 2
        assert retired.cancel_calls == 0
        assert retired.join_calls == 1
    finally:
        setattr(bridge, attribute, original)
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                with contextlib.suppress(Exception):
                    endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_restart_refuses_replacement_until_retired_queue_feeder_is_terminal() -> None:
    bridge = ZmqBridge()
    attribute = "_cmd_queue"
    original = getattr(bridge, attribute)
    release = threading.Event()
    feeder = threading.Thread(target=release.wait, name="retired-command-feeder")
    feeder.start()

    class _OwnedQueue:
        def __init__(self) -> None:
            self._thread = feeder
            self.close_calls = 0
            self.join_calls = 0

        @staticmethod
        def get_nowait():  # noqa: ANN205
            raise queue.Empty

        def close(self) -> None:
            self.close_calls += 1

        def join_thread(self) -> None:
            self.join_calls += 1

    retired = _OwnedQueue()
    setattr(bridge, attribute, retired)
    try:
        with pytest.raises(RuntimeError, match="queue feeder remained alive"):
            bridge._close_retired_mp_queue_locked(
                attribute,
                drain_before_close=True,
            )

        assert getattr(bridge, attribute) is retired
        assert attribute not in bridge._restart_queue_closure_proofs
        assert retired.close_calls == 1
        assert retired.join_calls == 0

        release.set()
        feeder.join(timeout=1.0)
        assert not feeder.is_alive()
        bridge._close_retired_mp_queue_locked(
            attribute,
            drain_before_close=True,
        )
        assert attribute in bridge._restart_queue_closure_proofs
        assert retired.close_calls == 2
        assert retired.join_calls == 1
    finally:
        release.set()
        feeder.join(timeout=1.0)
        setattr(bridge, attribute, original)
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                with contextlib.suppress(Exception):
                    endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


@pytest.mark.parametrize(
    ("failure", "expected_cause"),
    [
        pytest.param("noncallable_join", TypeError, id="noncallable-join"),
        pytest.param("noncallable_is_alive", TypeError, id="noncallable-is-alive"),
        pytest.param("non_boolean_is_alive", RuntimeError, id="non-boolean-is-alive"),
        pytest.param("noncallable_join_thread", TypeError, id="noncallable-join-thread"),
    ],
)
def test_restart_candidate_owner_is_retained_until_terminal_proof_succeeds(
    failure: str,
    expected_cause: type[BaseException],
) -> None:
    bridge = ZmqBridge()
    attribute = "_cmd_queue"
    candidate = _QueueTerminalProofProbe()
    candidate.invalidate_terminal_proof(failure)
    bridge._restart_queue_candidates[attribute] = candidate

    try:
        with pytest.raises(
            RuntimeError,
            match=r"replacement candidate cleanup incomplete: _cmd_queue:(TypeError|RuntimeError)",
        ) as raised:
            bridge._settle_restart_candidates_locked()

        assert isinstance(raised.value.__cause__, expected_cause)
        assert bridge._restart_queue_candidates[attribute] is candidate
        assert candidate.close_calls == 1
        assert candidate.join_thread_calls == 0

        candidate.repair_terminal_proof()
        bridge._settle_restart_candidates_locked()

        assert attribute not in bridge._restart_queue_candidates
        assert candidate.close_calls == 2
        assert candidate.join_thread_calls == 1
        assert candidate._thread.is_alive() is False
    finally:
        bridge._restart_queue_candidates.clear()
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                with contextlib.suppress(Exception):
                    endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        pytest.param("noncallable_join", TypeError, id="noncallable-join"),
        pytest.param("noncallable_is_alive", TypeError, id="noncallable-is-alive"),
        pytest.param("non_boolean_is_alive", RuntimeError, id="non-boolean-is-alive"),
        pytest.param("noncallable_join_thread", TypeError, id="noncallable-join-thread"),
    ],
)
def test_terminal_queue_is_not_marked_joined_until_terminal_proof_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_error: type[BaseException],
) -> None:
    bridge = ZmqBridge()
    queue_attributes = (
        "_data_queue",
        "_cmd_queue",
        "_safe_cmd_queue",
        "_reply_queue",
        "_safe_reply_queue",
        "_snapshot_queue",
    )
    originals = {attribute: getattr(bridge, attribute) for attribute in queue_attributes}
    terminal_queues = {attribute: _QueueTerminalProofProbe() for attribute in queue_attributes}
    for attribute, terminal_queue in terminal_queues.items():
        setattr(bridge, attribute, terminal_queue)
    failing_queue = terminal_queues["_data_queue"]
    failing_queue.invalidate_terminal_proof(failure)
    monkeypatch.setattr(bridge, "shutdown", lambda: None)

    try:
        with pytest.raises(expected_error):
            bridge.close()

        assert bridge._terminal_closed is False
        assert bridge._terminal_queues_closed == {"data"}
        assert bridge._terminal_queues_joined == set()
        assert bridge._data_queue is failing_queue
        assert failing_queue.close_calls == 1
        assert failing_queue.join_thread_calls == 0

        failing_queue.repair_terminal_proof()
        bridge.close()

        expected_names = {
            "data",
            "command",
            "safe_command",
            "reply",
            "safe_reply",
            "snapshot",
        }
        assert bridge._terminal_closed is True
        assert bridge._terminal_queues_closed == expected_names
        assert bridge._terminal_queues_joined == expected_names
        assert failing_queue.close_calls == 1
        assert failing_queue.join_thread_calls == 1
        assert all(
            getattr(bridge, attribute) is terminal_queue for attribute, terminal_queue in terminal_queues.items()
        )
    finally:
        for attribute, original in originals.items():
            setattr(bridge, attribute, original)
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                with contextlib.suppress(Exception):
                    endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_partial_safe_ipc_construction_owner_is_retained_until_retry_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.core.safe_command_ipc import SafeIpcConstructionError

    bridge = ZmqBridge()
    live_bundle = {
        attribute: getattr(bridge, attribute)
        for attribute in (
            "_snapshot_queue",
            "_data_queue",
            "_cmd_queue",
            "_reply_queue",
            "_safe_cmd_queue",
            "_safe_reply_queue",
        )
    }

    class _RetryEndpoint:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("partial endpoint close failed")

    retained = _RetryEndpoint()
    construction_error = SafeIpcConstructionError(
        "partial safe IPC construction",
        (retained,),
    )

    def _fail_safe_ipc(_capacity: int):
        raise construction_error

    monkeypatch.setattr(zmq_client, "create_safe_command_ipc", _fail_safe_ipc)
    try:
        with pytest.raises(RuntimeError, match="construction and cleanup failed"):
            bridge._construct_and_install_restart_bundle_locked()

        assert bridge._restart_safe_ipc_construction_failure is construction_error
        assert construction_error.retained_endpoints == (retained,)
        assert retained.close_calls == 1
        assert bridge._restart_queue_candidates == {}
        assert all(getattr(bridge, attribute) is owner for attribute, owner in live_bundle.items())

        bridge._settle_restart_candidates_locked()

        assert retained.close_calls == 2
        assert construction_error.retained_endpoints == ()
        assert bridge._restart_safe_ipc_construction_failure is None
        assert all(getattr(bridge, attribute) is owner for attribute, owner in live_bundle.items())
    finally:
        for endpoint in (
            bridge._safe_cmd_queue,
            bridge._safe_cmd_child_receiver,
            bridge._safe_reply_queue,
            bridge._safe_reply_child_sender,
        ):
            if endpoint is not None:
                with contextlib.suppress(Exception):
                    endpoint.close()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_shutdown_drains_reply_emitted_during_terminal_child_join() -> None:
    bridge = ZmqBridge()
    retired_reply_queue: queue.Queue = queue.Queue()
    bridge._reply_queue = retired_reply_queue
    request_id = "late-terminal-reply"
    generation = bridge._generation
    owner: Future = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        generation,
        zmq_client.CommandClass.MUTATION,
        "experiment_abort",
    )
    read_request_id = "retired-read"
    read_owner: Future = Future()
    bridge._pending[read_request_id] = read_owner
    bridge._request_generation[read_request_id] = generation
    bridge._request_bindings[read_request_id] = zmq_client._RequestBinding(
        generation,
        zmq_client.CommandClass.READ,
        "protocol_version",
    )

    class TerminalProcess:
        exitcode = 0

        def join(self, timeout=None) -> None:
            del timeout
            retired_reply_queue.put({"_rid": request_id, "ok": True, "settled": "terminal"})

        def is_alive(self) -> bool:
            return False

    bridge._process = TerminalProcess()
    bridge._process_started = True
    bridge.shutdown()

    result = bridge.reconcile_late_result(request_id, generation=generation)
    assert result is not None
    assert result.reply == {"ok": True, "settled": "terminal"}
    read_result = read_owner.result(timeout=1.0)
    assert read_result["outcome_unknown"] is False
    assert read_result["commit_state"] == "not_applicable"
    assert read_result["retry_safe"] is True
    assert read_request_id not in bridge._pending
    assert read_request_id not in bridge._outcome_unknown
    assert read_request_id not in bridge._request_generation
    assert read_request_id not in bridge._request_bindings


def test_restart_routes_reply_arriving_during_retired_queue_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ZmqBridge()

    class _CloseableReplyQueue(queue.Queue):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled_join = False
            self.joined = False
            self.closed = False

        def cancel_join_thread(self) -> None:
            self.cancelled_join = True

        def close(self) -> None:
            self.closed = True

        def join_thread(self) -> None:
            self.joined = True

    retired_reply_queue = _CloseableReplyQueue()
    bridge._reply_queue = retired_reply_queue
    request_id = "between-drains"
    generation = bridge._generation
    owner: Future = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        generation,
        zmq_client.CommandClass.MUTATION,
        "experiment_abort",
    )
    read_request_id = "restart-retired-read"
    read_owner: Future = Future()
    bridge._pending[read_request_id] = read_owner
    bridge._request_generation[read_request_id] = generation
    bridge._request_bindings[read_request_id] = zmq_client._RequestBinding(
        generation,
        zmq_client.CommandClass.READ,
        "protocol_version",
    )

    class TriggerQueue:
        def __init__(self) -> None:
            self.triggered = False

        def get_nowait(self):
            if not self.triggered:
                self.triggered = True
                retired_reply_queue.put({"_rid": request_id, "ok": True, "settled": "during-retirement"})
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            pass

        def join_thread(self) -> None:
            pass

    class FakeProcess:
        pid = 123

        def __init__(self, *_args, **_kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

    class FakeThread:
        def __init__(self, *_args, **_kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            del timeout
            self._alive = False

    bridge._data_queue = TriggerQueue()
    monkeypatch.setattr(zmq_client.mp, "Process", FakeProcess)
    monkeypatch.setattr(zmq_client.threading, "Thread", FakeThread)

    try:
        bridge.start()
        replacement = owner.result(timeout=1.0)
        assert replacement["request_id"] == request_id
        assert replacement["generation"] == generation
        assert replacement["outcome_unknown"] is True
        read_replacement = read_owner.result(timeout=1.0)
        assert read_replacement["request_id"] == read_request_id
        assert read_replacement["generation"] == generation
        assert read_replacement["outcome_unknown"] is False
        assert read_replacement["commit_state"] == "not_applicable"
        assert read_replacement["retry_safe"] is True
        assert read_request_id not in bridge._pending
        assert read_request_id not in bridge._outcome_unknown
        assert read_request_id not in bridge._request_generation
        assert read_request_id not in bridge._request_bindings
        result = bridge.reconcile_late_result(request_id, generation=generation)
        assert result is not None
        assert result.reply == {"ok": True, "settled": "during-retirement"}
        assert request_id not in bridge._request_bindings
        assert retired_reply_queue.cancelled_join is False
        assert retired_reply_queue.joined is True
        assert retired_reply_queue.closed is True
        assert bridge._reply_queue is not retired_reply_queue
    finally:
        if bridge._reply_consumer is not None:
            bridge._reply_consumer.join()
        if bridge._safe_reply_consumer is not None:
            bridge._safe_reply_consumer.join()
        for owned_queue in (
            bridge._data_queue,
            bridge._cmd_queue,
            bridge._safe_cmd_queue,
            bridge._reply_queue,
            bridge._safe_reply_queue,
            bridge._snapshot_queue,
        ):
            with contextlib.suppress(Exception):
                owned_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                owned_queue.close()


def test_shutdown_fails_closed_when_reply_consumer_does_not_settle() -> None:
    bridge = ZmqBridge()
    bridge._last_snapshot_time = 123.0

    class BlockingConsumer:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            del timeout

    bridge._reply_consumer = BlockingConsumer()
    bridge._reply_consumer_started = True

    with pytest.raises(RuntimeError, match="reply consumer remained alive after join"):
        bridge.shutdown()

    assert bridge._last_snapshot_time == 0.0
    assert bridge.bridge_instance_id is None
    bridge._reply_consumer = None
    for owned_queue in (
        bridge._data_queue,
        bridge._cmd_queue,
        bridge._safe_cmd_queue,
        bridge._reply_queue,
        bridge._safe_reply_queue,
        bridge._snapshot_queue,
    ):
        with contextlib.suppress(Exception):
            owned_queue.cancel_join_thread()
        with contextlib.suppress(Exception):
            owned_queue.close()


def test_application_close_settles_all_real_qthreads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Deferred QObject deletion can abort the interpreter when this scenario
    # shares a QApplication polluted by hundreds of prior GUI tests.  Run the
    # real boundary in a fresh process: a Qt abort remains a hard non-zero test
    # failure, while unrelated suite-owned windows cannot corrupt the result.
    child_marker = "CRYODAQ_QTHREAD_SHUTDOWN_PROBE"
    if os.environ.get(child_marker) != "1":
        env = os.environ.copy()
        env[child_marker] = "1"
        env["QT_QPA_PLATFORM"] = "offscreen"
        repo_root = Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = str(repo_root / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(tmp_path / "isolated-shutdown"),
                f"{Path(__file__).resolve()}::test_application_close_settles_all_real_qthreads",
                "-q",
            ],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            f"isolated QThread shutdown probe failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    app = QApplication.instance() or QApplication([])
    session_epoch = zmq_client.open_gui_command_worker_admission()
    window = MainWindowV2()
    nested_owner = QObject(window)
    deferred_owner = QObject(window)
    entered = threading.Event()
    entered_ids: set[str] = set()
    exited_ids: set[str] = set()
    callbacks: list[dict] = []
    state_lock = threading.Lock()

    def blocking_send(
        cmd: dict,
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict:
        assert cancellation_requested is not None
        with state_lock:
            entered_ids.add(cmd["id"])
            if len(entered_ids) == 3:
                entered.set()
        assert cancellation_requested.wait(2.0)
        with state_lock:
            exited_ids.add(cmd["id"])
        return {"ok": False, "cancelled": True}

    monkeypatch.setattr(zmq_client, "send_command", blocking_send)
    workers = [
        zmq_client.ZmqCommandWorker({"cmd": "mutate", "id": "root"}, parent=window),
        zmq_client.ZmqCommandWorker(
            {"cmd": "mutate", "id": "nested-1"},
            parent=nested_owner,
        ),
        zmq_client.ZmqCommandWorker(
            {"cmd": "mutate", "id": "nested-2"},
            parent=deferred_owner,
        ),
    ]
    for worker in workers:
        worker.finished.connect(callbacks.append)
        worker.start()
    assert entered.wait(1.0)
    window.show()
    app.processEvents()
    deferred_owner.deleteLater()

    try:
        zmq_client.revoke_gui_command_worker_admission(session_epoch)
        window.close()
        app.processEvents()
        assert not window.isVisible()
        assert entered_ids == {"root", "nested-1", "nested-2"}
        assert exited_ids == entered_ids
        assert callbacks == []
        assert all(worker.isFinished() and not worker.isRunning() for worker in workers)
        assert all(worker._cancellation_requested.is_set() for worker in workers)
        assert not any(thread.isRunning() for thread in window.findChildren(QThread))
        window.deleteLater()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        assert callbacks == []
        assert not isValid(deferred_owner)
        assert not isValid(window)
        assert all(not isValid(worker) for worker in workers)
    finally:
        if zmq_client.gui_command_worker_admission_open():
            zmq_client.revoke_gui_command_worker_admission(session_epoch)
        for worker in workers:
            if isValid(worker) and worker.isRunning():
                worker.requestInterruption()
                worker.wait(2_000)
        if isValid(window):
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()


class _LiveLauncherStatusBridge:
    def is_alive(self) -> bool:
        return True

    def process_pid(self) -> int:
        return 41

    def restart_count(self) -> int:
        return 3


def _healthy_launcher_status_reply(command: dict[str, object]) -> dict[str, object]:
    if command == {"cmd": "safety_status"}:
        return {
            "ok": True,
            "state": "ready",
            "fault_reason": "",
            "fault_revision": 0,
            "fault_activated_at": 0.0,
            "recovery_reason": "",
            "channels_tracked": 0,
            "keithley_connected": False,
            "active_channels": [],
            "mock": True,
            "engine_instance_id": "a" * 32,
            "proto": zmq_client.CLIENT_PROTOCOL_VERSION,
        }
    assert command == {"cmd": "annunciation_status"}
    return {
        "ok": True,
        "engine_instance_id": "a" * 32,
        "snapshot_revision": 1,
        "activations": [],
        "proto": zmq_client.CLIENT_PROTOCOL_VERSION,
    }


def _launcher_status_window():
    """Build only the QObject-owned state needed by the real health tick."""

    from PySide6.QtWidgets import QMainWindow

    from cryodaq.launcher import LauncherWindow

    window = LauncherWindow.__new__(LauncherWindow)
    QMainWindow.__init__(window)
    window._runtime_callbacks_open = True
    window._runtime_callback_epoch = 7
    window._shutdown_requested = False
    window._assistant_enabled = False
    window._engine_instance_id = "a" * 32
    window._engine_unsettled_incarnation = None
    window._bridge_restart_fault = False
    window._bridge_restart_hold = False
    window._restart_giving_up = False
    window._restart_attempts = 0
    window._last_restart_time = 0.0
    window._tray_only = True
    window._alarm_timer = None
    window._engine_down_banner = None
    window._bridge = _LiveLauncherStatusBridge()
    window._replay_source = None
    window._safety_status_generation = 0
    window._annunciation_status_generation = 0
    window._safety_worker = None
    window._annunciation_worker = None
    window._last_safety_state = None
    window._last_alarm_count = None
    window._last_reading_time = 0.0
    window._periodic_reporting_fault = False
    window._tray_icon_green = "green"
    window._tray_icon_yellow = "yellow"
    window._tray_icon_red = "red"
    window._tray = SimpleNamespace(
        isVisible=lambda: False,
        setIcon=lambda _icon: None,
        setToolTip=lambda _text: None,
    )
    window._is_engine_alive = lambda: True
    return window


def test_launcher_status_poll_keeps_finished_worker_children_bounded(monkeypatch) -> None:
    """Repeated real launcher health ticks must not retain historical QThreads."""

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from cryodaq.launcher import LauncherWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        zmq_client,
        "send_command",
        lambda command, *, cancellation_requested=None: _healthy_launcher_status_reply(command),
    )
    window = _launcher_status_window()
    observed_workers: list[weakref.ReferenceType[zmq_client.ZmqCommandWorker]] = []

    try:
        for tick in range(8):
            LauncherWindow._check_engine_health(window)
            current_workers = (window._safety_worker, window._annunciation_worker)
            assert all(worker is not None for worker in current_workers)
            assert all(worker.wait(2_000) for worker in current_workers if worker is not None)

            deadline = time.monotonic() + 1.0
            while zmq_client.registered_gui_command_workers() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert zmq_client.registered_gui_command_workers() == ()

            observed_workers.extend(weakref.ref(worker) for worker in current_workers if worker is not None)
            del current_workers
            app.processEvents()
            gc.collect()

            children = window.findChildren(zmq_client.ZmqCommandWorker)
            assert len(children) <= 2, f"launcher retained {len(children)} status workers after tick {tick + 1}"
            assert sum(reference() is not None for reference in observed_workers) <= 2
    finally:
        window._safety_worker = None
        window._annunciation_worker = None
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
