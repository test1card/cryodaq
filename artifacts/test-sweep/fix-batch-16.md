# Fix Report: Batch 16

## Per-Finding Table

| # | Severity | File | Test | Status | Fix Applied |
|---|----------|------|------|--------|-------------|
| 1 | HIGH | test_v0_55_14_audit_fixes.py:146 | `test_load_experiment_metadata_handles_string_phases_field` | FIXED | Changed `if chunks: assert "valid"` → unconditional `assert chunks` + `assert "valid" in text` |
| 2 | HIGH | test_calibration.py:265 | `test_calibration_index_uses_atomic_write` | FIXED | Replaced source-grep with `monkeypatch.setattr` on `atomic_write_text`, runs `save_curve` + `export_curve_cof`, asserts calls on `.json`/index/`.cof` paths |
| 3 | HIGH | test_calibration_fitter.py:151 | `test_downsample_preserves_curvature` | FIXED | Replaced near-tautological `data_dir` fixture with synthetic V-kink fixture (600 pts, sharp kink at srdg=50); asserts per-unit density in kink zone > flat tails |
| 4 | MED | test_v0_55_14_audit_fixes.py:74 | `test_swap_replaces_existing_canonical_table` | FIXED | Added `ids = set(table.to_arrow().column("chunk_id").to_pylist())` + asserts `"chunk_99" not in ids` and `ids == {"chunk_0","chunk_1","chunk_2"}` |
| 5 | MED | test_v0_55_14_audit_fixes.py:93 | `test_swap_cleans_up_orphaned_staging` | FIXED | Same pyarrow approach; asserts `"chunk_99" not in ids` and `ids == {"chunk_0"}` |
| 6 | MED | test_v0_55_14_audit_fixes.py:255 | `test_build_index_offloads_loaders_via_to_thread` | FIXED | Enabled `vault_dir` + `sqlite_path` sources; spy asserts all three loaders (`load_experiment_metadata`, `load_vault_notes`, `load_operator_log_entries`) appear in `seen`; heartbeat counter verifies event-loop yielding |
| 7 | MED | test_calibration_fitter.py:74 | `test_extract_pairs_basic` | FIXED | Added exact first/mid/last pair assertions using known SRDG values (5.0, 54.5, 104.5) and `_synthetic_dt670()` literal expected krdg values |
| 8 | MED | test_calibration_fitter.py:119 | `test_time_alignment_filter` | FIXED | Added `assert pairs[0] == pytest.approx((82.5, 77.0), abs=0.01)` — verifies the correct pair (not just count) survived |
| 9 | MED | test_cooldown_predictor.py:535 | `test_load_legacy_model_without_floor_fields` | FIXED | Replaced `> 0.0` floor checks with `_derive_floors(raw_for_expected)` computed from fixture data; asserts exact match + `!= FALLBACK` constants |
| 10 | LOW | test_calibration_fitter.py:234 | `test_coverage_empty_regions` | FIXED | Added: middle bins [1..8] must contain "empty", endpoint bins [0] and [-1] non-empty, total point count preserved |
| 11 | LOW | test_cooldown_predictor.py:457 | `test_build_model_from_curves_sets_floors` | FIXED | Replaced `synthetic_curves` fixture (re-derives formula) with self-contained tiny curves at known literal minima (T_cold=3.2K → floor=2.7, T_warm=68.0K → floor=66.0); asserts literal values + `!= FALLBACK` |
| 12 | LOW | test_cooldown_predictor.py:352 | `test_no_matplotlib_at_import` | FIXED | Replaced in-process `sys.modules` check (skips when mpl pre-loaded) with `subprocess.run` isolated check — always runs in fresh interpreter, no skip needed |

## Exact pytest line

```
pytest tests/agents/rag/test_v0_55_14_audit_fixes.py tests/analytics/test_calibration.py tests/analytics/test_calibration_fitter.py tests/analytics/test_cooldown_predictor.py -q --no-header
```

## Ruff

```
ruff check tests/agents/rag/test_v0_55_14_audit_fixes.py tests/analytics/test_calibration.py tests/analytics/test_calibration_fitter.py tests/analytics/test_cooldown_predictor.py
```
All checks passed.

## Files Changed

- `tests/agents/rag/test_v0_55_14_audit_fixes.py`
- `tests/analytics/test_calibration.py`
- `tests/analytics/test_calibration_fitter.py`
- `tests/analytics/test_cooldown_predictor.py`

No `src/` files modified.
