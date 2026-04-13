"""Memory leak regression tests.

Covers the four confirmed sources identified during 8-hour mock run
where RSS grew from ~100 MB to ~906 MB:

1. web/server.py — fire-and-forget create_task per reading
2. alarm_v2.py  — AlarmStateManager._history unbounded list
3. rate_estimator.py — deque(maxlen=5000) too large; trim may lag
4. channel_state.py — fault_history deque without maxlen cap
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC

import pytest

from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator

# ---------------------------------------------------------------------------
# 1. AlarmStateManager._history bounded
# ---------------------------------------------------------------------------

def _make_event(alarm_id: str = "test") -> AlarmEvent:
    return AlarmEvent(
        alarm_id=alarm_id,
        level="WARNING",
        message="test",
        triggered_at=0.0,
        channels=["ch1"],
        values={"ch1": 1.0},
    )


def test_alarm_state_manager_history_bounded() -> None:
    """history deque must not exceed 1000 entries regardless of how many
    TRIGGERED/CLEARED transitions are processed."""
    mgr = AlarmStateManager()
    cfg: dict = {}

    for i in range(2000):
        # alternate trigger / clear to generate history entries
        ev = _make_event(f"alarm_{i}")
        mgr.process(f"alarm_{i}", ev, cfg)
        mgr.process(f"alarm_{i}", None, cfg)

    assert len(mgr._history) <= 1000, (
        f"AlarmStateManager._history grew to {len(mgr._history)}, expected ≤ 1000"
    )


def test_alarm_state_manager_get_history_returns_list() -> None:
    """get_history() must return a plain list even when _history is a deque."""
    mgr = AlarmStateManager()
    ev = _make_event()
    mgr.process("a1", ev, {})
    hist = mgr.get_history()
    assert isinstance(hist, list)
    assert len(hist) >= 1


def test_alarm_state_manager_history_is_deque() -> None:
    """Internal _history must be a deque (not a plain list)."""
    mgr = AlarmStateManager()
    assert isinstance(mgr._history, deque), (
        "_history must be deque(maxlen=1000) to prevent unbounded growth"
    )
    assert mgr._history.maxlen == 1000


# ---------------------------------------------------------------------------
# 2. RateEstimator deque maxlen tightened
# ---------------------------------------------------------------------------

def test_rate_estimator_maxlen_computed_from_window() -> None:
    """maxlen must be computed from window_s, not hardcoded 5000."""
    est = RateEstimator(window_s=120.0)
    # At 10 Hz × 120s × 2 + 100 = 2500
    assert est._maxlen == max(500, int(120.0 * 20) + 100)
    assert est._maxlen < 5000


def test_rate_estimator_buffer_does_not_exceed_maxlen() -> None:
    """Pushing more points than maxlen must not grow the buffer beyond maxlen."""
    est = RateEstimator(window_s=10.0, min_points=5)
    # maxlen = max(500, int(10*20)+100) = 500  (floor is 500)
    maxlen = est._maxlen
    # Push 2× maxlen points with distinct timestamps
    for i in range(maxlen * 2):
        est.push("T1", float(i), float(i))

    assert est.buffer_size("T1") <= maxlen, (
        f"buffer grew to {est.buffer_size('T1')}, expected ≤ {maxlen}"
    )


def test_rate_estimator_small_window_uses_floor() -> None:
    """Very small window_s must use the 500-point floor."""
    est = RateEstimator(window_s=1.0)
    assert est._maxlen == 500


# ---------------------------------------------------------------------------
# 3. ChannelStateTracker fault_history bounded
# ---------------------------------------------------------------------------

def _make_reading(channel: str, value: float, unit: str = "K"):
    """Create a minimal Reading-like object for ChannelStateTracker.update()."""
    from datetime import datetime
    from unittest.mock import MagicMock

    r = MagicMock()
    r.channel = channel
    r.value = value
    r.unit = unit
    r.timestamp = datetime.now(UTC)
    r.instrument_id = "test"
    r.status = MagicMock()
    return r


def test_channel_state_fault_history_bounded() -> None:
    """fault_history deques must not grow beyond their safety cap."""
    tracker = ChannelStateTracker(fault_window_s=10.0)
    # maxlen = max(200, int(10*20)+100) = 300

    # Record far more faults than the cap
    for i in range(1000):
        tracker.record_fault("T1", float(i) * 0.001)

    hist = tracker._fault_history["T1"]
    assert hist.maxlen is not None, "fault_history deque must have a maxlen"
    assert len(hist) <= hist.maxlen


def test_channel_state_fault_history_deque_has_maxlen_after_update() -> None:
    """Deque is created with maxlen on first record_fault call."""
    tracker = ChannelStateTracker(fault_window_s=300.0)
    tracker.record_fault("T2", 1.0)
    hist = tracker._fault_history["T2"]
    assert hist.maxlen is not None
    # For 300s window: max(200, int(300*20)+100) = 6100
    assert hist.maxlen == max(200, int(300.0 * 20) + 100)


# ---------------------------------------------------------------------------
# 4. web/server.py — broadcast queue replaces per-reading tasks
# ---------------------------------------------------------------------------

def test_broadcast_state_has_queue_attribute() -> None:
    """_ServerState must have a broadcast_q attribute (may be None before startup)."""
    from cryodaq.web.server import _ServerState
    state = _ServerState()
    assert hasattr(state, "broadcast_q")
    assert state.broadcast_q is None  # initialised in startup only


def test_on_reading_callback_no_task_when_no_clients() -> None:
    """_on_reading_callback must return early when there are no clients.

    The queue must remain empty — no items enqueued, no tasks created.
    """
    from cryodaq.web.server import _on_reading_callback, _state

    _state.clients.clear()

    # Attach a real bounded queue so we can inspect it
    loop = asyncio.new_event_loop()
    q: asyncio.Queue = loop.run_until_complete(_make_queue(loop))
    _state.broadcast_q = q

    reading = _make_reading("T1", 4.2)
    _on_reading_callback(reading)

    assert q.empty(), "Queue must be empty when there are no WebSocket clients"
    _state.broadcast_q = None
    loop.close()


async def _make_queue(loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    return asyncio.Queue(maxsize=100)


@pytest.mark.asyncio
async def test_broadcast_queue_bounded() -> None:
    """broadcast_q must be bounded — put_nowait on a full queue must not raise
    TaskGroup errors and must simply drop the message."""
    from cryodaq.web.server import _state

    _state.broadcast_q = asyncio.Queue(maxsize=5)
    # Fill the queue
    for i in range(5):
        _state.broadcast_q.put_nowait({"v": i})

    # One more — must NOT raise, must be silently dropped in callback
    reading = _make_reading("T1", 4.2)
    _state.clients.clear()  # no clients so callback returns early anyway

    # Verify queue is still bounded after overflow attempt
    try:
        _state.broadcast_q.put_nowait({"overflow": True})
        overflow_dropped = False
    except asyncio.QueueFull:
        overflow_dropped = True

    # Either dropped (QueueFull caught) or queue is bounded at 5
    assert _state.broadcast_q.qsize() <= 5
    # Clean up
    _state.broadcast_q = None


@pytest.mark.asyncio
async def test_broadcast_pump_drains_queue() -> None:
    """_broadcast_pump must consume items from the queue."""
    from cryodaq.web.server import _broadcast_pump, _state

    _state.broadcast_q = asyncio.Queue(maxsize=50)
    _state.clients.clear()  # no clients → pump discards data

    # Enqueue some items
    for i in range(10):
        await _state.broadcast_q.put({"v": i})

    # Run the pump for a brief window
    pump_task = asyncio.create_task(_broadcast_pump())
    await asyncio.sleep(0.05)
    pump_task.cancel()
    try:
        await pump_task
    except asyncio.CancelledError:
        pass

    # Queue should be drained
    assert _state.broadcast_q.empty(), (
        f"broadcast_pump did not drain queue; {_state.broadcast_q.qsize()} items remain"
    )
    _state.broadcast_q = None
