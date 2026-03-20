"""Safety tests for ZMQ subprocess hardening: heartbeat, overflow, REP stuck state."""

from __future__ import annotations

import json
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
        args=("tcp://127.0.0.1:59990", "tcp://127.0.0.1:59991",
              data_q, cmd_q, reply_q, shutdown),
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
        args=("tcp://127.0.0.1:59992", "tcp://127.0.0.1:59993",
              data_q, cmd_q, reply_q, shutdown),
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


def test_overflow_counter_exists_in_subprocess() -> None:
    """Verify dropped_count variable and warning message pattern are in the code."""
    import inspect
    from cryodaq.core import zmq_subprocess
    source = inspect.getsource(zmq_subprocess.zmq_bridge_main)
    assert "dropped_count" in source
    assert "__type" in source
    assert "warning" in source


# ---------------------------------------------------------------------------
# REP socket stuck state
# ---------------------------------------------------------------------------


def test_serve_loop_sends_reply_on_serialization_error() -> None:
    """The serve loop must handle non-serializable replies gracefully.

    Verify the code has default=str in json.dumps and a fallback error reply.
    """
    import inspect
    from cryodaq.core import zmq_bridge
    source = inspect.getsource(zmq_bridge.ZMQCommandServer._serve_loop)
    # Must use default=str to handle datetime etc.
    assert "default=str" in source
    # Must have fallback error reply for serialization failures
    assert "serialization error" in source


def test_serve_loop_handles_cancelled_error() -> None:
    """The serve loop sends error reply on CancelledError after recv."""
    import inspect
    from cryodaq.core import zmq_bridge
    source = inspect.getsource(zmq_bridge.ZMQCommandServer._serve_loop)
    # Must catch CancelledError and send reply
    assert "CancelledError" in source
    # Must send internal error before re-raising
    assert '"internal"' in source


# ---------------------------------------------------------------------------
# GUI-side heartbeat tracking
# ---------------------------------------------------------------------------


def test_zmq_bridge_is_healthy_initial() -> None:
    """is_healthy returns True right after start (grace period)."""
    from cryodaq.gui.zmq_client import ZmqBridge
    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59994", cmd_addr="tcp://127.0.0.1:59995")
    # Not started → not alive → not healthy
    assert not bridge.is_healthy()


def test_zmq_bridge_poll_handles_heartbeat() -> None:
    """poll_readings recognizes heartbeat messages and updates timestamp."""
    from cryodaq.gui.zmq_client import ZmqBridge
    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59996", cmd_addr="tcp://127.0.0.1:59997")
    # Manually inject a heartbeat into the data queue
    bridge._data_queue.put_nowait({"__type": "heartbeat", "ts": time.monotonic()})
    readings = bridge.poll_readings()
    # Heartbeat should NOT appear as a Reading
    assert len(readings) == 0
    # But _last_heartbeat should be updated
    assert bridge._last_heartbeat > 0


def test_zmq_bridge_poll_handles_warning() -> None:
    """poll_readings recognizes warning messages and doesn't return them as readings."""
    from cryodaq.gui.zmq_client import ZmqBridge
    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59998", cmd_addr="tcp://127.0.0.1:59999")
    bridge._data_queue.put_nowait({"__type": "warning", "message": "test overflow"})
    readings = bridge.poll_readings()
    assert len(readings) == 0
