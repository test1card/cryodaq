"""Tests for the LakeShore 218S temperature monitor driver."""

from __future__ import annotations

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NORMAL_RESPONSE = (
    "+004.235E+0,+004.891E+0,+004.100E+0,+003.998E+0,"
    "+004.567E+0,+004.123E+0,+003.876E+0,+004.321E+0"
)

EXPECTED_NORMAL_VALUES = [
    4.235, 4.891, 4.100, 3.998, 4.567, 4.123, 3.876, 4.321,
]

RAW_RESPONSE = (
    "+8.298000E+1,+8.017000E+1,+1.738000E+1,+1.728000E+1,"
    "+8.204000E+1,+8.332000E+1,+8.433000E+1,+5.114000E+0"
)


def _make_mock_transport(response: str) -> MagicMock:
    """Return a GPIBTransport mock whose query() returns *response*."""
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(return_value=response)
    return transport


# ---------------------------------------------------------------------------
# 1. connect / disconnect lifecycle in mock mode
# ---------------------------------------------------------------------------

async def test_mock_mode_connect_disconnect() -> None:
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)

    assert not driver.connected

    await driver.connect()
    assert driver.connected

    readings = await driver.read_channels()
    assert len(readings) == 8

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 2. Mock mode returns 8 valid cryogenic readings
# ---------------------------------------------------------------------------

async def test_mock_returns_8_channels() -> None:
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)
    await driver.connect()

    readings = await driver.read_channels()

    assert len(readings) == 8
    for r in readings:
        assert isinstance(r, Reading)
        assert r.unit == "K"
        assert r.status == ChannelStatus.OK
        # Mock base temps range from 3.9 to 300 K, with ±0.5% noise
        assert 3.5 <= r.value <= 302.0, f"Temperature {r.value} K out of expected range"

    await driver.disconnect()


async def test_mock_returns_raw_sensor_channels() -> None:
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)
    await driver.connect()

    readings = await driver.read_srdg_channels()

    assert len(readings) == 8
    for reading in readings:
        assert reading.unit == "sensor_unit"
        assert reading.status == ChannelStatus.OK
        assert reading.metadata["reading_kind"] == "raw_sensor"
        assert reading.value > 0

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 3. Custom channel labels appear in Reading.channel
# ---------------------------------------------------------------------------

async def test_mock_channel_labels() -> None:
    labels = {1: "STAGE_A", 2: "STAGE_B", 3: "SHIELD", 4: "COLD_PLATE",
              5: "WARM_PLATE", 6: "FLANGE", 7: "AMBIENT", 8: "SPARE"}

    driver = LakeShore218S(
        "ls218s", "GPIB0::12::INSTR",
        channel_labels=labels,
        mock=True,
    )
    await driver.connect()

    readings = await driver.read_channels()

    assert len(readings) == 8
    reading_channels = {r.channel for r in readings}
    for label in labels.values():
        assert label in reading_channels, f"Label '{label}' missing from readings"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 4. Parse a normal 8-value KRDG response
# ---------------------------------------------------------------------------

async def test_parse_normal_response() -> None:
    transport = _make_mock_transport(NORMAL_RESPONSE)

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport  # inject mock transport before connect

    with patch.object(type(driver), "_transport", transport, create=True):
        driver._transport = transport
        # Connect via the patched transport (open() is mocked)
        await driver.connect()

        readings = await driver.read_channels()

    assert len(readings) == 8
    for reading, expected in zip(readings, EXPECTED_NORMAL_VALUES, strict=True):
        assert reading.unit == "K"
        assert reading.status == ChannelStatus.OK
        assert math.isclose(reading.value, expected, rel_tol=1e-4), (
            f"Expected {expected}, got {reading.value}"
        )


# ---------------------------------------------------------------------------
# 5. +OVL tokens produce OVERRANGE status and value=inf
# ---------------------------------------------------------------------------

async def test_parse_overrange() -> None:
    ovl_response = (
        "+OVL,+004.891E+0,+OVL,+003.998E+0,"
        "+004.567E+0,+004.123E+0,+003.876E+0,+004.321E+0"
    )
    transport = _make_mock_transport(ovl_response)

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport

    await driver.connect()
    readings = await driver.read_channels()

    assert len(readings) == 8

    # channels 1 and 3 (index 0 and 2) are OVL
    assert readings[0].status == ChannelStatus.OVERRANGE
    assert math.isinf(readings[0].value)

    assert readings[2].status == ChannelStatus.OVERRANGE
    assert math.isinf(readings[2].value)

    # the rest are normal
    for idx in (1, 3, 4, 5, 6, 7):
        assert readings[idx].status == ChannelStatus.OK
        assert math.isfinite(readings[idx].value)


async def test_parse_srdg_response() -> None:
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=["LSCI,MODEL218S,MOCK001,010101", RAW_RESPONSE])

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport

    await driver.connect()
    readings = await driver.read_srdg_channels()

    assert len(readings) == 8
    assert readings[0].unit == "sensor_unit"
    assert readings[0].metadata["reading_kind"] == "raw_sensor"
    assert readings[0].value == pytest.approx(82.98)


async def test_read_calibration_pair_resolves_channels() -> None:
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(
        side_effect=["LSCI,MODEL218S,MOCK001,010101", NORMAL_RESPONSE, RAW_RESPONSE]
    )
    driver = LakeShore218S(
        "ls218s",
        "GPIB0::12::INSTR",
        channel_labels={1: "REF", 2: "SENSOR"},
        mock=False,
    )
    driver._transport = transport

    await driver.connect()
    pair = await driver.read_calibration_pair(reference_channel="REF", sensor_channel="SENSOR")

    assert pair["reference"].unit == "K"
    assert pair["reference"].channel == "REF"
    assert pair["sensor"].unit == "sensor_unit"
    assert pair["sensor"].channel == "SENSOR"


# ---------------------------------------------------------------------------
# 6. Garbled tokens produce SENSOR_ERROR status
# ---------------------------------------------------------------------------

async def test_parse_garbled_response() -> None:
    garbled_response = (
        "GARBAGE,+004.891E+0,???,+003.998E+0,"
        "BAD,+004.123E+0,+003.876E+0,+004.321E+0"
    )
    transport = _make_mock_transport(garbled_response)

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport

    await driver.connect()
    readings = await driver.read_channels()

    assert len(readings) == 8

    bad_indices = (0, 2, 4)
    for idx in bad_indices:
        assert readings[idx].status == ChannelStatus.SENSOR_ERROR, (
            f"Channel at index {idx} should be SENSOR_ERROR, got {readings[idx].status}"
        )

    good_indices = (1, 3, 5, 6, 7)
    for idx in good_indices:
        assert readings[idx].status == ChannelStatus.OK


# ---------------------------------------------------------------------------
# 7. asyncio.TimeoutError from transport is handled gracefully
# ---------------------------------------------------------------------------

async def test_timeout_handling() -> None:
    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    # First call (IDN during connect) succeeds; read_channels query times out
    transport.query = AsyncMock(
        side_effect=["LSCI,MODEL218S,MOCK001,010101", asyncio.TimeoutError],
    )

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport

    await driver.connect()
    assert driver.connected

    # Driver must either raise a clearly typed exception OR return 8 TIMEOUT readings
    # — both are acceptable contracts; we just must not get an unhandled crash.
    try:
        readings = await driver.read_channels()
        # If it returns readings, they must all carry TIMEOUT status
        assert len(readings) == 8
        for r in readings:
            assert r.status == ChannelStatus.TIMEOUT, (
                f"Expected TIMEOUT status on timeout, got {r.status}"
            )
    except (asyncio.TimeoutError, TimeoutError, OSError, RuntimeError):
        # Raising a typed exception is also a valid design choice
        pass


# ---------------------------------------------------------------------------
# 8. Reconnect after disconnect works correctly
# ---------------------------------------------------------------------------

async def test_reconnect_after_disconnect() -> None:
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected

    # Second connect must succeed
    await driver.connect()
    assert driver.connected

    readings = await driver.read_channels()
    assert len(readings) == 8

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 11. Reading has instrument_id as first-class field
# ---------------------------------------------------------------------------

async def test_reading_has_instrument_id_field():
    from cryodaq.drivers.base import Reading
    r = Reading.now(channel="CH1", value=4.5, unit="K", instrument_id="LS218_1")
    assert r.instrument_id == "LS218_1"
