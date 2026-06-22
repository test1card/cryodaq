# Batch 02 — tier 0 — core: cooldown/engine/event (100 tests, 10 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 2 MED / 1 LOW. 5 files clean.

## Findings

- **HIGH** test_engine_leak_rate_command.py:57 — all `test_leak_rate_*` route through a
  LOCAL copied `_dispatch()` (lines 23-49), not production `engine._handle_gui_command`.
  Already STALE: production validates duration_s numeric/positive/finite; the copy
  doesn't. Fix: extract prod leak-rate dispatch into an importable helper and test that,
  or exercise the real handler. (same anti-pattern as the cycle-4 alarm-tick copy)
- **HIGH** test_engine_force_kill.py:8 `test_force_kill_reads_pid_via_os_open` —
  inspect.getsource grep; a comment satisfies it. Fix: temp _LOCK_FILE, monkeypatch
  Path.read_text→PermissionError, spy os.open/read/close, run _force_kill_existing(),
  assert lock handled/unlinked.
- **HIGH** test_cooldown_alarm_v0_55_12.py:170
  `test_cooldown_alarm_critical_swallows_latch_fault_exception` — only checks "does not
  raise"; passes if production stopped calling latch_fault entirely. Fix: assert
  latch_fault.assert_awaited_once(), alarm.state==FIRED, alarm_mgr.process got a
  non-None CRITICAL event.
- **MED** test_engine_leak_rate_command.py:70 `..._start_with_duration_override` —
  asserts only ok + is_active; passes if duration_s ignored. Fix: assert
  est._window_override == 120.0 or finalize-boundary behavior changes.
- **MED** test_deep_review.py:14 `test_correlation_with_tiny_timestamp_offset` —
  asserts only `correlation is not None`; wrong/negative value passes. Fix: assert > 0.99.
- **LOW** test_event_logger.py:65 `test_silently_fails_on_error` — only checks no
  exception; stale (prod now logs a warning). Fix: assert append_operator_log awaited +
  caplog warning; rename.

Clean: test_cooldown_alarm, test_diagnostic_alarm_aggregation, test_disk_monitor,
test_engine_dual_channel, test_event_bus.
