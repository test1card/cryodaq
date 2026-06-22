# Batch-05 Fix Report

**Date:** 2026-06-22  
**Pytest:** 77 passed in ~49s  
**Ruff:** All checks passed  
**Files changed:** 7 test files (tests/core/ only — no src/ changes)

---

## Per-Finding Table

| # | Severity | File:Location | Finding | Status | Evidence |
|---|----------|---------------|---------|--------|----------|
| 1 | HIGH | test_safety_fixes.py:123 | `emergency_off` from FAULT_LATCHED: assertion `ok is False OR state==FAULT_LATCHED` is tautology | **FIXED** | Production returns `ok=True, latched=True`. Now asserts `ok is True` + `latched is True` + `state == FAULT_LATCHED` |
| 2 | HIGH | test_safety_fixes.py:238 | Only 20 voltage samples; rate branch never activates (need ≥60) | **FIXED** | Feed 65 V samples; assert estimator has NO entry for voltage channel (unit-gate confirmed) + state RUNNING |
| 3 | HIGH | test_safety_fixes.py:311 | Only 20 non-critical K samples; rate branch never activates | **FIXED** | Feed 65 K samples on T4; assert `buffer_size("Т4 Радиатор 2") >= 60` (gate actually tested) + state RUNNING |
| 4 | HIGH | test_safety_manager.py:412 | Only asserts `state != RUN_PERMITTED`; SAFE_OFF transition would pass | **FIXED** | Now asserts `state == FAULT_LATCHED` + `fault_reason` contains stale-channel evidence ("Т1 Криостат верх" or "Устаревшие") |
| 5 | HIGH | test_scheduler.py:187 | No overlap counter; parallel connects pass | **FIXED** | Added `concurrent_count` / `max_concurrent` counter with 20ms connect delay; asserts `max_concurrent == 1` |
| 6 | HIGH | test_scheduler.py:219 | Sleep-based, poll may have already completed; in-flight not proven | **FIXED** | Driver blocks on `release_read` event; `read_started` event proves in-flight before `stop()`; release before drain timeout; asserts `read_completed=True` + disconnect called |
| 7 | MED | test_rate_estimator.py:110 | All 120 pts same slope; ignoring window_s passes | **FIXED** | Old batch (+10 K/min, 300s in the past) + recent batch (+2 K/min, 60 pts in window); asserts `rate ≈ 2.0 ± 0.3` |
| 8 | MED | test_rate_estimator.py:123 | 40 total pts < min_points(60); doesn't isolate custom-window filtering | **FIXED** | 60 old pts (outside window) + 30 recent pts (inside window); asserts `buffer_size >= 60` then `get_rate_custom_window → None` |
| 9 | MED | test_readings_history.py:55 | Asserts presence only; wrong values pass | **FIXED** | Asserts `points[0][1] == 4.2`, `points[-1][1] == 4.2+99*0.01`, first timestamp ≈ base_ts, oldest-first order |
| 10 | MED | test_readings_history.py:65 | Count only; wrong values/timestamps pass | **FIXED** | Asserts all returned timestamps ≥ from_ts, first value ≥ row-50 value |
| 11 | MED | test_readings_history.py:83 | Count + direction only; wrong "latest" slice passes | **FIXED** | Asserts `points[-1][1] == 4.2+99*0.01` (newest) and `points[0][1] == 4.2+90*0.01` (10th-from-end) |
| 12 | MED | test_readings_history.py:102 | Only asserts count; async≠sync not detected | **FIXED** | Calls both `_read_readings_history` and `read_readings_history`; asserts `async_data == sync_data` |
| 13 | MED | test_safety_manager.py:443 | Only asserts `len == 2`; timeout values not verified | **FIXED** | Asserts pattern strings "Т1 .*" and "Т7 .*" present; asserts `stale_timeout_s == 10.0` and `heartbeat_timeout_s == 15.0` |
| 14 | MED | test_safety_manager.py:672 | Fixed sleep, no ordering recorded; actual order not verified | **FIXED** | `call_order` list records "callback" and "channel_states_start"; patches `_publish_keithley_channel_states` (step 5) as slow coroutine; asserts `call_order.index("callback") < call_order.index("channel_states_start")`. Note: `_publish_state` is a fire-and-forget task from `_transition` and races independently — the contract is callback-before-channel-states-publish, not callback-before-_publish_state. |
| 15 | MED | test_safety_rate_estimator_config.py:10 | Private constant check; rename/refactor would miss regression | **FIXED** | Behavioral: 59 samples → `get_rate() is None`; 60th sample → `get_rate() is not None`; 65 samples → `rate > 5.0 K/min` |
| 16 | LOW | test_scheduler.py:73 | Fixed `sleep(0.1)` flakes | **FIXED** | `await asyncio.wait_for(queue.get(), timeout=2.0)` — deterministic, no sleep |
| 17 | LOW | test_safety_dual_channel.py:31 `_feed_ready` | `sleep(1.2)`, ~0.2s margin over 1.0s monitor | **FIXED** | `_feed_ready` now accepts optional `manager` arg; polls `manager.state == READY` in 0.05s increments up to 3s timeout; all 4 callers updated |

**No DEFERRED-PRODUCTION-BUG items.** All 17 findings resolved in test files only.

---

## Key Decisions

- **Finding #1 (emergency_off contract):** Production `safety_manager.py:410-418` returns `ok=True, latched=True, warning=...` from FAULT_LATCHED. The old test's `ok is False OR state==FAULT_LATCHED` was always true (second disjunct guaranteed). Fixed to assert the exact production contract.

- **Finding #14 (callback ordering):** `_transition` schedules `_publish_state` as a fire-and-forget `asyncio.create_task` that races independently. The Jules R2 Q1 contract is specifically about the shielded sequence: `fault_log_callback` (step 3/4) completes before `_publish_keithley_channel_states` (step 5). Test now patches `_publish_keithley_channel_states` directly to make it the observable slow step.

- **test_readings_history env var:** Added `os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")` to `writer_with_data` fixture — consistent with pattern in `test_audit_fixes.py`, `test_experiment.py`, `test_persistence_ordering.py`.

---

## Exact Pytest Line

```
pytest tests/core/test_safety_fixes.py tests/core/test_safety_manager.py tests/core/test_scheduler.py tests/core/test_rate_estimator.py tests/core/test_readings_history.py tests/core/test_safety_rate_estimator_config.py tests/core/test_safety_dual_channel.py -q --no-header
```

Result: **77 passed in 49.44s**

## Ruff

```
ruff check tests/core/test_safety_fixes.py tests/core/test_safety_manager.py tests/core/test_scheduler.py tests/core/test_rate_estimator.py tests/core/test_readings_history.py tests/core/test_safety_rate_estimator_config.py tests/core/test_safety_dual_channel.py
```

Result: **All checks passed!**

## Files Changed

- `tests/core/test_safety_fixes.py` — findings 1, 2, 3
- `tests/core/test_safety_manager.py` — findings 4, 13, 14
- `tests/core/test_scheduler.py` — findings 5, 6, 16
- `tests/core/test_rate_estimator.py` — findings 7, 8
- `tests/core/test_readings_history.py` — findings 9, 10, 11, 12
- `tests/core/test_safety_rate_estimator_config.py` — finding 15
- `tests/core/test_safety_dual_channel.py` — finding 17
