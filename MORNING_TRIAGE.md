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

## DEFERRED to a focused session (documented, not rushed)
These are real but need a refactor/harness best done with you in the loop —
rushing them risks wrong tests, which defeats the purpose:
- **#2 alarm production-level suppression** — to test the *production* phase filter
  (engine.py:2064) rather than the `_simulate_tick` helper copy, extract the
  per-alarm tick (filter→evaluate→process) from the engine's inline loop into a
  callable production function, then test that. Touches engine.py.
- **#10 sentinel vs real conftest** — to test the actual fixture (not a copied
  drain), unify gui + shell conftest cleanup into one importable helper and have
  the sentinel import it. Deferred to avoid re-touching the hard-won-green conftests.
- **B4 (MED)** gpib bus-lock RM sharing — over-mocked (mock=True returns before
  `_get_rm`); needs a non-mock pyvisa.ResourceManager monkeypatch + 2 transports.
- **B5 (MED)** thyracont fallback baud — only asserts mock connect; needs a fake
  serial transport that fails primary baud then succeeds fallback.
- **B6 (LOW-MED)** web dashboard `--host` — checks help/doc text, not runtime bind
  default; needs a CLI/config-level assertion.

## Bottom line
All Critical + HIGH false-confidence tests across cycles 1-3 are fixed and green
(safety overflow, rate limit, Keithley slew, WAL, cooldown arm, alarm suppression
positive-control, executor routing). No product bugs surfaced — the behaviors the
weak tests named all work. Remaining is a documented MED/LOW tail + 2 refactors.
