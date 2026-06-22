# Fix Report — Batch 03

**Files touched:** none (all findings pre-fixed)
**Pytest:** `pytest tests/core/test_experiment.py tests/core/test_f27_experiment_photos.py -q --no-header`
**Ruff:** `ruff check tests/core/test_experiment.py tests/core/test_f27_experiment_photos.py`

---

## Per-finding table

| # | Severity | Test | Status | Evidence |
|---|----------|------|--------|----------|
| 1 | HIGH | `test_experiment.py::test_experiment_wal_verification` | **FIXED (pre-existing)** | Test patches `sqlite3.connect` to return a fake connection whose `PRAGMA journal_mode=WAL` yields `"delete"`, then calls `em._get_connection()` and asserts `RuntimeError(match="WAL")`. Full runtime path exercised. |
| 2 | MED | `test_experiment.py::test_experiment_sidecars_use_atomic_write` | **FIXED (pre-existing)** | Test patches `cryodaq.core.atomic_write.atomic_write_text` with a capturing side_effect, calls `em.attach_composition_photo(...)` with a real JPEG, and asserts that at least one `.json` sidecar path was written through the helper. Real production path exercised. |
| 3 | MED | `test_f27_experiment_photos.py::test_html_escape_in_caption_prevents_injection` | **FIXED (pre-existing)** | Test instantiates `CompositionPhotoHandler` with a mocked bot (capturing `send_message_with_keyboard`), calls `handler.handle_photo(msg)` with malicious `<script>` and `<evil>` tags in username/caption/title, asserts raw tags absent and `&lt;script&gt;` present in confirm text. Full runtime path through `handle_photo`. |
| 4 | LOW | `test_f27_experiment_photos.py::test_widgets_set_photos_then_empty_then_photos_restores_max_height` | **FIXED (pre-existing)** | Test instantiates `QApplication` + `CompositionPhotosWidget`, calls `set_photos([fake_photo])` → `set_photos([])` → `set_photos([fake_photo])`, asserts `maximumHeight() == 16777215` after each non-empty state and `== 80` after empty. Qt widget transition fully exercised. |
| 5 | LOW | `test_experiment.py::test_no_english_debug_switch_string_remains_in_src` | **FIXED (pre-existing)** | Test calls `manager.start_experiment(...)` then `manager.set_app_mode("debug")`, catches `RuntimeError`, asserts no English strings (`"Cannot switch to debug"`, `"debug mode"`) and Russian strings present (`"режим отладки"` or `"карточка эксперимента"`). Runtime path, not source grep. |

---

## Pytest output

```
1 failed, 42 passed in 35.21s
```

The 1 failure (`test_finalize_builds_archive_snapshot_with_tables_plots_and_run_artifacts`) is **pre-existing and unrelated** to batch-03: it fails because SQLite 3.50.4 is on the `_check_sqlite_version()` blocklist (WAL-reset corruption bug range 3.7.0–3.51.2). No batch-03 test is in the failure set.

## Ruff output

```
All checks passed!
```

## Files changed

None. All 5 findings were already corrected in the test files prior to this sweep run. No source (src/) files were touched.
