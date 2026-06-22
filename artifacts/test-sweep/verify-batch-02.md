# Verify (amend cycle) — Batch 02 — core cooldown/engine/event

Codex gpt-5.5 high, READ-ONLY. 3 findings, all test-only fixable. The leak-rate copied
`_dispatch` HIGH item remains a known/intentional deferral (engine closure extraction) — not
re-touched.

## FIXED (test-only)
- **F1 `test_engine_force_kill.py:16` test_force_kill_removes_lock_when_pid_not_alive** —
  patched `_is_pid_alive` but never asserted it was consulted; an impl that unlinks the lock
  without parsing the PID would pass. Now `is_pid_alive.assert_called_once_with(12345)`
  (line 19). Teeth: wrong PID 99999 → FAIL.
- **F2 `test_cooldown_alarm_v0_55_12.py:170` ...swallows_latch_fault_exception** — asserted
  a CRITICAL event reached `alarm_mgr.process` but only checked `args[1] is not None`; a
  non-CRITICAL event would pass. Now captures the event and asserts `level=="CRITICAL"` +
  `alarm_id=="cooldown_alarm"` (209-212). Teeth: asserting WARNING → FAIL.
- **F3 `test_engine_leak_rate_command.py:70` test_leak_rate_start_with_duration_override** —
  fix pass had asserted `est._window_override == 120.0` (brittle private storage detail — the
  original FIND finding even suggested it). Verify replaced it with OBSERVABLE behavior:
  `should_finalize()` is False at +61s and True at +121s after start with duration_s=120
  (lines 78-95). `_t0` is read only to anchor sample datetimes, not asserted on. Public seam,
  refactor-safe.

## Clean (Codex concurs — fix-pass work holds)
- test_deep_review.py — correlation > 0.99 (not just non-None).
- test_event_logger.py — asserts writer call awaited + warning logged.

Independently re-verified: 48 pass (5 files) + ruff-clean. No new DEFERRALS (leak-rate
`_dispatch` deferral unchanged).
