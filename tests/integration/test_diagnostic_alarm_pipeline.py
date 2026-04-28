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

from unittest.mock import MagicMock, patch

import numpy as np

from cryodaq.core.alarm_v2 import AlarmStateManager
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


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
        """Mirrors engine.py _sensor_diag_tick Telegram dispatch exactly."""
        new_events = eng.update()
        for event in new_events:
            # Exact format from engine.py _sensor_diag_tick (Codex MEDIUM fix)
            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
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
