"""Tests for AlarmEvaluator v2 — composite, rate, threshold, stale, state manager."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

from cryodaq.core.alarm_v2 import (
    AlarmEvaluator,
    AlarmEvent,
    AlarmStateManager,
    PhaseProvider,
    SetpointProvider,
)
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(channel: str, value: float, unit: str = "K", ts: float | None = None) -> Reading:
    if ts is None:
        ts = time.time()
    return Reading(
        timestamp=datetime.fromtimestamp(ts, tz=UTC),
        instrument_id="LS218",
        channel=channel,
        value=value,
        unit=unit,
    )


def _make_evaluator(
    readings: list[Reading] | None = None,
    rate_data: dict[str, list[tuple[float, float]]] | None = None,
    phase: str | None = None,
    setpoints: dict[str, float] | None = None,
) -> AlarmEvaluator:
    state = ChannelStateTracker()
    rate = RateEstimator(window_s=120.0, min_points=2)  # min_points=2 для тестов

    if readings:
        for r in readings:
            state.update(r)
            rate.push(r.channel, r.timestamp.timestamp(), r.value)

    if rate_data:
        for ch, points in rate_data.items():
            for ts, val in points:
                rate.push(ch, ts, val)

    phase_provider = PhaseProvider()
    if phase is not None:
        phase_provider = MagicMock(spec=PhaseProvider)
        phase_provider.get_current_phase.return_value = phase
        phase_provider.get_phase_elapsed_s.return_value = 7200.0

    sp_provider = SetpointProvider(setpoints or {})
    return AlarmEvaluator(state, rate, phase_provider, sp_provider)


def _linear_rate_data(
    channel: str,
    *,
    rate_per_min: float,
    n: int = 90,
    start_val: float = 10.0,
    t0: float | None = None,
) -> list[tuple[float, float]]:
    """Generate (ts, value) list for given rate."""
    if t0 is None:
        t0 = time.time() - n
    rate_per_sec = rate_per_min / 60.0
    return [(t0 + i, start_val + rate_per_sec * i) for i in range(n)]


# ---------------------------------------------------------------------------
# Threshold checks
# ---------------------------------------------------------------------------


def test_threshold_above() -> None:
    ev = _make_evaluator([_reading("T1", 5.0)])
    cfg = {
        "alarm_type": "threshold",
        "channel": "T1",
        "check": "above",
        "threshold": 4.0,
        "level": "WARNING",
        "message": "T1 high",
    }
    result = ev.evaluate("test_above", cfg)
    assert result is not None
    assert result.alarm_id == "test_above"
    assert result.level == "WARNING"
    assert "T1" in result.channels


def test_threshold_above_not_triggered() -> None:
    ev = _make_evaluator([_reading("T1", 3.0)])
    cfg = {
        "alarm_type": "threshold",
        "channel": "T1",
        "check": "above",
        "threshold": 4.0,
        "level": "WARNING",
    }
    assert ev.evaluate("test", cfg) is None


def test_threshold_below() -> None:
    ev = _make_evaluator([_reading("T1", 1.0)])
    cfg = {
        "alarm_type": "threshold",
        "channel": "T1",
        "check": "below",
        "threshold": 2.0,
        "level": "WARNING",
    }
    result = ev.evaluate("test_below", cfg)
    assert result is not None


def test_threshold_outside_range() -> None:
    # Below range
    ev = _make_evaluator([_reading("T3", -1.0)])
    cfg = {
        "alarm_type": "threshold",
        "channel": "T3",
        "check": "outside_range",
        "range": [0.0, 350.0],
        "level": "WARNING",
    }
    assert ev.evaluate("sensor_fault", cfg) is not None

    # Above range
    ev2 = _make_evaluator([_reading("T3", 400.0)])
    assert ev2.evaluate("sensor_fault", cfg) is not None

    # Normal
    ev3 = _make_evaluator([_reading("T3", 77.0)])
    assert ev3.evaluate("sensor_fault", cfg) is None


def test_threshold_deviation_from_setpoint() -> None:
    ev = _make_evaluator([_reading("T12", 5.5)], setpoints={"T12_setpoint": 4.2})
    cfg = {
        "alarm_type": "threshold",
        "channel": "T12",
        "check": "deviation_from_setpoint",
        "setpoint_source": "T12_setpoint",
        "threshold": 0.5,
        "level": "WARNING",
    }
    result = ev.evaluate("detector_drift", cfg)
    assert result is not None  # |5.5 - 4.2| = 1.3 > 0.5


def test_threshold_deviation_from_setpoint_ok() -> None:
    ev = _make_evaluator([_reading("T12", 4.3)], setpoints={"T12_setpoint": 4.2})
    cfg = {
        "alarm_type": "threshold",
        "channel": "T12",
        "check": "deviation_from_setpoint",
        "setpoint_source": "T12_setpoint",
        "threshold": 0.5,
        "level": "WARNING",
    }
    assert ev.evaluate("drift", cfg) is None  # |4.3 - 4.2| = 0.1 < 0.5


def test_threshold_missing_channel_no_fire() -> None:
    """Канал без данных не вызывает аларм."""
    ev = _make_evaluator()
    cfg = {
        "alarm_type": "threshold",
        "channel": "T99",
        "check": "above",
        "threshold": 1.0,
        "level": "WARNING",
    }
    assert ev.evaluate("test", cfg) is None


# ---------------------------------------------------------------------------
# Sustained
# ---------------------------------------------------------------------------


def test_threshold_sustained_fires_after_delay() -> None:
    ev = _make_evaluator([_reading("T12", 5.5)], setpoints={"T12_setpoint": 4.2})
    cfg = {
        "alarm_type": "threshold",
        "channel": "T12",
        "check": "deviation_from_setpoint",
        "setpoint_source": "T12_setpoint",
        "threshold": 0.5,
        "level": "WARNING",
        "sustained_s": 60,
    }
    state_mgr = AlarmStateManager()

    # First evaluate — condition True, but sustained not yet
    event = ev.evaluate("drift", cfg)
    # Manually set sustained_since to 65 seconds ago
    state_mgr._sustained_since["drift"] = time.time() - 65

    result = state_mgr.process("drift", event, cfg)
    assert result == "TRIGGERED"


def test_threshold_sustained_resets_on_clear() -> None:
    state_mgr = AlarmStateManager()
    state_mgr._sustained_since["alarm1"] = time.time() - 10
    cfg = {"sustained_s": 30}
    # No event (condition cleared)
    result = state_mgr.process("alarm1", None, cfg)
    assert result is None
    assert "alarm1" not in state_mgr._sustained_since


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def test_composite_and_both_true() -> None:
    ev = _make_evaluator(
        [
            _reading("T11", 100.0),  # < 200 → any_below condition true
            _reading("T12", 100.0),
            _reading("P1", 2e-3, unit="mbar"),  # > 1e-3 → above condition true
        ]
    )
    cfg = {
        "alarm_type": "composite",
        "operator": "AND",
        "conditions": [
            {"channels": ["T11", "T12"], "check": "any_below", "threshold": 200},
            {"channel": "P1", "check": "above", "threshold": 1e-3},
        ],
        "level": "CRITICAL",
        "message": "Vacuum loss",
    }
    result = ev.evaluate("vacuum_loss_cold", cfg)
    assert result is not None
    assert result.level == "CRITICAL"


def test_composite_and_one_false() -> None:
    ev = _make_evaluator(
        [
            _reading("T11", 100.0),  # any_below 200 → True
            _reading("T12", 100.0),
            _reading("P1", 1e-6, unit="mbar"),  # < 1e-3 → False
        ]
    )
    cfg = {
        "alarm_type": "composite",
        "operator": "AND",
        "conditions": [
            {"channels": ["T11", "T12"], "check": "any_below", "threshold": 200},
            {"channel": "P1", "check": "above", "threshold": 1e-3},
        ],
        "level": "CRITICAL",
    }
    assert ev.evaluate("vacuum_loss_cold", cfg) is None


def test_composite_or() -> None:
    ev = _make_evaluator(
        [
            _reading("T11", 250.0),  # > 200 → any_below 200 False
            _reading("P1", 2e-3, unit="mbar"),  # > 1e-3 → True
        ]
    )
    cfg = {
        "alarm_type": "composite",
        "operator": "OR",
        "conditions": [
            {"channels": ["T11"], "check": "any_below", "threshold": 200},
            {"channel": "P1", "check": "above", "threshold": 1e-3},
        ],
        "level": "WARNING",
    }
    result = ev.evaluate("test_or", cfg)
    assert result is not None


# ---------------------------------------------------------------------------
# Rate
# ---------------------------------------------------------------------------


def test_rate_above_fires() -> None:
    """dT/dt > 5 K/мин должен сработать."""
    t0 = time.time() - 90
    rd = _linear_rate_data("T11", rate_per_min=6.0, n=90, t0=t0)
    ev = _make_evaluator(rate_data={"T11": rd})
    # Добавим reading чтобы state знал о канале
    state = ChannelStateTracker()
    for ts, val in rd:
        state.update(_reading("T11", val, ts=ts))

    cfg = {
        "alarm_type": "rate",
        "channels": ["T11"],
        "check": "rate_above",
        "threshold": 5.0,
        "rate_window_s": 90,
        "level": "WARNING",
        "message": "Cooling rate {channel}: {value} K/min",
    }
    result = ev.evaluate("excessive_cooling", cfg)
    assert result is not None
    assert result.alarm_id == "excessive_cooling"


def test_rate_below_fires() -> None:
    """dT/dt < -5 K/мин (быстрое охлаждение)."""
    t0 = time.time() - 90
    rd = _linear_rate_data("T12", rate_per_min=-6.0, start_val=200.0, n=90, t0=t0)
    ev = _make_evaluator(rate_data={"T12": rd})

    cfg = {
        "alarm_type": "rate",
        "channels": ["T12"],
        "check": "rate_below",
        "threshold": -5.0,
        "rate_window_s": 90,
        "level": "WARNING",
    }
    result = ev.evaluate("fast_cooling", cfg)
    assert result is not None


def test_rate_near_zero() -> None:
    """Stall detection: |dT/dt| < 0.1 K/мин."""
    t0 = time.time() - 90
    rd = _linear_rate_data("T12", rate_per_min=0.01, n=90, t0=t0)
    ev = _make_evaluator(rate_data={"T12": rd})

    cfg = {
        "alarm_type": "rate",
        "channel": "T12",
        "check": "rate_near_zero",
        "rate_threshold": 0.1,
        "rate_window_s": 90,
        "level": "INFO",
    }
    result = ev.evaluate("cooldown_stall", cfg)
    assert result is not None


def test_rate_no_data_no_fire() -> None:
    """Нет данных о скорости → нет аларма."""
    ev = _make_evaluator()
    cfg = {
        "alarm_type": "rate",
        "channel": "T1",
        "check": "rate_above",
        "threshold": 5.0,
        "rate_window_s": 90,
    }
    assert ev.evaluate("test", cfg) is None


# ---------------------------------------------------------------------------
# Stale
# ---------------------------------------------------------------------------


def test_stale_fires() -> None:
    """Нет данных > 30 с → stale аларм."""
    old_ts = time.time() - 60.0
    ev = _make_evaluator([_reading("T1", 4.2, ts=old_ts)])
    cfg = {
        "alarm_type": "stale",
        "channel": "T1",
        "timeout_s": 30,
        "level": "WARNING",
        "message": "Stale: {channel}",
    }
    result = ev.evaluate("data_stale", cfg)
    assert result is not None
    assert "T1" in result.channels


def test_stale_not_fires_fresh() -> None:
    """Свежие данные → нет аларма."""
    ev = _make_evaluator([_reading("T1", 4.2)])
    cfg = {"alarm_type": "stale", "channel": "T1", "timeout_s": 30}
    assert ev.evaluate("stale", cfg) is None


# ---------------------------------------------------------------------------
# AlarmStateManager
# ---------------------------------------------------------------------------


def _event(alarm_id: str = "a1", level: str = "WARNING") -> AlarmEvent:
    return AlarmEvent(
        alarm_id=alarm_id,
        level=level,
        message="test",
        triggered_at=time.time(),
        channels=["T1"],
        values={"T1": 5.0},
    )


def test_state_manager_triggered_once() -> None:
    mgr = AlarmStateManager()
    cfg = {}
    e = _event()
    assert mgr.process("a1", e, cfg) == "TRIGGERED"
    # Second call — dedup, no re-notify
    assert mgr.process("a1", e, cfg) is None
    assert "a1" in mgr.get_active()


def test_state_manager_cleared() -> None:
    mgr = AlarmStateManager()
    cfg = {}
    mgr.process("a1", _event(), cfg)
    result = mgr.process("a1", None, cfg)
    assert result == "CLEARED"
    assert "a1" not in mgr.get_active()


def test_state_manager_no_event_no_active() -> None:
    """None event when already cleared → None."""
    mgr = AlarmStateManager()
    assert mgr.process("a1", None, {}) is None


def test_state_manager_hysteresis() -> None:
    """Аларм сбрасывается (simplified: no value-based hysteresis in state manager)."""
    mgr = AlarmStateManager()
    mgr.process("a1", _event(), {})
    # With basic hysteresis config — should still clear (simplified impl)
    result = mgr.process("a1", None, {"hysteresis": {"pressure": 5e-4}})
    assert result == "CLEARED"


def test_state_manager_sustained_not_yet() -> None:
    """Sustained: условие держится, но ещё не выдержало N секунд → None."""
    mgr = AlarmStateManager()
    cfg = {"sustained_s": 60}
    e = _event()
    # First trigger — starts sustained timer
    result = mgr.process("a1", e, cfg)
    assert result is None  # sustained_since just set
    # Second call immediately — not enough time
    assert mgr.process("a1", e, cfg) is None


def test_state_manager_acknowledge() -> None:
    mgr = AlarmStateManager()
    mgr.process("a1", _event(), {})
    assert mgr.acknowledge("a1") is not None
    assert mgr.acknowledge("nonexistent") is None


def test_state_manager_history() -> None:
    mgr = AlarmStateManager()
    mgr.process("a1", _event(), {})
    mgr.process("a1", None, {})
    hist = mgr.get_history()
    assert len(hist) == 2
    assert hist[0]["transition"] == "TRIGGERED"
    assert hist[1]["transition"] == "CLEARED"


# ---------------------------------------------------------------------------
# Prefix resolution: config uses short ID, readings use full channel name
# ---------------------------------------------------------------------------


def test_threshold_alarm_with_full_channel_names() -> None:
    """Alarm config references short '\u042212', readings arrive as
    '\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2'.

    The ChannelStateTracker prefix resolution must bridge the gap.
    """
    # Feed readings with full channel names (as drivers produce)
    ev = _make_evaluator(
        [
            _reading(
                "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2",  # noqa: E501
                15.0,
            ),
        ]
    )
    # Config uses short channel ID (as in alarms_v3.yaml)
    cfg = {
        "alarm_type": "threshold",
        "channel": "\u042212",
        "check": "above",
        "threshold": 10.0,
        "level": "CRITICAL",
        "message": "\u042212 > 10K",
    }
    result = ev.evaluate("detector_warmup", cfg)
    assert result is not None
    assert result.level == "CRITICAL"


# ---------------------------------------------------------------------------
# Phase-2d A.9: AlarmStateManager.acknowledge real implementation
# ---------------------------------------------------------------------------


def test_acknowledge_transitions_active_alarm():
    """A.9: acknowledge must record state, operator, reason on active alarm."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="WARNING",
        message="test",
        triggered_at=time.time(),
        channels=["Т1"],
        values={"Т1": 300.0},
    )
    mgr._active["test_alarm"] = event

    result = mgr.acknowledge("test_alarm", operator="vladimir", reason="investigating")

    assert result is not None
    assert result["alarm_id"] == "test_alarm"
    assert result["operator"] == "vladimir"
    assert result["reason"] == "investigating"
    assert result["acknowledged_at"] > 0
    assert event.acknowledged is True
    assert event.acknowledged_at > 0
    assert event.acknowledged_by == "vladimir"


def test_acknowledge_records_history():
    """A.9: acknowledge must add ACKNOWLEDGED entry to history."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="CRITICAL",
        message="test",
        triggered_at=time.time(),
        channels=["Т7"],
        values={"Т7": 350.0},
    )
    mgr._active["test_alarm"] = event

    mgr.acknowledge("test_alarm", operator="op1", reason="seen")

    history = mgr.get_history()
    ack_entries = [h for h in history if h.get("transition") == "ACKNOWLEDGED"]
    assert len(ack_entries) == 1
    assert ack_entries[0]["alarm_id"] == "test_alarm"
    assert ack_entries[0]["operator"] == "op1"


def test_acknowledge_nonexistent_returns_none():
    """A.9: acknowledging non-existent alarm must return None (no event)."""
    mgr = AlarmStateManager()
    assert mgr.acknowledge("no_such_alarm") is None


def test_acknowledge_is_idempotent():
    """A.9 Codex: double-ack must not duplicate history entries."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="WARNING",
        message="test",
        triggered_at=time.time(),
        channels=["Т1"],
        values={"Т1": 300.0},
    )
    mgr._active["test_alarm"] = event

    first = mgr.acknowledge("test_alarm", operator="op1", reason="first")
    second = mgr.acknowledge("test_alarm", operator="op2", reason="second")

    assert first is not None  # newly acknowledged → event dict
    assert second is None  # already acknowledged → no event (idempotent)
    history = mgr.get_history()
    ack_entries = [h for h in history if h.get("transition") == "ACKNOWLEDGED"]
    assert len(ack_entries) == 1, f"Got {len(ack_entries)} ACK entries, expected 1"
    assert event.acknowledged_by == "op1"


def test_acknowledge_keeps_alarm_active():
    """A.9: acknowledged alarm stays in _active until CLEARED by condition."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="INFO",
        message="test",
        triggered_at=time.time(),
        channels=[],
        values={},
    )
    mgr._active["test_alarm"] = event

    mgr.acknowledge("test_alarm")

    assert "test_alarm" in mgr._active


# ---------------------------------------------------------------------------
# Tier 1 Fix C: Acknowledge event serialization tests
# ---------------------------------------------------------------------------


def test_acknowledge_event_fields_match_alarm_state():
    """A.9.1: returned event dict's acknowledged_at matches the alarm's state."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="sync_check",
        level="WARNING",
        message="test",
        triggered_at=time.time(),
        channels=["Т1"],
        values={"Т1": 300.0},
    )
    mgr._active["sync_check"] = event

    result = mgr.acknowledge("sync_check", operator="op1", reason="ok")

    assert result is not None
    assert result["acknowledged_at"] == event.acknowledged_at
    assert event.acknowledged_by == "op1"


def test_acknowledge_no_event_on_unknown_or_reack():
    """A.9.1: neither unknown alarm nor re-ack should produce an event."""
    mgr = AlarmStateManager()
    event = AlarmEvent(
        alarm_id="dup",
        level="INFO",
        message="test",
        triggered_at=time.time(),
        channels=[],
        values={},
    )
    mgr._active["dup"] = event

    assert mgr.acknowledge("nonexistent") is None
    first = mgr.acknowledge("dup")
    assert first is not None
    assert mgr.acknowledge("dup") is None  # idempotent, no event


# ---------------------------------------------------------------------------
# Codex-04 regression: cooldown_stall composite — threshold, not threshold_expr
# ---------------------------------------------------------------------------


def test_cooldown_stall_config_evaluates_without_threshold_keyerror(caplog) -> None:
    """Codex-04: composite cooldown_stall must not KeyError on 'above' condition.

    threshold_expr is not implemented; alarms_v3.yaml uses static threshold: 150.
    Т12=200 K > 150, rate≈0 K/мин → both AND conditions true → alarm fires.
    """
    t0 = time.time() - 90
    rate_points = _linear_rate_data("Т12", rate_per_min=0.01, n=90, start_val=200.0, t0=t0)
    ev = _make_evaluator([_reading("Т12", 200.0)], rate_data={"Т12": rate_points})
    cfg = {
        "alarm_type": "composite",
        "operator": "AND",
        "conditions": [
            {"channel": "Т12", "check": "rate_near_zero", "rate_threshold": 0.1, "rate_window_s": 900},
            {"channel": "Т12", "check": "above", "threshold": 150},
        ],
        "level": "WARNING",
        "message": "Охлаждение остановилось, Т12 далеко от setpoint.",
        "notify": ["gui", "telegram"],
    }

    with caplog.at_level("ERROR", logger="cryodaq.core.alarm_v2"):
        result = ev.evaluate("cooldown_stall", cfg)

    assert result is not None
    assert "Ошибка evaluate cooldown_stall" not in caplog.text


# ---------------------------------------------------------------------------
# F21 — Hysteresis deadband (alarm clears only below threshold - margin)
# ---------------------------------------------------------------------------


def _threshold_cfg(
    channel: str,
    threshold: float,
    hysteresis: float | None = None,
    check: str = "above",
) -> dict:
    cfg: dict = {
        "alarm_type": "threshold",
        "channel": channel,
        "check": check,
        "threshold": threshold,
        "level": "WARNING",
        "message": f"{channel} alarm",
    }
    if hysteresis is not None:
        cfg["hysteresis"] = hysteresis
    return cfg


def test_hysteresis_deadband_clears_only_below_margin() -> None:
    """Alarm stays active when value is in [threshold - hysteresis, threshold] deadband.

    With threshold=10.0 and hysteresis=2.0:
    - value=9.5 (deadband: 9.5 >= 10-2=8) → evaluate(is_active=True) returns event (keep active)
    - value=7.9 (below deadband) → evaluate(is_active=True) returns None (allow clear)
    """
    cfg = _threshold_cfg("T1", threshold=10.0, hysteresis=2.0)

    # In deadband: value dropped below threshold but not below threshold - hysteresis
    ev_deadband = _make_evaluator([_reading("T1", 9.5)])
    result = ev_deadband.evaluate("test_hyst", cfg, is_active=True)
    assert result is not None, "Deadband: alarm should remain active (keep event returned)"
    assert result.alarm_id == "test_hyst"

    # Below deadband: value cleared the margin → alarm clears
    ev_cleared = _make_evaluator([_reading("T1", 7.9)])
    result = ev_cleared.evaluate("test_hyst", cfg, is_active=True)
    assert result is None, "Below deadband: alarm should clear (None returned)"


def test_hysteresis_deadband_not_applied_when_alarm_inactive() -> None:
    """Hysteresis deadband only activates when is_active=True.

    Without is_active, value=9.5 (below threshold=10) → normal None return.
    """
    cfg = _threshold_cfg("T1", threshold=10.0, hysteresis=2.0)
    ev = _make_evaluator([_reading("T1", 9.5)])
    result = ev.evaluate("test_hyst", cfg, is_active=False)
    assert result is None, "is_active=False → no deadband check, normal clear"


def test_hysteresis_below_check_deadband() -> None:
    """Hysteresis works for check='below' direction.

    threshold=5.0, hysteresis=1.0:
    - value=5.5 (in deadband: 5.5 <= 5+1=6) → keep active
    - value=6.5 (above deadband) → clear
    """
    cfg = _threshold_cfg("T1", threshold=5.0, hysteresis=1.0, check="below")

    ev_deadband = _make_evaluator([_reading("T1", 5.5)])
    result = ev_deadband.evaluate("test_hyst_below", cfg, is_active=True)
    assert result is not None, "Deadband (below): keep active"

    ev_cleared = _make_evaluator([_reading("T1", 6.5)])
    result = ev_cleared.evaluate("test_hyst_below", cfg, is_active=True)
    assert result is None, "Above deadband (below check): allow clear"


def test_no_hysteresis_config_clears_normally() -> None:
    """Without hysteresis key in config, clearing behaviour unchanged."""
    cfg = _threshold_cfg("T1", threshold=10.0, hysteresis=None)  # no hysteresis
    ev = _make_evaluator([_reading("T1", 9.5)])
    result = ev.evaluate("test_no_hyst", cfg, is_active=True)
    assert result is None, "No hysteresis → normal clear when below threshold"


# ---------------------------------------------------------------------------
# F22 — Diagnostic alarm severity-upgrade (warning → critical in-place)
# ---------------------------------------------------------------------------


def test_warning_then_critical_severity_upgrade() -> None:
    """Critical replaces warning in-place: same alarm_id, level upgraded to CRITICAL.

    Sequence: publish warning → publish critical → expect SEVERITY_UPGRADED in history
    and _active[alarm_id].level == "CRITICAL".
    """
    mgr = AlarmStateManager()

    # Step 1: warning fires
    warn_event = mgr.publish_diagnostic_alarm("T1", "warning", 300.0)
    assert warn_event is not None
    assert warn_event.level == "WARNING"
    assert mgr.get_active()["diag:T1"].level == "WARNING"

    # Step 2: critical fires → severity upgrade
    crit_event = mgr.publish_diagnostic_alarm("T1", "critical", 900.0)
    assert crit_event is not None, "Severity upgrade should return the upgraded AlarmEvent"
    assert crit_event.level == "CRITICAL"
    assert mgr.get_active()["diag:T1"].level == "CRITICAL"

    # History should contain SEVERITY_UPGRADED transition
    history = mgr.get_history()
    transitions = [h["transition"] for h in history]
    assert "SEVERITY_UPGRADED" in transitions


def test_critical_no_duplicate_when_already_critical() -> None:
    """publish_diagnostic_alarm returns None when level is same or lower than active."""
    mgr = AlarmStateManager()

    mgr.publish_diagnostic_alarm("T1", "warning", 300.0)
    mgr.publish_diagnostic_alarm("T1", "critical", 900.0)  # upgrade

    # Second critical on same alarm → no-op
    result = mgr.publish_diagnostic_alarm("T1", "critical", 1000.0)
    assert result is None, "Duplicate critical should be no-op"

    # Warning on active critical → no-op (lower severity)
    result = mgr.publish_diagnostic_alarm("T1", "warning", 1000.0)
    assert result is None, "Lower severity on active critical should be no-op"
    assert mgr.get_active()["diag:T1"].level == "CRITICAL"


def test_severity_upgrade_message_updated() -> None:
    """Upgraded alarm's message reflects the critical age_seconds."""
    mgr = AlarmStateManager()
    mgr.publish_diagnostic_alarm("T1", "warning", 300.0)
    crit_event = mgr.publish_diagnostic_alarm("T1", "critical", 1234.0)
    assert crit_event is not None
    assert "1234" in crit_event.message


def test_hysteresis_deadband_non_triggering_channel_does_not_keep_active() -> None:
    """Codex finding: non-triggering channel in deadband must not keep alarm active.

    Multi-channel alarm: T1 triggered (value was > threshold), T2 never triggered.
    After T1 clears below deadband, T2 in deadband must NOT return keep-active event.
    active_channels={T1} → T2 skipped in deadband check → returns None (alarm clears).
    """
    cfg = {
        "alarm_type": "threshold",
        "channels": ["T1", "T2"],
        "check": "above",
        "threshold": 10.0,
        "hysteresis": 2.0,
        "level": "WARNING",
        "message": "test",
    }

    # T1 dropped below deadband (7.5 < 8.0), T2 in deadband (9.5 in [8, 10])
    # active_channels={T1} means only T1's deadband is checked
    ev = _make_evaluator([_reading("T1", 7.5), _reading("T2", 9.5)])

    # With active_channels pointing to T1: T1 below deadband → skip; T2 not in
    # active_channels → skip deadband → returns None (alarm clears correctly)
    result = ev.evaluate("test_multi", cfg, is_active=True, active_channels=frozenset(["T1"]))
    assert result is None, "Non-triggering channel T2 should not keep alarm active"

    # Without active_channels (old behavior): T2 in deadband → returns keep-active
    result_old = ev.evaluate("test_multi", cfg, is_active=True, active_channels=None)
    assert result_old is not None, "Without active_channels guard, T2 keeps alarm active (old behavior)"
