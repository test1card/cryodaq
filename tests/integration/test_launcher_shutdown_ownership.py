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
import time
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


def _verified_global_off_result() -> dict[str, object]:
    return {
        "ok": True,
        "active_channels": [],
        "off_evidence": {
            "off_tier": "verified_off",
            "channel_off_results": {
                "smua": "device_reported_off",
                "smub": "device_reported_off",
            },
            "verified_off": True,
        },
    }


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
            "schema": "cryodaq.engine_shutdown.v3",
            "engine_instance_id": command["engine_instance_id"],
            "request_id": command["request_id"],
            "off_evidence": _verified_global_off_result()["off_evidence"],
            "operator_physical_disconnect": False,
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


def _delayed_exit_engine_process() -> subprocess.Popen[bytes]:
    """A graceful engine whose exit lags its stdin signal by a short delay.

    ``_stop_engine``'s shutdown worker receives its ZMQ reply through
    ``ZmqBridge``'s real subprocess + reply-consumer-thread relay (see
    ``ZmqBridge.start()``: "Start the ZMQ bridge subprocess"), while this
    test's ``receipt_sent`` callback closes the engine's stdin synchronously,
    in-process, the instant the reply is handed back to the command server.
    An immediate-exit script (as ``_sleeping_process(graceful=True)`` uses
    elsewhere) therefore reliably reaps *before* the worker's own reply has
    finished that longer round-trip -- not a rare flake, a 100%-reproducible
    ordering under this test's topology -- tripping the unrelated "engine
    child died without an exact shutdown receipt" path instead of the
    command-path-retention behaviour this test exists to prove. A short,
    fixed delay after the stdin signal is read restores the realistic
    ordering (a real engine's teardown is not instantaneous either) without
    weakening any assertion below: every state this test checks is still
    read from the exact same production code path.
    """

    script = (
        "import sys, time; sys.stderr.write('ready\\n'); sys.stderr.flush(); sys.stdin.buffer.read(1); time.sleep(0.5)"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
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
    """The command path stays retained until an exact receipt lands.

    ``_stop_engine`` is no longer a single call that blocks for the whole
    round-trip (see ``_EngineShutdownWorker``): it dispatches the shutdown
    command on a background worker, waits a short bounded grace period, and
    -- if the reply has not landed -- raises a HOLD error and returns control
    to the caller instead of blocking. A caller therefore has to drive it in
    a retry loop, exactly as the real ``_schedule_shutdown_retry`` ladder
    does. What must still hold, and what this test exists to prove, is the
    property in its name: the command path (the dispatched worker, the
    bridge, the latched server-side authority) is retained -- never
    re-dispatched, never released -- across every one of those retries,
    until the receipt is exact.
    """

    engine = _delayed_exit_engine_process()
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
        return _verified_global_off_result()

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
        _engine_shutdown_worker=None,
        _engine_shutdown_wait_deadline=None,
        _bridge=bridge,
        _engine_stderr_thread=stderr_thread,
        _engine_stderr_logger=stderr_logger,
        _engine_stderr_handler=stderr_handler,
    )
    host._close_engine_stderr_stream = MethodType(LauncherWindow._close_engine_stderr_stream, host)

    # Count only launcher_shutdown dispatches (a concurrent mutation below
    # also calls bridge.send_command, for a different command, and must not
    # be conflated with a re-dispatch of the shutdown worker).
    launcher_shutdown_dispatch_count = 0
    real_send_command = bridge.send_command

    def counting_send_command(command: dict[str, object]) -> dict[str, object]:
        nonlocal launcher_shutdown_dispatch_count
        if command.get("cmd") == "launcher_shutdown":
            launcher_shutdown_dispatch_count += 1
        return real_send_command(command)

    bridge.send_command = counting_send_command

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

        # First call: dispatches the worker, waits the bounded
        # _ENGINE_SHUTDOWN_WORKER_GRACE_MS grace period (the reply cannot
        # land yet -- emergency_off is parked on release_off), and returns.
        # A non-blocking _stop_engine cannot hold a caller pending for ~5s
        # by construction; the fast, bounded HOLD below is what replaces it.
        first_call_started = time.monotonic()
        with pytest.raises(RuntimeError, match="awaiting its reply"):
            await asyncio.to_thread(LauncherWindow._stop_engine, host)
        first_call_elapsed = time.monotonic() - first_call_started
        assert first_call_elapsed < 2.0
        await asyncio.wait_for(off_started.wait(), timeout=5)

        dispatched_worker = host._engine_shutdown_worker
        assert dispatched_worker is not None
        assert launcher_shutdown_dispatch_count == 1

        # A concurrent mutation still finds the command path latched while
        # the receipt remains outstanding -- proof the path is retained, not
        # released, the moment the worker is dispatched.
        mutation_task = asyncio.create_task(
            asyncio.to_thread(
                bridge.send_command,
                {"cmd": "keithley_start", "channel": "smua"},
            )
        )
        mutation_reply = await asyncio.wait_for(mutation_task, timeout=5)
        mutation_task = None
        assert mutation_reply["error_code"] == "engine_shutdown_latched"
        assert mutation_reply["delivery_state"] == "dispatched"
        assert mutation_reply["commit_state"] == "not_committed"
        assert mutation_reply["retry_safe"] is False
        assert engine.poll() is None
        assert stderr_thread.is_alive()
        assert context.shutdown_event is not None
        assert not context.shutdown_event.is_set()

        # Retry loop: mirrors _schedule_shutdown_retry re-entering
        # _stop_engine on a timer. Intervals are shortened here (the real
        # ladder is 1s/3s/10s/30s) so the test stays fast; what's under test
        # is that every retry finds the *same* worker instead of
        # re-dispatching, and every retry stays bounded-fast rather than
        # blocking, for as long as the reply is outstanding.
        for _ in range(5):
            await asyncio.sleep(0.02)
            retry_started = time.monotonic()
            with pytest.raises(RuntimeError, match="awaiting its reply"):
                await asyncio.to_thread(LauncherWindow._stop_engine, host)
            retry_elapsed = time.monotonic() - retry_started
            assert retry_elapsed < 0.5
            assert host._engine_shutdown_worker is dispatched_worker
            assert host._bridge is bridge
            assert bridge._terminal_closed is False
            assert launcher_shutdown_dispatch_count == 1

        # Let the reply land, then keep driving _stop_engine (still
        # retry-style -- receipt validation and the bounded process-exit
        # wait can each still raise their own HOLD once) until it consumes
        # worker.result and settles.
        release_off.set()
        settled = False
        for _ in range(50):
            try:
                await asyncio.to_thread(LauncherWindow._stop_engine, host)
            except RuntimeError as exc:
                assert "awaiting its reply" in str(exc) or "has not yet exited" in str(exc)
                await asyncio.sleep(0.05)
                continue
            settled = True
            break
        assert settled

        assert context.safety_manager.emergency_off.await_count == 1
        assert context.shutdown_event.is_set()
        assert engine.poll() == 0
        assert host._engine_proc is None
        assert host._engine_stderr_thread is None
        assert not stderr_thread.is_alive()
        assert host._engine_shutdown_worker is None
        assert launcher_shutdown_dispatch_count == 1
    finally:
        release_off.set()
        if mutation_task is not None and not mutation_task.done():
            mutation_task.cancel()
        # A failure earlier in this test can leave the bridge with unresolved
        # mutation state, and ZmqBridge.close() refuses to close terminally
        # in that case. That must never skip reclaiming the real subprocess
        # and stderr-pump thread below -- an unconditional bridge.close()
        # here previously did exactly that (a whole-file run hung for 420s
        # with a leaked engine process). Reclaim everything else first, and
        # only re-raise the close failure once nothing real is left leaked.
        close_error: BaseException | None = None
        try:
            bridge.close()
        except BaseException as exc:  # noqa: BLE001 - deliberately broad, re-raised below
            close_error = exc
        await command_ingress.stop()
        _settle_process(engine)
        if engine.stdin is not None and not engine.stdin.closed:
            with contextlib.suppress(OSError):
                engine.stdin.close()
        stderr_thread.join(timeout=3)
        if stderr_handler in stderr_logger.handlers:
            stderr_logger.removeHandler(stderr_handler)
        stderr_handler.close()
        if close_error is not None:
            raise close_error


@pytest.mark.parametrize("iteration", range(3))
def test_real_launcher_shutdown_settles_every_owner_before_releasing_lock(
    tmp_path, iteration: int, _gui_worker_root_session: int
) -> None:
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
            # Production binds this in LauncherWindow.__init__ via
            # open_gui_command_worker_admission(); _quiesce_for_shutdown revokes
            # exactly this epoch. Without it the revoke is silently skipped,
            # _GUI_WORKER_ADMISSION_OPEN stays True, and
            # settle_registered_gui_command_workers() can never return True.
            _gui_worker_session_epoch=_gui_worker_root_session,
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
        settled = LauncherWindow._do_shutdown(host)
        settlement_deadline = time.monotonic() + 3.0
        while not settled and time.monotonic() < settlement_deadline:
            time.sleep(0.01)
            settled = LauncherWindow._do_shutdown(host)
        assert settled is True

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


def test_timed_out_engine_is_force_reaped_while_exact_settlement_remains_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live-but-unresponsive engine stays in bounded-retry HOLD, never an
    immediate force-kill, until the 60s exit-wait budget is genuinely spent
    -- then it is force-reaped exactly once, with the unsettled incarnation
    latched before that reaping ever touches the process.

    ``_stop_engine`` no longer waits for process exit on the Qt main thread.
    It polls without blocking against a wall-clock deadline tracked across
    repeated calls. A real caller re-enters via the shutdown-retry timer;
    this test fast-forwards a fake ``time.monotonic`` across those re-entries
    instead of sleeping for 60 real seconds.
    """

    class TimedOutProcess:
        pid = 41_999

        def __init__(self) -> None:
            self.state = "running"
            self.wait_timeouts: list[float] = []
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self) -> int | None:
            return -9 if self.state == "killed" else None

        def wait(self, timeout: float) -> int:
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

    class _FakeClock:
        """A controllable monotonic clock so the 60s exit-wait budget can be
        crossed deterministically across repeated _stop_engine calls,
        without a real 60s sleep."""

        def __init__(self, start: float) -> None:
            self.now = start

        def monotonic(self) -> float:
            return self.now

    clock = _FakeClock(1_000_000.0)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)

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
            "schema": "cryodaq.engine_shutdown.v3",
            "engine_instance_id": "a" * 32,
            "request_id": request_id,
            "off_evidence": _verified_global_off_result()["off_evidence"],
            "operator_physical_disconnect": False,
            "teardown_requested": True,
            "delivery_state": "dispatched",
            "commit_state": "committed",
            "proto": 2,
        },
        _engine_unsettled_incarnation=None,
        _engine_shutdown_worker=None,
        _engine_shutdown_wait_deadline=None,
        _restart_giving_up=False,
        _bridge=bridge,
        _close_engine_stderr_stream=close_stream,
    )

    # A receipt is already latched on the host (production behaviour once a
    # prior call has one), so every call below goes straight to the
    # process-exit wait -- the worker is never dispatched.
    with pytest.raises(RuntimeError, match="not yet exited"):
        LauncherWindow._stop_engine(host)

    assert process.wait_timeouts == []
    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert host._engine_proc is process
    deadline = host._engine_shutdown_wait_deadline
    assert deadline is not None
    assert host._engine_unsettled_incarnation is None
    assert host._engine_shutdown_worker is None
    close_stream.assert_not_called()
    bridge.send_command.assert_not_called()

    # Advance in slices while remaining strictly inside the 60s budget:
    # every call must stay a bounded HOLD, re-using the same deadline, never
    # an early force-kill.
    for _ in range(3):
        clock.now += 1.0
        with pytest.raises(RuntimeError, match="not yet exited"):
            LauncherWindow._stop_engine(host)
        assert host._engine_shutdown_wait_deadline == deadline
        assert process.terminate_calls == 0
        assert process.kill_calls == 0
        assert host._engine_proc is process

    assert process.wait_timeouts == []

    # Spy on terminate() to prove the unsettled incarnation is latched
    # BEFORE any reaping touches the process -- the production comment
    # "Latch before terminate() so a second stop cannot release retained
    # authority evidence" is the invariant under test here.
    latched_before_reap: list[object] = []
    original_terminate = process.terminate

    def spying_terminate() -> None:
        latched_before_reap.append(host._engine_unsettled_incarnation)
        original_terminate()

    process.terminate = spying_terminate

    # Cross the budget without a real 60s sleep: the next call must force-
    # reap exactly once.
    clock.now = deadline + 1.0
    with pytest.raises(RuntimeError, match="forced death was reaped but is not exact settlement"):
        LauncherWindow._stop_engine(host)

    assert latched_before_reap == [("a" * 32, None)]
    assert process.wait_timeouts == [5.0, 5.0]
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert host._engine_proc is None
    assert host._engine_unsettled_incarnation == ("a" * 32, -9)
    assert host._restart_giving_up is True
    assert host._engine_shutdown_wait_deadline is None
    close_stream.assert_called_once_with()
    bridge.send_command.assert_not_called()

    # A later "clean"-looking exit can never retroactively become
    # settlement, and must never re-dispatch or re-reap.
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
