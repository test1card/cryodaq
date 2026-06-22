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
    """main() with no args must call run(cmd_addr=TCP_DEFAULT, duration=180)."""
    from unittest.mock import patch

    with patch.object(diag_zmq_direct_req, "run", return_value=0) as mock_run:
        diag_zmq_direct_req.main([])

    mock_run.assert_called_once_with(
        cmd_addr=diag_zmq_direct_req._TCP_CMD_ADDR,
        duration=180,
    )
    assert diag_zmq_direct_req._TCP_CMD_ADDR == "tcp://127.0.0.1:5556"


def test_addr_resolution_ipc() -> None:
    """main() with --transport ipc must call run(cmd_addr=IPC_DEFAULT, duration=180)."""
    from unittest.mock import patch

    with patch.object(diag_zmq_direct_req, "run", return_value=0) as mock_run:
        diag_zmq_direct_req.main(["--transport", "ipc"])

    mock_run.assert_called_once_with(
        cmd_addr=diag_zmq_direct_req._IPC_CMD_ADDR,
        duration=180,
    )
    assert diag_zmq_direct_req._IPC_CMD_ADDR == "ipc:///tmp/cryodaq-cmd.sock"


def test_main_addr_override() -> None:
    """main() with --addr must pass the explicit address to run()."""
    from unittest.mock import patch

    custom_addr = "tcp://127.0.0.1:9999"
    with patch.object(diag_zmq_direct_req, "run", return_value=0) as mock_run:
        diag_zmq_direct_req.main(["--addr", custom_addr])

    mock_run.assert_called_once_with(cmd_addr=custom_addr, duration=180)


def test_main_duration_override() -> None:
    """main() with --duration must pass the overridden duration to run()."""
    from unittest.mock import patch

    with patch.object(diag_zmq_direct_req, "run", return_value=0) as mock_run:
        diag_zmq_direct_req.main(["--duration", "60"])

    mock_run.assert_called_once_with(
        cmd_addr=diag_zmq_direct_req._TCP_CMD_ADDR,
        duration=60,
    )
