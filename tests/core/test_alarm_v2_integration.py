"""Integration tests for Alarm Engine v2: evaluator + state_mgr + providers pipeline."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

from cryodaq.core.alarm_config import AlarmConfig, SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmEvent, AlarmStateManager
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


def _make_stack(
    phase: str | None = None,
    setpoints: dict | None = None,
) -> tuple[ChannelStateTracker, RateEstimator, AlarmEvaluator, AlarmStateManager]:
    state = ChannelStateTracker()
    rate = RateEstimator(window_s=120.0, min_points=2)

    mgr = MagicMock()
    mgr.get_current_phase.return_value = phase
    mgr.get_active_experiment.return_value = None
    mgr.get_phase_history.return_value = []

    phase_provider = ExperimentPhaseProvider(mgr)

    sp_defs: dict[str, SetpointDef] = {}
    if setpoints:
        for k, v in setpoints.items():
            sp_defs[k] = SetpointDef(key=k, source="constant", default=float(v))
    sp_provider = ExperimentSetpointProvider(mgr, sp_defs)

    evaluator = AlarmEvaluator(state, rate, phase_provider, sp_provider)
    state_mgr = AlarmStateManager()
    return state, rate, evaluator, state_mgr


# ---------------------------------------------------------------------------
# Phase-filtered alarm: only fires in correct phase
# ---------------------------------------------------------------------------


def test_phase_alarm_suppressed_outside_phase() -> None:
    state, rate, ev, sm = _make_stack(phase="vacuum")
    state.update(_reading("T12", 5.5))

    alarm_cfg = AlarmConfig(
        alarm_id="detector_drift",
        config={
            "alarm_type": "threshold",
            "channel": "T12",
            "check": "deviation_from_setpoint",
            "setpoint_source": "T12_setpoint",
            "threshold": 0.5,
            "level": "WARNING",
        },
        phase_filter=["measurement"],
    )

    # Current phase = "vacuum", filter = ["measurement"] → should not evaluate
    current_phase = ev._phase.get_current_phase()
    should_skip = alarm_cfg.phase_filter is not None and current_phase not in alarm_cfg.phase_filter
    assert should_skip  # logic: suppressed


def test_phase_alarm_fires_in_correct_phase() -> None:
    """Detector drift alarm fires when phase matches."""
    state, rate, ev, sm = _make_stack(phase="measurement", setpoints={"T12_setpoint": 4.2})
    state.update(_reading("T12", 5.5))

    cfg = {
        "alarm_type": "threshold",
        "channel": "T12",
        "check": "deviation_from_setpoint",
        "setpoint_source": "T12_setpoint",
        "threshold": 0.5,
        "level": "WARNING",
    }
    event = ev.evaluate("detector_drift", cfg)
    assert event is not None
    transition = sm.process("detector_drift", event, cfg)
    assert transition == "TRIGGERED"


# ---------------------------------------------------------------------------
# Full tick simulation
# ---------------------------------------------------------------------------


def _simulate_tick(
    evaluator: AlarmEvaluator,
    state_mgr: AlarmStateManager,
    alarm_cfgs: list[AlarmConfig],
    current_phase: str | None,
) -> dict[str, str]:
    """Simulate one alarm tick, return alarm_id → transition for those that changed."""
    transitions: dict[str, str] = {}
    for alarm_cfg in alarm_cfgs:
        if alarm_cfg.phase_filter is not None:
            if current_phase not in alarm_cfg.phase_filter:
                state_mgr.process(alarm_cfg.alarm_id, None, alarm_cfg.config)
                continue
        event = evaluator.evaluate(alarm_cfg.alarm_id, alarm_cfg.config)
        t = state_mgr.process(alarm_cfg.alarm_id, event, alarm_cfg.config)
        if t is not None:
            transitions[alarm_cfg.alarm_id] = t
    return transitions


def test_tick_global_triggers_regardless_of_phase() -> None:
    state, rate, ev, sm = _make_stack(phase=None)
    state.update(_reading("T3", 999.0))  # outside [0, 350]

    alarms = [
        AlarmConfig(
            alarm_id="sensor_fault_T3",
            config={
                "alarm_type": "threshold",
                "channel": "T3",
                "check": "outside_range",
                "range": [0.0, 350.0],
                "level": "WARNING",
            },
            phase_filter=None,  # global
        )
    ]
    t = _simulate_tick(ev, sm, alarms, current_phase=None)
    assert t.get("sensor_fault_T3") == "TRIGGERED"


def test_tick_clears_when_condition_resolves() -> None:
    state, rate, ev, sm = _make_stack(phase=None)
    state.update(_reading("T3", 999.0))

    cfg = {
        "alarm_type": "threshold",
        "channel": "T3",
        "check": "outside_range",
        "range": [0.0, 350.0],
        "level": "WARNING",
    }
    alarms = [AlarmConfig(alarm_id="sensor_fault", config=cfg, phase_filter=None)]

    # Tick 1: triggered
    t1 = _simulate_tick(ev, sm, alarms, None)
    assert t1.get("sensor_fault") == "TRIGGERED"

    # Update to normal value
    state.update(_reading("T3", 77.0))

    # Tick 2: cleared
    t2 = _simulate_tick(ev, sm, alarms, None)
    assert t2.get("sensor_fault") == "CLEARED"


def test_tick_dedup_no_retrigger() -> None:
    state, rate, ev, sm = _make_stack(phase=None)
    state.update(_reading("T3", 999.0))

    cfg = {
        "alarm_type": "threshold",
        "channel": "T3",
        "check": "outside_range",
        "range": [0.0, 350.0],
        "level": "WARNING",
    }
    alarms = [AlarmConfig(alarm_id="sensor_fault", config=cfg, phase_filter=None)]

    t1 = _simulate_tick(ev, sm, alarms, None)
    assert t1.get("sensor_fault") == "TRIGGERED"

    # Second tick — still faulty, should be deduped
    t2 = _simulate_tick(ev, sm, alarms, None)
    assert "sensor_fault" not in t2  # no re-notify


# ---------------------------------------------------------------------------
# alarm_v2_status command shape
# ---------------------------------------------------------------------------


def test_alarm_v2_status_shape() -> None:
    _, _, ev, sm = _make_stack()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="WARNING",
        message="Test",
        triggered_at=time.time(),
        channels=["T1"],
        values={"T1": 5.0},
    )
    sm.process("test_alarm", event, {})

    active = sm.get_active()
    assert "test_alarm" in active
    a = active["test_alarm"]
    # Fields expected by alarm_v2_status command handler
    assert a.level == "WARNING"
    assert a.message == "Test"
    assert isinstance(a.triggered_at, float)
    assert a.channels == ["T1"]


def test_alarm_v2_ack() -> None:
    _, _, ev, sm = _make_stack()
    event = AlarmEvent(
        alarm_id="ack_test",
        level="CRITICAL",
        message="Test",
        triggered_at=time.time(),
        channels=["T12"],
        values={"T12": 10.0},
    )
    sm.process("ack_test", event, {})
    assert sm.acknowledge("ack_test") is not None
    assert sm.acknowledge("nonexistent") is None
