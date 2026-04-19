"""Behavioral tests for ZMQCommandServer supervision and timeout hardening."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path

import zmq
import zmq.asyncio

from cryodaq.core.zmq_bridge import ZMQCommandServer


def _free_tcp_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()
    return f"tcp://{host}:{port}"


async def _send_command(
    address: str, payload: dict[str, object], *, timeout_s: float = 5.0
) -> dict:
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, int(timeout_s * 1000))
    req.setsockopt(zmq.SNDTIMEO, int(timeout_s * 1000))
    req.connect(address)
    try:
        await req.send(json.dumps(payload).encode())
        raw = await asyncio.wait_for(req.recv(), timeout=timeout_s)
        return json.loads(raw)
    finally:
        req.close(linger=0)
        ctx.term()


async def test_command_server_restarts_after_unexpected_task_error(caplog) -> None:
    caplog.set_level(logging.ERROR)
    address = _free_tcp_address()
    calls = 0

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "cmd": cmd["cmd"]}

    server = ZMQCommandServer(address=address, handler=handler)
    original_serve_loop = server._serve_loop

    async def flaky_serve_loop() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        await original_serve_loop()

    server._serve_loop = flaky_serve_loop  # type: ignore[method-assign]
    await server.start()
    try:
        deadline = asyncio.get_running_loop().time() + 2.0
        while calls < 2 and asyncio.get_running_loop().time() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.05)

        reply = await _send_command(address, {"cmd": "ping"})
        assert calls >= 2
        assert reply == {"ok": True, "cmd": "ping"}
        assert "serve loop crashed; restarting" in caplog.text
    finally:
        await server.stop()


async def test_command_server_times_out_slow_handler_and_keeps_serving(caplog) -> None:
    caplog.set_level(logging.ERROR)
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        if cmd["cmd"] == "slow":
            await asyncio.sleep(3.0)
            return {"ok": True, "cmd": "slow"}
        return {"ok": True, "cmd": cmd["cmd"]}

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=2.0)
    await server.start()
    try:
        slow_reply = await _send_command(address, {"cmd": "slow"})
        fast_reply = await _send_command(address, {"cmd": "fast"})

        # IV.3 F7: timeout reply now includes the _handler_timeout marker
        # and the "operation may still be running." suffix so callers
        # can distinguish envelope timeout from a handler-reported error.
        assert slow_reply["ok"] is False
        assert slow_reply.get("_handler_timeout") is True
        assert "handler timeout (2s)" in slow_reply["error"]
        assert "operation may still be running" in slow_reply["error"]
        assert fast_reply == {"ok": True, "cmd": "fast"}
        assert "action=slow" in caplog.text
    finally:
        await server.stop()


async def test_command_server_preserves_inner_timeout_message(caplog) -> None:
    """Inner TimeoutError messages from handler wrappers must reach the client."""
    caplog.set_level(logging.ERROR)
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        raise TimeoutError("log_get timeout (1.5s)")

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=2.0)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "log_get"})
        # IV.3 F7: inner-wrapper message still wins, but the reply now
        # also carries the _handler_timeout marker since this is still
        # a timeout path.
        assert reply["ok"] is False
        assert reply["error"] == "log_get timeout (1.5s)"
        assert reply.get("_handler_timeout") is True
        assert "log_get timeout (1.5s)" in caplog.text
        assert "handler timeout (2s)" not in caplog.text
    finally:
        await server.stop()


def test_engine_commands_keep_fast_inner_timeouts() -> None:
    engine_py = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "engine.py"
    source = engine_py.read_text(encoding="utf-8")

    assert "_LOG_GET_TIMEOUT_S = 1.5" in source
    assert "_EXPERIMENT_STATUS_TIMEOUT_S = 1.5" in source
    assert 'if action == "log_get":' in source
    assert 'if action == "experiment_status":' in source
    assert "await asyncio.wait_for(" in source
