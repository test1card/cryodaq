from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

import cryodaq.gui.zmq_client as zmq_client


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
