"""A2 — task supervision for long-lived engine tasks.

Covers the two extracted, importable helpers so the PRODUCTION supervision
logic is exercised directly (same rationale as ``_drain_dispatch_tasks``):

  * ``_alarm_v2_feed_loop`` — the per-reading guard that keeps the alarm-v2
    state feed alive when a single bad reading raises inside ``tracker.update``.
  * ``_handle_supervised_task_exit`` — the done-callback decision core:
    CRITICAL + operator alarm + exponential-backoff restart on unexpected
    death, and FAULT-latch for the two safety tasks after 2 failed restarts.
    Ordinary clean shutdown / cancellation must never restart or alarm. A
    safety-critical child returning or being cancelled while the engine is
    live is authority loss and must alarm/restart just like an exception.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_manager import SafetyShutdownUnverifiedError
from cryodaq.engine import (
    _SAFETY_TASK_MAX_RESTARTS,
    _SUPERVISE_BACKOFF_BASE_S,
    _SUPERVISE_RESET_WINDOW_S,
    _alarm_v2_feed_loop,
    _handle_supervised_task_exit,
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


async def test_cancelled_task_is_ignored() -> None:
    task = await _cancelled_task()
    verdict, calls, _ = _invoke(task)
    assert verdict == "ignored"
    assert calls == {"alarm": [], "restart": [], "fault": []}


async def test_shutdown_never_restarts() -> None:
    task = await _failed_task(RuntimeError("boom"))
    verdict, calls, _ = _invoke(task, stopping=True)
    assert verdict == "ignored"
    assert calls["restart"] == [] and calls["alarm"] == []


async def test_clean_return_is_ignored() -> None:
    task = await _clean_task()
    verdict, calls, _ = _invoke(task)
    assert verdict == "ignored"
    assert calls["alarm"] == []


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


async def test_rapid_triple_crash_still_latches_byte_identical() -> None:
    """Safe-direction behavior for a genuine rapid crash loop (no healthy run
    between failures) is unchanged: latches FAULT after
    _SAFETY_TASK_MAX_RESTARTS consecutive restarts."""
    counts: dict[str, int] = {}
    calls = _spy_actions()
    for expected_count in (1, 2):
        task = await _failed_task(RuntimeError("safety down"))
        verdict, calls, counts = _invoke(task, counts=counts, calls=calls, safety=True)
        assert verdict == "restart"
        assert counts["widget"] == expected_count
    assert counts["widget"] == _SAFETY_TASK_MAX_RESTARTS

    task = await _failed_task(RuntimeError("safety down"))
    verdict, calls, counts = _invoke(task, counts=counts, calls=calls, safety=True)
    assert verdict == "fault_latch"
    assert calls["fault"] and calls["fault"][-1][0] == "widget"
    assert len(calls["restart"]) == _SAFETY_TASK_MAX_RESTARTS


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
