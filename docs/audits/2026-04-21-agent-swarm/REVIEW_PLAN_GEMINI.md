# Review Plan - Gemini
## Summary
**CONDITIONAL** - Plan stays within hardening boundaries but has two significant gaps: Item C drift toward speculative behavior change disguised as logging, and Item D instrumentation scope creep without clear hypothesis targeting.

---

## Scope Analysis

### Does plan stay within hardening boundaries? **PARTIALLY**

Evidence for YES:
- Items A, B are purely defensive and document-validated
- Defer list correctly excludes IV.7 transport rewrite, root-cause speculation, architectural rewrites
- Explicit boundaries in "Explicitly NOT included" section (line 108-111)

Evidence for NO:
- Item C "Option 3" is framing bait-and-switch: logging ping/bridge discrepancy requires comparison logic that is behavioral change, not pure instrumentation
- Item D has 5 instrumentation points with no stated hypothesis to test - unfocused data collection
- Item C's "Option 3" opens path to state machine creep (tracking discrepancy patterns)

---

## Per-Item Adversarial Review

### Item A: Watchdog Cooldown

**Untested Assumptions:**
1. `_last_cmd_watchdog_restart` attribute survives across class instances correctly (timing issue with pickled state)
2. 60s is correct threshold (handoff says 60s, but no justification given - why not 30s? 10s?)
3. `getattr` default of 0.0 is safe - first restart could potentially race between multiple health check loops
4. `return` after restart is sufficient; no other cleanup (e.g., resetting other flags) needed

**Edge Cases:**
- Bridge restart takes >60s: next poll hits cooldown check, sees >60s elapsed, restarts again immediately - cooldown ineffective
- Launcher process crash mid-restart: `_last_cmd_watchdog_restart` timestamp written but `start()` not completed - restart on recovery despite failure risk
- Multiple concurrent `_health_check` calls (async boundary): `getattr`/`setattr` not atomic, non-thread-safe pattern possible

**Recommended Hardening:**
```
NONE for delta - plan is correct
BUT flag: Add validation that subprocess termination + restart cycle timing is measured
against actual cooldown effectiveness, not just code presence
```

---

### Item B: alarm_v2 Handling

**Untested Assumptions:**
1. Config fix (Option 1) is sufficient - assumes no other conditions use threshold_expr
2. Placeholder `threshold: 0` won't break semantically (threshold logic might interpret 0 differently)
3. YAML loader won't strip/modify the additional field

**Edge Cases:**
- `cooldown_stall` composite may have multiple conditions with mixed threshold/threshold_expr - placeholder applies to all or specific entry unclear
- If threshold_expr is meant to be dynamic (T12_setpoint + 50), hardcoding threshold: 0 makes alarm useless, just silent

**Recommended Hardening:**
```yaml
# In alarms_v3.yaml, instead of placeholder threshold: 0
# Implement as static threshold based on expected normal range:
threshold: 5.0  # or appropriate value for cooldown stall detection
```
OR replace threshold_expr with proper static threshold - do not paper over with placeholder.

---

### Item C: Ping/Bridge Consistency

**CRITICAL CONCERN: Scope drift disguised as "logging only"**

Claim: "Option 3 - minimal instrumentation to expose discrepancy, not behavioral change"

Reality: To log discrepancy, code must:
1. Track both ping state and bridge state
2. Compare them
3. Log when they diverge

This requires state tracking across health check cycles (behavior change). The claim "not behavioral change" is false.

**Untested Assumptions:**
1. Discrepancy correlation reveals useful data (may just show expected async delay)
2. Log volume won't overwhelm (discrepancy could fire every poll cycle if condition persistent)
3. No action will be taken based on discrepancy log (slippery slope toward adaptive restart)

**Edge Cases:**
- Discrepancy logged mid-restart window (transient expected divergence → false signal)
- Multiple log entries per second during B1 (log spam)

**Recommended Hardening:**
```
DROP Option 3 claim that this is "logging only" - it is behavioral state tracking
If maintaining Item C, ADD explicit bound: "No state stored beyond current poll cycle"
```

---

### Item D: B1 Diagnostic Instrumentation

**CRITICAL CONCERN: Instrumentation without hypothesis targeting is cargo cult**

Five instrumentation points with no stated diagnostic purpose:

| Instrumentation | Hypothesis it tests |
|-----------------|---------------------|
| Bridge restart counter + timestamps | Unknown - restart rate is observable already via log grep |
| Exit code logging on subprocess termination | Acceptable - distinguishes kill vs crash |
| SUB dropped message counter | No hypothesis - data plane already validated healthy |
| Command path health timeline | Overlaps with restart counter - redundant |
| Context ID logging per REQ creation | Tests "context routing state" hypothesis but not stated |

The plan does NOT reference Gemini's alternative hypotheses from ZERO_TRUST_AUDIT (Context routing state, TIME_WAIT exhaustion, REP socket wedging). Item D is fishing expedition, not targeted diagnostics.

**Untested Assumptions:**
1. More data is better (false - more code = more risk)
2. Each counter will be checked during B1 occurrence (who reads it?)
3. Instrumentation itself won't perturb timing (Heisenberg risk)

**Edge Cases:**
- Counter overflow on long-running engine (wraparound, negative values)
- Attribute access on partially-initialized bridge (AttributeError during startup phase)
- Counter read during bridge restart = race condition

**Recommended Hardening:**
```
CUT to two items: (1) exit code logging only, (2) add ONE counter with explicit
hypothesis: "Context ID per REQ tests routing state persistence hypothesis"
Remove: bridge restart counter (known via logs), SUB dropped counter (stable),
command timeline (redundant), per-REQ context ID (high overhead, unclear action)
```

---

## Hidden Dependencies

Cross-file, cross-module couplings not acknowledged in plan:

### 1. Launcher.py <-> zmq_subprocess.py
Cooldown fix uses `self._bridge` which is `ZMQBridge` instance. But `command_channel_stalled()` is implemented in subprocess wrapper, not bridge object. Plan assumes bridge exposes this - verify interface.

Evidence: `launcher.py:910` calls `self._bridge.command_channel_stalled()` - this is a method on bridge that delegates to subprocess state. If subprocess dies and restarts, does `command_channel_stalled` reflect old or new subprocess state?

### 2. alarm_v2.py <-> config/alarms_v3.yaml
Config fix (Item B) changes YAML. But `alarm_v2._eval_condition` at line 252 accesses `cond["threshold"]` directly. If config fix adds `threshold: 0` to wrong location in composite structure, error persists.

Evidence: `cooldown_stall` is composite (line 237 in alarms_v3.yaml). Composite structure has nested `conditions` array. Adding `threshold` to wrong nesting level doesn't fix the KeyError.

### 3. zmq_client.py instrumentation <-> GUI thread
Item D adds "SUB dropped message counter (exposed via getter)". GUI thread polls this. If counter stored in ZMQ client (subscriber), getter call is cross-thread. Locking not mentioned.

### 4. Multiple instrumentation points <-> Log volume
Five new counters with logging = 5x log line increase minimum. Lab systems with days-long experiments will generate GBs of logs. No retention/rotation consideration.

### 5. Launcher health check <-> Bridge subprocess lifecycle
Cooldown fix at line 82-92 in handoff shows restart sequence. But `self._bridge.shutdown()` is async (thread-based). `self._bridge.start()` immediately after - if shutdown still in progress, `start()` may fail or create zombie subprocess.

---

## Confidence Assessment

**Overall confidence in plan success: MEDIUM-LOW**

| Item | Confidence | Reason |
|------|------------|--------|
| Item A (cooldown) | HIGH | Well-understood, documented in handoff, surgical |
| Item B (alarm_v2) | MEDIUM | Config fix may paper over deeper issue; composite structure untested |
| Item C (ping/bridge) | LOW | Mischaracterized as logging-only; state tracking complexity underestimated |
| Item D (instrumentation) | LOW | Unfocused, no clear diagnostic hypothesis, scope creep risk |

Aggregate concern: Success criteria (Section 8) include "B1 diagnostic data is collectible (counters accessible)" but no criteria for "B1 diagnostic data answers specific hypothesis." Risk: Counters exist but no one interprets them.

---

## Final Verdict

**CONDITIONAL PASS** - Plan is directionally correct but requires two modifications before execution:

### Required Modifications:

1. **Item C must be reframed honestly**
   - Replace "Option 3 - logging only" with "Option 3a: single-poll discrepancy flag (no state retention)"
   - If state retention is required, elevate to MEDIUM-HIGH risk and flag explicitly

2. **Item D must be hypothesis-targeted**
   - Remove unfocused counters (SUB dropped, command timeline, restart counter)
   - Keep: exit code logging, ONE counter for specific hypothesis with clear read/interpret plan
   - State which hypothesis each metric tests

### Additional Recommendations (Not Blocking):

- Add alert: Measure actual bridge restart cycle time vs 60s threshold - may need adjustment
- Verify `cooldown_stall` composite structure before editing config (YAML nesting matters)
- Consider: Instrumentation is premature without B1 reproduction case

---

## Cross-Reference to ZERO_TRUST_AUDIT Findings

| Audit Finding | Plan Item | Handling Assessment |
|---------------|-----------|---------------------|
| F1 Watchdog cooldown missing | Item A | Correctly prioritized, matches handoff |
| F2 Ping/bridge decoupling | Item C | Claims diagnostic value but adds more abstraction |
| F3 alarm_v2 threshold_expr | Item B | Config-first approach acceptable risk |
| F6 B1 root cause unknown | Item D | Unfocused; audit suggested specific diagnostics not reflected |

Audit suggested: Context-per-command test, netstat TIME_WATCH check, ZMQ socket monitor events. Plan implements none of these targeted diagnostics, instead adds generic counters.

---

*Review completed: Gemini adversarial model*
*Assessment: Plan is ~70% surgical hardening, ~30% under-scoped instrumentation*
