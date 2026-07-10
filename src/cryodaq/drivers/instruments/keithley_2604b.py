"""Keithley 2604B driver with dual-channel runtime support.

P=const control runs host-side in read_channels(). The optional TSP v3 script
only checks a late pet; it does not regulate and is not autonomous.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
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

# TSP software late-pet watchdog, gated on _wdog_enabled (default False).
# Version 3 is explicitly non-autonomous: it covers stall-then-recover only.
# See tsp/cryodaq_wdog.lua.
_WDOG_SCRIPT: str | None = None

# Version stamp the driver was written against. Must equal CRYODAQ_WDOG_VERSION
# in tsp/cryodaq_wdog.lua — the script is re-uploaded from repo tsp/ on every
# arm, so the host reads this back post-upload and refuses to arm on mismatch
# (catches a truncated or stale upload; firmware gets no CI).
_WDOG_SCRIPT_VERSION = 3


class _WatchdogArmError(RuntimeError):
    """Watchdog upload/activation integrity check failed.

    ``required`` also raises when the uploaded script does not report the
    literal autonomous contract bit ``1``. Version 3 intentionally reports 0,
    so it is usable only as a degraded late-pet check in ``best_effort`` mode.
    """


def _parse_wdog_number(raw: str, *, field: str) -> float:
    """Parse one finite numeric TSP protocol value or raise ValueError."""
    text = raw.strip()
    if not text:
        raise ValueError(f"{field} readback is empty")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{field} readback is not numeric: {text!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field} readback is not finite: {text!r}")
    return value


def _parse_wdog_flag(raw: str, *, field: str) -> bool:
    """Parse an exact TSP protocol flag: finite numeric 0 or 1 only."""
    value = _parse_wdog_number(raw, field=field)
    if value == 0.0:
        return False
    if value == 1.0:
        return True
    raise ValueError(f"{field} readback must be exactly 0 or 1, got {raw.strip()!r}")


def _parse_wdog_latch(raw: str) -> bool:
    """Parse pre-upload latch, admitting only explicit fresh-state sentinels."""
    text = raw.strip().lower()
    if text == "nil":
        return False
    return _parse_wdog_flag(raw, field="cryodaq_wdog_tripped")


def _validate_wdog_timeout_s(value: object) -> float:
    """Return a finite late-pet timeout within the supported safety range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            "watchdog_timeout_s must be a real number, not a boolean or string"
        )
    timeout_s = float(value)
    if not math.isfinite(timeout_s):
        raise ValueError("watchdog_timeout_s must be finite")
    if not (_WDOG_TIMEOUT_MIN_S <= timeout_s <= _WDOG_TIMEOUT_MAX_S):
        raise ValueError(
            "watchdog_timeout_s must be between "
            f"{_WDOG_TIMEOUT_MIN_S:g} and {_WDOG_TIMEOUT_MAX_S:g} seconds"
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
            self._wdog_mode = (
                WatchdogMode.BEST_EFFORT if watchdog_enabled else WatchdogMode.OFF
            )
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
        self._unsafe_output_state = False

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
            # Mark connected BEFORE the crash-recovery readback so
            # _verify_output_off issues a real query (it short-circuits to True
            # while _connected is False). Reset in the except below if anything
            # here re-raises (only the IDN/clear steps above can, and they run
            # before this point).
            self._connected = True
            # SAFETY (Phase 2a G.1): force outputs off on every connect.
            # The previous engine process may have crashed mid-experiment
            # while sourcing — Keithley holds the last programmed voltage
            # indefinitely with no autonomous TSP-side watchdog. This
            # guarantees a known-safe state every time we assume control.
            # connect() must NOT abort on a force-off failure (refusing connect
            # strips the operator of all control — Phase 2a G.1 rationale). F2:
            # instead readback-verify both channels; an unverified/still-ON
            # output sets the blocking _unsafe_output_state flag so SafetyManager
            # refuses RUN (only RUN) until a later verified OFF clears it.
            if not self.mock:
                self._unsafe_output_state = False
                try:
                    await self._transport.write("smua.source.levelv = 0")
                    await self._transport.write("smub.source.levelv = 0")
                    await self._transport.write("smua.source.output = smua.OUTPUT_OFF")
                    await self._transport.write("smub.source.output = smub.OUTPUT_OFF")
                except Exception as exc:
                    log.critical(
                        "%s: SAFETY: failed to force output off on connect: %s",
                        self.name,
                        exc,
                    )
                    self._unsafe_output_state = True
                else:
                    for smu_channel in SMU_CHANNELS:
                        try:
                            if not await self._verify_output_off(smu_channel):
                                self._unsafe_output_state = True
                        except Exception as exc:
                            log.critical(
                                "%s: SAFETY: connect force-off readback FAILED on %s: %s",
                                self.name,
                                smu_channel,
                                exc,
                            )
                            self._unsafe_output_state = True
                    if self._unsafe_output_state:
                        log.critical(
                            "%s: SAFETY: output state UNVERIFIED after connect "
                            "force-OFF — RUN blocked until a verified OFF",
                            self.name,
                        )
                    else:
                        log.info(
                            "%s: SAFETY: forced outputs off on connect "
                            "(crash-recovery guard, readback-verified)",
                            self.name,
                        )
        except Exception:
            self._connected = False
            await self._transport.close()
            raise
        try:
            await self._wdog_arm()
        except Exception:
            # required-mode fail-CLOSED: an arm failure aborts connect
            # (a latched past-trip does NOT raise — see _wdog_arm).
            # best_effort never raises here.
            self._connected = False
            await self._transport.close()
            raise

    async def disconnect(self) -> None:
        if not self._connected:
            return
        await self.emergency_off()
        await self._wdog_disarm()
        await self._transport.close()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        if not self._connected:
            raise RuntimeError(f"{self.name}: instrument not connected")

        if self.mock:
            return self._mock_readings()

        await self._wdog_pet()

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
                            self._build_channel_readings(
                                smu_channel, 0.0, 0.0, resistance_override=0.0
                            )
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

                # --- Compliance check ---
                comp_raw = await self._transport.query(f"print({smu_channel}.source.compliance)")
                in_compliance = comp_raw.strip().lower() == "true"

                extra_meta: dict[str, Any] = {}
                if in_compliance:
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
                                delta_v = (
                                    MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
                                )
                                target_v = current_v + delta_v
                                log.debug(
                                    "Slew rate limited: delta=%.3f V, target=%.3f V",
                                    delta_v,
                                    target_v,
                                )

                            await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
                            self._last_v[smu_channel] = target_v

                readings.extend(
                    self._build_channel_readings(
                        smu_channel, voltage, current, extra_meta=extra_meta
                    )
                )
            except OSError as exc:
                # Transport-level error (USB disconnect, pipe broken) —
                # mark disconnected so scheduler triggers reconnect.
                log.error("%s: transport error on %s: %s", self.name, smu_channel, exc)
                self._connected = False
                raise
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
        if not (
            math.isfinite(p_target)
            and math.isfinite(v_compliance)
            and math.isfinite(i_compliance)
        ):
            # Non-finite would be formatted straight into the SCPI level/limit
            # writes below (and nan defeats the <= 0 guard). Reject at the
            # hardware boundary regardless of caller.
            raise ValueError("P/V/I must be finite")
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
        await self._transport.write(
            f"{smu_channel}.measure.autorangei = {smu_channel}.AUTORANGE_ON"
        )
        await self._transport.write(f"{smu_channel}.source.limitv = {v_compliance}")
        await self._transport.write(f"{smu_channel}.source.limiti = {i_compliance}")
        await self._transport.write(f"{smu_channel}.source.levelv = 0")
        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_ON")
        self._last_v[smu_channel] = 0.0
        self._compliance_count[smu_channel] = 0
        runtime.active = True

    async def stop_source(self, channel: str) -> None:
        smu_channel = normalize_smu_channel(channel)
        runtime = self._channels[smu_channel]

        if self.mock:
            self._last_v[smu_channel] = 0.0
            self._compliance_count[smu_channel] = 0
            runtime.active = False
            runtime.p_target = 0.0
            return

        if not self._connected:
            return

        await self._transport.write(f"{smu_channel}.source.levelv = 0")
        await self._transport.write(f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF")
        # F1 fail-closed: an unverified OFF (readback still ON / unparseable)
        # must RAISE so SafetyManager latches FAULT instead of reporting
        # SAFE_OFF. Raise BEFORE clearing runtime state — the host-side P=const
        # loop must keep treating this channel as active while the output is
        # UNVERIFIED. (A transport error from the query already propagates.)
        if not await self._verify_output_off(smu_channel):
            raise OutputStateUnverifiedError(
                f"{self.name}: {smu_channel} output state UNVERIFIED after "
                f"OUTPUT_OFF (readback did not confirm OFF) — output may still be ON"
            )
        self._last_v[smu_channel] = 0.0
        self._compliance_count[smu_channel] = 0
        runtime.active = False
        runtime.p_target = 0.0

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
        """Force output OFF on the targeted channel(s). NEVER raises.

        Returns True iff, for EVERY targeted channel, the ``levelv = 0`` +
        ``OUTPUT_OFF`` writes succeeded AND the readback verify confirmed the
        output is OFF. Returns False otherwise — the instrument may still be
        sourcing and callers must FAIL CLOSED (CR-2: SafetyManager latches a
        fault instead of reporting SAFE_OFF).
        """
        channels = [normalize_smu_channel(channel)] if channel is not None else list(SMU_CHANNELS)
        for smu_channel in channels:
            runtime = self._channels[smu_channel]
            runtime.active = False
            runtime.p_target = 0.0
            self._last_v[smu_channel] = 0.0
            self._compliance_count[smu_channel] = 0

        if self.mock or not self._connected:
            return True

        all_confirmed = True
        for smu_channel in channels:
            try:
                await self._transport.write(f"{smu_channel}.source.levelv = 0")
                await self._transport.write(
                    f"{smu_channel}.source.output = {smu_channel}.OUTPUT_OFF"
                )
            except Exception as exc:
                log.critical("%s: emergency_off failed on %s: %s", self.name, smu_channel, exc)
                all_confirmed = False
            # SAFETY (Phase 2a G.1): readback-verify each channel.
            # emergency_off is the most critical path — silent failure here
            # is unacceptable. _verify_output_off logs CRITICAL on mismatch.
            # Wrap in try because the caller is already in an emergency path
            # and a raise here would just propagate noise; the CRITICAL log
            # plus the False return are the signalling mechanisms (CR-2).
            try:
                if not await self._verify_output_off(smu_channel):
                    all_confirmed = False
            except Exception as exc:
                log.critical(
                    "%s: emergency_off verify FAILED on %s: %s — instrument may still be sourcing!",
                    self.name,
                    smu_channel,
                    exc,
                )
                all_confirmed = False
        # F2: a full both-channel emergency_off that confirms OFF resolves any
        # connect-time unverified-output block. Only the full scope (channel is
        # None) confirms BOTH channels, so only it may clear the flag.
        if channel is None and all_confirmed:
            self._unsafe_output_state = False
        return all_confirmed

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
            await self._transport.write(_load_wdog_script())
            # DELTA A8a — version stamp: the script is re-uploaded every arm, so
            # a truncated/stale upload passes the fire-and-forget writes silently.
            # Read CRYODAQ_WDOG_VERSION back and refuse to arm on mismatch.
            ver_raw = await self._transport.query("print(CRYODAQ_WDOG_VERSION)")
            try:
                ver = _parse_wdog_number(ver_raw, field="CRYODAQ_WDOG_VERSION")
            except ValueError as exc:
                raise _WatchdogArmError(str(exc)) from exc
            if ver != float(_WDOG_SCRIPT_VERSION):
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
                autonomous_raw = await self._transport.query(
                    "print(cryodaq_wdog_autonomous)"
                )
                self._wdog_autonomous = _parse_wdog_flag(
                    autonomous_raw, field="cryodaq_wdog_autonomous"
                )
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
                "%s: TSP software late-pet watchdog active "
                "(timeout=%.1fs, fw v%d, autonomous=%s)",
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
                    "%s: TSP watchdog arm FAILED and mode=required — refusing to "
                    "connect (fail-closed): %s",
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
        if (
            not self._wdog_enabled
            or self.mock
            or not self._connected
        ):
            return True
        if not self._wdog_armed and not self._wdog_trip_pending:
            return True

        raw = await self._transport.query("print(cryodaq_wdog_tripped)")
        fresh_instrument = raw.strip().lower() == "nil"
        if fresh_instrument:
            if not self._wdog_trip_pending:
                raise ValueError(
                    "watchdog latch disappeared without host-side pending evidence"
                )
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
                "%s: refusing watchdog trip acknowledgment because both-output "
                "OFF could not be readback-verified",
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
            version: float | None = None
            if not force_upload:
                version_raw = await self._transport.query(
                    "print(CRYODAQ_WDOG_VERSION)"
                )
                if version_raw.strip().lower() != "nil":
                    version = _parse_wdog_number(
                        version_raw, field="CRYODAQ_WDOG_VERSION"
                    )
            if version == float(_WDOG_SCRIPT_VERSION):
                await self._transport.write("cryodaq_wdog_acknowledge()")
            else:
                # Explicit operator acknowledgment authorizes consuming a latch
                # left by an older script, but only after verified OFF above.
                # Upgrade and reactivate v3 in this same visible recovery path.
                await self._transport.write(_load_wdog_script())
                uploaded_raw = await self._transport.query(
                    "print(CRYODAQ_WDOG_VERSION)"
                )
                uploaded = _parse_wdog_number(
                    uploaded_raw, field="CRYODAQ_WDOG_VERSION"
                )
                if uploaded != float(_WDOG_SCRIPT_VERSION):
                    raise _WatchdogArmError(
                        "watchdog acknowledgment upgrade version mismatch: "
                        f"{uploaded_raw.strip()!r}"
                    )
                autonomous_raw = await self._transport.query(
                    "print(cryodaq_wdog_autonomous)"
                )
                autonomous = _parse_wdog_flag(
                    autonomous_raw, field="cryodaq_wdog_autonomous"
                )
                if autonomous:
                    raise _WatchdogArmError(
                        "v3 acknowledgment upgrade unexpectedly reported autonomous=1"
                    )
                await self._transport.write(
                    f"CRYODAQ_WDOG_TIMEOUT_S = {self._wdog_timeout_s}"
                )
                await self._transport.write("cryodaq_wdog_run()")
            active_raw = await self._transport.query("print(cryodaq_wdog_active)")
            tripped_raw = await self._transport.query("print(cryodaq_wdog_tripped)")
            active = _parse_wdog_flag(active_raw, field="cryodaq_wdog_active")
            still_tripped = _parse_wdog_flag(
                tripped_raw, field="cryodaq_wdog_tripped"
            )
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
                        "%s: watchdog acknowledgment failed and disarm also "
                        "failed; TSP state UNKNOWN: %s",
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

        Returns True iff the readback confirms output OFF; False on a
        still-on readback or an unparseable response (CRITICAL logged, not
        raised). Transport exceptions from the query DO propagate — callers
        that must not raise (emergency_off) catch them and map to False,
        while stop_source keeps its fail-closed raise-through behavior.
        """
        if self.mock or not self._connected:
            return True
        smu_channel = normalize_smu_channel(channel)
        response = await self._transport.query(
            f"print({smu_channel}.source.output)", timeout_ms=3000
        )
        try:
            if float(response.strip()) > 0.5:
                log.critical(
                    "%s: %s still reports output=%s", self.name, smu_channel, response.strip()
                )
                return False
        except ValueError:
            log.critical(
                "%s: %s unexpected output response: %r", self.name, smu_channel, response.strip()
            )
            return False
        return True

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
                status=ChannelStatus.OK
                if math.isfinite(resistance)
                else ChannelStatus.SENSOR_ERROR,
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
        voltage = (
            math.sqrt(runtime.p_target * resistance)
            if runtime.active and runtime.p_target > 0.0
            else 0.0
        )
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
