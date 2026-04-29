"""Tests for F20: diagnostic alarm aggregation threshold + escalation cooldown.

Covers:
- test_escalation_cooldown_suppresses_renotification_within_window
- test_escalation_cooldown_allows_after_expiry
- test_escalation_cooldown_disabled_by_default_zero
- test_multiple_channels_all_return_events_above_threshold (verifies new_events count)
"""
from __future__ import annotations

import time
from unittest.mock import patch

import numpy as np

from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


# ---------------------------------------------------------------------------
# Publisher stub that returns real AlarmEvent objects (needed to populate new_events)
# ---------------------------------------------------------------------------


class _AlarmStatePublisher:
    """Wraps AlarmStateManager to act as publisher, returning AlarmEvent on new trigger."""

    def __init__(self) -> None:
        self._state = AlarmStateManager()

    def publish_diagnostic_alarm(
        self, channel_id: str, severity: str, age_s: float
    ) -> AlarmEvent | None:
        return self._state.publish_diagnostic_alarm(channel_id, severity, age_s)

    def clear_diagnostic_alarm(self, channel_id: str) -> None:
        self._state.clear_diagnostic_alarm(channel_id)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _make_engine(
    cooldown_s: float = 0.0,
    warning_duration_s: float = 300.0,
    critical_duration_s: float = 900.0,
    publisher: _AlarmStatePublisher | None = None,
) -> SensorDiagnosticsEngine:
    pub = publisher or _AlarmStatePublisher()
    return SensorDiagnosticsEngine(
        config={"escalation_cooldown_s": cooldown_s},
        alarm_publisher=pub,
        warning_duration_s=warning_duration_s,
        critical_duration_s=critical_duration_s,
    )


def _push_disconnected(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 400.0)


def _push_clean(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 1000.0) -> None:
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 100.0)


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


def test_escalation_cooldown_suppresses_renotification_within_window() -> None:
    """Within cooldown window, re-trigger after clear produces no events in new_events."""
    eng = _make_engine(cooldown_s=120.0, warning_duration_s=10.0)
    _push_disconnected(eng, "T1")

    # First anomaly: fire warning at T=10
    with patch("time.monotonic", side_effect=[0.0, 10.0]):
        eng.update()
        events_first = eng.update()

    assert len(events_first) == 1, "Initial warning should fire"

    # Channel clears
    _push_clean(eng, "T1")
    with patch("time.monotonic", return_value=20.0):
        eng.update()

    # Re-enter anomaly within cooldown (T=50, only 40s since last notification at T=10)
    _push_disconnected(eng, "T1", t0=2000.0)
    with patch("time.monotonic", side_effect=[30.0, 50.0]):
        eng.update()
        events_refire = eng.update()  # elapsed=20 >= 10 → warning fires, but cooldown suppresses

    assert len(events_refire) == 0, "Re-notification suppressed within cooldown window"


def test_escalation_cooldown_allows_after_expiry() -> None:
    """After cooldown window expires, re-trigger produces events normally."""
    eng = _make_engine(cooldown_s=60.0, warning_duration_s=10.0)
    _push_disconnected(eng, "T1")

    # First notification at T=10
    with patch("time.monotonic", side_effect=[0.0, 10.0]):
        eng.update()
        eng.update()

    # Channel clears at T=20
    _push_clean(eng, "T1")
    with patch("time.monotonic", return_value=20.0):
        eng.update()

    # Re-enter anomaly AFTER cooldown (T=100, 90s since T=10 > cooldown=60s)
    _push_disconnected(eng, "T1", t0=3000.0)
    with patch("time.monotonic", side_effect=[80.0, 100.0]):  # 100-10=90 > 60 → allowed
        eng.update()
        events_refire = eng.update()

    assert len(events_refire) == 1, "Re-notification allowed after cooldown expiry"


def test_escalation_cooldown_disabled_by_default() -> None:
    """With default escalation_cooldown_s=0 (disabled), re-triggers always produce events."""
    eng = _make_engine(cooldown_s=0.0, warning_duration_s=10.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 10.0]):
        eng.update()
        events_first = eng.update()

    assert len(events_first) == 1

    _push_clean(eng, "T1")
    with patch("time.monotonic", return_value=15.0):
        eng.update()

    _push_disconnected(eng, "T1", t0=2000.0)
    with patch("time.monotonic", side_effect=[20.0, 35.0]):
        eng.update()
        events_refire = eng.update()

    assert len(events_refire) == 1, "Cooldown disabled → re-notification always fires"


def test_critical_always_notifies_regardless_of_cooldown() -> None:
    """Codex finding: critical escalation must never be suppressed by cooldown.

    Even when warning was recently notified (within cooldown window), the subsequent
    critical notification must always appear in new_events.
    """
    eng = _make_engine(cooldown_s=600.0, warning_duration_s=10.0, critical_duration_s=20.0)
    _push_disconnected(eng, "T1")

    # Warning fires at T=10
    with patch("time.monotonic", side_effect=[0.0, 10.0]):
        eng.update()
        events_warning = eng.update()

    assert len(events_warning) == 1, "Warning should fire"
    assert events_warning[0].level == "WARNING"

    # Critical fires at T=20 (only 10s after warning, well within cooldown=600s)
    with patch("time.monotonic", return_value=20.0):
        events_critical = eng.update()

    assert len(events_critical) == 1, "Critical must not be cooldown-suppressed"
    assert events_critical[0].level == "CRITICAL"


def test_multiple_channels_above_aggregation_threshold_all_in_new_events() -> None:
    """When N > aggregation_threshold channels trigger simultaneously, all appear in new_events.

    Aggregation batching into a single Telegram message happens in engine._sensor_diag_tick
    which reads from new_events. This test verifies that sensor_diagnostics.update() returns
    all events so engine has full information for the aggregation decision.
    """
    eng = _make_engine(cooldown_s=0.0, warning_duration_s=10.0)
    channels = ["T1", "T2", "T3", "T4", "T5"]
    for ch in channels:
        _push_disconnected(eng, ch)

    # All 5 channels pass warning threshold simultaneously
    mono_calls = [0.0] + [10.0] * 5  # first call sets first_anomaly_ts for each channel
    with patch("time.monotonic", side_effect=mono_calls):
        eng.update()  # sets first_anomaly_ts = 0.0 for all channels
        events = eng.update()  # elapsed = 10 >= 10 → warning for each

    # All 5 channels should appear in new_events (aggregation decision is engine's job)
    assert len(events) == 5
    alarmed = {e.channels[0] for e in events}
    assert alarmed == set(channels)
