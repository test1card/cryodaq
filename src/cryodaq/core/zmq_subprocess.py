"""ZMQ bridge running in a separate process.

This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
assertion on Windows), only this subprocess dies. The GUI detects
the death via is_alive() and restarts it.

The GUI process never imports zmq.
"""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import queue
import time
from typing import Any

logger = logging.getLogger(__name__)

# Re-export constants so GUI code doesn't need to import zmq_bridge
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"


def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue)."""
    import msgpack

    data = msgpack.unpackb(payload, raw=False)
    return {
        "timestamp": data["ts"],
        "instrument_id": data.get("iid", ""),
        "channel": data["ch"],
        "value": data["v"],
        "unit": data["u"],
        "status": data["st"],
        "raw": data.get("raw"),
        "metadata": data.get("meta", {}),
    }


def zmq_bridge_main(
    pub_addr: str,
    cmd_addr: str,
    data_queue: mp.Queue,
    cmd_queue: mp.Queue,
    reply_queue: mp.Queue,
    shutdown_event: mp.Event,
) -> None:
    """Entry point for ZMQ bridge subprocess.

    Parameters
    ----------
    pub_addr:
        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    cmd_addr:
        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    data_queue:
        Subprocess → GUI: Reading dicts.
    cmd_queue:
        GUI → subprocess: command dicts to send via REQ.
    reply_queue:
        Subprocess → GUI: command reply dicts.
    shutdown_event:
        Set by GUI to signal clean shutdown.
    """
    import zmq

    ctx = zmq.Context()

    # SUB socket — receive data from engine
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.RCVTIMEO, 100)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    sub.connect(pub_addr)

    # REQ socket — send commands to engine
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 3000)
    req.setsockopt(zmq.SNDTIMEO, 3000)
    req.setsockopt(zmq.REQ_RELAXED, 1)
    req.setsockopt(zmq.REQ_CORRELATE, 1)
    req.connect(cmd_addr)

    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold
    last_heartbeat = time.monotonic()
    dropped_count = 0

    try:
        while not shutdown_event.is_set():
            # 1. Receive data from engine PUB
            try:
                parts = sub.recv_multipart(zmq.NOBLOCK)
                if len(parts) == 2:
                    try:
                        reading_dict = _unpack_reading_dict(parts[1])
                        data_queue.put_nowait(reading_dict)
                    except queue.Full:
                        dropped_count += 1
                        if dropped_count % 100 == 1:
                            try:
                                data_queue.put_nowait({
                                    "__type": "warning",
                                    "message": f"Queue overflow: {dropped_count} readings dropped",
                                })
                            except queue.Full:
                                pass
                    except Exception:
                        pass  # skip malformed
            except zmq.Again:
                pass

            # 2. Forward commands from GUI to engine
            try:
                cmd = cmd_queue.get_nowait()
                rid = cmd.pop("_rid", None)
                try:
                    req.send_string(json.dumps(cmd))
                    reply_raw = req.recv_string()
                    reply = json.loads(reply_raw)
                except zmq.ZMQError:
                    reply = {"ok": False, "error": "Engine не отвечает (таймаут)"}
                except Exception as exc:
                    reply = {"ok": False, "error": str(exc)}
                if rid is not None:
                    reply["_rid"] = rid
                try:
                    reply_queue.put(reply, timeout=2.0)
                except queue.Full:
                    # Log via data_queue warning so health monitoring sees it
                    try:
                        data_queue.put_nowait({"__type": "warning", "message": "Reply queue overflow"})
                    except queue.Full:
                        pass
            except queue.Empty:
                pass

            # 3. Heartbeat — prove subprocess is alive and not hung
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                try:
                    data_queue.put_nowait({"__type": "heartbeat", "ts": now})
                except queue.Full:
                    pass
                last_heartbeat = now

            time.sleep(0.005)  # 5ms poll — low CPU, ~200 Hz throughput

    except KeyboardInterrupt:
        pass
    finally:
        sub.close(linger=0)
        req.close(linger=0)
        ctx.term()
