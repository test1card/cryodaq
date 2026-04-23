# CryoDAQ Repository Hardening Plan
**Date:** 2026-04-21  
**Scope:** Defensive fixes and diagnostic instrumentation based on ZERO_TRUST_AUDIT_2026-04-20  
**Status:** Draft pending review

---

## 1. Surviving Findings Accepted as Input Truth

These findings are validated by direct code examination and confirmed across multiple reviewer sources:

| Finding | Severity | Evidence Location | Status |
|---------|----------|-------------------|--------|
| **F1: Watchdog cooldown missing** | CRITICAL | `launcher.py:910-921` — no `_last_cmd_watchdog_restart` | Confirmed missing |
| **F3: alarm_v2 threshold_expr** | HIGH | `alarm_v2.py:252` direct `cond["threshold"]` access | Confirmed defect |
| **F2: Ping/bridge decoupling** | MEDIUM | `launcher.py:184` hardcoded tcp://, isolated health check | Confirmed blind spot |
| **F6: B1 root cause unknown** | — | All hypotheses falsified or unverified | Confirmed unknown |

---

## 2. Findings Downgraded or Excluded from Implementation Scope

| Finding | Original Claim | Arbitration | Disposition |
|---------|----------------|-------------|-------------|
| B1 at TCP layer (TIME_WAIT) | Kimi proposed socket exhaustion | Kimi then falsified with direct REQ test | EXCLUDED — contradicted by same reviewer |
| IV.7 ipc:// as fix | Next priority fix | Gemini: test as diagnostic; Kimi: insufficient evidence | DEFERRED — diagnostic value, not fix certainty |
| alarm_v2 as "crash" | Original audit claimed crash | Exception is caught at `alarm_v2.py:129-131` | DOWNGRADED — log spam, not crash |
| Launcher TCP probes hardcoded | Will break with ipc:// | Future compatibility issue | DEFERRED — IV.7 pre-work, not hardening |

---

## 3. Exact Implementation Backlog for This Pass

### Item A: Watchdog Cooldown Guard (CRITICAL)
**Rationale:** HANDOFF documents a fix that was never committed. Current code will restart-storm (30-40/min) on any command timeout.

**Implementation:**
```python
# In launcher.py _health_check method, around line 915
if self._bridge.command_channel_stalled(timeout_s=10.0):
    now = time.monotonic()
    last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
    if now - last_cmd_restart >= 60.0:
        logger.warning("ZMQ bridge: command channel unhealthy...")
        self._last_cmd_watchdog_restart = now
        self._bridge.shutdown()
        self._bridge.start()
        return  # Missing return causes check continuation post-restart
```

**Validation:**
- Static: verify attribute access pattern
- Runtime: verify no restart storm on manual timeout injection

**Risk:** LOW — surgical change, well-documented in handoff

---

### Item B: alarm_v2 Defensive Handling (HIGH)
**Rationale:** `cooldown_stall` alarm uses `threshold_expr` which `_eval_condition` does not support. Direct `cond["threshold"]` access raises KeyError → caught → silent degradation.

**YAML Structure Verified:**
```yaml
cooldown_stall:
  alarm_type: composite
  conditions:
    - channel: Т12
      check: rate_near_zero       # OK: no threshold needed
      ...
    - channel: Т12
      check: above                # PROBLEM: uses threshold_expr
      threshold_expr: "T12_setpoint + 50"
```

**Decision:** Config fix Option 1 — add `threshold: 150` at the correct nesting level:
```yaml
    - channel: Т12
      check: above
      threshold: 150              # Operational value: T12 setpoint ~100K + 50K
      # threshold_expr: "T12_setpoint + 50"  # NOT IMPLEMENTED YET
```

**Why 150:** Per alarms_tuning_guide, T12 setpoint during cooldown is ~100K. Threshold of 150K provides 50K margin without dynamic expression support.

**Validation:**
- Static: `python -c "import yaml; yaml.safe_load(open('config/alarms_v3.yaml'))"`
- Runtime: No KeyError in logs for cooldown_stall evaluation

**Risk:** LOW — config-only, easily reverted

**Gemini Note:** YAML nesting verified. `threshold` must be added inside the second condition block at same level as `check`.

---

### Item C: Ping/Bridge Consistency Hardening (MEDIUM)
**Rationale:** Health check tests engine REP directly (`_ping_engine`) but this doesn't reflect the bridge forward path. Bridge can be broken while ping succeeds.

**Decision:** Single-poll discrepancy flag — no state retention across polls

**Implementation:**
```python
# In _health_check, after existing checks:
ping_healthy = self._ping_engine()
bridge_can_forward = self._bridge.is_healthy()  # Uses existing method
if ping_healthy and not bridge_can_forward:
    logger.warning("ZMQ health discrepancy: ping OK but bridge unhealthy")
# No state stored; comparison is per-poll only
```

**Explicit Bound:** No state stored beyond current poll cycle. No counters, no trend analysis. Pure single-poll observation.

**Validation:**
- Static: logger.warning call present
- Runtime: Log shows discrepancy when ping succeeds but bridge fails

**Risk:** LOW — single-poll logging, no state machine

**Gemini Note:** Reframed from "logging only" to explicitly state single-poll bound.

---

### Item D: B1 Diagnostic Instrumentation (MEDIUM - adds evidence)
**Rationale:** Next B1 phase needs runtime data. Current code lacks observability.

**Focused instrumentation (two items only):**

| Location | Instrumentation | Hypothesis Tested |
|----------|-----------------|-------------------|
| `zmq_subprocess.py` | Exit code logging on subprocess termination | Distinguish kill vs crash vs clean exit |
| `zmq_client.py` | Bridge restart counter (`_restart_count`) with getter | Quantify restart frequency; correlate with B1 events |

**Hypothesis mapping:**
- Exit code → If bridge exits non-zero during B1, suggests crash not graceful timeout
- Restart count + timestamps → If restarts cluster at B1 time, bridge is symptom not cause
- Comparison with B1 timeline → If B1 occurs WITHOUT restart, bridge is not the trigger

**Explicitly NOT included:**
- Context ID logging (high overhead, unclear interpretation action)
- SUB dropped message counter (data plane validated healthy)
- Command timeline per-minute (redundant with restart counter)
- Socket monitor events (high noise, uncertain diagnostic value)

**Validation:**
- Static: `_restart_count` attribute exists, getter accessible
- Runtime: counter increments on bridge restart; exit code in log on termination

**Risk:** LOW — two counters only, bounded growth

**Gemini Note:** Removed unfocused instrumentation. Kept only exit code (distinguishes exit types) and restart counter (correlates with B1).

---

## 4. Execution Order

1. **Item A** (cooldown) — highest impact, simplest fix
2. **Item D** (instrumentation) — need this before any runtime testing
3. **Item B** (alarm_v2) — config-level fix
4. **Item C** (ping/bridge) — lowest priority, logging only

---

## 5. Risk Assessment per Change

| Change | Blast Radius | Rollback Complexity | Confidence |
|--------|--------------|---------------------|------------|
| A. Cooldown | 1 method | Revert 8 lines | HIGH |
| B. alarm_v2 | 1 config entry | Revert YAML line | HIGH |
| C. Ping/bridge | 1 method | Revert logging lines | HIGH |
| D. Instrumentation | 4 modules | Revert attribute adds | HIGH |

---

## 6. Validation Method per Change

| Change | Static Check | Targeted Test | Runtime Check |
|--------|--------------|---------------|---------------|
| A | Attribute refs | `pytest tests/ -k launcher` | Manual timeout test |
| B | YAML syntax | Load config smoke test | Log spam check |
| C | Log call syntax | N/A | Log observation |
| D | Attribute refs | N/A | Counter accessibility |

---

## 7. Explicit Defer List

These are explicitly OUT OF SCOPE for this hardening pass:

| Item | Why Deferred |
|------|--------------|
| IV.7 ipc:// transport | Not yet justified; diagnostic value only |
| Root-cause B1 rewrite | Unknown root cause; premature |
| Launcher TCP probe transport-agnostic rewrite | Future-facing, no current need |
| Python version migration | Infrastructure, not hardening |
| Queueing redesign | Speculative optimization |
| engine.py architectural breakup | Tech debt, not critical fix |
| ZMQ socket monitor events | High complexity, uncertain diagnostic value |
| channels.yaml content changes | Architect's WIP per Rule 7 |

---

## 8. Success Criteria

This plan succeeds when:
- [ ] All 4 items implemented with reviews complete
- [ ] Watchdog cannot restart-storm (60s enforced cooldown)
- [ ] alarm_v2 does not KeyError on cooldown_stall
- [ ] B1 diagnostic data is collectible (counters accessible)
- [ ] No regressions in existing test suite
- [ ] Final arbitrator report produced

---

## 9. Reviewer Requirements

Per workflow, this plan MUST survive:
- Codex regression review (collateral damage analysis) — PENDING
- Gemini adversarial review (scope expansion check) — CONDITIONAL PASS
- Kimi contradiction review (if plan overreaches) — Not triggered (Gemini found scope issues but no fundamental contradictions)

Reviews go to:
- `REVIEW_PLAN_CODEX.md` — PENDING
- `REVIEW_PLAN_GEMINI.md` — CONDITIONAL (items addressed in revision)

### Gemini Review Response (REVISED 2026-04-21)

**Original Gemini verdict:** CONDITIONAL PASS with required modifications

**Modifications applied:**

| Gemini Finding | Revision Made |
|----------------|---------------|
| Item C "logging only" mischaracterization | Reframed as "single-poll discrepancy flag (no state retention)" with explicit bound |
| Item D unfocused instrumentation | Reduced from 5 counters to 2; removed context-ID, SUB-dropped, command-timeline; kept exit-code + restart-count |
| cooldown_stall YAML nesting risk | Added explicit YAML structure verification + correct nesting guidance |
| Threshold placeholder risk | Changed from `threshold: 0` to `threshold: 150` with operational justification |

**Remaining Gemini concerns (accepted as acceptable risk):**
- Item B may paper over deeper dynamic expression need — accepted, this is defensive hardening not full feature
- 60s cooldown threshold justification from handoff — accepted, handoff is ground truth

**Codex review still pending** — may yield additional modifications before implementation.

---

## Appendix: Evidence Citations

- `HANDOFF_2026-04-20_GLM.md:67-115` — watchdog cooldown description
- `ZERO_TRUST_AUDIT_2026-04-20.md:26-54` — Critical Finding 1 (CONTRADICTED)
- `ZERO_TRUST_AUDIT_2026-04-20.md:120-134` — Finding 5 (threshold_expr)
- `src/cryodaq/launcher.py:910-921` — current watchdog code (no cooldown)
- `config/alarms_v3.yaml:237` — threshold_expr usage
- `src/cryodaq/core/alarm_v2.py:252` — direct threshold access
