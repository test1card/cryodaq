"""Tests for ChannelStateTracker."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.drivers.base import Reading


def _reading(channel: str, value: float, unit: str = "K",
             instrument_id: str = "LS218", ts: float | None = None) -> Reading:
    if ts is None:
        ts = time.time()
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return Reading(
        timestamp=dt,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
    )


def test_update_and_get() -> None:
    tracker = ChannelStateTracker()
    r = _reading("T1", 4.19)
    tracker.update(r)
    state = tracker.get("T1")
    assert state is not None
    assert state.channel == "T1"
    assert abs(state.value - 4.19) < 1e-9
    assert state.unit == "K"
    assert state.instrument_id == "LS218"
    assert not state.is_stale


def test_unknown_channel_returns_none() -> None:
    tracker = ChannelStateTracker()
    assert tracker.get("nonexistent") is None


def test_stale_detection() -> None:
    tracker = ChannelStateTracker(stale_timeout_s=5.0)
    old_ts = time.time() - 10.0  # 10 секунд назад
    r = _reading("T1", 4.2, ts=old_ts)
    tracker.update(r)
    state = tracker.get("T1")
    assert state is not None
    assert state.is_stale


def test_fresh_not_stale() -> None:
    tracker = ChannelStateTracker(stale_timeout_s=30.0)
    r = _reading("T1", 4.2, ts=time.time())
    tracker.update(r)
    state = tracker.get("T1")
    assert state is not None
    assert not state.is_stale


def test_get_stale_channels() -> None:
    tracker = ChannelStateTracker(stale_timeout_s=5.0)
    now = time.time()
    tracker.update(_reading("T1", 4.2, ts=now - 10.0))  # stale
    tracker.update(_reading("T2", 4.5, ts=now))           # fresh
    stale = tracker.get_stale_channels()
    assert "T1" in stale
    assert "T2" not in stale


def test_get_stale_channels_custom_timeout() -> None:
    tracker = ChannelStateTracker(stale_timeout_s=30.0)
    now = time.time()
    tracker.update(_reading("T1", 4.2, ts=now - 60.0))  # 60s old → stale at 35s
    tracker.update(_reading("T2", 4.5, ts=now - 10.0))  # 10s old → not stale at 35s
    stale = tracker.get_stale_channels(timeout_s=35.0)
    assert "T1" in stale
    assert "T2" not in stale


def test_fault_recording_and_count() -> None:
    tracker = ChannelStateTracker(fault_window_s=300.0)
    now = time.time()
    # Fault reading: value > 350
    tracker.update(_reading("T3", 999.0, ts=now))
    assert tracker.get_fault_count("T3") >= 1


def test_normal_value_no_fault() -> None:
    tracker = ChannelStateTracker()
    tracker.update(_reading("T1", 4.2))
    assert tracker.get_fault_count("T1") == 0


def test_fault_expires_after_window() -> None:
    tracker = ChannelStateTracker(fault_window_s=10.0)
    old_ts = time.time() - 20.0  # давнее время
    tracker.record_fault("T5", old_ts)
    # Старый fault должен истечь при подсчёте
    assert tracker.get_fault_count("T5") == 0


def test_multiple_faults_counted() -> None:
    tracker = ChannelStateTracker(fault_window_s=300.0)
    now = time.time()
    tracker.record_fault("T6", now - 10)
    tracker.record_fault("T6", now - 20)
    tracker.record_fault("T6", now - 30)
    assert tracker.get_fault_count("T6") == 3


def test_fault_count_in_state() -> None:
    """fault_count_window обновляется в state при update."""
    tracker = ChannelStateTracker(fault_window_s=300.0)
    now = time.time()
    # Сначала пишем fault вручную
    tracker.record_fault("T7", now - 5)
    # Затем обновляем через reading (нормальное значение)
    tracker.update(_reading("T7", 4.2, ts=now))
    state = tracker.get("T7")
    assert state is not None
    assert state.fault_count_window == 1


def test_pressure_no_fault_for_normal_values() -> None:
    """Давление (unit=mbar) не вызывает fault при любом разумном значении."""
    tracker = ChannelStateTracker()
    tracker.update(_reading("P1", 1e-6, unit="mbar"))
    assert tracker.get_fault_count("P1") == 0


def test_channels_list() -> None:
    tracker = ChannelStateTracker()
    tracker.update(_reading("T1", 4.2))
    tracker.update(_reading("T2", 77.0))
    chs = tracker.channels()
    assert "T1" in chs
    assert "T2" in chs


def test_resolve_short_to_full() -> None:
    """Short ID '\u042212' resolves to full '\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2'."""
    tracker = ChannelStateTracker()
    tracker.update(_reading("\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2", 4.2))
    # Lookup by short ID should resolve
    state = tracker.get("\u042212")
    assert state is not None
    assert state.channel == "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2"
    assert abs(state.value - 4.2) < 1e-9
    # Full name also works
    state2 = tracker.get("\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2")
    assert state2 is not None
    assert state2.channel == "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2"


def test_resolve_fault_count() -> None:
    """get_fault_count works with short IDs via prefix resolution."""
    tracker = ChannelStateTracker(fault_window_s=300.0)
    now = time.time()
    # Update with full channel name and fault value (> 350 K)
    tracker.update(_reading("\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2", 999.0, ts=now))
    # Query by short ID
    count = tracker.get_fault_count("\u042212")
    assert count >= 1
