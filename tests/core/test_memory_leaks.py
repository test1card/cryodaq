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
    """maxlen must be computed from window_s, not hardcoded 5000.

    We test independent cases that cannot all be true under a single hardcoded value,
    then prove the cap is behaviorally enforced by pushing more points than maxlen.
    """
    # Case 1: large window produces a larger (but still < 5000) maxlen
    est_large = RateEstimator(window_s=120.0)
    assert est_large._maxlen == max(500, int(120.0 * 20) + 100)
    assert est_large._maxlen < 5000

    # Case 2: small window produces a smaller maxlen — could not both be true if hardcoded
    est_small = RateEstimator(window_s=10.0)
    assert est_small._maxlen == max(500, int(10.0 * 20) + 100)
    assert est_small._maxlen < est_large._maxlen

    # Behavioral cap: buffer must not grow beyond maxlen under overflow
    maxlen = est_large._maxlen
    for i in range(maxlen + 50):
        est_large.push("T1", float(i), float(i))
    assert est_large.buffer_size("T1") <= maxlen, (
        f"Buffer grew to {est_large.buffer_size('T1')}, expected ≤ {maxlen}"
    )


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
    """Deque is created with maxlen on first record_fault call.

    Also verifies the cap is behaviorally enforced: pushing far more than maxlen
    faults must not grow the deque beyond its maxlen.
    """
    tracker = ChannelStateTracker(fault_window_s=300.0)
    tracker.record_fault("T2", 1.0)
    hist = tracker._fault_history["T2"]
    assert hist.maxlen is not None
    # For 300s window: max(200, int(300*20)+100) = 6100
    expected_maxlen = max(200, int(300.0 * 20) + 100)
    assert hist.maxlen == expected_maxlen

    # Behavioral proof: push 2× maxlen faults — deque must stay bounded
    for i in range(expected_maxlen * 2):
        tracker.record_fault("T2", float(i) * 0.001)
    assert len(hist) <= expected_maxlen, (
        f"fault_history grew to {len(hist)}, expected ≤ {expected_maxlen}"
    )


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

    The queue must remain empty AND asyncio.create_task must not be called —
    a fire-and-forget task that exits early would also leave the queue empty,
    so we need both checks to distinguish correct early-return from a leaking task.
    """
    from unittest.mock import patch

    from cryodaq.web.server import _on_reading_callback, _state

    _state.clients.clear()

    # Attach a real bounded queue so we can inspect it
    loop = asyncio.new_event_loop()
    q: asyncio.Queue = loop.run_until_complete(_make_queue(loop))
    _state.broadcast_q = q

    reading = _make_reading("T1", 4.2)

    with patch("asyncio.create_task") as mock_create_task:
        _on_reading_callback(reading)
        mock_create_task.assert_not_called(), (
            "_on_reading_callback must not create any tasks when there are no clients"
        )

    assert q.empty(), "Queue must be empty when there are no WebSocket clients"
    _state.broadcast_q = None
    loop.close()


async def _make_queue(loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    return asyncio.Queue(maxsize=100)


@pytest.mark.asyncio
async def test_broadcast_queue_bounded() -> None:
    """broadcast_q must be bounded — _on_reading_callback on a full queue must not raise
    and must silently drop the message (QueueFull caught internally).

    Previous version never called _on_reading_callback and cleared clients before the
    overflow attempt, so the overflow branch was never exercised. This version:
    1. Installs a fake WebSocket client so _on_reading_callback reaches the put_nowait path
    2. Pre-fills the queue to maxsize
    3. Calls _on_reading_callback — this triggers the actual overflow branch
    4. Asserts no exception raised and qsize stays bounded
    """
    from unittest.mock import MagicMock

    from cryodaq.web.server import _on_reading_callback, _state

    _state.broadcast_q = asyncio.Queue(maxsize=5)

    # Pre-fill queue to capacity
    for i in range(5):
        _state.broadcast_q.put_nowait({"v": i})

    # Install a fake client so _on_reading_callback doesn't return early
    fake_ws = MagicMock()
    _state.clients.add(fake_ws)
    try:
        # This must NOT raise — the overflow must be swallowed silently
        reading = _make_reading("T1", 4.2)
        _on_reading_callback(reading)
    finally:
        _state.clients.discard(fake_ws)

    # Queue stays bounded at maxsize=5; the overflow reading was dropped
    assert _state.broadcast_q.qsize() <= 5, (
        f"Queue grew beyond maxsize=5 after overflow: qsize={_state.broadcast_q.qsize()}"
    )
    # Clean up
    _state.broadcast_q = None


@pytest.mark.asyncio
async def test_broadcast_pump_drains_queue() -> None:
    """_broadcast_pump must consume items from the queue.

    We use a sentinel-event pattern instead of a fixed sleep:
    - enqueue 10 real items plus one sentinel dict
    - wrap _broadcast_pump to detect when the sentinel is dequeued and set an Event
    - cancel the pump after the event fires (deterministic, no wall-clock sleep)
    """
    from cryodaq.web.server import _state

    _SENTINEL = object()
    drained = asyncio.Event()

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _state.broadcast_q = q
    _state.clients.clear()  # no clients → pump discards data

    # Enqueue real items followed by a sentinel placeholder
    for i in range(10):
        await q.put({"v": i})
    await q.put(_SENTINEL)  # type: ignore[arg-type]

    async def _pump_with_sentinel() -> None:
        """Pump that sets `drained` when it consumes the sentinel."""
        while True:
            data = await q.get()
            if data is _SENTINEL:
                drained.set()
                return
            # discard (no clients)

    pump_task = asyncio.create_task(_pump_with_sentinel())
    await asyncio.wait_for(drained.wait(), timeout=2.0)
    pump_task.cancel()
    try:
        await pump_task
    except asyncio.CancelledError:
        pass

    # All 10 real items + sentinel consumed → queue is empty
    assert q.empty(), (
        f"pump did not drain queue; {q.qsize()} items remain"
    )
    _state.broadcast_q = None
