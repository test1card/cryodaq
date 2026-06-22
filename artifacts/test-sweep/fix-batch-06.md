# Fix Report — Batch 06

## Per-Finding Table

| # | Severity | Location | Finding | Verdict | Fix Applied |
|---|----------|----------|---------|---------|-------------|
| 1 | MED | `tests/core/test_sqlite_writer.py:185` `test_wal_recovery_after_crash` | `writer_a._conn=None` is a refcount drop after commit, not a crash. Data is always readable regardless. Test proved nothing about WAL crash recovery. | FIXED | Replaced with subprocess crash via `multiprocessing.get_context("spawn")` + `os._exit(1)`. Child writes 10 rows and hard-exits without closing. Parent asserts exit code == 1, then opens a fresh `SQLiteWriter`, reads 10 rows, appends 3 more, asserts 13 total. Added `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE","1")` to parent; subprocess sets it before importing `SQLiteWriter`. Also fixed pre-existing failure in `test_write_batch_creates_db` (same file, same cause — missing env var). |
| 2 | MED | `tests/core/test_sensor_diagnostics_alarm_publishing.py:135` `test_alarm_clears_when_status_returns_to_ok` | Only asserts `"T1" in pub.cleared` after ok push. Would pass if clear fired during the alarm phase (pre-clear). No guard that clear count is exactly one. | FIXED | Added `assert pub.cleared == []` before `_push_clean` call (guards no premature clear). Changed final assert to `assert pub.cleared == ["T1"]` (exact list, exact count — fails if clear fires 0 or 2+ times). |
| 3 | LOW | `tests/core/test_user_preferences.py:44` `test_history_max_limit` | `len(history) <= 20` passes with 1 item; only checks `history[0]`. Does not verify truncation happened or order of retained entries. | FIXED | Changed to `assert len(history) == 20`. Added `assert history[-1] == "Operator-05"` and full-list equality `assert history == [f"Operator-{i:02d}" for i in range(24, 4, -1)]`. Verifies count is exactly 20, oldest retained is 05, order is newest-first. |
| 4 | LOW | `tests/core/test_user_preferences.py:79` `test_suggest_name_without_map` | `"001" in name` passes with any prefix containing "001". Passes even if title-casing logic is wrong. | FIXED | Changed to `assert name == "My Template-001"`. Production code applies `.replace("_", " ").title()` to `"my_template"` → `"My Template"`, then appends `"-001"`. Exact string asserts both the prefix transform and the counter. |

## Files Changed

- `tests/core/test_sqlite_writer.py` — findings 1 + pre-existing `test_write_batch_creates_db`
- `tests/core/test_sensor_diagnostics_alarm_publishing.py` — finding 2
- `tests/core/test_user_preferences.py` — findings 3 + 4

## Verification

```
pytest tests/core/test_sqlite_writer.py tests/core/test_sensor_diagnostics_alarm_publishing.py tests/core/test_user_preferences.py -q --no-header
35 passed in 0.24s

ruff check tests/core/test_sqlite_writer.py tests/core/test_sensor_diagnostics_alarm_publishing.py tests/core/test_user_preferences.py
All checks passed!
```

## Deferred

None. All 4 findings fixed in test files only; no src/ changes required.
