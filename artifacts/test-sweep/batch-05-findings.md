# Batch 05 — tier 0 — SAFETY-CRITICAL: safety_manager/scheduler/rate/dual-channel (93 tests, 9 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 6 HIGH / 8 MED / 3 LOW. 2 files clean.
This is the safety heart — HIGH findings here matter most.

## HIGH
- test_safety_fixes.py:238 `test_rate_limit_ignores_non_temperature` — publishes only
  20 voltage samples; estimator needs 60, so the rate branch NEVER activates. A bug
  rate-checking voltage after 60 samples would pass. Fix: publish ≥60 voltage samples
  spanning a high rate, assert no fault + no voltage channel in temp estimator.
- test_safety_fixes.py:311 `test_rate_limit_ignores_non_critical_channel` — same: only
  20 non-critical K samples (<60). Fix: ≥60 samples above threshold, assert RUNNING.
- test_safety_fixes.py:123 `test_fault_latched_not_cleared_by_emergency` — assertion
  `ok is False OR state==FAULT_LATCHED` lets prod ok=True pass; API contract untested.
  Fix: decide contract, assert ok directly + latched True + unchanged FAULT_LATCHED.
- test_safety_manager.py:412 `test_run_permitted_state_is_actively_monitored` — asserts
  only state changed from RUN_PERMITTED; a wrong transition to SAFE_OFF passes. Fix:
  assert state==FAULT_LATCHED + fault reason has stale-channel evidence.
- test_scheduler.py:187 `test_gpib_sequential_connect` — checks both names in
  connect_order; parallel connects also pass. Fix: overlap counter, assert max
  concurrent==1.
- test_scheduler.py:219 `test_stop_graceful_drain_completes_inflight` — sleeps until a
  poll already completed; doesn't prove in-flight during stop(). Fix: driver read
  signals started + blocks on event; stop() while blocked, release before timeout,
  assert completed + disconnect without forced cancel. (distinct from the :235 drain
  timeout test hardened in cycle 5)

## MED
- test_rate_estimator.py:110 `test_rate_custom_window_shorter` — all 120 pts same
  slope; ignoring window_s passes. Fix: old pts different slope + recent 2 K/min.
- test_rate_estimator.py:123 `test_rate_custom_window_insufficient` — 40 pts < min_points
  60; doesn't isolate custom-window filtering. Fix: ≥60 total, <60 in window.
- test_readings_history.py:55/65/83/102 — assert presence/approx-count/length only;
  wrong values/timestamps/oldest-vs-latest pass. Fix: assert exact rows + timestamps +
  first/last values; async==sync equivalence.
- test_safety_manager.py:443 `test_load_config_succeeds_with_valid_config` — asserts 2
  patterns only; timeout/heartbeat ignored. Fix: assert pattern strings +
  stale_timeout_s==10.0 + heartbeat_timeout_s==15.0.
- test_safety_manager.py:672 `test_fault_log_callback_runs_before_publish` — fixed sleep,
  no ordering recorded; _transition schedules _publish_state before callback (ambiguous).
  Fix: ordered event list, account for _publish_state.
- test_safety_rate_estimator_config.py:10 `..._min_points_at_least_60` — asserts a
  private constant, not behavior. Fix: 59 steep samples no fault; 60th/65th faults.

## LOW (reliability)
- test_scheduler.py:73 `test_mock_driver_polled` — fixed sleep(0.1) flakes. Fix: wait_for queue.get.
- test_safety_dual_channel.py:31 `_feed_ready` — sleep(1.2), ~0.2s margin over 1.0s monitor. Fix: wait_for state==READY.

Clean: test_physical_alarms_config_landmarks, test_safety_set_target.
