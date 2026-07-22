"""Fail-closed GUI mutation compatibility negotiation."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import pytest

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.gui.zmq_client import (
    _READ_ONLY_COMMANDS,
    ZmqBridge,
    _requires_mutation_envelope,
)


def _receipt(token: str = "a" * 32) -> dict[str, Any]:
    return {
        "ok": True,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": True,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_mutation_v1",
            "capability_token": token,
        },
    }


def _bridge_with_raw_handler(handler) -> ZmqBridge:
    bridge = object.__new__(ZmqBridge)
    bridge._mutation_lock = threading.Lock()
    bridge._mutation_receipt = None
    bridge._send_command_once = lambda command, *, cancellation_requested=None: handler(command)
    return bridge


@pytest.mark.parametrize("action", sorted(_READ_ONLY_COMMANDS))
def test_exact_read_inventory_never_requires_mutation_authority(action: str) -> None:
    assert _requires_mutation_envelope(action) is False


@pytest.mark.parametrize(
    "action",
    [
        "set_app_mode",
        "experiment_start",
        "experiment_create",
        "experiment_update",
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_attach_run_record",
        "experiment_create_retroactive",
        "experiment_generate_report",
        "experiment_advance_phase",
        "annunciation_ack",
        "alarm_v2_ack",
        "interlock_acknowledge",
        "safety_acknowledge",
        "log_entry",
        "keithley_stop",
        "keithley_start",
        "keithley_set_target",
        "keithley_set_limits",
        "multiline.set_channels",
        "multiline.burst_start",
        "multiline.burst_stop",
        "cooldown_alarm.arm",
        "cooldown_alarm.disarm",
        "calibration_curve_assign",
        "calibration_curve_export",
        "calibration_curve_import",
        "calibration_runtime_set_global",
        "calibration_runtime_set_channel_policy",
        "calibration_v2_fit",
        "leak_rate_start",
        "leak_rate_stop",
        "shift_handover_summary",
        "rag.rebuild_index",
    ],
)
def test_every_current_engine_mutation_requires_envelope(action: str) -> None:
    assert _requires_mutation_envelope(action) is True


def test_unknown_commands_default_to_mutation_class() -> None:
    assert _requires_mutation_envelope("future_command") is True
    assert _requires_mutation_envelope(1) is True
    assert _requires_mutation_envelope("") is True


def test_read_dispatches_directly_and_strips_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(command)
        return {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command(
        {
            "cmd": "annunciation_status",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True}
    assert calls == [{"cmd": "annunciation_status"}]


def test_assistant_protocol_version_dispatches_direct_without_engine_discovery() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(command)
        return {"ok": True, "proto": 2}

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command(
        {
            "cmd": "assistant.protocol_version",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True, "proto": 2}
    assert calls == [{"cmd": "assistant.protocol_version"}]


def test_safe_direction_emergency_off_dispatches_direct_and_strips_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command(
        {
            "cmd": "keithley_emergency_off",
            "channel": "smua",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True}
    assert calls == [{"cmd": "keithley_emergency_off", "channel": "smua"}]


def test_mutation_discovers_once_and_overwrites_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return _receipt() if command["cmd"] == "mutation_capabilities" else {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    forged = {
        "cmd": "keithley_start",
        "channel": "smua",
        "p_target": 1.0,
        "protocol_major": 999,
        "mutation_capability": "forged",
        "capability_token": "forged",
    }

    assert bridge.send_command(forged) == {"ok": True}
    assert bridge.send_command({"cmd": "keithley_stop", "channel": "smua"}) == {"ok": True}
    assert [call["cmd"] for call in calls] == [
        "mutation_capabilities",
        "keithley_start",
        "keithley_stop",
    ]
    for command in calls[1:]:
        assert command["protocol_major"] == 1
        assert command["mutation_capability"] == "cryodaq_mutation_v1"
        assert command["capability_token"] == "a" * 32


def test_invalid_discovery_fails_before_mutation_dispatch() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return _receipt("short")

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command({"cmd": "experiment_abort", "experiment_id": "exp-1"})

    assert result["ok"] is False
    assert result["error_code"] == "mutation_protocol_incompatible"
    assert result["retry_safe"] is True
    assert "capability_token" not in result["compatibility_receipt"]
    assert calls == [{"cmd": "mutation_capabilities"}]


def test_concurrent_mutations_share_one_discovery() -> None:
    calls: list[dict[str, Any]] = []
    calls_lock = threading.Lock()

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        with calls_lock:
            calls.append(dict(command))
        if command["cmd"] == "mutation_capabilities":
            time.sleep(0.03)
            return _receipt()
        return {"ok": True, "command": command["cmd"]}

    bridge = _bridge_with_raw_handler(raw)
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(
                lambda index: bridge.send_command(
                    {"cmd": "keithley_set_target", "channel": "smua", "p_target": index + 1.0}
                ),
                range(24),
            )
        )

    assert all(result["ok"] is True for result in results)
    assert sum(call["cmd"] == "mutation_capabilities" for call in calls) == 1
    mutations = [call for call in calls if call["cmd"] == "keithley_set_target"]
    assert len(mutations) == 24
    assert all(call["capability_token"] == "a" * 32 for call in mutations)


def test_rotated_token_invalidates_cache_without_replaying_rejected_mutation() -> None:
    discovery_tokens = iter(("a" * 32, "b" * 32))
    discoveries = 0
    mutation_calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        nonlocal discoveries
        if command["cmd"] == "mutation_capabilities":
            discoveries += 1
            return _receipt(next(discovery_tokens))
        mutation_calls.append(dict(command))
        if command["capability_token"] == "a" * 32:
            return {
                "ok": False,
                "error_code": "mutation_protocol_incompatible",
                "retry_safe": True,
            }
        return {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    command = {"cmd": "keithley_start", "channel": "smua", "p_target": 1.0}

    first = bridge.send_command(command)
    assert first["error_code"] == "mutation_protocol_incompatible"
    assert len(mutation_calls) == 1
    second = bridge.send_command(command)

    assert second == {"ok": True}
    assert discoveries == 2
    assert len(mutation_calls) == 2
    assert [call["capability_token"] for call in mutation_calls] == ["a" * 32, "b" * 32]


def test_cached_mutation_unknown_outcome_is_dispatched_once_without_discovery_or_replay() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return {
            "ok": False,
            "error_code": "command_outcome_unknown",
            "delivery_state": "unknown",
            "commit_state": "unknown",
            "retry_safe": False,
        }

    bridge = _bridge_with_raw_handler(raw)
    bridge._mutation_receipt = _receipt()["compatibility_receipt"]

    result = bridge.send_command({"cmd": "experiment_finalize", "experiment_id": "exp-1"})

    assert result["error_code"] == "command_outcome_unknown"
    assert result["retry_safe"] is False
    assert [call["cmd"] for call in calls] == ["experiment_finalize"]


@pytest.mark.parametrize("action", ["rag.rebuild_index", "rag.rebuild_status"])
def test_unknown_assistant_command_is_rejected_before_discovery_or_dispatch(action: str) -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command({"cmd": action})

    assert result["ok"] is False
    assert result["error_code"] == "assistant_read_only"
    assert result["delivery_state"] == "not_dispatched"
    assert result["commit_state"] == "not_committed"
    assert result["retry_safe"] is False
    assert calls == []


@pytest.mark.parametrize("command", [None, [], {}, {"cmd": ""}, {"cmd": 1}])
def test_malformed_command_never_reaches_transport(command) -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda payload: calls.append(payload) or {"ok": True})

    result = bridge.send_command(command)

    assert result["ok"] is False
    assert result["error_code"] == "command_invalid"
    assert calls == []


class _CommandQueue:
    def __init__(self, on_put: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.items: list[dict[str, Any]] = []
        self._on_put = on_put

    def put(self, item: dict[str, Any], timeout: float = 0.0) -> None:
        del timeout
        self.items.append(item)
        if self._on_put is not None:
            self._on_put(item)


def _bridge(monkeypatch) -> zmq_client.ZmqBridge:
    bridge = zmq_client.ZmqBridge()
    monkeypatch.setattr(bridge, "is_alive", lambda: True)
    bridge._mutation_receipt = _receipt()["compatibility_receipt"]
    return bridge


def _close_owned_queues(bridge: zmq_client.ZmqBridge) -> None:
    bridge._reply_stop.set()
    consumer = bridge._reply_consumer
    if consumer is not None and consumer.is_alive():
        consumer.join(1.0)
    if consumer is not None:
        assert not consumer.is_alive(), "reply consumer leaked past test cleanup"
    for owned in (
        bridge._data_queue,
        bridge._cmd_queue,
        bridge._reply_queue,
        bridge._snapshot_queue,
    ):
        with contextlib.suppress(Exception):
            owned.cancel_join_thread()
        with contextlib.suppress(Exception):
            owned.close()


def test_post_enqueue_cancel_retains_unknown_outcome_reconciliation(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        request_id = result["request_id"]
        assert result["ok"] is False
        assert "outcome unknown" in result["error"]
        assert len(bridge._cmd_queue.items) == 1
        assert request_id not in bridge._pending
        assert request_id in bridge._outcome_unknown
        assert bridge._request_generation[request_id] == bridge._generation
        assert bridge.reconcile_late_result(request_id, generation=bridge._generation) is None
    finally:
        _close_owned_queues(bridge)


def test_nonce_collision_never_overwrites_pending_owner(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    original = Future()
    bridge._pending["collision"] = original
    bridge._request_generation["collision"] = 3
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    values = iter(("collision", "fresh"))
    monkeypatch.setattr(
        zmq_client.uuid,
        "uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["request_id"] == "fresh"
        assert bridge._pending["collision"] is original
        assert bridge._request_generation["collision"] == 3
        assert bridge._outcome_unknown["fresh"] is not original
        assert bridge._cmd_queue.items[0]["_rid"] == "fresh"
    finally:
        _close_owned_queues(bridge)


def test_successful_reply_removes_pending_owner_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    duplicate_processed = threading.Event()
    original_check_proto = bridge._check_proto

    def _check_proto_with_barrier(reply: dict[str, Any]) -> None:
        original_check_proto(reply)
        if reply.get("_test_barrier") is True:
            duplicate_processed.set()

    monkeypatch.setattr(bridge, "_check_proto", _check_proto_with_barrier)
    replies = queue.Queue()
    bridge._reply_queue = replies
    seen: dict[str, str] = {}

    def dispatch(cmd: dict[str, Any]) -> None:
        seen["request_id"] = cmd["_rid"]
        replies.put({"_rid": cmd["_rid"], "ok": True, "revision": 1})

    bridge._cmd_queue = _CommandQueue(dispatch)
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    try:
        assert bridge.send_command({"cmd": "mutate"}) == {"ok": True, "revision": 1}
        request_id = seen["request_id"]
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._late_results
        assert request_id not in bridge._request_generation

        replies.put({"_rid": request_id, "ok": True, "revision": 2})
        replies.put({"_test_barrier": True})
        assert duplicate_processed.wait(1.0)
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert bridge.reconcile_late_result(request_id) is None
    finally:
        _close_owned_queues(bridge)


def test_late_reply_is_queryable_by_request_id_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    bridge._reply_queue = queue.Queue()
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        request_id = result["request_id"]
        generation = bridge._generation
        retained = bridge._outcome_unknown[request_id]
        bridge._reply_queue.put({"_rid": request_id, "ok": True, "revision": 9})
        assert retained.result(timeout=1.0) == {"ok": True, "revision": 9}

        assert bridge.reconcile_late_result(
            request_id,
            generation=generation,
        ) == zmq_client.LateCommandResult(
            request_id,
            generation,
            {"ok": True, "revision": 9},
        )
        assert bridge.reconcile_late_result(request_id, generation=generation) is None
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._late_results
        assert request_id not in bridge._request_generation
    finally:
        _close_owned_queues(bridge)


def test_first_late_terminal_reply_wins_over_contradictory_duplicate(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    request_id = "duplicate-late"
    generation = bridge._generation
    bridge._outcome_unknown[request_id] = Future()
    bridge._request_generation[request_id] = generation

    with bridge._pending_lock:
        assert bridge._route_reply_locked({"_rid": request_id, "ok": True, "revision": 1})
        assert bridge._route_reply_locked({"_rid": request_id, "ok": False, "error": "contradiction"})

    assert bridge.reconcile_late_result(
        request_id,
        generation=generation,
    ) == zmq_client.LateCommandResult(
        request_id,
        generation,
        {"ok": True, "revision": 1},
    )
    _close_owned_queues(bridge)


def test_nonce_collision_with_outcome_unknown_never_overwrites_owner(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    original = Future()
    bridge._outcome_unknown["collision"] = original
    bridge._request_generation["collision"] = 2
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    values = iter(("collision", "fresh"))
    monkeypatch.setattr(
        zmq_client.uuid,
        "uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["request_id"] == "fresh"
        assert bridge._outcome_unknown["collision"] is original
        assert bridge._request_generation["collision"] == 2
        assert bridge._outcome_unknown["fresh"] is not original
    finally:
        _close_owned_queues(bridge)


def test_outcome_unknown_capacity_fails_closed_without_eviction(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_UNRESOLVED_COMMANDS", 2)
    owners = {f"r{index}": Future() for index in range(2)}
    bridge._outcome_unknown.update(owners)
    bridge._request_generation.update({"r0": 1, "r1": 1})
    dispatch = _CommandQueue()
    bridge._cmd_queue = dispatch
    try:
        result = bridge.send_command({"cmd": "mutate"})
        assert result["ok"] is False
        assert "capacity exhausted" in result["error"]
        assert dispatch.items == []
        assert bridge._pending == {}
        assert set(bridge._outcome_unknown) == set(owners)
        assert all(bridge._outcome_unknown[key] is owner for key, owner in owners.items())
        assert bridge._request_generation == {"r0": 1, "r1": 1}
    finally:
        _close_owned_queues(bridge)


def test_timeout_reply_race_settles_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_CMD_REPLY_TIMEOUT_S", 0.0)
    timeout_lock_attempt = threading.Event()
    allow_timeout_owner = threading.Event()
    reply_set = threading.Event()

    class _RaceLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._sender_acquires = 0

        def __enter__(self):
            if threading.current_thread().name == "sender":
                self._sender_acquires += 1
                if self._sender_acquires == 2:
                    timeout_lock_attempt.set()
                    assert allow_timeout_owner.wait(1.0)
            self._lock.acquire()
            return self

        def __exit__(self, *_args) -> None:
            self._lock.release()

    bridge._pending_lock = _RaceLock()
    bridge._reply_queue = queue.Queue()
    captured: dict[str, str] = {}

    def dispatch(cmd: dict[str, Any]) -> None:
        captured["request_id"] = cmd["_rid"]
        bridge._pending[cmd["_rid"]].add_done_callback(lambda _future: reply_set.set())

    bridge._cmd_queue = _CommandQueue(dispatch)
    consumer = threading.Thread(
        target=bridge._consume_replies,
        name="consumer",
        daemon=True,
    )
    bridge._reply_consumer = consumer
    consumer.start()
    output: dict[str, dict[str, Any]] = {}
    sender = threading.Thread(
        target=lambda: output.setdefault(
            "result",
            bridge.send_command({"cmd": "mutate"}),
        ),
        name="sender",
    )
    try:
        sender.start()
        assert timeout_lock_attempt.wait(1.0)
        request_id = captured["request_id"]
        bridge._reply_queue.put({"_rid": request_id, "ok": True, "revision": 7})
        assert reply_set.wait(1.0)
        allow_timeout_owner.set()
        sender.join(1.0)
        assert not sender.is_alive()

        result = output["result"]
        if result.get("request_id") == request_id:
            late = bridge.reconcile_late_result(
                request_id,
                generation=bridge._generation,
            )
            assert late is not None
            assert late.reply == {"ok": True, "revision": 7}
            assert (
                bridge.reconcile_late_result(
                    request_id,
                    generation=bridge._generation,
                )
                is None
            )
        else:
            assert result == {"ok": True, "revision": 7}
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
    finally:
        allow_timeout_owner.set()
        if sender.is_alive():
            sender.join(1.0)
        assert not sender.is_alive(), "sender leaked past timeout/reply race"
        _close_owned_queues(bridge)


def test_pre_enqueue_cancel_is_definitely_not_dispatched(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    cancelled.set()
    dispatch = _CommandQueue()
    bridge._cmd_queue = dispatch
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["ok"] is False
        assert result.get("dispatched") is False
        assert "before dispatch" in result["error"]
        assert "request_id" not in result
        assert dispatch.items == []
        assert bridge._pending == {}
        assert bridge._outcome_unknown == {}
        assert bridge._request_generation == {}
    finally:
        _close_owned_queues(bridge)
