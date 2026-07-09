"""A3b — engine-side ring buffer of alarm_fired events (GUI sound poller).

Covers the two extracted, importable pieces so the PRODUCTION logic is
exercised directly (same rationale as ``_alarm_v2_feed_loop`` in
test_engine_task_supervision.py):

  * ``_AlarmRingBuffer`` — record/since bookkeeping the ``recent_alarms``
    command reads from.
  * ``_alarm_ring_buffer_loop`` — the per-event queue-drain guard that
    keeps the feed alive when a single bad event raises.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.engine import _alarm_ring_buffer_loop, _AlarmRingBuffer

# ---------------------------------------------------------------------------
# Part (a): _AlarmRingBuffer
# ---------------------------------------------------------------------------


def _alarm_event(alarm_id: str = "a1", level: str = "WARNING", message: str = "m") -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={"alarm_id": alarm_id, "level": level, "message": message},
        experiment_id=None,
    )


def test_empty_buffer_since_zero() -> None:
    ring = _AlarmRingBuffer()
    assert ring.since(0) == {"seq": 0, "alarms": []}


def test_record_assigns_increasing_seq() -> None:
    ring = _AlarmRingBuffer()
    ring.record(_alarm_event("a1"))
    ring.record(_alarm_event("a2"))
    result = ring.since(0)
    assert result["seq"] == 2
    assert [a["seq"] for a in result["alarms"]] == [1, 2]
    assert [a["alarm_id"] for a in result["alarms"]] == ["a1", "a2"]


def test_since_filters_already_seen() -> None:
    ring = _AlarmRingBuffer()
    ring.record(_alarm_event("a1"))
    ring.record(_alarm_event("a2"))
    ring.record(_alarm_event("a3"))
    result = ring.since(2)
    assert result["seq"] == 3
    assert [a["alarm_id"] for a in result["alarms"]] == ["a3"]


def test_since_head_returns_no_new_alarms() -> None:
    ring = _AlarmRingBuffer()
    ring.record(_alarm_event("a1"))
    result = ring.since(1)
    assert result == {"seq": 1, "alarms": []}


def test_entry_shape_matches_command_contract() -> None:
    ring = _AlarmRingBuffer()
    ring.record(_alarm_event("safety_fault_interlock", "CRITICAL", "Safety fault"))
    entry = ring.since(0)["alarms"][0]
    assert set(entry) == {"seq", "alarm_id", "level", "message", "ts"}
    assert entry["level"] == "CRITICAL"
    assert isinstance(entry["ts"], float)


def test_ring_buffer_bounded_by_maxlen() -> None:
    ring = _AlarmRingBuffer(maxlen=3)
    for i in range(5):
        ring.record(_alarm_event(f"a{i}"))
    result = ring.since(0)
    # Oldest two (seq 1, 2) fell off the ring; only the last 3 remain.
    assert [a["seq"] for a in result["alarms"]] == [3, 4, 5]
    assert result["seq"] == 5


# ---------------------------------------------------------------------------
# Part (b): _alarm_ring_buffer_loop
# ---------------------------------------------------------------------------


async def test_loop_records_alarm_fired_events() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    ring = _AlarmRingBuffer()
    task = asyncio.create_task(_alarm_ring_buffer_loop(queue, ring))
    try:
        await bus.publish(_alarm_event("a1"))
        for _ in range(20):
            if ring.since(0)["alarms"]:
                break
            await asyncio.sleep(0)
        assert [a["alarm_id"] for a in ring.since(0)["alarms"]] == ["a1"]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_loop_ignores_non_alarm_fired_events() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    ring = _AlarmRingBuffer()
    task = asyncio.create_task(_alarm_ring_buffer_loop(queue, ring))
    try:
        await bus.publish(
            EngineEvent(
                event_type="phase_transition",
                timestamp=datetime.now(UTC),
                payload={},
                experiment_id=None,
            )
        )
        await bus.publish(_alarm_event("a1"))
        for _ in range(20):
            if ring.since(0)["alarms"]:
                break
            await asyncio.sleep(0)
        assert [a["alarm_id"] for a in ring.since(0)["alarms"]] == ["a1"]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_loop_survives_a_bad_event_and_keeps_feeding() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    ring = _AlarmRingBuffer()

    calls = {"n": 0}
    real_record = ring.record

    def _flaky_record(event: EngineEvent) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        real_record(event)

    ring.record = _flaky_record  # type: ignore[method-assign]

    task = asyncio.create_task(_alarm_ring_buffer_loop(queue, ring))
    try:
        await bus.publish(_alarm_event("bad"))
        await bus.publish(_alarm_event("good"))
        for _ in range(20):
            if ring.since(0)["alarms"]:
                break
            await asyncio.sleep(0)
        assert [a["alarm_id"] for a in ring.since(0)["alarms"]] == ["good"]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_loop_exits_cleanly_on_cancellation() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    ring = _AlarmRingBuffer()
    task = asyncio.create_task(_alarm_ring_buffer_loop(queue, ring))
    await asyncio.sleep(0)
    task.cancel()
    await task  # must not raise — CancelledError is swallowed, matching _alarm_v2_feed_loop


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
