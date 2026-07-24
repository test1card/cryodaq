"""Real process, thread, queue-owner, and lock proof for launcher shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import socket
import subprocess
import sys
import threading
from dataclasses import MISSING, fields
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.command_authority import (
    is_exact_safe_direction_envelope,
    is_ordinary_command_endpoint_admitted,
)
from cryodaq.core.zmq_bridge import (
    CommandAuthorityRegistry,
    ZMQCommandIngressPair,
    ZMQCommandServer,
)
from cryodaq.engine import (
    EngineCommandContext,
    _handle_gui_command,
    _request_teardown_after_shutdown_receipt,
)
from cryodaq.gui.zmq_client import ZmqBridge
from cryodaq.instance_lock import release_lock_exact, try_acquire_lock
from cryodaq.launcher import LauncherWindow, _pump_engine_stderr


class _Timer:
    def stop(self) -> None:
        return None


class _ThreadWorker:
    """Small QThread-shaped owner backed by a real non-daemon thread."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, name="launcher-safety-worker")
        self.thread.start()

    def isFinished(self) -> bool:  # noqa: N802 - mirrors QThread
        return not self.thread.is_alive()

    def wait(self, timeout_ms: int) -> None:
        self.thread.join(timeout_ms / 1000)


class _Bridge:
    def __init__(self, worker: _ThreadWorker, engine: subprocess.Popen[bytes]) -> None:
        self.worker = worker
        self.engine = engine
        self.shutdown_calls = 0
        self.close_calls = 0
        self.receipt_sent = False

    def send_command(self, command: dict[str, str]) -> dict[str, object]:
        assert set(command) == {"cmd", "engine_instance_id", "request_id", "shutdown_capability"}
        assert command["cmd"] == "launcher_shutdown"
        assert command["engine_instance_id"] == "a" * 32
        assert command["shutdown_capability"] == "b" * 64
        assert self.engine.stdin is not None
        self.engine.stdin.write(b"x")
        self.engine.stdin.flush()
        self.receipt_sent = True
        return {
            "ok": True,
            "schema": "cryodaq.engine_shutdown.v1",
            "engine_instance_id": command["engine_instance_id"],
            "request_id": command["request_id"],
            "global_off_verified": True,
            "teardown_requested": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
            "proto": 2,
        }

    def shutdown(self) -> None:
        assert self.receipt_sent
        assert self.engine.poll() == 0
        self.shutdown_calls += 1
        self.worker.release.set()

    def close(self) -> None:
        if not self.worker.isFinished():
            raise RuntimeError("worker was not settled before bridge terminal close")
        self.close_calls += 1


def _sleeping_process(*, stderr: bool = False, graceful: bool = False) -> subprocess.Popen[bytes]:
    script = (
        "import sys; sys.stderr.write('ready\\n'); sys.stderr.flush(); sys.stdin.buffer.read(1)"
        if graceful
        else "import sys,time; sys.stderr.write('ready\\n'); sys.stderr.flush(); time.sleep(60)"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE if graceful else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE if stderr else subprocess.DEVNULL,
    )


def _settle_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _free_tcp_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        host, port = probe.getsockname()
    return f"tcp://{host}:{port}"


def _shutdown_context() -> EngineCommandContext:
    required: dict[str, object] = {}
    for item in fields(EngineCommandContext):
        if item.default is MISSING and item.default_factory is MISSING:
            required[item.name] = MagicMock(name=item.name)
    context = EngineCommandContext(**required)
    context.engine_instance_id = "a" * 32
    context.shutdown_capability = "b" * 64
    context.shutdown_event = asyncio.Event()
    context.mutation_capability_token = "m" * 32
    return context


async def test_launcher_retains_command_path_until_exact_shutdown_receipt() -> None:
    engine = _sleeping_process(stderr=True, graceful=True)
    assert engine.stderr is not None
    stderr_logger = logging.getLogger("cryodaq.test.real-shutdown-chain")
    stderr_logger.propagate = False
    stderr_handler = logging.NullHandler()
    stderr_logger.addHandler(stderr_handler)
    stderr_thread = threading.Thread(
        target=_pump_engine_stderr,
        args=(engine.stderr, stderr_logger),
        name="real-shutdown-stderr-pump",
        daemon=True,
    )
    stderr_thread.start()
    context = _shutdown_context()
    off_started = asyncio.Event()
    release_off = asyncio.Event()

    async def delayed_off(*, channel: str | None = None) -> dict[str, object]:
        assert channel is None
        off_started.set()
        await release_off.wait()
        return {"ok": True, "active_channels": []}

    context.safety_manager.emergency_off = AsyncMock(side_effect=delayed_off)
    address = _free_tcp_address()
    safe_address = _free_tcp_address()

    def receipt_sent(command: dict[str, object], reply: dict[str, object]) -> None:
        _request_teardown_after_shutdown_receipt(context, command, reply)
        if (
            command.get("cmd") == "launcher_shutdown"
            and context.shutdown_event is not None
            and context.shutdown_event.is_set()
            and engine.poll() is None
        ):
            assert engine.stdin is not None
            engine.stdin.write(b"x")
            engine.stdin.flush()
            engine.stdin.close()

    authority_registry = CommandAuthorityRegistry()
    ordinary_server = ZMQCommandServer(
        address=address,
        handler=functools.partial(_handle_gui_command, context=context),
        reply_sent_callback=receipt_sent,
        authority_registry=authority_registry,
        accepted_command_predicate=is_ordinary_command_endpoint_admitted,
    )
    safe_server = ZMQCommandServer(
        address=safe_address,
        handler=functools.partial(_handle_gui_command, context=context),
        reply_sent_callback=receipt_sent,
        authority_registry=authority_registry,
        accepted_actions=frozenset({"engine_ready", "keithley_emergency_off", "launcher_shutdown"}),
        accepted_command_predicate=is_exact_safe_direction_envelope,
    )
    command_ingress = ZMQCommandIngressPair(ordinary=ordinary_server, safe=safe_server)
    bridge = ZmqBridge(
        pub_addr=_free_tcp_address(),
        cmd_addr=address,
        assistant_cmd_addr=_free_tcp_address(),
        safe_cmd_addr=safe_address,
    )
    host = SimpleNamespace(
        _engine_proc=engine,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability="b" * 64,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_unsettled_incarnation=None,
        _bridge=bridge,
        _engine_stderr_thread=stderr_thread,
        _engine_stderr_logger=stderr_logger,
        _engine_stderr_handler=stderr_handler,
    )
    host._close_engine_stderr_stream = MethodType(LauncherWindow._close_engine_stderr_stream, host)
    stop_task: asyncio.Task[None] | None = None
    mutation_task: asyncio.Task[dict[str, object]] | None = None
    await command_ingress.start()
    bridge.start()
    try:
        # Keep the authority-mismatch assertion independent from the shared
        # transport quarantine exercised by the command-server partition.  A
        # handler-level not-dispatched settlement deliberately cannot clear a
        # transport registry whose application dispatch already occurred.
        mismatch = await _handle_gui_command(
            {
                "cmd": "launcher_shutdown",
                "engine_instance_id": "a" * 32,
                "request_id": "d" * 32,
                "shutdown_capability": "e" * 64,
            },
            context=context,
        )
        assert mismatch["error_code"] == "launcher_shutdown_authority_mismatch"
        assert context.shutdown_request_id is None
        context.safety_manager.emergency_off.assert_not_awaited()

        stop_task = asyncio.create_task(asyncio.to_thread(LauncherWindow._stop_engine, host))
        await asyncio.wait_for(off_started.wait(), timeout=5)
        mutation_task = asyncio.create_task(
            asyncio.to_thread(
                bridge.send_command,
                {"cmd": "keithley_start", "channel": "smua"},
            )
        )
        await asyncio.sleep(0.1)
        assert not stop_task.done()
        mutation_reply = await asyncio.wait_for(mutation_task, timeout=5)
        assert mutation_reply["error_code"] == "engine_shutdown_latched"
        assert mutation_reply["delivery_state"] == "dispatched"
        assert mutation_reply["commit_state"] == "not_committed"
        assert mutation_reply["retry_safe"] is False
        assert engine.poll() is None
        assert stderr_thread.is_alive()
        assert context.shutdown_event is not None
        assert not context.shutdown_event.is_set()

        release_off.set()
        await asyncio.wait_for(stop_task, timeout=10)
        assert context.safety_manager.emergency_off.await_count == 1
        assert context.shutdown_event.is_set()
        assert engine.poll() == 0
        assert host._engine_proc is None
        assert host._engine_stderr_thread is None
        assert not stderr_thread.is_alive()
    finally:
        release_off.set()
        if stop_task is not None and not stop_task.done():
            stop_task.cancel()
        if mutation_task is not None and not mutation_task.done():
            mutation_task.cancel()
        bridge.close()
        await command_ingress.stop()
        _settle_process(engine)
        if engine.stdin is not None and not engine.stdin.closed:
            with contextlib.suppress(OSError):
                engine.stdin.close()
        stderr_thread.join(timeout=3)
        if stderr_handler in stderr_logger.handlers:
            stderr_logger.removeHandler(stderr_handler)
        stderr_handler.close()


@pytest.mark.parametrize("iteration", range(3))
def test_real_launcher_shutdown_settles_every_owner_before_releasing_lock(tmp_path, iteration: int) -> None:
    lock_name = f".launcher-{iteration}.lock"
    lock_fd = try_acquire_lock(lock_name, lock_dir=tmp_path)
    assert lock_fd is not None
    replacement_fd: int | None = None
    engine: subprocess.Popen[bytes] | None = None
    assistant: subprocess.Popen[bytes] | None = None
    worker = _ThreadWorker()
    loop = asyncio.new_event_loop()
    handler = logging.NullHandler()
    stderr_logger = logging.getLogger(f"cryodaq.test.shutdown.{iteration}")
    stderr_logger.propagate = False
    stderr_logger.addHandler(handler)
    stderr_thread: threading.Thread | None = None

    try:
        engine = _sleeping_process(stderr=True, graceful=True)
        assert engine.stderr is not None
        stderr_thread = threading.Thread(
            target=_pump_engine_stderr,
            args=(engine.stderr, stderr_logger),
            name="engine-stderr-pump",
            daemon=True,
        )
        stderr_thread.start()
        assistant = _sleeping_process()
        bridge = _Bridge(worker, engine)
        app = MagicMock(name="application")
        tray = MagicMock(name="tray")
        host = SimpleNamespace(
            _shutdown_requested=False,
            _restart_pending=True,
            _assistant_restart_pending=True,
            _health_timer=_Timer(),
            _data_timer=_Timer(),
            _status_timer=_Timer(),
            _async_timer=_Timer(),
            _tray=tray,
            _tray_icon_red=None,
            _tray_icon_yellow=None,
            _stop_engine_down_alarm=lambda: None,
            _invalidate_descriptor_transport=lambda: None,
            _invalidate_engine_producer=lambda: None,
            _snapshot_ingress=None,
            _assistant_proc=assistant,
            _assistant_shutdown_path=None,
            _assistant_shutdown_authority=None,
            _bridge=bridge,
            _safety_worker=worker,
            _engine_proc=engine,
            _engine_external=False,
            _replay_source=None,
            _engine_instance_id="a" * 32,
            _engine_shutdown_capability="b" * 64,
            _engine_shutdown_request_id=None,
            _engine_shutdown_receipt=None,
            _engine_stderr_thread=stderr_thread,
            _engine_stderr_logger=stderr_logger,
            _engine_stderr_handler=handler,
            _soak_artifact_capability=None,
            _soak_bridge_handshake=None,
            _loop=loop,
            _app=app,
        )
        host._stop_assistant = MethodType(LauncherWindow._stop_assistant, host)
        host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
        host._close_engine_stderr_stream = MethodType(LauncherWindow._close_engine_stderr_stream, host)

        assert try_acquire_lock(lock_name, lock_dir=tmp_path) is None
        assert LauncherWindow._do_shutdown(host) is True

        assert assistant.poll() is not None
        assert engine.poll() is not None
        assert not worker.thread.is_alive()
        assert not stderr_thread.is_alive()
        assert host._safety_worker is None
        assert host._engine_stderr_thread is None
        assert bridge.shutdown_calls == 1
        assert bridge.close_calls == 1
        assert loop.is_closed()
        app.quit.assert_called_once_with()
        tray.hide.assert_called_once_with()

        # The launcher lock belongs to main(), outside LauncherWindow. It must
        # remain held even after owner settlement until the Qt loop returns.
        assert try_acquire_lock(lock_name, lock_dir=tmp_path) is None
        release_lock_exact(lock_fd, lock_name, lock_dir=tmp_path)
        lock_fd = None
        replacement_fd = try_acquire_lock(lock_name, lock_dir=tmp_path)
        assert replacement_fd is not None
    finally:
        worker.release.set()
        worker.thread.join(timeout=3)
        _settle_process(assistant)
        _settle_process(engine)
        if stderr_thread is not None:
            stderr_thread.join(timeout=3)
        if handler in stderr_logger.handlers:
            stderr_logger.removeHandler(handler)
            handler.close()
        if replacement_fd is not None:
            release_lock_exact(replacement_fd, lock_name, lock_dir=tmp_path)
        if lock_fd is not None:
            release_lock_exact(lock_fd, lock_name, lock_dir=tmp_path)


def test_timed_out_engine_is_force_reaped_while_exact_settlement_remains_hold() -> None:
    class TimedOutProcess:
        pid = 41_999

        def __init__(self) -> None:
            self.state = "running"
            self.wait_timeouts: list[int] = []
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self) -> int | None:
            return -9 if self.state == "killed" else None

        def wait(self, timeout: int) -> int:
            self.wait_timeouts.append(timeout)
            if self.state == "killed":
                return -9
            raise subprocess.TimeoutExpired("engine", timeout)

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.state = "terminated"

        def kill(self) -> None:
            self.kill_calls += 1
            self.state = "killed"

    process = TimedOutProcess()
    request_id = "c" * 32
    close_stream = MagicMock()
    bridge = MagicMock()
    host = SimpleNamespace(
        _engine_proc=process,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability="b" * 64,
        _engine_shutdown_request_id=request_id,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_receipt={
            "ok": True,
            "schema": "cryodaq.engine_shutdown.v1",
            "engine_instance_id": "a" * 32,
            "request_id": request_id,
            "global_off_verified": True,
            "teardown_requested": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
            "proto": 2,
        },
        _engine_unsettled_incarnation=None,
        _restart_giving_up=False,
        _bridge=bridge,
        _close_engine_stderr_stream=close_stream,
    )

    with pytest.raises(RuntimeError, match="forced death was reaped but is not exact settlement"):
        LauncherWindow._stop_engine(host)

    assert process.wait_timeouts == [60, 5, 5]
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert host._engine_proc is None
    assert host._engine_unsettled_incarnation == ("a" * 32, -9)
    assert host._restart_giving_up is True
    close_stream.assert_called_once_with()
    bridge.send_command.assert_not_called()

    with pytest.raises(RuntimeError, match="permanent HOLD"):
        LauncherWindow._stop_engine(host)
    assert process.terminate_calls == 1
    assert process.kill_calls == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows child-death contract")
def test_windows_child_death_without_shutdown_receipt_is_hold() -> None:
    process = _sleeping_process()
    try:
        process.terminate()
        process.wait(timeout=3)
        bridge = MagicMock()
        host = SimpleNamespace(
            _engine_proc=process,
            _engine_external=False,
            _replay_source=None,
            _engine_instance_id="a" * 32,
            _engine_shutdown_capability="b" * 64,
            _engine_shutdown_request_id=None,
            _engine_shutdown_receipt=None,
            _bridge=bridge,
            _close_engine_stderr_stream=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="died without an exact shutdown receipt"):
            LauncherWindow._stop_engine(host)

        assert host._engine_proc is process
        bridge.shutdown.assert_not_called()
        host._close_engine_stderr_stream.assert_not_called()
    finally:
        _settle_process(process)
