# Verify (amend cycle) — Batch 08 — drivers keithley/gpib/etalon

Codex gpt-5.5 high, READ-ONLY. 3 findings, all test-only fixable. Codex confirmed CLEAN: the
Keithley `_last_v` reset (stop / emergency_off_all), source-off readback, mock-force-off-skip, and
the etalon disconnect-listener (uses Event, not sleep) tests — the fix-pass non-mock seeding holds.

## FIXED (test-only)
- **F1 `test_gpib_bus_lock.py:148` test_gpib_connect_does_not_send_idn** — over-mocking: it
  monkeypatched `GPIBTransport._blocking_connect`, the very method that contains the no-*IDN?
  logic (gpib.py ~270-285), so the real path never ran. Now injects a fake `pyvisa.ResourceManager`
  via sys.modules so the REAL `_blocking_connect` executes against a recording fake resource;
  asserts `clears>=1` (real path ran) + no `*IDN?` write/query. Teeth: asserting clears==0 → FAIL.
- **F2 `test_etalon_multiline_continuous.py:107` test_read_channels_continuous_emits_first_cycle**
  — timestamp-blind: seeded CycleSnapshot(timestamp=ts) but only checked count/names/values; a
  regression to Reading.now() would pass. Now deterministic `ts=1.7e9`, asserts every
  `Reading.timestamp == datetime.fromtimestamp(ts, UTC)`. Teeth: wrong ts → FAIL.
- **F3 `test_etalon_multiline_continuous.py:338` test_burst_stop_persists_parquet_with_full_schema**
  — timestamp-blind: never checked the persisted `cycle_ts`. Now seeds 3 distinct per-cycle
  timestamps and asserts `table.column("cycle_ts").to_pylist() == [ts0,ts0,ts1,ts1,ts2,ts2]` (raw
  floats, as src stores). Teeth: reversed order → FAIL.

Independently re-verified: 59 pass (5 driver files, -m "not ollama") + ruff-clean. No DEFERRALS.
