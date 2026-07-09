"""A2 — task supervision for long-lived engine tasks.

Covers the two extracted, importable helpers so the PRODUCTION supervision
logic is exercised directly (same rationale as ``_drain_dispatch_tasks``):

  * ``_alarm_v2_feed_loop`` — the per-reading guard that keeps the alarm-v2
    state feed alive when a single bad reading raises inside ``tracker.update``.
  * ``_handle_supervised_task_exit`` — the done-callback decision core:
    CRITICAL + operator alarm + exponential-backoff restart on unexpected
    death, and FAULT-latch for the two safety tasks after 2 failed restarts.
    Clean shutdown / cancellation must never restart or alarm.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.engine import (
    _SAFETY_TASK_MAX_RESTARTS,
    _SUPERVISE_BACKOFF_BASE_S,
    _SUPERVISE_RESET_WINDOW_S,
    _alarm_v2_feed_loop,
    _handle_supervised_task_exit,
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
