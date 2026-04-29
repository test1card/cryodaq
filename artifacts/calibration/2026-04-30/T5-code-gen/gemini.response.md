YOLO mode is enabled. All tool calls will be automatically approved.
YOLO mode is enabled. All tool calls will be automatically approved.
```python
import math
from typing import Any

async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
    """Live-update P_target on an active channel. Validates against config limits.
    [Hypothetical Direct-SCPI update design]
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
            return {"ok": False, "error": f"P={p_target}W exceeds limit"}
        if self._keithley is None:
            return {"ok": False, "error": "Keithley not connected"}
            
        runtime = self._keithley._channels.get(smu_channel)
        if runtime is None or not runtime.active:
            return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}
            
        old_p = runtime.p_target
        runtime.p_target = p_target
        
        # Apply the immediate SCPI write step
        await self._apply_immediate_step(smu_channel, runtime, p_target)
        
        logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)
        return {"ok": True, "channel": smu_channel, "p_target": p_target}

async def _apply_immediate_step(self, smu_channel: str, runtime: Any, p_target: float) -> None:
    """Helper: Calculates and applies a single slew-limited voltage step immediately."""
    # Rely on the most recently cached measurements from the background loop
    current = getattr(runtime, "last_i", 0.0) 
    resistance = getattr(runtime, "last_r", 0.0)
    _I_MIN_A = 1e-6
    
    if abs(current) > _I_MIN_A and resistance > 0:
        # Calculate ideal V for the new P_target
        target_v = math.sqrt(p_target * resistance)
        
        # Enforce compliance limits
        target_v = max(0.0, min(target_v, runtime.v_comp))
        
        # Enforce slew rate limit
        MAX_DELTA_V_PER_STEP = 0.5
        current_v = self._keithley._last_v.get(smu_channel, 0.0)
        delta_v = target_v - current_v
        
        if abs(delta_v) > MAX_DELTA_V_PER_STEP:
            delta_v = MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
            target_v = current_v + delta_v
            
        # Immediate SCPI write
        await self._keithley._transport.write(f"{smu_channel}.source.levelv = {target_v:.6f}")
        # Sync state so the P=const loop resumes cleanly on the next cycle
        self._keithley._last_v[smu_channel] = target_v
```

**Design Choices and Tradeoffs**
This approach minimizes hardware latency by injecting an immediate SCPI command out-of-band instead of waiting up to 1 second for the next polling cycle. By updating `self._keithley._last_v`, we perfectly preserve state synchronization; the next iteration of the background loop simply treats our immediate write as its starting point and will continue stepping if the target hasn't been reached yet. However, this introduces tight architectural coupling, forcing `SafetyManager` to duplicate the Keithley's regulation logic and rely on its internal transport and cached state. Furthermore, it risks transport contention if `_transport.write` is invoked concurrently with the background polling loop, which could result in interleaved/mangled SCPI commands if the underlying socket transport isn't heavily shielded with async locks.
