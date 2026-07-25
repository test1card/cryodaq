from __future__ import annotations

import threading
from concurrent.futures import Future

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.gui.zmq_client import ZmqBridge


class _Queue:
    def __init__(self, on_put=None):
        self.items = []
        self.on_put = on_put

    def put(self, item, timeout=0):
        self.items.append(item)
        if self.on_put:
            self.on_put(item)

    def put_nowait(self, item):
        self.put(item)

    def get_nowait(self):
        if not self.items:
            raise __import__("queue").Empty
        return self.items.pop(0)


def _install_mutation_receipt(bridge: ZmqBridge) -> None:
    bridge._mutation_receipt = {
        "schema": "mutation_compatibility_v1",
        "accepted": True,
        "server_protocol_major": 1,
        "required_capability": "cryodaq_mutation_v1",
        "capability_token": "a" * 32,
    }


def test_post_enqueue_cancellation_retains_outcome_unknown_until_reply(live_zmq_bridge, monkeypatch):
    cancelled = threading.Event()
    bridge = live_zmq_bridge
    _install_mutation_receipt(bridge)

    with monkeypatch.context() as command_queue_patch:
        command_queue_patch.setattr(bridge, "_cmd_queue", _Queue(lambda _item: cancelled.set()))
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)

    assert result["error"] == "ZMQ command outcome unknown after cancellation"
    request_id = result["request_id"]
    assert request_id in bridge._outcome_unknown
    future = bridge._outcome_unknown[request_id]
    consumer = threading.Thread(target=bridge._consume_replies)
    consumer.start()
    bridge._reply_queue.put({"_rid": request_id, "ok": True})
    for _ in range(100):
        if request_id not in bridge._outcome_unknown:
            break
        threading.Event().wait(0.01)
    bridge._reply_stop.set()
    consumer.join(timeout=1.0)
    assert not consumer.is_alive()
    assert request_id not in bridge._outcome_unknown
    assert request_id not in bridge._request_generation
    assert request_id not in bridge._request_bindings
    late = bridge.reconcile_late_result(request_id)
    assert late is not None
    assert late.request_id == request_id
    assert late.reply == {"ok": True}
    assert request_id not in bridge._outcome_unknown
    assert future.result(timeout=0.1) == {"ok": True}


def test_request_nonce_collision_never_overwrites_pending_owner(live_zmq_bridge, monkeypatch):
    bridge = live_zmq_bridge
    existing = Future()
    bridge._pending["deadbeef"] = existing
    cancelled = threading.Event()
    _install_mutation_receipt(bridge)

    values = iter(("deadbeef", "fresh-owner"))
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.uuid.uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    with monkeypatch.context() as command_queue_patch:
        command_queue_patch.setattr(bridge, "_cmd_queue", _Queue(lambda _item: cancelled.set()))
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)

    assert result["request_id"] == "fresh-owner"
    assert bridge._pending["deadbeef"] is existing
    assert "fresh-owner" in bridge._outcome_unknown
    with bridge._pending_lock:
        assert bridge._route_reply_locked(
            {"_rid": "fresh-owner", "ok": True},
            source_generation=bridge._generation,
            source_lane="ordinary",
        )
        assert bridge._retire_definitely_unsent_owner_locked("deadbeef", existing)
    late = bridge.reconcile_late_result("fresh-owner", generation=bridge._generation)
    assert late is not None
    assert late.reply == {"ok": True}
    assert existing.done() is False


def test_shutdown_retains_late_reply_for_exact_generation() -> None:
    bridge = ZmqBridge()
    bridge._generation = 7
    request_id = "request-7"
    owner = Future()
    bridge._outcome_unknown[request_id] = owner
    bridge._request_generation[request_id] = 7
    bridge._reply_queue = _Queue()
    bridge._reply_queue.put({"_rid": request_id, "ok": True, "revision": 4})

    bridge.shutdown()

    result = bridge.reconcile_late_result(request_id, generation=7)
    assert result is not None
    assert result.generation == 7
    assert result.reply == {"ok": True, "revision": 4}
    assert bridge.reconcile_late_result(request_id, generation=8) is None


# -- Structured settlement vocabulary on unknown-outcome client replies -------
#
# The transport vocabulary is {delivery_state, commit_state, outcome_unknown}.
# Three client-side unknown-outcome return paths used to set outcome_unknown=True
# and OMIT delivery_state/commit_state, so consumers reading the structured keys
# (cryodaq.gui.shell.command_outcome.result_outcome_unknown) saw them missing.
# Each path below asserts the reply carries delivery_state="dispatched" and
# commit_state="unknown": in all three the command WAS dispatched to the bridge
# and only the final outcome is unresolved.


def test_cancel_after_dispatch_unknown_reply_carries_settlement_vocabulary(live_zmq_bridge, monkeypatch):
    cancel_requested = threading.Event()
    bridge = live_zmq_bridge
    _install_mutation_receipt(bridge)

    with monkeypatch.context() as command_queue_patch:
        command_queue_patch.setattr(bridge, "_cmd_queue", _Queue(lambda _item: cancel_requested.set()))
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancel_requested)

    request_id = result["request_id"]
    try:
        assert result["error"] == "ZMQ command outcome unknown after cancellation"
        assert result["outcome_unknown"] is True
        assert result["delivery_state"] == "dispatched"
        assert result["commit_state"] == "unknown"
    finally:
        # Reconcile the retained outcome-unknown owner so the fixture's terminal
        # close() sees a fully settled bridge (it requires empty identity dicts).
        consumer = threading.Thread(target=bridge._consume_replies)
        consumer.start()
        bridge._reply_queue.put({"_rid": request_id, "ok": True})
        for _ in range(100):
            if request_id not in bridge._outcome_unknown:
                break
            threading.Event().wait(0.01)
        bridge._reply_stop.set()
        consumer.join(timeout=1.0)
        assert not consumer.is_alive()
        assert bridge.reconcile_late_result(request_id) is not None
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings


def test_timeout_after_dispatch_unknown_reply_carries_settlement_vocabulary(live_zmq_bridge, monkeypatch):
    monkeypatch.setattr(zmq_client, "_CMD_REPLY_TIMEOUT_S", 0.2)
    bridge = live_zmq_bridge
    _install_mutation_receipt(bridge)

    with monkeypatch.context() as command_queue_patch:
        # Accept publication (enqueued=True) but never deliver a reply, so the
        # post-dispatch wait loop falls through to the timeout-after-dispatch
        # return path in send_command.
        command_queue_patch.setattr(bridge, "_cmd_queue", _Queue())
        result = bridge.send_command({"cmd": "mutate"})

    request_id = result["request_id"]
    try:
        assert result["error"] == "ZMQ command outcome unknown after timeout"
        assert result["outcome_unknown"] is True
        assert result["delivery_state"] == "dispatched"
        assert result["commit_state"] == "unknown"
    finally:
        # Reconcile the retained outcome-unknown owner so the fixture's terminal
        # close() sees a fully settled bridge (it requires empty identity dicts).
        consumer = threading.Thread(target=bridge._consume_replies)
        consumer.start()
        bridge._reply_queue.put({"_rid": request_id, "ok": True})
        for _ in range(100):
            if request_id not in bridge._outcome_unknown:
                break
            threading.Event().wait(0.01)
        bridge._reply_stop.set()
        consumer.join(timeout=1.0)
        assert not consumer.is_alive()
        assert bridge.reconcile_late_result(request_id) is not None
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings


def test_lifecycle_settlement_unknown_reply_carries_settlement_vocabulary() -> None:
    bridge = ZmqBridge()
    request_id = "c" * 32
    owner: Future[dict[str, object]] = Future()
    bridge._pending[request_id] = owner
    bridge._request_generation[request_id] = bridge._generation
    bridge._request_bindings[request_id] = zmq_client._RequestBinding(
        bridge._generation,
        zmq_client.CommandClass.MUTATION,
        "mutate",
    )

    with bridge._pending_lock:
        bridge._settle_pending_for_lifecycle_locked(
            error="ZMQ bridge shutting down; outcome unknown",
            default_generation=bridge._generation,
        )

    result = owner.result(timeout=1.0)
    assert result["outcome_unknown"] is True
    assert result["delivery_state"] == "dispatched"
    assert result["commit_state"] == "unknown"
