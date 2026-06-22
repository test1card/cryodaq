"""Integration tests for Alarm Engine v2: evaluator + state_mgr + providers pipeline."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

from cryodaq.core.alarm_config import AlarmConfig, SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmEvent, AlarmStateManager, tick_alarm
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
    # Phase = vacuum, but this alarm only applies in measurement. A reading that
    # WOULD breach the threshold must be suppressed by the phase filter. Prove it
    # by running the real evaluator + state-manager tick (mirrors the production
    # loop at engine.py:2064), not by re-deriving the filter boolean in the test.
    state, rate, ev, sm = _make_stack(phase="vacuum", setpoints={"T12_setpoint": 4.2})
    state.update(_reading("T12", 5.5))  # deviation 1.3 K > threshold 0.5 → would fire

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

    transitions = _simulate_tick(ev, sm, [alarm_cfg], current_phase="vacuum")
    assert "detector_drift" not in transitions, (
        f"alarm must be suppressed outside its phase filter, got transition {transitions}"
    )

    # Positive control: the SAME reading DOES fire once the phase matches — guards
    # against a false pass where the threshold simply never breaches.
    state2, rate2, ev2, sm2 = _make_stack(phase="measurement", setpoints={"T12_setpoint": 4.2})
    state2.update(_reading("T12", 5.5))
    fired = _simulate_tick(ev2, sm2, [alarm_cfg], current_phase="measurement")
    assert fired.get("detector_drift") == "TRIGGERED", (
        f"alarm must fire inside its phase filter, got {fired}"
    )


def test_phase_alarm_fires_in_correct_phase() -> None:
    """Detector drift alarm fires when phase matches — tested via tick_alarm production path.

    The alarm carries phase_filter=["measurement"] and tick_alarm is called with
    current_phase="measurement", so phase-filter suppression is exercised.
    A broken phase-filter implementation would suppress this and the assertion fails.
    """
    state, rate, ev, sm = _make_stack(phase="measurement", setpoints={"T12_setpoint": 4.2})
    state.update(_reading("T12", 5.5))  # deviation 1.3 K > threshold 0.5 → fires

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

    transitions = _simulate_tick(ev, sm, [alarm_cfg], current_phase="measurement")
    assert transitions.get("detector_drift") == "TRIGGERED", (
        f"alarm with phase_filter=['measurement'] must fire when current_phase='measurement', "
        f"got {transitions}"
    )


# ---------------------------------------------------------------------------
# Full tick simulation
# ---------------------------------------------------------------------------


def _simulate_tick(
    evaluator: AlarmEvaluator,
    state_mgr: AlarmStateManager,
    alarm_cfgs: list[AlarmConfig],
    current_phase: str | None,
) -> dict[str, str]:
    """Simulate one alarm tick via the PRODUCTION tick_alarm (the same function
    the engine's alarm loop runs), returning alarm_id → transition for those that
    changed. Using the production helper means phase-filter suppression is tested
    against real code, not a reimplementation."""
    transitions: dict[str, str] = {}
    for alarm_cfg in alarm_cfgs:
        _event, t = tick_alarm(alarm_cfg, current_phase, evaluator, state_mgr)
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
    # Exercise the serialization path used by the alarm_v2_status command handler
    # (engine.py ~line 2347): build the same dict the handler emits and assert
    # all required fields are present and well-typed.
    _, _, ev, sm = _make_stack()
    t_triggered = time.time()
    event = AlarmEvent(
        alarm_id="test_alarm",
        level="WARNING",
        message="Test",
        triggered_at=t_triggered,
        channels=["T1"],
        values={"T1": 5.0},
    )
    sm.process("test_alarm", event, {})

    active = sm.get_active()
    assert "test_alarm" in active

    # Reproduce the exact serialization the engine handler performs:
    # active_payload mirrors engine.py alarm_v2_status branch.
    active_payload = {
        k: {
            "level": v.level,
            "message": v.message,
            "triggered_at": v.triggered_at,
            "channels": v.channels,
            "acknowledged": v.acknowledged,
            "acknowledged_at": v.acknowledged_at,
            "acknowledged_by": v.acknowledged_by,
        }
        for k, v in active.items()
    }
    history = sm.get_history(limit=20)
    response = {"ok": True, "active": active_payload, "history": history}

    assert response["ok"] is True
    assert "test_alarm" in response["active"]
    a = response["active"]["test_alarm"]
    assert a["level"] == "WARNING"
    assert a["message"] == "Test"
    assert isinstance(a["triggered_at"], float)
    assert a["triggered_at"] == t_triggered
    assert a["channels"] == ["T1"]
    assert a["acknowledged"] is False
    assert isinstance(a["acknowledged_at"], float)
    assert a["acknowledged_by"] == ""
    assert isinstance(response["history"], list)


def test_alarm_v2_ack() -> None:
    # Exercise the acknowledge() return-dict shape used by the alarm_v2_ack
    # command handler (engine.py ~line 2392): handler publishes ack_event["acknowledged_at"]
    # and returns ok/alarm_name/acknowledged_at/event_emitted.
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

    ack_dict = sm.acknowledge("ack_test", operator="operator1", reason="test reason")
    assert ack_dict is not None, "acknowledge() must return a dict on first call"
    assert ack_dict["alarm_id"] == "ack_test"
    assert isinstance(ack_dict["acknowledged_at"], float)
    assert ack_dict["acknowledged_at"] > 0.0
    assert ack_dict["operator"] == "operator1"
    assert ack_dict["reason"] == "test reason"

    # Alarm must be flagged as acknowledged in the active state
    active = sm.get_active()
    assert "ack_test" in active, "acknowledged alarm must stay in active until cleared"
    assert active["ack_test"].acknowledged is True
    assert active["ack_test"].acknowledged_by == "operator1"

    # Idempotent: second ack on same alarm returns None
    assert sm.acknowledge("ack_test") is None, "second acknowledge() must be a no-op (None)"

    # Unknown alarm returns None
    assert sm.acknowledge("nonexistent") is None
