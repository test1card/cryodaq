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


_ERROR_FIELDS = [
    "analysis_error",
    "beam_break",
    "temp_error",
    "motion_tolerance_error",
    "intensity_error",
    "usb_error",
    "dll_error",
    "laser_speed_error",
    "laser_temp_error",
    "daq_error",
]


@pytest.mark.parametrize("flag", _ERROR_FIELDS)
def test_status_from_errors_any_flag_trips_sensor_error(flag):
    from cryodaq.drivers.instruments.etalon_multiline import _ChannelData

    flags = {f: 0 for f in _ERROR_FIELDS}
    flags[flag] = 1
    ch = _ChannelData(
        channel_number=1,
        length_mm=1.0,
        intensity_min=0,
        intensity_max=0,
        temperature_c=20.0,
        pressure_hpa=1013.0,
        humidity_pct=40.0,
        **flags,
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


# ---------------------------------------------------------------------------
# v0.55.6.1 — channel_count config + 1..32 validation
# ---------------------------------------------------------------------------


def test_channel_count_resolves_to_implicit_range_when_no_explicit_list() -> None:
    driver = MultiLineDriver("ML1", "localhost", channel_count=8, mock=True)
    assert driver._channel_numbers == [1, 2, 3, 4, 5, 6, 7, 8]


def test_explicit_channel_numbers_override_channel_count() -> None:
    driver = MultiLineDriver(
        "ML1",
        "localhost",
        channel_numbers=[2, 5, 7],
        channel_count=99,  # ignored when explicit list present
        mock=True,
    )
    assert driver._channel_numbers == [2, 5, 7]


def test_default_channels_when_no_config_provided() -> None:
    driver = MultiLineDriver("ML1", "localhost", mock=True)
    assert driver._channel_numbers == [1, 2, 3, 4]


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_channel_count_lower_bound_rejected(count: int) -> None:
    with pytest.raises(ValueError, match="1..32"):
        MultiLineDriver("ML1", "localhost", channel_count=count, mock=True)


def test_invalid_channel_count_upper_bound_rejected() -> None:
    with pytest.raises(ValueError, match="1..32"):
        MultiLineDriver("ML1", "localhost", channel_count=33, mock=True)


def test_invalid_explicit_channel_id_rejected() -> None:
    with pytest.raises(ValueError, match="channel id"):
        MultiLineDriver("ML1", "localhost", channel_numbers=[0, 1, 2], mock=True)
    with pytest.raises(ValueError, match="channel id"):
        MultiLineDriver("ML1", "localhost", channel_numbers=[1, 2, 33], mock=True)


def test_duplicate_channel_ids_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        MultiLineDriver("ML1", "localhost", channel_numbers=[1, 2, 2, 3], mock=True)


def test_max_32_channels_accepted() -> None:
    driver = MultiLineDriver(
        "ML1", "localhost", channel_count=32, mock=True
    )
    assert len(driver._channel_numbers) == 32
    assert driver._channel_numbers[0] == 1
    assert driver._channel_numbers[-1] == 32
