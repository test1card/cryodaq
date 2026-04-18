"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.

The GUI process never imports zmq. Communication with the subprocess
is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
on Windows), only the subprocess dies — GUI detects and restarts it.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QThread, Signal

from cryodaq.core.zmq_subprocess import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    zmq_bridge_main,
)
from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)

_CMD_REPLY_TIMEOUT_S = 5.0


def _reading_from_dict(d: dict[str, Any]) -> Reading:
    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    return Reading(
        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
        instrument_id=d.get("instrument_id", ""),
        channel=d["channel"],
        value=d["value"],
        unit=d["unit"],
        status=ChannelStatus(d["status"]),
        raw=d.get("raw"),
        metadata=d.get("metadata", {}),
    )


class ZmqBridge:
    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.

    Usage::

        bridge = ZmqBridge()
        bridge.start()
        # In QTimer tick:
        for reading in bridge.poll_readings():
            handle(reading)
        # Commands:
        reply = bridge.send_command({"cmd": "safety_status"})
        # Shutdown:
        bridge.shutdown()
    """

    def __init__(
        self,
        pub_addr: str = DEFAULT_PUB_ADDR,
        cmd_addr: str = DEFAULT_CMD_ADDR,
    ) -> None:
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._shutdown_event: mp.Event = mp.Event()
        self._process: mp.Process | None = None
        self._last_heartbeat: float = 0.0
        # Data-flow watchdog: timestamp of the most recently drained
        # actual reading (not heartbeat, not warning). Stays 0.0 until
        # the first reading arrives so startup and between-experiment
        # pauses don't trigger false-positive restarts.
        self._last_reading_time: float = 0.0
        # Future-per-request command routing
        self._pending: dict[str, Future] = {}
        self._pending_lock = threading.Lock()
        self._reply_stop = threading.Event()
        self._reply_consumer: threading.Thread | None = None

    def start(self) -> None:
        """Start the ZMQ bridge subprocess."""
        if self._process is not None and self._process.is_alive():
            return
        if self._reply_consumer is not None and self._reply_consumer.is_alive():
            self._reply_stop.set()
            self._reply_consumer.join(timeout=1.0)
            self._reply_consumer = None
        self._shutdown_event.clear()
        # Drain stale queues
        _drain(self._data_queue)
        _drain(self._cmd_queue)
        _drain(self._reply_queue)
        self._process = mp.Process(
            target=zmq_bridge_main,
            args=(
                self._pub_addr,
                self._cmd_addr,
                self._data_queue,
                self._cmd_queue,
                self._reply_queue,
                self._shutdown_event,
            ),
            daemon=True,
            name="zmq_bridge",
        )
        self._process.start()
        self._last_heartbeat = time.monotonic()
        self._last_reading_time = 0.0
        # Start dedicated reply consumer thread
        self._reply_stop.clear()
        self._reply_consumer = threading.Thread(
            target=self._consume_replies,
            daemon=True,
            name="zmq-reply-consumer",
        )
        self._reply_consumer.start()
        logger.info("ZMQ bridge subprocess started (PID=%d)", self._process.pid)

    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        return self._process is not None and self._process.is_alive()

    def poll_readings(self) -> list[Reading]:
        """Drain all available readings from the data queue. Non-blocking."""
        readings: list[Reading] = []
        while True:
            try:
                d = self._data_queue.get_nowait()
                # Handle internal control messages from subprocess
                msg_type = d.get("__type")
                if msg_type == "heartbeat":
                    self._last_heartbeat = time.monotonic()
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
                    continue
                self._last_reading_time = time.monotonic()
                readings.append(_reading_from_dict(d))
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning("poll_readings: error processing item: %s", exc)
                continue
        return readings

    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if the bridge heartbeat is older than ``timeout_s``."""
        return self._last_heartbeat != 0.0 and (
            time.monotonic() - self._last_heartbeat
        ) >= timeout_s

    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if readings previously flowed but are now stale."""
        return self._last_reading_time != 0.0 and (
            time.monotonic() - self._last_reading_time
        ) >= timeout_s

    def is_healthy(self) -> bool:
        """True if subprocess is alive and bridge heartbeats are fresh."""
        return self.is_alive() and not self.heartbeat_stale()

    def send_command(self, cmd: dict) -> dict:
        """Thread-safe command dispatch with Future-per-request correlation."""
        if not self.is_alive():
            return {"ok": False, "error": "ZMQ bridge subprocess not running"}

        rid = uuid.uuid4().hex[:8]
        cmd = {**cmd, "_rid": rid}
        future: Future = Future()

        with self._pending_lock:
            self._pending[rid] = future

        try:
            self._cmd_queue.put(cmd, timeout=2.0)
            return future.result(timeout=_CMD_REPLY_TIMEOUT_S)
        except Exception as exc:
            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _consume_replies(self) -> None:
        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
        while not self._reply_stop.is_set():
            try:
                reply = self._reply_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break

            try:
                if not isinstance(reply, dict):
                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
                    continue
                rid = reply.pop("_rid", None)
                if rid:
                    with self._pending_lock:
                        future = self._pending.get(rid)
                    if future and not future.done():
                        future.set_result(reply)
                        continue
                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
            except Exception:
                logger.exception("ZMQ reply consumer: error processing reply")

    def shutdown(self) -> None:
        """Signal subprocess to stop, cancel pending futures, wait for exit."""
        # Stop reply consumer thread
        self._reply_stop.set()
        with self._pending_lock:
            for rid, future in self._pending.items():
                if not future.done():
                    future.set_result({"ok": False, "error": "ZMQ bridge shutting down"})
            self._pending.clear()
        if self._reply_consumer is not None and self._reply_consumer.is_alive():
            self._reply_consumer.join(timeout=3.0)

        # Stop subprocess
        self._shutdown_event.set()
        if self._process is not None:
            self._process.join(timeout=3)
            if self._process.is_alive():
                logger.warning("ZMQ bridge subprocess did not exit, killing")
                self._process.kill()
                self._process.join(timeout=2)
            self._process = None
        logger.info("ZMQ bridge subprocess stopped")


def _drain(q: mp.Queue) -> None:
    """Drain a multiprocessing Queue, ignoring errors."""
    while True:
        try:
            q.get_nowait()
        except (queue.Empty, EOFError, OSError):
            break


# --- Backwards-compatible API used by keithley_panel and other GUI widgets ---

_bridge: ZmqBridge | None = None


def set_bridge(bridge: ZmqBridge) -> None:
    """Set the global bridge instance. Called once at GUI startup."""
    global _bridge
    _bridge = bridge


def send_command(cmd: dict) -> dict:
    """Send command via the global bridge (blocking). Used by GUI widgets."""
    if _bridge is None:
        return {"ok": False, "error": "ZMQ bridge not initialized"}
    return _bridge.send_command(cmd)


def shutdown() -> None:
    """Shutdown the global bridge."""
    if _bridge is not None:
        _bridge.shutdown()


class ZmqCommandWorker(QThread):
    """Background thread for non-blocking ZMQ commands (unchanged API)."""

    finished = Signal(dict)

    def __init__(self, cmd: dict, parent=None) -> None:
        super().__init__(parent)
        self._cmd = cmd

    def run(self) -> None:
        result = send_command(self._cmd)
        self.finished.emit(result)
