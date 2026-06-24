# Test-sweep escalation — architect decisions needed (2026-06-23)

The GUI test-quality sweep (batches 0–34: FIND → FIX → VERIFY, all Codex-approved,
full suite green) surfaced gaps that are **not** auto-fixable because they need a
product/architecture decision, not a test change. None were patched in prod. They
are listed worst-first.

---

## 0. SAFETY-AUTHORITY findings — cross-model cold audit (2026-06-24)

An independent **cross-model** cold audit (Codex gpt-5.5, auditing the safety FSM
+ driver from scratch — not reviewing diffs) found four source-control-path issues
that three same-model (Claude) review rounds had missed. **F1 was a clear
correctness defect and is FIXED** (commit `571eb65`: `_safe_off` now fails closed
on a failed `stop_source`). The remaining three change a **documented contract or
the data-flow architecture**, so they are escalated rather than auto-patched —
they are safety-authority decisions for the architect.

### 0a. CRIT — `emergency_off` reports success even when readback-verify fails
**Where:** `keithley_2604b.py:307-341` (`emergency_off` logs CRITICAL on a failed
OUTPUT_OFF write / `_verify_output_off` but **never raises** — by design, comment
:330-332) → `safety_manager.py:421-446` (`emergency_off` clears `_active_sources`
and returns `{"ok": True}`). **Effect:** a failed emergency-off (hardware may still
be sourcing) is reported to the operator/GUI as **success**; only a CRITICAL log
fires.
**Decision:** should `emergency_off` thread per-channel verified-off status back so
`SafetyManager` returns `ok=False` / a warning when a channel can't be proven off?
*Recommended:* yes — keep firing all writes (don't stop on first failure), but
return the verification result so the API is honest. Contract change to the most
critical path → your call.

### 0b. CRIT — crash-recovery force-off on `connect()` is best-effort (DOCUMENTED)
**Where:** `keithley_2604b.py:97-116` — `connect()` forces OUTPUT_OFF on both SMUs,
but a failed force-off only logs CRITICAL and continues; `_connected=True` is set
regardless. This is **explicitly documented** in CLAUDE.md ("best-effort: if
force-OFF fails, logs CRITICAL and continues — not guaranteed"). After a prior
crash that left outputs on, a failed force-off leaves the instrument connected,
unmanaged, possibly still sourcing.
**Decision:** keep best-effort (current, documented) or make `connect()` fail
closed (refuse to connect / latch a fault) if it can't prove both channels off?
*Trade-off:* fail-closed is safer but blocks startup if the readback is flaky.
Architect/product call — not auto-changed because it overrides a documented choice.

### 0c. HIGH — interlocks run on `DataBroker` (DROP_OLDEST), not a fail-closed channel
**Where:** `interlock.py:328` subscribes via `DataBroker` (default `maxsize=10_000`,
`OverflowPolicy.DROP_OLDEST`, `broker.py:36/62`). The `SafetyBroker` uses
overflow→FAULT, but the **protective** InterlockEngine does not. If its queue
overflows (e.g. a slow/blocked trip action backs the loop up), a threshold-
violating reading can be **dropped before `_process_reading` sees it** → the
protective action never runs for that reading.
**Decision:** route interlocks through a fail-closed channel (overflow→FAULT, like
SafetyBroker) or add a latch-on-interlock-overflow callback? *Recommended:* yes —
a protective consumer should never silently drop a reading. Changes the data-flow
architecture → your call.

---

## 1. ✅ RESOLVED (2026-06-24) — alarm-panel non-finite reading display
**Fix:** non-finite (NaN/Inf) value/threshold now render as "—" (fault marker),
not "nan" or a misleading "0" (`alarm_panel.py` `_fmt_metric`). Chosen over
coerce-to-0 because "0" can read as a plausible cold measurement on a faulted
sensor. Test `test_nonfinite_reading_value_renders_dash` asserts the rendered
cell. NOTE: this is the *display*; the deeper command-path NaN gap (a NaN
setpoint reaching the hardware) was the real CRIT — fixed separately (commit
98c90ac). Original text retained below for history.

## 1-orig. CRIT — alarm-panel does not coerce non-finite reading values
**Where:** `src/cryodaq/gui/shell/overlays/alarm_panel.py:608-611` — `float(reading.value)`
with no `math.isfinite` guard. Test: `tests/gui/shell/overlays/test_alarm_panel.py`
`test_reading_invalid_value_defaults_to_zero` (kept as-is, marker `DEFERRED-NAN-11`).
**Problem:** the test's named contract is "invalid value defaults to zero", but a
`NaN`/`inf` reading flows into the panel uncoerced. The test currently asserts only
the threshold, so it doesn't enforce the contract; strengthening it to assert the
rendered value cell would make it **red** against current prod.
**Decision needed (safety-adjacent — alarm display):**
- (a) **Prod fix** — coerce non-finite reading values to 0 (or to a clear "—"/fault
  marker) in the panel, then assert the rendered cell. *Recommended if NaN can reach
  the panel from a faulted sensor.* OR
- (b) Decide NaN cannot reach here (guaranteed upstream) and correct the test to
  assert the real intended behavior.
**Why escalate:** coercing-to-0 vs showing-a-fault-marker is a safety-display choice;
silently showing 0 for a faulted sensor could mislead an operator.

## 2. ARCHITECT — calibration acquisition: shell routes only Kelvin readings
**Where:** `src/cryodaq/gui/shell/main_window_v2.py:438` — `_dispatch_reading` forwards
only `unit == "K"` to `CalibrationPanel.on_reading`. But `CalibrationPanel.on_reading`
is documented (`calibration_panel.py:10`) to route `_raw`/`sensor_unit` readings to the
acquisition **live feed**. Acquisition stats/coverage actually arrive via the
`calibration_acquisition_status` **poll** (`_on_mode_result`), not via `on_reading`.
**Marker:** `DEFERRED-CALIB-ROUTING`. Test
`tests/gui/shell/test_main_window_v2_calibration_wiring.py` now pins current behavior
(A: shell forwards only K) + the panel contract (B: `on_reading` renders raw directly).
**Decision needed (Calibration-v2 data flow):**
- Is the live raw-pair feed **supposed** to populate from the realtime reading stream
  during acquisition? If yes → small prod fix in `_dispatch_reading` to also forward
  `_raw`/`sensor_unit` readings to calibration. If no (poll-only by design) → current
  behavior is correct and `on_reading`'s raw-routing path is effectively dead for the
  shell; consider documenting/removing it.

## 3. Lower-priority deferred (test-infra / src-seam, not correctness CRITs)
- **Item 7** — `alarm_v2_status` / `alarm_v2_ack` command-path tests reconstruct the
  engine's serialization (tautology) / call `AlarmStateManager` directly; the real
  command path is a nested closure in `engine.py` (2347/2392). Needs the closure
  extracted (prod refactor) to test end-to-end.
- **Item 10** — launcher real-construction tests (`_parse_args` helper, constructable
  `LauncherWindow` without `_start_engine()`); need a small src seam.
- **Item 12** — `tests/web/test_xss_escaping.py` 4 escaping guards stay source-grep;
  `escapeHtml` is client-side JS (`web/server.py:466`), proving rendered safety needs a
  Playwright/Selenium harness (out of scope for pytest).

## Believed-resolved (confirm)
The ZMQ timeout-layer CRIT (old item 1) + the engine-closure/timeout/label class
(items 2–6) were resolved on the `prod-fixes` worktree and merged to master
(commit `d4badef`). Worth a confirmation read, but not re-opened by the sweep.

---
**Nothing is pushed.** Pushing + any prod fix for items 1/2 are your call.
