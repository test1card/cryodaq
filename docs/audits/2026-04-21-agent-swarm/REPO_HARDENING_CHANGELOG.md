# Repository Hardening Changelog
**Date:** 2026-04-21  
**Plan:** REPO_HARDENING_PLAN.md  
**Reviewers:** Codex, Gemini (Kimi not triggered)

---

## Implementation Record

### Item A: Watchdog Cooldown Guard (CRITICAL)
**Finding addressed:** F1 — IV.6 Watchdog Cooldown Fix missing (CONTRADICTED by audit)

**Changes:**
- File: `src/cryodaq/launcher.py:915-928`
- Added 60s cooldown check via `_last_cmd_watchdog_restart` timestamp
- Added missing `return` after restart to prevent check continuation
- Comment references Hardening 2026-04-21

**Code delta:**
```python
# Hardening 2026-04-21: 60s cooldown prevents restart storm
# when fresh subprocess immediately sees stale cmd_timeout.
now = time.monotonic()
last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
if now - last_cmd_restart >= 60.0:
    # ... restart ...
    return  # missing return added
```

**Risk reduced:** Eliminates 30-40 restarts/minute storm when command timeout flag persists across bridge restart.

**Verification:**
- [x] Syntax validated via ast.parse
- [x] Attribute access pattern safe (getattr default)
- [ ] Runtime: requires B1 reproduction scenario to verify cooldown effectiveness

---

### Item B: alarm_v2 Defensive Config (HIGH)
**Finding addressed:** F5 — alarm_v2 threshold_expr CONFIGURED BUT NOT IMPLEMENTED

**Changes:**
- File: `config/alarms_v3.yaml:237`
- Replaced `threshold_expr: "T12_setpoint + 50"` with `threshold: 150`
- Added explicit comment noting threshold_expr not implemented

**Config delta:**
```yaml
- channel: Т12
  check: above
  threshold: 150  # threshold_expr not implemented; using static threshold (~100K setpoint + 50K)
```

**Risk reduced:** Eliminates KeyError log spam every ~2s when cooldown_stall alarm evaluates.

**Operational note:** 150K threshold is T12 setpoint (~100K) + 50K margin per alarms_tuning_guide.

**Verification:**
- [x] YAML syntax visually verified
- [ ] YAML parse validation (pyyaml unavailable in test env)
- [ ] Runtime: no KeyError in logs for cooldown_stall evaluation

---

### Item C: Ping/Bridge Consistency Logging (MEDIUM)
**Finding addressed:** F2 — Ping/bridge decoupling (VALIDATED blind spot)

**Changes:**
- File: `src/cryodaq/launcher.py:1133-1138` (in `_check_engine_health`)
- Added single-poll discrepancy logging with explicit "no state retention" bound

**Code delta:**
```python
# Hardening 2026-04-21: single-poll ping/bridge discrepancy logging
# Logs when direct engine ping succeeds but bridge forward path is unhealthy.
# No state retention — purely per-poll observation for diagnostic visibility.
if alive and self._bridge.is_alive():
    bridge_healthy = self._bridge.is_healthy()
    if alive and not bridge_healthy:
        logger.warning("ZMQ health discrepancy: engine ping OK but bridge unhealthy")
```

**Risk reduced:** Adds observability for ping/bridge divergence without behavioral change.

**Verification:**
- [x] Syntax validated
- [ ] Runtime: log shows when ping succeeds but bridge fails

---

### Item D: B1 Diagnostic Instrumentation (MEDIUM)
**Finding addressed:** F6 — B1 root cause unknown, needs runtime evidence

**Changes (2 items per plan revision):**

**1. Bridge restart counter:**
- File: `src/cryodaq/gui/zmq_client.py:94` — `_restart_count` initialization in `__init__`
- File: `src/cryodaq/gui/zmq_client.py:134` — increment in `start()` with logged value
- File: `src/cryodaq/gui/zmq_client.py:206-208` — `restart_count()` getter

**2. Exit code logging:**
- File: `src/cryodaq/gui/zmq_client.py:274-280` — log exitcode after subprocess termination

**Code delta:**
```python
# Initialization
self._restart_count: int = 0

# Increment on start
self._restart_count += 1
logger.info("ZMQ bridge subprocess started (PID=%d, restart_count=%d)", ...)

# Getter
return self._restart_count

# Exit code logging
exit_code = self._process.exitcode
if exit_code is not None:
    logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
```

**Hypothesis mapping:**
- Restart count + timestamps → correlate bridge restart frequency with B1 events
- Exit code → distinguish kill (-9), crash (non-zero), clean (0) termination

**Verification:**
- [x] Syntax validated
- [ ] Runtime: counter accessible; exit code in log

---

## Files Modified

| File | Lines | Nature | Reviewer Notes |
|------|-------|--------|----------------|
| src/cryodaq/launcher.py | +12, -1 | Hardening | Codex: thread-safe; Gemini: bound confirmed |
| src/cryodaq/gui/zmq_client.py | +16, -2 | Instrumentation | Codex: init needed, added; Gemini: focused |
| config/alarms_v3.yaml | +2, -1 | Config | Gemini: nesting verified |

Total: ~30 lines across 3 files. Surgical scope maintained.

---

## Validation Status

| Check | Status | Method |
|-------|--------|--------|
| Python syntax | PASS | ast.parse on all modified .py files |
| YAML syntax | PARTIAL | Visual + structure check; pyyaml unavailable |
| Targeted tests | SKIP | pytest not available in environment |
| Static inspection | PASS | All callers verified, no signature changes |
| Logic review | PASS | Reviews from Codex, Gemini integrated |

---

## Unverified (Runtime Required)

The following require runtime testing on actual CryoDAQ system:

1. Cooldown effectiveness during B1 failure scenario
2. alarm_v2 KeyError elimination (log observation)
3. Discrepancy logging trigger conditions
4. Restart counter increment and getter access
5. Exit code capture accuracy

These are deferred to next B1 diagnostic phase per plan.

---

## Explicitly Deferred (Per Plan)

- IV.7 ipc:// transport migration
- Root-cause B1 rewrite
- Launcher TCP probe transport-agnostic rewrite
- Python version migration
- Queueing redesign
- Broad queueing redesign
- ZMQ socket monitor events

---

*Implementation completed: 2026-04-21*
*Ready for: Final reviewer pass (Codex, Gemini, Kimi)*
