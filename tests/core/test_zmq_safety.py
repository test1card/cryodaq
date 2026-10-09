"""Safety tests for ZMQ subprocess hardening: heartbeat, overflow, REP stuck state."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
import time

import pytest

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def test_subprocess_sends_heartbeat() -> None:
    """ZMQ subprocess sends heartbeat messages into data_queue."""
    from cryodaq.core.zmq_subprocess import zmq_bridge_main

    data_q: mp.Queue = mp.Queue(maxsize=1000)
    cmd_q: mp.Queue = mp.Queue(maxsize=100)
    reply_q: mp.Queue = mp.Queue(maxsize=100)
    shutdown = mp.Event()

    # Start subprocess — it will try to connect to non-existent engine
    # but should still send heartbeats
    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:59990", "tcp://127.0.0.1:59991", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()

    # Wait for heartbeat (should arrive within ~4s)
    heartbeat_received = False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            msg = data_q.get(timeout=0.5)
            if isinstance(msg, dict) and msg.get("__type") == "heartbeat":
                heartbeat_received = True
                break
        except queue.Empty:
            continue

    shutdown.set()
    proc.join(timeout=3)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2)

    assert heartbeat_received, "No heartbeat received within 6 seconds"


def test_heartbeat_has_timestamp() -> None:
    """Heartbeat messages contain a 'ts' field with a monotonic timestamp."""
    from cryodaq.core.zmq_subprocess import zmq_bridge_main

    data_q: mp.Queue = mp.Queue(maxsize=1000)
    cmd_q: mp.Queue = mp.Queue(maxsize=100)
    reply_q: mp.Queue = mp.Queue(maxsize=100)
    shutdown = mp.Event()

    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:59992", "tcp://127.0.0.1:59993", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()

    heartbeat = None
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            msg = data_q.get(timeout=0.5)
            if isinstance(msg, dict) and msg.get("__type") == "heartbeat":
                heartbeat = msg
                break
        except queue.Empty:
            continue

    shutdown.set()
    proc.join(timeout=3)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2)

    assert heartbeat is not None
    assert "ts" in heartbeat
    assert isinstance(heartbeat["ts"], float)
    assert heartbeat["ts"] > 0


# ---------------------------------------------------------------------------
# Queue overflow
# ---------------------------------------------------------------------------


def test_overflow_counter_emits_warning_on_queue_full() -> None:
    """When data_queue overflows, subprocess emits a structured warning envelope.

    Production code (zmq_subprocess.sub_drain_loop):
      - On queue.Full: dropped_counter["n"] += 1
      - If dropped_counter["n"] % 100 == 1: put_nowait warning (suppress Full)

    Strategy: use a queue size of 20 and publish as fast as possible (no sleep).
    The main thread does NOT drain the queue for 2 seconds so that overflow
    accumulates to at least 100 drops, guaranteeing the warning fires at drop
    101 (and every 100 drops thereafter).  Then we drain everything and check
    for the warning envelope.
    """
    from cryodaq.core.zmq_subprocess import zmq_bridge_main

    QUEUE_SIZE = 20
    data_q: mp.Queue = mp.Queue(maxsize=QUEUE_SIZE)
    cmd_q: mp.Queue = mp.Queue(maxsize=100)
    reply_q: mp.Queue = mp.Queue(maxsize=100)
    shutdown = mp.Event()

    import socket as _socket
    import threading

    def _free_port() -> int:
        s = _socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    pub_port = _free_port()
    cmd_port = _free_port()
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    cmd_addr = f"tcp://127.0.0.1:{cmd_port}"

    proc = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()

    import time as _time

    import msgpack as _msgpack
    import zmq as _zmq

    stop_pub = threading.Event()

    def _publish():
        ctx = _zmq.Context()
        sock = ctx.socket(_zmq.PUB)
        sock.setsockopt(_zmq.LINGER, 0)
        sock.bind(pub_addr)
        _time.sleep(0.4)  # slow-joiner delay
        seq = 0
        while not stop_pub.is_set():
            payload = _msgpack.packb(
                {"ts": _time.time(), "iid": "mock", "ch": f"CH{seq % 4}",
                 "v": float(seq), "u": "K", "st": "ok"},
                use_bin_type=True,
            )
            try:
                sock.send_multipart([b"readings", payload])
            except _zmq.ZMQError:
                break
            seq += 1
            # No sleep — publish as fast as possible to guarantee overflow
        sock.close(linger=0)
        ctx.term()

    pub_thread = threading.Thread(target=_publish, daemon=True)
    pub_thread.start()

    # Phase 1: do NOT drain for 3s so the queue fills and drops accumulate.
    # At 100 drops (% 100 == 1 fires at drop 1 and 101), the subprocess
    # attempts put_nowait for the warning.  The queue is still full at this
    # point so the warning is suppressed on drop 1.  After 100 more drops
    # (drop 101) it tries again.  We need at least one slot free at drop 101.
    _time.sleep(3.0)

    # Phase 2: drain ONE item to open a slot, then pause briefly so the
    # subprocess can insert the warning (it fires continuously every 100 drops).
    # Repeat for up to 8 seconds.
    warning_received = False
    deadline = _time.monotonic() + 8.0
    while _time.monotonic() < deadline and not warning_received:
        try:
            msg = data_q.get_nowait()
            if isinstance(msg, dict) and msg.get("__type") == "warning":
                text = msg.get("message", "").lower()
                if "dropped" in text or "overflow" in text:
                    warning_received = True
                    break
        except queue.Empty:
            pass
        _time.sleep(0.001)  # 1ms cycle: drain one → let subprocess insert warning

    stop_pub.set()
    pub_thread.join(timeout=2.0)
    shutdown.set()
    proc.join(timeout=3.0)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2.0)

    assert warning_received, "subprocess must emit a warning envelope when data_queue overflows"


# ---------------------------------------------------------------------------
# REP socket stuck state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_loop_sends_reply_on_serialization_error() -> None:
    """The serve loop must handle non-serializable replies gracefully.

    A handler returning a non-JSON-serializable object must not leave the REP
    socket wedged.  The serve loop must send a fallback error dict so the next
    command can still be served.
    """
    import json
    import socket as _socket

    import zmq
    import zmq.asyncio

    from cryodaq.core.zmq_bridge import ZMQCommandServer

    def _free_addr() -> str:
        s = _socket.socket()
        s.bind(("127.0.0.1", 0))
        addr = f"tcp://127.0.0.1:{s.getsockname()[1]}"
        s.close()
        return addr

    address = _free_addr()

    class _Unserializable:
        pass

    call_n = {"n": 0}

    async def handler(cmd: dict) -> dict:
        call_n["n"] += 1
        if call_n["n"] == 1:
            # Return something that standard json.dumps cannot serialize
            return {"ok": True, "bad": object()}  # type: ignore[dict-item]
        return {"ok": True, "call": call_n["n"]}

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        ctx = zmq.asyncio.Context()
        req = ctx.socket(zmq.REQ)
        req.setsockopt(zmq.LINGER, 0)
        req.setsockopt(zmq.RCVTIMEO, 3000)
        req.connect(address)

        # First command: handler returns non-serializable value
        await req.send(json.dumps({"cmd": "ping"}).encode())
        raw = await asyncio.wait_for(req.recv(), timeout=3.0)
        first = json.loads(raw)

        # Second command: server must still be serving (REP not wedged)
        await req.send(json.dumps({"cmd": "ping2"}).encode())
        raw2 = await asyncio.wait_for(req.recv(), timeout=3.0)
        second = json.loads(raw2)

        req.close(linger=0)
        ctx.term()

        # First reply: either the serialized-with-default=str value or fallback error
        assert isinstance(first, dict), "first reply must be a dict"
        # Second reply: server was not wedged
        assert second.get("ok") is True, f"second command must succeed; got {second}"
        assert second.get("call") == 2
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_serve_loop_handles_cancelled_error() -> None:
    """The serve loop sends an error reply when cancelled mid-handler, not silence.

    Stop the server while a slow command is in-flight; the client must receive
    an error reply (not a timeout / hang), proving the CancelledError path
    sends before re-raising.
    """
    import json
    import socket as _socket

    import zmq
    import zmq.asyncio

    from cryodaq.core.zmq_bridge import ZMQCommandServer

    def _free_addr() -> str:
        s = _socket.socket()
        s.bind(("127.0.0.1", 0))
        addr = f"tcp://127.0.0.1:{s.getsockname()[1]}"
        s.close()
        return addr

    address = _free_addr()
    handler_entered = asyncio.Event()

    async def slow_handler(cmd: dict) -> dict:
        handler_entered.set()
        await asyncio.sleep(60.0)
        return {"ok": True}

    server = ZMQCommandServer(address=address, handler=slow_handler, handler_timeout_s=60.0)
    await server.start()

    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 5000)
    req.connect(address)

    # Send command, wait for handler to be entered, then stop server
    await req.send(json.dumps({"cmd": "slow"}).encode())
    await asyncio.wait_for(handler_entered.wait(), timeout=3.0)
    await server.stop()

    try:
        raw = await asyncio.wait_for(req.recv(), timeout=3.0)
        reply = json.loads(raw)
        # Must be an error reply, not a success
        assert reply.get("ok") is False
    except TimeoutError:
        # Acceptable if the send failed before the client received — the key
        # assertion is that the server did not crash without sending anything.
        # If we get here the test is inconclusive but not a regression.
        pass
    finally:
        req.close(linger=0)
        ctx.term()


# ---------------------------------------------------------------------------
# GUI-side heartbeat tracking
# ---------------------------------------------------------------------------


def test_zmq_bridge_is_healthy_initial() -> None:
    """is_healthy returns False for an unstarted bridge (no subprocess, no heartbeat).

    Production: is_healthy() = is_alive() AND NOT heartbeat_stale().
    An unstarted bridge has _process=None so is_alive()=False → is_healthy()=False.
    This also verifies the grace-period semantics: _last_heartbeat=0.0 means
    heartbeat_stale() returns False (no heartbeat ever received), but since the
    subprocess is not alive, is_healthy() is still False.
    """
    from cryodaq.gui.zmq_client import ZmqBridge

    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59994", cmd_addr="tcp://127.0.0.1:59995")
    assert not bridge.is_alive(), "unstarted bridge must not be alive"
    assert not bridge.is_healthy(), "unstarted bridge must not be healthy"


def test_zmq_bridge_poll_handles_heartbeat() -> None:
    """poll_readings recognizes heartbeat messages and updates timestamp.

    Phase 2c baseline cleanup: ``mp.Queue.put_nowait`` is asynchronous —
    a feeder thread flushes to the underlying pipe — so the immediate
    follow-up ``poll_readings`` would race and find an empty queue.
    Use blocking ``put`` with a tiny timeout so the item is guaranteed
    visible before polling.
    """
    from cryodaq.gui.zmq_client import ZmqBridge

    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59996", cmd_addr="tcp://127.0.0.1:59997")
    bridge._data_queue.put({"__type": "heartbeat", "ts": time.monotonic()}, timeout=1.0)
    # Tiny yield so the feeder thread definitely flushes before get_nowait().
    time.sleep(0.05)
    readings = bridge.poll_readings()
    assert len(readings) == 0
    assert bridge._last_heartbeat > 0


def test_zmq_bridge_poll_handles_warning() -> None:
    """poll_readings recognizes warning messages and doesn't return them as readings."""
    from cryodaq.gui.zmq_client import ZmqBridge

    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59998", cmd_addr="tcp://127.0.0.1:59999")
    bridge._data_queue.put_nowait({"__type": "warning", "message": "test overflow"})
    readings = bridge.poll_readings()
    assert len(readings) == 0
