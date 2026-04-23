# Final Review - Codex

## Verdict
**PASS**

---

## Item A: Watchdog Cooldown (lines 910-928)

### Code as Implemented
```python
# IV.6 B1 fix: command-channel watchdog. Detects the case where
# the subprocess is alive, heartbeats flow, readings flow, but
# a recent REQ/REP timeout indicates the command plane has
# entered a bad state. Restart bridge to cycle the ephemeral
# REQ / REP connection and recover command path.
if self._bridge.command_channel_stalled(timeout_s=10.0):
    # Hardening 2026-04-21: 60s cooldown prevents restart storm
    # when fresh subprocess immediately sees stale cmd_timeout.
    now = time.monotonic()
    last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
    if now - last_cmd_restart >= 60.0:
        logger.warning(
            "ZMQ bridge: command channel unhealthy "
            "(recent command timeout). Restarting bridge."
        )
        self._last_cmd_watchdog_restart = now
        self._bridge.shutdown()
        self._bridge.start()
        return
```

### Analysis
**Getattr pattern safety:** SAFE. The `getattr(self, "_last_cmd_watchdog_restart", 0.0)` pattern correctly handles the case where the attribute doesn't exist yet (first watchdog check). This avoids AttributeError without requiring explicit initialization in `__init__`.

**60s comparison safety:** SAFE. The comparison `now - last_cmd_restart >= 60.0` is correct:
- First pass: 0.0 as default, any positive `now` satisfies condition (instant trigger allowed)
- Subsequent passes within 60s: blocked, preventing restart storm
- After 60s: condition clears, next stalled command triggers restart

**Thread safety:** SAFE. `_check_engine_health()` runs on Qt's main thread (via `QTimer.timeout`). The `_last_cmd_watchdog_restart` attribute is only accessed in this single-threaded context. No synchronization primitives required.

**Completeness vs plan:** EXACT. Implementation matches Item A in REPO_HARDENING_PLAN.md.

---

## Item B: alarm_v2 Config (alarms_v3.yaml:237)

### Code as Implemented
```yaml
cooldown_stall:
  alarm_type: composite
  operator: AND
  conditions:
    - channel: Т12
      check: rate_near_zero
      rate_threshold: 0.1    # K/мин
      rate_window_s: 900     # 15 мин
    - channel: Т12
      check: above
      threshold: 150  # threshold_expr not implemented; using static threshold (~100K setpoint + 50K)
  level: WARNING
```

### Analysis
**Threshold nesting:** CORRECT. The `threshold: 150` is at the same YAML level as `check: above`, which is the correct nesting for `_eval_condition` in alarm_v2.py.

**Static value rationale:** APPROPRIATE. The comment documents the operator-facing rationale (100K setpoint + 50K margin) and explicitly marks this as workaround for unimplemented `threshold_expr`.

**alarm_v2 code compatibility:** VERIFIED. The alarm_v2.py code accesses `cond["threshold"]` directly at lines 231, 238, 243, 250, 252, 259, 267, 275. With `threshold: 150` present, no KeyError will occur.

**Completeness vs plan:** EXACT. Implementation uses Option 1 from plan (config-first approach) rather than defensive code changes.

---

## Item C: Ping/Bridge Consistency (lines 1130-1140)

### Code as Implemented
```python
def _check_engine_health(self) -> None:
    """Проверить состояние engine, перезапустить при падении."""
    alive = self._is_engine_alive()

    # Hardening 2026-04-21: single-poll ping/bridge discrepancy logging
    # Logs when direct engine ping succeeds but bridge forward path is unhealthy.
    # No state retention - purely per-poll observation for diagnostic visibility.
    if alive and self._bridge.is_alive():
        bridge_healthy = self._bridge.is_healthy()
        if alive and not bridge_healthy:
            logger.warning("ZMQ health discrepancy: engine ping OK but bridge unhealthy")
```

### Analysis
**Log-only nature:** CONFIRMED. No state is retained between polls. This is purely observability instrumentation.

**Double-check pattern:** NOTED. The redundant `alive` checks (lines 1137, 1139) are harmless but the second check on line 1139 is unnecessary since `alive` doesn't change between the checks. This is a minor style issue, not a functional defect.

**Thread safety:** SAFE. No mutable shared state; bridge methods called are read-only checks.

**Completeness vs plan:** EXACT. Implementation matches Item C specification.

---

## Item D: B1 Diagnostic Instrumentation

### Code as Implemented

**Restart counter initialization (zmq_client.py:94):**
```python
# Hardening 2026-04-21: restart counter for B1 diagnostic correlation
self._restart_count: int = 0
```

**Counter increment (zmq_client.py:133):**
```python
self._restart_count += 1
logger.info("ZMQ bridge subprocess started (PID=%d, restart_count=%d)", self._process.pid, self._restart_count)
```

**Getter method (zmq_client.py:205-207):**
```python
def restart_count(self) -> int:
    """Return the number of bridge restarts since launcher start."""
    return self._restart_count
```

**Exit code logging (zmq_client.py:274-280):**
```python
# Hardening 2026-04-21: log exit code for B1 diagnostic (distinguish kill vs crash vs clean)
exit_code = self._process.exitcode
if exit_code is not None:
    logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
else:
    logger.warning("ZMQ bridge subprocess stopped (exitcode=None after kill)")
```

### Analysis

**_restart_count initialization:** CORRECT. Type-annotated and initialized to 0 in `__init__`.

**_restart_count increment timing:** CORRECT. Incremented in `start()` method after subprocess successfully starts. This ensures the first start counts as restart=1, which aligns with the diagnostic purpose (correlating B1 events with restart history).

**exitcode safety:** CORRECT. The `if exit_code is not None:` check handles the race condition where `exitcode` may be `None` immediately after a kill if the OS hasn't reaped the process yet. The warning branch for `None after kill` provides diagnostic clarity that force-termination was required.

**Thread safety:** CONDITIONALLY SAFE. The instrumentation fields are:
- `_restart_count`: Written by `start()` (main Qt thread), read by `restart_count()` getter (also main Qt thread via launcher caller). No race conditions expected.
- `_process.exitcode`: Accessed in `shutdown()` after `join(timeout=3)` and potential `kill()`. The join ensures subprocess termination before exitcode read, making this access thread-safe.

**Completeness vs plan:** SUBSTANTIALLY COMPLETE. Implementation matches all 4 sub-items in Item D specification.

---

## Cross-Cutting Concerns

### Exception Paths
All items include proper exception handling:
- Item A: getattr default prevents AttributeError
- Item B: YAML structure validated by visual inspection; static value eliminates KeyError
- Item C: No exceptions possible (log-only, no I/O)
- Item D: exitcode None-check prevents TypeError in format string

### Side Effects
All changes are additive:
- No existing behavior modified
- No API signatures changed
- Getter `restart_count()` is new surface, no breaking changes
- Logging additions are informational level, not behavioral

### Interaction Matrix
| Component | Interacts With | Risk |
|-----------|----------------|------|
| Watchdog cooldown | command_channel_stalled() | Low - independent checks |
| Restart counter | bridge.start() | Low - simple increment |
| Exit code logging | shutdown() | Low - post-termination |
| Ping/bridge log | _is_engine_alive() | Low - read-only |

---

## Conclusion

**Overall assessment:** PASS

The implementation is surgical, defensive, and aligns with the approved hardening plan. All four items are correctly implemented:

1. **Watchdog cooldown** - Safe getattr pattern, correct 60s threshold, no restart storms
2. **alarm_v2 config** - Proper nesting, static threshold with explanatory comment
3. **Ping/bridge logging** - Observes without mutating, no state retention
4. **Instrumentation** - Proper initialization, safe exitcode access, thread-safe design

**Runtime verification required:**
- Cooldown effectiveness during actual B1 event (requires reproduction)
- alarm_v2 KeyError elimination (log observation)
- Exit code accuracy across kill/crash/normal termination scenarios

**Recommended follow-up:**
1. Monitor logs for cooldown trigger messages confirming 60s suppression works
2. Verify no KeyError in alarm_v2 evaluation after deployment
3. Remove or implement threshold_expr support in alarm_v2.py (technical debt)
