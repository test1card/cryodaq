"""Regression tests for the data-flow watchdog on ZmqBridge.

After the 2026-04 stall bug: is_healthy() must flip False when no
actual reading has arrived for ≥30s, even if heartbeats keep
flowing. Startup (no readings yet) must NOT trigger a false
positive restart.
"""

from __future__ import annotations

import inspect
import time

from cryodaq.gui.zmq_client import ZmqBridge


class _FakeAliveProcess:
    """Minimal stand-in for a live mp.Process so we can drive is_healthy()
    without actually starting the subprocess."""

    def is_alive(self) -> bool:
        return True


def _build_bridge_with_fake_proc() -> ZmqBridge:
    bridge = ZmqBridge()
    bridge._process = _FakeAliveProcess()  # type: ignore[assignment]
    return bridge


def test_is_healthy_true_during_startup_no_readings_yet():
    """_last_reading_time == 0.0 (never received a reading) must not
    trigger false-positive restart at startup."""
    bridge = _build_bridge_with_fake_proc()
    bridge._last_heartbeat = time.monotonic()
    bridge._last_reading_time = 0.0
    assert bridge.is_healthy() is True


def test_is_healthy_flips_false_after_30s_no_readings():
    """Once readings have flowed, a 30s gap with no readings trips
    the watchdog even if heartbeats remain fresh."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now
    bridge._last_reading_time = now - 31.0
    assert bridge.is_healthy() is False


def test_is_healthy_true_when_readings_fresh():
    """Both heartbeat and reading fresh → healthy."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now
    bridge._last_reading_time = now - 1.0
    assert bridge.is_healthy() is True


def test_is_healthy_flips_false_after_30s_no_heartbeat():
    """Heartbeat-staleness check remains in place independently of
    the new data-flow check."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now - 31.0
    bridge._last_reading_time = now
    assert bridge.is_healthy() is False


def _drain_poll_readings_until(bridge: ZmqBridge, predicate, timeout: float = 2.0):
    """Call poll_readings() in a tight loop until predicate(bridge) is True.

    mp.Queue.put_nowait hands the item to a background feeder thread, so
    an immediately-following get_nowait() may see an empty queue. Polling
    briefly is how the GUI consumes it in practice too (via QTimer).
    """
    deadline = time.monotonic() + timeout
    collected: list = []
    while time.monotonic() < deadline:
        collected.extend(bridge.poll_readings())
        if predicate(bridge):
            return collected
        time.sleep(0.01)
    return collected


def test_poll_readings_updates_last_reading_time():
    """An actual reading (not heartbeat/warning) updates
    _last_reading_time; a heartbeat updates only _last_heartbeat."""
    bridge = ZmqBridge()

    # Heartbeat alone must NOT touch _last_reading_time.
    bridge._data_queue.put({"__type": "heartbeat", "ts": time.monotonic()})
    _drain_poll_readings_until(bridge, lambda b: b._last_heartbeat > 0.0)
    assert bridge._last_reading_time == 0.0
    assert bridge._last_heartbeat > 0.0

    # A real reading must update _last_reading_time.
    bridge._data_queue.put(
        {
            "timestamp": time.time(),
            "instrument_id": "mock",
            "channel": "T1",
            "value": 42.0,
            "unit": "K",
            "status": "ok",
            "raw": None,
            "metadata": {},
        }
    )
    before = bridge._last_reading_time
    readings = _drain_poll_readings_until(
        bridge, lambda b: b._last_reading_time > before
    )
    assert len(readings) == 1
    assert bridge._last_reading_time > before


def test_is_healthy_false_when_process_dead():
    """If the subprocess is not alive, is_healthy() is always False
    regardless of timestamps."""
    bridge = ZmqBridge()
    bridge._process = None
    bridge._last_heartbeat = time.monotonic()
    bridge._last_reading_time = time.monotonic()
    assert bridge.is_healthy() is False


def test_launcher_poll_logs_reason_distinction():
    """_poll_bridge_data must log a distinct restart reason depending
    on whether the heartbeat is stale or readings are stale. Checked
    by static inspection — avoids spinning up a real LauncherWindow."""
    from cryodaq.launcher import LauncherWindow

    source = inspect.getsource(LauncherWindow._poll_bridge_data)
    assert "no heartbeat" in source
    assert "no readings" in source
    assert "_last_reading_time" in source
