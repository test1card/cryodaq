"""Tests for VacuumGuard state machine — Phase C of F-X v3."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.channel_state import ChannelState
from cryodaq.core.vacuum_guard import VacuumGuard, VacuumState

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


def _make_vg(cfg_overrides: dict | None = None) -> tuple[VacuumGuard, MagicMock, MagicMock, MagicMock]:
    """Return (guard, state_tracker, alarm_state_mgr, event_bus)."""
    cfg = {
        "pressure_channel": "VSP63D_1/pressure",
        "reference_temp_channel": "Т12",
        "arm_threshold_K": 260.0,
        "disarm_threshold_K": 270.0,
        "fire_pressure_mbar": 1.0e-2,
        "clear_pressure_mbar": 1.0e-3,
        "sustained_s": 0.0,   # instant firing for unit tests
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
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(280.0) if "Т12" in ch else _make_pressure_state(1.0)
    )
    await guard.tick()
    assert guard.state == VacuumState.DISARMED
    alarm_mgr.process.assert_called_once()
    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is None  # no alarm


@pytest.mark.asyncio
async def test_cold_good_vacuum_arms():
    """T_ref = 250K, P = 1e-5 mbar → ARMED, no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    assert guard.state == VacuumState.ARMED
    event_arg = alarm_mgr.process.call_args[0][1]
    assert event_arg is None


@pytest.mark.asyncio
async def test_armed_high_pressure_fires():
    """ARMED + P = 5e-2 mbar (over threshold), sustained_s=0 → FIRED."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    # First tick: arm
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    assert guard.state == VacuumState.ARMED

    # Second tick: high pressure
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
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
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    # Fire
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # Recover through deadband
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-4)
    )
    await guard.tick()
    assert guard.state == VacuumState.ARMED


@pytest.mark.asyncio
async def test_fired_pressure_in_deadband_stays_fired():
    """FIRED + P = 5e-3 (between clear 1e-3 and fire 1e-2) → stays FIRED."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # P in deadband
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-3)
    )
    await guard.tick()
    assert guard.state == VacuumState.FIRED


@pytest.mark.asyncio
async def test_fired_system_warmed_disarms():
    """FIRED + T_ref >= 270K → DISARMED (system back in safe regime)."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()
    assert guard.state == VacuumState.FIRED

    # System warms
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(280.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()
    assert guard.state == VacuumState.DISARMED


@pytest.mark.asyncio
async def test_armed_transient_spike_no_fire():
    """ARMED + P spike for <sustained_s → no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg({"sustained_s": 30.0})
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()  # arm

    # Spike — but sustained_s=30 not elapsed
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()
    assert guard.state == VacuumState.ARMED  # not FIRED yet


@pytest.mark.asyncio
async def test_pressure_channel_missing_stays_disarmed():
    """Pressure channel absent → DISARMED, WARNING, no fire."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else None
    )
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
    """Alarm message must contain channel IDs + values, no banned words."""
    guard, tracker, alarm_mgr, _ = _make_vg()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(250.0) if "Т12" in ch else _make_pressure_state(1e-5)
    )
    await guard.tick()
    tracker.get.side_effect = lambda ch: (
        _make_channel_state(245.0) if "Т12" in ch else _make_pressure_state(5e-2)
    )
    await guard.tick()

    event = alarm_mgr.process.call_args[0][1]
    if event is not None:
        msg = event.message.lower()
        assert "детектор" not in msg
        assert "VSP63D_1/pressure".lower() in event.message.lower() or "мбар" in event.message.lower()
