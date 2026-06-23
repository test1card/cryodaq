"""Regression tests for the data-flow watchdog on ZmqBridge.

After the 2026-04 stall bug: heartbeat liveness and data-flow freshness
are tracked separately. Startup (no readings yet) must NOT trigger a
false-positive restart, and restarting the bridge must re-arm the
data-flow watchdog.
"""

from __future__ import annotations

import logging
import time

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
    _last_reading_time; a heartbeat updates only _last_heartbeat.
    Exact Reading fields are verified — not just length."""
    from cryodaq.drivers.base import ChannelStatus

    bridge = ZmqBridge()

    # Heartbeat alone must NOT touch _last_reading_time.
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
    readings = _drain_poll_readings_until(
        bridge, lambda b: b._last_reading_time > before
    )
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
    bridge._reply_consumer = None
    bridge._process.exitcode = 0
    bridge.shutdown()
    assert "exitcode=0" in caplog.text


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
    bridge.start()

    assert old_consumer.joined is True
    assert bridge._reply_consumer is not old_consumer


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

    class _CmdStalledBridge:
        def __init__(self) -> None:
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

        def data_flow_stalled(self) -> bool:
            return False

        def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
            return True

        def shutdown(self) -> None:
            self.shutdown_calls += 1

        def start(self) -> None:
            self.start_calls += 1

    class _Dummy:
        def __init__(self) -> None:
            self._bridge = _CmdStalledBridge()

        def _on_reading_qt(self, item) -> None:  # pragma: no cover
            pass

    dummy = _Dummy()
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy._bridge.shutdown_calls == 1, "launcher must shut down bridge on cmd stall"
    assert dummy._bridge.start_calls == 1, "launcher must restart bridge on cmd stall"


def test_command_channel_not_stalled_after_window_expires(monkeypatch):
    """Once the configured window has elapsed past the last timeout,
    the watchdog must disarm so a single old blip doesn't trap the
    bridge in a restart loop."""
    bridge = _build_bridge_with_fake_proc()
    now = time.monotonic()
    bridge._last_cmd_timeout = now

    monkeypatch.setattr(
        "cryodaq.gui.zmq_client.time.monotonic", lambda: now + 15.0
    )
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
    readings = _drain_poll_readings_until(
        bridge, lambda b: b._last_cmd_timeout > 0.0
    )

    assert readings == [], "cmd_timeout envelope must not surface as a Reading"
    assert bridge._last_cmd_timeout > 0.0


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

        def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
            return False

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


def test_launcher_poll_reason_distinct_per_stall_type(caplog):
    """_poll_bridge_data must restart the bridge (shutdown+start exactly once)
    for EACH of the three stall types AND log a reason whose token is unique to
    that type — heartbeat-stale ('heartbeat') vs data-flow-stalled ('readings')
    vs command-channel-stalled ('command'). Asserts the expected token is
    present, the OTHER two tokens are ABSENT, and all three messages differ —
    catching wrong-reason logging and a missing restart on any single branch."""
    import logging

    from cryodaq.launcher import LauncherWindow

    class _ConfigurableBridge:
        def __init__(self, *, healthy, alive, data_stalled, cmd_stalled) -> None:
            self._healthy = healthy
            self._alive = alive
            self._data_stalled = data_stalled
            self._cmd_stalled = cmd_stalled
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self) -> bool:
            return self._healthy

        def is_alive(self) -> bool:
            return self._alive

        def data_flow_stalled(self) -> bool:
            return self._data_stalled

        def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
            return self._cmd_stalled

        def shutdown(self) -> None:
            self.shutdown_calls += 1

        def start(self) -> None:
            self.start_calls += 1

    class _Dummy:
        def __init__(self, bridge) -> None:
            self._bridge = bridge

        def _on_reading_qt(self, item) -> None:  # pragma: no cover
            pass

    # name -> (bridge kwargs, token that MUST be present, tokens that MUST be absent)
    cases = {
        "heartbeat": (
            dict(healthy=False, alive=True, data_stalled=False, cmd_stalled=False),
            "heartbeat",
            ("readings", "command"),
        ),
        "readings": (
            dict(healthy=True, alive=True, data_stalled=True, cmd_stalled=False),
            "readings",
            ("heartbeat", "command"),
        ),
        "command": (
            dict(healthy=True, alive=True, data_stalled=False, cmd_stalled=True),
            "command",
            ("heartbeat", "readings"),
        ),
    }

    messages: dict[str, str] = {}
    for name, (kwargs, present, absent) in cases.items():
        bridge = _ConfigurableBridge(**kwargs)
        dummy = _Dummy(bridge)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="cryodaq.launcher"):
            LauncherWindow._poll_bridge_data(dummy)

        assert bridge.shutdown_calls == 1, f"{name}: expected exactly one shutdown"
        assert bridge.start_calls == 1, f"{name}: expected exactly one start (restart)"
        log = " ".join(caplog.messages).lower()
        assert present in log, (
            f"{name}: expected reason token '{present}' in log, got: {caplog.messages}"
        )
        for tok in absent:
            assert tok not in log, (
                f"{name}: unexpected token '{tok}' in {name} log: {caplog.messages}"
            )
        messages[name] = log

    # All three normalized reason messages must be mutually distinct.
    assert len(set(messages.values())) == 3, f"stall reasons must all differ: {messages}"


def test_launcher_restarts_bridge_on_command_channel_stalled():
    """Launcher must restart the bridge when the command channel is
    stalled but heartbeats and data flow are otherwise healthy —
    that's the B1 failure shape (command plane dead, data plane alive)."""
    from cryodaq.launcher import LauncherWindow

    class _StalledCommandBridge:
        def __init__(self) -> None:
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

        def data_flow_stalled(self) -> bool:
            return False

        def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
            return True

        def shutdown(self) -> None:
            self.shutdown_calls += 1

        def start(self) -> None:
            self.start_calls += 1

    class _Dummy:
        def __init__(self) -> None:
            self._bridge = _StalledCommandBridge()

        def _on_reading_qt(self, item) -> None:  # pragma: no cover
            pass

    dummy = _Dummy()
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy._bridge.shutdown_calls == 1
    assert dummy._bridge.start_calls == 1


def test_launcher_watchdog_cooldown_blocks_repeat_restart(monkeypatch):
    from cryodaq.launcher import LauncherWindow

    class _Bridge:
        def __init__(self):
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self):
            return True

        def is_alive(self):
            return True

        def data_flow_stalled(self):
            return False

        def command_channel_stalled(self, *, timeout_s: float = 10.0):
            return True

        def shutdown(self):
            self.shutdown_calls += 1

        def start(self):
            self.start_calls += 1

    dummy = type(
        "D",
        (),
        {
            "_bridge": _Bridge(),
            "_last_cmd_watchdog_restart": 100.0,
            "_on_reading_qt": lambda self, item: None,
        },
    )()

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: 120.0)
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy._bridge.shutdown_calls == 0
    assert dummy._bridge.start_calls == 0


def test_launcher_watchdog_cooldown_allows_restart_after_60s(monkeypatch):
    from cryodaq.launcher import LauncherWindow

    class _Bridge:
        def __init__(self):
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self):
            return True

        def is_alive(self):
            return True

        def data_flow_stalled(self):
            return False

        def command_channel_stalled(self, *, timeout_s: float = 10.0):
            return True

        def shutdown(self):
            self.shutdown_calls += 1

        def start(self):
            self.start_calls += 1

    dummy = type(
        "D",
        (),
        {
            "_bridge": _Bridge(),
            "_last_cmd_watchdog_restart": 100.0,
            "_on_reading_qt": lambda self, item: None,
        },
    )()

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: 161.0)
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy._bridge.shutdown_calls == 1
    assert dummy._bridge.start_calls == 1


def test_launcher_does_not_restart_on_healthy_bridge():
    """When every liveness check passes, the launcher must not restart
    the bridge. A spurious restart here would drop in-flight commands
    and reset timers for no reason."""
    from cryodaq.launcher import LauncherWindow

    class _HealthyBridge:
        def __init__(self) -> None:
            self.shutdown_calls = 0
            self.start_calls = 0

        def poll_readings(self):
            return []

        def is_healthy(self) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

        def data_flow_stalled(self) -> bool:
            return False

        def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
            return False

        def shutdown(self) -> None:
            self.shutdown_calls += 1

        def start(self) -> None:
            self.start_calls += 1

    class _Dummy:
        def __init__(self) -> None:
            self._bridge = _HealthyBridge()

        def _on_reading_qt(self, item) -> None:  # pragma: no cover
            pass

    dummy = _Dummy()
    LauncherWindow._poll_bridge_data(dummy)

    assert dummy._bridge.shutdown_calls == 0
    assert dummy._bridge.start_calls == 0
