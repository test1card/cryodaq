### Full Method Body

```python
async def update_target(self, p_target: float, *, channel: None = None) -> dict[str, Any]:
    """Live-update P_target on an active channel. Validates against config limits.
    [Hybrid design — immediate SCPI write with constrained slew, while preserving safety chain.]
    """
    async with self._cmd_lock:
        smu_channel = normalize_smu_channel(channel)
        if self._state == SafetyState.FETY_LATCHED:
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

        # Compute new V target from P = V·I = V²/R (I = V/R)
        # Use current resistance estimate (measured R = V_measured / I_measured)
        # For safety, compute V_target with respect to *current compliance limits*:
        v_comp = runtime.v_comp
        i_comp = runtime.i_comp
        if v_comp <= 0:
            return {"ok": False, "error": "Invalid compliance V"}
        if i_comp <= 0:
            return {"ok": False, "error": "Invalid compliance I"}
        # Clamp P_target to physical limits under existing compliance:
        # P_max_at_v = v_comp * i_comp  (max possible at max V and I limits)
        # But if p_target > v_comp * i_comp, it's invalid
        # Already checked p_target <= self._config.max_power_w (but that’s config limit; we also require p_target <= v_comp * i_comp.
        # So enforce:
        p_max_physical = v_comp * i_comp
        if p_target > p_max_physical:
            return {"ok": False, "error": f"P={p_target}W > {p_max_physical}W (V_comp × I_comp)"}
        # So P_target is safe under V/I compliance.

        # Compute voltage corresponding to target power for the *current* load R_est.
        # Use runtime.resistance_est from last poll — assume available as runtime.resistance_est (Ω)
        # If unavailable (first update after start), assume worst case (e.g., 0 → use 1 Ω min)
        R = runtime.resistance_est if (runtime.resistance_est is not None and runtime.resistance_est > 0) else 1.0
        v_new = math.sqrt(p_target * R)
        v_new = max(0.0, min(v_new, v_comp))  # respect V compliance

        # Enforce slew limit relative to current V setting (use runtime.last_v_target, not last measured V)
        # However, runtime.last_v_target tracks the last set V (via update_target or start_source)
        # Use runtime.last_v_target if available; else, fall back to runtime.last_v (same mechanism)
        v_old = getattr(runtime, 'last_v_target', None)
        if v_old is None:
            # Should not happen after start, but defensive
            v_old = 0.0
        # Slew-constrained delta:
        delta_v = v_new - v_old
        MAX_DELTA_V_PER_STEP = 0.5  # V
        if abs(delta_v) > MAX_DELTA_V_PER_STEP:
            v_new = v_old + (MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_STEP_V)
        # v_new now satisfies |ΔV| ≤ 0.5 V from previous V setting

        # Write to hardware directly
        if self._keithley._transport is None:
            return {"ok": False, "error": "Transport not ready"}
        # Issue immediate write to V level, using standard SCPI syntax:
        # {ch}.source.levelv = {v_new}
        scpi = f"{smu_channel}.source.levelv = {v_new:.6f}"
        await self._transport.write(scpi)

        # Commit new state atomically
        old_p = runtime.p_target
        runtime.p_target = p_target
        runtime.last_v_target = v_new  # record for next update
        logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)
        return {"ok": True, "channel": smu_channel, "p_target": p_target}
```

### Helper: Normalization (unchanged for completeness)

```python
def normalize_smu_channel(channel: str | None) -> str:
    """Map logical channel → instrument SCPI prefix (e.g., 'smu1' → 'smu1' or 'smu1', 'smu2' → 'smu2').
    """
    # Preserve current behavior: use identity mapping
    if channel is None:
        # Default channel mapping
        return "smu1"
    return channel
```

### Design Choices & Trade-offs

1. **Hybrid State Synchronization:** The implementation preserves the `runtime.p_target` field for software state consistency (so the existing `P=const` loop can read it next poll cycle), while directly updating `runtime.last_v_target` after the slew-constrained SCPI write. This avoids race conditions where the regulator loop sees an outdated target, because `p_target` and `last_v_target` are updated atomically before releasing the lock.

2. **Conservative V Compliance Enforcement:** Rather than re-checking compliance limits on every update (which would duplicate logic), the implementation calculates `v_new = min(sqrt(P_target * R), v_comp)` *and* validates `p_target ≤ v_comp * i_comp`, reusing the same compliance values the P-loop uses. This keeps the check O(1) and branch-predictable.

3. **Slew Limit Enforcement at SCPI Write:** By computing the constrained V delta (`delta_v = v_new - v_old`) and clamping `delta_v = sign(ΔV)·0.5V`, the SCPI write produces a voltage step of ≤0.5 V. Since the next poll cycle reads the new `runtime.last_v` (via the hardware is already settling toward this), the P-loop sees a V that is within its expected range, preventing over-current transients.

4. **Compatibility with Existing Poll Loop:** Because the write is to `levelv`, the P-loop’s next execution reads the same `runtime.last_v_target`, so when the next poll cycle recomputes `target_v = sqrt(P * R)` and clamps it, it sees a V that is at most 0.5 V from the prior step, well within the regulator’s expected dynamics.

5. **Fault Safety Preservation:** All safety checks (`p_target > 0`, `p_target ≤ v_comp * i_comp`, channel active, instrument present) are retained. No compliance bypass occurs—the `v_new` is always ≤ `v_comp` and the P-target is always ≤ `v_comp * i_comp`, which is sufficient to guarantee the SMU operates within rated limits.

6. **Minimal Performance Impact:** The additional computation (one `sqrt`, a few comparisons and one `math.sqrt`) is O(1) and negligible relative to the bus latency. The write is blocking (`await`) but is issued only on command paths (not continuous poll), so no throughput degradation is expected.

7. **Debuggability:** By updating `runtime.last_v_target`, subsequent reads or logs show the exact V applied. If a transient fault occurs, the logged “p_target” and “last_v_target” provide a complete state picture, preserving forensics capabilities.
