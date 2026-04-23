from __future__ import annotations

import socket
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from cryodaq.core import zmq_transport


def _short_socket_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / f"cryodaq-{name}-{uuid.uuid4().hex}.sock"


def test_default_addr_prefixes_match_platform() -> None:
    if sys.platform == "win32":
        assert zmq_transport.DEFAULT_PUB_ADDR.startswith("tcp://")
        assert zmq_transport.DEFAULT_CMD_ADDR.startswith("tcp://")
    else:
        assert zmq_transport.DEFAULT_PUB_ADDR.startswith("ipc://")
        assert zmq_transport.DEFAULT_CMD_ADDR.startswith("ipc://")


def test_pub_and_cmd_addrs_are_different() -> None:
    assert zmq_transport.DEFAULT_PUB_ADDR != zmq_transport.DEFAULT_CMD_ADDR


def test_tcp_host_port_parses_tcp_address() -> None:
    assert zmq_transport.tcp_host_port("tcp://127.0.0.1:5556") == ("127.0.0.1", 5556)


def test_tcp_host_port_returns_none_for_ipc() -> None:
    assert zmq_transport.tcp_host_port("ipc:///tmp/cryodaq-cmd.sock") is None


def test_prepare_ipc_path_unlinks_stale_socket_path() -> None:
    sock_path = _short_socket_path("stale")
    stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale_socket.bind(str(sock_path))
    stale_socket.close()
    try:
        zmq_transport.prepare_ipc_path(f"ipc://{sock_path}")
        assert sock_path.exists() is False
    finally:
        if sock_path.exists():
            sock_path.unlink()


def test_prepare_ipc_path_refuses_live_socket_path() -> None:
    sock_path = _short_socket_path("live")
    live_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    live_socket.bind(str(sock_path))
    live_socket.listen(1)
    try:
        with pytest.raises(FileExistsError, match="live IPC endpoint"):
            zmq_transport.prepare_ipc_path(f"ipc://{sock_path}")
        assert sock_path.exists()
    finally:
        live_socket.close()
        if sock_path.exists():
            sock_path.unlink()


def test_cleanup_ipc_path_suppresses_missing_file(tmp_path) -> None:
    zmq_transport.cleanup_ipc_path(f"ipc://{tmp_path / 'missing.sock'}")


def test_cleanup_ipc_path_unlinks_stale_socket_path() -> None:
    sock_path = _short_socket_path("cst")
    stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale_socket.bind(str(sock_path))
    stale_socket.close()
    try:
        zmq_transport.cleanup_ipc_path(f"ipc://{sock_path}")
        assert sock_path.exists() is False
    finally:
        if sock_path.exists():
            sock_path.unlink()


def test_cleanup_ipc_path_refuses_non_socket_file(tmp_path) -> None:
    file_path = tmp_path / "not-a-socket.sock"
    file_path.write_text("not a socket")

    with pytest.raises(FileExistsError, match="non-socket IPC path"):
        zmq_transport.cleanup_ipc_path(f"ipc://{file_path}")

    assert file_path.exists()
