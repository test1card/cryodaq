"""Keithley 2604B driver with dual-channel runtime support."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryodaq.core.smu_channel import SMU_CHANNELS, SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.usbtmc import USBTMCTransport

log = logging.getLogger(__name__)

_DEFAULT_TSP_DIR = Path(__file__).parents[4] / "tsp"
_HEARTBEAT_INTERVAL_S = 10.0

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
    script_running: bool = False
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)


class Keithley2604B(InstrumentDriver):
    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        tsp_dir: Path | None = None,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._tsp_dir = tsp_dir or _DEFAULT_TSP_DIR
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
            try:
                # Check output state first — measure.iv() returns TSP error -285
                # ("not permitted when output is off") when source is OFF.
                output_raw = await self._transport.query(
                    f"print({smu_channel}.source.output)", timeout_ms=3000
                )
                try:
                    output_on = float(output_raw.strip()) > 0.5
                except ValueError:
                    output_on = False

                if not output_on:
                    # Source OFF is a normal operating state — return zeros.
                    # Explicit resistance_override=0.0 to avoid 0/0 → NaN
                    # (NaN maps to NULL in sqlite3, violating NOT NULL constraint).
                    readings.extend(
                        self._build_channel_readings(smu_channel, 0.0, 0.0, resistance_override=0.0)
                    )
                    continue

                raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
                current, voltage = self._parse_iv_response(raw, smu_channel)
                readings.extend(self._build_channel_readings(smu_channel, voltage, current))
            except Exception as exc:
                log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
                readings.extend(self._error_readings_for_channel(smu_channel))
        return readings

    async def load_tsp(self, script_path: Path) -> None:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        if not script_path.exists():
            raise FileNotFoundError(f"{self.name}: missing TSP script {script_path}")

        payload = f"loadandrunscript\n{script_path.read_text(encoding='utf-8')}\nendscript\n"
        await self._transport.write_raw(payload.encode("utf-8"))

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
            runtime.script_running = True
            self._start_heartbeat(smu_channel)
            return

        await self._transport.write(f"{smu_channel}_P_target = {p_target}")
        await self._transport.write(f"{smu_channel}_V_compliance = {v_compliance}")
        await self._transport.write(f"{smu_channel}_I_compliance = {i_compliance}")
        await self._transport.write_raw(self._load_tsp_template(smu_channel).encode("utf-8"))
        runtime.active = True
        runtime.script_running = True
        self._start_heartbeat(smu_channel)

    async def stop_source(self, channel: str) -> None:
        smu_channel = normalize_smu_channel(channel)
        runtime = self._channels[smu_channel]
        self._cancel_heartbeat(smu_channel)

        if self.mock:
            runtime.active = False
            runtime.script_running = False
            runtime.p_target = 0.0
            return

        if not self._connected:
            return

        await self._transport.write(f"{smu_channel}.source.levelv = 0")
        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
        await self._verify_output_off(smu_channel)
        runtime.active = False
        runtime.script_running = False
        runtime.p_target = 0.0

    async def heartbeat(self, channel: str | None = None) -> None:
        if not self._connected:
            return

        if channel is None:
            for smu_channel in self.active_channels:
                await self._transport.write(f"if {smu_channel}_heartbeat then {smu_channel}_heartbeat() end")
            return

        smu_channel = normalize_smu_channel(channel)
        await self._transport.write(f"if {smu_channel}_heartbeat then {smu_channel}_heartbeat() end")

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
            self._cancel_heartbeat(smu_channel)
            runtime = self._channels[smu_channel]
            runtime.active = False
            runtime.script_running = False
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

    def _start_heartbeat(self, channel: SmuChannel) -> None:
        self._cancel_heartbeat(channel)
        self._channels[channel].heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(channel),
            name=f"heartbeat:{self.name}:{channel}",
        )

    def _cancel_heartbeat(self, channel: SmuChannel) -> None:
        task = self._channels[channel].heartbeat_task
        if task is not None and not task.done():
            task.cancel()
        self._channels[channel].heartbeat_task = None

    async def _heartbeat_loop(self, channel: SmuChannel) -> None:
        try:
            while self._channels[channel].active:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
                await self.heartbeat(channel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.critical("%s: heartbeat failure on %s: %s", self.name, channel, exc)
            try:
                await self.stop_source(channel)
            except Exception:
                log.exception("%s: stop_source failed after heartbeat failure on %s", self.name, channel)

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

    def _load_tsp_template(self, channel: SmuChannel) -> str:
        template_path = self._tsp_dir / "p_const.lua"
        if not template_path.exists():
            template_path = self._tsp_dir / "p_const_single.lua"
        template = template_path.read_text(encoding="utf-8")
        return template.replace("{SMU}", channel).replace("{SMU_VAR}", channel)

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
