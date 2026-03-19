"""Keithley 2604B driver with dual-channel runtime support.

P=const control loop runs host-side in read_channels() — no TSP scripts
are uploaded to the instrument, so the VISA bus stays free for queries.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from cryodaq.core.smu_channel import SMU_CHANNELS, SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.usbtmc import USBTMCTransport

log = logging.getLogger(__name__)

# Minimum measurable current for resistance calculation (avoid division by noise)
_I_MIN_A = 1e-9

_MOCK_R0 = 100.0
_MOCK_T0 = 300.0
_MOCK_ALPHA = 0.0033
_MOCK_COOLING_RATE = 0.1
_MOCK_SMUB_FACTOR = 0.7

_IV_FIELDS = (
    ("voltage", "V"),
    ("current", "A"),
    ("resistance", "Ohm"),
    ("power", "W"),
)


@dataclass
class ChannelRuntime:
    channel: SmuChannel
    p_target: float = 0.0
    v_comp: float = 40.0
    i_comp: float = 1.0
    active: bool = False


class Keithley2604B(InstrumentDriver):
    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._transport = USBTMCTransport(mock=mock)
        self._instrument_id = ""
        self._channels: dict[SmuChannel, ChannelRuntime] = {
            "smua": ChannelRuntime(channel="smua"),
            "smub": ChannelRuntime(channel="smub"),
        }
        self._mock_temp = _MOCK_T0

    async def connect(self) -> None:
        log.info("%s: connecting to %s", self.name, self._resource_str)
        await self._transport.open(self._resource_str)
        try:
            idn = await self._transport.query("*IDN?")
            self._instrument_id = idn
            if "2604B" not in idn:
                raise RuntimeError(f"{self.name}: unexpected IDN {idn!r}")
            # Drain stale errors so they don't confuse runtime error checks.
            await self._transport.write("errorqueue.clear()")
        except Exception:
            await self._transport.close()
            raise
        self._connected = True

    async def disconnect(self) -> None:
        if not self._connected:
            return
        await self.emergency_off()
        await self._transport.close()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")

        if self.mock:
            return self._mock_readings()

        readings: list[Reading] = []
        for smu_channel in SMU_CHANNELS:
            runtime = self._channels[smu_channel]
            try:
                if not runtime.active:
                    # Check output state — source may be OFF or left ON from
                    # a previous session.  measure.iv() errors when output is OFF.
                    output_raw = await self._transport.query(
                        f"print({smu_channel}.source.output)", timeout_ms=3000
                    )
                    try:
                        output_on = float(output_raw.strip()) > 0.5
                    except ValueError:
                        output_on = False

                    if not output_on:
                        readings.extend(
                            self._build_channel_readings(smu_channel, 0.0, 0.0, resistance_override=0.0)
                        )
                        continue

                    # Output is ON but not managed by us — read for monitoring.
                    raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
                    current, voltage = self._parse_iv_response(raw, smu_channel)
                    readings.extend(self._build_channel_readings(smu_channel, voltage, current))
                    continue

                # --- Active P=const channel: measure + regulate ---
                raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
                current, voltage = self._parse_iv_response(raw, smu_channel)

                if abs(current) > _I_MIN_A:
                    resistance = voltage / current
                    if resistance > 0:
                        target_v = math.sqrt(runtime.p_target * resistance)
                        target_v = max(0.0, min(target_v, runtime.v_comp))
                        await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")

                readings.extend(self._build_channel_readings(smu_channel, voltage, current))
            except Exception as exc:
                log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
                readings.extend(self._error_readings_for_channel(smu_channel))
        return readings

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        smu_channel = normalize_smu_channel(channel)
        runtime = self._channels[smu_channel]

        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
            raise ValueError("P/V/I must be > 0")
        if runtime.active:
            raise RuntimeError(f"Channel {smu_channel} already active")

        runtime.p_target = p_target
        runtime.v_comp = v_compliance
        runtime.i_comp = i_compliance

        if self.mock:
            runtime.active = True
            return

        # Configure source directly via VISA — no TSP script.
        await self._transport.write(f"{smu_channel}.reset()")
        await self._transport.write(f"{smu_channel}.source.func = {smu_channel}.OUTPUT_DCVOLTS")
        await self._transport.write(f"{smu_channel}.source.autorangev = {smu_channel}.AUTORANGE_ON")
        await self._transport.write(f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON")
        await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
        await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
        await self._transport.write(f"{smu_channel}.source.levelv = 0")
        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
        runtime.active = True

    async def stop_source(self, channel: str) -> None:
        smu_channel = normalize_smu_channel(channel)
        runtime = self._channels[smu_channel]

        if self.mock:
            runtime.active = False
            runtime.p_target = 0.0
            return

        if not self._connected:
            return

        await self._transport.write(f"{smu_channel}.source.levelv = 0")
        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
        await self._verify_output_off(smu_channel)
        runtime.active = False
        runtime.p_target = 0.0

    async def read_buffer(self, start_idx: int = 1, count: int = 100) -> list[dict[str, float]]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        if self.mock:
            return self._mock_buffer(start_idx, count)

        end_idx = start_idx + count - 1
        raw = await self._transport.query(
            f"printbuffer({start_idx}, {end_idx}, smua.nvbuffer1.timestamps, smua.nvbuffer1.sourcevalues, smua.nvbuffer1)",
            timeout_ms=10_000,
        )
        return self._parse_buffer_response(raw)

    async def emergency_off(self, channel: str | None = None) -> None:
        channels = [normalize_smu_channel(channel)] if channel is not None else list(SMU_CHANNELS)
        for smu_channel in channels:
            runtime = self._channels[smu_channel]
            runtime.active = False
            runtime.p_target = 0.0

        if self.mock or not self._connected:
            return

        for smu_channel in channels:
            try:
                await self._transport.write(f"{smu_channel}.source.levelv = 0")
                await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
            except Exception as exc:
                log.critical("%s: emergency_off failed on %s: %s", self.name, smu_channel, exc)

    async def check_error(self) -> str | None:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        response = (await self._transport.query("print(errorqueue.count)")).strip()
        if response in {"", "0"}:
            return None
        return response

    @property
    def any_active(self) -> bool:
        return any(runtime.active for runtime in self._channels.values())

    @property
    def active_channels(self) -> list[str]:
        return [channel for channel, runtime in self._channels.items() if runtime.active]

    async def _verify_output_off(self, channel: str) -> None:
        if self.mock or not self._connected:
            return
        smu_channel = normalize_smu_channel(channel)
        response = await self._transport.query(f"print({smu_channel}.source.output)", timeout_ms=3000)
        try:
            if float(response.strip()) > 0.5:
                log.critical("%s: %s still reports output=%s", self.name, smu_channel, response.strip())
        except ValueError:
            log.critical("%s: %s unexpected output response: %r", self.name, smu_channel, response.strip())

    def _parse_iv_response(self, raw: str, channel: SmuChannel) -> tuple[float, float]:
        parts = raw.strip().split("\t")
        if len(parts) != 2:
            raise ValueError(f"{channel}: expected 2 values, got {raw!r}")
        return float(parts[0]), float(parts[1])

    def _build_channel_readings(
        self,
        channel: SmuChannel,
        voltage: float,
        current: float,
        *,
        resistance_override: float | None = None,
    ) -> list[Reading]:
        resistance = resistance_override if resistance_override is not None else (
            voltage / current if current != 0.0 else float("nan")
        )
        power = voltage * current
        metadata: dict[str, Any] = {"resource_str": self._resource_str, "smu_channel": channel}
        return [
            Reading.now(
                channel=f"{self.name}/{channel}/voltage",
                value=voltage,
                unit="V",
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=voltage,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/{channel}/current",
                value=current,
                unit="A",
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=current,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/{channel}/resistance",
                value=resistance,
                unit="Ohm",
                instrument_id=self.name,
                status=ChannelStatus.OK if math.isfinite(resistance) else ChannelStatus.SENSOR_ERROR,
                raw=resistance if math.isfinite(resistance) else None,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/{channel}/power",
                value=power,
                unit="W",
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=power,
                metadata=metadata,
            ),
        ]

    def _parse_buffer_response(self, raw: str) -> list[dict[str, float]]:
        tokens = [token.strip() for token in raw.replace("\t", ",").split(",")]
        results: list[dict[str, float]] = []
        n = len(tokens) // 3
        for idx in range(n):
            try:
                ts = float(tokens[idx])
                voltage = float(tokens[n + idx])
                current = float(tokens[2 * n + idx])
            except (ValueError, IndexError):
                continue
            resistance = voltage / current if current != 0.0 else float("nan")
            power = voltage * current
            results.append(
                {
                    "timestamp": ts,
                    "voltage": voltage,
                    "current": current,
                    "resistance": resistance,
                    "power": power,
                }
            )
        return results

    def _mock_r_of_t(self) -> float:
        return max(_MOCK_R0 * (1.0 + _MOCK_ALPHA * (self._mock_temp - _MOCK_T0)), 1.0)

    def _mock_readings(self) -> list[Reading]:
        if self._mock_temp > 4.0:
            self._mock_temp = max(4.0, self._mock_temp - _MOCK_COOLING_RATE)

        readings: list[Reading] = []
        base_r = self._mock_r_of_t()
        for smu_channel in SMU_CHANNELS:
            runtime = self._channels[smu_channel]
            resistance = base_r if smu_channel == "smua" else base_r * _MOCK_SMUB_FACTOR
            if runtime.active and runtime.p_target > 0.0:
                voltage = math.sqrt(runtime.p_target * resistance)
                current = voltage / resistance
            else:
                voltage = 0.0
                current = 0.0
            readings.extend(
                self._build_channel_readings(
                    smu_channel,
                    round(voltage, 6),
                    round(current, 7),
                    resistance_override=round(resistance, 4),
                )
            )
        return readings

    def _mock_buffer(self, start_idx: int, count: int) -> list[dict[str, float]]:
        results: list[dict[str, float]] = []
        resistance = self._mock_r_of_t()
        runtime = self._channels["smua"]
        voltage = math.sqrt(runtime.p_target * resistance) if runtime.active and runtime.p_target > 0.0 else 0.0
        current = voltage / resistance if resistance > 0.0 else 0.0
        for idx in range(count):
            results.append(
                {
                    "timestamp": float(start_idx + idx) * 0.5,
                    "voltage": round(voltage, 6),
                    "current": round(current, 7),
                    "resistance": round(resistance, 4),
                    "power": round(voltage * current, 7),
                }
            )
        return results

    def _error_readings_for_channel(self, channel: SmuChannel) -> list[Reading]:
        metadata: dict[str, Any] = {"resource_str": self._resource_str, "smu_channel": channel}
        return [
            Reading.now(
                channel=f"{self.name}/{channel}/{field}",
                value=float("nan"),
                unit=unit,
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata=metadata,
            )
            for field, unit in _IV_FIELDS
        ]
