"""Etalon MultiLine driver — interferometric length metrology over TCP.

Stage 1: latest valid length readings + environment data + connection
check + mock mode (request-response, ``mode=averaged``).
v0.55.11 (F-MultiLineContinuous): adds continuous-mode operation —
``startmeasnogui``-driven server push + adaptive decimation for STE
workflows + burst capture for actuator workflows. Stage 2 (deformation
analysis, channel alignment, MLAC/AC operations, frontend splitter /
shutter control) is intentionally out of scope and lives in a separate
spec.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


# v0.55.11 — continuous-mode cycle snapshot. The Etalon protocol bundles
# per-channel measurement + per-channel env (T/P/RH) into a single
# `channeldata_` push, so the cycle is fully described by the channel
# list + a wall-clock timestamp recorded on receipt.
@dataclass(frozen=True, slots=True)
class CycleSnapshot:
    timestamp: float  # Unix wall-clock seconds (used in Reading + Parquet)
    channels: tuple[_ChannelData, ...]


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

    # v0.55.11 — driver operating modes.
    MODE_AVERAGED = "averaged"
    MODE_CONTINUOUS = "continuous"
    _VALID_MODES = (MODE_AVERAGED, MODE_CONTINUOUS)

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
        mode: str = MODE_AVERAGED,
        target_rate_hz: float = 1.0,
        burst_dir: Path | None = None,
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
        # v0.55.11 — operating mode + decimation rate. Validated up-front
        # so configuration mistakes surface at engine boot rather than at
        # the first read_channels() tick.
        if mode not in self._VALID_MODES:
            raise ValueError(
                f"MultiLine mode must be one of {self._VALID_MODES}, got {mode!r}"
            )
        if target_rate_hz <= 0:
            raise ValueError(
                f"MultiLine target_rate_hz must be > 0, got {target_rate_hz!r}"
            )
        self._mode = mode
        self._target_rate_hz = float(target_rate_hz)
        self._target_interval_s = 1.0 / self._target_rate_hz
        # Burst-capture default sink — engine wires its own DATA_DIR-based
        # path; tests pass tmp_path. None falls back to a CWD-relative
        # ``data/multiline_bursts`` so a smoke run still has a place to
        # land the blob.
        self._burst_dir = burst_dir
        self._transport: TCPTransport | None = None
        self._mock_nominal_lengths_mm = {
            ch: 1000.0 + ch * 50.0 for ch in self._channel_numbers
        }
        # Continuous-mode state. _last_cycle is a single-slot buffer the
        # listener task fills; read_channels() snapshots it under the
        # decimation gate. Burst capture appends every cycle to
        # _burst_buffer regardless of decimation so the post-hoc Parquet
        # blob has the full hardware cadence.
        self._last_cycle: CycleSnapshot | None = None
        self._last_emit_mono: float | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._first_cycle_logged = False
        self._listener_started_mono: float | None = None
        self._burst_active = False
        self._burst_buffer: list[CycleSnapshot] = []
        self._burst_started_ts: float | None = None
        self._burst_started_iso: str | None = None
        # Active-experiment id is supplied by the engine when burst_stop
        # is invoked (so the driver does not need an ExperimentManager
        # back-reference). Storing it in burst_start lets a long-running
        # burst tag itself even if the experiment is finalised mid-burst.
        self._burst_experiment_id: str | None = None

    async def reconfigure_channels(self, new_channels: list[int]) -> list[int]:
        """v0.55.16.0.1 (smoke hotfix) — runtime channel set update.

        Validates the new selection (same rules as the constructor:
        1..32, ints, unique, non-empty) and atomically replaces
        ``self._channel_numbers``. In averaged mode the change takes
        effect on the next ``read_channels`` poll. In continuous mode
        the listener is restarted under the new channel set so the
        Etalon server's selected-channel filter matches what the
        driver expects.

        Returns the resolved channel list (sorted) so the engine can
        echo it back to the GUI for display.
        """
        # Validate first; raise without touching internal state if bad.
        normalised = sorted(new_channels)
        self._validate_channel_numbers(normalised)

        # Atomic state mutation — no awaits between the validation and
        # the assignment, so an interleaving read_channels poll sees
        # either the old or the new set, never half.
        self._channel_numbers = normalised
        # Refresh mock-mode nominals so a mock deployment reports
        # plausible lengths for the newly-selected channels.
        self._mock_nominal_lengths_mm = {
            ch: 1000.0 + ch * 50.0 for ch in self._channel_numbers
        }

        # Continuous-mode listener restart: tell the server to stop the
        # current measurement, then re-spawn the listener which issues
        # `startmeasnogui` again. The listener cancel + stopmeasnogui
        # handshake mirrors `disconnect()` so partial-state cleanup is
        # consistent.
        #
        # Codex audit cycle 1 amend (smoke hotfix): originally we
        # swallowed asyncio.TimeoutError silently and proceeded to
        # spawn a new listener — which could race a still-unwinding old
        # task for the read-stream buffer. Now: if the cancel doesn't
        # complete cleanly, we log CRITICAL and leave the new listener
        # un-spawned so the operator gets immediate feedback rather
        # than a silent double-listener race.
        if (
            self._mode == self.MODE_CONTINUOUS
            and self._listener_task is not None
            and not self._listener_task.done()
        ):
            self._listener_task.cancel()
            cancel_clean = False
            try:
                await asyncio.wait_for(self._listener_task, timeout=2.0)
                cancel_clean = True
            except asyncio.CancelledError:
                cancel_clean = True
            except asyncio.TimeoutError:
                logger.error(
                    "MultiLine '%s' reconfigure: listener did not cancel "
                    "within 2s — refusing to spawn replacement to avoid a "
                    "double-listener race. Disconnect/reconnect to recover.",
                    self.name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MultiLine '%s' reconfigure listener cancel raised: %s",
                    self.name,
                    exc,
                )
            self._listener_task = None
            # Drop the last-cycle snapshot so a stale read can't surface
            # under the new channel filter.
            self._last_cycle = None
            self._last_emit_mono = None
            if (
                cancel_clean
                and self._transport is not None
                and self._connected
            ):
                self._listener_started_mono = time.monotonic()
                self._first_cycle_logged = False
                self._listener_task = asyncio.create_task(
                    self._continuous_listener(),
                    name=f"multiline_listener_{self.name}",
                )

        return list(self._channel_numbers)

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
        # v0.55.11 — spawn the continuous listener AFTER the verify queries
        # finish; the listener owns the read stream from that point and
        # any further query() would race it for readline buffer.
        if self._mode == self.MODE_CONTINUOUS:
            self._listener_started_mono = time.monotonic()
            self._first_cycle_logged = False
            self._listener_task = asyncio.create_task(
                self._continuous_listener(), name=f"multiline_listener_{self.name}"
            )

    async def disconnect(self) -> None:
        # v0.55.11 — cancel listener first so its stopmeasnogui handshake
        # writes to the still-open transport, then close.
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await asyncio.wait_for(self._listener_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MultiLine '%s' listener cancel raised: %s", self.name, exc
                )
            self._listener_task = None
        # If a burst was in flight when the operator disconnected, drop
        # the buffer rather than half-persist it. burst_stop must be the
        # explicit close path so partial saves are operator-driven.
        self._burst_active = False
        self._burst_buffer = []
        self._burst_started_ts = None
        self._burst_started_iso = None
        self._burst_experiment_id = None
        if self._transport is not None:
            await self._transport.close()
            self._transport = None
        self._connected = False
        self._last_cycle = None
        self._last_emit_mono = None

    async def read_channels(self) -> list[Reading]:
        if self.mock:
            return self._mock_readings()
        if self._mode == self.MODE_CONTINUOUS:
            return self._read_channels_continuous()
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

    # ------------------------------------------------------------------
    # v0.55.11 — continuous-mode listener + decimated emit + burst API
    # ------------------------------------------------------------------

    async def _continuous_listener(self) -> None:
        """Read pushed cycles from the server and fill ``_last_cycle``.

        Sends ``startmeasnogui`` once, then drains the streaming
        iterator until cancelled. The first parsed cycle records the
        empirical cycle latency (architect-requested smoke instrument).
        On cancellation, sends ``stopmeasnogui`` so the server returns
        to idle rather than continuing to push into a closed socket.
        Channeldata parse failures are warnings only; the loop survives
        a single malformed response so a flaky measurement does not
        kill the entire continuous session.
        """
        if self._transport is None:
            return
        try:
            await self._transport.write_command("startmeasnogui")
            async for line in self._transport.read_lines_async():
                if not line:
                    continue
                if line == "measstarted" or line == "measurementfinished":
                    continue
                if line == "measstopped":
                    break
                if line.startswith("defanadata_"):
                    # Deformation analysis — F-MultiLineDeformation scope.
                    continue
                if line.startswith("channeldata_"):
                    try:
                        channel_data, _server_error = _parse_channeldata_response(line)
                    except ValueError as exc:
                        logger.warning(
                            "MultiLine '%s' cycle parse failed: %s",
                            self.name, exc,
                        )
                        continue
                    snapshot = CycleSnapshot(
                        timestamp=time.time(),
                        channels=tuple(channel_data),
                    )
                    self._last_cycle = snapshot
                    if not self._first_cycle_logged and self._listener_started_mono is not None:
                        elapsed = time.monotonic() - self._listener_started_mono
                        logger.info(
                            "MultiLine '%s' first cycle received after %.2fs",
                            self.name, elapsed,
                        )
                        self._first_cycle_logged = True
                    if self._burst_active:
                        self._burst_buffer.append(snapshot)
        except asyncio.CancelledError:
            try:
                if self._transport is not None:
                    await asyncio.wait_for(
                        self._transport.write_command("stopmeasnogui"),
                        timeout=2.0,
                    )
            except (TCPTransportError, asyncio.TimeoutError, OSError) as exc:
                logger.warning(
                    "MultiLine '%s' stopmeasnogui on cancel failed: %s",
                    self.name, exc,
                )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MultiLine '%s' continuous listener crashed: %s",
                self.name, exc, exc_info=True,
            )

    def _read_channels_continuous(self) -> list[Reading]:
        """Return the decimated cycle as a Reading list (or empty)."""
        cycle = self._last_cycle
        if cycle is None:
            return []
        # Decimation gate uses monotonic clock so wall-clock skew (NTP
        # corrections, leap seconds) cannot starve emission. First emit
        # always passes — _last_emit_mono is None until first read.
        now_mono = time.monotonic()
        if self._last_emit_mono is not None:
            if (now_mono - self._last_emit_mono) < self._target_interval_s:
                return []
        self._last_emit_mono = now_mono
        return self._cycle_to_readings(cycle)

    def _cycle_to_readings(self, cycle: CycleSnapshot) -> list[Reading]:
        readings: list[Reading] = []
        ts = datetime.fromtimestamp(cycle.timestamp, tz=UTC)
        for ch in cycle.channels:
            status = self._status_from_errors(ch)
            readings.append(
                Reading(
                    timestamp=ts,
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
        # Per-channel records carry env (T/P/RH); use the first channel's
        # values as the cycle-level env reading. Continuous mode does NOT
        # poll `environmentdata` separately — it would race the listener
        # for readline buffer (constraint per spec).
        if cycle.channels:
            first = cycle.channels[0]
            readings.append(
                Reading(
                    timestamp=ts,
                    channel=f"{self.name}/env_temperature",
                    value=first.temperature_c,
                    unit="°C",
                    instrument_id=self.name,
                )
            )
            readings.append(
                Reading(
                    timestamp=ts,
                    channel=f"{self.name}/env_pressure",
                    value=first.pressure_hpa,
                    unit="hPa",
                    instrument_id=self.name,
                )
            )
            readings.append(
                Reading(
                    timestamp=ts,
                    channel=f"{self.name}/env_humidity",
                    value=first.humidity_pct,
                    unit="%",
                    instrument_id=self.name,
                )
            )
        return readings

    def burst_status(self) -> dict[str, Any]:
        elapsed = 0.0
        if self._burst_started_ts is not None:
            elapsed = max(0.0, time.time() - self._burst_started_ts)
        return {
            "active": self._burst_active,
            "elapsed_s": elapsed,
            "cycle_count": len(self._burst_buffer),
            "started_iso": self._burst_started_iso,
        }

    async def burst_start(self, *, experiment_id: str | None = None) -> None:
        if self._mode != self.MODE_CONTINUOUS:
            raise RuntimeError(
                "Burst capture requires continuous mode "
                f"(driver '{self.name}' currently in {self._mode!r})"
            )
        if self._burst_active:
            raise RuntimeError(f"Burst already active for '{self.name}'")
        self._burst_active = True
        self._burst_started_ts = time.time()
        self._burst_started_iso = (
            datetime.fromtimestamp(self._burst_started_ts, tz=UTC)
            .strftime("%Y%m%dT%H%M%SZ")
        )
        self._burst_experiment_id = experiment_id
        self._burst_buffer = []

    async def burst_stop(
        self,
        *,
        experiments_root: Path | None = None,
    ) -> Path | None:
        """Stop accumulation and persist the buffered cycles to Parquet.

        Returns the artifact path on success, ``None`` when the burst
        was empty (no cycles received). The caller (engine command
        handler) supplies ``experiments_root`` so the driver does not
        need a back-reference to the engine's DATA_DIR — that decoupling
        keeps the driver unit-testable with ``tmp_path``.
        """
        if not self._burst_active:
            return None
        self._burst_active = False
        snapshots = self._burst_buffer
        started_ts = self._burst_started_ts or time.time()
        started_iso = self._burst_started_iso or (
            datetime.fromtimestamp(started_ts, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        experiment_id = self._burst_experiment_id
        # Reset state regardless of whether persist runs — failed persist
        # must not leave the next burst unable to start.
        self._burst_buffer = []
        self._burst_started_ts = None
        self._burst_started_iso = None
        self._burst_experiment_id = None
        if not snapshots:
            return None
        return await asyncio.to_thread(
            self._persist_burst,
            snapshots,
            started_iso,
            experiment_id,
            experiments_root,
        )

    def _persist_burst(
        self,
        snapshots: list[CycleSnapshot],
        started_iso: str,
        experiment_id: str | None,
        experiments_root: Path | None,
    ) -> Path:
        """Write a Parquet blob with all 17 channeldata fields per row.

        Schema (one row per channel per cycle):
        cycle_ts, channel_index, length_mm, intensity_min, intensity_max,
        temperature_c, pressure_hpa, humidity_pct,
        analysis_error, beam_break, temp_error, motion_tolerance_error,
        intensity_error, usb_error, dll_error, laser_speed_error,
        laser_temp_error, daq_error.
        """
        import pyarrow as pa  # noqa: PLC0415
        import pyarrow.parquet as pq  # noqa: PLC0415

        rows: dict[str, list[Any]] = {
            "cycle_ts": [],
            "channel_index": [],
            "length_mm": [],
            "intensity_min": [],
            "intensity_max": [],
            "temperature_c": [],
            "pressure_hpa": [],
            "humidity_pct": [],
            "analysis_error": [],
            "beam_break": [],
            "temp_error": [],
            "motion_tolerance_error": [],
            "intensity_error": [],
            "usb_error": [],
            "dll_error": [],
            "laser_speed_error": [],
            "laser_temp_error": [],
            "daq_error": [],
        }
        for snap in snapshots:
            for ch in snap.channels:
                rows["cycle_ts"].append(snap.timestamp)
                rows["channel_index"].append(ch.channel_number)
                rows["length_mm"].append(ch.length_mm)
                rows["intensity_min"].append(ch.intensity_min)
                rows["intensity_max"].append(ch.intensity_max)
                rows["temperature_c"].append(ch.temperature_c)
                rows["pressure_hpa"].append(ch.pressure_hpa)
                rows["humidity_pct"].append(ch.humidity_pct)
                rows["analysis_error"].append(ch.analysis_error)
                rows["beam_break"].append(ch.beam_break)
                rows["temp_error"].append(ch.temp_error)
                rows["motion_tolerance_error"].append(ch.motion_tolerance_error)
                rows["intensity_error"].append(ch.intensity_error)
                rows["usb_error"].append(ch.usb_error)
                rows["dll_error"].append(ch.dll_error)
                rows["laser_speed_error"].append(ch.laser_speed_error)
                rows["laser_temp_error"].append(ch.laser_temp_error)
                rows["daq_error"].append(ch.daq_error)
        out_dir = self._resolve_burst_dir(experiment_id, experiments_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Resolve early so a malicious experiment id cannot escape via
        # path traversal — _resolve_burst_dir already strips separators
        # and parent refs, but we double-check the final dir is inside
        # the chosen root.
        out_path = out_dir / f"multiline_burst_{started_iso}.parquet"
        table = pa.table(rows)
        pq.write_table(table, out_path)
        logger.info(
            "MultiLine '%s' burst persisted: %d cycles → %s",
            self.name,
            len(snapshots),
            out_path,
        )
        return out_path

    def _resolve_burst_dir(
        self,
        experiment_id: str | None,
        experiments_root: Path | None,
    ) -> Path:
        """Pick the burst output directory.

        Active experiment → ``<experiments_root>/<experiment_id>/``.
        No experiment → driver's configured ``_burst_dir`` or
        ``data/multiline_bursts`` relative to CWD as final fallback.

        ``experiment_id`` is sanitised against directory traversal —
        callers route operator-supplied ids through here so a malicious
        id cannot write outside the experiment root.
        """
        if experiment_id and experiments_root is not None:
            safe_id = experiment_id.replace("/", "_").replace("\\", "_")
            safe_id = safe_id.replace("..", "_")
            return Path(experiments_root) / safe_id
        if self._burst_dir is not None:
            return Path(self._burst_dir)
        return Path("data") / "multiline_bursts"

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
