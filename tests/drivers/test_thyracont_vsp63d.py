"""Tests for the Thyracont VSP63D vacuum gauge driver."""

from __future__ import annotations

import math

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D, _FALLBACK_BAUDRATES


# ---------------------------------------------------------------------------
# 1. connect / disconnect lifecycle in mock mode
# ---------------------------------------------------------------------------

async def test_mock_connect_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    assert not driver.connected

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 2. Mock mode returns 1 pressure reading
# ---------------------------------------------------------------------------

async def test_mock_returns_pressure() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()

    assert len(readings) == 1
    r = readings[0]
    assert isinstance(r, Reading)
    assert r.unit == "mbar"
    assert r.status == ChannelStatus.OK
    assert r.channel == "vsp63d/pressure"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 3. Mock pressure is in realistic range
# ---------------------------------------------------------------------------

async def test_mock_pressure_range() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    value = readings[0].value

    # Base ~1.5e-6, with noise ±20% and small drift
    assert 1e-8 < value < 1e-4, f"Mock pressure {value} mbar out of range"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 4. Parse OK response
# ---------------------------------------------------------------------------

async def test_parse_ok_response() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("0,1.234E-06\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1.234e-6, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 5. Parse overrange response
# ---------------------------------------------------------------------------

async def test_parse_overrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("2,1.000E+03\r")

    assert reading.status == ChannelStatus.OVERRANGE
    assert math.isclose(reading.value, 1000.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 6. Parse underrange response
# ---------------------------------------------------------------------------

async def test_parse_underrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("1,0.000E+00\r")

    assert reading.status == ChannelStatus.UNDERRANGE
    assert reading.value == 0.0


# ---------------------------------------------------------------------------
# 7. Parse sensor error response
# ---------------------------------------------------------------------------

async def test_parse_sensor_error() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("3,0.000E+00\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR


# ---------------------------------------------------------------------------
# 8. Reconnect after disconnect
# ---------------------------------------------------------------------------

async def test_reconnect_after_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected

    await driver.connect()
    assert driver.connected

    readings = await driver.read_channels()
    assert len(readings) == 1

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 9. Parse Protocol V1 — vacuum: "001M260017N" → (2600/1000)*10^(17-20) = 2.6e-3 mbar
# ---------------------------------------------------------------------------

async def test_thyracont_parse_pressure() -> None:
    """Protocol V1: '001M260017N' → mantissa=2600, exp=17 → 2.6e-3 mbar.

    These hard-coded fixture strings predate Phase 2c F.2 (default flip
    of validate_checksum to True). They test the *parser*, not the
    checksum validator, so explicit opt-out is correct.
    """
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, baudrate=115200, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M260017N\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 2.6e-3, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 10. Parse Protocol V1 — atmosphere: "001M100023D" → (1000/1000)*10^(23-20) = 1000 mbar
# ---------------------------------------------------------------------------

async def test_thyracont_parse_high_pressure() -> None:
    """Protocol V1: '001M100023D' → mantissa=1000, exp=23 → 1000 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100023D\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1000.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 11. Parse Protocol V1 — "001M400016O" → (4000/1000)*10^(16-20) = 4.0e-4 mbar
# ---------------------------------------------------------------------------

async def test_parse_v1_response_very_high_pressure() -> None:
    """Protocol V1: '001M400016O' → mantissa=4000, exp=16 → 4.0e-4 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M400016O\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 4.0e-4, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 14. Parse Protocol V1 — good vacuum: "001M100014X" → (1000/1000)*10^(14-20) = 1e-6 mbar
# ---------------------------------------------------------------------------

async def test_parse_v1_good_vacuum() -> None:
    """Protocol V1: '001M100014X' → mantissa=1000, exp=14 → 1e-6 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100014X\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1e-6, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 12. Parse Protocol V1 — invalid response
# ---------------------------------------------------------------------------

async def test_parse_v1_response_invalid() -> None:
    """Protocol V1: garbage response → SENSOR_ERROR + NaN."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")

    reading = driver._parse_v1_response("GARBAGE\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


# ---------------------------------------------------------------------------
# 13. Connect via V1 protocol probe (mock transport)
# ---------------------------------------------------------------------------

async def test_thyracont_connect_v1() -> None:
    """connect() sends '001M^' and gets '001M100023D\\r' → connected via V1."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, baudrate=115200, address="001")

    await driver.connect()

    assert driver.connected
    assert driver._protocol_v1 is True
    assert driver._instrument_id == "Thyracont-V1@001"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 15. Fallback baudrate mapping
# ---------------------------------------------------------------------------

def test_fallback_baudrates_mapping() -> None:
    """Verify known fallback baudrate pairs."""
    assert _FALLBACK_BAUDRATES[9600] == 115200
    assert _FALLBACK_BAUDRATES[115200] == 9600
    assert _FALLBACK_BAUDRATES.get(19200) is None


# ---------------------------------------------------------------------------
# 16. Connect with fallback baudrate (mock)
# ---------------------------------------------------------------------------

async def test_connect_fallback_baudrate() -> None:
    """When primary baudrate is 9600 in mock mode, connection still succeeds."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=9600, mock=True)
    await driver.connect()
    assert driver.connected
    await driver.disconnect()


# ---------------------------------------------------------------------------
# 17. Connect preserves original baudrate on success
# ---------------------------------------------------------------------------

async def test_connect_preserves_original_baudrate_on_success() -> None:
    """When primary baudrate probe succeeds, no fallback is attempted."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=115200, mock=True)
    await driver.connect()
    assert driver.connected
    assert driver._protocol_v1 is True
    await driver.disconnect()
