# Verify (amend cycle) — Batch 05 — SAFETY-CRITICAL: safety_manager/scheduler/rate/dual-channel

Codex gpt-5.5 high, READ-ONLY. 5 findings; 4 fixed (test-only), 1 kept by-design. The safety
heart — reviewed with extra rigor. Codex confirmed CLEAN: fault_latched_not_cleared_by_emergency,
rate_limit_ignores_non_critical_channel, load_config_succeeds, fault_log_callback_runs_before_publish,
mock_driver_polled, stop_graceful_drain_completes_inflight, rate_custom_window_* , _feed_ready.

## FIXED (test-only)
- **F1 `test_safety_fixes.py:238` test_rate_limit_ignores_non_temperature** — "no fault" was
  weak because `critical_channels=[]` (prod only rate-faults critical channels, sm.py:986), so
  nothing could fault regardless. Now makes "Keithley/voltage" CRITICAL, feeds 65 high-slope V
  samples (would fault a K-channel), asserts state==RUNNING — proves voltage is excluded at the
  unit/estimator level even when critical. + secondary: voltage absent from estimator.channels().
- **F2 `test_safety_manager.py:412` test_run_permitted_state_is_actively_monitored** — fault-
  reason disjunction `... or "Устаревшие" in _fault_reason` passed for a generic message with no
  channel evidence. Now asserts `_state==FAULT_LATCHED` (was "changed from RUN_PERMITTED") AND
  `"Т1 Криостат верх" in _fault_reason` (prod emits the channel, sm.py:951).
- **F3 `test_readings_history.py:83` test_read_readings_history_time_filter** — exact-boundary
  fix exposed a REAL FLAKE: fixture stored timestamps via datetime.fromtimestamp (µs precision)
  from `base_ts = time.time()-7200` (sub-µs float bits at ~1.7e9), so row-50's stored ts jittered
  above/below the raw-float `from_ts` by the wall-clock fraction → flaky 49/50. Failed once in a
  7-file run, passed in isolation. FIX (fixture, test-only): anchor `base_ts = float(int(time.time())
  -7200)` (whole second) → datetime round-trip lossless → row 50 == from_ts exactly → deterministic
  50. Verified: 0/20 fails on the boundary test + 2 clean full-set runs (each a fresh wall-clock
  fraction). Kept the exact-50 + first/last-value asserts.
- **F5 `test_scheduler.py:187` test_gpib_sequential_connect** — outer fixed `0.3s` completion
  wait was brittle. Now per-driver `d1_connected`/`d2_connected` Events + wait_for; kept the small
  intra-connect `sleep(0.02)` that creates the overlap-detection window. max_concurrent==1 assert
  intact.

## CONSIDERED — kept by design (NOT a fix)
- **F4 `test_safety_rate_estimator_config.py` min_points_at_least_60** — Codex called the
  60→not-None assertion over-fit to an exact threshold. REJECTED: the test deliberately encodes
  the two-sided min_points=60 contract (docstring: <60 → false faults from LS218 noise; >60 →
  faults delayed too long) and uses the estimator's PUBLIC push/get_rate. It does exactly what the
  original FIND finding asked (59→None, 60/65→rate). Churning a safety contract test on a
  borderline stylistic point would re-litigate a deliberate design choice. File left untouched.

Independently re-verified: 77 pass (full batch-5 set) + ruff-clean; F3 flake stress-tested gone.
No DEFERRALS.
