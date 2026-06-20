# Morning triage — test-quality hardening (Codex adversarial review)

Tests strengthened per Codex's adversarial review. Where strengthening turned a
test **red**, it exposed a real behavior gap the weak test was hiding.

## RED (likely real bug — needs your decision)
_(none so far)_ — every strengthened test went green. The behaviors the weak
tests claimed to cover **do actually work**; the apparent failures during
hardening were my test-setup mistakes (compiled-regex critical_channels, the
RateEstimator min_points=60 gate, arm()'s model-file existence check), not
product bugs.

## Strengthened & green (now assert real behavior)
- **A1 (Critical)** `test_safety_manager::test_broker_overflow_triggers_fault` —
  was asserting only that a callback exists; now deterministically forces queue
  overflow and asserts `FAULT_LATCHED` + reason. **Confirmed: overflow→FAULT works.**
- **A2 (High)** `test_alarm_v2_integration::test_phase_alarm_suppressed_outside_phase`
  — was re-deriving the filter boolean; now runs the real evaluator+state-manager
  tick (mirrors engine.py:2064) with a would-fire reading + positive control.
- **A3 (High)** `test_cooldown_alarm::test_arm_with_model_returns_true` — was
  patching `arm()` itself; now calls the real `arm()` (cold-start gate, state
  transition, model store), mocking only the file load.
- **A4/A5 (Med)** analytics cooldown forward + cached replay — were asserting only
  point count; now assert exact central/lower/upper curve values.
- **A6 (Med)** `test_analytics_view_lifecycle::test_pressure_forwarded...` — was
  asserting widget type only; now asserts the reading reaches `_series`.
- **A8 (Med→safety)** `test_safety_fixes` rate-limit — was asserting private attrs;
  replaced with a black-box test: steep dT/dt on a CRITICAL channel latches FAULT.
  **Confirmed: rate limiter faults (needs ≥60 samples by design).**
- **A12 (Low)** `test_changelog` — stale fixed version range → asserts the current
  pyproject version is documented.

## Batch 2 — strengthened & green
- **A9 (Med)** `test_sqlite_writer_executor_separation` — replaced 4 brittle
  `inspect.getsource("_read_executor" in source)` tests with one runtime test that
  spies `run_in_executor` and asserts reads route to `_read_executor`, writes to
  `_executor` (kept the real slow-write-doesn't-block-read integration test).
- **A10 (Med)** `test_replay_predictor` — fixed ZMQ ports 15555/15556 → OS-assigned
  free ports (`_free_tcp_addr`), so a stale process / parallel run can't collide.
- **A11 (Med)** new `tests/gui/test_widget_cleanup_sentinel.py` — guards the real
  protective invariant: teardown stops leaked widget timers (a running timer during
  app_palette's global setStyleSheet re-polish is the crash). Note: discovered that
  `deleteLater()+processEvents()` does NOT reliably *delete* widgets (Qt
  DeferredDelete semantics) — the conftest protects via timer-stop + closeEvent,
  not widget deletion. Sentinel asserts the timer-stop invariant accordingly.

## Rejected (with reason)
- **A7** shell conftest global `send_command` stub — kept. It's a deliberate
  test-isolation default (no real ZMQ sockets in unit tests). Scoping it per-test
  would mean auditing hundreds of shell tests and risk re-introducing real-ZMQ
  flakiness, and it hides nothing: command/wiring tests that matter already opt
  into real payload capture via `_patch_worker_capture` (test_shift_handover,
  test_periodic_prompt). Not false confidence.

## Cycle 1 net result
12/12 Codex findings addressed (11 strengthened, 1 reasoned-reject). All green;
no real product bugs surfaced.

## Cycle 2 (Codex re-review): 9/11 GENUINE, 2 still-weak, +6 new
Codex verified the cycle-1 fixes: 9 GENUINE; 2 still-weak (#2 alarm suppression
still routes through a test-helper copy of the prod loop; #10 sentinel tests a
copied drain, not the real conftest). Found 6 new (2 HIGH).

## Cycle 3 — strengthened & green (the HIGH new findings + a quick MED)
- **B1 (HIGH, safety)** `test_keithley_safety::test_slew_rate_limits_large_v_step`
  — was a tautology (mock path bypasses the limiter; asserted only the constant).
  Now drives the REAL non-mock regulation path via a fake TSP transport: a 10 kΩ
  measured R wants ~40 V, must clamp to 0.5 V/step. **Confirms the slew limiter works.**
- **B3 (HIGH, data-integrity)** `test_sqlite_writer::test_sqlite_writer_raises_when_wal_unavailable`
  — was source-string grep. Now fault-injects a fake connection whose
  PRAGMA journal_mode returns 'delete' and asserts _ensure_connection raises
  RuntimeError. **Confirms WAL-refusal is actually rejected.**
- **B2 (MED)** `test_keithley_2604b::test_inactive_channel_output_state_parsed_as_float`
  — was `assert float("1.000000e+00") > 0.5` (tests Python, not the driver). Now
  drives the driver's output-state branch via fake transport (ON form → reads iv;
  OFF → zeros).

## Cycle 4 — ALL remaining items finished
- **#2 alarm production-level suppression** — DONE. Extracted the per-alarm tick
  (phase-filter→evaluate→process) into `cryodaq.core.alarm_v2.tick_alarm`; the
  engine loop now calls it (behavior-preserving), and the test helper
  `_simulate_tick` routes through it — so phase-filter suppression is now tested
  against PRODUCTION code, not a reimplementation.
- **#10 sentinel vs real conftest** — DONE. Extracted the gui teardown into
  `tests/_widget_cleanup.drain_gui_widgets`; `tests/gui/conftest.py` (autouse,
  also covers shell tests as the parent conftest) and the leak sentinel both use
  it, so the sentinel exercises the real cleanup. Full tests/gui/ green (1137).
- **B4 (MED)** gpib RM sharing — DONE. Tests the real `_get_rm` caching with a fake
  pyvisa: same bus reuses one ResourceManager, different bus gets its own.
- **B5 (MED)** thyracont fallback baud — DONE. Fake serial transport: probe fails
  at primary baud, succeeds at fallback; asserts the open-baud order [9600,115200]
  and that a primary success opens only once.
- **B6 (LOW-MED)** web `--host` — KEPT (reasoned). The web server is launched by
  external uvicorn (`server:app`); there is no in-code host default to assert at
  runtime, so the docstring guard (bind must be 127.0.0.1, never 0.0.0.0) is the
  right check for this architecture. (Side note: the deploy example in CLAUDE.md
  shows `--host 0.0.0.0` — a docs inconsistency worth a separate look, not a test.)

## Bottom line
ALL Codex findings across 4 cycles are now addressed — every false-confidence
test (Critical → LOW) is either strengthened to exercise real behavior or kept
with a documented reason (A7 shell stub, B6 web bind). The two architectural
refactors (#2 engine alarm-tick extraction, #10 shared GUI cleanup helper) are
done. **No product bug surfaced in any cycle** — the safety/data-integrity
behaviors the weak tests named (overflow→FAULT, rate-limit→FAULT, Keithley slew
clamp, WAL-refusal→raise, cooldown arm, alarm phase-suppression, executor routing,
gpib RM caching, thyracont fallback) all genuinely work; the weak tests just
weren't proving it.

This MORNING_TRIAGE.md is a transient worklist — safe to delete now that it's
done, or keep as a record. The one real follow-up that is NOT a test issue: the
CLAUDE.md deploy example uses `uvicorn ... --host 0.0.0.0`, which contradicts the
127.0.0.1 guard — worth reconciling.
