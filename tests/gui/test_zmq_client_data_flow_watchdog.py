"""Regression tests for the data-flow watchdog on ZmqBridge.

After the 2026-04 stall bug: heartbeat liveness and data-flow freshness
are tracked separately. Startup (no readings yet) must NOT trigger a
false-positive restart, and restarting the bridge must re-arm the
data-flow watchdog.
"""

from __future__ import annotations

import logging
import queue
import time

from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.zmq_client import ZmqBridge


class _FakeAliveProcess:
    """Minimal stand-in for a live mp.Process so we can drive is_healthy()
    without actually starting the subprocess."""

    pid = 12345

    def __init__(self) -> None:
        self._alive = True
        self.exitcode = None

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self._alive = False

    def kill(self) -> None:
        self.exitcode = -9
        self._alive = False


class _FakeLiveConsumer:
    def __init__(self) -> None:
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self._alive = False


def _build_bridge_with_fake_proc() -> ZmqBridge:
    bridge = ZmqBridge()
    bridge._process = _FakeAliveProcess()  # type: ignore[assignment]
    bridge._process_started = True
    bridge._reply_consumer = _FakeLiveConsumer()  # type: ignore[assignment]
    bridge._safe_reply_consumer = _FakeLiveConsumer()  # type: ignore[assignment]
    bridge._reply_consumer_started = True
    bridge._safe_reply_consumer_started = True
    bridge._reply_stop.clear()
    bridge._generation_fatal = None
    with bridge._pending_lock:
        bridge._command_admission_open = True
    assert bridge._raw_process_is_alive_locked()
    assert bridge._reply_consumers_are_alive_locked()
    bridge._bridge_instance_id = "a" * 32
    return bridge


class _StatefulWatchdogBridge:
    """Model one exact live bridge generation and its watchdog replacement."""

    def __init__(
        self,
        *,
        healthy: bool = True,
        data_stalled: bool = False,
        command_stalled: bool = False,
        readings: tuple[DescriptorQualifiedReading, ...] = (),
        data_stalled_until_poll: bool = False,
    ) -> None:
        self._alive = True
        self._healthy = healthy
        self._data_stalled = data_stalled
        self._command_stalled = command_stalled
        self._readings = list(readings)
        self._polled = False
        self._data_stalled_until_poll = data_stalled_until_poll
        self._restart_count = 1
        self._pid = 12345
        self.shutdown_calls = 0
        self.start_calls = 0
        self.transitions: list[str] = []

    def poll_readings_with_descriptor(self) -> list[DescriptorQualifiedReading]:
        self._polled = True
        readings, self._readings = self._readings, []
        return readings

    def is_healthy(self) -> bool:
        return self._alive and self._healthy

    def is_alive(self) -> bool:
        return self._alive

    def data_flow_stalled(self) -> bool:
        if self._data_stalled_until_poll:
            return not self._polled
        return self._data_stalled

    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
        return self._command_stalled

    def restart_count(self) -> int:
        return self._restart_count

    def process_pid(self) -> int | None:
        return self._pid if self._alive else None

    def degrade(
        self,
        *,
        healthy: bool | None = None,
        data_stalled: bool | None = None,
        command_stalled: bool | None = None,
    ) -> None:
        if healthy is not None:
            self._healthy = healthy
        if data_stalled is not None:
            self._data_stalled = data_stalled
        if command_stalled is not None:
            self._command_stalled = command_stalled

    def shutdown(self) -> None:
        assert self._alive, "watchdog must settle exactly one live generation"
        self.shutdown_calls += 1
        self.transitions.append("shutdown")
        self._alive = False
        self._healthy = False

    def start(self) -> None:
        assert not self._alive, "watchdog must not overlap bridge generations"
        self.start_calls += 1
        self.transitions.append("start")
        self._restart_count += 1
        self._pid += 1
        self._alive = True
        self._healthy = True
        self._data_stalled = False
        self._command_stalled = False


class _WatchdogWindowDouble:
    def __init__(self, bridge: _StatefulWatchdogBridge) -> None:
        self._bridge = bridge
        self.dispatched: list[DescriptorQualifiedReading] = []
        self.descriptor_invalidations = 0

    def _on_reading_qt(self, item: DescriptorQualifiedReading) -> None:
        self.dispatched.append(item)

    def _invalidate_descriptor_transport(self) -> None:
        self.descriptor_invalidations += 1


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


def test_rejected_wire_item_cannot_refresh_data_flow_freshness():
    stale = time.monotonic() - 31.0
    for poll_name in ("poll_readings", "poll_readings_with_descriptor"):
        bridge = ZmqBridge()
        bridge._data_queue = queue.Queue()
        bridge._last_reading_time = stale
        bridge._data_queue.put_nowait({"timestamp": "not-a-number"})

        assert getattr(bridge, poll_name)() == []
        assert bridge._last_reading_time == stale
        assert bridge.data_flow_stalled() is True


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


def test_poll_readings_updates_last_reading_time(live_zmq_bridge):
    """An actual reading (not heartbeat/warning) updates
    _last_reading_time; a heartbeat updates only _last_heartbeat.
    Exact Reading fields are verified — not just length."""
    from cryodaq.drivers.base import ChannelStatus

    bridge = live_zmq_bridge

    # Heartbeat alone must NOT touch _last_reading_time.
    bridge._last_heartbeat = 0.0
    bridge._data_queue.put({"__type": "heartbeat", "ts": time.monotonic()})
    _drain_poll_readings_until(bridge, lambda b: b._last_heartbeat > 0.0)
    assert bridge._last_reading_time == 0.0
    assert bridge._last_heartbeat > 0.0

    # A real reading must update _last_reading_time and carry correct fields.
    ts = time.time()
    bridge._data_queue.put(
        {
            "timestamp": ts,
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
    readings = _drain_poll_readings_until(bridge, lambda b: b._last_reading_time > before)
    assert len(readings) == 1
    r = readings[0]
    assert r.channel == "T1"
    assert r.value == 42.0
    assert r.unit == "K"
    assert r.status == ChannelStatus.OK
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


def test_bridge_restart_count_increments_on_start(monkeypatch):
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
    assert bridge.restart_count() == 0
    bridge.start()
    assert bridge.restart_count() == 1


def test_shutdown_logs_exitcode(caplog):
    caplog.set_level(logging.INFO, logger="cryodaq.gui.zmq_client")
    bridge = _build_bridge_with_fake_proc()
    bridge._process.exitcode = 0
    bridge.shutdown()
    assert "exitcode=0" in caplog.text
    bridge.close()


def test_start_stops_stale_reply_consumer_before_restart(monkeypatch):
    """Restart after a dead subprocess must not leave two reply consumers alive."""

    class _DeadProcess:
        pid = 12345

        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

        def start(self) -> None:
            self._alive = True

    class _NewThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self._alive = False

    class _OldThread:
        def __init__(self) -> None:
            self.joined = False
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self.joined = True
            self._alive = False

    monkeypatch.setattr("cryodaq.gui.zmq_client.mp.Process", _DeadProcess)
    monkeypatch.setattr("cryodaq.gui.zmq_client.threading.Thread", _NewThread)

    bridge = ZmqBridge()
    old_consumer = _OldThread()
    bridge._reply_consumer = old_consumer
    bridge._reply_consumer_started = True
    bridge.start()

    assert old_consumer.joined is True
    assert bridge._reply_consumer is not old_consumer
    assert bridge._reply_consumer_started is True
    assert bridge._safe_reply_consumer_started is True


def test_command_channel_not_stalled_on_fresh_bridge():
    """Before any cmd_timeout has arrived, the command-channel watchdog
    must stay disarmed — otherwise the launcher would restart the bridge
    during startup while it's still establishing the REQ/REP path."""
    bridge = _build_bridge_with_fake_proc()
    assert bridge._last_cmd_timeout == 0.0
    assert bridge.command_channel_stalled(timeout_s=10.0) is False


def test_command_channel_stalled_after_recent_timeout():
    """Injecting a ``cmd_timeout`` control message via data_queue must
    flip ``command_channel_stalled`` to True inside the watchdog window,
    and the launcher must restart the bridge when it observes that state."""
    bridge = _build_bridge_with_fake_proc()
    bridge._last_heartbeat = time.monotonic()
    bridge._data_queue.put(
        {
            "__type": "cmd_timeout",
            "cmd": "safety_status",
            "ts": time.monotonic(),
            "message": "REP timeout on safety_status (Resource temporarily unavailable)",
        }
    )
    _drain_poll_readings_until(bridge, lambda b: b._last_cmd_timeout > 0.0)

    assert bridge._last_cmd_timeout > 0.0
    assert bridge.command_channel_stalled(timeout_s=10.0) is True

    # Verify the launcher's watchdog path calls shutdown + start on the bridge
    # when command_channel_stalled() is True (B1 failure shape).
    from cryodaq.launcher import LauncherWindow

    watchdog_bridge = _StatefulWatchdogBridge(command_stalled=True)
    dummy = _WatchdogWindowDouble(watchdog_bridge)
    LauncherWindow._poll_bridge_data(dummy)

    assert watchdog_bridge.shutdown_calls == 1, "launcher must shut down bridge on cmd stall"
    assert watchdog_bridge.start_calls == 1, "launcher must restart bridge on cmd stall"
    assert watchdog_bridge.transitions == ["shutdown", "start"]
    assert watchdog_bridge.restart_count() == 2
    assert watchdog_bridge.process_pid() == 12346
    assert dummy.descriptor_invalidations == 1


def test_command_channel_not_stalled_after_window_expires(monkeypatch):
    """Once the configured window has elapsed past the last timeout,
    the watchdog must disarm so a single old blip doesn't trap the
    bridge in a restart loop."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_cmd_timeout = now

    monkeypatch.setattr("cryodaq.gui.zmq_client.time.monotonic", lambda: now + 15.0)
    assert bridge.command_channel_stalled(timeout_s=10.0) is False


def test_poll_readings_handles_cmd_timeout_type():
    """poll_readings must consume ``cmd_timeout`` envelopes without
    returning them as Readings and must update ``_last_cmd_timeout``
    in the process."""
    bridge = _build_bridge_with_fake_proc()
    bridge._data_queue.put(
        {
            "__type": "cmd_timeout",
            "cmd": "safety_status",
            "ts": time.monotonic(),
            "message": "REP timeout on safety_status (test)",
        }
    )
    readings = _drain_poll_readings_until(bridge, lambda b: b._last_cmd_timeout > 0.0)

    assert readings == [], "cmd_timeout envelope must not surface as a Reading"
    assert bridge._last_cmd_timeout > 0.0


def test_launcher_poll_drains_before_data_stall_restart():
    """Queued readings must be drained before the stale-data policy fires."""
    from cryodaq.launcher import LauncherWindow

    reading = Reading.now(channel="T1", value=4.2, unit="K", instrument_id="mock")
    qualified = DescriptorQualifiedReading(reading=reading, descriptor=None)
    bridge = _StatefulWatchdogBridge(readings=(qualified,), data_stalled_until_poll=True)
    dummy = _WatchdogWindowDouble(bridge)
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy.dispatched == [qualified]
    assert bridge.transitions == []
    assert bridge.restart_count() == 1


def test_health_watchdog_cooldown_prevents_restart_storm():
    """A bridge that stays unhealthy across consecutive polls must restart ONCE,
    not on every poll — the 60s cooldown gives a freshly restarted bridge time to
    re-establish its heartbeat (without it, is_healthy()==False every poll would
    hammer restart). Mirrors the command-channel watchdog hardening."""
    from cryodaq.launcher import LauncherWindow

    bridge = _StatefulWatchdogBridge(healthy=False)
    dummy = _WatchdogWindowDouble(bridge)
    # Two consecutive polls on the SAME window (so the cooldown timestamp persists).
    LauncherWindow._poll_bridge_data(dummy)
    bridge.degrade(healthy=False)
    LauncherWindow._poll_bridge_data(dummy)

    assert bridge.start_calls == 1, "cooldown must prevent a restart storm (got >1 restart)"
    assert bridge.shutdown_calls == 1
    assert bridge.transitions == ["shutdown", "start"]
    assert bridge.restart_count() == 2


def test_launcher_poll_reason_distinct_per_stall_type(caplog):
    """_poll_bridge_data must restart the bridge (shutdown+start exactly once)
    for EACH of the three stall types AND log a reason whose token is unique to
    that type — heartbeat-stale ('heartbeat') vs data-flow-stalled ('readings')
    vs command-channel-stalled ('command'). Asserts the expected token is
    present, the OTHER two tokens are ABSENT, and all three messages differ —
    catching wrong-reason logging and a missing restart on any single branch."""
    import logging

    from cryodaq.launcher import LauncherWindow

    # name -> (bridge kwargs, token that MUST be present, tokens that MUST be absent)
    cases = {
        "heartbeat": (
            dict(healthy=False, data_stalled=False, command_stalled=False),
            "heartbeat",
            ("readings", "command"),
        ),
        "readings": (
            dict(healthy=True, data_stalled=True, command_stalled=False),
            "readings",
            ("heartbeat", "command"),
        ),
        "command": (
            dict(healthy=True, data_stalled=False, command_stalled=True),
            "command",
            ("heartbeat", "readings"),
        ),
    }

    messages: dict[str, str] = {}
    for name, (kwargs, present, absent) in cases.items():
        bridge = _StatefulWatchdogBridge(**kwargs)
        dummy = _WatchdogWindowDouble(bridge)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="cryodaq.launcher"):
            LauncherWindow._poll_bridge_data(dummy)

        assert bridge.shutdown_calls == 1, f"{name}: expected exactly one shutdown"
        assert bridge.start_calls == 1, f"{name}: expected exactly one start (restart)"
        assert bridge.transitions == ["shutdown", "start"]
        assert bridge.restart_count() == 2
        assert bridge.process_pid() == 12346
        assert dummy.descriptor_invalidations == 1
        log = " ".join(caplog.messages).lower()
        assert present in log, f"{name}: expected reason token '{present}' in log, got: {caplog.messages}"
        for tok in absent:
            assert tok not in log, f"{name}: unexpected token '{tok}' in {name} log: {caplog.messages}"
        messages[name] = log

    # All three normalized reason messages must be mutually distinct.
    assert len(set(messages.values())) == 3, f"stall reasons must all differ: {messages}"


def test_launcher_restarts_bridge_on_command_channel_stalled():
    """Launcher must restart the bridge when the command channel is
    stalled but heartbeats and data flow are otherwise healthy —
    that's the B1 failure shape (command plane dead, data plane alive)."""
    from cryodaq.launcher import LauncherWindow

    bridge = _StatefulWatchdogBridge(command_stalled=True)
    dummy = _WatchdogWindowDouble(bridge)
    LauncherWindow._poll_bridge_data(dummy)

    assert bridge.shutdown_calls == 1
    assert bridge.start_calls == 1
    assert bridge.transitions == ["shutdown", "start"]
    assert bridge.restart_count() == 2


def test_launcher_watchdog_cooldown_blocks_repeat_restart(monkeypatch):
    from cryodaq.launcher import LauncherWindow

    bridge = _StatefulWatchdogBridge(command_stalled=True)
    dummy = _WatchdogWindowDouble(bridge)
    dummy._last_cmd_watchdog_restart = 100.0

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: 120.0)
    LauncherWindow._poll_bridge_data(dummy)

    assert bridge.shutdown_calls == 0
    assert bridge.start_calls == 0
    assert bridge.transitions == []
    assert bridge.restart_count() == 1


def test_launcher_watchdog_cooldown_allows_restart_after_60s(monkeypatch):
    from cryodaq.launcher import LauncherWindow

    bridge = _StatefulWatchdogBridge(command_stalled=True)
    dummy = _WatchdogWindowDouble(bridge)
    dummy._last_cmd_watchdog_restart = 100.0

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: 161.0)
    LauncherWindow._poll_bridge_data(dummy)

    assert bridge.shutdown_calls == 1
    assert bridge.start_calls == 1
    assert bridge.transitions == ["shutdown", "start"]
    assert bridge.restart_count() == 2
    assert bridge.process_pid() == 12346


def test_launcher_does_not_restart_on_healthy_bridge():
    """When every liveness check passes, the launcher must not restart
    the bridge. A spurious restart here would drop in-flight commands
    and reset timers for no reason."""
    from cryodaq.launcher import LauncherWindow

    bridge = _StatefulWatchdogBridge()
    dummy = _WatchdogWindowDouble(bridge)
    LauncherWindow._poll_bridge_data(dummy)

    assert bridge.shutdown_calls == 0
    assert bridge.start_calls == 0
    assert bridge.transitions == []
    assert bridge.restart_count() == 1
