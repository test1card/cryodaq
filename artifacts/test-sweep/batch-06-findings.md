# Batch 06 — tier 0 — core: sensor-diagnostics/sqlite/user-prefs (91 tests, 6 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 0 HIGH / 2 MED / 2 LOW. 3 files clean.

## Findings
- **MED** test_sqlite_writer.py:185 `test_wal_recovery_after_crash` — `writer_a._conn=None`
  just drops the ref after commit; not a crash. Proves committed data readable, not WAL
  crash recovery. Fix: subprocess writes + os._exit() without closing, parent opens
  fresh writer, verify rows + append.
- **MED** test_sensor_diagnostics_alarm_publishing.py:135
  `test_alarm_clears_when_status_returns_to_ok` — only checks "T1" in pub.cleared after
  clean update; would pass if cleared during alarm phase but failed on recovery. Fix:
  assert pub.cleared==[] before clean push, then exactly one clear after ok.
- **LOW** test_user_preferences.py:44 `test_history_max_limit` — `<= 20` passes with 1
  item; only checks newest. Fix: assert ==20 + exact order (Operator-24..05, 04 absent).
- **LOW** test_user_preferences.py:79 `test_suggest_name_without_map` — `"001" in name`
  passes with wrong prefix. Fix: assert exact "My Template-001".

Clean: test_sensor_classification, test_sensor_diagnostics, test_sensor_diagnostics_grace.
