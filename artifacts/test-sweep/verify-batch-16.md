# Verify (amend cycle) — Batch 16 — rag-audit / analytics calibration+cooldown

Codex gpt-5.5 high, READ-ONLY. 4 findings, all test-only. Codex confirmed CLEAN (fix-pass holds):
string-phases loader, swap-replace/cleanup, extract_pairs_basic, time_alignment_filter,
downsample_preserves_curvature (the V-kink fixture), build_model_from_curves_sets_floors, the
subprocess matplotlib import-isolation test.

## FIXED (test-only)
- **F1 `test_cooldown_predictor.py:535` load_legacy_model_without_floor_fields** — same-oracle
  TAUTOLOGY: imported prod `_derive_floors` to compute the EXPECTED floors while load_model rebuilds
  via the same `_derive_floors`. Now removes that import; uses literal fixture minima
  (5.238.../84.814...) and applies the formula with explicit literal arithmetic
  `max(1.0, min-0.5)` / `max(50.0, min-2.0)` → 4.738.../82.814..., asserts loaded floors == those +
  != fallback constants. Teeth: +1 literal → FAIL. (the dedicated test_derive_floors_from_curves
  legitimately still tests _derive_floors directly.)
- **F2 `test_v0_55_14_audit_fixes.py:255` build_index_offloads_loaders_via_to_thread** — overfit:
  heartbeat was incremented INSIDE the to_thread spy (proved only the spy ran). Now genuine
  concurrency: a loader blocks in its worker thread on a threading.Event; build_index() runs as a
  task; an INDEPENDENT heartbeat coroutine ticks every 5ms; asserts ≥3 ticks accumulate WHILE the
  loader is blocked (event loop stayed responsive), then releases + awaits build. 3× stable, no
  deadlock.
- **F3 `test_calibration.py:265` calibration_index_uses_atomic_write** — weak "some .json/.cof"
  paths. Now captures `curve_path = save_curve(...)` and `cof_path = export_curve_cof("CH2")` and
  asserts atomic_write_text was called with the EXACT paths {curve_path, tmp_path/"index.yaml",
  cof_path}.
- **F4 `test_calibration_fitter.py:234` coverage_empty_regions** — count-only gap. Now asserts
  `coverage[0]["point_count"]==20`, `coverage[-1]==20`, and every middle bin `point_count==0` +
  `status=="empty"`. Teeth: asserting middle count 1 → FAIL.

Independently re-verified: 61 pass (4 files, -m "not ollama") + ruff-clean; F2 3× stable. No DEFERRALS.
