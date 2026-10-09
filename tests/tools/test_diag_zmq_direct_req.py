"""Smoke tests for tools/diag_zmq_direct_req.py.

Tests cover import and argparse only — the live soak experiment is
run manually as part of D3 H5 investigation, not as a unit test.
"""

from __future__ import annotations

from tools import diag_zmq_direct_req


def test_imports_cleanly() -> None:
    assert hasattr(diag_zmq_direct_req, "main")
    assert hasattr(diag_zmq_direct_req, "parse_args")
    assert hasattr(diag_zmq_direct_req, "run")


def test_parse_args_defaults() -> None:
    args = diag_zmq_direct_req.parse_args([])
    assert args.transport == "tcp"
    assert args.addr is None
    assert args.duration == 180


def test_parse_args_transport_ipc() -> None:
    args = diag_zmq_direct_req.parse_args(["--transport", "ipc"])
    assert args.transport == "ipc"
    assert args.addr is None


def test_parse_args_duration_override() -> None:
    args = diag_zmq_direct_req.parse_args(["--duration", "60"])
    assert args.duration == 60


def test_parse_args_addr_override() -> None:
    args = diag_zmq_direct_req.parse_args(["--addr", "tcp://127.0.0.1:9999"])
    assert args.addr == "tcp://127.0.0.1:9999"


def test_addr_resolution_tcp_default() -> None:
    args = diag_zmq_direct_req.parse_args([])
    addr = args.addr if args.addr else (
        diag_zmq_direct_req._IPC_CMD_ADDR if args.transport == "ipc"
        else diag_zmq_direct_req._TCP_CMD_ADDR
    )
    assert addr == "tcp://127.0.0.1:5556"


def test_addr_resolution_ipc() -> None:
    args = diag_zmq_direct_req.parse_args(["--transport", "ipc"])
    addr = args.addr if args.addr else (
        diag_zmq_direct_req._IPC_CMD_ADDR if args.transport == "ipc"
        else diag_zmq_direct_req._TCP_CMD_ADDR
    )
    assert addr == "ipc:///tmp/cryodaq-cmd.sock"
