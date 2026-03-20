"""Tests for the LakeShore 218S temperature monitor driver."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.analytics.calibration import CalibrationSample, CalibrationStore
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


_MOCK_IDN = "LSCI,MODEL218S,MOCK001,010101"


def _make_mock_transport(response: str) -> MagicMock:
    """Return a GPIBTransport mock whose query() returns *response*.

    connect() no longer sends *IDN?, so query() is only called for data reads.
    """
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
    transport.query = AsyncMock(side_effect=[RAW_RESPONSE])

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
        side_effect=[NORMAL_RESPONSE, RAW_RESPONSE]
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
        side_effect=[asyncio.TimeoutError],
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


def _calibration_samples(sensor_channel: str) -> list[CalibrationSample]:
    values = [82.98, 80.17, 60.0, 45.0, 30.0, 18.0, 10.0]
    return [
        CalibrationSample(
            timestamp=datetime(2026, 3, 16, 12, index, tzinfo=timezone.utc),
            reference_channel="CH1",
            reference_temperature=1500.0 / (raw_value + 18.0),
            sensor_channel=sensor_channel,
            sensor_raw_value=raw_value,
        )
        for index, raw_value in enumerate(values)
    ]


async def test_runtime_calibration_global_off_uses_krdg(tmp_path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve("ls218s:CH1", _calibration_samples("CH1"), raw_unit="sensor_unit", min_points_per_zone=3, target_rmse_k=0.2)
    store.save_curve(curve)
    store.assign_curve(sensor_id="ls218s:CH1", channel_key="ls218s:CH1", runtime_apply_ready=True)
    store.set_runtime_global_mode("off")

    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=[NORMAL_RESPONSE])

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False, calibration_store=store)
    driver._transport = transport
    await driver.connect()
    readings = await driver.read_channels()

    assert readings[0].value == pytest.approx(4.235)
    assert readings[0].metadata["reading_mode"] == "krdg"
    assert readings[0].metadata["raw_source"] == "KRDG"


async def test_runtime_calibration_global_on_uses_curve_and_preserves_metadata(tmp_path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve("ls218s:CH1", _calibration_samples("CH1"), raw_unit="sensor_unit", min_points_per_zone=3, target_rmse_k=0.2)
    store.save_curve(curve)
    store.assign_curve(
        sensor_id="ls218s:CH1",
        channel_key="ls218s:CH1",
        runtime_apply_ready=True,
        reading_mode_policy="on",
    )
    store.set_runtime_global_mode("on")

    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=[NORMAL_RESPONSE, RAW_RESPONSE])

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False, calibration_store=store)
    driver._transport = transport
    await driver.connect()
    readings = await driver.read_channels()

    assert readings[0].metadata["reading_mode"] == "curve"
    assert readings[0].metadata["raw_source"] == "SRDG"
    assert readings[0].metadata["curve_id"] == curve.curve_id
    assert readings[0].metadata["sensor_id"] == "ls218s:CH1"
    assert readings[0].unit == "K"
    assert readings[0].raw == pytest.approx(82.98)


async def test_runtime_calibration_hybrid_mode_uses_curve_only_for_enabled_channels(tmp_path) -> None:
    store = CalibrationStore(tmp_path)
    curve_ch1 = store.fit_curve("ls218s:CH1", _calibration_samples("CH1"), raw_unit="sensor_unit", min_points_per_zone=3, target_rmse_k=0.2)
    curve_ch2 = store.fit_curve("ls218s:CH2", _calibration_samples("CH2"), raw_unit="sensor_unit", min_points_per_zone=3, target_rmse_k=0.2)
    store.save_curve(curve_ch1)
    store.save_curve(curve_ch2)
    store.assign_curve(sensor_id="ls218s:CH1", channel_key="ls218s:CH1", runtime_apply_ready=True, reading_mode_policy="on")
    store.assign_curve(sensor_id="ls218s:CH2", channel_key="ls218s:CH2", runtime_apply_ready=True, reading_mode_policy="off")
    store.set_runtime_global_mode("on")

    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=[NORMAL_RESPONSE, RAW_RESPONSE])

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False, calibration_store=store)
    driver._transport = transport
    await driver.connect()
    readings = await driver.read_channels()

    assert readings[0].metadata["reading_mode"] == "curve"
    assert readings[1].metadata["reading_mode"] == "krdg"
    assert readings[1].metadata["raw_source"] == "KRDG"


# ---------------------------------------------------------------------------
# Per-channel fallback when KRDG? returns < 8 values
# ---------------------------------------------------------------------------

async def test_krdg_fallback_to_per_channel() -> None:
    """If KRDG? returns < 8 values, fall back to KRDG? 1..8."""
    all_values = ["+004.235E+0", "+004.891E+0", "+004.100E+0", "+003.998E+0",
                  "+004.567E+0", "+004.123E+0", "+003.876E+0", "+004.321E+0"]

    async def _query_handler(cmd, timeout_ms=None):
        if cmd == "KRDG?":
            return "+004.235E+0"  # Only 1 value — triggers fallback
        if cmd.startswith("KRDG? "):
            ch = int(cmd.split()[-1]) - 1
            return all_values[ch]
        return ""

    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=_query_handler)

    driver = LakeShore218S("ls218s", "GPIB0::11::INSTR", mock=False)
    driver._transport = transport
    await driver.connect()

    readings = await driver._read_krdg_channels()

    assert len(readings) == 8, f"Expected 8 readings from fallback, got {len(readings)}"
    for r in readings:
        assert r.unit == "K"
        assert r.status == ChannelStatus.OK


async def test_krdg_sticky_fallback() -> None:
    """After 3 short responses, driver switches to per-channel mode permanently."""
    transport = _make_mock_transport(NORMAL_RESPONSE)
    driver = LakeShore218S("ls218s", "GPIB0::11::INSTR", mock=False)
    driver._transport = transport
    await driver.connect()

    bulk_call_count = 0
    original_side_effect = transport.query.side_effect

    async def _patched_query(cmd, timeout_ms=None):
        nonlocal bulk_call_count
        if cmd == "KRDG?":
            bulk_call_count += 1
            return "+004.235E+0"  # Always short → triggers fallback
        if cmd.startswith("KRDG? "):
            ch = int(cmd.split()[-1]) - 1
            return ["+004.235E+0", "+004.891E+0", "+004.100E+0", "+003.998E+0",
                    "+004.567E+0", "+004.123E+0", "+003.876E+0", "+004.321E+0"][ch]
        return ""

    transport.query = AsyncMock(side_effect=_patched_query)

    # 3 calls to trigger sticky mode
    for _ in range(3):
        readings = await driver._read_krdg_channels()
        assert len(readings) == 8

    assert driver._use_per_channel_krdg is True
    assert bulk_call_count == 3  # KRDG? tried 3 times

    # 4th call should skip KRDG? entirely
    bulk_call_count = 0
    readings = await driver._read_krdg_channels()
    assert len(readings) == 8
    assert bulk_call_count == 0  # KRDG? NOT called — went straight to per-channel


async def test_krdg_no_argument_in_query() -> None:
    """Verify the driver sends KRDG? (no argument), not KRDG? 0."""
    queries_sent: list[str] = []

    async def _tracking_query(cmd, timeout_ms=None):
        queries_sent.append(cmd)
        return NORMAL_RESPONSE

    transport = MagicMock()
    transport.open = AsyncMock()
    transport.close = AsyncMock()
    transport.query = AsyncMock(side_effect=_tracking_query)

    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    driver._transport = transport
    await driver.connect()

    await driver._read_krdg_channels()

    assert "KRDG?" in queries_sent
    assert "KRDG? 0" not in queries_sent


# ---------------------------------------------------------------------------
# RDGST? periodic health check (read_status)
# ---------------------------------------------------------------------------


async def test_read_status_mock_returns_all_zero() -> None:
    """In mock mode, read_status returns {1:0, ..., 8:0}."""
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=True)
    await driver.connect()
    status = await driver.read_status()
    assert len(status) == 8
    for ch in range(1, 9):
        assert status[ch] == 0
    await driver.disconnect()


async def test_read_status_not_connected_raises() -> None:
    """read_status raises RuntimeError when not connected."""
    driver = LakeShore218S("ls218s", "GPIB0::12::INSTR", mock=False)
    with pytest.raises(RuntimeError, match="not connected"):
        await driver.read_status()
