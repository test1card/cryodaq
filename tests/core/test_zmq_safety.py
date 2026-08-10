"""Safety tests for ZMQ subprocess hardening: heartbeat, overflow, REP stuck state."""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import queue
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


_HEARTBEAT_COLLECTION_HANG_GUARD_S = 60.0


@dataclass
class _RunningBridge:
    data_queue: mp.Queue
    process: mp.Process


@contextlib.contextmanager
def _running_bridge(pub_addr: str, cmd_addr: str) -> Iterator[_RunningBridge]:
    """Run the real bridge subprocess and always settle its lifecycle."""
    from cryodaq.core.zmq_subprocess import zmq_bridge_main

    data_queue: mp.Queue = mp.Queue(maxsize=1000)
    command_queue: mp.Queue = mp.Queue(maxsize=100)
    reply_queue: mp.Queue = mp.Queue(maxsize=100)
    shutdown = mp.Event()
    process = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_queue, command_queue, reply_queue, shutdown),
        daemon=True,
    )
    process.start()
    try:
        yield _RunningBridge(data_queue, process)
    finally:
        shutdown.set()
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)


def _receive_heartbeat(bridge: _RunningBridge) -> dict[object, object]:
    try:
        message = bridge.data_queue.get(timeout=_HEARTBEAT_COLLECTION_HANG_GUARD_S)
    except queue.Empty:
        pytest.fail(
            "heartbeat collection hang guard expired; "
            f"bridge_alive={bridge.process.is_alive()}; exitcode={bridge.process.exitcode}"
        )
    assert isinstance(message, dict), f"expected heartbeat envelope, got {message!r}"
    assert message.get("__type") == "heartbeat", f"expected heartbeat envelope, got {message!r}"
    return message


class _OverflowProbeQueue:
    """Test queue proxy that gates the real warning enqueue."""

    def __init__(self, inner: mp.Queue) -> None:
        self._inner = inner
        self.warning_attempt = mp.Event()
        self.warning_release = mp.Event()
        self.warning_enqueued = mp.Event()

    def put_nowait(self, item: object) -> None:
        if isinstance(item, dict) and item.get("__type") == "warning":
            self.warning_attempt.set()
            if not self.warning_release.wait(timeout=8.0):
                raise queue.Full
            self.warning_release.clear()
            self._inner.put_nowait(item)
            self.warning_enqueued.set()
            return
        self._inner.put_nowait(item)

    def get(self, *args: object, **kwargs: object) -> object:
        return self._inner.get(*args, **kwargs)

    def full(self) -> bool:
        return self._inner.full()


def test_subprocess_sends_heartbeat() -> None:
    """A real bridge subprocess causally emits a heartbeat envelope."""
    with _running_bridge("tcp://127.0.0.1:59990", "tcp://127.0.0.1:59991") as bridge:
        _receive_heartbeat(bridge)


def test_heartbeat_has_timestamp() -> None:
    """Heartbeat envelopes carry a positive float monotonic timestamp."""
    with _running_bridge("tcp://127.0.0.1:59992", "tcp://127.0.0.1:59993") as bridge:
        heartbeat = _receive_heartbeat(bridge)

    assert type(heartbeat["ts"]) is float
    assert heartbeat["ts"] > 0


# ---------------------------------------------------------------------------
# Queue overflow
# ---------------------------------------------------------------------------


def test_overflow_counter_emits_warning_on_queue_full() -> None:
    """When data_queue overflows, subprocess emits a structured warning envelope.

    The test proxy synchronizes on the production queue.Full path and gates the
    warning enqueue until the parent has freed a queue slot.  It then waits for
    the successful enqueue event before draining and checking the envelope.
    """
    from cryodaq.core.zmq_subprocess import zmq_bridge_main

    QUEUE_SIZE = 20
    data_q = _OverflowProbeQueue(mp.Queue(maxsize=QUEUE_SIZE))
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
                {"ts": _time.time(), "iid": "mock", "ch": f"CH{seq % 4}", "v": float(seq), "u": "K", "st": "ok"},
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

    # The probe observes the production queue.Full path and gates the warning
    # put.  Free one slot before releasing it, so the warning cannot be lost to
    # the full queue; then wait for the successful enqueue signal.
    assert data_q.warning_attempt.wait(timeout=8.0), "subprocess must reach the queue overflow warning path"
    data_q.get(timeout=1.0)
    data_q.warning_release.set()
    assert data_q.warning_enqueued.wait(timeout=8.0), "subprocess must enqueue the overflow warning"
    stop_pub.set()

    warning_received = False
    deadline = _time.monotonic() + 8.0
    while _time.monotonic() < deadline and not warning_received:
        try:
            msg = data_q.get(timeout=max(0.001, deadline - _time.monotonic()))
        except queue.Empty:
            break
        if isinstance(msg, dict) and msg.get("__type") == "warning":
            text = msg.get("message", "").lower()
            if "dropped" in text or "overflow" in text:
                warning_received = True
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
    """The serve loop must send the serialization-error fallback on a truly
    non-serializable reply, then continue serving the next command.

    ``json.dumps(obj, default=str)`` happily serializes any object whose
    ``__str__`` works (including plain ``object()``).  To actually trigger
    the serialization-error fallback path we need an object whose
    ``__str__`` (and ``__repr__``) both RAISE so that ``default=str``
    also fails.  The serve loop must then send
    ``{"ok": False, "error": "serialization error"}`` and keep the REP
    socket alive for the next command.
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

    class _TrulyUnserializable:
        """An object whose __str__ and __repr__ both raise, defeating default=str."""

        def __str__(self) -> str:
            raise RuntimeError("cannot convert to str")

        def __repr__(self) -> str:
            raise RuntimeError("cannot convert to repr")

    call_n = {"n": 0}

    async def handler(cmd: dict) -> dict:
        call_n["n"] += 1
        if call_n["n"] == 1:
            # Return a value that makes json.dumps(default=str) fail
            return {"ok": True, "bad": _TrulyUnserializable()}  # type: ignore[dict-item]
        return {"ok": True, "call": call_n["n"]}

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        ctx = zmq.asyncio.Context()
        req = ctx.socket(zmq.REQ)
        req.setsockopt(zmq.LINGER, 0)
        req.setsockopt(zmq.RCVTIMEO, 3000)
        req.connect(address)

        # First command: handler returns a truly non-serializable value
        await req.send(json.dumps({"cmd": "safety_status"}).encode())
        raw = await asyncio.wait_for(req.recv(), timeout=3.0)
        first = json.loads(raw)

        # Second command: server must still be serving (REP not wedged)
        await req.send(json.dumps({"cmd": "safety_status"}).encode())
        raw2 = await asyncio.wait_for(req.recv(), timeout=3.0)
        second = json.loads(raw2)

        req.close(linger=0)
        ctx.term()

        # First reply: must be the serialization-error fallback (not the bad value)
        assert isinstance(first, dict), "first reply must be a dict"
        assert first.get("ok") is False, f"serialization-error fallback must have ok=False; got {first}"
        assert first.get("error_code") == "command_reply_serialization_failed"
        assert first.get("error") == ("Command reply could not be serialized; outcome may be unknown.")
        assert first.get("delivery_state") == "dispatched"
        assert first.get("commit_state") == "not_applicable"
        assert first.get("retry_safe") is True
        assert first.get("proto") == 2
        # Second reply: server was not wedged
        assert second.get("ok") is True, f"second command must succeed; got {second}"
        assert second.get("call") == 2
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_serve_loop_handles_cancelled_error() -> None:
    """The serve loop makes a best-effort error reply when cancelled mid-handler.

    Contract (from zmq_bridge.py _serve_loop):
      - CancelledError during _run_handler → try to send {"ok": False, "error": "internal"}
        then re-raise.
      - The send is itself wrapped in try/except — if the socket is already torn
        down, the reply is silently lost.

    So the client MAY receive {"ok": False, "error": "internal"} or it MAY see
    a timeout/closed-socket error depending on ZMQ teardown ordering.  This test
    asserts: if a reply is received at all, it MUST be an error dict (ok=False).
    A TimeoutError / connection error means the reply was lost during teardown —
    that is within the documented contract and is not a regression.
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
        # If a reply arrived it MUST be an error dict — not a success response
        assert reply.get("ok") is False, f"CancelledError path must not return ok=True; got {reply}"
        assert "error" in reply, f"error key must be present in cancellation reply; got {reply}"
    except (TimeoutError, zmq.ZMQError):
        # Reply was lost during ZMQ teardown — within contract, not a regression.
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
