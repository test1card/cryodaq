"""LakeShore 218S driver with optional runtime calibration routing."""

from __future__ import annotations

import logging
import random
from typing import Any

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.gpib import GPIBTransport

log = logging.getLogger(__name__)

_MOCK_BASE_TEMPS: tuple[float, ...] = (4.2, 4.8, 77.0, 77.5, 4.5, 4.1, 3.9, 300.0)


def _mock_sensor_unit(temp_k: float) -> float:
    return round((1600.0 / (temp_k + 15.0)) + 0.08, 6)


class LakeShore218S(InstrumentDriver):
    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        channel_labels: dict[int, str] | None = None,
        mock: bool = False,
        calibration_store: CalibrationStore | None = None,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._channel_labels: dict[int, str] = channel_labels or {}
        self._transport = GPIBTransport(mock=mock)
        self._instrument_id: str = ""
        self._calibration_store = calibration_store
        self._runtime_warning_cache: set[tuple[str, str]] = set()

    async def connect(self) -> None:
        log.info("%s: connecting to %s", self.name, self._resource_str)
        idn = await self._transport.open(self._resource_str, verify_query="*IDN?")
        self._instrument_id = idn or ""
        self._connected = True

    async def disconnect(self) -> None:
        if not self._connected:
            return
        await self._transport.close()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument is not connected")

        runtime_policies = self._runtime_channel_policies()
        if not runtime_policies:
            return await self._read_krdg_channels()

        temperature_readings = await self._read_krdg_channels()
        needs_curve = any(policy.get("reading_mode") == "curve" for policy in runtime_policies.values())
        raw_readings = await self.read_srdg_channels() if needs_curve else []
        return self._merge_runtime_readings(temperature_readings, raw_readings, runtime_policies)

    async def _read_krdg_channels(self) -> list[Reading]:
        if self.mock:
            return self._mock_readings()
        raw_response = await self._transport.query("KRDG? 0")
        log.debug("%s: KRDG? 0 -> %s", self.name, raw_response)
        return self._parse_response(raw_response, unit="K", reading_kind="temperature")

    async def read_srdg_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument is not connected")
        if self.mock:
            return self._mock_sensor_readings()
        raw_response = await self._transport.query("SRDG? 0")
        log.debug("%s: SRDG? 0 -> %s", self.name, raw_response)
        return self._parse_response(raw_response, unit="sensor_unit", reading_kind="raw_sensor")

    async def read_calibration_pair(
        self,
        *,
        reference_channel: int | str,
        sensor_channel: int | str,
    ) -> dict[str, Any]:
        temperatures = await self._read_krdg_channels()
        raw_readings = await self.read_srdg_channels()
        reference_reading = self._resolve_channel_reading(temperatures, reference_channel)
        sensor_reading = self._resolve_channel_reading(raw_readings, sensor_channel)
        return {
            "reference": reference_reading,
            "sensor": sensor_reading,
        }

    def _parse_response(self, response: str, *, unit: str, reading_kind: str) -> list[Reading]:
        tokens = [token.strip() for token in response.split(",")]
        readings: list[Reading] = []
        for index, token in enumerate(tokens[:8], start=1):
            channel_name = self._channel_labels.get(index, f"CH{index}")
            metadata = {
                "raw_channel": index,
                "reading_kind": reading_kind,
            }
            token_upper = token.upper().lstrip("+")
            if token_upper in {"OVL", "+OVL"}:
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("inf"),
                        unit=unit,
                        instrument_id=self.name,
                        status=ChannelStatus.OVERRANGE,
                        raw=None,
                        metadata=metadata,
                    )
                )
                continue
            try:
                value = float(token)
            except ValueError:
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("nan"),
                        unit=unit,
                        instrument_id=self.name,
                        status=ChannelStatus.SENSOR_ERROR,
                        raw=None,
                        metadata=metadata,
                    )
                )
                continue
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=value,
                    unit=unit,
                    instrument_id=self.name,
                    status=ChannelStatus.OK,
                    raw=value,
                    metadata=metadata,
                )
            )
        return readings

    def _mock_readings(self) -> list[Reading]:
        readings: list[Reading] = []
        for index, base_temp in enumerate(_MOCK_BASE_TEMPS, start=1):
            channel_name = self._channel_labels.get(index, f"CH{index}")
            noise = base_temp * random.uniform(-0.005, 0.005)
            value = round(base_temp + noise, 4)
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=value,
                    unit="K",
                    instrument_id=self.name,
                    status=ChannelStatus.OK,
                    raw=value,
                    metadata={
                        "raw_channel": index,
                        "reading_kind": "temperature",
                    },
                )
            )
        return readings

    def _mock_sensor_readings(self) -> list[Reading]:
        readings: list[Reading] = []
        for index, base_temp in enumerate(_MOCK_BASE_TEMPS, start=1):
            channel_name = self._channel_labels.get(index, f"CH{index}")
            raw_base = _mock_sensor_unit(base_temp)
            noise = raw_base * random.uniform(-0.002, 0.002)
            value = round(raw_base + noise, 6)
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=value,
                    unit="sensor_unit",
                    instrument_id=self.name,
                    status=ChannelStatus.OK,
                    raw=value,
                    metadata={
                        "raw_channel": index,
                        "reading_kind": "raw_sensor",
                    },
                )
            )
        return readings

    def _runtime_channel_policies(self) -> dict[int, dict[str, Any]]:
        if self._calibration_store is None:
            return {}
        policies: dict[int, dict[str, Any]] = {}
        for channel_num in range(1, 9):
            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
            channel_key = self._runtime_channel_key(channel_name)
            resolution = self._calibration_store.resolve_runtime_policy(channel_key=channel_key)
            policies[channel_num] = resolution
            reason = str(resolution.get("reason", ""))
            if resolution.get("reading_mode") != "curve" and reason not in {"global_off", "channel_off", "missing_assignment", ""}:
                self._log_runtime_fallback(channel_key=channel_key, reason=reason)
        return policies

    def _merge_runtime_readings(
        self,
        temperature_readings: list[Reading],
        raw_readings: list[Reading],
        policies: dict[int, dict[str, Any]],
    ) -> list[Reading]:
        raw_by_channel = {
            int(reading.metadata.get("raw_channel", 0)): reading
            for reading in raw_readings
            if int(reading.metadata.get("raw_channel", 0)) > 0
        }
        merged: list[Reading] = []
        for reading in temperature_readings:
            channel_num = int(reading.metadata.get("raw_channel", 0))
            policy = policies.get(channel_num) or {}
            assignment = policy.get("assignment") if isinstance(policy.get("assignment"), dict) else {}
            if policy.get("reading_mode") != "curve":
                merged.append(
                    self._with_runtime_metadata(
                        reading,
                        reading_mode="krdg",
                        raw_source="KRDG",
                        curve_id=assignment.get("curve_id"),
                        sensor_id=assignment.get("sensor_id"),
                        runtime_reason=str(policy.get("reason", "krdg_default")),
                    )
                )
                continue

            raw_reading = raw_by_channel.get(channel_num)
            if raw_reading is None or raw_reading.status is not ChannelStatus.OK:
                self._log_runtime_fallback(channel_key=str(policy.get("channel_key", "")), reason="missing_srdg")
                merged.append(
                    self._with_runtime_metadata(
                        reading,
                        reading_mode="krdg",
                        raw_source="KRDG",
                        curve_id=assignment.get("curve_id"),
                        sensor_id=assignment.get("sensor_id"),
                        runtime_reason="missing_srdg",
                    )
                )
                continue

            sensor_id = str(assignment.get("sensor_id", "")).strip()
            try:
                calibrated_value = self._calibration_store.evaluate(sensor_id, float(raw_reading.value))  # type: ignore[union-attr]
            except Exception:
                self._log_runtime_fallback(channel_key=str(policy.get("channel_key", "")), reason="curve_evaluate_failed")
                merged.append(
                    self._with_runtime_metadata(
                        reading,
                        reading_mode="krdg",
                        raw_source="KRDG",
                        curve_id=assignment.get("curve_id"),
                        sensor_id=assignment.get("sensor_id"),
                        runtime_reason="curve_evaluate_failed",
                    )
                )
                continue

            merged.append(
                Reading(
                    timestamp=reading.timestamp,
                    instrument_id=reading.instrument_id,
                    channel=reading.channel,
                    value=float(calibrated_value),
                    unit="K",
                    status=ChannelStatus.OK,
                    raw=float(raw_reading.value),
                    metadata={
                        **reading.metadata,
                        "reading_mode": "curve",
                        "raw_source": "SRDG",
                        "curve_id": assignment.get("curve_id"),
                        "sensor_id": assignment.get("sensor_id"),
                    },
                )
            )
        return merged

    def _with_runtime_metadata(
        self,
        reading: Reading,
        *,
        reading_mode: str,
        raw_source: str,
        curve_id: Any,
        sensor_id: Any,
        runtime_reason: str,
    ) -> Reading:
        return Reading(
            timestamp=reading.timestamp,
            instrument_id=reading.instrument_id,
            channel=reading.channel,
            value=reading.value,
            unit=reading.unit,
            status=reading.status,
            raw=reading.raw,
            metadata={
                **reading.metadata,
                "reading_mode": reading_mode,
                "raw_source": raw_source,
                "curve_id": curve_id,
                "sensor_id": sensor_id,
                "runtime_reason": runtime_reason,
            },
        )

    def _runtime_channel_key(self, channel_name: str) -> str:
        return f"{self.name}:{channel_name}"

    def _log_runtime_fallback(self, *, channel_key: str, reason: str) -> None:
        cache_key = (channel_key, reason)
        if cache_key in self._runtime_warning_cache:
            return
        self._runtime_warning_cache.add(cache_key)
        log.warning("%s: runtime calibration fallback for %s (%s)", self.name, channel_key, reason)

    def _resolve_channel_reading(
        self,
        readings: list[Reading],
        channel_spec: int | str,
    ) -> Reading:
        if isinstance(channel_spec, int):
            for reading in readings:
                if reading.metadata.get("raw_channel") == channel_spec:
                    return reading
            raise KeyError(f"LakeShore channel {channel_spec} not found.")

        channel_name = str(channel_spec).strip()
        if not channel_name:
            raise ValueError("LakeShore channel must not be empty.")
        if channel_name.upper().startswith("CH") and channel_name[2:].isdigit():
            channel_num = int(channel_name[2:])
            for reading in readings:
                if reading.metadata.get("raw_channel") == channel_num:
                    return reading
        for reading in readings:
            if reading.channel == channel_name:
                return reading
        raise KeyError(f"LakeShore channel '{channel_name}' not found.")
