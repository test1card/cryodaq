"""Tests for the ThermalCalculator analytics plugin."""

from __future__ import annotations

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from plugins.thermal_calculator import ThermalCalculator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOT_CH = "lakeshore/ch1"
COLD_CH = "lakeshore/ch2"
HEATER_CH = "keithley/power"


def _make_reading(channel: str, value: float, status: ChannelStatus = ChannelStatus.OK) -> Reading:
    return Reading.now(channel=channel, value=value, unit="K", instrument_id="test", status=status)


def _make_heater_reading(value: float, status: ChannelStatus = ChannelStatus.OK) -> Reading:
    return Reading.now(channel=HEATER_CH, value=value, unit="W", instrument_id="test", status=status)


def _configured_plugin() -> ThermalCalculator:
    plugin = ThermalCalculator()
    plugin.configure(
        {
            "hot_sensor": HOT_CH,
            "cold_sensor": COLD_CH,
            "heater_channel": HEATER_CH,
        }
    )
    return plugin


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_thermal_resistance_basic():
    """Known T_hot, T_cold, P should produce the expected R_thermal value."""
    plugin = _configured_plugin()

    T_hot = 30.0   # K
    T_cold = 10.0  # K
    P = 4.0        # W
    # Expected R = (30 - 10) / 4 = 5.0 K/W

    readings = [
        _make_reading(HOT_CH, T_hot),
        _make_reading(COLD_CH, T_cold),
        _make_heater_reading(P),
    ]
    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    assert metrics[0].metric == "R_thermal"
    assert metrics[0].unit == "K/W"
    assert metrics[0].value == pytest.approx(5.0)


async def test_zero_power_returns_empty():
    """P == 0 must produce no metric (division by zero guard)."""
    plugin = _configured_plugin()

    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(0.0),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_negative_power_returns_empty():
    """P < 0 must produce no metric."""
    plugin = _configured_plugin()

    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(-1.5),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_missing_channel_returns_empty():
    """Only 2 of 3 required channels present → no metric until all known."""
    plugin = _configured_plugin()

    # Only hot + cold, no heater
    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_partial_batch_accumulates():
    """First batch provides hot + cold; second batch provides power → computes."""
    plugin = _configured_plugin()

    # First batch: temperatures only
    batch1 = [
        _make_reading(HOT_CH, 40.0),
        _make_reading(COLD_CH, 20.0),
    ]
    metrics1 = await plugin.process(batch1)
    assert metrics1 == [], "should be empty without power reading"

    # Second batch: power only — plugin must use cached temperatures
    batch2 = [_make_heater_reading(10.0)]
    metrics2 = await plugin.process(batch2)

    assert len(metrics2) == 1
    # R = (40 - 20) / 10 = 2.0 K/W
    assert metrics2[0].value == pytest.approx(2.0)


async def test_only_ok_status_used():
    """Readings with SENSOR_ERROR status are ignored; only OK readings count."""
    plugin = _configured_plugin()

    # Good readings with OK status
    readings_ok = [
        _make_reading(HOT_CH, 50.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(8.0),
    ]
    await plugin.process(readings_ok)

    # Now send a batch where hot sensor has SENSOR_ERROR — cache must keep old value
    readings_err = [
        _make_reading(HOT_CH, 999.0, status=ChannelStatus.SENSOR_ERROR),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(8.0),
    ]
    metrics = await plugin.process(readings_err)

    # Plugin should still compute using cached T_hot = 50.0
    assert len(metrics) == 1
    assert metrics[0].value == pytest.approx((50.0 - 10.0) / 8.0)


async def test_metric_has_correct_metadata():
    """Returned DerivedMetric must carry T_hot, T_cold, and P in metadata."""
    plugin = _configured_plugin()

    T_hot = 25.0
    T_cold = 5.0
    P = 5.0

    readings = [
        _make_reading(HOT_CH, T_hot),
        _make_reading(COLD_CH, T_cold),
        _make_heater_reading(P),
    ]
    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    meta = metrics[0].metadata

    assert meta["hot_T"] == pytest.approx(T_hot)
    assert meta["cold_T"] == pytest.approx(T_cold)
    assert meta["P"] == pytest.approx(P)
