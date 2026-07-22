from __future__ import annotations

import threading
from concurrent.futures import Future

from cryodaq.gui.zmq_client import ZmqBridge


class _Queue:
    def __init__(self, on_put=None):
        self.items = []
        self.on_put = on_put

    def put(self, item, timeout=0):
        self.items.append(item)
        if self.on_put:
            self.on_put(item)


def test_post_enqueue_cancellation_retains_outcome_unknown_until_reply(monkeypatch):
    cancelled = threading.Event()
    bridge = ZmqBridge()
    bridge._process = object()
    bridge.is_alive = lambda: True
    bridge._cmd_queue = _Queue(lambda _item: cancelled.set())

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
    assert future.result(timeout=0.1) == {"ok": True}


def test_request_nonce_collision_never_overwrites_pending_owner(monkeypatch):
    bridge = ZmqBridge()
    bridge._process = object()
    bridge.is_alive = lambda: True
    existing = Future()
    bridge._pending["deadbeef"] = existing
    cancelled = threading.Event()
    bridge._cmd_queue = _Queue(lambda _item: cancelled.set())

    values = iter(("deadbeef", "fresh-owner"))
    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.uuid.uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)

    assert result["request_id"] == "fresh-owner"
    assert bridge._pending["deadbeef"] is existing
    assert "fresh-owner" in bridge._outcome_unknown
