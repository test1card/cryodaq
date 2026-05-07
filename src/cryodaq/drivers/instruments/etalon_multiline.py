"""Etalon MultiLine driver — interferometric length metrology over TCP.

Stage 1: latest valid length readings + environment data + connection
check + mock mode. Stage 2 (deformation analysis, channel alignment,
MLAC/AC operations, frontend splitter/shutter control) is intentionally
out of scope and lives in a separate spec.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.tcp import TCPTransport, TCPTransportError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ChannelData:
    """Per-channel record extracted from a `channeldata_...` response."""

    channel_number: int
    length_mm: float
    intensity_min: int
    intensity_max: int
    temperature_c: float
    pressure_hpa: float
    humidity_pct: float
    analysis_error: int
    beam_break: int
    temp_error: int
    motion_tolerance_error: int
    intensity_error: int
    usb_error: int
    dll_error: int
    laser_speed_error: int
    laser_temp_error: int
    daq_error: int


def _parse_channeldata_response(response: str) -> tuple[list[_ChannelData], int]:
    """Parse `channeldata_<CH1>,<L1>,...,<DAQE1>_<CH2>,..._<SE>` response.

    Channel records are underscore-separated; each record is a
    comma-separated tuple of 17 fields. The last underscore-separated
    element is the server-error flag.
    """
    if not response.startswith("channeldata_"):
        raise ValueError(f"Unexpected response: {response[:80]}")
    payload = response[len("channeldata_") :]
    parts = payload.split("_")
    if len(parts) < 2:
        raise ValueError(f"channeldata too short: {response[:120]}")
    se_str = parts[-1]
    channel_parts = parts[:-1]

    channels: list[_ChannelData] = []
    for ch_str in channel_parts:
        fields = ch_str.split(",")
        if len(fields) < 17:
            logger.warning("channeldata channel record too short: %r", ch_str[:80])
            continue
        try:
            channels.append(
                _ChannelData(
                    channel_number=int(fields[0]),
                    length_mm=float(fields[1]),
                    intensity_min=int(fields[2]),
                    intensity_max=int(fields[3]),
                    temperature_c=float(fields[4]),
                    pressure_hpa=float(fields[5]),
                    humidity_pct=float(fields[6]),
                    analysis_error=int(fields[7]),
                    beam_break=int(fields[8]),
                    temp_error=int(fields[9]),
                    motion_tolerance_error=int(fields[10]),
                    intensity_error=int(fields[11]),
                    usb_error=int(fields[12]),
                    dll_error=int(fields[13]),
                    laser_speed_error=int(fields[14]),
                    laser_temp_error=int(fields[15]),
                    daq_error=int(fields[16]),
                )
            )
        except (ValueError, IndexError) as exc:
            logger.warning("channeldata field parse failed (%r): %s", ch_str[:80], exc)

    try:
        server_error = int(se_str)
    except ValueError:
        server_error = -1
    return channels, server_error


def _parse_environmentdata_response(response: str) -> tuple[float, float, float]:
    """Parse `environmentdata_<T>,<P>,<H>` -> (temp_c, pressure_hpa, humidity_pct)."""
    if not response.startswith("environmentdata_"):
        raise ValueError(f"Unexpected response: {response[:80]}")
    parts = response[len("environmentdata_") :].split(",")
    if len(parts) < 3:
        raise ValueError(f"environmentdata too short: {response[:80]}")
    return float(parts[0]), float(parts[1]), float(parts[2])


def _parse_isconnected_response(response: str) -> bool:
    """Parse `isconnected_<flag>` -> bool."""
    if not response.startswith("isconnected_"):
        raise ValueError(f"Unexpected response: {response[:80]}")
    return response[len("isconnected_") :].strip() == "1"


def _parse_laserready_response(response: str) -> bool:
    """Parse `laserready_<flag>` -> bool."""
    if not response.startswith("laserready_"):
        raise ValueError(f"Unexpected response: {response[:80]}")
    return response[len("laserready_") :].strip() == "1"


class MultiLineDriver(InstrumentDriver):
    """Etalon MultiLine interferometric length measurement driver.

    Stage 1 features: latest valid length readings, environment data,
    connection lifecycle, mock mode. Reading channels follow the
    convention `<name>/length_ch<N>` (mm) and `<name>/env_<temperature
    |pressure|humidity>`. Reconnection is the scheduler's job, not the
    driver's: read_channels returns [] on transport error.
    """

    # v0.55.6.1: Etalon MultiLine hardware ships with up to 32 laser
    # channels; the operator picks the active set per deployment. The
    # driver enforces 1..32 because the protocol's `latestlengthvalid`
    # query degenerates outside that band (zero or repeated indices
    # produce an empty channeldata response and silently lose data).
    _MIN_CHANNELS = 1
    _MAX_CHANNELS = 32

    def __init__(
        self,
        name: str,
        host: str,
        *,
        port: int = 2001,
        channel_numbers: list[int] | None = None,
        channel_count: int | None = None,
        connect_timeout_s: float = 5.0,
        read_timeout_s: float = 10.0,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._host = host
        self._port = port
        # Resolve channel set. ``channel_numbers`` (explicit list) wins
        # over ``channel_count`` (count-only sugar) so an operator can
        # pin a specific laser subset (e.g. [2, 5, 7] when one mirror
        # is replaced) without rewriting the implicit-range default.
        if channel_numbers:
            resolved = list(channel_numbers)
        elif channel_count is not None:
            resolved = list(range(1, int(channel_count) + 1))
        else:
            resolved = [1, 2, 3, 4]
        self._validate_channel_numbers(resolved)
        self._channel_numbers = resolved
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._transport: TCPTransport | None = None
        self._mock_nominal_lengths_mm = {
            ch: 1000.0 + ch * 50.0 for ch in self._channel_numbers
        }

    @classmethod
    def _validate_channel_numbers(cls, channels: list[int]) -> None:
        if len(channels) < cls._MIN_CHANNELS or len(channels) > cls._MAX_CHANNELS:
            raise ValueError(
                f"MultiLine channel set must have {cls._MIN_CHANNELS}..{cls._MAX_CHANNELS} "
                f"entries, got {len(channels)}"
            )
        for ch in channels:
            if not isinstance(ch, int) or ch < 1 or ch > cls._MAX_CHANNELS:
                raise ValueError(
                    f"MultiLine channel id must be int in 1..{cls._MAX_CHANNELS}, got {ch!r}"
                )
        if len(set(channels)) != len(channels):
            raise ValueError(f"MultiLine channel set must be unique, got {channels}")

    async def connect(self) -> None:
        if self._connected:
            return
        if self.mock:
            self._connected = True
            return
        self._transport = TCPTransport(
            self._host,
            self._port,
            connect_timeout_s=self._connect_timeout_s,
            read_timeout_s=self._read_timeout_s,
        )
        await self._transport.open()
        try:
            response = await self._transport.query("isconnected")
            if not _parse_isconnected_response(response):
                logger.warning("MultiLine '%s': lasers not connected", self.name)
        except (TCPTransportError, ValueError) as exc:
            logger.error("MultiLine '%s' connect verify failed: %s", self.name, exc)
        self._connected = True

    async def disconnect(self) -> None:
        if self._transport is not None:
            await self._transport.close()
            self._transport = None
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if self.mock:
            return self._mock_readings()
        if self._transport is None:
            raise TCPTransportError("Driver not connected")

        readings: list[Reading] = []
        try:
            channels_arg = ",".join(str(c) for c in self._channel_numbers)
            response = await self._transport.query(
                f"latestlengthvalid,{channels_arg}"
            )
            channel_data, _server_error = _parse_channeldata_response(response)
            for ch in channel_data:
                status = self._status_from_errors(ch)
                readings.append(
                    Reading.now(
                        channel=f"{self.name}/length_ch{ch.channel_number}",
                        value=ch.length_mm,
                        unit="mm",
                        instrument_id=self.name,
                        status=status,
                        metadata={
                            "intensity_min": ch.intensity_min,
                            "intensity_max": ch.intensity_max,
                            "temperature_c": ch.temperature_c,
                            "pressure_hpa": ch.pressure_hpa,
                        },
                    )
                )
            env_response = await self._transport.query("environmentdata")
            t_c, p_hpa, h_pct = _parse_environmentdata_response(env_response)
            readings.append(
                Reading.now(
                    channel=f"{self.name}/env_temperature",
                    value=t_c,
                    unit="°C",
                    instrument_id=self.name,
                )
            )
            readings.append(
                Reading.now(
                    channel=f"{self.name}/env_pressure",
                    value=p_hpa,
                    unit="hPa",
                    instrument_id=self.name,
                )
            )
            readings.append(
                Reading.now(
                    channel=f"{self.name}/env_humidity",
                    value=h_pct,
                    unit="%",
                    instrument_id=self.name,
                )
            )
        except (TCPTransportError, ValueError) as exc:
            logger.error("MultiLine '%s' read failed: %s", self.name, exc)
            return []

        return readings

    @staticmethod
    def _status_from_errors(ch: _ChannelData) -> ChannelStatus:
        # Any non-zero error field invalidates the reading. The Annex
        # protocol exposes 10 distinct error flags per channel record;
        # silently mapping a subset would let bad data surface as OK.
        if (
            ch.analysis_error
            or ch.beam_break
            or ch.temp_error
            or ch.motion_tolerance_error
            or ch.intensity_error
            or ch.usb_error
            or ch.dll_error
            or ch.laser_speed_error
            or ch.laser_temp_error
            or ch.daq_error
        ):
            return ChannelStatus.SENSOR_ERROR
        return ChannelStatus.OK

    def _mock_readings(self) -> list[Reading]:
        readings: list[Reading] = []
        for ch_num in self._channel_numbers:
            nominal = self._mock_nominal_lengths_mm[ch_num]
            length = nominal + random.uniform(-0.010, 0.010)
            readings.append(
                Reading.now(
                    channel=f"{self.name}/length_ch{ch_num}",
                    value=length,
                    unit="mm",
                    instrument_id=self.name,
                )
            )
        readings.append(
            Reading.now(
                channel=f"{self.name}/env_temperature",
                value=22.5 + random.uniform(-0.5, 0.5),
                unit="°C",
                instrument_id=self.name,
            )
        )
        readings.append(
            Reading.now(
                channel=f"{self.name}/env_pressure",
                value=1013.25 + random.uniform(-2.0, 2.0),
                unit="hPa",
                instrument_id=self.name,
            )
        )
        readings.append(
            Reading.now(
                channel=f"{self.name}/env_humidity",
                value=45.0 + random.uniform(-3.0, 3.0),
                unit="%",
                instrument_id=self.name,
            )
        )
        return readings
