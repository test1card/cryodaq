"""Persistent ZMQ REQ client for GUI → engine commands."""

from __future__ import annotations

import json
import logging

import zmq
from PySide6.QtCore import QThread, Signal

from cryodaq.core.zmq_bridge import DEFAULT_CMD_ADDR

logger = logging.getLogger(__name__)

_TIMEOUT_MS = 2000

# Module-level persistent socket
_ctx: zmq.Context | None = None
_socket: zmq.Socket | None = None


def _get_socket(addr: str = DEFAULT_CMD_ADDR) -> zmq.Socket:
    global _ctx, _socket
    if _ctx is None:
        _ctx = zmq.Context.instance()
    if _socket is None or _socket.closed:
        _socket = _ctx.socket(zmq.REQ)
        _socket.setsockopt(zmq.RCVTIMEO, _TIMEOUT_MS)
        _socket.setsockopt(zmq.SNDTIMEO, _TIMEOUT_MS)
        _socket.setsockopt(zmq.LINGER, 0)
        _socket.connect(addr)
    return _socket


def send_command(cmd: dict) -> dict:
    """Отправить команду синхронно (вызывать из фонового потока)."""
    global _socket
    try:
        sock = _get_socket()
        sock.send(json.dumps(cmd).encode())
        return json.loads(sock.recv().decode())
    except zmq.ZMQError:
        # Сокет в плохом состоянии после таймаута — пересоздать
        if _socket:
            _socket.close()
            _socket = None
        return {"ok": False, "error": "Engine не отвечает (таймаут)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class ZmqCommandWorker(QThread):
    """Фоновый поток для неблокирующих ZMQ-команд."""

    finished = Signal(dict)

    def __init__(self, cmd: dict, parent=None) -> None:
        super().__init__(parent)
        self._cmd = cmd

    def run(self) -> None:
        result = send_command(self._cmd)
        self.finished.emit(result)
