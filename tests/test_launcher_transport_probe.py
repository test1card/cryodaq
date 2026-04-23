from __future__ import annotations

import json
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq import launcher


def _short_socket_path(name: str) -> Path:
    root = Path("/tmp") if Path("/tmp").exists() else Path(tempfile.gettempdir())
    return root / f"cryodaq-{name}-{uuid.uuid4().hex}.sock"


def _unused_tcp_addr() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    host, port = probe.getsockname()
    probe.close()
    return f"tcp://{host}:{port}"


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="AF_UNIX unavailable")
def test_transport_endpoint_present_false_for_missing_ipc(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(launcher, "DEFAULT_PUB_ADDR", f"ipc://{tmp_path / 'pub.sock'}")
    monkeypatch.setattr(launcher, "DEFAULT_CMD_ADDR", f"ipc://{tmp_path / 'cmd.sock'}")

    assert launcher._transport_endpoint_present() is False


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="AF_UNIX unavailable")
def test_transport_endpoint_present_true_for_live_ipc_socket(
    monkeypatch,
) -> None:
    live_sock = _short_socket_path("launcher-pub")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(live_sock))
    server.listen(1)
    try:
        monkeypatch.setattr(launcher, "DEFAULT_PUB_ADDR", f"ipc://{live_sock}")
        monkeypatch.setattr(launcher, "DEFAULT_CMD_ADDR", f"ipc://{_short_socket_path('launcher-cmd')}")

        assert launcher._transport_endpoint_present() is True
    finally:
        server.close()
        if live_sock.exists():
            live_sock.unlink()


def test_transport_endpoint_present_true_for_live_tcp_socket(monkeypatch) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    try:
        monkeypatch.setattr(launcher, "DEFAULT_PUB_ADDR", _unused_tcp_addr())
        monkeypatch.setattr(launcher, "DEFAULT_CMD_ADDR", f"tcp://{host}:{port}")

        assert launcher._transport_endpoint_present() is True
    finally:
        server.close()


def test_ping_engine_uses_default_cmd_addr(monkeypatch) -> None:
    connected: list[str] = []
    sent: list[str] = []

    class _FakeSocket:
        def setsockopt(self, *_args) -> None:
            pass

        def connect(self, address: str) -> None:
            connected.append(address)

        def send_string(self, payload: str) -> None:
            sent.append(payload)

        def recv_string(self) -> str:
            return json.dumps({"ok": True})

        def close(self) -> None:
            pass

    class _FakeContext:
        def __init__(self) -> None:
            self.socket_instance = _FakeSocket()
            self.terminated = False

        def socket(self, _kind: int) -> _FakeSocket:
            return self.socket_instance

        def term(self) -> None:
            self.terminated = True

    fake_ctx = _FakeContext()
    fake_zmq = SimpleNamespace(
        Context=lambda: fake_ctx,
        REQ=1,
        RCVTIMEO=2,
        SNDTIMEO=3,
        LINGER=4,
    )

    monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
    monkeypatch.setattr(launcher, "DEFAULT_CMD_ADDR", "ipc:///tmp/cryodaq-test-cmd.sock")

    assert launcher._ping_engine() is True
    assert connected == ["ipc:///tmp/cryodaq-test-cmd.sock"]
    assert sent == [json.dumps({"cmd": "safety_status"})]
    assert fake_ctx.terminated is True
