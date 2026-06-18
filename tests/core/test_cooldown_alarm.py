"""Tests for CooldownAlarm state machine — Phase B of F-X v3."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.core.channel_state import ChannelState
from cryodaq.core.cooldown_alarm import CooldownAlarm, CooldownState

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_ch(ch: str, value: float, stale: bool = False) -> ChannelState:
    return ChannelState(
        channel=ch, value=value, timestamp=time.time(),
        unit="K", instrument_id="test", is_stale=stale,
    )


def _make_alarm(model_dir: Path | None = None, cfg_overrides: dict | None = None):
    """Return (alarm, tracker, alarm_mgr, event_bus)."""
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

    alarm = CooldownAlarm(cfg, tracker, alarm_mgr, event_bus)
    return alarm, tracker, alarm_mgr, event_bus


def _fake_model(duration_mean: float = 72.0, duration_std: float = 8.0):
    """Minimal mock EnsembleModel for unit tests."""
    model = MagicMock()
    model.n_curves = 5
    model.duration_mean = duration_mean
    model.duration_std = duration_std
    model._p_of_t_mean = lambda t: min(1.0, t / duration_mean)
    return model


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


def test_default_state_disarmed():
    alarm, *_ = _make_alarm()
    assert alarm.state == CooldownState.DISARMED


def test_arm_with_missing_model_returns_false(tmp_path):
    """Model file absent → arm() returns False, stays DISARMED."""
    alarm, *_ = _make_alarm(model_dir=tmp_path)
    result = alarm.arm()
    assert result is False
    assert alarm.state == CooldownState.DISARMED


def test_arm_with_model_returns_true(tmp_path):
    """Model present → arm() returns True, state ARMED."""
    alarm, *_ = _make_alarm(model_dir=tmp_path)
    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm.arm") as mock_arm:
        mock_arm.return_value = True
        # Directly set state to test the contract
        alarm._model = _fake_model()
        alarm._t_armed = time.monotonic()
        alarm._state = CooldownState.ARMED
    assert alarm.state == CooldownState.ARMED


@pytest.mark.asyncio
async def test_armed_before_rate_min_stays_armed():
    """Tick before RATE_MIN_HISTORY_H elapsed → state stays ARMED."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic()  # just armed
    alarm._state = CooldownState.ARMED

    tracker.get.side_effect = lambda ch: _make_ch(ch, 50.0 if "Т11" in ch else 200.0)
    await alarm.tick()
    assert alarm.state == CooldownState.ARMED


@pytest.mark.asyncio
async def test_watching_after_rate_min_elapsed():
    """After RATE_MIN_HISTORY_H elapsed → WATCHING."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 2000.0  # 0.55h ago
    alarm._state = CooldownState.ARMED

    from cryodaq.analytics.cooldown_predictor import PredictionResult
    fake_pred = MagicMock(spec=PredictionResult)
    fake_pred.progress = 0.3
    fake_pred.t_remaining_hours = 50.0

    tracker.get.side_effect = lambda ch: _make_ch(ch, 50.0 if "Т11" in ch else 200.0)
    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
        with patch("cryodaq.analytics.cooldown_predictor.predict", return_value=fake_pred):
            await alarm.tick()
    assert alarm.state == CooldownState.WATCHING


@pytest.mark.asyncio
async def test_on_track_no_fire():
    """On-track cooldown (actual ≈ expected progress) → no alarm, WATCHING."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model(duration_mean=72.0, duration_std=8.0)
    alarm._t_armed = time.monotonic() - 36 * 3600  # 36h ago (half of 72h)
    alarm._state = CooldownState.WATCHING

    from cryodaq.analytics.cooldown_predictor import PredictionResult
    fake_pred = MagicMock(spec=PredictionResult)
    fake_pred.progress = 0.50   # exactly on track at t=36h
    fake_pred.t_remaining_hours = 36.0

    tracker.get.side_effect = lambda ch: _make_ch(ch, 50.0 if "Т11" in ch else 200.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict", return_value=fake_pred):
        for _ in range(3):
            await alarm.tick()

    assert alarm.state == CooldownState.WATCHING
    event = alarm_mgr.process.call_args[0][1]
    assert event is None


@pytest.mark.asyncio
async def test_plateau_fires_after_sustained():
    """Sustained deviation → FIRED after sustained_min ticks."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"sustained_min": 2})
    alarm._model = _fake_model(duration_mean=72.0, duration_std=4.0)
    alarm._t_armed = time.monotonic() - 36 * 3600  # 36h elapsed
    alarm._state = CooldownState.WATCHING

    from cryodaq.analytics.cooldown_predictor import PredictionResult
    fake_pred = MagicMock(spec=PredictionResult)
    # Expected at 36h: p≈0.5. Actual: 0.1 (stuck at 70K) → big deviation
    fake_pred.progress = 0.10
    fake_pred.t_remaining_hours = 200.0

    tracker.get.side_effect = lambda ch: _make_ch(ch, 70.0 if "Т11" in ch else 200.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict", return_value=fake_pred):
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            for _ in range(3):
                await alarm.tick()

    assert alarm.state == CooldownState.FIRED
    event = alarm_mgr.process.call_args[0][1]
    assert event is not None
    assert "детектор" not in event.message.lower()


@pytest.mark.asyncio
async def test_fired_recovery_returns_to_watching():
    """After plateau, cooldown resumes → FIRED → WATCHING."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"sustained_min": 1})
    alarm._model = _fake_model(duration_mean=72.0, duration_std=4.0)
    alarm._t_armed = time.monotonic() - 36 * 3600
    alarm._state = CooldownState.FIRED
    alarm._sustained_count = 5

    from cryodaq.analytics.cooldown_predictor import PredictionResult
    fake_pred = MagicMock(spec=PredictionResult)
    fake_pred.progress = 0.49  # back on track
    fake_pred.t_remaining_hours = 37.0

    tracker.get.side_effect = lambda ch: _make_ch(ch, 50.0 if "Т11" in ch else 200.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict", return_value=fake_pred):
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            await alarm.tick()

    assert alarm.state == CooldownState.WATCHING


@pytest.mark.asyncio
async def test_auto_disarm_on_high_progress():
    """Progress >= 0.95 → AUTO_DISARMED → WATCHDOG (watchdog_enabled=True)."""
    # v0.55.4 A3: watchdog_enabled default flipped to False; this test
    # specifically exercises the watchdog path so opts in explicitly.
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"watchdog_enabled": True})
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING
    alarm._current_progress = 0.96  # already at 96%

    from cryodaq.analytics.cooldown_predictor import PredictionResult
    fake_pred = MagicMock(spec=PredictionResult)
    fake_pred.progress = 0.97
    fake_pred.t_remaining_hours = 1.0

    tracker.get.side_effect = lambda ch: _make_ch(ch, 4.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict", return_value=fake_pred):
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            await alarm.tick()

    # AUTO_DISARMED is momentary — with watchdog_enabled (default), final state is WATCHDOG
    assert alarm.state == CooldownState.WATCHDOG


@pytest.mark.asyncio
async def test_auto_disarm_on_base_temp():
    """T_cold <= base_temp_K → AUTO_DISARMED → WATCHDOG (watchdog_enabled=True)."""
    # v0.55.4 A3: watchdog_enabled default flipped to False; opt in
    # explicitly to exercise the watchdog path.
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"watchdog_enabled": True})
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING

    tracker.get.side_effect = lambda ch: _make_ch(ch, 4.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict") as mock_pred:
        mock_pred.return_value = MagicMock(progress=0.92, t_remaining_hours=2.0)
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            await alarm.tick()

    assert alarm.state == CooldownState.WATCHDOG


def test_disarm_while_watching_clears_alarm():
    """arm() then disarm() → DISARMED, sustained_count reset."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic()
    alarm._state = CooldownState.WATCHING
    alarm._sustained_count = 3

    alarm.disarm()
    assert alarm.state == CooldownState.DISARMED
    assert alarm._sustained_count == 0
    # disarm() clears both alarm IDs
    alarm_mgr.process.assert_any_call("cooldown_alarm", None, {})
    alarm_mgr.process.assert_any_call("cooldown_watchdog", None, {})


@pytest.mark.asyncio
async def test_cold_channel_stale_skips_tick():
    """Stale T_cold reading → tick skipped, no state change."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 2000
    alarm._state = CooldownState.WATCHING

    tracker.get.side_effect = lambda ch: _make_ch(ch, 50.0, stale=True)
    await alarm.tick()
    alarm_mgr.process.assert_not_called()
    assert alarm.state == CooldownState.WATCHING


# ---------------------------------------------------------------------------
# WATCHDOG tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_disarmed_enters_watchdog_when_enabled():
    """AUTO_DISARMED → WATCHDOG when watchdog_enabled=True (opt-in v0.55.4)."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"watchdog_enabled": True})
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING

    tracker.get.side_effect = lambda ch: _make_ch(ch, 4.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict") as mock_pred:
        mock_pred.return_value = MagicMock(progress=0.92, t_remaining_hours=2.0)
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            await alarm.tick()

    assert alarm.state == CooldownState.WATCHDOG


@pytest.mark.asyncio
async def test_auto_disarmed_stays_terminal_when_watchdog_disabled():
    """AUTO_DISARMED stays terminal when watchdog_enabled=False — verify second tick doesn't escape."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={"watchdog_enabled": False})
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING

    tracker.get.side_effect = lambda ch: _make_ch(ch, 4.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict") as mock_pred:
        mock_pred.return_value = MagicMock(progress=0.92, t_remaining_hours=2.0)
        with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
            await alarm.tick()          # WATCHING → AUTO_DISARMED

    assert alarm.state == CooldownState.AUTO_DISARMED

    # Second tick must not escape AUTO_DISARMED (early-return path)
    alarm_mgr.reset_mock()
    await alarm.tick()
    assert alarm.state == CooldownState.AUTO_DISARMED
    alarm_mgr.process.assert_not_called()  # no alarm IDs touched


@pytest.mark.asyncio
async def test_watchdog_t_cold_in_range_does_not_fire():
    """WATCHDOG + T_cold below threshold → no alarm fired."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={
        "watchdog_enabled": True,
        "watchdog_margin_K": 1.0,
        "watchdog_sustained_s": 90,
    })
    alarm._state = CooldownState.WATCHDOG
    alarm._watchdog_sustained_count = 0

    # T_cold = 5.5 K, threshold = 5.0 + 1.0 = 6.0 K → in range
    tracker.get.side_effect = lambda ch: _make_ch(ch, 5.5)

    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
        await alarm.tick()

    # process called with event=None (no alarm)
    alarm_mgr.process.assert_called_once_with("cooldown_watchdog", None, {"sustained_s": None, "hysteresis": None})
    assert alarm.state == CooldownState.WATCHDOG


@pytest.mark.asyncio
async def test_watchdog_sustained_over_threshold_fires():
    """WATCHDOG + T_cold sustained above threshold for sustained_min ticks → WATCHDOG_FIRED."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={
        "watchdog_enabled": True,
        "watchdog_margin_K": 1.0,
        "watchdog_sustained_s": 90,
    })
    alarm._state = CooldownState.WATCHDOG

    # T_cold = 7.0 K > 6.0 K threshold
    tracker.get.side_effect = lambda ch: _make_ch(ch, 7.0)

    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
        for _ in range(3):
            await alarm.tick()

    assert alarm.state == CooldownState.WATCHDOG_FIRED
    # Last call should have fired an AlarmEvent
    last_call = alarm_mgr.process.call_args_list[-1]
    assert last_call[0][0] == "cooldown_watchdog"
    assert last_call[0][1] is not None  # AlarmEvent, not None


@pytest.mark.asyncio
async def test_watchdog_fired_clears_when_t_cold_recovers():
    """WATCHDOG_FIRED + T_cold returns below threshold → WATCHDOG (alarm cleared)."""
    alarm, tracker, alarm_mgr, _ = _make_alarm(cfg_overrides={
        "watchdog_enabled": True,
        "watchdog_margin_K": 1.0,
        "watchdog_sustained_s": 90,
    })
    alarm._state = CooldownState.WATCHDOG_FIRED
    alarm._watchdog_sustained_count = 3

    # T_cold drops back below threshold
    tracker.get.side_effect = lambda ch: _make_ch(ch, 5.0)

    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
        await alarm.tick()

    assert alarm.state == CooldownState.WATCHDOG
    # process called with event=None (clear)
    alarm_mgr.process.assert_called_once_with("cooldown_watchdog", None, {"sustained_s": None, "hysteresis": None})


@pytest.mark.asyncio
async def test_watchdog_experiment_finalized_disarms():
    """notify_experiment_finalized() while in WATCHDOG → DISARMED on next tick."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._state = CooldownState.WATCHDOG

    alarm.notify_experiment_finalized()

    with patch("cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event", new_callable=AsyncMock):
        await alarm.tick()

    assert alarm.state == CooldownState.DISARMED


def test_watchdog_disarm_resets_to_disarmed():
    """disarm() from WATCHDOG state → DISARMED, both alarm IDs cleared."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._state = CooldownState.WATCHDOG
    alarm._watchdog_sustained_count = 2

    alarm.disarm()

    assert alarm.state == CooldownState.DISARMED
    assert alarm._watchdog_sustained_count == 0
    alarm_mgr.process.assert_any_call("cooldown_alarm", None, {})
    alarm_mgr.process.assert_any_call("cooldown_watchdog", None, {})


@pytest.mark.asyncio
async def test_arm_from_watchdog_resets_cleanly():
    """arm() from WATCHDOG state → ARMED, watchdog alarm cleared, model reloaded if needed."""
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._state = CooldownState.WATCHDOG
    alarm._watchdog_sustained_count = 5
    alarm._model = _fake_model()  # model already loaded

    result = alarm.arm()

    assert result is True
    assert alarm.state == CooldownState.ARMED
    assert alarm._watchdog_sustained_count == 0
    alarm_mgr.process.assert_called_with("cooldown_watchdog", None, {})


@pytest.mark.asyncio
async def test_finalize_disarms_any_active_state():
    """notify_experiment_finalized() from ARMED/WATCHING/FIRED also disarms (not only WATCHDOG)."""
    for initial_state in (CooldownState.ARMED, CooldownState.WATCHING, CooldownState.FIRED):
        alarm, tracker, alarm_mgr, _ = _make_alarm()
        alarm._model = _fake_model()
        alarm._t_armed = time.monotonic()
        alarm._state = initial_state

        alarm.notify_experiment_finalized()
        await alarm.tick()

        assert alarm.state == CooldownState.DISARMED, (
            f"Expected DISARMED after finalize from {initial_state.name}, "
            f"got {alarm.state.name}"
        )


# ---------------------------------------------------------------------------
# v0.55.4 — auto-arm + quasi-steady gate + watchdog default flip
# ---------------------------------------------------------------------------


def test_auto_arm_default_enabled():
    """v0.55.4 A1: auto_arm defaults to True so the engine wires up
    auto-arm on cooldown phase entry without operator config.
    """
    alarm, _, _, _ = _make_alarm()
    assert alarm.is_auto_arm_enabled is True


def test_auto_arm_can_be_disabled_via_config():
    alarm, _, _, _ = _make_alarm(cfg_overrides={"auto_arm": False})
    assert alarm.is_auto_arm_enabled is False


def test_watchdog_disabled_by_default():
    """v0.55.4 A3: watchdog default flipped to False per architect rule.
    AUTO_DISARMED stays terminal — no automatic WATCHDOG escalation.
    """
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING

    tracker.get.side_effect = lambda ch: _make_ch(ch, 4.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict") as mock_pred:
        mock_pred.return_value = MagicMock(progress=0.92, t_remaining_hours=2.0)
        with patch(
            "cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event",
            new_callable=AsyncMock,
        ):
            asyncio.run(alarm.tick())
    assert alarm.state == CooldownState.AUTO_DISARMED


@pytest.mark.asyncio
async def test_quasi_steady_skips_deviation_check():
    """v0.55.4 A2: when SteadyStatePredictor reports the cold channel
    is_quasi_steady=True, the deviation evaluation must short-circuit
    so gas-desorption drift doesn't masquerade as trajectory divergence.
    """
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.WATCHING
    alarm._sustained_count = 1

    quasi_pred = MagicMock(is_quasi_steady=True)
    ss_pred = MagicMock()
    ss_pred.get_prediction = MagicMock(return_value=quasi_pred)
    alarm.set_steady_state_predictor(ss_pred)

    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.5 if "Т12" in ch else 80.0)
    with patch("cryodaq.analytics.cooldown_predictor.predict") as mock_pred:
        mock_pred.return_value = MagicMock(progress=0.5, t_remaining_hours=10.0)
        with patch(
            "cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event",
            new_callable=AsyncMock,
        ):
            await alarm.tick()

    # Deviation check skipped — predictor never invoked, sustained reset.
    mock_pred.assert_not_called()
    assert alarm._sustained_count == 0
    assert alarm.state == CooldownState.WATCHING


@pytest.mark.asyncio
async def test_quasi_steady_clears_active_fired():
    """v0.55.4 A2: a FIRED alarm transitions back to WATCHING and
    clears via the state manager once the cold channel reports
    is_quasi_steady=True.
    """
    alarm, tracker, alarm_mgr, _ = _make_alarm()
    alarm._model = _fake_model()
    alarm._t_armed = time.monotonic() - 70 * 3600
    alarm._state = CooldownState.FIRED
    alarm._sustained_count = 5

    quasi_pred = MagicMock(is_quasi_steady=True)
    ss_pred = MagicMock()
    ss_pred.get_prediction = MagicMock(return_value=quasi_pred)
    alarm.set_steady_state_predictor(ss_pred)

    tracker.get.side_effect = lambda ch: _make_ch(ch, 6.5 if "Т12" in ch else 80.0)
    with patch(
        "cryodaq.core.cooldown_alarm.CooldownAlarm._publish_state_event",
        new_callable=AsyncMock,
    ):
        await alarm.tick()

    assert alarm.state == CooldownState.WATCHING
    assert alarm._sustained_count == 0
    alarm_mgr.process.assert_any_call("cooldown_alarm", None, {})
