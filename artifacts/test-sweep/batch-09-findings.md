# Batch 09 — tier 0 — drivers (lakeshore/thyracont/tcp/visa) + storage/archive (94 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 2 HIGH / 8 MED / 3 LOW. 3 files clean.

## HIGH
- test_visa_executors.py:56 `test_usbtmc_transport_no_default_executor` — inspect.getsource
  grep (the USBTMC sibling of the GPIB test I converted to a behavioral spy in cycle 5).
  Fix: mirror the spy — patch loop.run_in_executor, run non-mock USBTMC open/query/write
  with fake resource, assert executor is transport._get_executor().
- test_visa_executors.py:161 `test_close_all_managers_holds_rm_lock` — only checks
  "_rm_lock" string in source. Fix: spy lock/context-manager or controlled race vs
  _get_rm; assert close happens while lock held.

## MED
- test_visa_executors.py:88/96 `test_{gpib,usbtmc}_close_shuts_down_executor` — grep
  module source for _executor.shutdown. Fix: create executor, fake resource, await
  close(), assert _executor is None.
- test_lakeshore_218s.py:439/475/529 — calibration-curve tests assert metadata/raw value
  but NOT that Reading.value equals store.evaluate(...) curve output; KRDG fallback
  asserts only length/unit. Fix: assert calibrated values == store.evaluate, per-channel
  commands [KRDG?, KRDG? 1..8] + mapped values.
- test_archive_reader.py:95/147/243 — parquet/sqlite/merge tests assert
  channel/count/sorted-order only, not values. Fix: assert exact (timestamp,value)
  sequences (incl. 5-parquet+3-sqlite merge order).

## LOW
- test_multiline_reconfigure.py:76 — checks keys only, not nominal formula. Fix: assert
  exact {7:1350.0, 14:1700.0}.
- test_tcp_transport.py:257 — fixed sleep(0.05) poll flake. Fix: Event/Future + wait_for.
- test_archive_reader.py:182 `test_missing_archive_file_returns_partial` — checks 5 points
  exist, not day2 values. Fix: assert exact day2 rows, no day1 timestamps.

Clean: test_lakeshore_idn_validation, test_thyracont_checksum_default, test_thyracont_vsp63d.
