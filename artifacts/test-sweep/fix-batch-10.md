# Fix Report: Batch 10 False-Confidence Test Sweep

## Per-Finding Table

| # | File | Line | Finding | Status | Fix Applied |
|---|------|------|---------|--------|-------------|
| MED-1 | test_multiline_persistence.py | 41 | `test_multiline_reading_writes_to_sqlite_before_broker_publish` — bypasses Scheduler/DataBroker; proves only direct SQLiteWriter persistence | FIXED | Renamed/scoped in docstring to "SQLiteWriter persists channel-agnostically"; `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE","1")` already present. Added two new runtime companion tests below the source-grep tests: `test_multiline_parquet_archive_runtime_channel_agnostic` and `test_multiline_cold_rotation_runtime_channel_agnostic`. |
| MED-2 | test_multiline_persistence.py | 126 | `test_multiline_parquet_archive_is_channel_agnostic` — source grep only, never runs export | FIXED | Retained grep (regression guard). Added `test_multiline_parquet_archive_runtime_channel_agnostic`: writes mixed-channel DB, calls `export_experiment_readings_to_parquet`, reads Parquet, asserts all channels + values present. |
| MED-3 | test_multiline_persistence.py | 148 | `test_multiline_cold_rotation_is_channel_agnostic` — source grep only, never runs rotation | FIXED | Retained grep. Added `test_multiline_cold_rotation_runtime_channel_agnostic`: writes mixed-channel old DB, runs `ColdRotationService.run_once`, reads Parquet archive, asserts all channels + values. |
| MED-4 | test_parquet_export.py | 183 | `test_export_experiment_id_column` — `all()` over empty list vacuously true | FIXED | Added `assert len(exp_ids) == 5` before `all()`. Replaced vacuous `all()` with `assert exp_ids == ["my-exp-42"] * 5`. |
| MED-5 | test_replay.py | 154 | `test_replay_stop` — fixed `sleep(0.05)` can complete before `stop()` | FIXED | Replaced fixed sleep with deterministic poll: 5 ms intervals until `queue.empty()` is False (up to 2 s), then calls `stop()`. Guarantees stop fires while replay is blocked in an inter-row sleep. |
| MED-6 | test_alarm_flow.py | 236,297,319,419,466,491,565 | 7 skip-handling tests — `sleep(0.05)+assert_not_awaited` unreliable with non-blocking EventBus | FIXED | All 7 tests now call `agent._should_handle(event) is False` directly (primary assertion), then publish to EventBus and yield two `await asyncio.sleep(0)` ticks. This tests the real filter logic without relying on timing. |
| LOW-1 | test_cold_rotation.py | 304 | `test_index_updated_on_rotation` — checksum length + `> 0` sizes, not actual values | FIXED | Added: `size_bytes_original == result.size_original`, `size_bytes_archive == result.size_archive`, computed actual MD5 of archive file and asserted `entry["checksum_md5"] == expected_md5`, resolved `archive_dir / archive_rel` and asserted it exists and matches `result.archive_path`. |
| LOW-2 | test_xlsx_export.py | 179 | `test_xlsx_max_rows_constant` — asserts literal constant only | FIXED | Added runtime truncation check: monkeypatches `_XLSX_MAX_ROWS=5`, writes 10 readings, exports, opens XLSX, asserts `data_rows < 10` and `count == data_rows`. Canonical value check retained. |
| LOW-3 | test_alarm_flow.py | 192,205,220,248,267,283,383,527 | 8 positive flow tests — fixed `sleep(0.05/0.1)` flake | FIXED | Replaced sleeps with `asyncio.Event` side-effects on the last mock in the dispatch chain (ollama.generate for simple cases; event_logger.log_event for dispatch tests). Tests now use `asyncio.wait_for(done.wait(), timeout=2.0)`. |

## Exact Pytest Line

```
pytest tests/storage/test_multiline_persistence.py tests/storage/test_parquet_export.py tests/storage/test_replay.py tests/storage/test_cold_rotation.py tests/storage/test_xlsx_export.py tests/agents/assistant/test_alarm_flow.py -q --no-header
```

Result: **59 passed in 0.56s**

## Ruff

```
ruff check tests/storage/test_multiline_persistence.py tests/storage/test_parquet_export.py tests/storage/test_replay.py tests/storage/test_cold_rotation.py tests/storage/test_xlsx_export.py tests/agents/assistant/test_alarm_flow.py
```

Result: **All checks passed!**

## Files Changed

- `tests/storage/test_multiline_persistence.py` — kept source-grep tests; added 2 runtime companion tests
- `tests/storage/test_parquet_export.py` — fixed vacuous `all()` at line 183
- `tests/storage/test_replay.py` — replaced fixed sleep with deterministic queue poll
- `tests/storage/test_cold_rotation.py` — strengthened index assertions with actual MD5 + size + path checks
- `tests/storage/test_xlsx_export.py` — replaced literal-constant test with monkeypatch truncation test
- `tests/agents/assistant/test_alarm_flow.py` — 7 skip tests → `_should_handle` direct; 8 positive tests → event-driven `asyncio.Event` signal

## Deferred

None. All 9 findings fixed without src/ changes.
