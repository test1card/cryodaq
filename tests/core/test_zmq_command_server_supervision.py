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


async def _send_command(address: str, payload: dict[str, object], *, timeout_s: float = 5.0) -> dict:
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


def _assert_failure_envelope(
    reply: dict,
    *,
    error_code: str,
    delivery_state: str,
    commit_state: str,
    retry_safe: bool,
) -> None:
    assert reply["ok"] is False
    assert reply["error_code"] == error_code
    assert isinstance(reply["error"], str)
    assert reply["delivery_state"] == delivery_state
    assert reply["commit_state"] == commit_state
    assert reply["retry_safe"] is retry_safe
    assert reply["proto"] == PROTOCOL_VERSION


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
        assert "serve loop crashed; replacing socket" in caplog.text
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
        read_reply = await _send_command(address, {"cmd": "safety_status"})

        _assert_failure_envelope(
            slow_reply,
            error_code="command_handler_timeout",
            delivery_state="dispatched",
            commit_state="unknown",
            retry_safe=False,
        )
        assert slow_reply.get("_handler_timeout") is True
        assert slow_reply["error"] == "Command handler timed out; outcome may be unknown."
        assert read_reply == {"ok": True, "cmd": "safety_status", "proto": PROTOCOL_VERSION}
        assert "action=slow" in caplog.text
    finally:
        await server.stop()


async def test_command_server_preserves_inner_timeout_message(caplog) -> None:
    """Inner TimeoutError messages stay redacted from the public envelope."""
    caplog.set_level(logging.ERROR)
    address = _free_tcp_address()

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        raise TimeoutError("log_get timeout (1.5s)")

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=2.0)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "log_get"})
        _assert_failure_envelope(
            reply,
            error_code="command_handler_timeout",
            delivery_state="dispatched",
            commit_state="not_applicable",
            retry_safe=True,
        )
        assert reply["error"] == "Command handler timed out; outcome may be unknown."
        assert reply.get("_handler_timeout") is True
        assert "action=log_get" in caplog.text
        assert "exception=TimeoutError" not in caplog.text
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

        _assert_failure_envelope(
            reply,
            error_code="command_request_invalid",
            delivery_state="not_dispatched",
            commit_state="not_committed",
            retry_safe=True,
        )
        assert reply["error"] == "Command request is invalid."
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
        _assert_failure_envelope(
            reply,
            error_code="command_request_invalid",
            delivery_state="not_dispatched",
            commit_state="not_committed",
            retry_safe=True,
        )
        assert reply["error"] == "Command request is invalid."
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
        raise RuntimeError("SECRET internal handler details")

    server = ZMQCommandServer(address=address, handler=handler)
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "status"})
        _assert_failure_envelope(
            reply,
            error_code="command_handler_failed",
            delivery_state="dispatched",
            commit_state="unknown",
            retry_safe=False,
        )
        assert reply["error"] == "Command handler failed; outcome may be unknown."
        assert "SECRET internal handler details" not in reply["error"]
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
    _assert_failure_envelope(
        reply,
        error_code="command_reply_serialization_failed",
        delivery_state="dispatched",
        commit_state="unknown",
        retry_safe=False,
    )
    assert reply["error"] == "Command reply could not be serialized; outcome may be unknown."


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

    socket_mock.send.assert_not_awaited()


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

    socket_mock.send.assert_awaited_once()


async def test_timeout_quarantines_mutations_but_allows_read_and_global_off() -> None:
    address = _free_tcp_address()
    release = asyncio.Event()
    resisted_cancellation = asyncio.Event()
    calls: list[str] = []
    commits: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        action = str(cmd["cmd"])
        calls.append(action)
        if action == "experiment_start":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                resisted_cancellation.set()
                await release.wait()
            commits.append(action)
        return {"ok": True, "cmd": action}

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=0.02)
    await server.start()
    try:
        timed_out = await _send_command(address, {"cmd": "experiment_start"})
        _assert_failure_envelope(
            timed_out,
            error_code="command_handler_timeout",
            delivery_state="dispatched",
            commit_state="unknown",
            retry_safe=False,
        )
        await asyncio.wait_for(resisted_cancellation.wait(), timeout=1.0)

        read_reply = await _send_command(address, {"cmd": "safety_status"})
        assert read_reply == {"ok": True, "cmd": "safety_status", "proto": PROTOCOL_VERSION}

        quarantined = await _send_command(address, {"cmd": "experiment_stop"})
        _assert_failure_envelope(
            quarantined,
            error_code="command_authority_quarantined",
            delivery_state="not_dispatched",
            commit_state="not_committed",
            retry_safe=False,
        )
        channel_off = await _send_command(
            address,
            {"cmd": "keithley_emergency_off", "channel": "smua"},
        )
        assert channel_off["error_code"] == "command_authority_quarantined"

        global_off = await _send_command(address, {"cmd": "keithley_emergency_off"})
        assert global_off == {
            "ok": True,
            "cmd": "keithley_emergency_off",
            "proto": PROTOCOL_VERSION,
        }
        assert calls == ["experiment_start", "safety_status", "keithley_emergency_off"]

        release.set()
        for _ in range(100):
            if not server._has_uncertain_authority_owner():
                break
            await asyncio.sleep(0)
        assert commits == ["experiment_start"]

        admitted = await _send_command(address, {"cmd": "experiment_stop"})
        assert admitted == {"ok": True, "cmd": "experiment_stop", "proto": PROTOCOL_VERSION}
    finally:
        release.set()
        await server.stop()


async def test_stop_waits_for_cancellation_resistant_handler_without_late_commit() -> None:
    address = _free_tcp_address()
    release = asyncio.Event()
    cancellation_count = 0
    commits: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        nonlocal cancellation_count
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellation_count += 1
        commits.append(str(cmd["cmd"]))
        return {"ok": True}

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=0.02)
    await server.start()
    timed_out = await _send_command(address, {"cmd": "experiment_start"})
    assert timed_out["error_code"] == "command_handler_timeout"
    for _ in range(100):
        if cancellation_count:
            break
        await asyncio.sleep(0)
    assert cancellation_count == 1

    stop_task = asyncio.create_task(server.stop())
    for _ in range(100):
        if cancellation_count >= 2:
            break
        await asyncio.sleep(0)
    assert cancellation_count >= 2
    assert not stop_task.done()
    assert server._socket is not None
    assert server._ctx is not None
    assert commits == []

    release.set()
    await asyncio.wait_for(stop_task, timeout=1.0)
    assert commits == ["experiment_start"]
    assert server._handler_tasks == set()
    assert server._uncertain_authority_tasks == set()
    assert server._socket is None
    assert server._ctx is None
    await asyncio.sleep(0.02)
    assert commits == ["experiment_start"]


async def test_cancelled_handler_waiter_retains_uncertain_owner_until_settlement() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    resisted_cancellation = asyncio.Event()
    commits: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            resisted_cancellation.set()
            await release.wait()
        commits.append(str(cmd["cmd"]))
        return {"ok": True}

    server = ZMQCommandServer(handler=handler, handler_timeout_s=5.0)
    waiter = asyncio.create_task(server._run_handler({"cmd": "experiment_start"}))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.wait_for(resisted_cancellation.wait(), timeout=1.0)

    rejected = await server._run_handler({"cmd": "experiment_stop"})
    assert rejected["error_code"] == "command_authority_quarantined"
    release.set()
    for _ in range(100):
        if not server._has_uncertain_authority_owner():
            break
        await asyncio.sleep(0)
    assert commits == ["experiment_start"]
    assert server._handler_tasks == set()
    assert server._uncertain_authority_tasks == set()


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
