"""Regression tests for bridge subprocess thread separation.

After the 2026-04 stall bug: SUB drain must continue even when the
engine REP is absent or unresponsive, and heartbeats must keep flowing
because they come from the SUB drain thread (i.e. they prove the data
path is alive).
"""

from __future__ import annotations

import multiprocessing as mp
import queue as stdlib_queue
import socket
import threading
import time

import pytest

from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, zmq_bridge_main


def _find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def _bridge_fixture():
    """Yield (pub_addr, cmd_addr, queues, shutdown_event, proc_holder).

    Tests append the mp.Process to proc_holder so the fixture can
    shut them down cleanly regardless of assertion outcome.
    """
    pub_port = _find_free_port()
    cmd_port = _find_free_port()
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    cmd_addr = f"tcp://127.0.0.1:{cmd_port}"
    data_q: mp.Queue = mp.Queue(maxsize=10_000)
    cmd_q: mp.Queue = mp.Queue(maxsize=1_000)
    reply_q: mp.Queue = mp.Queue(maxsize=1_000)
    shutdown: mp.Event = mp.Event()
    proc_holder: list[mp.Process] = []

    yield pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown, proc_holder

    shutdown.set()
    for proc in proc_holder:
        proc.join(timeout=3.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2.0)


def test_sub_drain_continues_when_rep_is_dead(_bridge_fixture):
    """Engine REP is deliberately never bound. Bridge must still
    drain SUB messages — they arrive in data_queue within seconds."""
    import zmq

    pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown, proc_holder = _bridge_fixture

    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.LINGER, 0)
    pub.bind(pub_addr)
    # slow joiner — SUB needs a moment to connect+subscribe
    time.sleep(0.3)

    stop_emit = threading.Event()

    def emit_readings():
        import msgpack

        while not stop_emit.is_set():
            payload = msgpack.packb(
                {
                    "ts": time.time(),
                    "iid": "mock",
                    "ch": "T1",
                    "v": 42.0,
                    "u": "K",
                    "st": "ok",
                }
            )
            try:
                pub.send_multipart([DEFAULT_TOPIC, payload])
            except zmq.ZMQError:
                break
            time.sleep(0.05)

    proc = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc_holder.append(proc)
    proc.start()

    emitter = threading.Thread(target=emit_readings, daemon=True)
    emitter.start()

    # Queue a command headed for the dead REP so cmd_forward is actively
    # blocked on req.recv_string() when we measure SUB drain.
    cmd_q.put({"type": "safety_status", "_rid": "x"})

    deadline = time.monotonic() + 8.0
    readings = []
    while time.monotonic() < deadline and len(readings) < 5:
        try:
            msg = data_q.get(timeout=0.5)
        except stdlib_queue.Empty:
            continue
        if isinstance(msg, dict) and msg.get("__type") in {"heartbeat", "warning"}:
            continue
        readings.append(msg)

    stop_emit.set()
    emitter.join(timeout=1.0)
    pub.close(linger=0)
    ctx.term()

    assert len(readings) >= 5, (
        f"SUB drain starved while REP is dead (got {len(readings)} readings)"
    )


def test_heartbeat_still_emitted_even_without_data(_bridge_fixture):
    """Heartbeat comes from sub_drain thread, so it arrives periodically
    even when no PUB is emitting and no REP is bound."""
    pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown, proc_holder = _bridge_fixture

    proc = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc_holder.append(proc)
    proc.start()

    # HEARTBEAT_INTERVAL is 5s; allow two intervals.
    deadline = time.monotonic() + 12.0
    heartbeats = 0
    while time.monotonic() < deadline and heartbeats < 1:
        try:
            msg = data_q.get(timeout=0.5)
        except stdlib_queue.Empty:
            continue
        if isinstance(msg, dict) and msg.get("__type") == "heartbeat":
            heartbeats += 1

    assert heartbeats >= 1, "no heartbeat arrived within 12s with no data and dead REP"


def test_cmd_timeout_emits_warning(_bridge_fixture):
    """A command to a dead REP should produce a warning control message
    on data_queue (so the GUI can distinguish command-channel failure
    from data starvation)."""
    pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown, proc_holder = _bridge_fixture

    proc = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc_holder.append(proc)
    proc.start()

    cmd_q.put({"type": "safety_status", "_rid": "r1"})

    # REQ RCVTIMEO is 3s — warning should appear within ~5s.
    deadline = time.monotonic() + 6.0
    got_warning = False
    while time.monotonic() < deadline and not got_warning:
        try:
            msg = data_q.get(timeout=0.5)
        except stdlib_queue.Empty:
            continue
        if isinstance(msg, dict) and msg.get("__type") == "warning":
            if "REP timeout" in str(msg.get("message", "")):
                got_warning = True

    assert got_warning, "cmd_forward did not emit a REP-timeout warning"
