"""SafetyManager for CryoDAQ."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.smu_channel import SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500
_CHECK_INTERVAL_S = 1.0


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


class SafetyManager:
    """Single safety state machine with channel-aware Keithley control."""

    def __init__(
        self,
        safety_broker: SafetyBroker,
        *,
        keithley_driver: Any | None = None,
        mock: bool = False,
        data_broker: Any | None = None,
    ) -> None:
        self._broker = safety_broker
        self._keithley = keithley_driver
        self._mock = mock
        self._data_broker = data_broker
        self._state = SafetyState.SAFE_OFF
        self._config = SafetyConfig()
        self._events: deque[SafetyEvent] = deque(maxlen=_MAX_EVENTS)
        self._fault_reason = ""
        self._fault_time = 0.0
        self._recovery_reason = ""
        self._active_sources: set[SmuChannel] = set()

        self._latest: dict[str, tuple[float, float, str]] = {}
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}

        self._queue: asyncio.Queue[Reading] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._collect_task: asyncio.Task[None] | None = None

        self._keithley_patterns = [re.compile(p) for p in self._config.keithley_channel_patterns]
        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []
        self._broker.set_overflow_callback(
            lambda: self._fault("SafetyBroker overflow - data lost")
        )

    def load_config(self, path: Path) -> None:
        if not path.exists():
            logger.warning("safety.yaml not found: %s", path)
            return

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        patterns: list[re.Pattern[str]] = []
        for pattern in raw.get("critical_channels", []):
            try:
                patterns.append(re.compile(pattern))
            except re.error as exc:
                logger.error("Invalid critical_channels regex %r: %s", pattern, exc)

        src_limits = raw.get("source_limits", {})
        self._config = SafetyConfig(
            critical_channels=patterns,
            stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
            heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
            max_safety_backlog=int(raw.get("max_safety_backlog", 100)),
            require_keithley_for_run=bool(raw.get("require_keithley_for_run", True)),
            max_dT_dt_K_per_min=float(raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)),
            require_reason=bool(raw.get("recovery", {}).get("require_reason", True)),
            cooldown_before_rearm_s=float(raw.get("recovery", {}).get("cooldown_before_rearm_s", 60.0)),
            max_power_w=float(src_limits.get("max_power_w", 5.0)),
            max_voltage_v=float(src_limits.get("max_voltage_v", 40.0)),
            max_current_a=float(src_limits.get("max_current_a", 1.0)),
        )
        self._keithley_patterns = [
            re.compile(pattern) for pattern in raw.get("keithley_channels", [".*/smu.*"])
        ]

    async def start(self) -> None:
        self._queue = self._broker.subscribe("safety_manager", maxsize=self._config.max_safety_backlog)
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
        smu_channel = normalize_smu_channel(channel)

        if self._state == SafetyState.FAULT_LATCHED:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"FAULT: {self._fault_reason}"}

        if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"Start not allowed from {self._state.value}"}

        if smu_channel in self._active_sources:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"Channel {smu_channel} already active"}

        ok, reason = self._check_preconditions()
        if not ok:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": reason}

        if p_target > self._config.max_power_w:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W"}
        if v_comp > self._config.max_voltage_v:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V"}
        if i_comp > self._config.max_current_a:
            return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A"}

        if self._state != SafetyState.RUNNING:
            self._transition(
                SafetyState.RUN_PERMITTED,
                f"Start requested for {smu_channel}: P={p_target}W",
                channel=smu_channel,
                value=p_target,
            )

        if self._keithley is None:
            if self._config.require_keithley_for_run and not self._mock:
                self._transition(SafetyState.SAFE_OFF, "Keithley not connected")
                return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": "Keithley not connected"}
        else:
            try:
                await self._keithley.start_source(smu_channel, p_target, v_comp, i_comp)
            except Exception as exc:
                await self._fault(f"Source start failed on {smu_channel}: {exc}", channel=smu_channel)
                return {"ok": False, "state": self._state.value, "channel": smu_channel, "error": str(exc)}

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
        """Live-update P_target on an active channel. Validates against config limits."""
        smu_channel = normalize_smu_channel(channel)

        if self._state == SafetyState.FAULT_LATCHED:
            return {"ok": False, "error": f"FAULT: {self._fault_reason}"}

        if smu_channel not in self._active_sources:
            return {"ok": False, "error": f"Channel {smu_channel} not active"}

        if p_target <= 0:
            return {"ok": False, "error": "p_target must be > 0"}

        if p_target > self._config.max_power_w:
            return {"ok": False, "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W"}

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
                return {"ok": False, "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V"}
            if not self._keithley.mock:
                await self._keithley._transport.write(f"{smu_channel}.source.limitv = {v_comp}")
            runtime.v_comp = v_comp  # update only after successful write

        if i_comp is not None:
            if i_comp <= 0:
                return {"ok": False, "error": "i_comp must be > 0"}
            if i_comp > self._config.max_current_a:
                return {"ok": False, "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A"}
            if not self._keithley.mock:
                await self._keithley._transport.write(f"{smu_channel}.source.limiti = {i_comp}")
            runtime.i_comp = i_comp  # update only after successful write

        logger.info(
            "SAFETY: limits update %s: V_comp=%.1f I_comp=%.3f",
            smu_channel, runtime.v_comp, runtime.i_comp,
        )
        return {"ok": True, "channel": smu_channel, "v_comp": runtime.v_comp, "i_comp": runtime.i_comp}

    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
        if self._state != SafetyState.FAULT_LATCHED:
            return {"ok": False, "state": self._state.value, "error": "Нет активной аварии для подтверждения"}
        if self._config.require_reason and not reason.strip():
            return {"ok": False, "state": self._state.value, "error": "Укажите причину аварии"}

        elapsed = time.monotonic() - self._fault_time
        if elapsed < self._config.cooldown_before_rearm_s:
            remaining = self._config.cooldown_before_rearm_s - elapsed
            return {"ok": False, "state": self._state.value, "error": f"Ожидание: ещё {remaining:.0f}с до разрешения восстановления"}

        self._recovery_reason = reason.strip()
        self._transition(SafetyState.MANUAL_RECOVERY, f"Fault acknowledged: {reason}")
        await self._publish_keithley_channel_states("fault_acknowledged")
        return {"ok": True, "state": self._state.value}

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "fault_reason": self._fault_reason,
            "recovery_reason": self._recovery_reason,
            "channels_tracked": len(self._latest),
            "keithley_connected": self._keithley is not None and getattr(self._keithley, "connected", False),
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
                logger.warning("Failed to publish Keithley channel state for %s: %s", smu_channel, exc)

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
                timestamp=datetime.now(timezone.utc),
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
            asyncio.get_running_loop().create_task(self._publish_state(reason))
        except RuntimeError:
            pass

    async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
        # 1. Latch fault state IMMEDIATELY — no awaits before this.
        #    _transition is synchronous, so request_run() will see
        #    FAULT_LATCHED and reject before any yield point.
        self._fault_reason = reason
        self._fault_time = time.monotonic()
        self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)

        # 2. Now safe to do async cleanup — state already protects us.
        self._active_sources.clear()

        if self._keithley is not None:
            try:
                await self._keithley.emergency_off()
            except Exception as exc:
                logger.critical("FAULT: emergency_off failed: %s", exc)

        fault_channel = channel if channel in {"smua", "smub"} else None
        await self._publish_keithley_channel_states(reason, fault_channel=fault_channel)

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
            await self._ensure_output_off()
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
            self._state = SafetyState.RUNNING
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
                    self._rate_buffers.setdefault(reading.channel, deque(maxlen=120)).append((now, reading.value))
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

        if self._state != SafetyState.RUNNING:
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

        if self._keithley is not None and not self._mock and self._active_sources:
            for smu_channel in sorted(self._active_sources):
                if not self._has_fresh_keithley_data(now, smu_channel):
                    await self._fault(
                        f"Keithley heartbeat timeout {smu_channel}: no data {self._config.heartbeat_timeout_s}s",
                        channel=smu_channel,
                    )
                    return

        for ch, buf in self._rate_buffers.items():
            if not any(pattern.match(ch) for pattern in self._config.critical_channels):
                continue
            if len(buf) < 10:
                continue
            t0, v0 = buf[0]
            t1, v1 = buf[-1]
            dt_s = t1 - t0
            if dt_s <= 0:
                continue
            rate_k_min = abs(v1 - v0) / (dt_s / 60.0)
            if rate_k_min > self._config.max_dT_dt_K_per_min:
                await self._fault(
                    f"Rate limit exceeded {ch}: {rate_k_min:.2f} K/min > {self._config.max_dT_dt_K_per_min}",
                    channel=ch,
                    value=rate_k_min,
                )
                return

    def _has_fresh_keithley_data(self, now: float, smu_channel: SmuChannel) -> bool:
        aliases = {smu_channel, smu_channel.replace("smu", "smu_")}
        for channel, (ts, _value, status) in self._latest.items():
            if status != "ok":
                continue
            if not any(pattern.match(channel) for pattern in self._keithley_patterns):
                continue
            if any(f"/{alias}/" in channel for alias in aliases) and now - ts < self._config.heartbeat_timeout_s:
                return True
        return False

    async def on_interlock_trip(self, interlock_name: str, channel: str, value: float) -> None:
        await self._fault(
            f"Interlock '{interlock_name}' tripped: channel={channel}, value={value:.4g}",
            channel=channel,
            value=value,
        )
