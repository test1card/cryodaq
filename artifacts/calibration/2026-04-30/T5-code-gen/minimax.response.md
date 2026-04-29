```python
# Inside safety_manager.SafetyManager (eitherman pseudo‑code)
import math
from typing import Any

MAX_DELTA_V_PER_STEP = 0.5  # V – same limit used by the P=const loop

async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
    """Live‑update P_target on an active channel, with an immediate SCPI write.

    The new power setpoint is validated against config limits.  A steady‑state
    voltage is computed from the last measured resistance, clamped to the
    channel’s voltage compliance, and then slewed by at most
    ``MAX_DELTA_V_PER_STEP`` before being written to the SMU.  The in‑memory
    ``p_target`` and the driver's ``_last_v`` are also updated so that the
    P=const regulation loop picks up the new target on its next poll without
    breaking continuity.
    """
    async with self._cmd_lock:
        smu_channel = normalize_smu_channel(channel)

        # ---- safety checks ----------------------------------------------------
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

        # ---- update the in‑memory target ------------------------------------
        old_p = runtime.p_target
        runtime.p_target = p_target

        # ---- compute an immediate voltage -----------------------------------
        # Use the most recent measurement (if available) to estimate resistance.
        current_v = self._keithley._last_v.get(smu_channel, 0.0)
        i_meas = getattr(runtime, "i_meas", None)   # latest measured current
        v_meas = getattr(runtime, "v_meas", None)   # latest measured voltage

        # Estimate resistance from V/I (guard against divide‑by‑zero).
        resistance = 0.0
        if i_meas is not None and v_meas is not None and abs(i_meas) > 1e-9:
            resistance = v_meas / i_meas

        # Steady‑state voltage that would satisfy the new power setpoint.
        if resistance > 0:
            target_v = math.sqrt(p_target * resistance)
        else:
            # No valid resistance – keep the present voltage.
            target_v = current_v

        # ---- apply voltage compliance ----------------------------------------
        v_comp = getattr(runtime, "v_comp", self._config.max_voltage_v)
        target_v = max(0.0, min(target_v, v_comp))

        # ---- apply slew‑rate limit -------------------------------------------
        delta_v = target_v - current_v
        if abs(delta_v) > MAX_DELTA_V_PER_STEP:
            delta_v = MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
        new_v = current_v + delta_v

        # ---- immediate SCPI write --------------------------------------------
        try:
            await self._keithley._transport.write(
                f"{smu_channel}.source.levelv = {new_v}"
            )
        except Exception as exc:
            logger.exception("SCPI write failed during immediate P_target update")
            return {"ok": False, "error": f"SCPI write failed: {exc}"}

        # Keep the driver’s voltage tracker in sync.
        self._keithley._last_v[smu_channel] = new_v

        logger.info(
            "SAFETY: P_target immediate update %s: %.4f → %.4f W, "
            "V immediate: %.4f → %.4f V (slew‑limited)",
            smu_channel, old_p, p_target, current_v, new_v
        )

        return {"ok": True, "channel": smu_channel, "p_target": p_target, "v_set": new_v}
```

The direct SCPI write reduces the latency of a target change from the length of a poll cycle (up to 1 s) to essentially the communication round‑trip time, which is critical for fast demand steps. By recomputing the steady‑state voltage from the most recent resistance estimate and re‑applying the same compliance‑voltage clamp and 0.5 V slew‑rate limit used by the P=const loop, the immediate update respects all safety constraints and does not over‑drive the instrument. The in‑memory `p_target` and `_last_v` are updated so that the next execution of the regular regulation loop sees the new setpoint and continues smoothly, avoiding any race condition or abrupt voltage jumps. The trade‑off is a modest increase in SCPI traffic per update and reliance on a reasonably fresh resistance measurement; however, any staleness is corrected on the next poll, preserving overall safety.
