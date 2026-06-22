# Batch 08 — tier 0 — drivers: keithley/gpib/etalon (82 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 0 HIGH / 4 MED / 5 LOW. 2 files clean.
NOTE: cycle-5 hardened tests (slew normal/large-step, emergency_off_single, gpib
recovery) were NOT re-flagged — they hold up under fresh review.

## Findings
- **MED** test_keithley_safety.py:108 `test_last_v_resets_on_stop` — mock; _last_v["smua"]
  already 0.0 (mock read doesn't seed it), so passes even if stop_source stopped
  resetting. SIBLING of the cycle-5 fix; same flaw. Fix: seed nonzero or non-mock path.
- **MED** test_keithley_safety.py:148 `test_last_v_resets_on_emergency_off_all` — same:
  both _last_v already zero before call. Fix: seed both channels nonzero.
- **MED** test_gpib_bus_lock.py:148 `test_gpib_connect_does_not_send_idn` — mock open()
  returns before any real path; no assertion after open(). Fix: fake non-mock RM/resource
  recording write/query, assert no *IDN? issued.
- **MED** test_keithley_2604b.py:94 `test_keithley_read_source_off` — mock bypasses the
  non-mock source.output readback; a NaN regression in real OFF branch passes. Fix: fake
  non-mock transport returns output=0, assert finite OFF values both channels.
- **LOW** test_keithley_connect_safety.py:60 `test_connect_skips_force_off_in_mock_mode`
  — asserts only _connected True; mock writes are no-ops. Fix: spy write, assert no
  force-off commands.
- **LOW** test_etalon_multiline_continuous.py:107/259/338 — value-blind (count/names/cols
  only). Fix: assert actual length/env/timestamp values, distinct buffered lengths,
  parquet cell values.
- **LOW (reliability)** test_etalon_multiline_continuous.py:427
  `test_disconnect_cancels_listener...` — fixed sleep(0.05) flake. Fix: Event set by fake
  write_command/read entry.

Clean: test_etalon_multiline_v0_55_13, test_keithley_dual_channel.
