"""Regression test for bridge subprocess SUB subscription.

Reproduces the stall bug where zmq_subprocess.zmq_bridge_main set up the SUB
socket with setsockopt_string(SUBSCRIBE, "") BEFORE connect() — which produced
zero received messages on macOS Python 3.14 pyzmq 25+. The fix (connect-first,
then subscribe(b"readings")) must keep readings flowing through the multiprocessing
data queue.
"""

from __future__ import annotations

import multiprocessing as mp
import socket
import threading
import time

import msgpack
import pytest
import zmq

from cryodaq.core.zmq_bridge import DEFAULT_TOPIC
from cryodaq.core.zmq_subprocess import zmq_bridge_main


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pack_reading(seq: int) -> bytes:
    return msgpack.packb(
        {
            "ts": time.time(),
            "iid": "mock_instrument",
            "ch": f"ch_{seq % 4}",
            "v": 42.0 + seq,
            "u": "K",
            "st": "ok",
            "raw": None,
            "meta": {},
        },
        use_bin_type=True,
    )


def _run_publisher(address: str, stop: threading.Event, interval_s: float = 0.1) -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.bind(address)
    try:
        seq = 0
        while not stop.is_set():
            sock.send_multipart([DEFAULT_TOPIC, _pack_reading(seq)])
            seq += 1
            stop.wait(interval_s)
    finally:
        sock.close(linger=0)
        ctx.term()


def test_bridge_subprocess_receives_published_readings():
    """Bridge subprocess must deliver readings from PUB to the data queue.

    Regression guard for the connect-before-subscribe fix in zmq_subprocess.py.
    Publisher emits every 100ms; bridge should surface ≥ 3 readings in ≤ 2s.
    """
    pub_port = _free_tcp_port()
    cmd_port = _free_tcp_port()
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    cmd_addr = f"tcp://127.0.0.1:{cmd_port}"

    data_q: mp.Queue = mp.Queue(maxsize=100)
    cmd_q: mp.Queue = mp.Queue(maxsize=100)
    reply_q: mp.Queue = mp.Queue(maxsize=100)
    shutdown = mp.Event()

    stop_pub = threading.Event()
    pub_thread = threading.Thread(
        target=_run_publisher,
        args=(pub_addr, stop_pub),
        daemon=True,
    )
    pub_thread.start()

    proc = mp.Process(
        target=zmq_bridge_main,
        args=(pub_addr, cmd_addr, data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()

    try:
        readings = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(readings) < 3:
            try:
                msg = data_q.get(timeout=deadline - time.monotonic())
            except Exception:
                break
            if isinstance(msg, dict) and msg.get("__type") in {"heartbeat", "warning"}:
                continue
            readings.append(msg)

        assert len(readings) >= 3, (
            f"bridge subprocess delivered only {len(readings)} readings in 2s; "
            "expected ≥ 3 (connect-before-subscribe regression?)"
        )
        assert all(r.get("instrument_id") == "mock_instrument" for r in readings)
        assert all(r.get("unit") == "K" for r in readings)
    finally:
        shutdown.set()
        stop_pub.set()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)
        pub_thread.join(timeout=2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
