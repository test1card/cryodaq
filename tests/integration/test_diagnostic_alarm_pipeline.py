"""Integration tests for F10 Cycle 3: diagnostic alarm pipeline end-to-end.

Covers spec §5.3:
- test_diagnostic_anomaly_to_alarm_to_telegram_pipeline: sustained anomaly
  → AlarmStateManager active alarm → new event returned → mock Telegram
  dispatch triggered
- test_diagnostic_alarm_displayed_in_alarm_panel: sustained anomaly →
  alarm_v2_state_mgr.get_active() contains diagnostic alarm (alarm panel
  polls get_active())
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryodaq.core.alarm_v2 import AlarmStateManager
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.engine import _format_diag_telegram_messages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline(warning_duration_s: float = 300.0, critical_duration_s: float = 900.0):
    """Create a wired SensorDiagnosticsEngine + AlarmStateManager pair."""
    state_mgr = AlarmStateManager()
    engine = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=state_mgr,
        warning_duration_s=warning_duration_s,
        critical_duration_s=critical_duration_s,
    )
    return engine, state_mgr


def _push_disconnected(eng: SensorDiagnosticsEngine, ch: str, n: int = 200) -> None:
    for i in range(n):
        eng.push(ch, float(i) * 0.5, 400.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _diag_event(level: str, alarm_id: str, channels: list[str], message: str = "msg"):
    return SimpleNamespace(
        level=level, alarm_id=alarm_id, channels=channels, message=message
    )


def test_diag_telegram_per_event_format_below_threshold() -> None:
    """At or below the aggregation threshold: one (task_name, message) pair per
    event, in the exact production format."""
    events = [_diag_event("CRITICAL", "diag:T1", ["T1"], "T1 disconnected")]

    pairs = _format_diag_telegram_messages(events, aggregation_threshold=3)

    assert pairs == [("diag_tg_diag:T1", "⚠ [CRITICAL] diag:T1\nT1 disconnected")]


def test_diag_telegram_aggregates_above_threshold() -> None:
    """More than `aggregation_threshold` simultaneous events collapse into a
    single batch summary message named ``diag_tg_batch`` (F20)."""
    events = [_diag_event("WARNING", f"diag:T{i}", [f"T{i}"]) for i in range(5)]

    pairs = _format_diag_telegram_messages(events, aggregation_threshold=3)

    assert len(pairs) == 1
    name, msg = pairs[0]
    assert name == "diag_tg_batch"
    assert msg.startswith("⚠ Diagnostic alarm batch:")
    assert "5 channels warning" in msg


def test_diag_telegram_empty_events_returns_empty() -> None:
    assert _format_diag_telegram_messages([]) == []


def test_diagnostic_anomaly_to_alarm_to_telegram_pipeline() -> None:
    """Sustained anomaly flows through the full pipeline: diagnostics → alarm →
    new event returned → Telegram-like notifier would fire.

    Simulates what the engine's _sensor_diag_tick does: receives new events
    from update() and dispatches notifications.
    """
    engine, state_mgr = _make_pipeline(warning_duration_s=300.0)
    _push_disconnected(engine, "T1")

    # Mock a Telegram-like notifier that fires when update() returns new events
    telegram_mock = MagicMock()

    def _simulate_tick(eng: SensorDiagnosticsEngine) -> None:
        """Dispatch via the PRODUCTION formatter (engine._format_diag_telegram_messages)."""
        for _name, msg in _format_diag_telegram_messages(eng.update()):
            telegram_mock.send(msg)

    # First tick: sets first_anomaly_ts = 0.0
    with patch("time.monotonic", return_value=0.0):
        _simulate_tick(engine)

    telegram_mock.send.assert_not_called()  # anomaly just started, not yet sustained

    # Second tick: elapsed = 301s → warning threshold crossed
    with patch("time.monotonic", return_value=301.0):
        _simulate_tick(engine)

    # Telegram notifier must have been called with exact production message format
    assert telegram_mock.send.called
    call_args = telegram_mock.send.call_args[0][0]
    assert call_args.startswith("⚠ [WARNING]")
    assert "diag:T1" in call_args

    # AlarmStateManager must hold the active alarm
    active = state_mgr.get_active()
    assert "diag:T1" in active
    assert active["diag:T1"].level == "WARNING"


def test_diagnostic_alarm_displayed_in_alarm_panel() -> None:
    """Sustained anomaly produces an alarm visible in the alarm panel.

    The GUI alarm panel polls alarm_v2_state_mgr.get_active() via the
    alarm_v2_status ZMQ command. This test verifies that diagnostic alarms
    appear in that dict immediately after sustained anomaly is detected.
    """
    engine, state_mgr = _make_pipeline(warning_duration_s=300.0, critical_duration_s=900.0)
    _push_disconnected(engine, "T1")
    _push_disconnected(engine, "T2")

    # Both channels start anomaly at t=0
    with patch("time.monotonic", return_value=0.0):
        engine.update()

    # No alarms yet — alarm panel sees empty dict
    assert not state_mgr.get_active()

    # After warning duration
    with patch("time.monotonic", return_value=301.0):
        engine.update()

    active = state_mgr.get_active()

    # Alarm panel should see two independent diagnostic alarms
    assert "diag:T1" in active
    assert "diag:T2" in active
    assert active["diag:T1"].level == "WARNING"
    assert active["diag:T2"].level == "WARNING"
    assert active["diag:T1"].channels == ["T1"]
    assert active["diag:T2"].channels == ["T2"]

    # Recovery: push clean data for T1 → alarm clears for T1 only
    for i in range(200):
        engine.push("T1", 2000.0 + i * 0.5, 100.0)

    with patch("time.monotonic", return_value=302.0):
        engine.update()

    active = state_mgr.get_active()
    assert "diag:T1" not in active  # T1 recovered
    assert "diag:T2" in active  # T2 still alarming
