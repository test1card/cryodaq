"""v0.55.12 — regression guards for the cooldown-alarm safety hotfix.

Covers audit SCOPE 1 fixes:
- 1.1 — CooldownAlarm CRITICAL escalates via SafetyManager.latch_fault
- 1.2 — phase change away from cooldown disarms the alarm
- 1.3 — tick() race aborts on disarm/phase-change mid-flight
- 1.4 — auto_arm + watchdog_enabled YAML overrides honoured
- 1.5 — cold-start auto-detect skips arm()
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.channel_state import ChannelState
from cryodaq.core.cooldown_alarm import ALARM_ID, CooldownAlarm, CooldownState
from cryodaq.core.physical_alarms_config import (
    _COOLDOWN_DEFAULTS,
    load_physical_alarms_config,
)


def _make_ch(ch: str, value: float, stale: bool = False) -> ChannelState:
    return ChannelState(
        channel=ch, value=value, timestamp=time.time(),
        unit="K", instrument_id="test", is_stale=stale,
    )


def _make_alarm(model_dir: Path | None = None, cfg_overrides: dict | None = None,
                safety_manager=None):
    cfg = {
        "cold_channel": "Т12",
        "warm_channel": "Т11",
        "k_p": 2.5,
        "sustained_min": 3,
        "base_temp_K": 5.0,
        "base_epsilon_K": 1.0,
        "auto_disarm_progress": 0.95,
        "eta_slip_window_min": 60,
        "eta_slip_message_threshold_h": 0.5,
        "predictor_model_path": str((model_dir or Path("model")) / "predictor_model.json"),
    }
    if cfg_overrides:
        cfg.update(cfg_overrides)

    tracker = MagicMock()
    alarm_mgr = MagicMock()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    alarm = CooldownAlarm(
        cfg, tracker, alarm_mgr, event_bus, safety_manager=safety_manager
    )
    return alarm, tracker, alarm_mgr, event_bus


def _fake_model(duration_mean: float = 72.0, duration_std: float = 8.0):
    model = MagicMock()
    model.n_curves = 5
    model.duration_mean = duration_mean
    model.duration_std = duration_std
    model._p_of_t_mean = lambda t: min(1.0, t / duration_mean)
    return model


# ---------------------------------------------------------------------------
# 1.1 — SafetyManager.latch_fault public API
# ---------------------------------------------------------------------------


def test_safety_manager_has_public_latch_fault_method():
    from cryodaq.core.safety_manager import SafetyManager
    assert hasattr(SafetyManager, "latch_fault")
    assert callable(SafetyManager.latch_fault)


@pytest.mark.asyncio
async def test_latch_fault_delegates_to_private_fault():
    """latch_fault wraps _fault, preserving args + adding source kwarg."""
    from cryodaq.core.safety_manager import SafetyManager

    sm = MagicMock(spec=SafetyManager)
    sm._fault = AsyncMock()
    # Bind real method to mock
    await SafetyManager.latch_fault(
        sm, reason="test reason", source="cooldown_alarm",
    )
    sm._fault.assert_awaited_once_with(
        reason="test reason",
        channel="",
        value=0.0,
        source="cooldown_alarm",
    )


@pytest.mark.asyncio
async def test_latch_fault_forwards_optional_channel_value():
    """Engine interlock-escalation path retains channel/value via the
    public API."""
    from cryodaq.core.safety_manager import SafetyManager

    sm = MagicMock(spec=SafetyManager)
    sm._fault = AsyncMock()
    await SafetyManager.latch_fault(
        sm,
        reason="interlock failure",
        source="interlock",
        channel="smua",
        value=42.0,
    )
    sm._fault.assert_awaited_once_with(
        reason="interlock failure",
        channel="smua",
        value=42.0,
        source="interlock",
    )


@pytest.mark.asyncio
async def test_cooldown_alarm_critical_calls_latch_fault(tmp_path):
    """When the alarm transitions FIRED→fires, it must escalate to
    SafetyManager.latch_fault with source='cooldown_alarm'."""
    safety_manager = MagicMock()
    safety_manager.latch_fault = AsyncMock()

    alarm, tracker, alarm_mgr, _ = _make_alarm(
        model_dir=tmp_path, safety_manager=safety_manager,
    )
    alarm._model = _fake_model(duration_mean=72.0, duration_std=8.0)
    alarm._t_armed = time.monotonic() - 3600  # 1h elapsed (past baseline)
    alarm._state = CooldownState.WATCHING

    # Set up readings: cold T well above base, deviation large
    tracker.get.side_effect = lambda ch: (
        _make_ch(ch, 60.0) if ch == "Т12" else _make_ch(ch, 80.0)
    )

    # Force sustained count to threshold so the next tick fires
    alarm._sustained_count = alarm._sustained_min - 1

    # Stub model._p_of_t_mean to return high expected progress
    alarm._model._p_of_t_mean = lambda t: 0.9  # expected 90%
    alarm._model.duration_mean = 72.0
    alarm._model.duration_std = 8.0

    # Force the predictor.predict to return low actual progress (so deviation > k_p*sigma)
    import cryodaq.analytics.cooldown_predictor as cdp
    original_predict = cdp.predict
    fake_pred = MagicMock(progress=0.1, t_remaining_hours=10.0)
    cdp.predict = MagicMock(return_value=fake_pred)
    try:
        await alarm.tick()
    finally:
        cdp.predict = original_predict

    safety_manager.latch_fault.assert_awaited_once()
    call_kwargs = safety_manager.latch_fault.await_args.kwargs
    assert call_kwargs["source"] == "cooldown_alarm"
    assert "Захолаживание" in call_kwargs["reason"]


@pytest.mark.asyncio
async def test_cooldown_alarm_critical_swallows_latch_fault_exception(tmp_path):
    """latch_fault failure must NOT propagate — alarm tick keeps running.

    Strengthened: verifies latch_fault was actually awaited, alarm reached
    FIRED state, and alarm_mgr.process received a non-None (CRITICAL) event.
    """
    safety_manager = MagicMock()
    safety_manager.latch_fault = AsyncMock(side_effect=RuntimeError("safety down"))

    alarm, tracker, alarm_mgr, _ = _make_alarm(
        model_dir=tmp_path, safety_manager=safety_manager,
    )
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 3600
    alarm._state = CooldownState.WATCHING
    alarm._sustained_count = alarm._sustained_min - 1
    alarm._model._p_of_t_mean = lambda t: 0.9
    tracker.get.side_effect = lambda ch: (
        _make_ch(ch, 60.0) if ch == "Т12" else _make_ch(ch, 80.0)
    )

    import cryodaq.analytics.cooldown_predictor as cdp
    original_predict = cdp.predict
    cdp.predict = MagicMock(return_value=MagicMock(progress=0.1, t_remaining_hours=10.0))
    try:
        # Must not raise even though latch_fault raises
        await alarm.tick()
    finally:
        cdp.predict = original_predict

    # latch_fault must have been called (not silently skipped)
    safety_manager.latch_fault.assert_awaited_once()
    # Alarm must have transitioned to FIRED
    assert alarm.state == CooldownState.FIRED
    # alarm_mgr.process must have been called with a CRITICAL event carrying the expected alarm_id
    critical_calls = [
        c for c in alarm_mgr.process.call_args_list
        if len(c.args) >= 2 and c.args[1] is not None
    ]
    assert critical_calls, "alarm_mgr.process must be called with a non-None CRITICAL event"
    event = critical_calls[-1].args[1]
    assert event.level == "CRITICAL", f"expected CRITICAL, got {event.level!r}"
    assert event.alarm_id == "cooldown_alarm", f"expected alarm_id='cooldown_alarm', got {event.alarm_id!r}"


def test_cooldown_alarm_constructible_without_safety_manager():
    """safety_manager defaults to None — backward compat for unit tests
    that don't care about the safety wiring."""
    alarm, *_ = _make_alarm()
    assert alarm._safety_manager is None


# ---------------------------------------------------------------------------
# 1.2 — Phase-skip handling
# ---------------------------------------------------------------------------


def test_notify_phase_change_to_non_cooldown_disarms_armed():
    alarm, _, alarm_mgr, _ = _make_alarm()
    alarm._state = CooldownState.ARMED
    alarm.notify_phase_change("measurement")
    assert alarm.state == CooldownState.DISARMED


def test_notify_phase_change_to_non_cooldown_disarms_fired():
    alarm, _, alarm_mgr, _ = _make_alarm()
    alarm._state = CooldownState.FIRED
    alarm.notify_phase_change("warmup")
    assert alarm.state == CooldownState.DISARMED


def test_notify_phase_change_to_non_cooldown_disarms_watchdog():
    alarm, _, _, _ = _make_alarm()
    alarm._state = CooldownState.WATCHDOG
    alarm.notify_phase_change("measurement")
    assert alarm.state == CooldownState.DISARMED


def test_notify_phase_change_to_cooldown_does_not_disarm_already_armed():
    alarm, *_ = _make_alarm()
    alarm._state = CooldownState.ARMED
    alarm.notify_phase_change("cooldown")
    # Stays ARMED — engine's auto-arm path is the one that re-arms
    assert alarm.state == CooldownState.ARMED


def test_notify_phase_change_disarmed_idempotent():
    alarm, *_ = _make_alarm()
    alarm._state = CooldownState.DISARMED
    alarm.notify_phase_change("measurement")
    assert alarm.state == CooldownState.DISARMED


def test_notify_phase_change_to_cooldown_clears_cold_start_flag():
    alarm, *_ = _make_alarm()
    alarm._cold_start_skipped = True
    alarm.notify_phase_change("cooldown")
    assert alarm._cold_start_skipped is False


# ---------------------------------------------------------------------------
# 1.3 — tick() race / cycle generation
# ---------------------------------------------------------------------------


def test_disarm_increments_cycle_generation():
    alarm, *_ = _make_alarm()
    initial = alarm._cycle_generation
    alarm._state = CooldownState.ARMED  # disarm only fires the bump on real disarms
    alarm.disarm()
    assert alarm._cycle_generation == initial + 1


def test_notify_phase_change_disarm_increments_cycle_generation():
    alarm, *_ = _make_alarm()
    alarm._state = CooldownState.WATCHING
    initial = alarm._cycle_generation
    alarm.notify_phase_change("measurement")
    assert alarm._cycle_generation > initial


@pytest.mark.asyncio
async def test_tick_aborts_when_cycle_invalidated_during_publish(tmp_path):
    """Disarm during the publish_state_event await must prevent the
    subsequent alarm_state_mgr.process() and latch_fault calls from
    firing on stale state."""
    safety_manager = MagicMock()
    safety_manager.latch_fault = AsyncMock()

    alarm, tracker, alarm_mgr, event_bus = _make_alarm(
        model_dir=tmp_path, safety_manager=safety_manager,
    )
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 3600
    alarm._state = CooldownState.WATCHING
    alarm._sustained_count = alarm._sustained_min - 1
    alarm._model._p_of_t_mean = lambda t: 0.9
    tracker.get.side_effect = lambda ch: (
        _make_ch(ch, 60.0) if ch == "Т12" else _make_ch(ch, 80.0)
    )

    # Make publish_state_event bump the cycle DURING its await — simulating
    # an operator disarm landing between sustained_count >= threshold and
    # alarm_state_mgr.process().
    async def disrupting_publish():
        alarm._cycle_generation += 1  # invalidate the captured cycle

    alarm._publish_state_event = disrupting_publish

    import cryodaq.analytics.cooldown_predictor as cdp
    cdp.predict = MagicMock(return_value=MagicMock(progress=0.1, t_remaining_hours=10.0))

    result = await alarm.tick()
    # Tick must return None (aborted) and never call latch_fault or process
    assert result is None
    safety_manager.latch_fault.assert_not_awaited()
    # alarm_state_mgr.process was not called for the CRITICAL event because
    # the cycle check fired before it.
    assert not any(
        c.args and c.args[0] == ALARM_ID and c.args[1] is not None
        for c in alarm_mgr.process.call_args_list
    )


# ---------------------------------------------------------------------------
# 1.4 — YAML overrides honoured
# ---------------------------------------------------------------------------


def test_defaults_include_auto_arm():
    assert "auto_arm" in _COOLDOWN_DEFAULTS
    assert _COOLDOWN_DEFAULTS["auto_arm"] is True


def test_defaults_include_watchdog_enabled():
    assert "watchdog_enabled" in _COOLDOWN_DEFAULTS
    assert _COOLDOWN_DEFAULTS["watchdog_enabled"] is False


def test_defaults_include_watchdog_margin():
    assert "watchdog_margin_K" in _COOLDOWN_DEFAULTS
    assert math.isclose(_COOLDOWN_DEFAULTS["watchdog_margin_K"], 1.0)


def test_defaults_include_cold_start_margin():
    assert "cold_start_skip_margin_K" in _COOLDOWN_DEFAULTS


def test_yaml_auto_arm_false_honored(tmp_path):
    """v0.55.12 — operator setting auto_arm: false must reach the alarm
    object; previously silently dropped because absent from defaults."""
    yaml_path = tmp_path / "physical_alarms.yaml"
    yaml_path.write_text(
        "cooldown:\n"
        "  auto_arm: false\n"
        "  watchdog_enabled: true\n",
        encoding="utf-8",
    )
    cooldown_cfg, _ = load_physical_alarms_config(yaml_path)
    assert cooldown_cfg["auto_arm"] is False
    assert cooldown_cfg["watchdog_enabled"] is True


def test_yaml_watchdog_enabled_true_honored(tmp_path):
    yaml_path = tmp_path / "physical_alarms.yaml"
    yaml_path.write_text(
        "cooldown:\n"
        "  watchdog_enabled: true\n"
        "  watchdog_margin_K: 2.5\n",
        encoding="utf-8",
    )
    cooldown_cfg, _ = load_physical_alarms_config(yaml_path)
    assert cooldown_cfg["watchdog_enabled"] is True
    assert math.isclose(cooldown_cfg["watchdog_margin_K"], 2.5)


def test_alarm_constructed_with_auto_arm_false_disables_auto_arm():
    alarm, *_ = _make_alarm(cfg_overrides={"auto_arm": False})
    assert alarm.is_auto_arm_enabled is False


# ---------------------------------------------------------------------------
# 1.5 — Cold-start auto-detect
# ---------------------------------------------------------------------------


def test_cold_start_detected_when_cold_in_base_range():
    alarm, tracker, *_ = _make_alarm(cfg_overrides={"base_temp_K": 5.0})
    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.0)  # cold = 6K, in [5, 10]
    assert alarm._is_cold_start() is True


def test_cold_start_not_detected_when_cold_above_range():
    alarm, tracker, *_ = _make_alarm(
        cfg_overrides={"base_temp_K": 5.0, "cold_start_skip_margin_K": 5.0}
    )
    tracker.get.side_effect = lambda ch: _make_ch(ch, 80.0)  # cold = 80K, way above
    assert alarm._is_cold_start() is False


def test_cold_start_not_detected_when_reading_stale():
    alarm, tracker, *_ = _make_alarm(cfg_overrides={"base_temp_K": 5.0})
    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.0, stale=True)
    assert alarm._is_cold_start() is False


def test_cold_start_not_detected_when_reading_missing():
    alarm, tracker, *_ = _make_alarm()
    tracker.get.return_value = None
    assert alarm._is_cold_start() is False


def test_cold_start_with_steady_predictor_quasi_steady_true():
    alarm, tracker, *_ = _make_alarm(cfg_overrides={"base_temp_K": 5.0})
    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.0)
    pred = MagicMock(is_quasi_steady=True)
    ssp = MagicMock()
    ssp.get_prediction = MagicMock(return_value=pred)
    alarm._steady_state_predictor = ssp
    assert alarm._is_cold_start() is True


def test_cold_start_rejected_when_steady_predictor_says_not_quasi_steady():
    """Cold-temperature reading alone isn't enough if the predictor says
    the system is still drifting (e.g. gas-desorption rebound)."""
    alarm, tracker, *_ = _make_alarm(cfg_overrides={"base_temp_K": 5.0})
    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.0)
    pred = MagicMock(is_quasi_steady=False)
    ssp = MagicMock()
    ssp.get_prediction = MagicMock(return_value=pred)
    alarm._steady_state_predictor = ssp
    assert alarm._is_cold_start() is False


def test_arm_skips_when_cold_start_detected_and_logs(tmp_path, caplog):
    alarm, tracker, *_ = _make_alarm(model_dir=tmp_path)
    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.0)
    with caplog.at_level(logging.INFO):
        result = alarm.arm()
    assert result is False
    assert alarm.state == CooldownState.DISARMED
    assert alarm.cold_start_skipped is True
    assert any("cold-start detected" in rec.message for rec in caplog.records)


def test_arm_warm_start_normal_path(tmp_path):
    """If cryostat is warm, arm() proceeds normally (subject to model availability)."""
    alarm, tracker, *_ = _make_alarm(model_dir=tmp_path)
    tracker.get.side_effect = lambda ch: _make_ch(ch, 250.0)
    # No model file — arm returns False, but for the right reason (no model)
    result = alarm.arm()
    assert result is False
    assert alarm.cold_start_skipped is False  # different failure mode


def test_cold_start_flag_clears_on_phase_entry_into_cooldown():
    alarm, *_ = _make_alarm()
    alarm._cold_start_skipped = True
    alarm.notify_phase_change("cooldown")
    assert alarm.cold_start_skipped is False


def test_cold_start_property_reflects_internal_flag():
    alarm, *_ = _make_alarm()
    assert alarm.cold_start_skipped is False
    alarm._cold_start_skipped = True
    assert alarm.cold_start_skipped is True
