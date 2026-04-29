```python
# ── keithley_2604b.py — new helper method + lock ──

# Add to __init__:
#     self._reg_lock = asyncio.Lock()

async def apply_regulation_step(self, smu_channel: str) -> dict[str, Any]:
    """One immediate P=const regulation step: measure → compute → write.

    Mirrors the read_channels regulation logic exactly so _last_v stays
    consistent and the next poll cycle continues seamlessly.
    Caller must have already set runtime.p_target to the desired value.
    """
    async with self._reg_lock:
        runtime = self._channels.get(smu_channel)
        if runtime is None or not runtime.active:
            return {"ok": False, "error": f"Channel {smu_channel} not active"}

        # ── Fresh V/I measurement ──
        try:
            v_meas = float(
                (await self._transport.query(
                    f"print({smu_channel}.measure.v())"
                )).strip()
            )
            i_meas = float(
                (await self._transport.query(
                    f"print({smu_channel}.measure.i())"
                )).strip()
            )
        except Exception as exc:
            logger.warning(
                "apply_regulation_step measure failed %s: %s", smu_channel, exc
            )
            return {"ok": False, "error": f"Measurement failed: {exc}"}

        current_v = self._last_v.get(smu_channel, 0.0)

        # ── Resistance & target voltage (same formula as regulation loop) ──
        resistance: float | None = None
        if abs(i_meas) > _I_MIN_A and abs(v_meas) > 0:
            resistance = abs(v_meas) / abs(i_meas)

        if resistance is not None and resistance > 0:
            target_v = math.sqrt(runtime.p_target * resistance)
        else:
            # Indeterminate resistance — hold voltage; loop corrects next cycle
            target_v = current_v

        # ── Voltage compliance clamp ──
        target_v = max(0.0, min(target_v, runtime.v_comp))

        # ── Current compliance pre-check (defense-in-depth; HW also enforces) ──
        if resistance is not None and resistance > 0:
            if target_v / resistance > runtime.i_comp:
                target_v = runtime.i_comp * resistance

        # ── Slew-rate limit (identical to read_channels) ──
        delta_v = target_v - current_v
        if abs(delta_v) > MAX_DELTA_V_PER_STEP:
            delta_v = (
                MAX_DELTA_V_PER_STEP if delta_v > 0 else -MAX_DELTA_V_PER_STEP
            )
            target_v = current_v + delta_v

        # ── Write hardware & update tracking ──
        await self._transport.write(
            f"{smu_channel}.source.levelv = {target_v}"
        )
        self._last_v[smu_channel] = target_v

        return {
            "ok": True,
            "v_written": target_v,
            "v_meas": v_meas,
            "i_meas": i_meas,
        }


# ── keithley_2604b.py — read_channels regulation block must acquire same lock ──
#
# In read_channels, wrap the voltage-computation-and-write section with:
#
#     async with self._reg_lock:
#         ... compute target_v from measurements ...
#         ... slew-limit against self._last_v[smu_channel] ...
#         await self._transport.write(f"{smu_channel}.source.levelv = {target_v}")
#         self._last_v[smu_channel] = target_v
#
# This serialises the immediate step with the background poll cycle,
# preventing a race on _last_v that could cause a double-step or
# stale-delta computation.


# ── safety_manager.py — updated update_target ──

async def update_target(
    self, p_target: float, *, channel: str | None = None
) -> dict[str, Any]:
    """Live-update P_target on an active channel with immediate SCPI write.

    Validates against config limits, sets runtime.p_target, then drives
    one slew-limited voltage step to hardware immediately.  The P=const
    regulation loop continues normally on subsequent poll cycles.
    """
    async with self._cmd_lock:
        smu_channel = normalize_smu_channel(channel)

        # ── Validation (unchanged) ──
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
            return {
                "ok": False,
                "error": f"Channel {smu_channel} not active on instrument",
            }

        old_p = runtime.p_target
        runtime.p_target = p_target
        logger.info(
            "SAFETY: P_target update %s: %.4f → %.4f W",
            smu_channel, old_p, p_target,
        )

        # ── Immediate regulation step (new) ──
        step = await self._keithley.apply_regulation_step(smu_channel)
        if not step.get("ok"):
            # p_target is already set; loop will apply it on next poll cycle.
            # Immediate step is best-effort — don't fail the whole call.
            logger.warning(
                "SAFETY: immediate step deferred for %s: %s",
                smu_channel,
                step.get("error"),
            )
            return {
                "ok": True,
                "channel": smu_channel,
                "p_target": p_target,
                "immediate": False,
                "note": step.get("error"),
            }

        return {
            "ok": True,
            "channel": smu_channel,
            "p_target": p_target,
            "immediate": True,
            "v_written": step["v_written"],
        }
```

**Design choices and tradeoffs.** The immediate step reuses the identical compute-then-write logic from the regulation loop (same resistance formula, same slew and compliance clamping), which guarantees the next poll cycle sees a consistent `_last_v` and simply continues ramping — no discontinuity or double-step. A `_reg_lock` on the Keithley driver serialises the immediate write with the background poll, preventing a race where both paths compute deltas against a stale `_last_v`. The tradeoff is added latency: the immediate step requires two SCPI queries + one write (~30–90 ms depending on transport), and while it holds `_reg_lock` the poll cycle is blocked. On measurement failure the method degrades gracefully — `runtime.p_target` is already set, so the loop catches up on the next cycle, preserving the original delayed-update fallback. The i_comp pre-check is defense-in-depth beyond the hardware's own compliance enforcement, clamping the computed voltage so we never command a step that would certainly trip compliance.
