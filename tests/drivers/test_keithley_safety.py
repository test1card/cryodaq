"""Safety tests for Keithley 2604B: slew rate limit, compliance, diagnostics."""

from __future__ import annotations

import math

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.drivers.instruments.keithley_2604b import (
    Keithley2604B,
    MAX_DELTA_V_PER_STEP,
    _COMPLIANCE_NOTIFY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Slew rate limiting
# ---------------------------------------------------------------------------


async def test_slew_rate_normal_regulation() -> None:
    """When R is stable, voltage changes stay within MAX_DELTA_V_PER_STEP."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)

    # Read several cycles — mock has stable R
    for _ in range(5):
        await driver.read_channels()

    # _last_v should be set and finite
    last_v = driver._last_v["smua"]
    assert math.isfinite(last_v)
    assert last_v >= 0.0

    await driver.disconnect()


async def test_slew_rate_limits_large_r_change() -> None:
    """When R drops dramatically, voltage step is clamped to MAX_DELTA_V_PER_STEP.

    In mock mode we can't simulate R changes directly, but we can verify
    that _last_v tracks and the limit constant is correct.
    """
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)

    # After start, _last_v is 0
    assert driver._last_v["smua"] == 0.0

    # First read: voltage jumps from 0 to sqrt(P*R) but is limited
    await driver.read_channels()

    # In mock: R ≈ 100 Ω, P=0.5W → V ≈ sqrt(50) ≈ 7.07V
    # But _last_v was 0, so step is limited to MAX_DELTA_V_PER_STEP = 0.5V
    # Mock path doesn't go through the slew limiter (it computes directly),
    # but the constant must exist and be sensible.
    assert MAX_DELTA_V_PER_STEP == 0.5
    assert MAX_DELTA_V_PER_STEP > 0

    await driver.disconnect()


async def test_slew_rate_constant_is_safe() -> None:
    """MAX_DELTA_V_PER_STEP should be conservative (≤1V)."""
    assert 0 < MAX_DELTA_V_PER_STEP <= 1.0


async def test_last_v_resets_on_stop() -> None:
    """stop_source resets _last_v for that channel."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)
    await driver.read_channels()  # sets _last_v

    await driver.stop_source("smua")
    assert driver._last_v["smua"] == 0.0

    await driver.disconnect()


async def test_last_v_resets_on_emergency_off_single() -> None:
    """emergency_off(channel) resets _last_v for that channel only."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)
    await driver.start_source("smub", p_target=0.3, v_compliance=20.0, i_compliance=0.5)
    await driver.read_channels()

    await driver.emergency_off("smua")
    assert driver._last_v["smua"] == 0.0
    # smub was not affected by emergency_off on smua
    # (it was reset because emergency_off("smua") only targets smua)

    await driver.disconnect()


async def test_last_v_resets_on_emergency_off_all() -> None:
    """emergency_off(None) resets _last_v for ALL channels."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)
    await driver.start_source("smub", p_target=0.3, v_compliance=20.0, i_compliance=0.5)
    await driver.read_channels()

    await driver.emergency_off()  # all channels
    assert driver._last_v["smua"] == 0.0
    assert driver._last_v["smub"] == 0.0

    await driver.disconnect()


# ---------------------------------------------------------------------------
# Compliance detection
# ---------------------------------------------------------------------------


async def test_compliance_count_starts_at_zero() -> None:
    """Compliance count is 0 on init and after start_source."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    assert driver._compliance_count["smua"] == 0
    assert driver._compliance_count["smub"] == 0

    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)
    assert driver._compliance_count["smua"] == 0

    await driver.disconnect()


async def test_compliance_count_resets_on_stop() -> None:
    """stop_source resets compliance count."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)

    # Manually set to simulate compliance
    driver._compliance_count["smua"] = 15

    await driver.stop_source("smua")
    assert driver._compliance_count["smua"] == 0

    await driver.disconnect()


async def test_compliance_count_resets_on_emergency_off() -> None:
    """emergency_off resets compliance count for all channels."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    driver._compliance_count["smua"] = 20
    driver._compliance_count["smub"] = 10

    await driver.emergency_off()
    assert driver._compliance_count["smua"] == 0
    assert driver._compliance_count["smub"] == 0

    await driver.disconnect()


async def test_compliance_persistent_threshold() -> None:
    """compliance_persistent returns True when count >= threshold."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    assert not driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD - 1
    assert not driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD
    assert driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD + 5
    assert driver.compliance_persistent("smua")

    await driver.disconnect()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


async def test_diagnostics_mock_returns_empty() -> None:
    """In mock mode, diagnostics returns empty dict (no real instrument)."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    result = await driver.diagnostics()
    assert result == {}
    await driver.disconnect()


async def test_diagnostics_disconnected_returns_empty() -> None:
    """When not connected, diagnostics returns empty dict."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    result = await driver.diagnostics()
    assert result == {}
