"""SafetyManager for CryoDAQ."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.smu_channel import SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500
_CHECK_INTERVAL_S = 1.0


class SafetyConfigError(RuntimeError):
    """Raised when safety.yaml cannot be loaded in a fail-closed manner.

    Distinct class so engine startup and launcher can recognise it as a
    config error (clean exit code, no auto-restart) rather than a generic
    runtime crash (retryable).
    """


class SafetyState(Enum):
    SAFE_OFF = "safe_off"
    READY = "ready"
    RUN_PERMITTED = "run_permitted"
    RUNNING = "running"
    FAULT_LATCHED = "fault_latched"
    MANUAL_RECOVERY = "manual_recovery"


@dataclass(frozen=True, slots=True)
class SafetyEvent:
    timestamp: datetime
    from_state: SafetyState
    to_state: SafetyState
    reason: str
    channel: str = ""
    value: float = 0.0


@dataclass
class SafetyConfig:
    critical_channels: list[re.Pattern[str]] = field(default_factory=list)
    stale_timeout_s: float = 10.0
    heartbeat_timeout_s: float = 15.0
    max_safety_backlog: int = 100
    require_keithley_for_run: bool = True
    max_dT_dt_K_per_min: float = 5.0
    require_reason: bool = True
    cooldown_before_rearm_s: float = 60.0
    max_power_w: float = 5.0
    max_voltage_v: float = 40.0
    max_current_a: float = 1.0
    keithley_channel_patterns: list[str] = field(default_factory=lambda: [".*/smu.*"])
    scheduler_drain_timeout_s: float = 5.0


class SafetyManager:
    """Single safety state machine with channel-aware Keithley control."""

    def __init__(
        self,
        safety_broker: SafetyBroker,
        *,
        keithley_driver: Any | None = None,
        mock: bool = False,
        data_broker: Any | None = None,
        fault_log_callback: Any | None = None,
    ) -> None:
        self._broker = safety_broker
        self._keithley = keithley_driver
        self._mock = mock
        self._data_broker = data_broker
        self._fault_log_callback = fault_log_callback
        self._state = SafetyState.SAFE_OFF
        self._config = SafetyConfig()
        self._events: deque[SafetyEvent] = deque(maxlen=_MAX_EVENTS)
        self._fault_reason = ""
        self._fault_time = 0.0
        self._recovery_reason = ""
        self._active_sources: set[SmuChannel] = set()
        self._run_permitted_since: float = 0.0  # monotonic timestamp of RUN_PERMITTED entry

        self._latest: dict[str, tuple[float, float, str]] = {}
        # Phase 2c CC I.3: min_points raised from 10 to 60 to match
        # rate_estimator.py's documented noise-suppression recommendation.
        # At 0.5s poll interval the 120s window holds ~240 points;
        # min_points=60 = 30s of data before any rate-based fault decision,
        # which keeps response time acceptable for the 5 K/min threshold
        # while reducing false-positive rate ~2.4x under LS218 ±0.01 K noise.
        self._rate_estimator = RateEstimator(window_s=120.0, min_points=60)

        self._queue: asyncio.Queue[Reading] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._collect_task: asyncio.Task[None] | None = None

        # Strong-ref set for fire-and-forget _publish_state tasks scheduled
        # from synchronous _transition. Without this the event loop only
        # weak-refs the task and GC can silently drop a fault-state broadcast.
        # See DEEP_AUDIT_CC.md A.2/I.2.
        self._pending_publishes: set[asyncio.Task[None]] = set()

        # Hook called from acknowledge_fault to clear external persistence
        # flags (Phase 2a H.1). Engine wires this to writer.clear_disk_full
        # so operator acknowledgment, not auto-recovery, resumes polling.
        self._persistence_failure_clear: Callable[[], None] | None = None

        # Lock that serializes _active_sources mutations across await points.
        # Multiple REQ clients (GUI subprocess + web dashboard + future
        # operator CLI) can race on request_run / request_stop / emergency_off.
        # See DEEP_AUDIT_CC.md I.1.
        self._cmd_lock = asyncio.Lock()

        self._keithley_patterns = [re.compile(p) for p in self._config.keithley_channel_patterns]
        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []
        self._broker.set_overflow_callback(lambda: self._fault("SafetyBroker overflow - data lost"))

    def load_config(self, path: Path) -> None:
        if not path.exists():
            raise SafetyConfigError(
                f"safety.yaml not found at {path} — refusing to start "
                f"SafetyManager without safety configuration"
            )

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        if not isinstance(raw, dict):
            raise SafetyConfigError(
                f"safety.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})"
            )

        raw_patterns = raw.get("critical_channels", [])
        if not isinstance(raw_patterns, list):
            raise SafetyConfigError(
                f"safety.yaml at {path}: critical_channels must be a list, "
                f"got {type(raw_patterns).__name__}"
            )
        if not raw_patterns:
            raise SafetyConfigError(
                f"safety.yaml at {path} has no critical_channels defined — "
                f"refusing to start SafetyManager without critical channel monitoring"
            )

        patterns: list[re.Pattern[str]] = []
        errors: list[str] = []
        for pattern in raw_patterns:
            if not isinstance(pattern, str):
                errors.append(f"  - {pattern!r}: expected string, got {type(pattern).__name__}")
                continue
            try:
                patterns.append(re.compile(pattern))
            except re.error as exc:
                errors.append(f"  - {pattern!r}: {exc}")

        if errors:
            raise SafetyConfigError(
                f"safety.yaml at {path} has invalid critical_channels regex:\n" + "\n".join(errors)
            )

        if not patterns:
            raise SafetyConfigError(f"safety.yaml at {path} produced no valid critical_channels")

        logger.info(
            "SafetyManager config: %d critical channel patterns from %s",
            len(patterns),
            path,
        )

        try:
            src_limits = raw.get("source_limits", {})
            self._config = SafetyConfig(
                critical_channels=patterns,
                stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
                heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
                max_safety_backlog=int(raw.get("max_safety_backlog", 100)),
                require_keithley_for_run=bool(raw.get("require_keithley_for_run", True)),
                max_dT_dt_K_per_min=float(
                    raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)
                ),
                require_reason=bool(raw.get("recovery", {}).get("require_reason", True)),
                cooldown_before_rearm_s=float(
                    raw.get("recovery", {}).get("cooldown_before_rearm_s", 60.0)
                ),
                max_power_w=float(src_limits.get("max_power_w", 5.0)),
                max_voltage_v=float(src_limits.get("max_voltage_v", 40.0)),
                max_current_a=float(src_limits.get("max_current_a", 1.0)),
                scheduler_drain_timeout_s=float(raw.get("scheduler_drain_timeout_s", 5.0)),
            )
            self._keithley_patterns = [
                re.compile(pattern) for pattern in raw.get("keithley_channels", [".*/smu.*"])
            ]
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SafetyConfigError(
                f"safety.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
            ) from exc

    async def start(self) -> None:
        self._queue = self._broker.subscribe(
            "safety_manager", maxsize=self._config.max_safety_backlog
        )
        self._broker.freeze()
        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
        await self._publish_state("initial")
        await self._publish_keithley_channel_states("initial")

    async def stop(self) -> None:
        if self._active_sources:
            await self._safe_off("system stop", channels=set(self._active_sources))

        for task in (self._collect_task, self._monitor_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._collect_task = None
        self._monitor_task = None

    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def fault_reason(self) -> str:
        return self._fault_reason

    async def request_run(
        self,
        p_target: float,
        v_comp: float,
        i_comp: float,
        *,
        channel: str | None = None,
    ) -> dict[str, Any]:
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)

            if self._state == SafetyState.FAULT_LATCHED:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"FAULT: {self._fault_reason}",
                }

            if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"Start not allowed from {self._state.value}",
                }

            if smu_channel in self._active_sources:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"Channel {smu_channel} already active",
                }

            ok, reason = self._check_preconditions()
            if not ok:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": reason,
                }

            if p_target > self._config.max_power_w:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
                }
            if v_comp > self._config.max_voltage_v:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
                }
            if i_comp > self._config.max_current_a:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
                }

            if self._state != SafetyState.RUNNING:
                self._run_permitted_since = time.monotonic()
                self._transition(
                    SafetyState.RUN_PERMITTED,
                    f"Start requested for {smu_channel}: P={p_target}W",
                    channel=smu_channel,
                    value=p_target,
                )

            if self._keithley is None:
                if self._config.require_keithley_for_run and not self._mock:
                    self._transition(SafetyState.SAFE_OFF, "Keithley not connected")
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": "Keithley not connected",
                    }
            else:
                try:
                    await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
                except Exception as exc:
                    await self._fault(
                        f"Source start failed on {smu_channel}: {exc}", channel=smu_channel
                    )
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": str(exc),
                    }

                # CRITICAL safety reconciliation (Codex Phase 1 review P0-2):
                # _fault() runs OUTSIDE _cmd_lock — a fail-on-silence /
                # rate-limit / interlock fault can fire while we are awaiting
                # start_source(). When that happens, _fault has already issued
                # emergency_off and latched FAULT_LATCHED. We must NOT add the
                # channel to _active_sources, and as defense-in-depth we
                # re-issue emergency_off in case start_source's last write
                # interleaved after the fault's OUTPUT_OFF.
                if self._state == SafetyState.FAULT_LATCHED:
                    try:
                        await self._keithley.emergency_off()
                    except Exception as exc:
                        logger.critical("FAULT after start_source: emergency_off failed: %s", exc)
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": f"Fault during start: {self._fault_reason}",
                    }

            self._active_sources.add(smu_channel)
            if self._state != SafetyState.RUNNING:
                self._transition(
                    SafetyState.RUNNING,
                    f"Source {smu_channel} enabled: P={p_target}W",
                    channel=smu_channel,
                    value=p_target,
                )
            await self._publish_keithley_channel_states(f"run:{smu_channel}")
            return {
                "ok": True,
                "state": self._state.value,
                "channel": smu_channel,
                "active_channels": sorted(self._active_sources),
            }

    async def request_stop(self, *, channel: str | None = None) -> dict[str, Any]:
        async with self._cmd_lock:
            channels = self._resolve_channels(channel)
            if self._state == SafetyState.FAULT_LATCHED:
                await self._ensure_output_off(channel)
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channels": sorted(channels),
                    "error": "System is fault-latched - acknowledge_fault required",
                }

            await self._safe_off("Operator stop", channels=channels)
            await self._publish_keithley_channel_states("stop")
            return {
                "ok": True,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
            }

    async def emergency_off(self, *, channel: str | None = None) -> dict[str, Any]:
        async with self._cmd_lock:
            channels = self._resolve_channels(channel)
            await self._ensure_output_off(channel)
            self._active_sources.difference_update(channels)
            await self._publish_keithley_channel_states("emergency_off")

            if self._state == SafetyState.FAULT_LATCHED:
                return {
                    "ok": True,
                    "state": self._state.value,
                    "channels": sorted(channels),
                    "active_channels": sorted(self._active_sources),
                    "latched": True,
                    "warning": "Outputs disabled but fault remains latched",
                }

            if not self._active_sources:
                self._transition(SafetyState.SAFE_OFF, "Operator emergency off")

            return {
                "ok": True,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
            }

    async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
        """Live-update P_target on an active channel. Validates against config limits.

        Updates ``runtime.p_target`` in-memory. The hardware voltage is NOT changed
        here directly — the P=const regulation loop in
        ``Keithley2604B.read_channels()`` reads ``runtime.p_target`` on every poll
        cycle and recomputes ``target_v = sqrt(p_target * R)``, so the instrument
        output converges within one poll interval (typically ≤1 s).

        This is intentional: slew-rate limiting and compliance checks live in the
        regulation loop and must not be bypassed by direct SCPI writes here.
        """
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)

            if self._state == SafetyState.FAULT_LATCHED:
                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}

            if smu_channel not in self._active_sources:
                return {"ok": False, "error": f"Channel {smu_channel} not active"}

            if p_target <= 0:
                return {"ok": False, "error": "p_target must be > 0"}

            if p_target > self._config.max_power_w:
                return {
                    "ok": False,
                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
                }

            if self._keithley is None:
                return {"ok": False, "error": "Keithley not connected"}

            runtime = self._keithley._channels.get(smu_channel)
            if runtime is None or not runtime.active:
                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}

            old_p = runtime.p_target
            runtime.p_target = p_target
            logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)

            return {"ok": True, "channel": smu_channel, "p_target": p_target}

    async def update_limits(
        self,
        *,
        channel: str | None = None,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> dict[str, Any]:
        """Live-update V/I compliance limits. Validates against config limits."""
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)

            if self._state == SafetyState.FAULT_LATCHED:
                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}

            if smu_channel not in self._active_sources:
                return {"ok": False, "error": f"Channel {smu_channel} not active"}

            if self._keithley is None:
                return {"ok": False, "error": "Keithley not connected"}

            runtime = self._keithley._channels.get(smu_channel)
            if runtime is None or not runtime.active:
                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}

            if v_comp is not None:
                if v_comp <= 0:
                    return {"ok": False, "error": "v_comp must be > 0"}
                if v_comp > self._config.max_voltage_v:
                    return {
                        "ok": False,
                        "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
                    }
                if not self._keithley.mock:
                    await self._keithley._transport.write(f"{smu_channel}.source.limitv = {v_comp}")
                runtime.v_comp = v_comp  # update only after successful write

            if i_comp is not None:
                if i_comp <= 0:
                    return {"ok": False, "error": "i_comp must be > 0"}
                if i_comp > self._config.max_current_a:
                    return {
                        "ok": False,
                        "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
                    }
                if not self._keithley.mock:
                    await self._keithley._transport.write(f"{smu_channel}.source.limiti = {i_comp}")
                runtime.i_comp = i_comp  # update only after successful write

            logger.info(
                "SAFETY: limits update %s: V_comp=%.1f I_comp=%.3f",
                smu_channel,
                runtime.v_comp,
                runtime.i_comp,
            )
            return {
                "ok": True,
                "channel": smu_channel,
                "v_comp": runtime.v_comp,
                "i_comp": runtime.i_comp,
            }

    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
        async with self._cmd_lock:
            if self._state != SafetyState.FAULT_LATCHED:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "error": "Нет активной аварии для подтверждения",
                }
            if self._config.require_reason and not reason.strip():
                return {"ok": False, "state": self._state.value, "error": "Укажите причину аварии"}

            elapsed = time.monotonic() - self._fault_time
            if elapsed < self._config.cooldown_before_rearm_s:
                remaining = self._config.cooldown_before_rearm_s - elapsed
                return {
                    "ok": False,
                    "state": self._state.value,
                    "error": f"Ожидание: ещё {remaining:.0f}с до разрешения восстановления",
                }

            self._recovery_reason = reason.strip()
            # Phase 2a H.1: clear persistence-failure latch on the writer
            # via the engine-wired callback. This is what unblocks scheduler
            # polling — DiskMonitor only logs recovery, it does not clear.
            if self._persistence_failure_clear is not None:
                try:
                    self._persistence_failure_clear()
                except Exception as exc:
                    logger.error("persistence_failure_clear callback failed: %s", exc)
            self._transition(SafetyState.MANUAL_RECOVERY, f"Fault acknowledged: {reason}")
            await self._publish_keithley_channel_states("fault_acknowledged")
            return {"ok": True, "state": self._state.value}

    def set_persistence_failure_clear(self, callback: Callable[[], None]) -> None:
        """Register a sync callback that clears external persistence-failure
        flags (Phase 2a H.1). Called from acknowledge_fault."""
        self._persistence_failure_clear = callback

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "fault_reason": self._fault_reason,
            "recovery_reason": self._recovery_reason,
            "channels_tracked": len(self._latest),
            "keithley_connected": self._keithley is not None
            and getattr(self._keithley, "connected", False),
            "active_channels": sorted(self._active_sources),
            "mock": self._mock,
        }

    def get_events(self) -> list[SafetyEvent]:
        return list(self._events)

    def on_state_change(self, callback: Callable[[SafetyState, SafetyState, str], Any]) -> None:
        self._on_state_change.append(callback)

    async def _publish_state(self, reason: str = "") -> None:
        if self._data_broker is None:
            return
        reading = Reading.now(
            channel="analytics/safety_state",
            value=0.0,
            unit="",
            instrument_id="safety_manager",
            metadata={"state": self._state.value, "reason": reason},
        )
        try:
            await self._data_broker.publish(reading)
        except Exception as exc:
            logger.warning("Failed to publish safety state: %s", exc)

    async def _publish_keithley_channel_states(
        self,
        reason: str = "",
        *,
        fault_channel: str | None = None,
    ) -> None:
        if self._data_broker is None:
            return

        for smu_channel in ("smua", "smub"):
            if fault_channel == smu_channel:
                state = "fault"
                value = -1.0
            elif smu_channel in self._active_sources:
                state = "on"
                value = 1.0
            else:
                state = "off"
                value = 0.0

            reading = Reading.now(
                channel=f"analytics/keithley_channel_state/{smu_channel}",
                value=value,
                unit="",
                instrument_id="safety_manager",
                metadata={"state": state, "channel": smu_channel, "reason": reason},
            )
            try:
                await self._data_broker.publish(reading)
            except Exception as exc:
                logger.warning(
                    "Failed to publish Keithley channel state for %s: %s", smu_channel, exc
                )

    def _transition(
        self,
        new_state: SafetyState,
        reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
    ) -> None:
        old_state = self._state
        self._state = new_state
        self._events.append(
            SafetyEvent(
                timestamp=datetime.now(UTC),
                from_state=old_state,
                to_state=new_state,
                reason=reason,
                channel=channel,
                value=value,
            )
        )

        level = logging.CRITICAL if new_state == SafetyState.FAULT_LATCHED else logging.INFO
        logger.log(level, "SAFETY: %s -> %s | %s", old_state.value, new_state.value, reason)

        for callback in self._on_state_change:
            try:
                callback(old_state, new_state, reason)
            except Exception:
                logger.exception("State change callback failed")

        try:
            task = asyncio.get_running_loop().create_task(
                self._publish_state(reason),
                name=f"safety_publish_{new_state.value}",
            )
            self._pending_publishes.add(task)
            task.add_done_callback(self._pending_publishes.discard)
        except RuntimeError:
            # No running loop (sync caller during tests). Publish skipped.
            pass

    async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
        # Early-return guard: ignore concurrent re-entries while already latched.
        # Multiple call sites (SafetyBroker overflow, monitoring loop, channel
        # faults, start_source failure) can fire in the same tick. Without
        # this guard, a second call would overwrite _fault_reason, emit
        # duplicate events + log entries, and queue a redundant emergency_off.
        # The check is safe under asyncio single-threaded semantics: state is
        # mutated synchronously below before any await, so a later call sees
        # FAULT_LATCHED and exits.
        if self._state == SafetyState.FAULT_LATCHED:
            logger.info(
                "_fault() re-entry ignored (already latched); new reason=%s channel=%s",
                reason,
                channel or "-",
            )
            return

        # 1. Latch fault state IMMEDIATELY — no awaits before this.
        #    _transition is synchronous, so request_run() will see
        #    FAULT_LATCHED and reject before any yield point.
        self._fault_reason = reason
        self._fault_time = time.monotonic()
        self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)

        # 2. Now safe to do async cleanup — state already protects us.
        self._active_sources.clear()

        if self._keithley is not None:
            # Hardware shutdown must complete even if our caller is cancelled.
            # asyncio.shield prevents outer cancellation from interrupting
            # emergency_off. We catch CancelledError to ensure the shielded
            # task finishes before re-raising.
            shutdown_task = asyncio.create_task(self._keithley.emergency_off())
            try:
                await asyncio.shield(shutdown_task)
            except asyncio.CancelledError:
                logger.critical(
                    "FAULT: _fault() cancelled but emergency_off is shielded; "
                    "waiting for hardware shutdown to complete"
                )
                try:
                    await shutdown_task
                except Exception as exc:
                    logger.critical("FAULT: shielded emergency_off failed: %s", exc)
                raise
            except Exception as exc:
                logger.critical("FAULT: emergency_off failed: %s", exc)

        # 4. Post-mortem log emission — shielded — MUST happen after hardware
        #    shutdown but BEFORE optional broker publish. Previously this came
        #    after publish, creating an escape path if publish was cancelled
        #    (Jules Round 2 Q1).
        if self._fault_log_callback is not None:
            log_task = asyncio.create_task(
                self._fault_log_callback(
                    source="safety_manager",
                    message=f"Safety fault: {reason}",
                    channel=channel,
                    value=value,
                )
            )
            try:
                await asyncio.shield(log_task)
            except asyncio.CancelledError:
                logger.critical(
                    "FAULT: _fault() cancelled after hardware shutdown; "
                    "waiting for post-mortem log emission to complete"
                )
                try:
                    await log_task
                except Exception as exc:
                    logger.error("Failed to write safety fault to operator_log: %s", exc)
                raise
            except Exception as exc:
                logger.error("Failed to write safety fault to operator_log: %s", exc)

        # 5. Broadcast Keithley channel states — best-effort, non-critical.
        #    Publish failure does NOT prevent fault latching or post-mortem
        #    logging because those already completed above.
        fault_channel = channel if channel in {"smua", "smub"} else None
        try:
            await self._publish_keithley_channel_states(reason, fault_channel=fault_channel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Failed to publish Keithley channel states: %s", exc)

    async def _ensure_output_off(self, channel: str | None = None) -> None:
        if self._keithley is None:
            return
        try:
            await self._keithley.emergency_off(channel)
        except TypeError:
            if channel is None:
                await self._keithley.emergency_off()
            else:
                raise
        except Exception as exc:
            logger.critical("_ensure_output_off failed: %s", exc)

    async def _safe_off(self, reason: str, *, channels: set[SmuChannel]) -> None:
        if self._state == SafetyState.FAULT_LATCHED:
            # Jules review: shield emergency_off in fault-latched cleanup path
            # so cancellation cannot interrupt the defensive hardware shutdown.
            off_task = asyncio.create_task(self._ensure_output_off())
            try:
                await asyncio.shield(off_task)
            except asyncio.CancelledError:
                logger.warning(
                    "_safe_off cancelled while fault latched; "
                    "waiting for hardware shutdown to complete"
                )
                try:
                    await off_task
                except Exception as exc:
                    logger.critical("_safe_off shielded emergency_off failed: %s", exc)
                raise
            except Exception as exc:
                logger.error("_ensure_output_off in _safe_off failed: %s", exc)
            logger.warning("_safe_off rejected while fault latched")
            return

        if self._keithley is not None:
            for smu_channel in sorted(channels):
                try:
                    await self._keithley.stop_source(smu_channel)
                except Exception as exc:
                    logger.error("stop_source(%s) failed: %s", smu_channel, exc)

        self._active_sources.difference_update(channels)
        if self._active_sources:
            self._transition(
                SafetyState.RUNNING,
                f"Partial stop: {sorted(channels)}, still active: {sorted(self._active_sources)}",
            )
            return

        self._transition(SafetyState.SAFE_OFF, reason)

    def _resolve_channels(self, channel: str | None) -> set[SmuChannel]:
        if channel is not None:
            return {normalize_smu_channel(channel)}
        if self._active_sources:
            return set(self._active_sources)
        return {normalize_smu_channel(None)}

    def _check_preconditions(self) -> tuple[bool, str]:
        now = time.monotonic()

        for pattern in self._config.critical_channels:
            matched = False
            for ch, (ts, value, status) in self._latest.items():
                if not pattern.match(ch):
                    continue
                matched = True
                age = now - ts
                if age > self._config.stale_timeout_s:
                    return False, f"Stale data: {ch} ({age:.1f}s)"
                if status != "ok":
                    return False, f"Channel {ch} status={status}"
                if math.isnan(value) or math.isinf(value):
                    return False, f"Channel {ch} invalid value {value}"
            if not matched and not self._mock:
                return False, f"No data for critical channel: {pattern.pattern}"

        if self._config.require_keithley_for_run and not self._mock:
            if self._keithley is None:
                return False, "Keithley not connected"
            if not getattr(self._keithley, "connected", False):
                return False, "Keithley connected=False"

        if self._state == SafetyState.FAULT_LATCHED:
            return False, f"Active fault: {self._fault_reason}"

        return True, ""

    async def _collect_loop(self) -> None:
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()
                now = time.monotonic()
                self._latest[reading.channel] = (now, reading.value, reading.status.value)
                if reading.unit == "K":
                    self._rate_estimator.push(reading.channel, now, reading.value)
        except asyncio.CancelledError:
            return

    async def _monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_CHECK_INTERVAL_S)
                await self._run_checks()
        except asyncio.CancelledError:
            return

    async def _run_checks(self) -> None:
        now = time.monotonic()

        if self._state == SafetyState.MANUAL_RECOVERY:
            ok, _ = self._check_preconditions()
            if ok:
                self._transition(SafetyState.READY, "Recovery preconditions restored")
            return

        if self._state == SafetyState.SAFE_OFF:
            ok, _ = self._check_preconditions()
            if ok and self._latest:
                self._transition(SafetyState.READY, "All preconditions satisfied")
            return

        # Active monitoring states: RUN_PERMITTED (source starting) and
        # RUNNING (source on). Both need stale/rate/heartbeat checks because
        # a stuck start_source() call must not silently disable monitoring.
        if self._state not in (SafetyState.RUN_PERMITTED, SafetyState.RUNNING):
            return

        for pattern in self._config.critical_channels:
            for ch, (ts, _value, _status) in self._latest.items():
                if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
                    await self._fault(f"Устаревшие данные канала {ch}", channel=ch)
                    return

        for ch, (_ts, value, status) in self._latest.items():
            if any(pattern.match(ch) for pattern in self._config.critical_channels):
                if status != "ok":
                    await self._fault(f"Channel {ch} status={status}", channel=ch, value=value)
                    return
                if math.isnan(value) or math.isinf(value):
                    await self._fault(f"Channel {ch}: NaN/Inf", channel=ch, value=value)
                    return

        if self._keithley is not None and not self._mock:
            if self._active_sources:
                for smu_channel in sorted(self._active_sources):
                    if not self._has_fresh_keithley_data(now, smu_channel):
                        await self._fault(
                            f"Keithley heartbeat timeout {smu_channel}: no data {self._config.heartbeat_timeout_s}s",  # noqa: E501
                            channel=smu_channel,
                        )
                        return
            elif (
                self._state == SafetyState.RUN_PERMITTED
                and self._run_permitted_since > 0
                and now - self._run_permitted_since > self._config.heartbeat_timeout_s
            ):
                # Stuck start_source(): sitting in RUN_PERMITTED longer than
                # heartbeat timeout without _active_sources being populated.
                await self._fault(
                    f"start_source() stuck: RUN_PERMITTED for "
                    f">{self._config.heartbeat_timeout_s:.0f}s without source activation",
                )
                return

        for ch in self._rate_estimator.channels():
            if not any(pattern.match(ch) for pattern in self._config.critical_channels):
                continue
            rate = self._rate_estimator.get_rate(ch)
            if rate is None:
                continue
            abs_rate = abs(rate)
            if abs_rate > self._config.max_dT_dt_K_per_min:
                await self._fault(
                    f"Rate limit exceeded {ch}: {abs_rate:.2f} K/min > {self._config.max_dT_dt_K_per_min}",  # noqa: E501
                    channel=ch,
                    value=abs_rate,
                )
                return

    def _has_fresh_keithley_data(self, now: float, smu_channel: SmuChannel) -> bool:
        aliases = {smu_channel, smu_channel.replace("smu", "smu_")}
        for channel, (ts, _value, status) in self._latest.items():
            if status != "ok":
                continue
            if not any(pattern.match(channel) for pattern in self._keithley_patterns):
                continue
            if (
                any(f"/{alias}/" in channel for alias in aliases)
                and now - ts < self._config.heartbeat_timeout_s
            ):
                return True
        return False

    async def on_interlock_trip(
        self,
        interlock_name: str,
        channel: str,
        value: float,
        *,
        action: str = "emergency_off",
    ) -> None:
        """Handle an interlock trip from InterlockEngine.

        ``action="emergency_off"`` (default, backwards-compatible):
            Full fault latch — outputs off, FAULT_LATCHED, operator must
            acknowledge_fault to recover.

        ``action="stop_source"``:
            Soft stop — outputs off, transition to SAFE_OFF, no fault latch.
            Operator can call ``request_run`` again as soon as the underlying
            condition (e.g. detector_warmup) clears.

        Any other action escalates to a full fault as the safe default.

        See DEEP_AUDIT_CODEX.md I.1.
        """
        reason = f"Interlock '{interlock_name}' tripped: channel={channel}, value={value:.4g}"

        if action == "emergency_off":
            logger.critical("INTERLOCK emergency_off: %s", reason)
            await self._fault(reason, channel=channel, value=value)
            return

        if action == "stop_source":
            logger.warning("INTERLOCK stop_source: %s", reason)
            # Soft stop: outputs off, no fault latch.
            async with self._cmd_lock:
                if self._keithley is not None:
                    try:
                        await self._keithley.emergency_off()
                    except Exception as exc:
                        logger.error(
                            "stop_source interlock: emergency_off failed: %s — "
                            "escalating to full fault",
                            exc,
                        )
                        # The lock is released when this `async with` block
                        # exits via the `return` below. _fault itself is
                        # unlocked, so it does not deadlock — but it WILL
                        # serialize behind the lock until _fault returns.
                        await self._fault(
                            f"{reason} (emergency_off failed: {exc})",
                            channel=channel,
                            value=value,
                        )
                        return
                self._active_sources.clear()
                await self._publish_keithley_channel_states(f"interlock_stop:{interlock_name}")
                if self._state not in (SafetyState.FAULT_LATCHED, SafetyState.MANUAL_RECOVERY):
                    self._transition(
                        SafetyState.SAFE_OFF,
                        f"Interlock stop_source: {interlock_name}",
                        channel=channel,
                        value=value,
                    )
            return

        # Unknown action — fail-safe to a full fault rather than ignore.
        logger.critical(
            "Unknown interlock action %r for '%s' — escalating to full fault",
            action,
            interlock_name,
        )
        await self._fault(
            f"Unknown interlock action {action!r}: {reason}",
            channel=channel,
            value=value,
        )

    async def on_persistence_failure(self, reason: str) -> None:
        """Called by SQLiteWriter when persistent storage fails (disk full etc).

        Immediately triggers ``_fault`` with a persistence-failure reason.
        ``_fault`` is intentionally NOT wrapped in ``_cmd_lock`` so this can
        be called from any context (including the writer thread via
        :func:`asyncio.run_coroutine_threadsafe`). The fault path itself
        latches the state synchronously before any await, so concurrent
        ``request_run`` callers will see ``FAULT_LATCHED`` and abort.
        """
        logger.critical("PERSISTENCE FAILURE: %s — triggering safety fault", reason)
        await self._fault(
            f"Persistence failure: {reason}",
            channel="",
            value=0.0,
        )
