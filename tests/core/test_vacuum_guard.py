"""Tests for VacuumGuard state machine — Phase C of F-X v3."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.channel_state import ChannelState, ChannelStateTracker
from cryodaq.core.vacuum_guard import VacuumGuard, VacuumState
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_channel_state(value: float, is_stale: bool = False) -> ChannelState:
    return ChannelState(
        channel="test",
        value=value,
        timestamp=time.time(),
        unit="K",
        instrument_id="test",
        is_stale=is_stale,
    )


def _make_pressure_state(mbar: float, is_stale: bool = False) -> ChannelState:
    return ChannelState(
        channel="VSP63D_1/pressure",
        value=mbar,
        timestamp=time.time(),
        unit="mbar",
        instrument_id="thyracont",
        is_stale=is_stale,
    )


def _make_vg(
    cfg_overrides: dict | None = None,
) -> tuple[VacuumGuard, MagicMock, MagicMock, MagicMock]:
    """Return (guard, state_tracker, alarm_state_mgr, event_bus)."""
    cfg = {
        "pressure_channel": "VSP63D_1/pressure",
        "reference_temp_channel": "Т12",
        "arm_threshold_K": 260.0,
        "disarm_threshold_K": 270.0,
        "fire_pressure_mbar": 1.0e-2,
        "clear_pressure_mbar": 1.0e-3,
        "sustained_s": 0.0,  # instant firing for unit tests
        "severity": "CRITICAL",
    }
    if cfg_overrides:
        cfg.update(cfg_overrides)

    tracker = MagicMock()
    alarm_mgr = MagicMock()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    guard = VacuumGuard(cfg, tracker, alarm_mgr, event_bus)
    return guard, tracker, alarm_mgr, event_bus


async def _tick_arm(guard, tracker) -> None:
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()


async def _tick_fire(guard, tracker) -> None:
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()


async def _tick_recover(guard, tracker) -> None:
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-4)
    await guard.tick()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_default_state_disarmed():
    guard, *_ = _make_vg()
    assert guard.state == VacuumState.DISARMED


@pytest.mark.asyncio
async def test_warm_system_stays_disarmed():
    """T_ref = 280K (warm) → stays DISARMED regardless of pressure."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: _make_channel_state(280.0) if "Т12" in ch else _make_pressure_state(1.0)
    await guard.tick()
    assert guard.state == VacuumState.DISARMED
    alarm_mgr.process.assert_called_once()
    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is None  # no alarm


@pytest.mark.asyncio
async def test_cold_good_vacuum_arms():
    """T_ref = 250K, P = 1e-5 mbar → ARMED, no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    assert guard.state == VacuumState.ARMED
    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is None


@pytest.mark.asyncio
async def test_armed_high_pressure_fires():
    """ARMED + P = 5e-2 mbar (over threshold), sustained_s=0 → FIRED."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    # First tick: arm
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    assert guard.state == VacuumState.ARMED

    # Second tick: high pressure
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.FIRED
    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is not None
    assert event_arg.level == "CRITICAL"


@pytest.mark.asyncio
async def test_fired_pressure_recovers_below_clear():
    """FIRED + P = 5e-4 mbar (below clear_pressure_mbar=1e-3) → ARMED."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    # Arm
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    # Fire
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # Recover through deadband
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-4)
    await guard.tick()
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_fired_pressure_in_deadband_stays_fired():
    """FIRED + P = 5e-3 (between clear 1e-3 and fire 1e-2) → stays FIRED."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # P in deadband
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-3)
    await guard.tick()
    assert guard.state == VacuumState.FIRED


@pytest.mark.asyncio
async def test_fired_system_warmed_disarms():
    """FIRED + T_ref >= 270K → DISARMED (system back in safe regime)."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # System warms
    tracker.get.side_effect = lambda ch: _make_channel_state(280.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.DISARMED


@pytest.mark.asyncio
async def test_armed_transient_spike_no_fire():
    """ARMED + P spike for <sustained_s → no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg({"sustained_s": 30.0})
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()  # arm

    # Spike — but sustained_s=30 not elapsed
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.ARMED  # not FIRED yet


def _tracker_reading(channel: str, value: float, unit: str, *, status=ChannelStatus.OK) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="test",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


@pytest.mark.asyncio
async def test_unusable_pressure_does_not_reset_sustained_fire_window():
    """A NaN pressure sample must not erase evidence of sustained vacuum loss."""
    guard, _, _, _ = _make_vg({"sustained_s": 30.0})
    tracker = ChannelStateTracker()
    guard._state_tracker = tracker
    tracker.update(_tracker_reading("Т12", 250.0, "K"))
    tracker.update(_tracker_reading("VSP63D_1/pressure", 5e-2, "mbar"))
    await guard.tick()
    assert guard.state == VacuumState.ARMED
    guard._sustained_since = time.monotonic() - 31.0

    tracker.update(
        _tracker_reading(
            "VSP63D_1/pressure",
            math.nan,
            "mbar",
            status=ChannelStatus.SENSOR_ERROR,
        )
    )
    await guard.tick()
    tracker.update(_tracker_reading("VSP63D_1/pressure", 5e-2, "mbar"))
    await guard.tick()

    assert guard.state == VacuumState.FIRED


@pytest.mark.asyncio
async def test_unusable_reference_temperature_is_stale_not_quiet_disarmed_state():
    """NaN T_ref is exposed as stale while the guard declines to arm on unknown data."""
    guard, _, _, _ = _make_vg()
    tracker = ChannelStateTracker()
    guard._state_tracker = tracker
    tracker.update(_tracker_reading("Т12", math.nan, "K", status=ChannelStatus.SENSOR_ERROR))
    tracker.update(_tracker_reading("VSP63D_1/pressure", 1e-5, "mbar"))

    await guard.tick()

    ref_state = tracker.get("Т12")
    assert ref_state is not None and ref_state.is_stale
    assert guard.state == VacuumState.DISARMED


@pytest.mark.asyncio
async def test_pressure_channel_missing_stays_disarmed():
    """Pressure channel absent → DISARMED, WARNING, no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else None
    await guard.tick()
    assert guard.state == VacuumState.DISARMED
    alarm_mgr.process.assert_called_once()


@pytest.mark.asyncio
async def test_reference_temp_channel_missing_stays_disarmed():
    """T_ref channel absent → DISARMED, no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.return_value = None
    await guard.tick()
    assert guard.state == VacuumState.DISARMED


@pytest.mark.asyncio
async def test_alarm_message_contains_factual_data_only():
    """Alarm message must contain channel IDs + values, no banned words.

    The test drives guard into FIRED state (arm tick then fire tick with
    sustained_s=0), so the alarm event is guaranteed non-None.  Assertions
    are unconditional — a None event here means guard.tick() has a regression.
    """
    guard, tracker, alarm_mgr, _ = _make_vg()
    # Tick 1: arm (T=250K, good vacuum)
    tracker.get.side_effect = lambda ch: _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    await guard.tick()
    assert guard.state == VacuumState.ARMED, "pre-condition: guard must ARM before firing"

    # Tick 2: fire (T=245K, bad vacuum; sustained_s=0 → instant)
    tracker.get.side_effect = lambda ch: _make_channel_state(245.0) if "Т12" in ch else _make_pressure_state(5e-2)
    await guard.tick()
    assert guard.state == VacuumState.FIRED, "guard must reach FIRED state"

    event = alarm_mgr.process.call_args[0][1]
    assert event is not None, "alarm event must not be None when guard is FIRED"
    msg = event.message.lower()
    assert "детектор" not in msg
    assert event.level == "CRITICAL"
    # channels list must contain both the pressure and reference-temperature channels
    assert "VSP63D_1/pressure" in event.channels, f"pressure channel must be in event.channels; got {event.channels}"
    assert "Т12" in event.channels, f"reference temp channel must be in event.channels; got {event.channels}"
    # values dict must carry the exact numeric values fed in tick 2
    assert event.values.get("VSP63D_1/pressure") == pytest.approx(5e-2), (
        f"pressure value must be 5e-2 mbar; got {event.values}"
    )
    assert event.values.get("Т12") == pytest.approx(245.0), f"temp value must be 245.0 K; got {event.values}"
    # formatted values must appear in the alarm message
    assert "5" in event.message or "0.05" in event.message or "5e" in event.message.lower(), (
        f"pressure value must appear in alarm message; got {event.message!r}"
    )
    assert "245" in event.message, f"temperature value must appear in alarm message; got {event.message!r}"


# ---------------------------------------------------------------------------
# The guard annunciates. It has no authority over the source.
# ---------------------------------------------------------------------------


def test_the_guard_cannot_be_given_a_safety_manager():
    """The authority is gone from the signature, not merely unwired.

    It was previously an opt-in parameter, and the opt-in was not real: the
    guard never consulted `escalate_to_safety`, so the presence of the handle
    *was* the gate, and one keyword in engine.py was the whole distance between
    "annunciates" and "de-energises the source". Removing the parameter makes
    restoring that authority a TypeError.
    """

    import inspect

    assert "safety_manager" not in inspect.signature(VacuumGuard.__init__).parameters


@pytest.mark.asyncio
async def test_firing_while_cold_annunciates_and_touches_nothing_else():
    """A FIRED edge produces a CRITICAL alarm event and no source action.

    On 2026-09-03 this edge latched the SafetyManager for eleven hours, on a
    threshold every recorded cooldown on this stand would have crossed — and
    while it was latched, the cryocooler CRITICAL arrived and left as one INFO
    line. The alarm was right; the authority was not its to hold.
    """

    guard, tracker, alarm_mgr, _ = _make_vg()
    await _tick_arm(guard, tracker)
    await _tick_fire(guard, tracker)
    assert guard.state == VacuumState.FIRED

    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is not None
    assert event_arg.level == "CRITICAL"
    assert not hasattr(guard, "_safety_manager")


@pytest.mark.asyncio
async def test_recovery_and_retrip_still_move_the_state_machine():
    """Removing the escalation must not have disturbed the ARMED/FIRED edges."""

    guard, tracker, _, _ = _make_vg()
    await _tick_arm(guard, tracker)
    await _tick_fire(guard, tracker)
    await _tick_recover(guard, tracker)
    assert guard.state == VacuumState.ARMED
    await _tick_fire(guard, tracker)
    assert guard.state == VacuumState.FIRED


# ---------------------------------------------------------------------------
# Fractional-rise detection
#
# The level path reports that the temperature gate opened, not that anything
# happened: on 2026-09-03 the guard fired 31 s after arming, at 7.3e-2 mbar
# against a 1.0e-2 threshold, and every recorded cooldown on this stand crossed
# 260 K between 7.3e-2 and 9.8e-1 mbar. A vacuum loss is a RISE — and a
# fractional one, because +0.001 mbar/h is catastrophic at 1e-5 mbar and
# invisible at 5e-2.
# ---------------------------------------------------------------------------

_RISE_CFG = {
    "fire_pressure_mbar": 1.0,       # backstop only — far above normal
    "clear_pressure_mbar": 0.5,
    "fire_rise_pct_per_h": 50.0,
    "clear_rise_pct_per_h": 10.0,
    "rise_window_s": 600.0,
    "sustained_s": 0.0,
}


async def _feed(guard, tracker, series, *, t_ref: float = 250.0, start: float = 0.0, step_s: float = 60.0):
    """Feed (pressure) samples step_s apart on a controlled monotonic clock."""

    import cryodaq.core.vacuum_guard as vg_mod

    real = vg_mod.time.monotonic
    try:
        for i, p in enumerate(series):
            vg_mod.time.monotonic = lambda _t=start + i * step_s: _t
            tracker.get.side_effect = (
                lambda ch, _p=p, _t=t_ref: _make_channel_state(_t) if "Т12" in ch else _make_pressure_state(_p)
            )
            await guard.tick()
    finally:
        vg_mod.time.monotonic = real


@pytest.mark.asyncio
async def test_a_flat_bad_vacuum_does_not_fire():
    """5e-2 mbar and steady is this stand's normal cold vacuum, not an event.

    The whole 2026-09-03 cooldown ran here and the level path called it CRITICAL
    within 31 seconds of arming.
    """

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    await _feed(guard, tracker, [5.0e-2] * 12)
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_a_slow_drift_within_normal_does_not_fire():
    """Measured on this stand: normal fractional rise is at most ~+2.5 %/h."""

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    series = [5.0e-2 * (1.0 + 0.025 * (i * 60.0) / 3600.0) for i in range(12)]
    await _feed(guard, tracker, series)
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_a_sustained_fractional_rise_fires():
    """Doubling per hour is ~+69 %/h — far outside anything this stand does."""

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    series = [5.0e-2 * 2.0 ** ((i * 60.0) / 3600.0) for i in range(12)]
    await _feed(guard, tracker, series)
    assert guard.state == VacuumState.FIRED


@pytest.mark.asyncio
async def test_the_same_fractional_rise_fires_at_any_absolute_pressure():
    """Scale invariance: the point of a fractional threshold.

    An mbar/h threshold would be wrong by orders of magnitude at one end.
    """

    for p0 in (5.0e-2, 1.0e-5):
        guard, tracker, *_ = _make_vg(_RISE_CFG)
        series = [p0 * 2.0 ** ((i * 60.0) / 3600.0) for i in range(12)]
        await _feed(guard, tracker, series)
        assert guard.state == VacuumState.FIRED, f"failed at {p0:.0e} mbar"


@pytest.mark.asyncio
async def test_a_short_window_cannot_manufacture_a_rise():
    """Regression against a real analysis error.

    Measuring this stand's own history produced a spurious +71.5 %/h from a
    single 0.00016 mbar quantization step whose window had collapsed to seconds
    across a database rollover. A slope needs a baseline in TIME.
    """

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    # A big jump, but sampled a second apart — no real span.
    await _feed(guard, tracker, [5.0e-2, 6.0e-2, 8.0e-2, 1.2e-1], step_s=1.0)
    assert guard.state == VacuumState.ARMED, "no time span, no rate, no alarm"


@pytest.mark.asyncio
async def test_the_rise_path_is_off_unless_configured():
    """Existing deployments keep the level path alone until an operator opts in."""

    guard, tracker, *_ = _make_vg()  # no fire_rise_pct_per_h
    series = [1.0e-5 * 2.0 ** ((i * 60.0) / 3600.0) for i in range(12)]
    await _feed(guard, tracker, series)
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_recovery_needs_the_rise_to_stop():
    """Fired on a rise, cleared when the rise stops — not when a level is met."""

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    await _feed(guard, tracker, [5.0e-2 * 2.0 ** ((i * 60.0) / 3600.0) for i in range(12)])
    assert guard.state == VacuumState.FIRED

    steady = guard._pressure_history[-1][1]
    await _feed(guard, tracker, [steady] * 12, start=10_000.0)
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_the_absolute_backstop_still_fires():
    """A level this bad while cold is an emergency however it got there."""

    guard, tracker, *_ = _make_vg(_RISE_CFG)
    await _feed(guard, tracker, [2.0] * 4)
    assert guard.state == VacuumState.FIRED
