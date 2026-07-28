"""Stage 3 tests: replay_engine package — source dispatch + ZMQ integration.

Uses isolated test ports (15555/15556) to avoid conflicts with a running engine.
All async tests use asyncio_mode=auto (pyproject.toml).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zmq
import zmq.asyncio

from cryodaq.core.zmq_bridge import (
    ZMQCommandIngressTerminalError,
    ZMQCommandIngressTerminalFailure,
)
from cryodaq.replay_engine.sources import (
    CurveReplay,
    DirectoryReplay,
    SQLiteReplay,
    resolve_source,
)

_TEST_PUB = "tcp://127.0.0.1:15555"
_TEST_CMD = "tcp://127.0.0.1:15556"
_TEST_SAFE_CMD = "tcp://127.0.0.1:15558"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_replay_child_emits_exact_v2_receipt_with_both_command_endpoints(tmp_path: Path) -> None:
    from cryodaq.replay_engine.__main__ import _emit_launcher_replay_ready

    read_fd, write_fd = os.pipe()
    source = tmp_path / "replay.db"
    try:
        _emit_launcher_replay_ready(
            nonce="a" * 64,
            session_id="b" * 32,
            source=source,
            speed=5.0,
            pub_addr="tcp://127.0.0.1:5555",
            cmd_addr="tcp://127.0.0.1:5556",
            safe_cmd_addr="tcp://127.0.0.1:5558",
            channel_fd=write_fd,
        )
        raw = os.read(read_fd, 8192)
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass
        os.close(read_fd)

    prefix, payload = raw.split(b" ", 1)
    assert prefix == b"CRYODAQ_REPLAY_READY_V2"
    assert json.loads(payload) == {
        "schema": "cryodaq.replay_ready.v2",
        "nonce": "a" * 64,
        "session_id": "b" * 32,
        "mode": "replay",
        "source": str(source),
        "speed": 5.0,
        "pid": os.getpid(),
        "pub_addr": "tcp://127.0.0.1:5555",
        "cmd_addr": "tcp://127.0.0.1:5556",
        "safe_cmd_addr": "tcp://127.0.0.1:5558",
    }


@pytest.mark.asyncio
async def test_replay_ready_requires_full_private_challenge_and_real_encoder_injects_proto() -> None:
    from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer
    from cryodaq.replay_engine.server import ReplayEngine

    engine = object.__new__(ReplayEngine)
    engine._launcher_ready_nonce = "a" * 64
    engine._launcher_session_id = "b" * 32
    engine._source_path = Path("C:/data/replay.db")
    engine._speed = 5.0
    engine._pub_addr = "tcp://127.0.0.1:5555"
    engine._cmd_addr = "tcp://127.0.0.1:5556"
    engine._safe_cmd_addr = "tcp://127.0.0.1:5558"
    receipt = {
        "schema": "cryodaq.replay_ready.v2",
        "nonce": "a" * 64,
        "session_id": "b" * 32,
        "mode": "replay",
        "source": str(engine._source_path),
        "speed": 5.0,
        "pid": os.getpid(),
        "pub_addr": engine._pub_addr,
        "cmd_addr": engine._cmd_addr,
        "safe_cmd_addr": engine._safe_cmd_addr,
    }

    assert await engine._handle_command({"cmd": "replay_ready"}) == {
        "ok": False,
        "error_code": "replay_ready_invalid",
    }
    result = await engine._handle_command({"cmd": "replay_ready", **receipt})
    assert result == {"ok": True, **receipt}
    assert "proto" not in result
    wire = json.loads(ZMQCommandServer()._encode_reply(result))
    assert wire == {"ok": True, **receipt, "proto": PROTOCOL_VERSION}

    missing_safe = dict(receipt)
    del missing_safe["safe_cmd_addr"]
    assert (await engine._handle_command({"cmd": "replay_ready", **missing_safe}))["ok"] is False

    legacy = dict(receipt)
    legacy["schema"] = "cryodaq.replay_ready.v1"
    assert (await engine._handle_command({"cmd": "replay_ready", **legacy}))["ok"] is False


@pytest.mark.asyncio
async def test_replay_mutation_discovery_uses_launcher_scope_and_real_wire_proto() -> None:
    from cryodaq.core.command_authority import (
        MUTATION_PROTOCOL_MAJOR,
        MUTATION_RECEIPT_SCHEMA,
        REPLAY_MUTATION_CAPABILITY,
    )
    from cryodaq.core.zmq_bridge import PROTOCOL_VERSION, ZMQCommandServer
    from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION
    from cryodaq.replay_engine.server import ReplayEngine

    engine = object.__new__(ReplayEngine)
    engine._launcher_session_id = "b" * 32
    engine._mutation_capability_token = "c" * 32
    engine._source_path = Path("C:/data/replay.db")
    engine._speed = 5.0

    result = await engine._handle_command({"cmd": "mutation_capabilities"})

    assert result == {
        "ok": True,
        "compatibility_receipt": {
            "schema": MUTATION_RECEIPT_SCHEMA,
            "accepted": True,
            "server_protocol_major": MUTATION_PROTOCOL_MAJOR,
            "required_capability": REPLAY_MUTATION_CAPABILITY,
            "capability_token": "c" * 32,
            "mode": "replay",
            "session_id": "b" * 32,
            "source": str(engine._source_path),
            "speed": 5.0,
        },
    }
    assert "proto" not in result, "handlers must not forge the transport-owned protocol field"
    wire = json.loads(ZMQCommandServer()._encode_reply(result))
    assert set(wire) == {"ok", "compatibility_receipt", "proto"}
    assert wire["proto"] == PROTOCOL_VERSION == CLIENT_PROTOCOL_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"pid": True},
        {"speed": 5},
        {"nonce": "c" * 64},
        {"session_id": "d" * 32},
        {"source": "C:/data/other.db"},
        {"cmd_addr": "tcp://127.0.0.1:6556"},
        {"safe_cmd_addr": "tcp://127.0.0.1:6558"},
        {"extra": "not-allowed"},
    ],
)
async def test_replay_ready_rejects_bool_numeric_near_misses_and_extra_keys(
    mutation: dict[str, object],
) -> None:
    from cryodaq.replay_engine.server import ReplayEngine

    engine = object.__new__(ReplayEngine)
    engine._launcher_ready_nonce = "a" * 64
    engine._launcher_session_id = "b" * 32
    engine._source_path = Path("C:/data/replay.db")
    engine._speed = 5.0
    engine._pub_addr = "tcp://127.0.0.1:5555"
    engine._cmd_addr = "tcp://127.0.0.1:5556"
    engine._safe_cmd_addr = "tcp://127.0.0.1:5558"
    command: dict[str, object] = {
        "cmd": "replay_ready",
        "schema": "cryodaq.replay_ready.v2",
        "nonce": "a" * 64,
        "session_id": "b" * 32,
        "mode": "replay",
        "source": str(engine._source_path),
        "speed": 5.0,
        "pid": os.getpid(),
        "pub_addr": engine._pub_addr,
        "cmd_addr": engine._cmd_addr,
        "safe_cmd_addr": engine._safe_cmd_addr,
    }
    command.update(mutation)

    response = await engine._handle_command(command)

    assert response["ok"] is False
    assert response["error_code"] in {"replay_ready_invalid", "replay_ready_mismatch"}


def test_replay_engine_lock_is_exclusive_persistent_and_reacquirable(tmp_path, monkeypatch) -> None:
    """Replay and live contenders must always address one stable lock object."""

    from cryodaq.replay_engine.__main__ import _acquire_engine_lock, _release_engine_lock

    monkeypatch.setattr("cryodaq.instance_lock.get_data_dir", lambda: tmp_path)
    lock_path = tmp_path / ".engine.lock"

    first = _acquire_engine_lock()
    try:
        assert lock_path.exists()
        with pytest.raises(SystemExit):
            _acquire_engine_lock()
    finally:
        _release_engine_lock(first)

    assert lock_path.exists()
    second = _acquire_engine_lock()
    _release_engine_lock(second)
    assert lock_path.exists()


@pytest.mark.asyncio
async def test_replay_cooldown_stop_failure_retains_same_owner_and_refuses_success() -> None:
    from cryodaq.replay_engine.server import ReplayEngine

    events: list[str] = []

    class CooldownOwner:
        def __init__(self) -> None:
            self.calls = 0

        async def stop(self) -> None:
            self.calls += 1
            events.append(f"cooldown:{self.calls}")
            if self.calls == 1:
                raise RuntimeError("TOP-SECRET shutdown detail")

    class DownstreamOwner:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls = 0

        async def stop(self) -> None:
            self.calls += 1
            events.append(self.name)

    engine = object.__new__(ReplayEngine)
    engine._watchdog_task = None
    engine._source = None
    cooldown = CooldownOwner()
    command = DownstreamOwner("command")
    publisher = DownstreamOwner("publisher")
    engine._cooldown_service = cooldown
    engine._cmd = command
    engine._pub = publisher

    with pytest.raises(RuntimeError):
        await engine.stop()

    assert engine._cooldown_service is cooldown
    assert cooldown.calls == 1
    assert command.calls == 0
    assert publisher.calls == 0
    assert events == ["cooldown:1"]

    await engine.stop()

    assert engine._cooldown_service is None
    assert cooldown.calls == 2
    assert command.calls == 1
    assert publisher.calls == 1
    assert events == ["cooldown:1", "cooldown:2", "command", "publisher"]


@pytest.mark.asyncio
async def test_replay_runtime_automatically_retries_retained_stop_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    events: list[str] = []

    class Engine:
        def __init__(self) -> None:
            self.stop_attempts = 0

        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            return None

        @property
        def command_ingress_terminal_failure(self):
            return None

        async def wait_command_ingress_failure(self):
            await asyncio.Event().wait()

        async def run_source(self) -> None:
            events.append("source-complete")

        async def stop(self) -> None:
            self.stop_attempts += 1
            events.append(f"stop:{self.stop_attempts}")
            if self.stop_attempts == 1:
                raise RuntimeError("transient retained-owner failure")

    engine = Engine()
    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: engine)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    await asyncio.wait_for(replay_main._run(args), timeout=1.0)

    assert engine.stop_attempts == 2
    assert events == ["start", "source-complete", "stop:1", "stop:2"]


@pytest.mark.asyncio
async def test_replay_runtime_finally_resists_repeated_cancellation_until_stop_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    source_entered = asyncio.Event()
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()

    class Engine:
        def __init__(self, *_args, **_kwargs) -> None:
            self.source_cancelled = False
            self.stop_cancelled = False
            self.stop_completed = False

        async def start(self) -> None:
            return None

        def require_command_ingress_healthy(self) -> None:
            return None

        @property
        def command_ingress_terminal_failure(self):
            return None

        async def wait_command_ingress_failure(self):
            await asyncio.Event().wait()

        async def run_source(self) -> None:
            source_entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.source_cancelled = True
                raise

        async def stop(self) -> None:
            stop_entered.set()
            try:
                await release_stop.wait()
            except asyncio.CancelledError:
                self.stop_cancelled = True
                raise
            self.stop_completed = True

    engine = Engine()
    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: engine)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    owner = asyncio.create_task(replay_main._run(args), name="replay-runtime-owner")
    await asyncio.wait_for(source_entered.wait(), timeout=1.0)
    owner.cancel()
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)

    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    assert not owner.done()
    assert engine.source_cancelled is True
    assert engine.stop_cancelled is False
    assert engine.stop_completed is False

    release_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=1.0)
    assert engine.stop_completed is True
    assert engine.stop_cancelled is False


@pytest.mark.asyncio
async def test_replay_source_independent_cancellation_is_failure_after_exact_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child task cancelling itself is a fault, not a clean replay completion."""
    import cryodaq.replay_engine.__main__ as replay_main

    events: list[str] = []

    class Engine:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            return None

        @property
        def command_ingress_terminal_failure(self):
            return None

        async def wait_command_ingress_failure(self):
            await asyncio.Event().wait()

        async def run_source(self) -> None:
            events.append("source.cancel")
            raise asyncio.CancelledError()

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(replay_main, "ReplayEngine", Engine)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    with pytest.raises(RuntimeError, match="replay source execution failed"):
        await replay_main._run(args)

    assert events == ["start", "source.cancel", "stop"]


@pytest.mark.asyncio
async def test_replay_command_ingress_terminal_failure_cancels_peers_settles_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    events: list[str] = []
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="safe",
        stage="recovery_exhausted",
        failure_type="RuntimeError",
    )

    class Engine:
        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            events.append("healthy")

        @property
        def command_ingress_terminal_failure(self):
            return None

        async def run_source(self) -> None:
            events.append("source.start")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("source.cancel")
                raise

        async def wait_command_ingress_failure(self):
            events.append("ingress.failure")
            return failure

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: Engine())
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    with pytest.raises(RuntimeError, match="replay command ingress terminated"):
        await replay_main._run(args)

    live_terminal_tasks = {
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"replay_source", "stop_signal", "command_ingress_terminal"}
    }
    assert live_terminal_tasks == set()
    assert events == [
        "start",
        "healthy",
        "healthy",
        "source.start",
        "ingress.failure",
        "source.cancel",
        "stop",
    ]


@pytest.mark.asyncio
async def test_replay_sticky_ingress_failure_wins_source_completion_before_waiter_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    events: list[str] = []
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="ordinary",
        stage="loop_closed",
        failure_type="RuntimeError",
    )

    class Engine:
        def __init__(self) -> None:
            self.latched = None

        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            events.append("healthy")

        @property
        def command_ingress_terminal_failure(self):
            return self.latched

        async def run_source(self) -> None:
            events.append("source.complete")
            self.latched = failure

        async def wait_command_ingress_failure(self):
            events.append("ingress.wait")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("ingress.cancel")
                raise

        async def stop(self) -> None:
            events.append("stop")

    engine = Engine()
    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: engine)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    with pytest.raises(RuntimeError, match="replay command ingress terminated"):
        await replay_main._run(args)

    live_terminal_tasks = {
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name() in {"replay_source", "stop_signal", "command_ingress_terminal"}
    }
    assert live_terminal_tasks == set()
    assert events == [
        "start",
        "healthy",
        "healthy",
        "source.complete",
        "ingress.wait",
        "ingress.cancel",
        "stop",
    ]


@pytest.mark.asyncio
async def test_replay_startup_terminal_ingress_blocks_ready_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    emitted: list[object] = []
    events: list[str] = []
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="ordinary",
        stage="recovery_task_create_failed",
        failure_type="OSError",
    )

    class Engine:
        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            raise ZMQCommandIngressTerminalError(failure)

        @property
        def command_ingress_terminal_failure(self):
            return failure

        async def run_source(self) -> None:
            raise AssertionError("source must not start")

        async def wait_command_ingress_failure(self):
            raise AssertionError("terminal waiter must not start")

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(replay_main, "_emit_launcher_replay_ready", lambda **kwargs: emitted.append(kwargs))
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    with pytest.raises(RuntimeError, match="replay runtime failed"):
        await replay_main._run(args)

    assert emitted == []
    assert events == ["start", "stop"]


@pytest.mark.asyncio
async def test_replay_ready_emission_terminal_race_blocks_runtime_commit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import cryodaq.replay_engine.__main__ as replay_main

    caplog.set_level("INFO")
    emitted: list[object] = []
    events: list[str] = []
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="safe",
        stage="recovery_exhausted",
        failure_type="RuntimeError",
    )

    class Engine:
        latched = False

        async def start(self) -> None:
            events.append("start")

        def require_command_ingress_healthy(self) -> None:
            events.append("health")
            if self.latched:
                raise ZMQCommandIngressTerminalError(failure)

        @property
        def command_ingress_terminal_failure(self):
            return failure if self.latched else None

        async def run_source(self) -> None:
            raise AssertionError("source must not start")

        async def wait_command_ingress_failure(self):
            raise AssertionError("terminal waiter must not start")

        async def stop(self) -> None:
            events.append("stop")

    engine = Engine()

    def emit(**kwargs) -> None:
        emitted.append(kwargs)
        engine.latched = True

    monkeypatch.setattr(replay_main, "ReplayEngine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(replay_main, "_emit_launcher_replay_ready", emit)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        legacy_channel_era=None,
        source=Path("replay.db"),
        speed=1.0,
        phase="cooldown",
        loop=False,
        pub_addr="inproc://replay-pub",
        cmd_addr="inproc://replay-cmd",
        safe_cmd_addr="inproc://replay-safe-cmd",
        cold_channel="cold",
        warm_channel="warm",
        force_replay=True,
    )

    with pytest.raises(RuntimeError, match="replay runtime failed"):
        await replay_main._run(args)

    assert len(emitted) == 1
    assert events == ["start", "health", "health", "stop"]
    assert "Replay engine exact readiness committed" not in caplog.text


@pytest.mark.asyncio
async def test_replay_partial_publisher_start_rollback_resists_repeated_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.replay_engine.server as replay_server

    publisher_start_entered = asyncio.Event()
    publisher_stop_entered = asyncio.Event()
    release_publisher_stop = asyncio.Event()

    class Source:
        def __init__(self) -> None:
            self.stop_calls = 0

        def stop(self) -> None:
            self.stop_calls += 1

    class Broker:
        async def subscribe(self, *_args, **_kwargs):
            return asyncio.Queue()

    class Publisher:
        def __init__(self, _address: str) -> None:
            self.stop_cancelled = False
            self.stop_completed = False

        async def start(self, _queue) -> None:
            publisher_start_entered.set()
            await asyncio.Future()

        async def stop(self) -> None:
            publisher_stop_entered.set()
            try:
                await release_publisher_stop.wait()
            except asyncio.CancelledError:
                self.stop_cancelled = True
                raise
            self.stop_completed = True

    source = Source()
    publishers: list[Publisher] = []

    def publisher_factory(
        address: str,
        *,
        applied_cold_stage_channel: str | None = None,
    ) -> Publisher:
        publisher = Publisher(address)
        publisher.applied_cold_stage_channel = applied_cold_stage_channel
        publishers.append(publisher)
        return publisher

    monkeypatch.setattr(replay_server, "_check_port_available", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(replay_server, "resolve_source", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(replay_server, "DataBroker", Broker)
    monkeypatch.setattr(replay_server, "ZMQPublisher", publisher_factory)
    monkeypatch.setattr(
        replay_server,
        "ZMQCommandServer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("command owner must not start")),
    )

    engine = object.__new__(replay_server.ReplayEngine)
    engine._source_path = Path("replay.db")
    engine._speed = 1.0
    engine._phase = "cooldown"
    engine._loop = False
    engine._pub_addr = "inproc://replay-pub"
    engine._cmd_addr = "inproc://replay-cmd"
    engine._safe_cmd_addr = "inproc://replay-safe-cmd"
    engine._cold_channel = "cold"
    engine._warm_channel = "warm"
    engine._force = True
    engine._channel_map = None
    engine._launcher_session_id = None
    engine._pub = None
    engine._cmd = None
    engine._pub_queue = None
    engine._source = None
    engine._source_quiesced = False
    engine._session_start = 0.0
    engine._readings_published = 0
    engine._watchdog_task = None
    engine._broker = None
    engine._lifecycle_started = False
    engine._cooldown_service = None

    owner = asyncio.create_task(engine.start(), name="replay-start-owner")
    await asyncio.wait_for(publisher_start_entered.wait(), timeout=1.0)
    owner.cancel()
    await asyncio.wait_for(publisher_stop_entered.wait(), timeout=1.0)

    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    assert not owner.done()
    assert len(publishers) == 1
    assert publishers[0].applied_cold_stage_channel == "cold"
    assert publishers[0].stop_cancelled is False
    assert publishers[0].stop_completed is False
    assert engine._pub is publishers[0]

    release_publisher_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=1.0)

    assert publishers[0].stop_completed is True
    assert publishers[0].stop_cancelled is False
    assert source.stop_calls == 1
    assert engine._runtime_ownership_present() is False
    assert engine._pub is None
    assert engine._pub_queue is None
    assert engine._broker is None
    assert engine._source is None


def _write_curve_json(path: Path) -> None:
    t = np.linspace(0, 10, 60).tolist()
    T_cold = (np.linspace(290, 4, 60)).tolist()
    T_warm = (np.linspace(300, 10, 60)).tolist()
    path.write_text(
        json.dumps({"t_hours": t, "T_cold": T_cold, "T_warm": T_warm, "name": "test"}),
        encoding="utf-8",
    )


def _write_sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    base = time.time()
    for i in range(20):
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (base + i, "Т12", 290.0 - i * 2, "K", "ok", "test"),
        )
    conn.commit()
    conn.close()


def _write_empty_readings_db(path: Path) -> None:
    """SQLite file with valid readings schema but zero rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    conn.commit()
    conn.close()


def _write_readings_db(path: Path, *, ts_start: float, n_rows: int) -> None:
    """SQLite file with n_rows of readings starting at ts_start (POSIX seconds)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    for i in range(n_rows):
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (ts_start + i, "Т12", 290.0 - i * 2, "K", "ok", "test"),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Source resolution — no ZMQ required
# ---------------------------------------------------------------------------


def test_resolve_source_sqlite(tmp_path):
    db = tmp_path / "data_2026-01-01.db"
    _write_sqlite_db(db)
    src = resolve_source(db)
    assert isinstance(src, SQLiteReplay)


def test_resolve_source_curve_json(tmp_path):
    j = tmp_path / "curve.json"
    _write_curve_json(j)
    src = resolve_source(j)
    assert isinstance(src, CurveReplay)


def test_resolve_source_directory(tmp_path):
    db = tmp_path / "data_2026-01-01.db"
    _write_sqlite_db(db)
    src = resolve_source(tmp_path)
    assert isinstance(src, DirectoryReplay)


def test_resolve_source_invalid_json_raises(tmp_path):
    j = tmp_path / "bad.json"
    j.write_text('{"foo": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="t_hours"):
        resolve_source(j)


def test_resolve_source_unsupported_suffix_raises(tmp_path):
    p = tmp_path / "file.csv"
    p.write_text("a,b", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_source(p)


# ---------------------------------------------------------------------------
# ZMQ integration — engine on isolated test ports
# ---------------------------------------------------------------------------


async def _start_engine_with_curve(tmp_path: Path):
    """Start ReplayEngine with a curve fixture; return (engine, source_task)."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(
        j,
        speed=0.0,
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
    )
    await engine.start()
    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    return engine, source_task


async def _stop_engine(engine, source_task) -> None:
    await engine.stop()
    source_task.cancel()
    try:
        await source_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_replay_engine_first_reading_pub(tmp_path):
    """PUB socket delivers the first msgpack-encoded reading within 2 s.

    This directly tests that the engine publishes readings on the ZMQ PUB
    socket, which is the precondition for bridge sub_drain_loop heartbeats.

    Subscribe BEFORE creating the source task to mitigate the ZMQ slow-joiner
    race (same pattern as test_replay_engine_curve_data_pub).
    """
    import msgpack

    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(
        j,
        speed=0.0,
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
    )
    await engine.start()

    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    await asyncio.sleep(0.05)  # Let ZMQ subscription establish before source.

    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    try:
        parts = await asyncio.wait_for(sub.recv_multipart(), timeout=2.0)
        assert len(parts) == 2, f"Expected [topic, payload], got {len(parts)} parts"
        assert parts[0] == b"readings"
        # Payload must be a valid msgpack-encoded reading dict with required fields
        data = msgpack.unpackb(parts[1], raw=False)
        assert "ch" in data, f"Reading missing 'ch' field: {data}"
        assert "v" in data, f"Reading missing 'v' field: {data}"
        assert isinstance(data["v"], (int, float)), f"'v' must be numeric: {data}"
    finally:
        sub.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_transport_rejects_live_safety_and_marks_legacy_status_unavailable(tmp_path):
    """Real REP transport must never invent live safety or an empty alarm set."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 2000)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "safety_status"}')
        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = json.loads(raw)
        assert reply == {
            "ok": False,
            "available": False,
            "reason": "REPLAY_MODE_READONLY",
            "proto": 2,
        }

        await req.send_string('{"cmd": "/status"}')
        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        status = json.loads(raw)
        assert status["ok"] is True
        assert status["mode"] == "replay"
        assert status["safety_state"] is None
        assert status["safety_available"] is False
        assert status["safety_unavailable_reason"] == "REPLAY_MODE_READONLY"
        assert status["alarms"] is None
        assert status["alarms_available"] is False
        assert status["alarms_unavailable_reason"] == "REPLAY_MODE_READONLY"
        assert "active_experiment" in status

        await req.send_string('{"cmd": "experiment_status"}')
        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        experiment = json.loads(raw)
        assert experiment["ok"] is True
        assert experiment["app_mode"] == "replay"
        assert experiment["current_phase"] == "cooldown"
        assert "replay_source" in experiment
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_safe_endpoint_proves_exact_session_and_never_grants_live_authority(tmp_path) -> None:
    from cryodaq.core.zmq_bridge import PROTOCOL_VERSION
    from cryodaq.replay_engine.server import ReplayEngine

    source = tmp_path / "curve.json"
    _write_curve_json(source)
    engine = ReplayEngine(
        source,
        speed=0.0,
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
        launcher_ready_nonce="a" * 64,
        launcher_session_id="b" * 32,
    )
    await engine.start()
    context = zmq.asyncio.Context()
    safe = context.socket(zmq.REQ)
    safe.setsockopt(zmq.LINGER, 0)
    safe.setsockopt(zmq.RCVTIMEO, 2000)
    safe.connect(_TEST_SAFE_CMD)
    receipt = {
        "schema": "cryodaq.replay_ready.v2",
        "nonce": "a" * 64,
        "session_id": "b" * 32,
        "mode": "replay",
        "source": str(source),
        "speed": 0.0,
        "pid": os.getpid(),
        "pub_addr": _TEST_PUB,
        "cmd_addr": _TEST_CMD,
        "safe_cmd_addr": _TEST_SAFE_CMD,
    }
    safe_direction_commands = (
        {"cmd": "keithley_emergency_off", "channel": "smua"},
        {"cmd": "keithley_emergency_off"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "c" * 32,
            "request_id": "d" * 32,
            "shutdown_capability": "e" * 64,
        },
    )
    try:
        await safe.send_json({"cmd": "replay_ready", **receipt})
        assert await asyncio.wait_for(safe.recv_json(), timeout=2.0) == {
            "ok": True,
            **receipt,
            "proto": PROTOCOL_VERSION,
        }
        for command in safe_direction_commands:
            await safe.send_json(command)
            assert await asyncio.wait_for(safe.recv_json(), timeout=2.0) == {
                "ok": False,
                "reason": "REPLAY_MODE_READONLY",
                "proto": PROTOCOL_VERSION,
            }
    finally:
        safe.close(linger=0)
        context.term()
        await engine.stop()


@pytest.mark.parametrize(
    ("pub_addr", "cmd_addr", "safe_cmd_addr"),
    [
        ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5555", "tcp://127.0.0.1:5558"),
        ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5556", "tcp://127.0.0.1:5556"),
        ("tcp://127.0.0.1:5555", "tcp://127.0.0.1:5556", "tcp://127.0.0.1:5555"),
    ],
)
def test_replay_rejects_any_overlapping_transport_addresses(
    tmp_path: Path,
    pub_addr: str,
    cmd_addr: str,
    safe_cmd_addr: str,
) -> None:
    from cryodaq.replay_engine.server import ReplayEngine

    with pytest.raises(ValueError, match="aliases the independent"):
        ReplayEngine(
            tmp_path / "curve.json",
            pub_addr=pub_addr,
            cmd_addr=cmd_addr,
            safe_cmd_addr=safe_cmd_addr,
        )


@pytest.mark.asyncio
async def test_replay_engine_current_phase(tmp_path):
    """REP current_phase returns the configured phase."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(
        j,
        speed=0.0,
        phase="measurement",
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
    )
    await engine.start()
    source_task = asyncio.create_task(engine.run_source())
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "current_phase"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is True
        assert reply["phase"] == "measurement"
        assert "phase_started_at" in reply
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_rejects_set_target(tmp_path):
    """Hardware commands return ok=False, reason=REPLAY_MODE_READONLY."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "set_target", "channel": "T11", "value": 4.2}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["reason"] == "REPLAY_MODE_READONLY"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_ordinary_endpoint_rejects_safe_direction_before_dispatch(tmp_path):
    """Safe actions never enter replay through the ordinary command lane."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "keithley_emergency_off"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["error_code"] == "command_endpoint_action_rejected"
        assert reply["delivery_state"] == "not_dispatched"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_curve_data_pub(tmp_path):
    """Curve replay PUBs >=10 readings containing BOTH Т11 and Т12 channels
    with numeric temperature values in the expected cooldown range.

    SUB must subscribe and establish connection BEFORE source_task starts,
    otherwise speed=0.0 publishes all readings before the slow-joiner connects.

    Uses a readiness loop (poll until both channels seen or deadline) instead
    of a fixed sleep so the test passes quickly on fast machines and doesn't
    flake on slow ones.
    """
    import msgpack

    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(
        j,
        speed=0.0,
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
    )
    await engine.start()

    # Subscribe before source task so all readings are seen (slow-joiner fix).
    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    # Readiness loop: poll until ZMQ subscription is established before source starts.
    # We don't know exactly when the subscription handshake completes, so we yield
    # the event loop a few times rather than sleeping a fixed amount.
    for _ in range(5):
        await asyncio.sleep(0.01)

    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    readings = []
    try:
        deadline = asyncio.get_event_loop().time() + 3.0
        while len(readings) < 10:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                parts = await asyncio.wait_for(sub.recv_multipart(), timeout=remaining)
                if len(parts) == 2:
                    data = msgpack.unpackb(parts[1], raw=False)
                    readings.append(data)
            except TimeoutError:
                break
    finally:
        sub.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)

    assert len(readings) >= 10, f"Expected >=10 readings, got {len(readings)}"

    channels = {r["ch"] for r in readings}
    # Both cold and warm channels must be present — one channel passing is insufficient
    assert {"Т12", "Т11"} <= channels, f"Expected both Т11 and Т12 channels in published readings, got: {channels}"

    # Verify decoded values are numeric and in physically plausible range (4K–300K)
    for r in readings:
        assert "v" in r, f"Reading missing 'v' field: {r}"
        assert isinstance(r["v"], (int, float)), f"'v' must be numeric: {r}"
        assert 4.0 <= r["v"] <= 305.0, (
            f"Temperature value {r['v']} out of expected range [4, 305] K for channel {r['ch']}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "alarm_v2_status",
        "cooldown_alarm.status",
        "annunciation_status",
        "alarm_v2_ack",
        "annunciation_ack",
    ],
)
async def test_replay_engine_explicitly_rejects_live_alarm_endpoints(action: str) -> None:
    from cryodaq.replay_engine.server import ReplayEngine

    engine = object.__new__(ReplayEngine)

    assert await engine._handle_command({"cmd": action}) == {
        "ok": False,
        "reason": "REPLAY_MODE_READONLY",
    }


@pytest.mark.asyncio
async def test_replay_engine_experiment_status(tmp_path):
    """experiment_status returns ok=True with app_mode=replay and configured phase."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(
        j,
        speed=0.0,
        phase="cooldown",
        pub_addr=_TEST_PUB,
        cmd_addr=_TEST_CMD,
        safe_cmd_addr=_TEST_SAFE_CMD,
    )
    await engine.start()
    source_task = asyncio.create_task(engine.run_source())
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "experiment_status"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is True
        assert reply["app_mode"] == "replay"
        assert "replay_source" in reply
        assert "replay_speed" in reply
        assert reply["active_experiment"] is None
        assert reply["current_phase"] == "cooldown"
        assert "phase_started_at" in reply
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_cooldown_history_unavailable(tmp_path):
    """/cooldown_history_get returns predictor_unavailable_in_replay before Stage 5."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "cooldown_history_get"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["reason"] == "predictor_unavailable_in_replay"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


# ---------------------------------------------------------------------------
# DirectoryReplay base_offset edge cases (Stage 4c, P2-B fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_directory_replay_skips_empty_first_file(tmp_path):
    """Empty first DB must not collapse global_base_offset to 0.0."""
    from cryodaq.drivers.base import Reading

    # First file: empty SQLite with valid schema, zero rows
    empty_db = tmp_path / "data_2026-01-01.db"
    _write_empty_readings_db(empty_db)

    # Second file: rows with old (2023) timestamps
    full_db = tmp_path / "data_2026-01-02.db"
    _write_readings_db(full_db, ts_start=1672531200.0, n_rows=5)

    replay = DirectoryReplay(tmp_path, speed=1000.0, loop=False)
    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    await replay.run(cb)

    assert len(received) == 5
    # Confirm timestamps shifted to wall-clock now (not original 2023)
    from datetime import UTC, datetime

    now_ts = datetime.now(tz=UTC).timestamp()
    for r in received:
        delta = abs(r.timestamp.timestamp() - now_ts)
        assert delta < 60, f"Reading timestamp {r.timestamp} not shifted to now: delta={delta}s expected <60s"


@pytest.mark.asyncio
async def test_directory_replay_all_empty_returns_cleanly(tmp_path, caplog):
    """All-empty directory returns without crashing or publishing."""
    import logging

    from cryodaq.drivers.base import Reading

    _write_empty_readings_db(tmp_path / "data_2026-01-01.db")
    _write_empty_readings_db(tmp_path / "data_2026-01-02.db")

    replay = DirectoryReplay(tmp_path, speed=1000.0, loop=False)
    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    with caplog.at_level(logging.WARNING, logger="cryodaq.replay_engine.sources"):
        await replay.run(cb)

    assert len(received) == 0
    assert any("all data_*.db files" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# NaN-доктрина: replay-engine read path masks sentinel/error rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_replay_masks_nonfinite(tmp_path):
    """A stored sentinel / non-OK status / legacy raw ±inf must republish as
    NaN, never as the sentinel or a raw number, when the replay engine
    reconstructs Reading objects from a daily SQLite file."""
    import math

    from cryodaq.drivers.base import Reading
    from cryodaq.storage.sentinel import SENTINEL

    db = tmp_path / "data_2026-01-01.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    base = time.time()
    conn.execute("INSERT INTO readings VALUES (?,?,?,?,?,?)", (base, "Т12", 290.0, "K", "ok", "test"))
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (base + 1, "Т12", SENTINEL, "K", "sensor_error", "test"),
    )
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (base + 2, "Т12", float("inf"), "K", "overrange", "test"),  # legacy raw inf
    )
    conn.commit()
    conn.close()

    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    src = SQLiteReplay(db, speed=1000.0, loop=False)
    await src.run(cb, base_offset=0.0)

    vals = [r.value for r in received]
    assert 290.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"


@pytest.mark.asyncio
async def test_sqlite_replay_uppercase_status_masks(tmp_path):
    """A legacy uppercase non-OK status ("SENSOR_ERROR") with a finite value must
    case-fold back to its ChannelStatus and republish as NaN, not escape as OK."""
    import math

    from cryodaq.drivers.base import ChannelStatus, Reading

    db = tmp_path / "data_2026-01-01.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (time.time(), "Т12", 123.0, "K", "SENSOR_ERROR", "test"),
    )
    conn.commit()
    conn.close()

    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    src = SQLiteReplay(db, speed=1000.0, loop=False)
    await src.run(cb, base_offset=0.0)

    assert len(received) == 1
    assert received[0].status is ChannelStatus.SENSOR_ERROR, "uppercase status must reconstruct"
    assert math.isnan(received[0].value), "non-OK status must mask finite value as NaN"


# ---------------------------------------------------------------------------
# F28: DirectoryReplay is archive-aware — rotated (cold) days replay too
# ---------------------------------------------------------------------------


def _write_day_via_writer(data_dir: Path, readings: list) -> None:
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    w = SQLiteWriter(data_dir)
    w._write_batch(readings)
    if w._conn is not None:
        w._conn.close()
    w._conn = None


@pytest.mark.asyncio
async def test_directory_replay_includes_rotated_day(tmp_path):
    """A day rotated to Parquet (SQLite deleted) still replays, in day order,
    sharing the one monotonic time origin with the surviving hot day."""
    pytest.importorskip("pyarrow")
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)
    recent_day = today - timedelta(days=1)

    def rdg(ch, val, ts, status=ChannelStatus.OK):
        return Reading(timestamp=ts, instrument_id="ls218s", channel=ch, value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 200.0, old_day.replace(hour=12)), rdg("Т12", 180.0, old_day.replace(hour=13))],
    )
    _write_day_via_writer(data_dir, [rdg("Т11", 90.0, recent_day.replace(hour=12))])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    assert len(received) == 3, f"cold + hot rows must all replay, got {len(received)}"
    assert sorted(r.value for r in received) == pytest.approx([90.0, 180.0, 200.0])
    assert {"Т12", "Т11"} <= {r.channel for r in received}

    # One monotonic origin across the union: timestamps ascend, first ~now.
    ts_list = [r.timestamp.timestamp() for r in received]
    assert ts_list == sorted(ts_list), "timestamps must stay monotonic across cold+hot"
    now_ts = datetime.now(tz=UTC).timestamp()
    assert abs(min(ts_list) - now_ts) < 120, "earliest replayed row must be shifted to ~now"


@pytest.mark.asyncio
async def test_directory_replay_cold_day_masks_sentinel(tmp_path):
    """A sentinel/error row in a cold (rotated) day republishes as NaN."""
    pytest.importorskip("pyarrow")
    import math
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService
    from cryodaq.storage.sentinel import SENTINEL

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)

    def rdg(val, ts, status):
        return Reading(timestamp=ts, instrument_id="ls218s", channel="Т12", value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [
            rdg(200.0, old_day.replace(hour=12), ChannelStatus.OK),
            rdg(float("nan"), old_day.replace(hour=13), ChannelStatus.SENSOR_ERROR),
        ],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    vals = [r.value for r in received]
    assert 200.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    bad = [r for r in received if r.status is ChannelStatus.SENSOR_ERROR]
    assert bad and all(math.isnan(r.value) for r in bad), "cold sentinel row must present as NaN"


@pytest.mark.asyncio
async def test_directory_replay_overlap_day_unions_hot_and_cold(tmp_path):
    """F4: a day in BOTH the archive and a restored hot .db replays union+dedup.

    Old code did cold_days = archived − hot, so an overlap day (restored /
    backdated hot DB for an archived day) fell to the hot-only SQLiteReplay path
    and the archived rows vanished. query_rows already unions+dedups both
    sources; the overlap day must route through it.
    """
    pytest.importorskip("pyarrow")
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)

    def rdg(ch, val, ts, status=ChannelStatus.OK):
        return Reading(timestamp=ts, instrument_id="ls218s", channel=ch, value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 200.0, old_day.replace(hour=12)), rdg("Т12", 180.0, old_day.replace(hour=13))],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    # Restore a hot DB for the SAME archived day: exact-dup hour13 + new hour14.
    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 180.0, old_day.replace(hour=13)), rdg("Т12", 150.0, old_day.replace(hour=14))],
    )
    assert (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    vals = sorted(r.value for r in received)
    # Archived-only 200.0 present (RED discriminator), restored 150.0 present,
    # shared 180.0 exactly once (dedup) → 3 rows total.
    assert vals == pytest.approx([150.0, 180.0, 200.0]), f"union/dedup wrong: {vals}"
    assert len(received) == 3
