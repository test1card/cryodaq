"""Regression tests for the data-flow watchdog on ZmqBridge.

After the 2026-04 stall bug: heartbeat liveness and data-flow freshness
are tracked separately. Startup (no readings yet) must NOT trigger a
false-positive restart, and restarting the bridge must re-arm the
data-flow watchdog.
"""

from __future__ import annotations

import inspect
import time

from cryodaq.drivers.base import Reading
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
    """_last_reading_time == 0.0 must not trigger false-positive startup restart."""
    bridge = _build_bridge_with_fake_proc()
    bridge._last_heartbeat = time.monotonic()
    bridge._last_reading_time = 0.0
    assert bridge.is_healthy() is True


def test_data_flow_stalled_flips_true_after_30s_no_readings():
    """Once readings have flowed, a 30s gap trips the data-flow watchdog."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now
    bridge._last_reading_time = now - 31.0
    assert bridge.is_healthy() is True
    assert bridge.data_flow_stalled() is True


def test_is_healthy_true_when_readings_fresh():
    """Heartbeat freshness governs bridge liveness."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now
    bridge._last_reading_time = now - 1.0
    assert bridge.is_healthy() is True
    assert bridge.data_flow_stalled() is False


def test_is_healthy_flips_false_after_30s_no_heartbeat():
    """Heartbeat-staleness check remains the bridge-health boundary."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_heartbeat = now - 31.0
    bridge._last_reading_time = now
    assert bridge.is_healthy() is False
    assert bridge.heartbeat_stale() is True


def test_data_flow_stalled_false_until_first_reading():
    """Startup remains disarmed until at least one actual reading arrived."""
    bridge = _build_bridge_with_fake_proc()
    bridge._last_heartbeat = time.monotonic()
    bridge._last_reading_time = 0.0
    assert bridge.data_flow_stalled() is False


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


def test_start_resets_last_reading_time(monkeypatch):
    """Bridge restart must re-arm the data-flow watchdog."""

    class _FakeProcess:
        pid = 12345

        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

        def start(self) -> None:
            self._alive = True

    class _FakeThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self._alive = False

    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", _FakeProcess)
    monkeypatch.setattr("cryodaq.gui.zmq_client.threading.Thread", _FakeThread)

    bridge = ZmqBridge()
    bridge._last_reading_time = time.monotonic() - 123.0
    bridge.start()

    assert bridge._last_reading_time == 0.0


def test_launcher_poll_drains_before_data_stall_restart():
    """Queued readings must be drained before the stale-data policy fires."""
    from cryodaq.launcher import LauncherWindow

    reading = Reading.now(channel="T1", value=4.2, unit="K", instrument_id="mock")
    dispatched: list[Reading] = []

    class _FakeBridge:
        def __init__(self) -> None:
            self.restarted = False
            self._polled = False

        def poll_readings(self):
            self._polled = True
            return [reading]

        def is_healthy(self) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

        def data_flow_stalled(self) -> bool:
            return not self._polled

        def shutdown(self) -> None:
            self.restarted = True

        def start(self) -> None:
            self.restarted = True

    class _Dummy:
        def __init__(self) -> None:
            self._bridge = _FakeBridge()

        def _on_reading_qt(self, item) -> None:
            dispatched.append(item)

    dummy = _Dummy()
    LauncherWindow._poll_bridge_data(dummy)

    assert dispatched == [reading]
    assert dummy._bridge.restarted is False


def test_launcher_poll_logs_reason_distinction():
    """Launcher still distinguishes heartbeat failure from data starvation."""
    from cryodaq.launcher import LauncherWindow

    source = inspect.getsource(LauncherWindow._poll_bridge_data)
    assert "no heartbeat" in source
    assert "no readings" in source
    assert "poll_readings" in source
