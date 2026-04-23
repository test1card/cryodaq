# Review Plan - Codex

**Model:** gpt-5.4 / Reasoning effort: high  
**Date:** 2026-04-21  
**Focus:** Regression risks, collateral damage, implementation completeness

---

## Summary
**PASS** with NOTES — No blocking regressions identified. Three non-critical notes on thread safety, timing coverage, and config Defaults. All items within acceptable risk bounds for hardening pass.

---

## Per-Item Analysis

### Item A: Watchdog Cooldown
- **Risk Level:** LOW
- **Regression Concerns:**
  - Initial `getattr` with 0.0 default is slightly risk-prone if system time is adjusted backward (unlikely on monotonic clock)
  - No risk of exception leakage — all new code is attribute access and comparison
- **Implementation Gaps:**
  - None — implementation matches handoff exactly
- **Thread Safety Note:**
  - `getattr`/`setattr` on `_last_cmd_watchdog_restart` is thread-safe for CPython (GIL-protected at bytecode level)
  - However, `_health_check` runs on QTimer on main thread; `command_channel_stalled()` has internal lock — safe
- **Recommendations:** NONE for delta

### Item B: alarm_v2 Handling
- **Risk Level:** LOW
- **Regression Concerns:**
  - Adding `threshold: 150` to config with existing `threshold_expr` may confuse future maintainers
  - If someone removes the comment saying threshold_expr isn't implemented, ambiguity enters
- **Implementation Gaps:**
  - Consider adding explicit YAML comment: `# threshold_expr not implemented; using static threshold`
- **Recommendations:** Add explicit comment in YAML to prevent future confusion

### Item C: Ping/Bridge Consistency (Revised)
- **Risk Level:** LOW
- **Regression Concerns:**
  - Single-poll implementation prevents state accumulation — good
  - `self._bridge.is_healthy()` existing behavior unchanged
  - Log volume is bounded (one line per poll cycle max)
- **Implementation Gaps:** NONE — revised framing addresses Gemini concern
- **Recommendations:** NONE

### Item D: B1 Diagnostic Instrumentation (Revised)
- **Risk Level:** LOW
- **Regression Concerns:**
  - Exit code logging: Need to ensure `subprocess.wait()` or `returncode` access is after process termination not during
  - Restart counter: Simple integer increment is safe; `_restart_count` attribute needs initialization in `__init__`
- **Implementation Gaps:**
  - Initialization of `_restart_count` not specified in plan
- **Recommendations:** Add `self._restart_count = 0` to ZmqBridge `__init__`

---

## Cross-Cutting Concerns

### Testing Coverage
- **No automated test changes** in plan — acceptable for hardening pass
- Targeted validation via existing tests + manual verification sufficient

### Lifecycle Interaction
- Cooldown fix occurs after `self._bridge.start()` returns, which is synchronous (thread spawn) — OK
- Bridge restart timing: If `start()` takes >60s, cooldown is ineffective — but this is edge case, normal startup is <2s

### Config Risk
- YAML change is single line addition — lowest risk change category
- Static validation via pyyaml parse is sufficient

---

## Notes on Gemini Revisions

The revisions made to address Gemini's CONDITIONAL findings are appropriate:
1. Item C now explicitly states "no state retention" — resolves scope drift concern
2. Item D reduced from 5 to 2 instrumentation points — eliminates cargo-cult diagnostic risk
3. cooldown_stall threshold changed from placeholder 0 to operational 150 — addresses semantic validity concern

---

## Final Verdict

**PASS**

Blockers: None
Notes: 3 (all non-blocking, see above)
Confidence: HIGH that plan can be implemented without regression

---

*Review completed: Codex regression model*
*Assessment: Plan is surgically scoped, defensively motivated, within acceptable risk bounds*
