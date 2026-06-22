# Batch 04 — tier 0 — core: interlock/memory-leaks/p0-p1/persistence (99 tests, 10 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 4 MED / 3 LOW. 6 files clean.

## Findings

- **HIGH** test_p0_fixes.py:230 `test_alarm_publishes_alarm_count_on_clear` —
  AlarmEngine.start() already publishes 0.0; test asserts `0.0 in count_values`, passes
  even if clear never publishes the final zero. Fix: drain initial count after start(),
  assert LAST count after clear == 0.0 and active_names == [].
- **HIGH** test_persistence_ordering.py:141 `test_ordering_guarantee_write_before_zmq` —
  only checks some row exists; a publish-before-write race passes. (ALSO the Windows CI
  flaky timeout, 2.0s.) Fix: gate/slow write_immediate, assert queue stays empty while
  write blocked, release, assert exact reading appears. (rewrite, not just timeout bump)
- **HIGH** test_memory_leaks.py:193 `test_broadcast_queue_bounded` — never calls
  _on_reading_callback; _make_reading() unused, clients cleared → overflow branch not
  run. Fix: fill broadcast_q, install fake client, call _on_reading_callback, assert no
  raise + qsize capped.
- **MED** test_memory_leaks.py:167 `test_on_reading_callback_no_task_when_no_clients` —
  asserts only queue empty; a fire-and-forget task returning early passes. Fix: spy
  asyncio.create_task, assert not called.
- **MED** test_p0_fixes.py:427 `test_safety_publish_failure_does_not_crash` — never
  asserts failing publish awaited. Fix: assert publish.await_count>=1 + state transitions.
- **MED** test_interlock.py:140 `test_action_called_async` — side-effect-after-sleep
  passes even if prod used create_task instead of awaiting. Fix: action blocked on
  Event, assert trip pending until set.
- **MED** test_interlock.py:310 `test_load_config_yaml` — checks only name exists +
  ARMED; threshold/comparison/action/pattern/cooldown could be ignored. Fix: drive
  readings via YAML threshold/pattern/action or assert loaded fields.
- **LOW** test_memory_leaks.py:81 `test_rate_estimator_maxlen_computed_from_window` —
  re-derives production formula. Fix: independent cases + behavioral cap.
- **LOW** test_memory_leaks.py:143 `..._fault_history_deque_has_maxlen...` — same
  formula re-derivation. Fix: behavioral bound after many record_fault().
- **LOW (reliability)** test_memory_leaks.py:220 `test_broadcast_pump_drains_queue` —
  fixed sleep(0.05) flakes on slow CI. Fix: poll with wait_for until q.empty().

Clean: test_interlock_action_dispatch, test_keithley_channel_state_publish,
test_operator_log, test_p1_fixes, test_phase_labels, test_physical_alarms_config.
