"""Behavioral tests for ZMQCommandServer supervision and timeout hardening."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import os
import socket
import stat
import sys
import types
from dataclasses import MISSING, fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import zmq
import zmq.asyncio

from cryodaq.core.command_authority import (
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_PROTOCOL_MAJOR,
    CommandClass,
    classify_engine_command,
    is_exact_safe_direction_envelope,
    is_ordinary_command_endpoint_admitted,
)
from cryodaq.core.zmq_bridge import (
    HANDLER_TIMEOUT_SLOW_S,
    PROTOCOL_VERSION,
    CommandAuthorityRegistry,
    ZMQCommandIngressPair,
    ZMQCommandServer,
    _timeout_for,
)
from cryodaq.engine import (
    EngineCommandContext,
    _consume_child_ready_channel,
    _consume_engine_ready_nonce,
    _consume_engine_shutdown_authority,
    _emit_engine_ready_receipt,
    _engine_ready_receipt,
    _engine_ready_response,
    _handle_gui_command,
    _request_teardown_after_shutdown_receipt,
)


def _shutdown_context(*, off_result: dict[str, object]) -> EngineCommandContext:
    required: dict[str, object] = {}
    for item in fields(EngineCommandContext):
        if item.default is MISSING and item.default_factory is MISSING:
            required[item.name] = MagicMock(name=item.name)
    context = EngineCommandContext(**required)
    context.engine_instance_id = "a" * 32
    context.shutdown_capability = "b" * 64
    context.shutdown_event = asyncio.Event()
    context.safety_manager.emergency_off = AsyncMock(return_value=off_result)
    return context


def _launcher_shutdown_command(*, request_id: str = "c" * 32) -> dict[str, str]:
    return {
        "cmd": "launcher_shutdown",
        "engine_instance_id": "a" * 32,
        "request_id": request_id,
        "shutdown_capability": "b" * 64,
    }


def _verified_global_off_result(**fields: object) -> dict[str, object]:
    return {
        "ok": True,
        "active_channels": [],
        "off_evidence": {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": True,
        },
        **fields,
    }


def test_exact_startup_readiness_actions_are_observations_while_near_misses_fail_closed() -> None:
    """Only exact startup challenges may bypass mutation quarantine."""

    assert classify_engine_command("engine_ready") is CommandClass.READ
    assert classify_engine_command("replay_ready") is CommandClass.READ
    assert classify_engine_command("engine_ready ") is CommandClass.MUTATION
    assert classify_engine_command("replay_ready ") is CommandClass.MUTATION
    assert classify_engine_command("ENGINE_READY") is CommandClass.MUTATION
    assert classify_engine_command("REPLAY_READY") is CommandClass.MUTATION
    assert classify_engine_command(None) is CommandClass.MUTATION


async def test_freeze_admission_after_receive_prevents_cross_boundary_dispatch() -> None:
    handler = AsyncMock(return_value={"ok": True})
    server = ZMQCommandServer("inproc://freeze-boundary", handler=handler)

    class FreezeOnReceiveSocket:
        send_calls = 0

        async def poll(self, *, timeout: int) -> int:  # noqa: ASYNC109 - matches the ZMQ socket API
            assert timeout == 1000
            return zmq.POLLIN

        async def recv(self) -> bytes:
            server.freeze_admission()
            return json.dumps({"cmd": "experiment_abort", "experiment_id": "exp-1"}).encode("utf-8")

        async def send(self, _wire: bytes) -> None:
            self.send_calls += 1

    socket_owner = FreezeOnReceiveSocket()
    server._socket = socket_owner
    server._running = True
    server._shutdown_requested = False

    await server._serve_loop()

    handler.assert_not_awaited()
    assert socket_owner.send_calls == 0
    assert server._shutdown_requested is True
    assert server._running is False


def _ready_context() -> EngineCommandContext:
    context = _shutdown_context(off_result={"ok": True, "active_channels": []})
    context.engine_ready_nonce = "c" * 64
    context.engine_ready_pid = 7319
    context.engine_ready_advertised = True
    return context


def test_engine_ready_nonce_is_one_use_and_removed_before_child_spawn() -> None:
    environment = {
        "CRYODAQ_ENGINE_READY_NONCE": "c" * 64,
        "UNRELATED": "preserved",
    }

    assert _consume_engine_ready_nonce(environment) == "c" * 64
    assert environment == {"UNRELATED": "preserved"}


@pytest.mark.parametrize(
    "invalid_nonce",
    ["", "c" * 63, "c" * 65, "C" * 64, "g" * 64, True, 7, None],
)
def test_invalid_engine_ready_nonce_is_consumed_and_never_creates_authority(
    invalid_nonce: object,
) -> None:
    environment = {"CRYODAQ_ENGINE_READY_NONCE": invalid_nonce}

    with pytest.raises(RuntimeError, match="readiness nonce is invalid"):
        _consume_engine_ready_nonce(environment)
    assert "CRYODAQ_ENGINE_READY_NONCE" not in environment


def test_engine_ready_receipt_has_exact_identity_and_canonical_addresses() -> None:
    context = _ready_context()

    assert _engine_ready_receipt(context) == {
        "schema": "cryodaq.engine_ready.v2",
        "nonce": "c" * 64,
        "engine_instance_id": "a" * 32,
        "mode": "live",
        "pid": 7319,
        "pub_addr": "tcp://127.0.0.1:5555",
        "cmd_addr": "tcp://127.0.0.1:5556",
        "safe_cmd_addr": "tcp://127.0.0.1:5558",
    }

    context.engine_ready_pid = True
    assert _engine_ready_receipt(context) is None


def test_engine_ready_bare_discovery_discloses_nothing_but_full_challenge_returns_exact_receipt() -> None:
    context = _ready_context()
    receipt = _engine_ready_receipt(context)
    assert receipt is not None
    expected = {"ok": True, **receipt}

    assert _engine_ready_response({"cmd": "engine_ready"}, context) == {
        "ok": False,
        "error_code": "engine_ready_invalid",
    }
    assert (
        _engine_ready_response(
            {
                "cmd": "engine_ready",
                "nonce": receipt["nonce"],
                "engine_instance_id": receipt["engine_instance_id"],
                "pid": receipt["pid"],
                "pub_addr": receipt["pub_addr"],
                "cmd_addr": receipt["cmd_addr"],
                "safe_cmd_addr": receipt["safe_cmd_addr"],
            },
            context,
        )
        == expected
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"pid": True},
        {"pid": 7319, "extra": "accepted-by-loose-decoder"},
        {"pub_addr": "tcp://127.0.0.1:5555 "},
        {"safe_cmd_addr": "tcp://127.0.0.1:5558 "},
        {"cmd": "ENGINE_READY"},
    ],
)
def test_engine_ready_full_challenge_rejects_bool_pid_extra_keys_and_near_misses(
    mutation: dict[str, object],
) -> None:
    context = _ready_context()
    receipt = _engine_ready_receipt(context)
    assert receipt is not None
    command: dict[str, object] = {
        "cmd": "engine_ready",
        "nonce": receipt["nonce"],
        "engine_instance_id": receipt["engine_instance_id"],
        "pid": receipt["pid"],
        "pub_addr": receipt["pub_addr"],
        "cmd_addr": receipt["cmd_addr"],
        "safe_cmd_addr": receipt["safe_cmd_addr"],
    }
    command.update(mutation)

    response = _engine_ready_response(command, context)

    assert response["ok"] is False
    assert response["error_code"] in {"engine_ready_invalid", "engine_ready_mismatch"}


def test_engine_ready_full_challenge_requires_dedicated_safe_endpoint_identity() -> None:
    context = _ready_context()
    receipt = _engine_ready_receipt(context)
    assert receipt is not None
    command = {
        "cmd": "engine_ready",
        "nonce": receipt["nonce"],
        "engine_instance_id": receipt["engine_instance_id"],
        "pid": receipt["pid"],
        "pub_addr": receipt["pub_addr"],
        "cmd_addr": receipt["cmd_addr"],
    }

    assert _engine_ready_response(command, context) == {
        "ok": False,
        "error_code": "engine_ready_invalid",
    }


def test_engine_ready_private_pipe_frame_is_canonical_bounded_and_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _ready_context()
    context.engine_ready_advertised = False
    context.engine_ready_channel_fd = 17
    writes: list[bytes] = []
    closes: list[int] = []

    def partial_write(fd: int, payload: bytes) -> int:
        assert fd == 17
        count = min(11, len(payload))
        writes.append(payload[:count])
        return count

    monkeypatch.setattr(os, "write", partial_write)
    monkeypatch.setattr(os, "close", closes.append)

    _emit_engine_ready_receipt(context)

    wire = b"".join(writes)
    receipt = _engine_ready_receipt(context)
    assert receipt is not None
    expected_payload = json.dumps(
        receipt,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    assert wire == b"CRYODAQ_ENGINE_READY_V2 " + expected_payload + b"\n"
    assert b"\r" not in wire
    assert len(wire) <= 1024
    assert closes == [17]
    assert context.engine_ready_channel_fd is None
    assert context.engine_ready_advertised is True


def test_engine_ready_private_pipe_no_progress_fails_closed_but_still_closes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _ready_context()
    context.engine_ready_advertised = False
    context.engine_ready_channel_fd = 19
    closes: list[int] = []
    monkeypatch.setattr(os, "write", lambda _fd, _payload: 0)
    monkeypatch.setattr(os, "close", closes.append)

    with pytest.raises(OSError, match="made no progress"):
        _emit_engine_ready_receipt(context)

    assert closes == [19]
    assert context.engine_ready_channel_fd is None
    assert context.engine_ready_advertised is False


def test_engine_consumes_private_ready_channel_and_removes_descendant_inheritance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = 23
    environment = {"CRYODAQ_CHILD_READY_CHANNEL": f"fd:{descriptor}", "UNRELATED": "preserved"}
    set_inheritable = MagicMock()
    monkeypatch.setattr("cryodaq.engine.sys.platform", "linux")
    monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFIFO) if fd == descriptor else None)
    monkeypatch.setattr(os, "set_inheritable", set_inheritable)

    assert _consume_child_ready_channel(environment) == descriptor
    assert environment == {"UNRELATED": "preserved"}
    set_inheritable.assert_called_once_with(descriptor, False)


@pytest.mark.parametrize("encoded", ["", "fd:0", "fd:1", "fd:2", "fd:-1", "fd:3x", "handle:3"])
def test_engine_rejects_and_consumes_malformed_or_unsafe_ready_channels(
    monkeypatch: pytest.MonkeyPatch,
    encoded: str,
) -> None:
    environment = {"CRYODAQ_CHILD_READY_CHANNEL": encoded, "UNRELATED": "preserved"}
    monkeypatch.setattr("cryodaq.engine.sys.platform", "linux")

    with pytest.raises(RuntimeError, match="launcher readiness channel is invalid"):
        _consume_child_ready_channel(environment)

    assert environment == {"UNRELATED": "preserved"}


@pytest.mark.parametrize("descriptor", [0, 1, 2])
def test_engine_invalid_ready_channel_cannot_close_process_stdio(
    monkeypatch: pytest.MonkeyPatch,
    descriptor: int,
) -> None:
    before = os.fstat(descriptor)
    environment = {"CRYODAQ_CHILD_READY_CHANNEL": f"fd:{descriptor}"}
    monkeypatch.setattr("cryodaq.engine.sys.platform", "linux")

    with pytest.raises(RuntimeError, match="launcher readiness channel is invalid"):
        _consume_child_ready_channel(environment)

    assert os.path.samestat(before, os.fstat(descriptor))
    assert environment == {}


def test_engine_nonpipe_ready_channel_remains_open_after_rejection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "not-a-pipe"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    before = os.fstat(descriptor)
    environment = {"CRYODAQ_CHILD_READY_CHANNEL": f"fd:{descriptor}"}
    monkeypatch.setattr("cryodaq.engine.sys.platform", "linux")
    try:
        with pytest.raises(RuntimeError, match="launcher readiness channel is invalid"):
            _consume_child_ready_channel(environment)

        assert os.path.samestat(before, os.fstat(descriptor))
        assert environment == {}
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("descriptor", [0, 1, 2])
def test_engine_windows_ready_handle_rejects_standard_handles_before_conversion(
    monkeypatch: pytest.MonkeyPatch,
    descriptor: int,
) -> None:
    import cryodaq.engine as engine_module

    standard_handles = {index: 10_000 + index for index in range(3)}
    open_osfhandle = MagicMock()
    fake_msvcrt = SimpleNamespace(
        get_osfhandle=lambda fd: standard_handles[fd],
        open_osfhandle=open_osfhandle,
    )
    monkeypatch.setattr(engine_module.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    environment = {"CRYODAQ_CHILD_READY_CHANNEL": f"handle:{standard_handles[descriptor]}"}

    with pytest.raises(RuntimeError, match="launcher readiness channel is invalid"):
        engine_module._consume_child_ready_channel(environment)

    open_osfhandle.assert_not_called()
    assert environment == {}


def test_launcher_shutdown_uses_hardware_safe_command_timeout() -> None:
    assert _timeout_for(_launcher_shutdown_command()) == HANDLER_TIMEOUT_SLOW_S


def test_engine_consumes_shutdown_authority_before_descendant_environment_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance_id = "a" * 32
    capability = "b" * 64
    monkeypatch.setenv("CRYODAQ_ENGINE_INSTANCE_ID", instance_id)
    monkeypatch.setenv("CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY", capability)

    consumed_instance, consumed_capability = _consume_engine_shutdown_authority()
    child_environment = os.environ.copy()
    context = _shutdown_context(off_result={"ok": True, "active_channels": []})
    context.engine_instance_id = consumed_instance
    context.shutdown_capability = consumed_capability

    assert (context.engine_instance_id, context.shutdown_capability) == (instance_id, capability)
    assert "CRYODAQ_ENGINE_INSTANCE_ID" not in child_environment
    assert "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY" not in child_environment
    assert instance_id not in child_environment.values()
    assert capability not in child_environment.values()


def test_engine_main_consumes_authority_before_force_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launch authority must leave the environment before --force snapshots it
    for engine-owned children, and the launcher-owned POSIX fd-2 bootstrap must
    sit between that consumption and logging init. The bootstrap itself is only
    observed here (stubbed module recording its invocation) so the recorded
    startup sequence proves the ordering on every host without installing
    isolation into the pytest process; the real installer stays covered by the
    subprocess guards in tests/integration/test_launcher_fd2_shutdown_blocker.py."""
    import cryodaq.engine as engine_module
    import cryodaq.logging_setup as logging_setup

    instance_id = "a" * 32
    capability = "b" * 64
    ready_nonce = "c" * 64
    force_environments: list[dict[str, str]] = []
    force_channel_inheritable: list[bool] = []
    run_arguments: list[tuple[bool, str, str, str, int]] = []
    startup_events: list[str] = []
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setenv("CRYODAQ_ENGINE_INSTANCE_ID", instance_id)
    monkeypatch.setenv("CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY", capability)
    monkeypatch.setenv("CRYODAQ_ENGINE_READY_NONCE", ready_nonce)
    monkeypatch.setenv("CRYODAQ_CHILD_READY_CHANNEL", f"fd:{write_fd}")
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(mock=True, mock_thermal_simulator=None, force=True),
    )

    def observe_setup_logging(*_args: object, **_kwargs: object) -> None:
        startup_events.append("setup_logging")

    monkeypatch.setattr(logging_setup, "setup_logging", observe_setup_logging)
    monkeypatch.setattr(logging_setup, "resolve_log_level", lambda: logging.INFO)

    def observe_force_environment() -> None:
        force_environments.append(os.environ.copy())
        force_channel_inheritable.append(os.get_inheritable(write_fd))
        startup_events.append("force_environment_snapshot")

    fd2_bootstrap_stub = types.ModuleType("cryodaq._fd2_bootstrap")

    def record_fd2_bootstrap_installation() -> None:
        startup_events.append("fd2_bootstrap_installed")

    fd2_bootstrap_stub.isolate_launcher_stderr_fd2 = record_fd2_bootstrap_installation
    monkeypatch.setitem(sys.modules, "cryodaq._fd2_bootstrap", fd2_bootstrap_stub)

    monkeypatch.setattr(engine_module, "_force_kill_existing", observe_force_environment)
    monkeypatch.setattr(engine_module, "_acquire_engine_lock", lambda: 17)
    monkeypatch.setattr(engine_module, "_release_engine_lock", lambda _fd: None)
    # The gate decision must stay host-independent here: with a complete
    # envelope on a POSIX-marked platform it authorizes isolation before any
    # descendant can spawn, exactly as the launcher-owned child runs.
    monkeypatch.setattr(engine_module.sys, "platform", "linux")

    async def fake_run_engine(
        *,
        mock: bool,
        engine_instance_id: str,
        shutdown_capability: str,
        engine_ready_nonce: str,
        engine_ready_channel_fd: int,
        mock_instrument_client: object | None = None,
    ) -> None:
        assert mock_instrument_client is None
        assert engine_ready_channel_fd == write_fd
        assert os.get_inheritable(engine_ready_channel_fd) is False
        run_arguments.append(
            (mock, engine_instance_id, shutdown_capability, engine_ready_nonce, engine_ready_channel_fd)
        )
        startup_events.append("engine_run")
        os.close(engine_ready_channel_fd)

    monkeypatch.setattr(engine_module, "_run_engine", fake_run_engine)

    try:
        engine_module.main()
    finally:
        os.close(read_fd)

    assert run_arguments == [(True, instance_id, capability, ready_nonce, write_fd)]
    assert startup_events == [
        "fd2_bootstrap_installed",
        "setup_logging",
        "force_environment_snapshot",
        "engine_run",
    ]
    assert len(force_environments) == 1
    assert force_channel_inheritable == [False]
    force_environment = force_environments[0]
    assert "CRYODAQ_ENGINE_INSTANCE_ID" not in force_environment
    assert "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY" not in force_environment
    assert "CRYODAQ_ENGINE_READY_NONCE" not in force_environment
    assert "CRYODAQ_CHILD_READY_CHANNEL" not in force_environment
    assert instance_id not in force_environment.values()
    assert capability not in force_environment.values()
    assert ready_nonce not in force_environment.values()


def test_engine_main_installs_launcher_fd2_isolation_before_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered fd-2 guard invokes the production ``engine.main()`` wiring."""
    import cryodaq.engine as engine_module
    import cryodaq.logging_setup as logging_setup

    startup_events: list[str] = []
    monkeypatch.setattr(engine_module.sys, "platform", "linux")
    monkeypatch.setattr(
        engine_module,
        "_consume_engine_launch_authority",
        lambda: ("a" * 32, "b" * 64, "c" * 64, 17),
    )
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(mock=True, mock_thermal_simulator=None, force=False),
    )

    fd2_bootstrap_stub = types.ModuleType("cryodaq._fd2_bootstrap")
    fd2_bootstrap_stub.isolate_launcher_stderr_fd2 = lambda: startup_events.append("fd2_bootstrap_installed")
    monkeypatch.setitem(sys.modules, "cryodaq._fd2_bootstrap", fd2_bootstrap_stub)
    monkeypatch.setattr(
        logging_setup,
        "setup_logging",
        lambda *_args, **_kwargs: startup_events.append("setup_logging"),
    )
    monkeypatch.setattr(logging_setup, "resolve_log_level", lambda: logging.INFO)
    monkeypatch.setattr(engine_module, "_acquire_engine_lock", lambda: 19)
    monkeypatch.setattr(engine_module, "_release_engine_lock", lambda _fd: None)

    async def observe_engine_run(**_kwargs: object) -> None:
        startup_events.append("engine_run")

    monkeypatch.setattr(engine_module, "_run_engine", observe_engine_run)

    engine_module.main()

    assert startup_events == ["fd2_bootstrap_installed", "setup_logging", "engine_run"]


@pytest.mark.parametrize(
    ("instance_id", "capability"),
    [
        ("", "b" * 64),
        ("a" * 32, ""),
        ("g" * 32, "b" * 64),
        ("a" * 32, "z" * 64),
    ],
)
def test_malformed_or_incomplete_shutdown_environment_never_creates_authority(
    instance_id: str,
    capability: str,
) -> None:
    environment = {
        "CRYODAQ_ENGINE_INSTANCE_ID": instance_id,
        "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY": capability,
    }

    with pytest.raises(RuntimeError, match="shutdown authority is invalid"):
        _consume_engine_shutdown_authority(environment)
    assert "CRYODAQ_ENGINE_INSTANCE_ID" not in environment
    assert "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY" not in environment


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
        assert server.terminal_failure is None
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_command_server_exhausted_recovery_latches_sanitized_one_shot_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    secret = "do-not-leak-recovery-token"
    server = ZMQCommandServer()
    notifications = []
    server.bind_terminal_failure_notifier(notifications.append)
    server._running = True

    async def fail_recovery():
        raise RuntimeError(secret)

    monkeypatch.setattr(server, "_open_bound_socket", fail_recovery)

    await server._restart_after_unexpected_exit()
    failure = await server.wait_terminal_failure()

    assert failure.stage == "recovery_exhausted"
    assert failure.failure_type == "RuntimeError"
    assert notifications == [failure]
    assert server._running is False
    assert server._shutdown_requested is True
    assert secret not in repr(failure)
    assert secret not in caplog.text

    server._latch_terminal_failure(stage="loop_closed", failure_type="OSError")
    assert server.terminal_failure is failure
    assert notifications == [failure]
    server._start_serve_task()
    assert server._task is None


@pytest.mark.parametrize(
    ("loop_factory", "expected_stage", "expected_type"),
    [
        pytest.param(
            lambda _secret: SimpleNamespace(is_closed=lambda: True),
            "loop_closed",
            "RuntimeError",
            id="closed-loop",
        ),
        pytest.param(
            lambda secret: SimpleNamespace(
                is_closed=lambda: False,
                create_task=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(secret)),
            ),
            "recovery_task_create_failed",
            "OSError",
            id="recovery-task-create-failure",
        ),
    ],
)
@pytest.mark.asyncio
async def test_command_server_recovery_scheduling_failure_is_terminal_and_sanitized(
    loop_factory,
    expected_stage: str,
    expected_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    secret = "do-not-leak-scheduler-token"
    loop = loop_factory(secret)

    class FailedTask:
        def exception(self):
            return RuntimeError(secret)

        def get_loop(self):
            return loop

    task = FailedTask()
    server = ZMQCommandServer()
    server._running = True
    server._task = task  # type: ignore[assignment]

    server._on_serve_task_done(task)  # type: ignore[arg-type]
    failure = await server.wait_terminal_failure()

    assert failure.stage == expected_stage
    assert failure.failure_type == expected_type
    assert server._running is False
    assert server._shutdown_requested is True
    assert secret not in repr(failure)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_command_server_replacement_serve_task_creation_failure_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    secret = "do-not-leak-replacement-task-token"
    replacement = MagicMock()
    server = ZMQCommandServer()
    server._running = True

    async def open_replacement():
        server._socket = replacement
        return replacement

    def fail_create() -> None:
        raise OSError(secret)

    monkeypatch.setattr(server, "_open_bound_socket", open_replacement)
    monkeypatch.setattr(server, "_start_serve_task", fail_create)

    await server._restart_after_unexpected_exit()
    failure = await server.wait_terminal_failure()

    assert failure.stage == "recovery_task_create_failed"
    assert failure.failure_type == "OSError"
    assert server._socket is replacement
    assert server._running is False
    assert secret not in repr(failure)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_command_server_clean_stop_never_signals_terminal_failure() -> None:
    server = ZMQCommandServer(address=_free_tcp_address())
    await server.start()
    waiter = asyncio.create_task(server.wait_terminal_failure())

    await server.stop()
    await asyncio.sleep(0)

    assert server.terminal_failure is None
    assert waiter.done() is False
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter


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


async def test_non_object_json_is_rejected_without_poisoning_rep_or_callback() -> None:
    address = _free_tcp_address()
    handled: list[dict[str, object]] = []
    callbacks: list[tuple[dict[str, object], dict[str, object]]] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        handled.append(cmd)
        return {"ok": True, "status": "usable"}

    def reply_sent(cmd: dict[str, object], reply: dict[str, object]) -> None:
        callbacks.append((cmd, reply))

    server = ZMQCommandServer(
        address=address,
        handler=handler,
        reply_sent_callback=reply_sent,
    )
    await server.start()
    try:
        for payload in (b"42", b"[]"):
            rejected = await _send_raw(address, payload)
            _assert_failure_envelope(
                rejected,
                error_code="command_request_invalid",
                delivery_state="not_dispatched",
                commit_state="not_committed",
                retry_safe=True,
            )

        valid = {"cmd": "safety_status"}
        assert await _send_command(address, valid) == {
            "ok": True,
            "status": "usable",
            "proto": 2,
        }
        assert handled == [valid]
        assert callbacks == [(valid, {"ok": True, "status": "usable", "proto": 2})]
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
    mutation_started = asyncio.Event()
    calls: list[str] = []
    commits: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        action = str(cmd["cmd"])
        calls.append(action)
        if action == "experiment_start":
            mutation_started.set()
            await release.wait()
            commits.append(action)
            return {
                "ok": True,
                "cmd": action,
                "delivery_state": "dispatched",
                "commit_state": "committed",
            }
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
        await asyncio.wait_for(mutation_started.wait(), timeout=1.0)

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
        malformed_shutdown = await _send_command(
            address,
            {"cmd": "launcher_shutdown", "engine_instance_id": "a" * 32, "request_id": "c" * 32},
        )
        assert malformed_shutdown["error_code"] == "command_authority_quarantined"
        shutdown_reply = await _send_command(address, _launcher_shutdown_command())
        assert shutdown_reply == {"ok": True, "cmd": "launcher_shutdown", "proto": PROTOCOL_VERSION}
        assert calls == ["experiment_start", "safety_status", "keithley_emergency_off", "launcher_shutdown"]

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


async def test_dedicated_safe_server_dispatches_targeted_off_while_ordinary_rep_is_blocked() -> None:
    ordinary_address = _free_tcp_address()
    safe_address = _free_tcp_address()
    registry = CommandAuthorityRegistry()
    ordinary_entered = asyncio.Event()
    ordinary_release = asyncio.Event()
    calls: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        action = str(cmd["cmd"])
        calls.append(action)
        if action == "experiment_start":
            ordinary_entered.set()
            await ordinary_release.wait()
        return {"ok": True, "cmd": action}

    ordinary = ZMQCommandServer(
        address=ordinary_address,
        handler=handler,
        handler_timeout_s=5.0,
        authority_registry=registry,
        accepted_command_predicate=is_ordinary_command_endpoint_admitted,
    )
    safe = ZMQCommandServer(
        address=safe_address,
        handler=handler,
        handler_timeout_s=5.0,
        authority_registry=registry,
        accepted_actions=frozenset({"keithley_emergency_off", "launcher_shutdown"}),
        accepted_command_predicate=is_exact_safe_direction_envelope,
    )
    await ordinary.start()
    await safe.start()
    try:
        ordinary_task = asyncio.create_task(_send_command(ordinary_address, {"cmd": "experiment_start"}))
        await asyncio.wait_for(ordinary_entered.wait(), timeout=1.0)
        targeted = await asyncio.wait_for(
            _send_command(
                safe_address,
                {"cmd": "keithley_emergency_off", "channel": "smua"},
            ),
            timeout=1.0,
        )
        assert targeted == {
            "ok": True,
            "cmd": "keithley_emergency_off",
            "proto": PROTOCOL_VERSION,
        }
        assert ordinary_task.done() is False
        ordinary_release.set()
        assert await asyncio.wait_for(ordinary_task, timeout=1.0) == {
            "ok": True,
            "cmd": "experiment_start",
            "proto": PROTOCOL_VERSION,
        }
        assert calls == ["experiment_start", "keithley_emergency_off"]
    finally:
        ordinary_release.set()
        await asyncio.gather(ordinary.stop(), safe.stop())


async def test_ordinary_server_rejects_every_safe_action_shape_before_handler_dispatch() -> None:
    address = _free_tcp_address()
    calls: list[dict[str, object]] = []

    async def handler(command: dict[str, object]) -> dict[str, object]:
        calls.append(dict(command))
        return {"ok": True}

    server = ZMQCommandServer(
        address,
        handler=handler,
        accepted_command_predicate=is_ordinary_command_endpoint_admitted,
    )
    await server.start()
    try:
        commands = (
            {"cmd": "keithley_emergency_off"},
            {"cmd": "keithley_emergency_off", "channel": "smua"},
            {"cmd": "keithley_emergency_off", "unexpected": True},
            _launcher_shutdown_command(),
            {**_launcher_shutdown_command(), "unexpected": True},
        )
        for command in commands:
            reply = await _send_command(address, command)
            assert reply["error_code"] == "command_endpoint_action_rejected"
            assert reply["delivery_state"] == "not_dispatched"
        assert calls == []
    finally:
        await server.stop()


async def test_live_composition_root_executes_dual_ingress_lane_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The actual live root must bind safe actions only to its preemptive lane."""

    import cryodaq.engine as engine_module

    class _StopAtCommandIngress(RuntimeError):
        pass

    captured: dict[str, object] = {}
    tasks_before = set(asyncio.all_tasks())
    config_dir = engine_module._CONFIG_DIR

    def capture_ingress_pair(*, ordinary: object, safe: object) -> ZMQCommandIngressPair:
        pair = ZMQCommandIngressPair(ordinary=ordinary, safe=safe)
        captured.update(ordinary=ordinary, safe=safe, pair=pair)
        raise _StopAtCommandIngress

    monkeypatch.setattr(engine_module, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        engine_module,
        "_engine_config_path",
        lambda name: config_dir / f"{name}.yaml",
    )
    monkeypatch.setattr(engine_module, "ZMQCommandIngressPair", capture_ingress_pair)

    with pytest.raises(_StopAtCommandIngress):
        await engine_module._run_engine(
            mock=True,
            engine_instance_id="a" * 32,
            shutdown_capability="b" * 64,
        )

    ordinary = captured["ordinary"]
    safe = captured["safe"]
    pair = captured["pair"]
    assert isinstance(ordinary, ZMQCommandServer)
    assert isinstance(safe, ZMQCommandServer)
    assert isinstance(pair, ZMQCommandIngressPair)
    assert pair._ordinary is ordinary
    assert pair._safe is safe
    assert ordinary._authority_registry is safe._authority_registry
    assert ordinary._accepted_actions is None
    assert ordinary._accepted_command_predicate is is_ordinary_command_endpoint_admitted

    root_handler = ordinary._handler
    safe_predicate = safe._accepted_command_predicate
    assert root_handler is safe._handler
    assert isinstance(root_handler, functools.partial)
    assert isinstance(safe_predicate, functools.partial)
    assert safe_predicate.func is engine_module._safe_engine_command_is_admitted
    assert safe_predicate.keywords == {"context": root_handler.keywords["context"]}
    assert safe._accepted_actions == frozenset({"engine_ready", "keithley_emergency_off", "launcher_shutdown"})
    assert set(asyncio.all_tasks()) == tasks_before

    dispatches: list[tuple[str, dict[str, object]]] = []

    async def ordinary_handler(command: dict[str, object]) -> dict[str, object]:
        dispatches.append(("ordinary", dict(command)))
        return {"ok": True, "lane": "ordinary"}

    async def safe_handler(command: dict[str, object]) -> dict[str, object]:
        dispatches.append(("safe", dict(command)))
        return {"ok": True, "lane": "safe"}

    ordinary._handler = ordinary_handler
    safe._handler = safe_handler
    exact_safe_commands: tuple[dict[str, object], ...] = (
        {"cmd": "keithley_emergency_off"},
        {"cmd": "keithley_emergency_off", "channel": "smua"},
        {"cmd": "keithley_emergency_off", "channel": "smub"},
        _launcher_shutdown_command(),
    )
    malformed_safe_commands: tuple[dict[str, object], ...] = (
        {"cmd": "keithley_emergency_off", "channel": None},
        {"cmd": "keithley_emergency_off", "channel": "SMUA"},
        {"cmd": "keithley_emergency_off", "unexpected": True},
        {"cmd": "launcher_shutdown"},
        {**_launcher_shutdown_command(), "engine_instance_id": "A" * 32},
        {**_launcher_shutdown_command(), "unexpected": True},
    )

    for command in (*exact_safe_commands, *malformed_safe_commands):
        reply = await ordinary._run_handler(command)
        assert reply["error_code"] == "command_endpoint_action_rejected"
        assert reply["delivery_state"] == "not_dispatched"
        assert reply["commit_state"] == "not_committed"
    assert dispatches == []

    ordinary_read = {"cmd": "safety_status"}
    assert await ordinary._run_handler(ordinary_read) == {
        "ok": True,
        "lane": "ordinary",
    }
    assert dispatches == [("ordinary", ordinary_read)]
    dispatches.clear()

    for command in malformed_safe_commands:
        reply = await safe._run_handler(command)
        assert reply["error_code"] == "command_endpoint_action_rejected"
        assert reply["delivery_state"] == "not_dispatched"
        assert reply["commit_state"] == "not_committed"
    assert dispatches == []

    for command in exact_safe_commands:
        assert await safe._run_handler(command) == {"ok": True, "lane": "safe"}
    assert dispatches == [("safe", command) for command in exact_safe_commands]


async def test_shared_registry_quarantines_targeted_off_but_not_global_or_launcher() -> None:
    ordinary_address = _free_tcp_address()
    safe_address = _free_tcp_address()
    registry = CommandAuthorityRegistry()
    release = asyncio.Event()
    mutation_started = asyncio.Event()
    safe_calls: list[str] = []

    async def ordinary_handler(cmd: dict[str, object]) -> dict[str, object]:
        if cmd["cmd"] == "experiment_start":
            mutation_started.set()
            await release.wait()
        return {"ok": True, "cmd": cmd["cmd"]}

    async def safe_handler(cmd: dict[str, object]) -> dict[str, object]:
        safe_calls.append(str(cmd["cmd"]))
        return {"ok": True, "cmd": cmd["cmd"]}

    ordinary = ZMQCommandServer(
        address=ordinary_address,
        handler=ordinary_handler,
        handler_timeout_s=0.02,
        authority_registry=registry,
    )
    safe = ZMQCommandServer(
        address=safe_address,
        handler=safe_handler,
        authority_registry=registry,
        accepted_actions=frozenset({"keithley_emergency_off", "launcher_shutdown"}),
        accepted_command_predicate=is_exact_safe_direction_envelope,
    )
    await ordinary.start()
    await safe.start()
    try:
        timed_out = await _send_command(ordinary_address, {"cmd": "experiment_start"})
        assert timed_out["error_code"] == "command_handler_timeout"
        await asyncio.wait_for(mutation_started.wait(), timeout=1.0)

        targeted = await _send_command(
            safe_address,
            {"cmd": "keithley_emergency_off", "channel": "smua"},
        )
        assert targeted["error_code"] == "command_authority_quarantined"
        assert safe_calls == []

        global_off = await _send_command(safe_address, {"cmd": "keithley_emergency_off"})
        launcher = await _send_command(safe_address, _launcher_shutdown_command())
        assert global_off["ok"] is True
        assert launcher["ok"] is True
        assert safe_calls == ["keithley_emergency_off", "launcher_shutdown"]
    finally:
        release.set()
        await asyncio.gather(ordinary.stop(), safe.stop())


@pytest.mark.parametrize(
    "handler_result",
    [
        object(),
        {
            "ok": False,
            "delivery_state": "dispatched",
            "commit_state": "unknown",
            "retry_safe": False,
        },
        {
            "ok": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
            "outcome_unknown": True,
        },
        {
            "ok": False,
            "delivery_state": "unknown",
            "commit_state": "not_committed",
        },
        {
            "ok": True,
            "delivery_state": "not_dispatched",
            "commit_state": "committed",
        },
        {
            "ok": True,
            "commit_state": "committed",
        },
    ],
    ids=[
        "invalid-type",
        "explicit-unknown",
        "committed-contradicts-outcome-unknown",
        "not-committed-contradicts-delivery-unknown",
        "committed-contradicts-not-dispatched",
        "committed-without-delivery-proof",
    ],
)
async def test_nonread_post_dispatch_unknown_latches_shared_authority(handler_result: object) -> None:
    registry = CommandAuthorityRegistry()
    dispatched: list[str] = []

    async def invalid_handler(cmd: dict[str, object]) -> object:
        dispatched.append(str(cmd["cmd"]))
        return handler_result

    first = ZMQCommandServer(handler=invalid_handler, authority_registry=registry)
    second = ZMQCommandServer(
        handler=lambda cmd: {"ok": True, "cmd": cmd["cmd"]},
        authority_registry=registry,
    )

    reply = await first._run_handler({"cmd": "experiment_start"})
    assert type(reply) is dict
    assert registry.has_uncertain_authority() is True
    rejected = await second._run_handler({"cmd": "experiment_stop"})
    assert rejected["error_code"] == "command_authority_quarantined"
    assert dispatched == ["experiment_start"]


@pytest.mark.parametrize(
    "late_reply",
    [
        {"ok": True},
        {"ok": False},
        {
            "ok": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
            "outcome_unknown": True,
        },
        {
            "ok": False,
            "delivery_state": "unknown",
            "commit_state": "not_committed",
        },
        {
            "ok": True,
            "delivery_state": "not_dispatched",
            "commit_state": "committed",
        },
        {
            "ok": True,
            "commit_state": "committed",
        },
    ],
    ids=[
        "bare-success",
        "bare-failure",
        "committed-contradicts-outcome-unknown",
        "not-committed-contradicts-delivery-unknown",
        "committed-contradicts-not-dispatched",
        "committed-without-delivery-proof",
    ],
)
async def test_late_nonread_without_exact_terminal_proof_keeps_shared_authority_latched(
    late_reply: dict[str, object],
) -> None:
    registry = CommandAuthorityRegistry()
    release = asyncio.Event()

    async def delayed(_cmd: dict[str, object]) -> dict[str, object]:
        await release.wait()
        return late_reply

    server = ZMQCommandServer(
        handler=delayed,
        handler_timeout_s=0.001,
        authority_registry=registry,
    )
    peer = ZMQCommandServer(
        handler=lambda _cmd: {
            "ok": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
        },
        authority_registry=registry,
    )

    timed_out = await server._run_handler({"cmd": "experiment_start"})
    assert timed_out["commit_state"] == "unknown"
    release.set()
    for _ in range(100):
        server._prune_handler_tasks()
        if not server._uncertain_authority_tasks:
            break
        await asyncio.sleep(0)

    assert server._uncertain_authority_tasks == set()
    assert registry.has_uncertain_authority() is True
    rejected = await peer._run_handler({"cmd": "experiment_stop"})
    assert rejected["error_code"] == "command_authority_quarantined"


@pytest.mark.parametrize("commit_state", ["committed", "not_committed"])
async def test_late_nonread_exact_terminal_proof_releases_task_derived_quarantine(
    commit_state: str,
) -> None:
    registry = CommandAuthorityRegistry()
    release = asyncio.Event()

    async def delayed(_cmd: dict[str, object]) -> dict[str, object]:
        await release.wait()
        return {
            "ok": commit_state == "committed",
            "delivery_state": "dispatched",
            "commit_state": commit_state,
        }

    server = ZMQCommandServer(
        handler=delayed,
        handler_timeout_s=0.001,
        authority_registry=registry,
    )

    timed_out = await server._run_handler({"cmd": "experiment_start"})
    assert timed_out["commit_state"] == "unknown"
    release.set()
    for _ in range(100):
        server._prune_handler_tasks()
        if not registry.has_uncertain_authority():
            break
        await asyncio.sleep(0)

    assert registry.has_uncertain_authority() is False


async def test_mutation_reply_serialization_failure_latches_shared_authority() -> None:
    address = _free_tcp_address()
    registry = CommandAuthorityRegistry()

    async def handler(_cmd: dict[str, object]) -> dict[object, object]:
        return {("not", "json"): True}

    server = ZMQCommandServer(address=address, handler=handler, authority_registry=registry)
    peer = ZMQCommandServer(
        handler=lambda cmd: {"ok": True, "cmd": cmd["cmd"]},
        authority_registry=registry,
    )
    await server.start()
    try:
        reply = await _send_command(address, {"cmd": "experiment_start"})
        assert reply["error_code"] == "command_reply_serialization_failed"
        assert reply["commit_state"] == "unknown"
        assert registry.has_uncertain_authority() is True
        rejected = await peer._run_handler({"cmd": "experiment_stop"})
        assert rejected["error_code"] == "command_authority_quarantined"
    finally:
        await server.stop()


async def test_mutation_reply_send_failure_latches_shared_authority() -> None:
    registry = CommandAuthorityRegistry()
    socket_owner = MagicMock()
    socket_owner.poll = AsyncMock(return_value=zmq.POLLIN)
    socket_owner.recv = AsyncMock(return_value=b'{"cmd":"experiment_start"}')
    socket_owner.send = AsyncMock(side_effect=RuntimeError("wire send failed"))
    server = ZMQCommandServer(
        handler=lambda _cmd: {"ok": True},
        authority_registry=registry,
    )
    server._socket = socket_owner
    server._running = True

    with pytest.raises(RuntimeError, match="wire send failed"):
        await server._serve_loop()

    assert registry.has_uncertain_authority() is True


async def test_nested_shield_child_keeps_mutation_quarantined_and_stop_waits_for_exact_settlement() -> None:
    address = _free_tcp_address()
    release = asyncio.Event()
    child_started = asyncio.Event()
    child_tasks: list[asyncio.Task[dict[str, object]]] = []
    commits: list[str] = []

    async def commit_child(action: str) -> dict[str, object]:
        child_started.set()
        await release.wait()
        commits.append(action)
        return {"ok": True, "cmd": action}

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        action = str(cmd["cmd"])
        if action != "experiment_start":
            return {"ok": True, "cmd": action}
        child = asyncio.create_task(commit_child(action), name="shielded-engine-mutation-owner")
        child_tasks.append(child)
        return await asyncio.shield(child)

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=0.02)
    await server.start()
    timed_out = await _send_command(address, {"cmd": "experiment_start"})
    assert timed_out["error_code"] == "command_handler_timeout"
    await asyncio.wait_for(child_started.wait(), timeout=1.0)
    assert len(child_tasks) == 1
    assert not child_tasks[0].done()
    assert server._has_uncertain_authority_owner() is True

    rejected = await _send_command(address, {"cmd": "experiment_stop"})
    _assert_failure_envelope(
        rejected,
        error_code="command_authority_quarantined",
        delivery_state="not_dispatched",
        commit_state="not_committed",
        retry_safe=False,
    )

    stop_task = asyncio.create_task(server.stop())
    await asyncio.sleep(0.02)
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


async def test_cancelled_stop_still_closes_rep_socket_and_context_after_handler_settlement() -> None:
    address = _free_tcp_address()
    release = asyncio.Event()
    started = asyncio.Event()

    async def handler(_cmd: dict[str, object]) -> dict[str, object]:
        started.set()
        await release.wait()
        return {"ok": True}

    server = ZMQCommandServer(address=address, handler=handler, handler_timeout_s=0.02)
    await server.start()
    try:
        timed_out = await _send_command(address, {"cmd": "experiment_start"})
        assert timed_out["error_code"] == "command_handler_timeout"
        await asyncio.wait_for(started.wait(), timeout=1.0)

        stop_task = asyncio.create_task(server.stop())
        await asyncio.sleep(0.02)
        assert not stop_task.done()
        stop_task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stop_task, timeout=1.0)

        assert server._handler_tasks == set()
        assert server._uncertain_authority_tasks == set()
        assert server._socket is None
        assert server._ctx is None
    finally:
        release.set()
        if server._socket is not None or server._ctx is not None:
            await server.stop()


async def test_command_server_double_start_rejects_without_replacing_any_live_owner() -> None:
    server = ZMQCommandServer(address=_free_tcp_address(), handler=lambda _cmd: {"ok": True})
    await server.start()
    original = (server._ctx, server._socket, server._task)
    try:
        with pytest.raises(RuntimeError, match="already started|not pristine"):
            await server.start()
        assert (server._ctx, server._socket, server._task) == original
        assert server._running is True
    finally:
        await server.stop()


async def test_command_server_partial_start_rolls_back_and_allows_clean_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[MagicMock] = []
    socket_owner = MagicMock(name="retry_socket")

    def context_factory() -> MagicMock:
        context = MagicMock(name=f"context_{len(contexts)}")
        contexts.append(context)
        return context

    attempts = 0

    async def open_socket() -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("bind failed")
        return socket_owner

    server = ZMQCommandServer(handler=lambda _cmd: {"ok": True})
    monkeypatch.setattr(zmq.asyncio, "Context", context_factory)
    monkeypatch.setattr(server, "_open_bound_socket", open_socket)
    monkeypatch.setattr(server, "_start_serve_task", lambda: None)

    with pytest.raises(RuntimeError, match="bind failed"):
        await server.start()

    assert len(contexts) == 1
    contexts[0].term.assert_called_once_with()
    assert server._ctx is None
    assert server._socket is None
    assert server._task is None
    assert server._running is False

    await server.start()
    assert server._ctx is contexts[1]
    assert server._socket is socket_owner
    assert server._running is True
    await server.stop()


async def test_command_server_stop_retains_failed_socket_owner_for_retry() -> None:
    class RetrySocket:
        def __init__(self) -> None:
            self.calls = 0

        def close(self, *, linger: int = 0) -> None:
            assert linger == 0
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("socket close failed")

    socket_owner = RetrySocket()
    context_owner = MagicMock(name="context_owner")
    server = ZMQCommandServer(handler=lambda _cmd: {"ok": True})
    server._socket = socket_owner  # type: ignore[assignment]
    server._ctx = context_owner
    server._running = True

    with pytest.raises(RuntimeError, match="socket close failed"):
        await server.stop()

    assert server._socket is socket_owner
    assert server._ctx is context_owner
    context_owner.term.assert_not_called()

    await server.stop()
    assert socket_owner.calls == 2
    context_owner.term.assert_called_once_with()
    assert server._socket is None
    assert server._ctx is None


async def test_command_server_stop_retains_failed_context_owner_for_retry() -> None:
    socket_owner = MagicMock(name="socket_owner")
    context_owner = MagicMock(name="context_owner")
    context_owner.term.side_effect = [RuntimeError("context term failed"), None]
    server = ZMQCommandServer(handler=lambda _cmd: {"ok": True})
    server._socket = socket_owner
    server._ctx = context_owner
    server._running = True

    with pytest.raises(RuntimeError, match="context term failed"):
        await server.stop()

    socket_owner.close.assert_called_once_with(linger=0)
    assert server._socket is None
    assert server._ctx is context_owner

    await server.stop()
    socket_owner.close.assert_called_once_with(linger=0)
    assert context_owner.term.call_count == 2
    assert server._ctx is None


async def test_command_server_cleanup_failure_remains_observable_under_caller_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settlement_entered = asyncio.Event()
    release_settlement = asyncio.Event()

    async def delayed_settlement() -> None:
        settlement_entered.set()
        await release_settlement.wait()

    socket_owner = MagicMock(name="socket_owner")
    socket_owner.close.side_effect = RuntimeError("socket close failed after cancellation")
    context_owner = MagicMock(name="context_owner")
    server = ZMQCommandServer(handler=lambda _cmd: {"ok": True})
    server._socket = socket_owner
    server._ctx = context_owner
    server._running = True
    monkeypatch.setattr(server, "_settle_handler_tasks", delayed_settlement)

    stop_task = asyncio.create_task(server.stop())
    await asyncio.wait_for(settlement_entered.wait(), timeout=1.0)
    stop_task.cancel()
    release_settlement.set()

    with pytest.raises(RuntimeError, match="socket close failed after cancellation"):
        await asyncio.wait_for(stop_task, timeout=1.0)

    assert server._socket is socket_owner
    assert server._ctx is context_owner
    context_owner.term.assert_not_called()


async def test_cancelled_handler_waiter_retains_uncertain_owner_until_settlement() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    commits: list[str] = []

    async def handler(cmd: dict[str, object]) -> dict[str, object]:
        started.set()
        await release.wait()
        commits.append(str(cmd["cmd"]))
        return {
            "ok": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
        }

    server = ZMQCommandServer(handler=handler, handler_timeout_s=5.0)
    waiter = asyncio.create_task(server._run_handler({"cmd": "experiment_start"}))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert commits == []
    assert server._has_uncertain_authority_owner() is True

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


async def test_launcher_shutdown_requires_exact_capability_and_verified_global_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _shutdown_context(off_result=_verified_global_off_result(state="safe_off", channels=["smua", "smub"]))
    command = _launcher_shutdown_command()

    invalid = await _handle_gui_command({"cmd": "launcher_shutdown"}, context=context)
    assert invalid["error_code"] == "launcher_shutdown_invalid"
    assert invalid["delivery_state"] == "dispatched"
    assert invalid["commit_state"] == "not_committed"
    assert invalid["retry_safe"] is True

    wrong = await _handle_gui_command({**command, "shutdown_capability": "d" * 64}, context=context)
    assert wrong["error_code"] == "launcher_shutdown_authority_mismatch"
    assert wrong["delivery_state"] == "dispatched"
    assert wrong["commit_state"] == "not_committed"
    assert wrong["retry_safe"] is False
    assert "b" * 64 not in json.dumps(wrong, sort_keys=True)
    assert "d" * 64 not in json.dumps(wrong, sort_keys=True)
    context.safety_manager.emergency_off.assert_not_awaited()

    receipt = await _handle_gui_command(command, context=context)
    assert receipt == {
        "ok": True,
        "schema": "cryodaq.engine_shutdown.v2",
        "engine_instance_id": "a" * 32,
        "request_id": "c" * 32,
        "off_evidence": {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": True,
        },
        "teardown_requested": True,
        "delivery_state": "dispatched",
        "commit_state": "committed",
    }
    assert "b" * 64 not in json.dumps(receipt, sort_keys=True)
    assert "b" * 64 not in caplog.text
    assert "d" * 64 not in caplog.text
    context.safety_manager.emergency_off.assert_awaited_once_with(channel=None)
    assert context.shutdown_event is not None
    assert not context.shutdown_event.is_set()

    _request_teardown_after_shutdown_receipt(
        context,
        command,
        {**receipt, "engine_instance_id": "d" * 32, "proto": PROTOCOL_VERSION},
    )
    assert not context.shutdown_event.is_set()
    _request_teardown_after_shutdown_receipt(context, command, {**receipt, "proto": PROTOCOL_VERSION})
    assert context.shutdown_event.is_set()

    assert await _handle_gui_command(command, context=context) == receipt
    context.safety_manager.emergency_off.assert_awaited_once_with(channel=None)
    conflict = await _handle_gui_command(_launcher_shutdown_command(request_id="e" * 32), context=context)
    assert conflict["error_code"] == "launcher_shutdown_already_requested"
    assert conflict["delivery_state"] == "dispatched"
    assert conflict["commit_state"] == "not_committed"
    assert conflict["retry_safe"] is False


async def test_real_server_shutdown_latch_rejects_queued_output_mutation() -> None:
    address = _free_tcp_address()
    off_started = asyncio.Event()
    release_off = asyncio.Event()

    async def delayed_off(*, channel: str | None = None) -> dict[str, object]:
        assert channel is None
        off_started.set()
        await release_off.wait()
        return _verified_global_off_result()

    context = _shutdown_context(off_result={"ok": True, "active_channels": []})
    context.safety_manager.emergency_off = AsyncMock(side_effect=delayed_off)
    context.mutation_capability_token = "m" * 32
    handler = functools.partial(_handle_gui_command, context=context)
    server = ZMQCommandServer(
        address=address,
        handler=handler,
        reply_sent_callback=functools.partial(
            _request_teardown_after_shutdown_receipt,
            context,
        ),
    )
    await server.start()
    try:
        shutdown_task = asyncio.create_task(_send_command(address, _launcher_shutdown_command()))
        await asyncio.wait_for(off_started.wait(), timeout=2)
        mutation_task = asyncio.create_task(
            _send_command(
                address,
                {
                    "cmd": "keithley_start",
                    "channel": "smua",
                    "protocol_major": MUTATION_PROTOCOL_MAJOR,
                    "mutation_capability": ENGINE_MUTATION_CAPABILITY,
                    "capability_token": context.mutation_capability_token,
                },
            )
        )
        await asyncio.sleep(0)
        assert not shutdown_task.done()
        assert not mutation_task.done()

        release_off.set()
        shutdown_reply = await asyncio.wait_for(shutdown_task, timeout=3)
        mutation_reply = await asyncio.wait_for(mutation_task, timeout=3)

        assert shutdown_reply["schema"] == "cryodaq.engine_shutdown.v2"
        assert shutdown_reply["off_evidence"]["verified_off"] is True
        assert mutation_reply == {
            "ok": False,
            "error_code": "engine_shutdown_latched",
            "error": "engine shutdown owns mutation admission; later state changes are refused",
            "delivery_state": "dispatched",
            "commit_state": "not_committed",
            "retry_safe": False,
            "proto": PROTOCOL_VERSION,
        }
        context.safety_manager.emergency_off.assert_awaited_once_with(channel=None)
        assert context.shutdown_event is not None
        assert context.shutdown_event.is_set()
    finally:
        release_off.set()
        await server.stop()


async def test_launcher_shutdown_global_off_failure_never_creates_receipt() -> None:
    context = _shutdown_context(off_result={"ok": False, "active_channels": ["smua"], "state": "fault_latched"})
    context.mutation_capability_token = "m" * 32
    context.safety_manager.emergency_off = AsyncMock(
        side_effect=[
            {"ok": False, "active_channels": ["smua"], "state": "fault_latched"},
            _verified_global_off_result(),
            _verified_global_off_result(),
        ]
    )
    context.safety_manager.get_status.return_value = {"state": "safe_off"}
    context.event_logger.log_event = AsyncMock()
    command = _launcher_shutdown_command()

    result = await _handle_gui_command(command, context=context)

    assert result["error_code"] == "launcher_shutdown_global_off_unverified"
    assert context.shutdown_request_id == command["request_id"]
    assert context.shutdown_receipt is None
    assert context.shutdown_event is not None
    assert not context.shutdown_event.is_set()

    mutation = await _handle_gui_command(
        {
            "cmd": "keithley_start",
            "channel": "smua",
            "protocol_major": MUTATION_PROTOCOL_MAJOR,
            "mutation_capability": ENGINE_MUTATION_CAPABILITY,
            "capability_token": context.mutation_capability_token,
        },
        context=context,
    )
    assert mutation["error_code"] == "engine_shutdown_latched"

    status = await _handle_gui_command({"cmd": "safety_status"}, context=context)
    assert status.get("error_code") != "engine_shutdown_latched"

    global_off = await _handle_gui_command({"cmd": "keithley_emergency_off"}, context=context)
    assert global_off["ok"] is True
    assert global_off["active_channels"] == []

    retry = await _handle_gui_command(command, context=context)
    assert retry["schema"] == "cryodaq.engine_shutdown.v2"
    assert retry["off_evidence"]["verified_off"] is True
    assert context.shutdown_receipt == retry
    assert context.safety_manager.emergency_off.await_count == 3


async def test_launcher_shutdown_refuses_unknown_device_off_evidence() -> None:
    """A successful coroutine is not a physical-OFF receipt."""
    context = _shutdown_context(
        off_result={
            "ok": True,
            "active_channels": [],
            "off_evidence": {
                "off_tier": "verified_off",
                "channel_off_results": {
                    "smua": "physical_state_unknown",
                    "smub": "physical_state_unknown",
                },
                "verified_off": False,
            },
        }
    )

    result = await _handle_gui_command(_launcher_shutdown_command(), context=context)

    assert result["error_code"] == "launcher_shutdown_global_off_unverified"
    assert context.shutdown_receipt is None
    assert context.shutdown_event is not None
    assert not context.shutdown_event.is_set()


async def test_reply_sent_callback_runs_only_after_successful_wire_send() -> None:
    callbacks: list[tuple[dict[str, object], dict[str, object]]] = []
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(side_effect=[zmq.POLLIN, asyncio.CancelledError()])
    socket_mock.recv = AsyncMock(return_value=json.dumps(_launcher_shutdown_command()).encode())
    socket_mock.send = AsyncMock()
    server = ZMQCommandServer(
        handler=lambda _cmd: {"ok": True, "receipt": "exact"},
        reply_sent_callback=lambda cmd, reply: callbacks.append((dict(cmd), dict(reply))),
    )
    server._socket = socket_mock
    server._running = True

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    socket_mock.send.assert_awaited_once()
    assert callbacks == [(_launcher_shutdown_command(), {"ok": True, "receipt": "exact", "proto": PROTOCOL_VERSION})]


async def test_reply_send_failure_never_triggers_shutdown_callback() -> None:
    callback = MagicMock()
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(return_value=zmq.POLLIN)
    socket_mock.recv = AsyncMock(return_value=json.dumps(_launcher_shutdown_command()).encode())
    socket_mock.send = AsyncMock(side_effect=OSError("wire unavailable"))
    server = ZMQCommandServer(
        handler=lambda _cmd: {"ok": True, "receipt": "not-delivered"},
        reply_sent_callback=callback,
    )
    server._socket = socket_mock
    server._running = True

    with pytest.raises(OSError, match="wire unavailable"):
        await server._serve_loop()

    callback.assert_not_called()


async def test_malformed_json_has_no_callback_and_next_request_uses_clean_state() -> None:
    callbacks: list[tuple[dict[str, object], dict[str, object]]] = []
    valid_command = _launcher_shutdown_command()
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(side_effect=[zmq.POLLIN, zmq.POLLIN, asyncio.CancelledError()])
    socket_mock.recv = AsyncMock(side_effect=[b"{", json.dumps(valid_command).encode()])
    socket_mock.send = AsyncMock()
    server = ZMQCommandServer(
        handler=lambda _cmd: {"ok": True, "receipt": "valid"},
        reply_sent_callback=lambda cmd, reply: callbacks.append((dict(cmd), dict(reply))),
    )
    server._socket = socket_mock
    server._running = True

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    assert socket_mock.send.await_count == 2
    first_wire = json.loads(socket_mock.send.await_args_list[0].args[0])
    second_wire = json.loads(socket_mock.send.await_args_list[1].args[0])
    assert first_wire["error_code"] == "command_request_invalid"
    assert second_wire == {"ok": True, "receipt": "valid", "proto": PROTOCOL_VERSION}
    assert callbacks == [(valid_command, second_wire)]


async def test_serialization_fallback_never_releases_teardown_for_unsent_receipt() -> None:
    context = _shutdown_context(off_result={"ok": True, "active_channels": []})
    assert context.shutdown_event is not None
    command = _launcher_shutdown_command()
    unsent_receipt: dict[str, object] = {
        "ok": True,
        "schema": "cryodaq.engine_shutdown.v2",
        "engine_instance_id": "a" * 32,
        "request_id": "c" * 32,
        "off_evidence": {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": True,
        },
        "teardown_requested": True,
        "delivery_state": "dispatched",
        "commit_state": "committed",
        "unserializable": object(),
    }
    context.shutdown_receipt = unsent_receipt
    socket_mock = MagicMock()
    socket_mock.poll = AsyncMock(side_effect=[zmq.POLLIN, asyncio.CancelledError()])
    socket_mock.recv = AsyncMock(return_value=json.dumps(command).encode())
    socket_mock.send = AsyncMock()
    server = ZMQCommandServer(
        handler=lambda _cmd: unsent_receipt,
        reply_sent_callback=functools.partial(
            _request_teardown_after_shutdown_receipt,
            context,
        ),
    )
    server._socket = socket_mock
    server._running = True

    with pytest.raises(asyncio.CancelledError):
        await server._serve_loop()

    sent_wire = json.loads(socket_mock.send.await_args.args[0])
    assert sent_wire["error_code"] == "command_reply_serialization_failed"
    assert not context.shutdown_event.is_set()
