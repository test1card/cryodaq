"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.

The GUI process never imports zmq. Communication with the subprocess
is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
on Windows), only the subprocess dies — GUI detects and restarts it.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import time
from datetime import datetime, timezone
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
        timestamp=datetime.fromtimestamp(d["timestamp"], tz=timezone.utc),
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

    def start(self) -> None:
        """Start the ZMQ bridge subprocess."""
        if self._process is not None and self._process.is_alive():
            return
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
                readings.append(_reading_from_dict(d))
            except (queue.Empty, EOFError):
                break
            except Exception:
                break
        return readings

    def is_healthy(self) -> bool:
        """True if subprocess is alive AND sending heartbeats."""
        if not self.is_alive():
            return False
        if self._last_heartbeat == 0.0:
            return True  # just started, give it time
        return time.monotonic() - self._last_heartbeat < 9.0  # 3 * HEARTBEAT_INTERVAL

    def send_command(self, cmd: dict) -> dict:
        """Send command to engine via subprocess. Blocks until reply (with timeout)."""
        if not self.is_alive():
            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
        # Drain stale replies
        _drain(self._reply_queue)
        try:
            self._cmd_queue.put_nowait(cmd)
        except queue.Full:
            return {"ok": False, "error": "Command queue full"}

        deadline = time.monotonic() + _CMD_REPLY_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                return self._reply_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except EOFError:
                return {"ok": False, "error": "ZMQ bridge subprocess died"}
        return {"ok": False, "error": "Engine не отвечает (таймаут)"}

    def shutdown(self) -> None:
        """Signal subprocess to stop and wait for it to exit."""
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
