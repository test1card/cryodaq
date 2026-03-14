"""Tests for the Keithley 2604B source-measure unit driver."""

from __future__ import annotations

import asyncio

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


# ---------------------------------------------------------------------------
# 1. Mock connect/disconnect lifecycle
# ---------------------------------------------------------------------------

async def test_mock_connect_disconnect() -> None:
    driver = Keithley2604B("k2604", "USB0::0x05E6::0x2604::MOCK::INSTR", mock=True)
    assert not driver.connected

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 2. IDN verification in mock mode
# ---------------------------------------------------------------------------

async def test_mock_idn_contains_2604b() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    assert "2604B" in driver._instrument_id
    await driver.disconnect()


# ---------------------------------------------------------------------------
# 3. Mock returns 4 channels (V, I, R, P)
# ---------------------------------------------------------------------------

async def test_mock_returns_4_channels() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    assert len(readings) == 4

    channels = {r.channel.split("/")[-1] for r in readings}
    assert channels == {"voltage", "current", "resistance", "power"}

    for r in readings:
        assert isinstance(r, Reading)
        assert r.status == ChannelStatus.OK

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 4. Mock channel naming: "name/smua/voltage" etc
# ---------------------------------------------------------------------------

async def test_mock_channel_naming() -> None:
    driver = Keithley2604B("K1", "USB0::MOCK", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    for r in readings:
        assert r.channel.startswith("K1/smua/")
        # instrument_id is set by driver (may be driver name or mock ID)
        assert "instrument_id" in r.metadata

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 5. disconnect() calls emergency_off()
# ---------------------------------------------------------------------------

async def test_disconnect_calls_emergency_off() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    # Track emergency_off calls
    calls = []
    original = driver.emergency_off

    async def tracked_emergency_off():
        calls.append(True)
        await original()

    driver.emergency_off = tracked_emergency_off
    await driver.disconnect()
    assert len(calls) >= 1


# ---------------------------------------------------------------------------
# 6. emergency_off() never raises
# ---------------------------------------------------------------------------

async def test_emergency_off_never_raises() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    # Should not raise even when called multiple times
    await driver.emergency_off()
    await driver.emergency_off()
    assert True  # If we got here, no exception

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 7. Mock mode produces realistic R(T) physics
# ---------------------------------------------------------------------------

async def test_mock_realistic_values() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    values = {r.channel.split("/")[-1]: r.value for r in readings}

    # Voltage and current should be non-negative
    assert values["voltage"] >= 0
    assert values["current"] >= 0
    # Resistance should be positive (unless zero current)
    assert values["resistance"] >= 0
    # Power should be non-negative
    assert values["power"] >= 0

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 8. Reconnect after disconnect
# ---------------------------------------------------------------------------

async def test_reconnect_after_disconnect() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)

    await driver.connect()
    assert driver.connected
    await driver.disconnect()
    assert not driver.connected

    await driver.connect()
    assert driver.connected
    readings = await driver.read_channels()
    assert len(readings) == 4

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 9. Read without connect raises RuntimeError
# ---------------------------------------------------------------------------

async def test_read_without_connect_raises() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)

    with pytest.raises(RuntimeError):
        await driver.read_channels()


# ---------------------------------------------------------------------------
# 10. Disconnect is idempotent
# ---------------------------------------------------------------------------

async def test_disconnect_idempotent() -> None:
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    await driver.disconnect()
    await driver.disconnect()  # Second call should not raise
    assert not driver.connected
