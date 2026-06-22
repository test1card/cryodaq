# Batch 01 — tier 0 — core: storage/calibration/channel-state (92 tests, 9 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 1 HIGH / 1 MED / 4 LOW. 5 files clean.

## Findings

- **HIGH** test_audit_fixes.py:226 `test_sqlite_filters_inf` — STALE PREMISE.
  Claims float('inf') must be filtered, but production (sqlite_writer.py:350) now
  intentionally persists OVERRANGE/UNDERRANGE infinities; test passes only because
  readings default to ChannelStatus.OK. Fix: rename to "OK non-finite filtered", set
  status explicitly, add companion asserts that OVERRANGE +inf / UNDERRANGE -inf persist.
- **MED** test_calibration_commands.py:59 `test_calibration_curve_export_import` —
  export asserts only paths exist (74-75); zero-byte/wrong-content table would pass;
  import checks only sensor_id, not curve identity/coeffs/evaluation. Fix: parse
  exported artifacts, assert sensor id + curve id/coeffs or evaluated-T equivalence,
  assert artifacts non-empty.
- **LOW** test_calibration_commands.py:88 `test_calibration_curve_list_and_lookup` —
  list verified only by len==1; a wrong curve passes. Fix: assert curve_id + sensor_id.
- **LOW** test_channel_state.py:88 `test_fault_recording_and_count` — `>= 1`; duplicate
  recording in one update() passes. Fix: assert `== 1`.
- **LOW** test_channel_state.py:176 `test_resolve_fault_count` — `>= 1`; same. Fix: `== 1`.
- **LOW** test_channel_taxonomy.py:52 `test_get_channels_in_zone_disconnected_reserve`
  — checks length + endpoints only; wrong interior member passes. Fix:
  `set(reserves) == {f"Т{i}" for i in range(17,25)}`.

Clean: test_atomic_write, test_audit_fixes(rest), test_broker,
test_calibration_acquisition, test_channel_manager_cold, test_channel_manager_off_change.
