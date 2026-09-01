"""LakeShore 218S driver with optional runtime calibration routing."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time as _time
from dataclasses import replace
from typing import Any

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.drivers.base import (
    INSTRUMENT_STATUS_FAULT_REASONS_KEY,
    INSTRUMENT_STATUS_REGISTER_KEY,
    LAKESHORE_218_RDGST_REGISTER,
    ChannelStatus,
    InstrumentDriver,
    InstrumentStatusFaultReason,
    Reading,
)
from cryodaq.drivers.transport.gpib import GPIBTransport
from cryodaq.drivers.transport.mock_instrument import ExternalMockInstrumentClient

log = logging.getLogger(__name__)

_MOCK_BASE_TEMPS: tuple[float, ...] = (4.2, 4.8, 77.0, 77.5, 4.5, 4.1, 3.9, 300.0)

_RDGST_FAULT_BITS: tuple[tuple[int, InstrumentStatusFaultReason], ...] = (
    (1, InstrumentStatusFaultReason.INVALID_READING),
    (16, InstrumentStatusFaultReason.TEMPERATURE_UNDER_RANGE),
    (32, InstrumentStatusFaultReason.TEMPERATURE_OVER_RANGE),
    (64, InstrumentStatusFaultReason.SENSOR_UNITS_OVER_RANGE),
    (128, InstrumentStatusFaultReason.SENSOR_UNITS_ZERO),
)
_RDGST_KNOWN_MASK = sum(bit for bit, _reason in _RDGST_FAULT_BITS)


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
        connect_timeout_s: float = 3.0,
        read_timeout_s: float = 3.0,
        mock_instrument_client: ExternalMockInstrumentClient | None = None,
    ) -> None:
        super().__init__(name, mock=mock)
        for label, value in (
            ("connect_timeout_s", connect_timeout_s),
            ("read_timeout_s", read_timeout_s),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{label} must be a finite positive number")
        self._resource_str = resource_str
        self._channel_labels: dict[int, str] = channel_labels or {}
        self._transport = GPIBTransport(mock=mock)
        self._connect_timeout_s = float(connect_timeout_s)
        self._read_timeout_s = float(read_timeout_s)
        self._instrument_id: str = ""
        self._calibration_store = calibration_store
        if not mock and mock_instrument_client is not None:
            raise ValueError("mock_instrument_client is available only in mock mode")
        self._mock_instrument_client = mock_instrument_client
        self._runtime_warning_cache: set[tuple[str, str]] = set()
        self._use_per_channel_krdg: bool = False
        self._use_per_channel_srdg: bool = False
        self._krdg0_fail_count: int = 0
        self._srdg0_fail_count: int = 0
        self._krdg_batch_retry_interval_s: float = 60.0
        self._srdg_batch_retry_interval_s: float = 60.0
        self._krdg_last_batch_retry: float = 0.0
        self._srdg_last_batch_retry: float = 0.0

    async def connect(self) -> None:
        try:
            await self._connect_impl()
        except asyncio.CancelledError:
            await asyncio.shield(self.abort_connect())
            raise

    async def _connect_impl(self) -> None:
        log.info("%s: connecting to %s", self.name, self._resource_str)
        await self._transport.open(
            self._resource_str,
            timeout_ms=max(1, int(round(self._read_timeout_s * 1000))),
        )

        # Release a sticky query quarantine before anything is asked of the
        # device.
        #
        # A desynchronized query quarantines the session permanently, and
        # neither close/open nor clear_bus() releases it -- clear_bus sends the
        # SDC but never touches the flag. Every subsequent query then failed
        # with "GPIB session is quarantined", so one desynchronized read killed
        # the instrument until the process restarted. On 2026-09-01 that cost
        # 6.8 hours of LS218_2 and 2.0 more that afternoon, while the scheduler
        # wrote timeout rows that kept the row count at 100%.
        #
        # recover_device() is SDC-scoped and raises on failure, so a recovery
        # that cannot be trusted fails the connect and is retried under backoff
        # rather than being mistaken for success.
        # `is True` on purpose. The real transport returns a bool; a test
        # double is often a MagicMock whose every attribute is truthy, and
        # treating that as a quarantine would drive recovery on transports that
        # have none. Only an explicit quarantine triggers this path.
        if getattr(self._transport, "query_desynchronized", False) is True:
            log.warning("%s: session quarantined; attempting device-local recovery", self.name)
            await self._transport.recover_device()

        if not self.mock or self._mock_instrument_client is not None:
            # Phase 2c F.1: validate IDN with retry-after-clear fallback.
            # The previous fallback (log a warning and proceed) allowed silent
            # mis-routing to a wrong GPIB address — KRDG? would still produce
            # numbers, just from the wrong instrument.
            idn_valid = False
            idn_raw = ""
            idn_timeout_ms = max(1, int(round(self._connect_timeout_s * 1000)))

            for attempt in range(2):  # initial + one retry after device clear
                try:
                    idn_raw = (await self._query("*IDN?", timeout_ms=idn_timeout_ms)).strip()
                except Exception as exc:
                    log.warning(
                        "%s: *IDN? query failed (attempt %d/2): %s",
                        self.name,
                        attempt + 1,
                        exc,
                    )
                    idn_raw = ""

                upper = idn_raw.upper()
                if idn_raw and "LSCI" in upper and "218" in upper:
                    idn_valid = True
                    self._instrument_id = idn_raw
                    log.info("%s: IDN verified: %s", self.name, idn_raw)
                    break

                if attempt == 0:
                    # Try a Selected Device Clear before the second attempt.
                    log.warning(
                        "%s: IDN validation failed (response=%r), issuing GPIB clear and retrying",
                        self.name,
                        idn_raw,
                    )
                    try:
                        await self._transport.clear_bus()
                    except Exception as clear_exc:
                        log.warning(
                            "%s: clear_bus before IDN retry failed: %s",
                            self.name,
                            clear_exc,
                        )
                    await asyncio.sleep(0.2)

            if not idn_valid:
                # The identity check is what stands between a recovered bus and
                # a misattributed reading: a late reply to the query that
                # failed, or a response from the wrong address, both arrive
                # here as a non-identity. Re-quarantine before closing so the
                # session can never be reused on the strength of this attempt.
                self._transport.mark_desynchronized(
                    f"identity not validated after recovery (response={idn_raw!r})"
                )
                await self._transport.close()
                raise RuntimeError(
                    f"{self.name}: LakeShore 218S IDN validation failed. "
                    f"Expected 'LSCI,MODEL218...', got {idn_raw!r}. "
                    f"Check GPIB address and cabling."
                )

        self._connected = True
        self._use_per_channel_krdg = False
        self._use_per_channel_srdg = False
        self._krdg0_fail_count = 0
        self._srdg0_fail_count = 0
        log.info("%s: connected", self.name)

    async def disconnect(self) -> None:
        await self._transport.close()
        self._connected = False

    async def abort_connect(self) -> None:
        """Settle partial transport ownership before connection truth commits."""

        await self._transport.abort_open()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument is not connected")

        acquisition_started_at = _time.time()
        acquisition_started_monotonic = _time.monotonic()
        runtime_policies = self._runtime_channel_policies()
        if not runtime_policies:
            readings = await self._read_krdg_channels()
        else:
            temperature_readings = await self._read_krdg_channels()
            needs_curve = any(policy.get("reading_mode") == "curve" for policy in runtime_policies.values())
            raw_readings = await self.read_srdg_channels() if needs_curve else []
            readings = self._merge_runtime_readings(temperature_readings, raw_readings, runtime_policies)

        status_reason: str | None = None
        try:
            status_by_channel = await self.read_status()
        except Exception as exc:
            status_by_channel = {}
            status_reason = str(exc) or type(exc).__name__
            log.debug("%s: RDGST? acquisition failed: %s", self.name, exc)
        readings = [
            self._with_instrument_status(
                reading,
                status_by_channel=status_by_channel,
                unavailable_reason=status_reason,
            )
            for reading in readings
        ]

        for reading in readings:
            reading.metadata["acquisition_started_at"] = acquisition_started_at
            reading.metadata["acquisition_started_monotonic"] = acquisition_started_monotonic
        return readings

    def _with_instrument_status(
        self,
        reading: Reading,
        *,
        status_by_channel: dict[int, int],
        unavailable_reason: str | None,
    ) -> Reading:
        channel_num = reading.metadata.get("raw_channel")
        metadata = dict(reading.metadata)
        if type(channel_num) is not int:
            return reading
        bitmap = status_by_channel.get(channel_num)
        if type(bitmap) is not int or not 0 <= bitmap <= 255:
            metadata["sensor_status_availability"] = {
                "available": False,
                "stale": False,
                "reason": unavailable_reason or f"RDGST? unavailable for channel {channel_num}",
            }
            return replace(reading, metadata=metadata)

        metadata["sensor_status"] = bitmap
        metadata["sensor_status_availability"] = {
            "available": True,
            "stale": False,
            "reason": None,
        }
        if bitmap == 0:
            return replace(reading, metadata=metadata)

        reasons = [reason.value for bit, reason in _RDGST_FAULT_BITS if bitmap & bit]
        if reasons and bitmap & ~_RDGST_KNOWN_MASK == 0:
            # An exact advisory requires the entire bitmap to be understood.
            # Reserved/future bits retain the failed observation but carry no
            # exact fault reasons, so the generic dead-channel path stays
            # fail-closed even when documented bits are also present.
            metadata[INSTRUMENT_STATUS_REGISTER_KEY] = LAKESHORE_218_RDGST_REGISTER
            metadata[INSTRUMENT_STATUS_FAULT_REASONS_KEY] = reasons
        if bitmap & 32 and not bitmap & 16:
            status = ChannelStatus.OVERRANGE
        elif bitmap & 16 and not bitmap & 32:
            status = ChannelStatus.UNDERRANGE
        else:
            status = ChannelStatus.SENSOR_ERROR
        return replace(
            reading,
            value=float("nan"),
            status=status,
            raw=None,
            metadata=metadata,
        )

    async def _query(self, command: str, timeout_ms: int | None = None) -> str:
        if self._mock_instrument_client is not None:
            if timeout_ms is None:
                timeout_ms = max(1, int(round(self._read_timeout_s * 1000)))
            return await self._mock_instrument_client.query(command, timeout_ms=timeout_ms)
        return await self._transport.query(command, timeout_ms=timeout_ms)

    def failure_readings(self) -> list[Reading]:
        """Represent a failed whole-instrument poll for every temperature channel.

        The configured channel inventory makes this pure object construction,
        not a second transport operation. Scheduler persists and publishes the
        samples through its ordinary path, so interlocks see GPIB failure as
        non-usable measurements instead of silence.

        For ``LS218_2`` the roster intentionally includes the mandatory T11/T12
        critical inputs. One whole-poll TIMEOUT therefore remains direct
        SafetyBroker evidence and latches the stronger critical-input fault
        without waiting for InterlockEngine's multi-sample debounce. Suppressing
        those two genuine sensor failures would weaken the existing safety policy.
        """
        return [
            Reading.now(
                self._channel_labels.get(index, f"CH{index}"),
                float("nan"),
                "K",
                instrument_id=self.name,
                status=ChannelStatus.TIMEOUT,
                metadata={
                    "raw_channel": index,
                    "reading_kind": "temperature",
                    "scheduler_failure": "whole_poll",
                },
            )
            for index in range(1, 9)
        ]

    async def _read_krdg_channels(self) -> list[Reading]:
        if self.mock and self._mock_instrument_client is None:
            return self._mock_readings()

        if self._use_per_channel_krdg:
            return await self._read_krdg_per_channel()

        raw_response = await self._query("KRDG?")
        log.debug("%s: KRDG? -> %s", self.name, raw_response)
        readings = self._parse_response(raw_response, unit="K", reading_kind="temperature")
        if len(readings) < 8:
            self._krdg0_fail_count += 1
            log.warning(
                "%s: KRDG? returned %d values (expected 8), fallback #%d",
                self.name,
                len(readings),
                self._krdg0_fail_count,
            )
            if self._krdg0_fail_count >= 3:
                self._use_per_channel_krdg = True
                log.warning(
                    "%s: KRDG? failed %d times, switching to per-channel mode permanently",
                    self.name,
                    self._krdg0_fail_count,
                )
            return await self._read_krdg_per_channel()
        self._krdg0_fail_count = 0
        return readings

    async def _read_krdg_per_channel(self) -> list[Reading]:
        """Fallback: query each channel individually (KRDG? 1 .. KRDG? 8).

        Periodically retries batch KRDG? to recover from transient failures.
        """

        now = _time.monotonic()
        if now - self._krdg_last_batch_retry >= self._krdg_batch_retry_interval_s:
            self._krdg_last_batch_retry = now
            try:
                raw = await self._query("KRDG?")
                readings = self._parse_response(raw, unit="K", reading_kind="temperature")
                if len(readings) >= 8:
                    log.info(
                        "%s: KRDG? batch mode recovered — switching back from per-channel",
                        self.name,
                    )
                    self._use_per_channel_krdg = False
                    self._krdg0_fail_count = 0
                    return readings
            except Exception:
                pass  # Stay in per-channel mode

        readings: list[Reading] = []
        for ch in range(1, 9):
            try:
                raw = await self._query(f"KRDG? {ch}")
                parsed = self._parse_response(raw, unit="K", reading_kind="temperature")
                if parsed:
                    # Fix channel index — _parse_response starts at 1 for first token
                    reading = parsed[0]
                    channel_name = self._channel_labels.get(ch, f"CH{ch}")
                    readings.append(
                        Reading.now(
                            channel=channel_name,
                            value=reading.value,
                            unit=reading.unit,
                            instrument_id=self.name,
                            status=reading.status,
                            raw=reading.raw,
                            metadata={"raw_channel": ch, "reading_kind": "temperature"},
                        )
                    )
            except Exception as exc:
                log.error("%s: KRDG? %d failed: %s", self.name, ch, exc)
                channel_name = self._channel_labels.get(ch, f"CH{ch}")
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("nan"),
                        unit="K",
                        instrument_id=self.name,
                        status=ChannelStatus.SENSOR_ERROR,
                        raw=None,
                        metadata={"raw_channel": ch, "reading_kind": "temperature"},
                    )
                )
        return readings

    async def read_srdg_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument is not connected")
        if self.mock and self._mock_instrument_client is None:
            return self._mock_sensor_readings()

        if self._use_per_channel_srdg:
            return await self._read_srdg_per_channel()

        raw_response = await self._query("SRDG?")
        log.debug("%s: SRDG? -> %s", self.name, raw_response)
        readings = self._parse_response(raw_response, unit="sensor_unit", reading_kind="raw_sensor")
        if len(readings) < 8:
            self._srdg0_fail_count += 1
            log.warning(
                "%s: SRDG? returned %d values (expected 8), fallback #%d",
                self.name,
                len(readings),
                self._srdg0_fail_count,
            )
            if self._srdg0_fail_count >= 3:
                self._use_per_channel_srdg = True
                log.warning(
                    "%s: SRDG? failed %d times, switching to per-channel mode permanently",
                    self.name,
                    self._srdg0_fail_count,
                )
            return await self._read_srdg_per_channel()
        self._srdg0_fail_count = 0
        return readings

    async def _read_srdg_per_channel(self) -> list[Reading]:
        """Fallback: query each channel individually (SRDG? 1 .. SRDG? 8).

        Periodically retries batch SRDG? to recover from transient failures.
        """

        now = _time.monotonic()
        if now - self._srdg_last_batch_retry >= self._srdg_batch_retry_interval_s:
            self._srdg_last_batch_retry = now
            try:
                raw = await self._query("SRDG?")
                readings = self._parse_response(raw, unit="sensor_unit", reading_kind="raw_sensor")
                if len(readings) >= 8:
                    log.info(
                        "%s: SRDG? batch mode recovered — switching back from per-channel",
                        self.name,
                    )
                    self._use_per_channel_srdg = False
                    self._srdg0_fail_count = 0
                    return readings
            except Exception:
                pass

        readings: list[Reading] = []
        for ch in range(1, 9):
            try:
                raw = await self._query(f"SRDG? {ch}")
                parsed = self._parse_response(raw, unit="sensor_unit", reading_kind="raw_sensor")
                if parsed:
                    reading = parsed[0]
                    channel_name = self._channel_labels.get(ch, f"CH{ch}")
                    readings.append(
                        Reading.now(
                            channel=channel_name,
                            value=reading.value,
                            unit=reading.unit,
                            instrument_id=self.name,
                            status=reading.status,
                            raw=reading.raw,
                            metadata={"raw_channel": ch, "reading_kind": "raw_sensor"},
                        )
                    )
            except Exception as exc:
                log.error("%s: SRDG? %d failed: %s", self.name, ch, exc)
                channel_name = self._channel_labels.get(ch, f"CH{ch}")
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("nan"),
                        unit="sensor_unit",
                        instrument_id=self.name,
                        status=ChannelStatus.SENSOR_ERROR,
                        raw=None,
                        metadata={"raw_channel": ch, "reading_kind": "raw_sensor"},
                    )
                )
        return readings

    async def read_status(self) -> dict[int, int]:
        """Query RDGST? for all channels. Returns {channel_num: status_bitmap}.

        Bitmap bits: 0=invalid, 4=T_under, 5=T_over, 6=sensor_overrange, 7=sensor_zero.
        Called for every temperature acquisition so the status describes that
        reading cycle.  An unavailable channel is returned as ``-1`` and is
        treated as unknown, never as affirmative fault evidence.
        """
        if self.mock and self._mock_instrument_client is None:
            return {ch: 0 for ch in range(1, 9)}
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument is not connected")
        result: dict[int, int] = {}
        for ch in range(1, 9):
            try:
                raw = await self._query(f"RDGST? {ch}")
                result[ch] = int(raw.strip())
            except Exception as exc:
                log.warning("%s: RDGST? %d failed: %s", self.name, ch, exc)
                result[ch] = -1
        return result

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
            if resolution.get("reading_mode") != "curve" and reason not in {
                "global_off",
                "channel_off",
                "missing_assignment",
                "",
            }:
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

            # CR-1: never evaluate a raw outside the calibrated span — the curve
            # clips it to the boundary, freezing the published temperature
            # (dT/dt -> 0) and blinding the SafetyManager rate fault. Fall back
            # to the native KRDG reading instead.
            try:
                raw_in_range = self._calibration_store.raw_in_range(sensor_id, float(raw_reading.value))  # type: ignore[union-attr]
            except Exception:
                raw_in_range = False
            if not raw_in_range:
                self._log_runtime_fallback(
                    channel_key=str(policy.get("channel_key", "")),
                    reason="raw_out_of_cal_range",
                )
                merged.append(
                    self._with_runtime_metadata(
                        reading,
                        reading_mode="krdg",
                        raw_source="KRDG",
                        curve_id=assignment.get("curve_id"),
                        sensor_id=assignment.get("sensor_id"),
                        runtime_reason="raw_out_of_cal_range",
                    )
                )
                continue

            try:
                calibrated_value = self._calibration_store.evaluate(sensor_id, float(raw_reading.value))  # type: ignore[union-attr]
            except Exception:
                self._log_runtime_fallback(
                    channel_key=str(policy.get("channel_key", "")), reason="curve_evaluate_failed"
                )
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
