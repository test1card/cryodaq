"""Keithley 2604B driver with dual-channel runtime support.

P=const control runs host-side in read_channels(). The optional TSP v3 script
only checks a late pet; it does not regulate and is not autonomous.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from cryodaq.core.smu_channel import SMU_CHANNELS, SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.usbtmc import USBTMCTransport

log = logging.getLogger(__name__)


class OutputStateUnverifiedError(RuntimeError):
    """Raised when an OUTPUT_OFF could not be readback-verified.

    The SMU output state is UNVERIFIED — it may still be sourcing. Callers
    (SafetyManager) must fail CLOSED and latch a fault rather than report a
    clean SAFE_OFF.
    """


# Minimum measurable current for resistance calculation (avoid division by noise).
# At 1 nA, R = V/I is dominated by noise.  For heaters with R ~ 10–1000 Ω,
# 100 nA gives R accurate to ~1%.
_I_MIN_A = 1e-7

# Maximum voltage change per poll cycle (slew rate limit).
# Prevents target_v from jumping from 0 to V_compliance in one step when
# resistance changes abruptly (superconducting transition, wire break).
MAX_DELTA_V_PER_STEP = 0.5  # V — do not increase without thermal analysis

# Number of consecutive compliance cycles before notifying SafetyManager.
_COMPLIANCE_NOTIFY_THRESHOLD = 10

# TSP os.time() has one-second granularity. Sub-second deadlines are therefore
# misleading, while an excessively long late-pet window defeats its diagnostic
# purpose. The upper bound is deliberately generous for slow lab setups.
_WDOG_TIMEOUT_MIN_S = 1.0
_WDOG_TIMEOUT_MAX_S = 300.0

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

_OUTPUT_STATE_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_OUTPUT_STATE_MAX_CHARS = 64
_PROTOCOL_TRIM_CHARS = " \t\r\n"
_IDN_MAX_CHARS = 256
_IDN_VALUE_RE = re.compile(r"[A-Za-z0-9._-]+\Z")
_MOCK_IDN = "Keithley Instruments Inc., Model 2604B, MOCK00001, 3.0.0"
_OFF_CHALLENGE_PREFIX = "CRYODAQ_OFF_V1"
_OFF_CHALLENGE_NONCE_RE = re.compile(r"[0-9a-f]{32}\Z")
_OFF_CHALLENGE_MAX_CHARS = 96

# TSP software late-pet watchdog, gated on _wdog_enabled (default False).
# Version 3 is explicitly non-autonomous: it covers stall-then-recover only.
# See tsp/cryodaq_wdog.lua.
_WDOG_SCRIPT: str | None = None

# Version stamp the driver was written against. Must equal CRYODAQ_WDOG_VERSION
# in tsp/cryodaq_wdog.lua — the script is re-uploaded from repo tsp/ on every
# arm, so the host reads this back post-upload and refuses to arm on mismatch
# (catches a truncated or stale upload; firmware gets no CI).
_WDOG_SCRIPT_VERSION = 3


def _bounded_ascii_token(raw: str, *, field: str, max_chars: int = 64) -> str:
    """Return one bounded ASCII protocol token with transport whitespace removed."""

    if not isinstance(raw, str):
        raise ValueError(f"{field} response is not text")
    if not raw or len(raw) > max_chars:
        raise ValueError(f"{field} response length is outside 1..{max_chars}")
    if not raw.isascii():
        raise ValueError(f"{field} response is not ASCII")
    token = raw.strip(_PROTOCOL_TRIM_CHARS)
    if not token:
        raise ValueError(f"{field} response is empty")
    return token


def _parse_keithley_idn_family(raw: str, *, mock: bool) -> tuple[str, tuple[str, str, str, str]]:
    """Authorize 2604B-specific OFF commands without accepting full identity."""

    token = _bounded_ascii_token(raw, field="*IDN?", max_chars=_IDN_MAX_CHARS)
    if mock:
        if token != _MOCK_IDN:
            raise ValueError("mock *IDN? response does not match the exact simulator identity")

    fields = [field.strip(" \t") for field in token.split(",")]
    if len(fields) != 4:
        raise ValueError("*IDN? response must contain exactly four comma-separated fields")
    manufacturer, model, serial, firmware = fields
    if manufacturer.lower() != "keithley instruments inc.":
        raise ValueError("*IDN? manufacturer is not Keithley Instruments Inc.")
    if model.lower() != "model 2604b":
        raise ValueError("*IDN? model is not exactly 2604B")
    return token, (manufacturer, model, serial, firmware)


def _parse_keithley_idn(raw: str, *, mock: bool) -> str:
    """Validate one documented four-field Keithley 2604B identity response."""

    token, (_manufacturer, _model, serial, firmware) = _parse_keithley_idn_family(raw, mock=mock)
    if not serial or len(serial) > 64 or _IDN_VALUE_RE.fullmatch(serial) is None:
        raise ValueError("*IDN? serial field is empty, overlong, or malformed")
    if not mock and serial.upper().startswith("MOCK"):
        raise ValueError("mock identity is not valid for a physical connection")
    if not firmware or len(firmware) > 64 or _IDN_VALUE_RE.fullmatch(firmware) is None:
        raise ValueError("*IDN? firmware field is empty, overlong, or malformed")
    return token


def _parse_output_enabled(raw: str) -> bool:
    """Parse one exact Keithley output enum without coercing ambiguity to OFF."""

    token = _bounded_ascii_token(raw, field="output-state", max_chars=_OUTPUT_STATE_MAX_CHARS)
    try:
        if _OUTPUT_STATE_NUMBER_RE.fullmatch(token) is None:
            raise InvalidOperation
        value = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError(f"invalid output-state token {token!r}") from exc
    if not value.is_finite() or value not in (Decimal(0), Decimal(1)):
        raise ValueError(f"output-state token must be exactly 0 or 1, got {token!r}")
    return value == Decimal(1)


def _parse_output_off_challenge(raw: str, *, expected_nonce: str) -> bool:
    """Accept only the current nonce and literal OFF state in one response."""

    if _OFF_CHALLENGE_NONCE_RE.fullmatch(expected_nonce) is None:
        raise ValueError("OFF challenge nonce must be 32 lowercase hexadecimal characters")
    token = _bounded_ascii_token(
        raw,
        field="output-OFF challenge",
        max_chars=_OFF_CHALLENGE_MAX_CHARS,
    )
    fields = token.split("|")
    if len(fields) != 3:
        raise ValueError("output-OFF challenge must contain exactly three pipe-separated fields")
    prefix, nonce, state = fields
    if prefix != _OFF_CHALLENGE_PREFIX:
        raise ValueError("output-OFF challenge prefix does not match")
    if nonce != expected_nonce:
        raise ValueError("output-OFF challenge nonce is stale or does not match")
    return state == "0"


def _parse_compliance(raw: str) -> bool:
    """Parse the exact lowercase TSP boolean emitted by source.compliance."""

    token = _bounded_ascii_token(raw, field="source.compliance")
    if token == "true":
        return True
    if token == "false":
        return False
    raise ValueError(f"source.compliance must be literal 'true' or 'false', got {token!r}")


class _WatchdogArmError(RuntimeError):
    """Watchdog upload/activation integrity check failed.

    ``required`` also raises when the uploaded script does not report the
    literal autonomous contract bit ``1``. Version 3 intentionally reports 0,
    so it is usable only as a degraded late-pet check in ``best_effort`` mode.
    """


def _parse_wdog_version(raw: str, *, field: str) -> int:
    """Parse one canonical non-negative decimal integer version token."""

    token = _bounded_ascii_token(raw, field=field)
    if re.fullmatch(r"(?:0|[1-9][0-9]*)\Z", token) is None:
        raise ValueError(f"{field} readback is not a canonical integer: {token!r}")
    return int(token)


def _parse_wdog_flag(raw: str, *, field: str) -> bool:
    """Parse an exact TSP protocol flag: literal ASCII 0 or 1 only."""

    token = _bounded_ascii_token(raw, field=field)
    if token == "0":
        return False
    if token == "1":
        return True
    raise ValueError(f"{field} readback must be literal 0 or 1, got {token!r}")


def _parse_wdog_latch(raw: str) -> bool:
    """Parse pre-upload latch, admitting only explicit fresh-state sentinels."""
    token = _bounded_ascii_token(raw, field="cryodaq_wdog_tripped")
    if token == "nil":
        return False
    return _parse_wdog_flag(token, field="cryodaq_wdog_tripped")


def _validate_wdog_timeout_s(value: object) -> float:
    """Return a finite late-pet timeout within the supported safety range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("watchdog_timeout_s must be a real number, not a boolean or string")
    timeout_s = float(value)
    if not math.isfinite(timeout_s):
        raise ValueError("watchdog_timeout_s must be finite")
    if not (_WDOG_TIMEOUT_MIN_S <= timeout_s <= _WDOG_TIMEOUT_MAX_S):
        raise ValueError(
            f"watchdog_timeout_s must be between {_WDOG_TIMEOUT_MIN_S:g} and {_WDOG_TIMEOUT_MAX_S:g} seconds"
        )
    return timeout_s


class WatchdogMode(StrEnum):
    """Operator-selected TSP watchdog behaviour (config: keithley.watchdog.mode).

    - ``off``: no TSP watchdog; host SafetyManager is the sole authority.
      Zero ``cryodaq_wdog`` writes — the command stream is byte-identical.
    - ``best_effort``: activate the software late-pet check on connect; report
      the absence of autonomous host-death protection at CRITICAL severity.
      == legacy ``enabled: true``.
    - ``required``: fail-CLOSED unless the uploaded script explicitly reports
      an autonomous protection bit of literal 1. Version 3 reports 0, so the
      instrument stays unavailable and the SafetyManager holds SAFE_OFF. A
      read-back latched trip is NOT a failure: it is logged CRITICAL and armed
      over (outputs were already forced OFF; raising would only lock the
      operator out).
    """

    OFF = "off"
    BEST_EFFORT = "best_effort"
    REQUIRED = "required"


def _load_wdog_script() -> str:
    global _WDOG_SCRIPT
    if _WDOG_SCRIPT is None:
        from cryodaq.paths import get_tsp_dir

        _WDOG_SCRIPT = (get_tsp_dir() / "cryodaq_wdog.lua").read_text(encoding="utf-8")
    return _WDOG_SCRIPT


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
        watchdog_mode: str | WatchdogMode | None = None,
        watchdog_enabled: bool | None = None,
        watchdog_timeout_s: float = 5.0,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._transport = USBTMCTransport(mock=mock)
        self._instrument_id = ""
        # TSP late-pet watchdog plumbing (default OFF → byte-identical stream).
        # Explicit mode wins; else the deprecated ``watchdog_enabled`` alias
        # maps True→best_effort / False→off; else default off. Unknown mode
        # string raises ValueError (fail-closed config).
        if watchdog_mode is not None:
            self._wdog_mode = WatchdogMode(watchdog_mode)
        elif watchdog_enabled is not None:
            self._wdog_mode = WatchdogMode.BEST_EFFORT if watchdog_enabled else WatchdogMode.OFF
        else:
            self._wdog_mode = WatchdogMode.OFF
        self._wdog_enabled = self._wdog_mode is not WatchdogMode.OFF
        self._wdog_timeout_s = _validate_wdog_timeout_s(watchdog_timeout_s)
        self._wdog_armed = False
        # Separate truth bit: _wdog_armed means only that the software late-pet
        # check is active. It must never imply autonomous host-death coverage.
        self._wdog_autonomous = False
        # Host-side evidence bit survives a firmware trip or a pre-upload latch
        # read until explicit operator-authorized acknowledgment succeeds.
        self._wdog_trip_pending = False
        self._channels: dict[SmuChannel, ChannelRuntime] = {
            "smua": ChannelRuntime(channel="smua"),
            "smub": ChannelRuntime(channel="smub"),
        }
        # Slew rate state: last voltage actually written to each SMU channel.
        self._last_v: dict[SmuChannel, float] = {"smua": 0.0, "smub": 0.0}
        # Compliance tracking: consecutive cycles where SMU reports compliance.
        self._compliance_count: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
        self._mock_temp = _MOCK_T0
        # F2: set True when the crash-recovery force-OFF on connect() cannot be
        # readback-verified (outputs may still be ON). A blocking RUN
        # precondition in SafetyManager, cleared by a later verified OFF.
        self._unsafe_output_state = True
        # Connection-scoped evidence: only OFF readback collected in the
        # current connection generation may authorize transport teardown.
        self._connection_generation = 0
        self._connect_in_progress = False
        self._disconnect_in_progress = False
        self._source_command_epoch: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
        self._source_start_token: dict[SmuChannel, int | None] = {"smua": None, "smub": None}
        self._source_off_depth: dict[SmuChannel, int] = {"smua": 0, "smub": 0}
        self._source_regulation_epoch: dict[SmuChannel, int | None] = {
            "smua": None,
            "smub": None,
        }
        self._output_off_verified: dict[SmuChannel, bool] = {
            "smua": False,
            "smub": False,
        }
        self._output_off_verified_generation: dict[SmuChannel, int | None] = {
            "smua": None,
            "smub": None,
        }
        self._output_off_verified_epoch: dict[SmuChannel, int | None] = {
            "smua": None,
            "smub": None,
        }

    async def connect(self) -> None:
        if self._connected or self._connect_in_progress or self._disconnect_in_progress:
            raise RuntimeError(f"{self.name}: connect already active")
        if any(self._source_start_token.values()) or any(self._source_off_depth.values()):
            raise RuntimeError(f"{self.name}: source transition blocks connect")
        self._connect_in_progress = True
        self._instrument_id = ""
        log.info("%s: connecting to %s", self.name, self._resource_str)
        self._connection_generation += 1
        for smu_channel, runtime in self._channels.items():
            self._source_command_epoch[smu_channel] += 1
            self._source_start_token[smu_channel] = None
            runtime.active = False
            runtime.p_target = 0.0
            self._last_v[smu_channel] = 0.0
            self._compliance_count[smu_channel] = 0
        self._revoke_off_evidence()
        self._wdog_armed = False
        self._wdog_autonomous = False

        family_authorized = False
        accepted_identity: str | None = None
        try:
            await self._transport.open(self._resource_str)
            idn_raw = await self._transport.query("*IDN?")

            # Two-stage trust boundary: only an exact documented vendor/model
            # family authorizes TSP-specific recovery commands.  Serial and
            # firmware remain untrusted until every OFF attempt has settled.
            _parse_keithley_idn_family(idn_raw, mock=self.mock)
            family_authorized = True
            self._connected = True
            off_confirmed, pending_cancel = await self._attempt_owned_off(
                list(SMU_CHANNELS),
                context="connect",
            )
            if not off_confirmed:
                log.critical(
                    "%s: SAFETY: output state UNVERIFIED after connect force-OFF; source start remains blocked",
                    self.name,
                )
            if pending_cancel is not None:
                raise pending_cancel

            accepted_identity = _parse_keithley_idn(idn_raw, mock=self.mock)
            # Drain stale errors only after family authorization and OFF
            # settlement; unknown hardware receives no vendor-specific write.
            await self._transport.write("errorqueue.clear()")
            await self._wdog_arm()
        except BaseException:
            self._instrument_id = ""
            self._connect_in_progress = False
            retained_for_recovery = (
                family_authorized
                and self._connected
                and not all(self._has_current_off_proof(channel) for channel in SMU_CHANNELS)
            )
            if retained_for_recovery:
                self._unsafe_output_state = True
                log.critical(
                    "%s: retaining family-authorized transport for OFF recovery; "
                    "identity is unpublished and source start remains blocked",
                    self.name,
                )
                raise
            await self._settle_failed_connect()
            raise

        assert accepted_identity is not None
        self._instrument_id = accepted_identity
        self._connect_in_progress = False

    async def _settle_failed_connect(self) -> None:
        """Revoke connection truth and settle transport cleanup before return."""

        self._connected = False
        self._instrument_id = ""
        self._revoke_off_evidence()
        try:
            close_task = asyncio.create_task(self._transport.close())
            while not close_task.done():
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            try:
                close_task.result()
            except BaseException as exc:
                log.critical("%s: failed-connect transport cleanup failed: %s", self.name, exc)
        finally:
            self._connected = False
            self._connect_in_progress = False
            self._instrument_id = ""
            self._revoke_off_evidence()

    async def disconnect(self) -> None:
        if self._connect_in_progress or self._disconnect_in_progress:
            raise RuntimeError(f"{self.name}: lifecycle transition blocks disconnect")
        self._disconnect_in_progress = True
        pending_cancel: asyncio.CancelledError | None = None
        terminal_error: BaseException | None = None
        try:
            if not self._connected:
                self._instrument_id = ""
                self._revoke_off_evidence()
                return

            off_confirmed = all(self._has_current_off_proof(channel) for channel in SMU_CHANNELS)
            if not off_confirmed:
                try:
                    off_confirmed, pending_cancel = await self._attempt_owned_off(
                        list(SMU_CHANNELS),
                        context="disconnect",
                    )
                except BaseException as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        pending_cancel = pending_cancel or exc
                    else:
                        terminal_error = exc
                    off_confirmed = all(self._has_current_off_proof(channel) for channel in SMU_CHANNELS)
            if not off_confirmed:
                self._unsafe_output_state = True
                if pending_cancel is not None:
                    raise pending_cancel
                if terminal_error is not None:
                    raise terminal_error
                raise OutputStateUnverifiedError(
                    f"{self.name}: disconnect refused without a readback-verified OFF for both outputs"
                )

            # Terminal current-generation OFF proof authorizes teardown.  Keep
            # the lifecycle barrier raised until disarm and close both settle.
            try:
                await self._wdog_disarm()
            except asyncio.CancelledError as exc:
                pending_cancel = pending_cancel or exc
            except BaseException as exc:
                terminal_error = terminal_error or exc

            close_task = asyncio.create_task(self._transport.close())
            while not close_task.done():
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError as exc:
                    pending_cancel = pending_cancel or exc
                except BaseException:
                    break
            try:
                close_task.result()
            except asyncio.CancelledError as exc:
                pending_cancel = pending_cancel or exc
            except BaseException as exc:
                terminal_error = terminal_error or exc
            finally:
                self._connected = False
                self._instrument_id = ""
                self._wdog_armed = False
                self._wdog_autonomous = False
                self._revoke_off_evidence()

            if pending_cancel is not None:
                raise pending_cancel
            if terminal_error is not None:
                raise terminal_error
        finally:
            self._disconnect_in_progress = False

    async def read_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")

        if self.mock:
            return self._mock_readings()

        try:
            await self._wdog_pet()
        except OSError:
            self._connected = False
            self._instrument_id = ""
            self._revoke_off_evidence()
            raise

        readings: list[Reading] = []
        for smu_channel in SMU_CHANNELS:
            runtime = self._channels[smu_channel]
            iv_evidence: str | None = None
            output_evidence: str | None = None
            compliance_evidence: str | None = None
            try:
                if not runtime.active:
                    # Check output state — source may be OFF or left ON from
                    # a previous session.  measure.iv() errors when output is OFF.
                    output_raw = await self._transport.query(f"print({smu_channel}.source.output)", timeout_ms=3000)
                    output_evidence = output_raw
                    try:
                        output_on = _parse_output_enabled(output_raw)
                    except ValueError as exc:
                        self._invalidate_channel_off_evidence(smu_channel, advance_epoch=True)
                        log.error(
                            "%s: invalid output state on %s: %s",
                            self.name,
                            smu_channel,
                            exc,
                        )
                        readings.extend(
                            self._error_readings_for_channel(
                                smu_channel,
                                output_evidence=output_evidence,
                            )
                        )
                        continue

                    if not output_on:
                        readings.extend(self._build_channel_readings(smu_channel, 0.0, 0.0, resistance_override=0.0))
                        continue

                    # Output is ON but not managed by us — read for monitoring.
                    self._invalidate_channel_off_evidence(smu_channel, advance_epoch=True)
                    raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
                    iv_evidence = raw
                    current, voltage = self._parse_iv_response(raw, smu_channel)
                    readings.extend(self._build_channel_readings(smu_channel, voltage, current))
                    continue

                # --- Active P=const channel: measure + regulate ---
                regulation_generation = self._connection_generation
                regulation_epoch = self._source_command_epoch[smu_channel]
                raw = await self._transport.query(f"print({smu_channel}.measure.iv())")
                iv_evidence = raw
                current, voltage = self._parse_iv_response(raw, smu_channel)

                # --- Compliance check ---
                comp_raw = await self._transport.query(f"print({smu_channel}.source.compliance)")
                compliance_evidence = comp_raw
                in_compliance = _parse_compliance(comp_raw)

                extra_meta: dict[str, Any] = {}
                if in_compliance:
                    if self._regulation_is_current(
                        smu_channel,
                        generation=regulation_generation,
                        command_epoch=regulation_epoch,
                    ):
                        self._compliance_count[smu_channel] += 1
                        log.warning(
                            "%s: %s in compliance — P=const regulation ineffective (consecutive=%d)",
                            self.name,
                            smu_channel,
                            self._compliance_count[smu_channel],
                        )
                    extra_meta["compliance"] = True
                    # Do NOT adjust voltage — the SMU is already at its limit.
                else:
                    if self._regulation_is_current(
                        smu_channel,
                        generation=regulation_generation,
                        command_epoch=regulation_epoch,
                    ):
                        self._compliance_count[smu_channel] = 0

                    # --- P=const voltage regulation with slew rate limit ---
                    if abs(current) > _I_MIN_A:
                        resistance = voltage / current
                        if resistance > 0:
                            target_v = math.sqrt(runtime.p_target * resistance)
                            target_v = max(0.0, min(target_v, runtime.v_comp))

                            # Slew rate limit
                            current_v = self._last_v[smu_channel]
                            delta_v = target_v - current_v
                            if abs(delta_v) > MAX_DELTA_V_PER_STEP:
                                delta_v = MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
                                target_v = current_v + delta_v
                                log.debug(
                                    "Slew rate limited: delta=%.3f V, target=%.3f V",
                                    delta_v,
                                    target_v,
                                )

                            if self._regulation_is_current(
                                smu_channel,
                                generation=regulation_generation,
                                command_epoch=regulation_epoch,
                            ):
                                await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
                                if self._regulation_is_current(
                                    smu_channel,
                                    generation=regulation_generation,
                                    command_epoch=regulation_epoch,
                                ):
                                    self._last_v[smu_channel] = target_v

                readings.extend(self._build_channel_readings(smu_channel, voltage, current, extra_meta=extra_meta))
            except OSError as exc:
                # Transport-level error (USB disconnect, pipe broken) —
                # mark disconnected so scheduler triggers reconnect.
                log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
                self._connected = False
                self._instrument_id = ""
                self._revoke_off_evidence()
                raise
            except Exception as exc:
                log.error("%s: read failure on %s: %s", self.name, smu_channel, exc)
                readings.extend(
                    self._error_readings_for_channel(
                        smu_channel,
                        raw_evidence=iv_evidence,
                        output_evidence=output_evidence,
                        compliance_evidence=compliance_evidence,
                    )
                )
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
        if not (math.isfinite(p_target) and math.isfinite(v_compliance) and math.isfinite(i_compliance)):
            # Non-finite would be formatted straight into the SCPI level/limit
            # writes below (and nan defeats the <= 0 guard). Reject at the
            # hardware boundary regardless of caller.
            raise ValueError("P/V/I must be finite")
        if p_target <= 0 or v_compliance <= 0 or i_compliance <= 0:
            raise ValueError("P/V/I must be > 0")
        if runtime.active:
            raise RuntimeError(f"Channel {smu_channel} already active")
        start_token = self._begin_start_operation(smu_channel)

        runtime.p_target = p_target
        runtime.v_comp = v_compliance
        runtime.i_comp = i_compliance
        self._source_regulation_epoch[smu_channel] = None
        output_on_attempted = False

        async def write_owned(command: str) -> None:
            self._require_current_start(smu_channel, start_token)
            await self._transport.write(command)
            self._require_current_start(smu_channel, start_token)

        try:
            if self.mock:
                runtime.active = True
                self._source_regulation_epoch[smu_channel] = start_token
                return

            # Every hazardous write is bracketed by an ownership check.  OFF
            # authority may supersede this start at any await boundary.
            for command in (
                f"{smu_channel}.reset()",
                f"{smu_channel}.source.func = {smu_channel}.OUTPUT_DCVOLTS",
                f"{smu_channel}.source.autorangev = {smu_channel}.AUTORANGE_ON",
                f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON",
                f"{smu_channel}.source.limitv = {v_compliance}",
                f"{smu_channel}.source.limiti = {i_compliance}",
                f"{smu_channel}.source.levelv = 0",
            ):
                await write_owned(command)

            self._require_current_start(smu_channel, start_token)
            output_on_attempted = True
            # A write can reach the instrument and then raise locally. Publish
            # the hazardous possibility before awaiting the command.
            runtime.active = True
            await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
            self._require_current_start(smu_channel, start_token)

            self._last_v[smu_channel] = 0.0
            self._compliance_count[smu_channel] = 0
            self._source_regulation_epoch[smu_channel] = start_token
        except BaseException as original_error:
            cleanup_exact = False
            cleanup_pending: asyncio.CancelledError | None = None
            try:
                cleanup_exact, cleanup_pending = await self._attempt_owned_off(
                    [smu_channel],
                    context="failed_start",
                )
            except BaseException as cleanup_error:
                cleanup_exact = self._has_current_off_readback(smu_channel)
                log.critical(
                    "%s: SAFETY: failed-start OFF cleanup raised on %s: %s",
                    self.name,
                    smu_channel,
                    cleanup_error,
                )

            if not cleanup_exact:
                self._source_regulation_epoch[smu_channel] = None
                runtime.active = output_on_attempted
                if not output_on_attempted:
                    runtime.p_target = 0.0
                self._unsafe_output_state = True

            if isinstance(original_error, asyncio.CancelledError):
                raise original_error
            if cleanup_pending is not None:
                raise cleanup_pending from original_error
            raise
        finally:
            self._finish_start_operation(smu_channel, start_token)

    async def _settle_owned_bool_task(
        self,
        task: asyncio.Task[bool],
    ) -> tuple[bool | None, BaseException | None, asyncio.CancelledError | None]:
        """Retain one safety task to terminal state despite caller cancellation."""

        caller_cancelled: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
                continue
            except BaseException:
                break
        try:
            return task.result(), None, caller_cancelled
        except BaseException as exc:
            return None, exc, caller_cancelled

    async def _attempt_output_off_sequence(
        self,
        channels: list[SmuChannel],
        *,
        tokens: dict[SmuChannel, int],
        generation: int,
        context: str,
    ) -> bool:
        """Attempt every OFF command, then independently verify every target."""

        if self.mock:
            all_confirmed = True
            for smu_channel in channels:
                committed = self._mark_channel_off_verified(
                    smu_channel,
                    generation=generation,
                    command_epoch=tokens[smu_channel],
                )
                all_confirmed = committed and all_confirmed
            return all_confirmed

        deferred_error: BaseException | None = None
        for smu_channel in channels:
            for command in (
                f"{smu_channel}.source.levelv = 0",
                f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF",
            ):
                try:
                    await self._transport.write(command)
                except Exception as exc:
                    log.critical(
                        "%s: SAFETY: %s command failed on %s (%s): %s",
                        self.name,
                        context,
                        smu_channel,
                        command,
                        exc,
                    )
                except BaseException as exc:
                    deferred_error = deferred_error or exc
                    log.critical(
                        "%s: SAFETY: %s command interrupted on %s (%s): %s",
                        self.name,
                        context,
                        smu_channel,
                        command,
                        exc,
                    )

        all_confirmed = True
        for smu_channel in channels:
            try:
                readback_confirmed = await self._verify_output_off(smu_channel)
            except Exception as exc:
                log.critical(
                    "%s: SAFETY: %s OFF readback failed on %s: %s",
                    self.name,
                    context,
                    smu_channel,
                    exc,
                )
                readback_confirmed = False
            except BaseException as exc:
                deferred_error = deferred_error or exc
                log.critical(
                    "%s: SAFETY: %s OFF readback interrupted on %s: %s",
                    self.name,
                    context,
                    smu_channel,
                    exc,
                )
                readback_confirmed = False
            if readback_confirmed:
                committed = self._mark_channel_off_verified(
                    smu_channel,
                    generation=generation,
                    command_epoch=tokens[smu_channel],
                )
                all_confirmed = committed and all_confirmed
            else:
                all_confirmed = False
                if tokens[smu_channel] == self._source_command_epoch[smu_channel]:
                    self._invalidate_channel_off_evidence(smu_channel)
        if deferred_error is not None:
            raise deferred_error
        return all_confirmed

    async def _attempt_owned_off(
        self,
        channels: list[SmuChannel],
        *,
        context: str,
    ) -> tuple[bool, asyncio.CancelledError | None]:
        """Preclaim and settle one complete OFF sequence without a broad lock."""

        tokens = self._begin_off_operation(channels)
        generation = self._connection_generation
        task = asyncio.create_task(
            self._attempt_output_off_sequence(
                channels,
                tokens=tokens,
                generation=generation,
                context=context,
            ),
            name=f"{self.name}_{context}_off",
        )
        try:
            result, error, caller_cancelled = await self._settle_owned_bool_task(task)
        finally:
            self._finish_off_operation(channels)
        if error is not None:
            raise error
        return result is True, caller_cancelled

    async def stop_source(self, channel: str) -> None:
        smu_channel = normalize_smu_channel(channel)

        if not self._connected:
            if self.mock:
                tokens = self._begin_off_operation([smu_channel])
                try:
                    self._mark_channel_off_verified(
                        smu_channel,
                        command_epoch=tokens[smu_channel],
                    )
                finally:
                    self._finish_off_operation([smu_channel])
                return
            self._unsafe_output_state = True
            raise OutputStateUnverifiedError(
                f"{self.name}: {smu_channel} is disconnected; output OFF cannot be verified"
            )

        off_confirmed, pending_cancel = await self._attempt_owned_off(
            [smu_channel],
            context="stop_source",
        )
        if pending_cancel is not None:
            raise pending_cancel
        if not off_confirmed:
            raise OutputStateUnverifiedError(
                f"{self.name}: {smu_channel} output state UNVERIFIED after "
                f"OUTPUT_OFF (readback did not confirm OFF) — output may still be ON"
            )

    async def read_buffer(self, start_idx: int = 1, count: int = 100) -> list[dict[str, float]]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        if self.mock:
            return self._mock_buffer(start_idx, count)

        end_idx = start_idx + count - 1
        raw = await self._transport.query(
            f"printbuffer({start_idx}, {end_idx}, smua.nvbuffer1.timestamps, smua.nvbuffer1.sourcevalues, smua.nvbuffer1)",  # noqa: E501
            timeout_ms=10_000,
        )
        return self._parse_buffer_response(raw)

    async def emergency_off(self, channel: str | None = None) -> bool:
        """Force output OFF on the targeted channel(s).

        A fresh exact readback is the sole positive authority for each target.
        Every command and readback is attempted even after an earlier ordinary
        failure.  Caller cancellation is delivered only after the full sequence
        reaches a terminal result.
        """
        channels = [normalize_smu_channel(channel)] if channel is not None else list(SMU_CHANNELS)

        if not self._connected:
            if not self.mock:
                self._unsafe_output_state = True
                return False
            tokens = self._begin_off_operation(channels)
            try:
                for smu_channel in channels:
                    self._mark_channel_off_verified(
                        smu_channel,
                        command_epoch=tokens[smu_channel],
                    )
            finally:
                self._finish_off_operation(channels)
            return True

        off_confirmed, pending_cancel = await self._attempt_owned_off(
            channels,
            context="emergency_off",
        )
        if pending_cancel is not None:
            raise pending_cancel
        return off_confirmed

    def _has_current_off_proof(self, smu_channel: SmuChannel) -> bool:
        return (
            self._has_current_off_readback(smu_channel)
            and self._source_start_token[smu_channel] is None
            and self._source_off_depth[smu_channel] == 0
        )

    def _has_current_off_readback(self, smu_channel: SmuChannel) -> bool:
        """Return exact OFF evidence without treating an active transition as settled."""

        return (
            self._connected
            and self._output_off_verified[smu_channel] is True
            and self._output_off_verified_generation[smu_channel] == self._connection_generation
            and self._output_off_verified_epoch[smu_channel] == self._source_command_epoch[smu_channel]
        )

    def _refresh_output_uncertainty(self) -> None:
        self._unsafe_output_state = not all(self._has_current_off_proof(channel) for channel in SMU_CHANNELS)

    def _invalidate_channel_off_evidence(
        self,
        smu_channel: SmuChannel,
        *,
        advance_epoch: bool = False,
    ) -> None:
        if advance_epoch:
            self._source_command_epoch[smu_channel] += 1
        self._source_regulation_epoch[smu_channel] = None
        self._output_off_verified[smu_channel] = False
        self._output_off_verified_generation[smu_channel] = None
        self._output_off_verified_epoch[smu_channel] = None
        self._unsafe_output_state = True

    def _revoke_off_evidence(self) -> None:
        self._output_off_verified = {"smua": False, "smub": False}
        self._output_off_verified_generation = {"smua": None, "smub": None}
        self._output_off_verified_epoch = {"smua": None, "smub": None}
        self._unsafe_output_state = True

    def _begin_off_operation(self, channels: list[SmuChannel]) -> dict[SmuChannel, int]:
        """Preclaim OFF authority for every target before the first await."""

        tokens: dict[SmuChannel, int] = {}
        for smu_channel in channels:
            self._source_command_epoch[smu_channel] += 1
            token = self._source_command_epoch[smu_channel]
            self._source_off_depth[smu_channel] += 1
            self._invalidate_channel_off_evidence(smu_channel)
            tokens[smu_channel] = token
        return tokens

    def _finish_off_operation(self, channels: list[SmuChannel]) -> None:
        for smu_channel in channels:
            self._source_off_depth[smu_channel] = max(0, self._source_off_depth[smu_channel] - 1)
        self._refresh_output_uncertainty()

    def _begin_start_operation(self, smu_channel: SmuChannel) -> int:
        if self._connect_in_progress or self._disconnect_in_progress:
            raise RuntimeError(f"{self.name}: lifecycle transition blocks source start")
        if self._source_start_token[smu_channel] is not None:
            raise RuntimeError(f"{self.name}: {smu_channel} source start already in progress")
        if self._source_off_depth[smu_channel] != 0:
            raise RuntimeError(f"{self.name}: {smu_channel} OFF operation is in progress")
        if not self._has_current_off_proof(smu_channel):
            raise OutputStateUnverifiedError(
                f"{self.name}: {smu_channel} source start blocked without current readback-verified OFF"
            )
        self._source_command_epoch[smu_channel] += 1
        token = self._source_command_epoch[smu_channel]
        self._source_start_token[smu_channel] = token
        self._invalidate_channel_off_evidence(smu_channel)
        return token

    def _start_operation_is_current(self, smu_channel: SmuChannel, token: int) -> bool:
        return (
            self._connected
            and not self._connect_in_progress
            and not self._disconnect_in_progress
            and self._source_start_token[smu_channel] == token
            and self._source_command_epoch[smu_channel] == token
            and self._source_off_depth[smu_channel] == 0
        )

    def _require_current_start(self, smu_channel: SmuChannel, token: int) -> None:
        if not self._start_operation_is_current(smu_channel, token):
            raise RuntimeError(f"{self.name}: {smu_channel} source start was superseded by OFF/lifecycle authority")

    def _finish_start_operation(self, smu_channel: SmuChannel, token: int) -> None:
        if self._source_start_token[smu_channel] == token:
            self._source_start_token[smu_channel] = None
        self._refresh_output_uncertainty()

    def _regulation_is_current(
        self,
        smu_channel: SmuChannel,
        *,
        generation: int,
        command_epoch: int,
    ) -> bool:
        return (
            self._connected
            and not self._connect_in_progress
            and not self._disconnect_in_progress
            and generation == self._connection_generation
            and command_epoch == self._source_command_epoch[smu_channel]
            and self._source_regulation_epoch[smu_channel] == command_epoch
            and self._source_start_token[smu_channel] is None
            and self._source_off_depth[smu_channel] == 0
            and self._channels[smu_channel].active
        )

    def _mark_channel_off_verified(
        self,
        smu_channel: SmuChannel,
        *,
        generation: int | None = None,
        command_epoch: int | None = None,
    ) -> bool:
        """Commit one exact current-connection/current-command OFF readback."""
        if generation is not None and (not self._connected or generation != self._connection_generation):
            return False
        proof_epoch = self._source_command_epoch[smu_channel] if command_epoch is None else command_epoch
        if proof_epoch != self._source_command_epoch[smu_channel]:
            return False
        runtime = self._channels[smu_channel]
        self._source_regulation_epoch[smu_channel] = None
        runtime.active = False
        runtime.p_target = 0.0
        self._last_v[smu_channel] = 0.0
        self._compliance_count[smu_channel] = 0
        self._output_off_verified[smu_channel] = True
        self._output_off_verified_generation[smu_channel] = self._connection_generation
        self._output_off_verified_epoch[smu_channel] = proof_epoch
        self._refresh_output_uncertainty()
        return True

    async def check_error(self) -> str | None:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")
        response = (await self._transport.query("print(errorqueue.count)")).strip()
        if response in {"", "0"}:
            return None
        return response

    @property
    def output_state_unverified(self) -> bool:
        """True when the crash-recovery force-OFF on connect() could not be
        readback-verified (outputs may still be ON). SafetyManager treats this
        as a blocking RUN precondition until a later verified OFF clears it."""
        if not self.mock and not self._connected:
            return True
        return self._unsafe_output_state

    @property
    def any_active(self) -> bool:
        return any(runtime.active for runtime in self._channels.values())

    @property
    def active_channels(self) -> list[str]:
        return [channel for channel, runtime in self._channels.items() if runtime.active]

    def compliance_persistent(self, channel: SmuChannel) -> bool:
        """True if compliance has persisted for >= threshold consecutive cycles."""
        return self._compliance_count.get(channel, 0) >= _COMPLIANCE_NOTIFY_THRESHOLD

    @property
    def watchdog_trip_pending(self) -> bool:
        """Whether unconsumed TSP trip evidence requires operator recovery."""
        return self._wdog_trip_pending

    async def diagnostics(self) -> dict[str, Any]:
        """Periodic health check — called by scheduler every 30s."""
        if not self._connected or self.mock:
            return {}
        result: dict[str, Any] = {}
        try:
            raw = await self._transport.query("print(errorqueue.count)")
            err_count = int(float(raw.strip()))
            if err_count > 0:
                raw = await self._transport.query("print(errorqueue.next())")
                log.warning("Keithley error queue: %s", raw.strip())
                result["error_queue"] = raw.strip()
        except Exception as exc:
            log.error("%s: diagnostics error: %s", self.name, exc)
        return result

    # --- TSP software late-pet watchdog -------------------------------------
    # All methods are no-ops unless _wdog_enabled and not mock, so the default
    # command stream is byte-identical to the pre-watchdog driver.

    def _wdog_reject_unknown_latch(self, detail: str) -> bool:
        """Route an unknown pre-upload latch without erasing instrument state."""
        self._wdog_armed = False
        self._wdog_autonomous = False
        if self._wdog_mode is WatchdogMode.REQUIRED:
            log.critical(
                "%s: TSP watchdog latch state UNKNOWN and mode=required — "
                "refusing to connect without uploading/resetting it: %s",
                self.name,
                detail,
            )
            raise _WatchdogArmError(f"TSP watchdog latch state unknown: {detail}")
        log.critical(
            "%s: TSP watchdog latch state UNKNOWN; NOT activating or uploading "
            "because that would erase possible trip evidence (degraded, "
            "host-only): %s",
            self.name,
            detail,
        )
        return False

    async def _wdog_arm(self) -> None:
        """Upload and activate the selected watchdog behavior.

        Latch read FIRST (before upload): re-uploading the script re-runs
        ``cryodaq_wdog_tripped = 0`` and would wipe a prior trip before it can
        be seen. A fresh instrument has no such global → prints ``nil`` →
        accepted only as the explicit fresh-state sentinel. A latched prior trip
        is preserved without upload and exposed as pending evidence. The
        operator must acknowledge it through SafetyManager after outputs are
        verified OFF; connect itself remains available for recovery.

        best_effort: NON-fatal on activation failure — connect still succeeds,
        _wdog_armed stays False, CRITICAL flags the degraded run. With v3 it
        may activate late-pet checking while _wdog_autonomous remains False.

        required: fail-CLOSED unless the uploaded script reports the literal
        autonomous bit 1. The current version truthfully reports 0, so required
        refuses it before activation. A pre-existing latch is not a failure."""
        if not self._wdog_enabled or self.mock:
            return
        self._wdog_armed = False
        self._wdog_autonomous = False
        if self._wdog_trip_pending:
            log.critical(
                "%s: preserving previously observed watchdog trip evidence; "
                "explicit operator acknowledgment required before reactivation",
                self.name,
            )
            return
        # DELTA 1: read the latch before the upload clears it. Two failure
        # cases must NOT be conflated:
        #   (a) query succeeds with the explicit TSP nil sentinel from a
        #       fresh instrument → genuinely "no latch" → proceed.
        #   (b) query fails OR returns malformed/non-finite/out-of-domain data —
        #       the latch state is
        #       UNKNOWN. Proceeding re-uploads the script, which re-runs
        #       ``cryodaq_wdog_tripped = 0`` and silently destroys evidence of a
        #       past watchdog trip. This follows failure semantics per mode.
        try:
            raw = await self._transport.query("print(cryodaq_wdog_tripped)")
        except Exception as exc:
            self._wdog_reject_unknown_latch(f"transport read failed: {exc}")
            return
        try:
            latched = _parse_wdog_latch(raw)
        except ValueError as exc:
            self._wdog_reject_unknown_latch(str(exc))
            return
        if latched:
            self._wdog_trip_pending = True
            log.critical(
                "%s: TSP watchdog read back a LATCHED prior trip — "
                "preserving evidence without upload/reactivation; explicit "
                "operator acknowledgment is required after verified OFF",
                self.name,
            )
            return
        run_issued = False
        try:
            watchdog_script = await asyncio.to_thread(_load_wdog_script)
            await self._transport.write(watchdog_script)
            # DELTA A8a — version stamp: the script is re-uploaded every arm, so
            # a truncated/stale upload passes the fire-and-forget writes silently.
            # Read CRYODAQ_WDOG_VERSION back and refuse to arm on mismatch.
            ver_raw = await self._transport.query("print(CRYODAQ_WDOG_VERSION)")
            try:
                ver = _parse_wdog_version(ver_raw, field="CRYODAQ_WDOG_VERSION")
            except ValueError as exc:
                raise _WatchdogArmError(str(exc)) from exc
            if ver != _WDOG_SCRIPT_VERSION:
                raise _WatchdogArmError(
                    f"TSP watchdog version mismatch: firmware={ver_raw.strip()!r} "
                    f"expected={_WDOG_SCRIPT_VERSION} (truncated or stale upload)"
                )

            # An active late-pet checker is not an autonomous dead-man. Read a
            # separate explicit contract bit and never infer it from
            # cryodaq_wdog_active. Version 3 deliberately reports 0.
            self._wdog_autonomous = False
            autonomous_read_ok = False
            try:
                autonomous_raw = await self._transport.query("print(cryodaq_wdog_autonomous)")
                self._wdog_autonomous = _parse_wdog_flag(autonomous_raw, field="cryodaq_wdog_autonomous")
                autonomous_read_ok = True
            except Exception as autonomous_exc:
                if self._wdog_mode is WatchdogMode.REQUIRED:
                    raise _WatchdogArmError(
                        "TSP watchdog autonomous readback failed; required mode "
                        "refuses unverified host-death protection"
                    ) from autonomous_exc
                log.critical(
                    "%s: SAFETY DEGRADED: autonomous watchdog readback failed; "
                    "continuing with software late-pet protection only, which "
                    "has ZERO full-host-death coverage: %s",
                    self.name,
                    autonomous_exc,
                )
            if autonomous_read_ok and not self._wdog_autonomous:
                if self._wdog_mode is WatchdogMode.REQUIRED:
                    raise _WatchdogArmError(
                        "TSP watchdog is not autonomous: "
                        f"cryodaq_wdog_autonomous={autonomous_raw.strip()!r}; "
                        "required mode refuses source availability"
                    )
                log.critical(
                    "%s: SAFETY DEGRADED: watchdog is NON-AUTONOMOUS; "
                    "best_effort enables only the software late-pet check "
                    "and provides ZERO full-host-death coverage",
                    self.name,
                )
            await self._transport.write(f"CRYODAQ_WDOG_TIMEOUT_S = {self._wdog_timeout_s}")
            # R2 (Phase A recheck, MEDIUM): mark issued BEFORE the write, not
            # after it returns. A write that raises AFTER the instrument has
            # already accepted the command (ambiguous VISA/TSP failure) must
            # still trigger the best-effort disarm below — conservative:
            # ambiguity means attempt the disarm.
            run_issued = True
            await self._transport.write("cryodaq_wdog_run()")
            # Software state readback: confirm the script became active and did
            # not boot latched. This bit says nothing about autonomy; that was
            # read separately above.
            active_raw = await self._transport.query("print(cryodaq_wdog_active)")
            tripped_raw = await self._transport.query("print(cryodaq_wdog_tripped)")
            active = _parse_wdog_flag(active_raw, field="cryodaq_wdog_active")
            tripped = _parse_wdog_flag(tripped_raw, field="cryodaq_wdog_tripped")
            if not active or tripped:
                raise _WatchdogArmError(
                    f"TSP watchdog arm readback bad: active={active_raw.strip()!r} "
                    f"tripped={tripped_raw.strip()!r} (expected active=1 tripped=0)"
                )
            self._wdog_armed = True
            log.info(
                "%s: TSP software late-pet watchdog active (timeout=%.1fs, fw v%d, autonomous=%s)",
                self.name,
                self._wdog_timeout_s,
                _WDOG_SCRIPT_VERSION,
                self._wdog_autonomous,
            )
        except Exception as exc:
            self._wdog_armed = False
            self._wdog_autonomous = False
            if run_issued:
                # F4 (Phase A gate, MEDIUM): cryodaq_wdog_run() was already
                # written before this failure (e.g. the readback that would
                # confirm/refute activation timed out) — the script may still
                # be active even though we just set _wdog_armed=False.
                # Best-effort disarm write, bypassing the
                # _wdog_armed gate in _wdog_disarm() (we don't trust host
                # state here — that's the whole problem).
                try:
                    await self._transport.write("cryodaq_wdog_disarm()")
                except Exception as disarm_exc:
                    log.critical(
                        "%s: TSP watchdog best-effort disarm after a failed "
                        "post-run readback ALSO failed — TSP activation state "
                        "UNKNOWN: %s",
                        self.name,
                        disarm_exc,
                    )
            if self._wdog_mode is WatchdogMode.REQUIRED:
                log.critical(
                    "%s: TSP watchdog arm FAILED and mode=required — refusing to connect (fail-closed): %s",
                    self.name,
                    exc,
                )
                raise
            log.critical(
                "%s: TSP watchdog upload/activation FAILED — running host-only "
                "without even the software late-pet check (degraded): %s",
                self.name,
                exc,
            )

    async def _wdog_pet(self) -> None:
        """Run the TSP late-pet deadline check. No-op unless active."""
        if not (self._wdog_enabled and self._wdog_armed) or self.mock:
            return
        try:
            await self._transport.write("cryodaq_wdog_pet()")
        except Exception as exc:
            log.error("%s: TSP watchdog pet failed: %s", self.name, exc)

    async def _wdog_disarm(self) -> None:
        """Clean release of the TSP late-pet checker on disconnect."""
        if not (self._wdog_enabled and self._wdog_armed) or self.mock:
            return
        try:
            await self._transport.write("cryodaq_wdog_disarm()")
        except Exception as exc:
            log.error("%s: TSP watchdog disarm failed: %s", self.name, exc)
        finally:
            self._wdog_armed = False
            self._wdog_autonomous = False

    async def acknowledge_wdog_trip(self) -> bool:
        """Consume a trip only after verified OFF and explicit operator ack.

        SafetyManager calls this from its fault-acknowledgment path after it has
        accepted and recorded a recovery reason. A successful command clears
        the latch and reactivates only the non-autonomous late-pet checker.
        Any ambiguity keeps recovery fault-latched and attempts a disarm.
        """
        if not self._wdog_enabled or self.mock:
            return True
        if not self._connected:
            if self._wdog_trip_pending:
                log.critical(
                    "%s: refusing watchdog trip acknowledgment while disconnected; trip evidence remains pending",
                    self.name,
                )
                return False
            return True
        if not self._wdog_armed and not self._wdog_trip_pending:
            return True

        raw = await self._transport.query("print(cryodaq_wdog_tripped)")
        fresh_instrument = raw.strip(_PROTOCOL_TRIM_CHARS) == "nil"
        if fresh_instrument:
            if not self._wdog_trip_pending:
                raise ValueError("watchdog latch disappeared without host-side pending evidence")
            tripped = False
        else:
            tripped = _parse_wdog_flag(raw, field="cryodaq_wdog_tripped")
        if not tripped and not self._wdog_trip_pending:
            return True
        # Preserve host evidence until verified OFF + successful reactivation.
        self._wdog_trip_pending = True
        force_upload = fresh_instrument or not tripped

        if not await self.emergency_off():
            log.critical(
                "%s: refusing watchdog trip acknowledgment because both-output OFF could not be readback-verified",
                self.name,
            )
            return False

        if self._wdog_mode is WatchdogMode.REQUIRED:
            log.critical(
                "%s: watchdog trip evidence preserved: required mode cannot "
                "reactivate non-autonomous v3; explicitly select best_effort "
                "and reconnect before acknowledging (off only intentionally "
                "disables the TSP path)",
                self.name,
            )
            return False

        ack_issued = False
        try:
            ack_issued = True
            version: int | None = None
            if not force_upload:
                version_raw = await self._transport.query("print(CRYODAQ_WDOG_VERSION)")
                if version_raw.strip().lower() != "nil":
                    version = _parse_wdog_version(version_raw, field="CRYODAQ_WDOG_VERSION")
            if version == _WDOG_SCRIPT_VERSION:
                await self._transport.write("cryodaq_wdog_acknowledge()")
            else:
                # Explicit operator acknowledgment authorizes consuming a latch
                # left by an older script, but only after verified OFF above.
                # Upgrade and reactivate v3 in this same visible recovery path.
                watchdog_script = await asyncio.to_thread(_load_wdog_script)
                await self._transport.write(watchdog_script)
                uploaded_raw = await self._transport.query("print(CRYODAQ_WDOG_VERSION)")
                uploaded = _parse_wdog_version(uploaded_raw, field="CRYODAQ_WDOG_VERSION")
                if uploaded != _WDOG_SCRIPT_VERSION:
                    raise _WatchdogArmError(
                        f"watchdog acknowledgment upgrade version mismatch: {uploaded_raw.strip()!r}"
                    )
                autonomous_raw = await self._transport.query("print(cryodaq_wdog_autonomous)")
                autonomous = _parse_wdog_flag(autonomous_raw, field="cryodaq_wdog_autonomous")
                if autonomous:
                    raise _WatchdogArmError("v3 acknowledgment upgrade unexpectedly reported autonomous=1")
                await self._transport.write(f"CRYODAQ_WDOG_TIMEOUT_S = {self._wdog_timeout_s}")
                await self._transport.write("cryodaq_wdog_run()")
            active_raw = await self._transport.query("print(cryodaq_wdog_active)")
            tripped_raw = await self._transport.query("print(cryodaq_wdog_tripped)")
            active = _parse_wdog_flag(active_raw, field="cryodaq_wdog_active")
            still_tripped = _parse_wdog_flag(tripped_raw, field="cryodaq_wdog_tripped")
            if not active or still_tripped:
                raise _WatchdogArmError(
                    "TSP watchdog acknowledgment readback bad: "
                    f"active={active_raw.strip()!r} tripped={tripped_raw.strip()!r}"
                )
        except Exception as exc:
            self._wdog_armed = False
            if ack_issued:
                try:
                    await self._transport.write("cryodaq_wdog_disarm()")
                except Exception as disarm_exc:
                    log.critical(
                        "%s: watchdog acknowledgment failed and disarm also failed; TSP state UNKNOWN: %s",
                        self.name,
                        disarm_exc,
                    )
            log.critical("%s: watchdog acknowledgment failed: %s", self.name, exc)
            return False

        self._wdog_armed = True
        self._wdog_autonomous = False
        self._wdog_trip_pending = False
        log.warning(
            "%s: operator acknowledgment consumed the late-pet trip after "
            "verified both-output OFF; late-pet checking reactivated",
            self.name,
        )
        return True

    async def wdog_tripped(self) -> bool:
        """True iff the software late-pet check latched a trip.

        This means a pet arrived after its deadline; it does not mean outputs
        were removed during complete host death. Inert unless the
        watchdog is enabled+armed on a real connected instrument — so the
        SafetyManager reconcile is a no-op under the default-OFF flag."""
        if self._wdog_trip_pending:
            return True
        if not (self._wdog_enabled and self._wdog_armed) or self.mock or not self._connected:
            return False
        raw = await self._transport.query("print(cryodaq_wdog_tripped)")
        tripped = _parse_wdog_flag(raw, field="cryodaq_wdog_tripped")
        if tripped:
            self._wdog_trip_pending = True
        return tripped

    async def _verify_output_off(self, channel: str) -> bool:
        """Readback-verify that ``channel``'s output is OFF.

        The output state and a unique host challenge must arrive in the same
        TSP response.  A stale queued response from an earlier query or process
        therefore cannot establish OFF authority.
        """
        if self.mock:
            return True
        if not self._connected:
            log.critical("%s: cannot verify %s OFF while disconnected", self.name, channel)
            return False
        smu_channel = normalize_smu_channel(channel)
        nonce = secrets.token_hex(16)
        command = f'print(string.format("{_OFF_CHALLENGE_PREFIX}|{nonce}|%g", {smu_channel}.source.output))'
        response = await self._transport.query(command, timeout_ms=3000)
        try:
            off_confirmed = _parse_output_off_challenge(response, expected_nonce=nonce)
        except ValueError as exc:
            log.critical(
                "%s: %s invalid OFF challenge response (%s): %r",
                self.name,
                smu_channel,
                exc,
                response[:256],
            )
            return False
        if not off_confirmed:
            log.critical(
                "%s: %s current OFF challenge did not report literal state 0: %r",
                self.name,
                smu_channel,
                response[:256],
            )
            return False
        return True

    def _parse_iv_response(self, raw: str, channel: SmuChannel) -> tuple[float, float]:
        parts = raw.strip().split("\t")
        if len(parts) != 2:
            raise ValueError(f"{channel}: expected 2 values, got {raw!r}")
        current, voltage = float(parts[0]), float(parts[1])
        if not (math.isfinite(current) and math.isfinite(voltage)):
            raise ValueError(f"{channel}: non-finite IV response {raw[:256]!r}")
        return current, voltage

    def _build_channel_readings(
        self,
        channel: SmuChannel,
        voltage: float,
        current: float,
        *,
        resistance_override: float | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> list[Reading]:
        resistance = (
            resistance_override
            if resistance_override is not None
            else (voltage / current if current != 0.0 else float("nan"))
        )
        power = voltage * current
        metadata: dict[str, Any] = {"resource_str": self._resource_str, "smu_channel": channel}
        if extra_meta:
            metadata.update(extra_meta)
        values = {
            "voltage": voltage,
            "current": current,
            "resistance": resistance,
            "power": power,
        }
        if not all(math.isfinite(value) for value in values.values()):
            metadata["reported_iv"] = {field: repr(value) for field, value in values.items()}
        readings: list[Reading] = []
        for field, unit in _IV_FIELDS:
            value = values[field]
            finite = math.isfinite(value)
            readings.append(
                Reading.now(
                    channel=f"{self.name}/{channel}/{field}",
                    value=value if finite else float("nan"),
                    unit=unit,
                    instrument_id=self.name,
                    status=ChannelStatus.OK if finite else ChannelStatus.SENSOR_ERROR,
                    raw=value if finite else None,
                    metadata=metadata,
                )
            )
        return readings

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
            if not all(math.isfinite(value) for value in (ts, voltage, current)):
                log.error("%s: discarding non-finite buffered IV row", self.name)
                continue
            resistance = voltage / current if current != 0.0 else float("nan")
            power = voltage * current
            if not math.isfinite(power):
                log.error("%s: buffered IV row has non-finite derived power", self.name)
                power = float("nan")
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

    def _error_readings_for_channel(
        self,
        channel: SmuChannel,
        *,
        raw_evidence: str | None = None,
        output_evidence: str | None = None,
        compliance_evidence: str | None = None,
    ) -> list[Reading]:
        metadata: dict[str, Any] = {"resource_str": self._resource_str, "smu_channel": channel}
        if raw_evidence is not None:
            metadata["reported_iv_response"] = repr(raw_evidence[:256])
        if output_evidence is not None:
            metadata["reported_output_response"] = repr(output_evidence[:256])
        if compliance_evidence is not None:
            metadata["reported_compliance_response"] = repr(compliance_evidence[:256])
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
