# Batch 00 — tier 0 — alarm core (98 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 0 HIGH / 4 MED / 3 LOW. 3 files clean.

Files: test_advance_phase_command, test_alarm, test_alarm_config, test_alarm_v2,
test_alarm_v2_diagnostic_rule, test_alarm_v2_integration, test_alarm_v2_legacy_cleanup.

## Findings

- **MED** test_alarm.py:353 `test_event_history_bounded` — asserts only
  `len(events) <= 1000`; passes for 0/2/999 events, never proves the cap is hit or
  old events evicted. Fix: drive to the expected volume, assert `== 1000` and that
  earliest retained event isn't from the first cycles.
- **MED** test_alarm_v2.py:194 `test_threshold_sustained_fires_after_delay` —
  manually seeds `state_mgr._sustained_since["drift"]`, bypassing the real
  "first-true starts the timer" path. Fix: fake clock — first process()→None records
  sustained_since, advance clock, second process()→"TRIGGERED".
- **MED** test_alarm_v2_integration.py:213 `test_alarm_v2_status_shape` — never calls
  the command handler (engine.py:2347); only inspects an AlarmEvent. Misses payload
  fields ok/active/history/acknowledged/... Fix: exercise the serialization path.
- **MED** test_alarm_v2_legacy_cleanup.py:16 `test_measurement_thresholds_removed...`
  — checks 3 hard-coded removed IDs; a renamed measurement Т11/Т12 absolute threshold
  would pass. Fix: walk phase_alarms.measurement via load_alarm_config(), reject
  threshold checks on Т11/Т12 with explicit exemptions.
- **LOW** test_alarm_v2_integration.py:99 `test_phase_alarm_fires_in_correct_phase` —
  never sets phase_filter or calls tick_alarm; phase matching could be broken and it
  passes. Fix: AlarmConfig(phase_filter=["measurement"]) + tick_alarm(current_phase=
  "measurement"), or drop as redundant with the suppressed-outside-phase positive control.
- **LOW** test_alarm_v2_integration.py:235 `test_alarm_v2_ack` — calls
  AlarmStateManager.acknowledge() directly, not the command handler (engine.py:2392);
  no response shape / broker ack event. Fix: exercise the handler.
- **LOW** test_alarm_v2_legacy_cleanup.py:48 `test_calibrated_sensor_fault_retained`
  — only checks the key exists. Fix: assert rule semantics (global, threshold,
  calibrated channels, check=="outside_range", expected range).

Clean: test_advance_phase_command, test_alarm_config, test_alarm_v2_diagnostic_rule.
