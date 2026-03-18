"""Tests for the Keithley 2604B dual-channel driver."""

from __future__ import annotations

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


async def test_mock_connect_disconnect() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    assert not driver.connected
    await driver.connect()
    assert driver.connected
    await driver.disconnect()
    assert not driver.connected


async def test_mock_returns_dual_channel_readings() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    readings = await driver.read_channels()
    assert len(readings) == 8
    assert {reading.channel.split("/")[1] for reading in readings} == {"smua", "smub"}
    for reading in readings:
        assert isinstance(reading, Reading)
        assert reading.status == ChannelStatus.OK
    await driver.disconnect()


async def test_start_both_channels_concurrently_in_mock() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.start_source("smub", 0.3, 20.0, 0.5)

    assert driver.any_active
    assert set(driver.active_channels) == {"smua", "smub"}

    values = {reading.channel: reading.value for reading in await driver.read_channels()}
    assert values["k2604/smua/power"] > 0.0
    assert values["k2604/smub/power"] > 0.0
    await driver.disconnect()


async def test_stop_is_channel_scoped() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.start_source("smub", 0.3, 20.0, 0.5)

    await driver.stop_source("smua")

    assert set(driver.active_channels) == {"smub"}
    values = {reading.channel: reading.value for reading in await driver.read_channels()}
    assert values["k2604/smua/power"] == 0.0
    assert values["k2604/smub/power"] > 0.0
    await driver.disconnect()


async def test_emergency_off_is_channel_scoped() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.start_source("smub", 0.3, 20.0, 0.5)

    await driver.emergency_off("smub")

    assert set(driver.active_channels) == {"smua"}
    values = {reading.channel: reading.value for reading in await driver.read_channels()}
    assert values["k2604/smua/power"] > 0.0
    assert values["k2604/smub/power"] == 0.0
    await driver.disconnect()


async def test_invalid_channel_is_rejected() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    with pytest.raises(ValueError, match="Invalid Keithley channel"):
        await driver.start_source("smuc", 0.5, 40.0, 1.0)
    await driver.disconnect()


async def test_start_same_channel_twice_is_rejected() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    with pytest.raises(RuntimeError, match="already active"):
        await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.disconnect()


async def test_keithley_read_source_off() -> None:
    """When source output is OFF, read_channels returns zeros without error."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    # Neither channel is active (source OFF) → should return zero V/I/P
    readings = await driver.read_channels()
    assert len(readings) == 8  # 4 per channel × 2 channels

    for reading in readings:
        assert reading.status == ChannelStatus.OK
        if "resistance" not in reading.channel:
            assert reading.value == 0.0, f"{reading.channel} should be 0 when OFF"

    await driver.disconnect()
