"""Behavioral tests for ZMQCommandServer supervision and timeout hardening."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from unittest.mock import AsyncMock, MagicMock

import pytest
import zmq
import zmq.asyncio

from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer


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


async def _send_raw(address: str, payload: bytes, *, timeout_s: float = 5.0) -> dict:
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, int(timeout_s * 1000))
    req.setsockopt(zmq.SNDTIMEO, int(timeout_s * 1000))
    req.connect(address)
    try:
        await req.send(payload)
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
        # Every REP reply carries the additive protocol version.
        assert reply == {"ok": True, "cmd": "ping", "proto": PROTOCOL_VERSION}
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
        assert slow_reply["proto"] == PROTOCOL_VERSION
        assert "handler timeout (2s)" in slow_reply["error"]
        assert "operation may still be running" in slow_reply["error"]
        assert fast_reply == {"ok": True, "cmd": "fast", "proto": PROTOCOL_VERSION}
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
        assert reply["proto"] == PROTOCOL_VERSION
        assert "log_get timeout (1.5s)" in caplog.text
        assert "handler timeout (2s)" not in caplog.text
    finally:
        await server.stop()


async def test_protocol_version_command_over_the_wire() -> None:
    """End-to-end: protocol_version answers even though the wired handler
    knows nothing about it (never routed to `handler`, unlike every other
    command)."""
    address = _free_tcp_address()
    calls: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        calls.append(str(cmd.get("cmd")))
        return {"ok": False, "error": "should never be reached for protocol_version"}

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "protocol_version"})
        assert reply["ok"] is True
        assert reply["proto"] == PROTOCOL_VERSION
        assert reply["server"] == "engine"
        assert isinstance(reply["app_version"], str)
        assert calls == [], "protocol_version must not reach the wired handler"
    finally:
        await server.stop()


async def test_malformed_json_reply_still_carries_proto() -> None:
    """The reply encoder covers every reply branch, not just the success path —
    a malformed-JSON reject must carry `proto` too."""
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        ctx = zmq.asyncio.Context()
        req = ctx.socket(zmq.REQ)
        req.setsockopt(zmq.LINGER, 0)
        req.setsockopt(zmq.RCVTIMEO, 5000)
        req.setsockopt(zmq.SNDTIMEO, 5000)
        req.connect(address)
        try:
            await req.send(b"not valid json")
            raw = await asyncio.wait_for(req.recv(), timeout=5.0)
            reply = json.loads(raw)
        finally:
            req.close(linger=0)
            ctx.term()

        assert reply == {"ok": False, "error": "invalid JSON", "proto": PROTOCOL_VERSION}
    finally:
        await server.stop()


@pytest.mark.parametrize("payload", [b'"string"', b"42", b"[1, 2]", b"null"])
async def test_valid_non_object_json_reply_still_carries_proto(payload: bytes) -> None:
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        reply = await _send_raw(address, payload)
        assert reply["ok"] is False
        assert "invalid payload" in reply["error"]
        assert reply["proto"] == PROTOCOL_VERSION
    finally:
        await server.stop()


async def test_no_handler_reply_still_carries_proto() -> None:
    address = _free_tcp_address()
    server = ZMQCommandServer(address=address, handler=None)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "status"})
        assert reply == {
            "ok": False,
            "error": "no handler",
            "proto": PROTOCOL_VERSION,
        }
    finally:
        await server.stop()


async def test_handler_exception_reply_still_carries_proto() -> None:
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("handler failed")

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "status"})
        assert reply == {
            "ok": False,
            "error": "handler failed",
            "proto": PROTOCOL_VERSION,
        }
    finally:
        await server.stop()


async def test_serialization_fallback_reply_carries_proto() -> None:
    """A non-JSON dictionary key takes the deterministic fallback reply path."""

    async def handler(cmd: dict[str, object]) -> dict[object, object]:
        return {("not", "json"): True}

    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(side_effect=[zmq.POLLIN, asyncio.CancelledError()])
    socket_mock.recv = AsyncMock(return_value=b'{"cmd": "status"}')
    socket_mock.send = AsyncMock()
    server = ZMQCommandServer(handler=handler)
    server._socket = socket_mock
    server._running = True

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    socket_mock.send.assert_awaited_once()
    reply = json.loads(socket_mock.send.await_args.args[0])
    assert reply == {
        "ok": False,
        "error": "serialization error",
        "proto": PROTOCOL_VERSION,
    }


async def test_handler_cancellation_best_effort_reply_carries_proto() -> None:
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(return_value=zmq.POLLIN)
    socket_mock.recv = AsyncMock(return_value=b'{"cmd": "status"}')
    socket_mock.send = AsyncMock()
    server = ZMQCommandServer(handler=None)
    server._socket = socket_mock
    server._running = True
    server._run_handler = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    socket_mock.send.assert_awaited_once()
    reply = json.loads(socket_mock.send.await_args.args[0])
    assert reply == {"ok": False, "error": "internal", "proto": PROTOCOL_VERSION}


async def test_send_cancellation_best_effort_reply_carries_proto() -> None:
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(return_value=zmq.POLLIN)
    socket_mock.recv = AsyncMock(return_value=b'{"cmd": "status"}')
    socket_mock.send = AsyncMock(side_effect=[asyncio.CancelledError(), None])
    server = ZMQCommandServer(handler=lambda cmd: {"ok": True})
    server._socket = socket_mock
    server._running = True

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    assert socket_mock.send.await_count == 2
    fallback = json.loads(socket_mock.send.await_args_list[1].args[0])
    assert fallback == {"ok": False, "error": "internal", "proto": PROTOCOL_VERSION}


def test_engine_commands_keep_inner_timeouts_wired() -> None:
    """Inner timeout constants must be present and positive; do NOT pin specific
    seconds (F-TimeoutRelax bumped them and this test should not block
    future tuning)."""
    import importlib

    engine_mod = importlib.import_module("cryodaq.engine")

    assert hasattr(engine_mod, "_LOG_GET_TIMEOUT_S"), (
        "engine._LOG_GET_TIMEOUT_S must exist — inner log_get timeout wiring removed?"
    )
    assert hasattr(engine_mod, "_EXPERIMENT_STATUS_TIMEOUT_S"), (
        "engine._EXPERIMENT_STATUS_TIMEOUT_S must exist — inner experiment_status timeout wiring removed?"
    )
    log_get_t = engine_mod._LOG_GET_TIMEOUT_S
    exp_status_t = engine_mod._EXPERIMENT_STATUS_TIMEOUT_S
    assert isinstance(log_get_t, (int, float)) and log_get_t > 0, (
        f"_LOG_GET_TIMEOUT_S must be a positive number, got {log_get_t!r}"
    )
    assert isinstance(exp_status_t, (int, float)) and exp_status_t > 0, (
        f"_EXPERIMENT_STATUS_TIMEOUT_S must be a positive number, got {exp_status_t!r}"
    )
