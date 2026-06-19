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

## Still open (next pass / Codex cycle 2)
- A9 executor source-string tests → runtime executor assertions.
- A10 replay_predictor fixed ZMQ ports/sleep → dynamic ports.
- A11 app_palette isolation → add a GUI leak-sentinel test.
- A7 shell conftest global `send_command` stub → see note (likely justified default).
