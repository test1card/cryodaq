"""F-MultiLine — Etalon MultiLine driver tests (Stage 1)."""

from __future__ import annotations

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.drivers.instruments.etalon_multiline import (
    MultiLineDriver,
    _parse_channeldata_response,
    _parse_environmentdata_response,
    _parse_isconnected_response,
    _parse_laserready_response,
)


def test_parse_channeldata_two_channels():
    response = (
        "channeldata_"
        "1,1234.5678,100,200,22.5,1013.25,45.0,0,0,0,0,0,0,0,0,0,0_"
        "2,1234.6789,150,250,22.5,1013.25,45.0,0,0,0,0,0,0,0,0,0,0_"
        "0"
    )
    channels, se = _parse_channeldata_response(response)
    assert len(channels) == 2
    assert channels[0].channel_number == 1
    assert channels[0].length_mm == pytest.approx(1234.5678)
    assert channels[1].length_mm == pytest.approx(1234.6789)
    assert se == 0


def test_parse_channeldata_with_beam_break():
    response = (
        "channeldata_"
        "1,1234.5678,100,200,22.5,1013.25,45.0,0,1,0,0,0,0,0,0,0,0_"
        "0"
    )
    channels, _ = _parse_channeldata_response(response)
    assert channels[0].beam_break == 1


def test_parse_channeldata_short_record_skipped(caplog):
    response = "channeldata_1,1234.5_0"  # 2 fields instead of 17
    channels, se = _parse_channeldata_response(response)
    assert channels == []
    assert se == 0


def test_parse_channeldata_garbage_raises():
    with pytest.raises(ValueError):
        _parse_channeldata_response("garbage")


def test_parse_environmentdata():
    t, p, h = _parse_environmentdata_response("environmentdata_22.5,1013.25,45.0")
    assert t == pytest.approx(22.5)
    assert p == pytest.approx(1013.25)
    assert h == pytest.approx(45.0)


def test_parse_environmentdata_short_raises():
    with pytest.raises(ValueError):
        _parse_environmentdata_response("environmentdata_22.5")


def test_parse_isconnected_true():
    assert _parse_isconnected_response("isconnected_1") is True


def test_parse_isconnected_false():
    assert _parse_isconnected_response("isconnected_0") is False


def test_parse_isconnected_garbage_raises():
    with pytest.raises(ValueError):
        _parse_isconnected_response("garbage")


def test_parse_laserready():
    assert _parse_laserready_response("laserready_1") is True
    assert _parse_laserready_response("laserready_0") is False


@pytest.mark.asyncio
async def test_mock_driver_returns_length_and_env_readings():
    driver = MultiLineDriver(
        "ML1", "localhost", channel_numbers=[1, 2], mock=True
    )
    await driver.connect()
    try:
        readings = await driver.read_channels()
    finally:
        await driver.disconnect()

    length = [r for r in readings if "/length_ch" in r.channel]
    env = [r for r in readings if "/env_" in r.channel]
    assert len(length) == 2
    assert len(env) == 3

    for r in length:
        assert r.unit == "mm"
        assert 900.0 < r.value < 1300.0  # near nominal
        assert r.instrument_id == "ML1"
        assert r.status == ChannelStatus.OK

    units = {r.channel.split("/", 1)[1]: r.unit for r in env}
    assert units == {
        "env_temperature": "°C",
        "env_pressure": "hPa",
        "env_humidity": "%",
    }


@pytest.mark.asyncio
async def test_mock_driver_idempotent_connect_and_disconnect():
    driver = MultiLineDriver("ML1", "localhost", mock=True)
    await driver.connect()
    await driver.connect()
    assert driver.connected
    await driver.disconnect()
    await driver.disconnect()
    assert not driver.connected


def test_status_from_errors_beam_break():
    from cryodaq.drivers.instruments.etalon_multiline import _ChannelData

    ch = _ChannelData(
        channel_number=1,
        length_mm=1.0,
        intensity_min=0,
        intensity_max=0,
        temperature_c=20.0,
        pressure_hpa=1013.0,
        humidity_pct=40.0,
        analysis_error=0,
        beam_break=1,
        temp_error=0,
        motion_tolerance_error=0,
        intensity_error=0,
        usb_error=0,
        dll_error=0,
        laser_speed_error=0,
        laser_temp_error=0,
        daq_error=0,
    )
    assert MultiLineDriver._status_from_errors(ch) == ChannelStatus.SENSOR_ERROR


def test_status_from_errors_clean():
    from cryodaq.drivers.instruments.etalon_multiline import _ChannelData

    ch = _ChannelData(
        channel_number=1,
        length_mm=1.0,
        intensity_min=0,
        intensity_max=0,
        temperature_c=20.0,
        pressure_hpa=1013.0,
        humidity_pct=40.0,
        analysis_error=0,
        beam_break=0,
        temp_error=0,
        motion_tolerance_error=0,
        intensity_error=0,
        usb_error=0,
        dll_error=0,
        laser_speed_error=0,
        laser_temp_error=0,
        daq_error=0,
    )
    assert MultiLineDriver._status_from_errors(ch) == ChannelStatus.OK
