"""ZMQ bridge running in a separate process.

This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
assertion on Windows), only this subprocess dies. The GUI detects
the death via is_alive() and restarts it.

The GUI process never imports zmq.

Threading model (see fix(gui): split bridge subprocess ...):
- sub_drain owns the SUB socket, receives readings, emits heartbeats.
  Heartbeat comes from this thread so it proves the *data* path is alive.
- cmd_forward owns the REQ socket, sends commands and waits up to 3s
  per reply. May block; does not affect sub_drain.
- Main thread starts both threads and waits on shutdown_event.
"""

from __future__ import annotations

import contextlib
import json
import logging
import multiprocessing as mp
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Re-export constants so GUI code doesn't need to import zmq_bridge
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
# module is loaded in the GUI process, which must not import zmq/zmq_bridge
# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
DEFAULT_TOPIC = b"readings"


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
        Subprocess → GUI: Reading dicts plus control messages
        (``__type`` in {"heartbeat", "warning"}).
    cmd_queue:
        GUI → subprocess: command dicts to send via REQ.
    reply_queue:
        Subprocess → GUI: command reply dicts.
    shutdown_event:
        Set by GUI to signal clean shutdown.
    """
    import zmq

    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold

    ctx = zmq.Context()

    dropped_counter = {"n": 0}

    def sub_drain_loop() -> None:
        """Own SUB socket; drain readings and emit periodic heartbeats.

        Heartbeat comes from this thread (not the command thread) so
        the GUI's heartbeat freshness check proves the *data* path is
        alive, not just that the subprocess exists.
        """
        # Order matters: connect() BEFORE subscribe(). The inverse pattern
        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
        # zero received messages on macOS Python 3.14 pyzmq 25+.
        sub = ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.RCVTIMEO, 100)
        # 2026-04-20 idle-death fix: same keepalive as REQ side to
        # survive macOS kernel idle reaping. SUB normally gets a
        # stream of readings so idle is rare, but between-experiment
        # quiet periods exist (scheduler paused, no active polls).
        sub.setsockopt(zmq.TCP_KEEPALIVE, 1)
        sub.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
        sub.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
        sub.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
        sub.connect(pub_addr)
        sub.subscribe(DEFAULT_TOPIC)
        last_heartbeat = time.monotonic()
        try:
            while not shutdown_event.is_set():
                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
                # responsive for shutdown and heartbeat emission.
                try:
                    parts = sub.recv_multipart()
                    if len(parts) == 2:
                        try:
                            reading_dict = _unpack_reading_dict(parts[1])
                        except Exception:
                            reading_dict = None  # skip malformed
                        if reading_dict is not None:
                            try:
                                data_queue.put_nowait(reading_dict)
                            except queue.Full:
                                dropped_counter["n"] += 1
                                if dropped_counter["n"] % 100 == 1:
                                    with contextlib.suppress(queue.Full):
                                        data_queue.put_nowait(
                                            {
                                                "__type": "warning",
                                                "message": (
                                                    f"Queue overflow: "
                                                    f"{dropped_counter['n']} readings dropped"
                                                ),
                                            }
                                        )
                except zmq.Again:
                    pass
                except zmq.ZMQError:
                    if shutdown_event.is_set():
                        break
                    # Unexpected socket error — swallow and continue.
                    time.sleep(0.01)

                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    with contextlib.suppress(queue.Full):
                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
                    last_heartbeat = now
        finally:
            sub.close(linger=0)

    def cmd_forward_loop() -> None:
        """Forward GUI commands via a fresh REQ socket per command.

        IV.6 B1 fix: each command creates, uses, and closes its own REQ
        socket. Shared long-lived REQ accumulated state across commands
        and became permanently unrecoverable after a platform-specific
        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
        ch.4 canonical "poll / timeout / close / reopen" reliable
        request-reply pattern.

        May block up to 35 s per timed-out REQ. That does not starve
        the data path because SUB drain runs on a separate thread.
        A timed-out REQ emits a structured ``cmd_timeout`` control
        message via data_queue so the launcher watchdog can detect
        command-channel-only failures and restart the bridge.
        """

        def _new_req_socket():
            """Build a fresh per-command REQ socket.

            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
            useful for stateful recovery on a shared socket, which the
            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
            the command path (reverting the f5f9039 partial fix) —
            Codex revised analysis confirmed idle-reap was not the
            actual cause; keepalive is a no-op here and clutters
            debugging of the real socket state.
            """
            req = ctx.socket(zmq.REQ)
            req.setsockopt(zmq.LINGER, 0)
            # IV.3 Finding 7: REQ timeout stays at 35 s so a slow
            # server-side handler (experiment_finalize / report
            # generation, tiered at 30 s) has room to reply before
            # the REQ side gives up. Server's 30 s ceiling + 5 s slack
            # stays inside the client's 35 s future wait
            # (_CMD_REPLY_TIMEOUT_S), so timeouts at each layer fire
            # in predictable order: server → subprocess → GUI future.
            req.setsockopt(zmq.RCVTIMEO, 35000)
            req.setsockopt(zmq.SNDTIMEO, 35000)
            req.connect(cmd_addr)
            return req

        while not shutdown_event.is_set():
            try:
                cmd = cmd_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
            cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"

            # Fresh socket per command — no shared state across commands.
            req = _new_req_socket()
            try:
                try:
                    req.send_string(json.dumps(cmd))
                    reply_raw = req.recv_string()
                    reply = json.loads(reply_raw)
                except zmq.ZMQError as exc:
                    reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
                    with contextlib.suppress(queue.Full):
                        data_queue.put_nowait(
                            {
                                "__type": "cmd_timeout",
                                "cmd": cmd_type,
                                "ts": time.monotonic(),
                                "message": f"REP timeout on {cmd_type} ({exc})",
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    reply = {"ok": False, "error": str(exc)}
            finally:
                req.close(linger=0)

            if rid is not None:
                reply["_rid"] = rid
            try:
                reply_queue.put(reply, timeout=2.0)
            except queue.Full:
                with contextlib.suppress(queue.Full):
                    data_queue.put_nowait(
                        {"__type": "warning", "message": "Reply queue overflow"}
                    )

    sub_thread = threading.Thread(target=sub_drain_loop, name="zmq-sub-drain", daemon=True)
    cmd_thread = threading.Thread(target=cmd_forward_loop, name="zmq-cmd-forward", daemon=True)

    try:
        sub_thread.start()
        cmd_thread.start()
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_event.set()
        sub_thread.join(timeout=2.0)
        cmd_thread.join(timeout=4.0)
        if sub_thread.is_alive() or cmd_thread.is_alive():
            logger.warning("ZMQ bridge threads did not exit cleanly before context term")
        ctx.term()
