"""A2 — task supervision for long-lived engine tasks.

Covers the two extracted, importable helpers so the PRODUCTION supervision
logic is exercised directly (same rationale as ``_drain_dispatch_tasks``):

  * ``_alarm_v2_feed_loop`` — the per-reading guard that keeps the alarm-v2
    state feed alive when a single bad reading raises inside ``tracker.update``.
  * ``_handle_supervised_task_exit`` — the done-callback decision core:
    CRITICAL + operator alarm + exponential-backoff restart on unexpected
    death, and FAULT-latch for the two safety tasks after 2 failed restarts.
    Every registered task returning or being cancelled while the engine is
    live is authority loss and must alarm/restart just like an exception.
    During orderly shutdown, every terminal outcome remains expected.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from dataclasses import MISSING, fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cryodaq.engine as engine_module
from cryodaq.core.safety_manager import SafetyShutdownUnverifiedError
from cryodaq.core.zmq_bridge import (
    ZMQCommandIngressTerminalError,
    ZMQCommandIngressTerminalFailure,
)
from cryodaq.engine import (
    _SAFETY_TASK_MAX_RESTARTS,
    _SUPERVISE_BACKOFF_BASE_S,
    _SUPERVISE_RESET_WINDOW_S,
    _alarm_v2_feed_loop,
    _commit_engine_command_ingress_startup,
    _EngineShutdownLayer,
    _EngineShutdownOwner,
    _EngineShutdownSettledFailure,
    _EngineStartupRollback,
    _EngineTeardownSequence,
    _EngineTeardownState,
    _handle_supervised_task_exit,
    _run_engine,
    _settle_command_server_before_safety,
    _settle_engine_shutdown_phase,
    _settle_engine_shutdown_plan,
    _wait_for_engine_shutdown_or_ingress_failure,
)
from cryodaq.engine_wiring import supervision as supervision_mod
from cryodaq.engine_wiring.supervision import (
    TaskSupervisor,
    install_loop_exception_backstop,
    stop_safety_manager_with_hold,
)

# --------------------------------------------------------------------------
# Part (a): alarm-v2 feed loop per-reading guard
# --------------------------------------------------------------------------


class _FakeReading:
    def __init__(self, channel: str, value: float, *, usable: bool = True) -> None:
        self.channel = channel
        self.value = value
        self._usable = usable

    class _TS:
        def timestamp(self) -> float:
            return 123.0

    @property
    def timestamp(self) -> _FakeReading._TS:
        return _FakeReading._TS()

    def is_usable(self) -> bool:
        return self._usable


class _FlakyTracker:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def update(self, reading: _FakeReading) -> None:
        self.seen.append(reading.channel)
        if reading.channel == "bad":
            raise ValueError("corrupt reading")


class _RecordingRate:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    def push(self, channel: str, ts: float, value: float) -> None:
        self.pushed.append(channel)


async def test_feed_loop_survives_bad_reading(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    queue: asyncio.Queue = asyncio.Queue()
    tracker = _FlakyTracker()
    rate = _RecordingRate()

    await queue.put(_FakeReading("bad", 1.0))
    await queue.put(_FakeReading("good", 2.0))

    task = asyncio.create_task(_alarm_v2_feed_loop(queue, tracker, rate))
    # Drain both readings, then cancel the loop.
    for _ in range(50):
        if queue.empty():
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    await task  # loop swallows CancelledError and returns cleanly

    # Bad reading did not kill the loop: the good reading was processed after it.
    assert tracker.seen == ["bad", "good"]
    assert rate.pushed == ["good"]
    assert "Alarm v2 feed" in caplog.text


async def test_feed_loop_skips_unusable_reading() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    tracker = _FlakyTracker()
    rate = _RecordingRate()

    await queue.put(_FakeReading("good", 2.0, usable=False))
    task = asyncio.create_task(_alarm_v2_feed_loop(queue, tracker, rate))
    for _ in range(50):
        if queue.empty():
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    await task  # loop swallows CancelledError and returns cleanly

    assert tracker.seen == ["good"]
    assert rate.pushed == []  # not usable -> no OLS push


# --------------------------------------------------------------------------
# Part (b): supervised-task done-callback decision core
# --------------------------------------------------------------------------


async def _failed_task(exc: BaseException) -> asyncio.Task:
    async def boom() -> None:
        raise exc

    t = asyncio.create_task(boom())
    try:
        await t
    except BaseException:  # noqa: BLE001 — retrieve so no "never retrieved" warning
        pass
    return t


async def _cancelled_task() -> asyncio.Task:
    async def hang() -> None:
        await asyncio.sleep(10)

    t = asyncio.create_task(hang())
    await asyncio.sleep(0)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    return t


async def _clean_task() -> asyncio.Task:
    async def done() -> None:
        return None

    t = asyncio.create_task(done())
    await t
    return t


def _spy_actions() -> dict:
    calls: dict = {"alarm": [], "restart": [], "fault": []}
    return calls


def _invoke(task, *, stopping=False, counts=None, calls=None, safety=False, running_s=0.0):
    calls = calls if calls is not None else _spy_actions()
    counts = counts if counts is not None else {}
    logger = logging.getLogger("test.supervise")
    return (
        _handle_supervised_task_exit(
            name="widget",
            task=task,
            stopping=stopping,
            restart_counts=counts,
            logger_=logger,
            on_alarm=lambda n, e: calls["alarm"].append((n, repr(e))),
            on_restart=lambda d: calls["restart"].append(d),
            on_fault_latch=lambda n, e: calls["fault"].append((n, repr(e))),
            safety_critical=safety,
            running_s=running_s,
        ),
        calls,
        counts,
    )


async def test_live_cancelled_task_alarms_and_restarts() -> None:
    task = await _cancelled_task()
    verdict, calls, counts = _invoke(task)
    assert verdict == "restart"
    assert counts["widget"] == 1
    assert "cancelled unexpectedly" in calls["alarm"][0][1]
    assert calls["restart"] == [_SUPERVISE_BACKOFF_BASE_S]


async def test_shutdown_never_restarts() -> None:
    task = await _failed_task(RuntimeError("boom"))
    verdict, calls, _ = _invoke(task, stopping=True)
    assert verdict == "ignored"
    assert calls["restart"] == [] and calls["alarm"] == []


async def test_live_clean_return_alarms_and_restarts() -> None:
    task = await _clean_task()
    verdict, calls, counts = _invoke(task)
    assert verdict == "restart"
    assert counts["widget"] == 1
    assert "returned unexpectedly" in calls["alarm"][0][1]
    assert calls["restart"] == [_SUPERVISE_BACKOFF_BASE_S]


async def test_unexpected_safety_task_cancellation_alarms_and_restarts() -> None:
    task = await _cancelled_task()
    verdict, calls, counts = _invoke(task, safety=True)
    assert verdict == "restart"
    assert counts["widget"] == 1
    assert calls["alarm"]
    assert "cancelled unexpectedly" in calls["alarm"][0][1]
    assert calls["restart"] == [_SUPERVISE_BACKOFF_BASE_S]


async def test_unexpected_safety_task_clean_return_alarms_and_restarts() -> None:
    task = await _clean_task()
    verdict, calls, counts = _invoke(task, safety=True)
    assert verdict == "restart"
    assert counts["widget"] == 1
    assert calls["alarm"]
    assert "returned unexpectedly" in calls["alarm"][0][1]
    assert calls["restart"] == [_SUPERVISE_BACKOFF_BASE_S]


async def test_stopping_safety_task_cancellation_is_expected() -> None:
    task = await _cancelled_task()
    verdict, calls, counts = _invoke(task, safety=True, stopping=True)
    assert verdict == "ignored"
    assert counts == {}
    assert calls == {"alarm": [], "restart": [], "fault": []}


async def test_safety_shutdown_hold_retries_until_exact_settlement(caplog: pytest.LogCaptureFixture) -> None:
    manager = MagicMock()
    manager.stop = AsyncMock(
        side_effect=[
            SafetyShutdownUnverifiedError("OFF unverified"),
            None,
        ]
    )
    sleep = AsyncMock()

    await stop_safety_manager_with_hold(manager, logging.getLogger("test-hold"), retry_delay_s=0.0, sleep=sleep)

    assert manager.stop.await_count == 2
    sleep.assert_awaited_once_with(0.0)
    assert "Safety shutdown HOLD" in caplog.text


async def test_safety_shutdown_owner_absorbs_repeated_caller_cancellation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_stop() -> None:
        entered.set()
        await release.wait()

    manager = MagicMock()
    manager.stop = AsyncMock(side_effect=blocked_stop)
    owner = asyncio.create_task(
        stop_safety_manager_with_hold(manager, logging.getLogger("test-hold-cancel"), retry_delay_s=0.0)
    )
    await entered.wait()
    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    release.set()
    await owner

    manager.stop.assert_awaited_once_with()
    assert "retained until exact settlement" in caplog.text


async def test_command_server_shutdown_proves_off_while_mutation_owner_is_held_and_after_settlement() -> None:
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    first_off = asyncio.Event()

    class CommandServer:
        frozen = False

        def freeze_admission(self) -> None:
            self.frozen = True

        async def stop(self) -> None:
            stop_entered.set()
            await release_stop.wait()

    off_calls = 0

    async def stop_safety() -> None:
        nonlocal off_calls
        off_calls += 1
        first_off.set()

    command_server = CommandServer()
    safety_manager = MagicMock()
    safety_manager.stop = AsyncMock(side_effect=stop_safety)
    owner = asyncio.create_task(
        _settle_command_server_before_safety(
            command_server,
            safety_manager,
            logging.getLogger("test-command-shutdown-hold"),
            retry_delay_s=0.01,
        )
    )

    await asyncio.wait_for(stop_entered.wait(), timeout=0.1)
    await asyncio.wait_for(first_off.wait(), timeout=0.1)
    assert command_server.frozen is True
    assert not owner.done(), "global OFF must not abandon the retained mutation owner"
    first_off_count = off_calls

    release_stop.set()
    failures = await asyncio.wait_for(owner, timeout=0.2)

    assert failures == ()
    assert off_calls > first_off_count, "OFF must be proved again after the final mutation owner settles"


async def test_command_server_shutdown_retries_terminal_failures_without_bypassing_off() -> None:
    stop_outcomes: list[BaseException | None] = [
        RuntimeError("REP stop failed"),
        asyncio.CancelledError(),
        None,
    ]

    class CommandServer:
        freeze_calls = 0
        stop_calls = 0

        def freeze_admission(self) -> None:
            self.freeze_calls += 1

        async def stop(self) -> None:
            self.stop_calls += 1
            outcome = stop_outcomes.pop(0)
            if outcome is not None:
                raise outcome

    command_server = CommandServer()
    safety_manager = MagicMock()
    safety_manager.stop = AsyncMock(return_value=None)

    failures = await _settle_command_server_before_safety(
        command_server,
        safety_manager,
        logging.getLogger("test-command-shutdown-retry"),
        retry_delay_s=0.0,
    )

    assert command_server.freeze_calls == 1
    assert command_server.stop_calls == 3
    assert [type(failure) for failure in failures] == [RuntimeError, asyncio.CancelledError]
    assert safety_manager.stop.await_count >= 3


async def test_command_server_settlement_uses_hardened_safety_owner_without_direct_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = logging.getLogger("test-command-shutdown-hardened-owner")

    class CommandServer:
        def freeze_admission(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    safety_manager = MagicMock()
    safety_manager.stop = AsyncMock(side_effect=AssertionError("direct SafetyManager.stop bypassed HOLD owner"))
    hardened_stop = AsyncMock(return_value=None)
    monkeypatch.setattr(engine_module, "stop_safety_manager_with_hold", hardened_stop)

    failures = await engine_module._settle_command_server_before_safety(
        CommandServer(),
        safety_manager,
        logger,
        retry_delay_s=0.0,
    )

    assert failures == ()
    assert hardened_stop.await_count >= 2
    assert all(call.args == (safety_manager, logger) for call in hardened_stop.await_args_list)
    assert all(call.kwargs == {} for call in hardened_stop.await_args_list)
    safety_manager.stop.assert_not_awaited()


async def test_engine_terminal_wait_normal_shutdown_cancels_non_consuming_ingress_waiter() -> None:
    shutdown = asyncio.Event()

    class Pair:
        terminal_failure = None
        waiter_cancelled = False

        async def wait_terminal_failure(self):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.waiter_cancelled = True
                raise

    pair = Pair()
    shutdown.set()

    failure = await _wait_for_engine_shutdown_or_ingress_failure(shutdown, pair)  # type: ignore[arg-type]

    assert failure is None
    assert pair.waiter_cancelled is True


def _ready_context(*, channel_fd: int | None) -> engine_module.EngineCommandContext:
    required: dict[str, object] = {}
    for item in fields(engine_module.EngineCommandContext):
        if item.default is MISSING and item.default_factory is MISSING:
            required[item.name] = MagicMock(name=item.name)
    context = engine_module.EngineCommandContext(**required)
    context.engine_ready_nonce = "a" * 64
    context.engine_instance_id = "b" * 32
    context.engine_ready_pid = 1234
    context.engine_ready_channel_fd = channel_fd
    context.engine_ready_advertised = False
    context.experiment_commands_accepting = False
    return context


async def test_engine_ready_commit_emits_real_private_pipe_before_accepting_commands() -> None:
    rollback_events: list[str] = []

    class Ingress:
        health_checks = 0

        def require_healthy(self) -> None:
            self.health_checks += 1

    read_fd, write_fd = os.pipe()
    context = _ready_context(channel_fd=write_fd)
    ingress = Ingress()
    startup = _EngineStartupRollback()
    startup.add("command_ingress", lambda: rollback_events.append("ingress.stop"))
    try:
        await _commit_engine_command_ingress_startup(  # type: ignore[arg-type]
            command_ingress=ingress,
            command_context=context,
            startup=startup,
        )
        wire = os.read(read_fd, 2048)
    finally:
        os.close(read_fd)
        if context.engine_ready_channel_fd is not None:
            os.close(context.engine_ready_channel_fd)
            context.engine_ready_channel_fd = None

    assert wire.startswith(engine_module._ENGINE_READY_WIRE_PREFIX)
    receipt = json.loads(wire.removeprefix(engine_module._ENGINE_READY_WIRE_PREFIX))
    assert receipt["nonce"] == "a" * 64
    assert receipt["engine_instance_id"] == "b" * 32
    assert receipt["pid"] == 1234
    assert ingress.health_checks == 2
    assert context.engine_ready_advertised is True
    assert context.experiment_commands_accepting is True
    assert context.engine_ready_channel_fd is None
    assert rollback_events == []
    assert startup._settled is True


async def test_engine_ready_commit_rejects_async_internal_drift_before_external_send(monkeypatch) -> None:
    rollback_events: list[str] = []
    emissions: list[str] = []

    class Ingress:
        health_checks = 0

        def require_healthy(self) -> None:
            self.health_checks += 1

    ingress = Ingress()
    context = _ready_context(channel_fd=None)
    startup = _EngineStartupRollback()
    startup.add("command_ingress", lambda: rollback_events.append("ingress.stop"))

    async def drifted_internal_ready_send(_context) -> None:  # noqa: ANN001
        emissions.append("external-ready-sent")
        await asyncio.sleep(0)

    monkeypatch.setattr(engine_module, "_emit_engine_ready_receipt", drifted_internal_ready_send)

    with pytest.raises(TypeError, match="engine READY emitter must return exactly None"):
        await _commit_engine_command_ingress_startup(  # type: ignore[arg-type]
            command_ingress=ingress,
            command_context=context,
            startup=startup,
        )

    assert emissions == []
    assert ingress.health_checks == 1
    assert context.experiment_commands_accepting is False
    assert rollback_events == ["ingress.stop"]
    assert startup._settled is True


async def test_engine_terminal_wait_prioritizes_sticky_ingress_failure_when_both_ready() -> None:
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="safe",
        stage="recovery_exhausted",
        failure_type="RuntimeError",
    )
    shutdown = asyncio.Event()
    shutdown.set()

    class Pair:
        terminal_failure = failure

        async def wait_terminal_failure(self):
            return failure

    assert (
        await _wait_for_engine_shutdown_or_ingress_failure(  # type: ignore[arg-type]
            shutdown,
            Pair(),
        )
        is failure
    )


async def test_engine_terminal_wait_keeps_failure_latched_while_losing_waiter_settles() -> None:
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="ordinary",
        stage="loop_closed",
        failure_type="RuntimeError",
    )
    shutdown = asyncio.Event()
    shutdown.set()

    class Pair:
        terminal_failure = None

        async def wait_terminal_failure(self):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.terminal_failure = failure
                raise

    pair = Pair()

    assert (
        await _wait_for_engine_shutdown_or_ingress_failure(  # type: ignore[arg-type]
            shutdown,
            pair,
        )
        is failure
    )


def test_ingress_terminal_error_exposes_only_sanitized_provenance() -> None:
    secret = "raw-exception-secret"
    failure = ZMQCommandIngressTerminalFailure(
        endpoint="ordinary",
        stage="recovery_task_create_failed",
        failure_type="OSError",
    )

    error = ZMQCommandIngressTerminalError(failure)

    assert error.failure is failure
    assert str(error) == (
        "ZMQ command ingress terminated: endpoint=ordinary; stage=recovery_task_create_failed; failure=OSError"
    )
    assert secret not in str(error)


async def test_crash_alarms_and_restarts_with_backoff() -> None:
    counts: dict[str, int] = {}
    task = await _failed_task(RuntimeError("boom"))
    verdict, calls, _ = _invoke(task, counts=counts)
    assert verdict == "restart"
    assert counts["widget"] == 1
    assert calls["alarm"] and calls["alarm"][0][0] == "widget"
    # First restart uses the base backoff.
    assert calls["restart"] == [_SUPERVISE_BACKOFF_BASE_S]

    # Second crash -> backoff doubles.
    task2 = await _failed_task(RuntimeError("boom2"))
    verdict2, calls2, _ = _invoke(task2, counts=counts)
    assert verdict2 == "restart"
    assert counts["widget"] == 2
    assert calls2["restart"] == [_SUPERVISE_BACKOFF_BASE_S * 2]


async def test_healthy_run_resets_restart_count_before_latch() -> None:
    """F3 (Phase A gate, MEDIUM): sparse crashes, each separated by a healthy
    run window (>= _SUPERVISE_RESET_WINDOW_S), must NOT accumulate toward the
    safety latch — only CONSECUTIVE rapid restarts count (roadmap policy:
    "after 2 FAILED restarts", i.e. consecutive, not lifetime)."""
    counts: dict[str, int] = {}
    calls = _spy_actions()

    # Crash 1: fresh task, no prior healthy run to credit.
    task = await _failed_task(RuntimeError("transient 1"))
    verdict, calls, counts = _invoke(task, counts=counts, calls=calls, safety=True)
    assert verdict == "restart"
    assert counts["widget"] == 1

    # That restarted incarnation ran HEALTHILY for a long window before it
    # too crashed — this must reset the streak, not accumulate to 2.
    task2 = await _failed_task(RuntimeError("transient 2"))
    verdict2, calls, counts = _invoke(
        task2, counts=counts, calls=calls, safety=True, running_s=_SUPERVISE_RESET_WINDOW_S
    )
    assert verdict2 == "restart"
    assert counts["widget"] == 1, "a healthy run before the crash must reset the count"

    # A third crash, again after a healthy run — must still not approach latch.
    task3 = await _failed_task(RuntimeError("transient 3"))
    verdict3, calls, counts = _invoke(
        task3, counts=counts, calls=calls, safety=True, running_s=_SUPERVISE_RESET_WINDOW_S
    )
    assert verdict3 == "restart"
    assert counts["widget"] == 1
    assert calls["fault"] == [], "sparse, well-separated crashes must never latch FAULT"


async def test_safety_task_latches_fault_after_two_restarts() -> None:
    counts: dict[str, int] = {}
    calls = _spy_actions()
    # Restarts 1 and 2 -> restart.
    for expected_count in (1, 2):
        task = await _failed_task(RuntimeError("safety down"))
        verdict, calls, counts = _invoke(task, counts=counts, calls=calls, safety=True)
        assert verdict == "restart"
        assert counts["widget"] == expected_count
    assert counts["widget"] == _SAFETY_TASK_MAX_RESTARTS
    # Third crash -> fault latch, no further restart scheduled.
    task = await _failed_task(RuntimeError("safety down"))
    verdict, calls, counts = _invoke(task, counts=counts, calls=calls, safety=True)
    assert verdict == "fault_latch"
    assert calls["fault"] and calls["fault"][-1][0] == "widget"
    # restart list must not have grown for the fault-latch case (3 restarts scheduled max = 2).
    assert len(calls["restart"]) == _SAFETY_TASK_MAX_RESTARTS


class _RecordingEventBus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


class _RecordingSafetyManager:
    def __init__(self) -> None:
        self.faults: list[dict] = []
        self._collect_task: asyncio.Task | None = None

    async def latch_fault(self, **kwargs) -> None:
        self.faults.append(kwargs)


def _make_supervisor():
    event_bus = _RecordingEventBus()
    safety_manager = _RecordingSafetyManager()
    dispatch_tasks: set[asyncio.Task] = set()
    supervisor = TaskSupervisor(
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="exp-1"),
        safety_manager=safety_manager,
        alarm_dispatch_tasks=dispatch_tasks,
        logger_=logging.getLogger("test.task-supervisor.integration"),
    )
    return supervisor, event_bus, safety_manager, dispatch_tasks


async def _spin_until(predicate, *, turns: int = 200) -> None:
    for _ in range(turns):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


async def _cancel_live_supervised_tasks(supervisor: TaskSupervisor) -> None:
    supervisor.stop()
    tasks = [task for task in supervisor.supervised_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_task_supervisor_respawns_replaces_registry_and_updates_on_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.0)
    supervisor, _, safety_manager, _ = _make_supervisor()
    attempts = 0
    keep_alive = asyncio.Event()

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first incarnation failed")
        await keep_alive.wait()

    initial = supervisor.spawn(
        "safety_collect",
        factory,
        safety_critical=True,
        on_spawn=lambda task: setattr(safety_manager, "_collect_task", task),
    )
    await _spin_until(lambda: attempts == 2)

    replacement = supervisor.supervised_tasks["safety_collect"]
    assert replacement is not initial
    assert safety_manager._collect_task is replacement
    await _cancel_live_supervised_tasks(supervisor)


async def test_task_supervisor_live_clean_return_alarms_and_respawns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.0)
    supervisor, event_bus, _, dispatch_tasks = _make_supervisor()
    attempts = 0
    keep_alive = asyncio.Event()

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return
        await keep_alive.wait()

    initial = supervisor.spawn("ordinary", factory)
    await _spin_until(lambda: attempts == 2)
    if dispatch_tasks:
        await asyncio.gather(*list(dispatch_tasks), return_exceptions=True)

    assert supervisor.supervised_tasks["ordinary"] is not initial
    assert len(event_bus.events) == 1
    assert event_bus.events[0].payload["alarm_id"] == "task_supervisor_ordinary"
    await _cancel_live_supervised_tasks(supervisor)


async def test_task_supervisor_live_cancellation_alarms_and_respawns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.0)
    supervisor, event_bus, _, dispatch_tasks = _make_supervisor()
    attempts = 0
    keep_alive = asyncio.Event()

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        await keep_alive.wait()

    initial = supervisor.spawn("ordinary", factory)
    await _spin_until(lambda: attempts == 1)
    initial.cancel()
    await asyncio.gather(initial, return_exceptions=True)
    await _spin_until(lambda: attempts == 2)
    if dispatch_tasks:
        await asyncio.gather(*list(dispatch_tasks), return_exceptions=True)

    assert supervisor.supervised_tasks["ordinary"] is not initial
    assert len(event_bus.events) == 1
    assert event_bus.events[0].payload["alarm_id"] == "task_supervisor_ordinary"
    await _cancel_live_supervised_tasks(supervisor)


async def test_task_supervisor_stopping_cancellation_does_not_alarm_or_respawn() -> None:
    supervisor, event_bus, _, dispatch_tasks = _make_supervisor()
    started = asyncio.Event()
    keep_alive = asyncio.Event()

    async def factory() -> None:
        started.set()
        await keep_alive.wait()

    task = supervisor.spawn("ordinary", factory)
    await started.wait()
    supervisor.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    if dispatch_tasks:
        await asyncio.gather(*list(dispatch_tasks), return_exceptions=True)

    assert supervisor._restarts == {}
    assert event_bus.events == []


async def test_task_supervisor_latches_after_two_failed_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.0)
    supervisor, event_bus, safety_manager, dispatch_tasks = _make_supervisor()
    attempts = 0

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError(f"failure-{attempts}")

    supervisor.spawn("safety_collect", factory, safety_critical=True)
    await _spin_until(lambda: bool(safety_manager.faults))
    if dispatch_tasks:
        await asyncio.gather(*list(dispatch_tasks), return_exceptions=True)

    assert attempts == _SAFETY_TASK_MAX_RESTARTS + 1
    assert len(event_bus.events) == _SAFETY_TASK_MAX_RESTARTS + 1
    assert len(safety_manager.faults) == 1
    assert safety_manager.faults[0]["source"] == "safety_collect"
    supervisor.stop()


async def test_task_supervisor_healthy_window_resets_integrated_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.0)
    supervisor, _, _, _ = _make_supervisor()
    release = asyncio.Event()
    attempts = 0

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("initial failure")
        await release.wait()
        raise RuntimeError("failure after healthy run")

    supervisor.spawn("ordinary", factory)
    await _spin_until(lambda: attempts == 2)
    supervisor._spawn_times["ordinary"] = time.monotonic() - _SUPERVISE_RESET_WINDOW_S
    release.set()
    await _spin_until(lambda: attempts == 3)

    assert supervisor._restarts["ordinary"] == 1
    await _cancel_live_supervised_tasks(supervisor)


async def test_task_supervisor_stop_before_timer_suppresses_respawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision_mod, "_SUPERVISE_BACKOFF_BASE_S", 0.05)
    supervisor, _, _, _ = _make_supervisor()
    attempts = 0

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("failure")

    supervisor.spawn("ordinary", factory)
    await _spin_until(lambda: supervisor._restarts.get("ordinary") == 1)
    supervisor.stop()
    await asyncio.sleep(0.08)

    assert attempts == 1


async def test_loop_exception_backstop_logs_named_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    test_logger = logging.getLogger("test.loop-backstop")
    caplog.set_level(logging.CRITICAL, logger=test_logger.name)
    install_loop_exception_backstop(loop, test_logger)

    async def fail() -> None:
        raise RuntimeError("backstop-boom")

    task = asyncio.create_task(fail(), name="named-backstop-task")
    try:
        await task
    except RuntimeError as exc:
        loop.call_exception_handler({"message": "manual backstop", "exception": exc, "task": task})
    finally:
        loop.set_exception_handler(previous)

    assert "manual backstop" in caplog.text
    assert "named-backstop-task" in caplog.text
    assert "backstop-boom" in caplog.text


async def test_engine_startup_partial_acquire_rolls_back_every_owner_in_reverse_order() -> None:
    startup = _EngineStartupRollback()
    events: list[str] = []
    second_stop_attempts = 0

    async def first_start() -> str:
        events.append("first-start")
        return "first-ready"

    async def first_stop() -> None:
        await asyncio.sleep(0)
        events.append("first-stop")

    async def second_partial_start() -> None:
        events.append("second-partially-acquired")
        raise RuntimeError("second start failed")

    def second_stop_failure_then_success() -> None:
        nonlocal second_stop_attempts
        second_stop_attempts += 1
        events.append("second-stop")
        if second_stop_attempts == 1:
            raise ValueError("second cleanup failed")

    assert (
        await startup.acquire(
            first_start(),
            label="first",
            rollback=first_stop,
        )
        == "first-ready"
    )
    with pytest.raises(RuntimeError, match="second start failed"):
        await startup.acquire(
            second_partial_start(),
            label="second",
            rollback=second_stop_failure_then_success,
        )

    assert events == [
        "first-start",
        "second-partially-acquired",
        "second-stop",
        "first-stop",
        "second-stop",
    ]
    with pytest.raises(RuntimeError, match="already settled"):
        startup.add("late-owner", lambda: None)


async def test_engine_startup_failure_automatically_retries_retained_cleanup_before_returning() -> None:
    startup = _EngineStartupRollback()
    events: list[str] = []
    cleanup_attempts = 0

    async def acquired_owner_stop() -> None:
        events.append("acquired-stop")

    async def partial_start() -> None:
        events.append("partial-start")
        raise RuntimeError("startup failed")

    async def partial_stop() -> None:
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        events.append(f"partial-stop:{cleanup_attempts}")
        if cleanup_attempts == 1:
            raise OSError("transient cleanup failure")

    startup.add("acquired", acquired_owner_stop)

    with pytest.raises(RuntimeError, match="startup failed"):
        await asyncio.wait_for(
            startup.acquire(
                partial_start(),
                label="partial",
                rollback=partial_stop,
            ),
            timeout=1.0,
        )

    assert events == [
        "partial-start",
        "partial-stop:1",
        "acquired-stop",
        "partial-stop:2",
    ]
    assert cleanup_attempts == 2
    with pytest.raises(RuntimeError, match="already settled"):
        startup.add("late-owner", lambda: None)


async def test_engine_shutdown_phase_attempts_every_peer_before_retry_and_removes_only_exact_success() -> None:
    events: list[str] = []
    attempts = {"transient": 0, "non_exact": 0}

    async def transient() -> None:
        attempts["transient"] += 1
        events.append(f"transient:{attempts['transient']}")
        if attempts["transient"] == 1:
            raise OSError("first attempt failed")

    async def exact_success() -> None:
        events.append("exact-success")

    async def non_exact_success() -> bool | None:
        attempts["non_exact"] += 1
        events.append(f"non-exact:{attempts['non_exact']}")
        if attempts["non_exact"] == 1:
            return True
        return None

    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    failures = await asyncio.wait_for(
        _settle_engine_shutdown_phase(
            (
                _EngineShutdownOwner("transient", transient),
                _EngineShutdownOwner("exact_success", exact_success),
                _EngineShutdownOwner("non_exact", non_exact_success),
            ),
            logging.getLogger("test.engine-shutdown.attempt-all"),
            retry_delay_s=999.0,
            sleep=record_delay,
        ),
        timeout=1.0,
    )

    assert set(events[:3]) == {"transient:1", "exact-success", "non-exact:1"}
    assert events.count("exact-success") == 1
    assert events[3:] == ["transient:2", "non-exact:2"]
    assert attempts == {"transient": 2, "non_exact": 2}
    assert delays == [1.0]
    assert [(label, type(exc), str(exc)) for label, exc in failures] == [
        ("transient", OSError, "first attempt failed"),
        ("non_exact", RuntimeError, "shutdown callback did not return exact success"),
    ]


async def test_engine_shutdown_phase_survives_repeated_caller_cancellation_until_every_owner_settles() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    peer_settled = asyncio.Event()
    attempts = 0

    async def retained_owner() -> None:
        nonlocal attempts
        attempts += 1
        entered.set()
        await release.wait()

    async def peer_owner() -> None:
        peer_settled.set()

    settlement = asyncio.create_task(
        _settle_engine_shutdown_phase(
            (
                _EngineShutdownOwner("retained", retained_owner),
                _EngineShutdownOwner("peer", peer_owner),
            ),
            logging.getLogger("test.engine-shutdown.cancellation"),
            retry_delay_s=0.0,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=0.5)

    settlement.cancel()
    await asyncio.sleep(0)
    settlement.cancel()
    await asyncio.sleep(0)
    assert not settlement.done()
    assert peer_settled.is_set()

    release.set()
    failures = await asyncio.wait_for(settlement, timeout=0.5)
    assert attempts == 1
    assert len(failures) == 1
    assert failures[0][0] == "phase_wait"
    assert isinstance(failures[0][1], asyncio.CancelledError)


def test_engine_shutdown_owner_and_phase_reject_ambiguous_identity() -> None:
    with pytest.raises(ValueError, match="invalid"):
        _EngineShutdownOwner("owner\nforged", lambda: None)
    with pytest.raises(ValueError, match="invalid"):
        _EngineShutdownOwner("", lambda: None)
    with pytest.raises(ValueError, match="invalid"):
        _EngineShutdownOwner("owner", None)  # type: ignore[arg-type]

    async def exercise_duplicate_labels() -> None:
        with pytest.raises(ValueError, match="unique"):
            await _settle_engine_shutdown_phase(
                (
                    _EngineShutdownOwner("same", lambda: None),
                    _EngineShutdownOwner("same", lambda: None),
                ),
                logging.getLogger("test.engine-shutdown.labels"),
            )

    asyncio.run(exercise_duplicate_labels())


async def test_engine_shutdown_plan_preserves_dependency_order_and_aggregates_deferred_failures() -> None:
    first_attempt_entered = asyncio.Event()
    release_first_attempt = asyncio.Event()
    events: list[str] = []
    transient_attempts = 0

    async def transient_mutation() -> None:
        nonlocal transient_attempts
        transient_attempts += 1
        events.append(f"mutation:{transient_attempts}:start")
        if transient_attempts == 1:
            first_attempt_entered.set()
            await release_first_attempt.wait()
            events.append("mutation:1:failed")
            raise OSError("retained mutation failed once")
        events.append("mutation:2:settled")

    async def mutation_peer() -> None:
        events.append("mutation-peer:settled")

    async def terminal_failure() -> None:
        events.append("producer:terminal-failure")
        raise _EngineShutdownSettledFailure(ValueError("producer terminal failure"))

    async def producer_peer() -> None:
        events.append("producer-peer:settled")

    async def terminal_dependency() -> None:
        events.append("terminal-dependency:settled")

    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    plan = asyncio.create_task(
        _settle_engine_shutdown_plan(
            (
                _EngineShutdownLayer(
                    "retained_mutations",
                    (
                        _EngineShutdownOwner("transient_mutation", transient_mutation),
                        _EngineShutdownOwner("mutation_peer", mutation_peer),
                    ),
                ),
                _EngineShutdownLayer(
                    "producer_services",
                    (
                        _EngineShutdownOwner("terminal_failure", terminal_failure),
                        _EngineShutdownOwner("producer_peer", producer_peer),
                    ),
                ),
                _EngineShutdownLayer(
                    "terminal_dependencies",
                    (_EngineShutdownOwner("writer", terminal_dependency),),
                ),
            ),
            logging.getLogger("test.engine-shutdown.plan"),
            retry_delay_s=999.0,
            sleep=record_delay,
        )
    )
    await asyncio.wait_for(first_attempt_entered.wait(), timeout=0.5)
    await asyncio.sleep(0)
    assert "mutation-peer:settled" in events
    assert not any(event.startswith("producer") for event in events)

    plan.cancel()
    await asyncio.sleep(0)
    plan.cancel()
    await asyncio.sleep(0)
    assert not plan.done()
    release_first_attempt.set()

    failures = await asyncio.wait_for(plan, timeout=0.5)
    assert transient_attempts == 2
    assert delays == [1.0]
    producer_start = min(index for index, event in enumerate(events) if event.startswith("producer"))
    mutation_end = events.index("mutation:2:settled")
    terminal_start = events.index("terminal-dependency:settled")
    assert mutation_end < producer_start < terminal_start
    assert events.count("producer:terminal-failure") == 1
    assert [(label, type(failure), str(failure)) for label, failure in failures] == [
        ("retained_mutations.phase_wait", asyncio.CancelledError, ""),
        ("retained_mutations.transient_mutation", OSError, "retained mutation failed once"),
        ("producer_services.terminal_failure", ValueError, "producer terminal failure"),
    ]


async def test_engine_teardown_sequence_cannot_finalize_before_off_and_plan_settle(monkeypatch) -> None:
    ingress_entered = asyncio.Event()
    release_ingress = asyncio.Event()
    plan_entered = asyncio.Event()
    release_plan = asyncio.Event()

    async def settle_ingress(*_args) -> tuple[BaseException, ...]:
        ingress_entered.set()
        await release_ingress.wait()
        return ()

    async def settle_plan(*_args) -> tuple[tuple[str, BaseException], ...]:
        plan_entered.set()
        await release_plan.wait()
        return ()

    monkeypatch.setattr(engine_module, "_settle_command_server_before_safety", settle_ingress)
    monkeypatch.setattr(engine_module, "_settle_engine_shutdown_plan", settle_plan)
    sequence = _EngineTeardownSequence(
        command_ingress=SimpleNamespace(terminal_failure=None),  # type: ignore[arg-type]
        safety_manager=object(),
        logger_=logging.getLogger("cryodaq.test.engine-teardown-order"),
        ingress_terminal_failure=None,
    )

    with pytest.raises(RuntimeError, match="cannot finalize before"):
        sequence.finalize()
    with pytest.raises(RuntimeError, match="out of sequence"):
        await sequence.settle_plan(())

    ingress_owner = asyncio.create_task(sequence.settle_ingress_off())
    await ingress_entered.wait()
    assert sequence.state is _EngineTeardownState.NEW
    with pytest.raises(RuntimeError, match="cannot finalize before"):
        sequence.finalize()
    release_ingress.set()
    await ingress_owner
    assert sequence.state is _EngineTeardownState.INGRESS_OFF_SETTLED

    plan_owner = asyncio.create_task(sequence.settle_plan(()))
    await plan_entered.wait()
    assert sequence.state is _EngineTeardownState.INGRESS_OFF_SETTLED
    with pytest.raises(RuntimeError, match="cannot finalize before"):
        sequence.finalize()
    release_plan.set()
    await plan_owner

    assert sequence.state is _EngineTeardownState.PLAN_SETTLED
    assert sequence.finalize() is None


async def test_engine_teardown_sequence_terminal_failure_wins_after_all_failures_settle(
    monkeypatch,
    caplog,
) -> None:
    ingress_failure = OSError("ingress recovered")
    plan_failure = ValueError("plan recovered")
    sticky_failure = ZMQCommandIngressTerminalFailure(
        endpoint="ordinary",
        stage="loop_closed",
        failure_type="RuntimeError",
    )
    pair = SimpleNamespace(terminal_failure=None)

    async def settle_ingress(*_args) -> tuple[BaseException, ...]:
        return (ingress_failure,)

    async def settle_plan(*_args) -> tuple[tuple[str, BaseException], ...]:
        pair.terminal_failure = sticky_failure
        return (("terminal.writer", plan_failure),)

    monkeypatch.setattr(engine_module, "_settle_command_server_before_safety", settle_ingress)
    monkeypatch.setattr(engine_module, "_settle_engine_shutdown_plan", settle_plan)
    sequence = _EngineTeardownSequence(
        command_ingress=pair,  # type: ignore[arg-type]
        safety_manager=object(),
        logger_=logging.getLogger("cryodaq.test.engine-teardown-terminal"),
        ingress_terminal_failure=None,
    )

    await sequence.settle_ingress_off()
    await sequence.settle_plan(())
    with caplog.at_level(logging.ERROR), pytest.raises(ZMQCommandIngressTerminalError) as raised:
        sequence.finalize()

    assert raised.value.failure is sticky_failure
    assert "command_server,terminal.writer" in caplog.text


def test_run_engine_binds_root_to_one_typed_teardown_sequence() -> None:
    source = inspect.getsource(engine_module._run_engine)
    bindings = (
        "teardown_sequence = _EngineTeardownSequence(",
        "await teardown_sequence.settle_ingress_off()",
        "await teardown_sequence.settle_plan(tuple(shutdown_layers))",
        "teardown_sequence.finalize()",
    )
    for binding in bindings:
        assert source.count(binding) == 1
    constructor, ingress, plan, final = (source.index(binding) for binding in bindings)

    assert constructor < ingress < plan < final
    assert "await _settle_command_server_before_safety(" not in source
    assert "await _settle_engine_shutdown_plan(" not in source


def test_engine_completion_banner_follows_successful_teardown_finalization() -> None:
    source = inspect.getsource(engine_module._run_engine)

    assert source.count("teardown_sequence.finalize()") == 1
    assert source.count("CryoDAQ Engine завершён") == 1
    assert source.index("teardown_sequence.finalize()") < source.index("CryoDAQ Engine завершён")


async def test_engine_startup_rollback_resists_repeated_cancellation_until_every_owner_settles() -> None:
    startup = _EngineStartupRollback()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    events: list[str] = []

    async def first_cleanup() -> None:
        events.append("first-cleanup")

    async def second_cleanup() -> None:
        events.append("second-cleanup-entered")
        cleanup_entered.set()
        await release_cleanup.wait()
        events.append("second-cleanup-settled")

    startup.add("first", first_cleanup)
    startup.add("second", second_cleanup)
    owner = asyncio.create_task(startup.rollback())
    await asyncio.wait_for(cleanup_entered.wait(), timeout=0.1)

    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    assert events == ["second-cleanup-entered"]

    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await owner

    assert events == [
        "second-cleanup-entered",
        "second-cleanup-settled",
        "first-cleanup",
    ]
    await startup.rollback()
    assert events == [
        "second-cleanup-entered",
        "second-cleanup-settled",
        "first-cleanup",
    ]


async def test_engine_startup_rollback_awaits_future_returning_cleanup_before_settlement() -> None:
    startup = _EngineStartupRollback()
    cleanup_result: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    cleanup_invoked = asyncio.Event()
    events: list[str] = []

    def cleanup() -> asyncio.Future[None]:
        events.append("cleanup-invoked")
        cleanup_invoked.set()
        return cleanup_result

    startup.add("future-owner", cleanup)
    rollback = asyncio.create_task(startup.rollback())
    await asyncio.wait_for(cleanup_invoked.wait(), timeout=0.1)

    assert events == ["cleanup-invoked"]
    assert not rollback.done()
    with pytest.raises(RuntimeError, match="already settled"):
        startup.add("late-owner", lambda: None)

    cleanup_result.set_result(None)
    await rollback
    await startup.rollback()
    assert events == ["cleanup-invoked"]


async def test_engine_startup_cancellation_settles_initialization_before_writer_rollback() -> None:
    startup = _EngineStartupRollback()
    initialization_entered = asyncio.Event()
    release_initialization = asyncio.Event()
    events: list[str] = []

    async def writer_stop() -> None:
        events.append("writer-stop")

    async def initialize_operator_log_idempotency() -> None:
        initialization_entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("initialization-cancel-observed")
            await release_initialization.wait()
            events.append("initialization-settled")
            raise

    startup.add("sqlite-writer", writer_stop)
    owner = asyncio.create_task(startup.guard(initialize_operator_log_idempotency()))
    await asyncio.wait_for(initialization_entered.wait(), timeout=0.1)

    owner.cancel()
    await asyncio.sleep(0)
    assert events == ["initialization-cancel-observed"]

    release_initialization.set()
    with pytest.raises(asyncio.CancelledError):
        await owner

    assert events == [
        "initialization-cancel-observed",
        "initialization-settled",
        "writer-stop",
    ]


@pytest.mark.asyncio
async def test_run_engine_registers_safety_tasks_before_installing_startup_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real startup path must advance past live safety-task registration."""

    class _ReachedPostRegistrationStartup(RuntimeError):
        pass

    registered: list[tuple[str, bool]] = []
    original_register = TaskSupervisor.register

    def _record_register(
        self: TaskSupervisor,
        name: str,
        task: asyncio.Task[object],
        *args: object,
        **kwargs: object,
    ) -> asyncio.Task[object]:
        registered.append((name, not task.done()))
        return original_register(self, name, task, *args, **kwargs)

    def _stop_after_registration(*_args: object, **_kwargs: object) -> None:
        raise _ReachedPostRegistrationStartup

    monkeypatch.setattr(TaskSupervisor, "register", _record_register)
    monkeypatch.setattr(engine_module, "install_loop_exception_backstop", _stop_after_registration)

    try:
        with pytest.raises(_ReachedPostRegistrationStartup):
            await asyncio.wait_for(_run_engine(mock=True), timeout=5.0)
    except TimeoutError:  # pragma: no cover - exercised by the pre-fix startup hang
        raise AssertionError(
            "_run_engine awaited the live safety task during registration and "
            "never reached the post-registration startup step"
        ) from None

    assert [name for name, _was_live in registered] == ["safety_collect", "safety_monitor"]
    assert all(was_live for _name, was_live in registered)


@pytest.mark.asyncio
async def test_startup_call_does_not_await_a_returned_task() -> None:
    """Startup must RECEIVE a supervised task, never wait for it to finish.

    `inspect.isawaitable` is True for a Task, because a Task is a Future. A
    registration helper returns the task it just started, so awaiting that
    return value waits for a supervised loop that never ends. That blocked
    engine startup permanently at `supervisor.register("safety_collect", ...)`,
    so the SIGTERM handler installed further down was never reached and the
    engine died on the signal a real deployment sends -- the failure mode of the
    nightly bounded mock soak.

    Without the fix this test does not fail with an assertion; it HANGS, which
    is exactly what the engine did. The timeout is the assertion.
    """
    from cryodaq.engine import _EngineStartupRollback

    async def never_finishes() -> None:
        # An Event that nobody sets, not a sleep loop. The task must be
        # genuinely unresolvable for the whole test, because the defect being
        # pinned is that startup waits for something that never completes.
        await asyncio.Event().wait()

    startup = _EngineStartupRollback()
    running = asyncio.create_task(never_finishes())
    try:
        returned = await asyncio.wait_for(startup.call(lambda: running), timeout=5.0)
        assert returned is running, "startup.call must hand back the task itself, not its result"
        assert not running.done(), "the supervised task must still be running"
    except TimeoutError:  # pragma: no cover - the defect being pinned
        raise AssertionError(
            "startup.call awaited a returned Task and blocked; engine startup "
            "cannot complete when a registration helper returns a live task"
        ) from None
    finally:
        running.cancel()


@pytest.mark.asyncio
async def test_startup_call_still_awaits_a_coroutine() -> None:
    """The narrowing must not stop coroutines from being awaited."""
    from cryodaq.engine import _EngineStartupRollback

    async def produces_a_value() -> str:
        return "awaited"

    startup = _EngineStartupRollback()
    assert await startup.call(produces_a_value) == "awaited"
