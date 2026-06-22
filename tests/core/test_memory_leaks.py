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
    """Buffer cap must be derived from window_s, not hardcoded.

    Two independent window cases — neither can hold under a single fixed cap.
    We prove the cap behaviorally by pushing more samples than any reasonable
    fixed maxlen and observing the retained buffer length stays bounded.
    No private formula is re-derived; only the public buffer_size() is used.
    """
    # Case 1: large window — push well above any fixed cap and assert retained size is finite
    est_large = RateEstimator(window_s=120.0)
    n_large = 5000 + 200  # exceeds any sane fixed 5000 cap
    for i in range(n_large):
        est_large.push("T1", float(i), float(i))
    size_large = est_large.buffer_size("T1")
    assert size_large < n_large, (
        f"Large-window buffer not capped: retained {size_large} of {n_large} pushed samples"
    )

    # Case 2: small window — its cap must be strictly smaller than the large-window cap
    est_small = RateEstimator(window_s=10.0)
    n_small = 5000 + 200
    for i in range(n_small):
        est_small.push("T1", float(i), float(i))
    size_small = est_small.buffer_size("T1")
    assert size_small < size_large, (
        f"Small-window buffer ({size_small}) is not smaller than large-window buffer "
        f"({size_large}) — cap appears to be independent of window_s"
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
    """fault_history deque must be bounded from the first fault onward.

    We verify behaviorally: after driving far more faults than any sane cap,
    the retained count stays at or below the deque's own maxlen. No private
    formula is re-derived — only the public record_fault() path and the
    deque's own maxlen attribute are used.
    """
    tracker = ChannelStateTracker(fault_window_s=300.0)
    tracker.record_fault("T2", 1.0)
    hist = tracker._fault_history["T2"]
    assert hist.maxlen is not None, "fault_history deque must have a maxlen after first fault"

    # Push far more faults than any reasonable cap — deque must stay bounded
    n_push = 15_000  # well above max(200, int(300*20)+100) = 6100
    for i in range(n_push):
        tracker.record_fault("T2", float(i) * 0.001)
    assert len(hist) <= hist.maxlen, (
        f"fault_history grew to {len(hist)}, exceeds its own maxlen={hist.maxlen}"
    )
    assert hist.maxlen < n_push, (
        f"maxlen={hist.maxlen} is not smaller than pushed count {n_push} — "
        "cap may not be constraining growth"
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
    """The REAL _broadcast_pump must consume items from _state.broadcast_q.

    We wire the production pump directly — no local reimplementation.
    With no clients, the pump discards each item immediately after dequeueing.
    We poll until the queue is empty (deadline-based, no fixed sleep).
    """
    from cryodaq.web.server import _broadcast_pump, _state

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _state.broadcast_q = q
    _state.clients.clear()  # no clients → pump discards items

    # Enqueue 10 items before starting the pump
    for i in range(10):
        await q.put({"v": i})

    pump_task = asyncio.create_task(_broadcast_pump(), name="test_broadcast_pump")
    try:
        # Deadline-poll: wait up to 2 s for the queue to drain
        deadline = asyncio.get_event_loop().time() + 2.0
        while not q.empty():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(0.01)

        assert q.empty(), (
            f"production _broadcast_pump did not drain queue; {q.qsize()} items remain"
        )
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        _state.broadcast_q = None
