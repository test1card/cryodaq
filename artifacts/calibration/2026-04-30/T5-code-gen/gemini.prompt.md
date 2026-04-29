# Code Generation — Hypothetical update_target() SCPI Write

This is exploratory — DO NOT actually recommend merging this.

Current update_target() uses delayed-update design: sets runtime.p_target,
trusts the P=const regulation loop to pick it up on next poll cycle (≤1s).

Hypothetical: add direct SCPI write to update_target() so hardware responds
immediately, BUT preserve all safety properties (slew-rate limiting,
compliance checks). Show how you would implement this.

## Reference materials

```python
# Current update_target() body (safety_manager.py:430)
async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
    """Live-update P_target on an active channel. Validates against config limits.
    [Delayed-update design — hardware updates on next poll cycle via P=const loop]
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
        logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)
        return {"ok": True, "channel": smu_channel, "p_target": p_target}

# start_source() pattern (keithley_2604b.py:223) — sets initial levelv=0
async def start_source(self, channel, p_target, v_compliance, i_compliance):
    smu_channel = normalize_smu_channel(channel)
    runtime = self._channels[smu_channel]
    runtime.p_target = p_target
    # ... configure SMU ...
    await self._transport.write(f"{smu_channel}.source.levelv = 0")  # starts at 0
    self._last_v[smu_channel] = 0.0
    runtime.active = True

# P=const regulation loop (keithley_2604b.py read_channels)
MAX_DELTA_V_PER_STEP = 0.5  # V — slew rate limit
# Called every poll cycle:
if abs(current) > _I_MIN_A and resistance > 0:
    target_v = math.sqrt(runtime.p_target * resistance)
    target_v = max(0.0, min(target_v, runtime.v_comp))
    current_v = self._last_v[smu_channel]
    delta_v = target_v - current_v
    if abs(delta_v) > MAX_DELTA_V_PER_STEP:
        delta_v = MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
        target_v = current_v + delta_v
    await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
    self._last_v[smu_channel] = target_v
```

## Output format
Full method body in Python (update_target + any helpers needed).
Then 3-5 sentences on design choices and tradeoffs vs the delayed-update approach.

Key constraints your implementation must satisfy:
1. Must respect MAX_DELTA_V_PER_STEP = 0.5 V slew limit
2. Must not bypass compliance checks (v_comp, i_comp)
3. Must not break the P=const loop on next cycle
4. Must work with the existing _last_v tracking

Hard cap 1500 words. No preamble.
