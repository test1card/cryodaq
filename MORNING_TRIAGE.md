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

## Net result
12/12 Codex findings addressed (11 strengthened, 1 reasoned-reject). All green;
no real product bugs surfaced — the safety/alarm/cooldown/persistence behaviors
the weak tests named do actually work.
