# Batch 09 — Fix Report

Date: 2026-06-22

## Per-Finding Table

| Finding | Severity | Location | Status | Action |
|---------|----------|----------|--------|--------|
| `test_usbtmc_transport_no_default_executor` | HIGH | test_visa_executors.py:56 | FIXED | Replaced source-grep with behavioral spy: patch `loop.run_in_executor`, call `query()` + `write()` on non-mock transport with fake resource, assert executor arg is `transport._get_executor()`. |
| `test_close_all_managers_holds_rm_lock` | HIGH | test_visa_executors.py:161 | FIXED | Replaced source-grep with spy lock: `_SpyLock` wraps a real `threading.Lock`, records `locked()` state inside `rm.close()`, asserts lock was held. |
| `test_gpib_close_shuts_down_executor` | MED | test_visa_executors.py:88 | FIXED | Replaced source-grep with behavioral: force `_get_executor()`, call `await transport.close()`, assert `transport._executor is None`. |
| `test_usbtmc_close_shuts_down_executor` | MED | test_visa_executors.py:96 | FIXED | Same pattern as GPIB: fake resource + manager, `await close()`, assert `_executor is None`. |
| `test_runtime_calibration_global_on_uses_curve_and_preserves_metadata` | MED | test_lakeshore_218s.py:439 | FIXED | Added `readings[0].value == pytest.approx(store.evaluate("ls218s:CH1", readings[0].raw))` — proves calibrated value flows through, not raw KRDG. |
| `test_runtime_calibration_hybrid_mode_uses_curve_only_for_enabled_channels` | MED | test_lakeshore_218s.py:475 | FIXED | Added: CH1 value == `store.evaluate(...)` output; CH2 value == 4.891 (KRDG passthrough). |
| `test_krdg_fallback_to_per_channel` | MED | test_lakeshore_218s.py:529 | FIXED | Added command tracking: assert `KRDG? 1..KRDG? 8` all issued; assert each `reading.value == expected_values[i]`. |
| `test_query_archived_uses_parquet` | MED | test_archive_reader.py:95 | FIXED | Added exact `(timestamp, value)` loop over all 10 points from parquet. |
| `test_query_recent_uses_sqlite` | MED | test_archive_reader.py:147 | FIXED | Added exact `(timestamp, value)` loop over all 15 SQLite points. |
| `test_query_merges_sqlite_and_parquet` | MED | test_archive_reader.py:243 | FIXED | Added exact value checks: 5 parquet points (70.0+i) then 3 SQLite points (85.0+i) in merge order. |
| `test_reconfigure_refreshes_mock_nominals` | LOW | test_multiline_reconfigure.py:76 | FIXED | Added `assert _mock_nominal_lengths_mm[7] == 1350.0` and `[14] == 1700.0`. |
| `test_write_command_sends_line_without_reading_response` | LOW | test_tcp_transport.py:257 | FIXED | Replaced `sleep(0.05)` poll loop with `asyncio.Event` + `asyncio.wait_for(..., timeout=2.0)`. |
| `test_missing_archive_file_returns_partial` | LOW | test_archive_reader.py:182 | FIXED | Added exact day2 rows check: each ts >= day2_ts, ts < day2_ts+86400, value == 90.0+i. |

## Files Changed

- `tests/drivers/test_visa_executors.py` — 3 tests replaced (HIGH×2, MED×2); removed `import inspect` (now unused)
- `tests/drivers/test_lakeshore_218s.py` — 3 tests hardened (MED×3)
- `tests/storage/test_archive_reader.py` — 3 tests hardened (MED×2, LOW×1)
- `tests/drivers/test_multiline_reconfigure.py` — 1 test hardened (LOW×1)
- `tests/drivers/test_tcp_transport.py` — 1 test hardened (LOW×1)

## Exact pytest line

```
pytest tests/drivers/test_visa_executors.py tests/drivers/test_lakeshore_218s.py tests/drivers/test_multiline_reconfigure.py tests/drivers/test_tcp_transport.py tests/storage/test_archive_reader.py -q --no-header
```

Result: **69 passed in 6.45s**

## Ruff

```
ruff check tests/drivers/test_visa_executors.py tests/drivers/test_lakeshore_218s.py tests/drivers/test_multiline_reconfigure.py tests/drivers/test_tcp_transport.py tests/storage/test_archive_reader.py
```

Result: **All checks passed!**

## Deferred

None. All 13 findings fixed.
