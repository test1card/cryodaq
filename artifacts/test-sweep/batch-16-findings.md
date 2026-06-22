# Batch 16 — tier 1 — rag-audit / engine-cmds / analytics calib+cooldown (96 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 6 MED / 3 LOW. 4 files clean.

## HIGH
- test_v0_55_14_audit_fixes.py:146 `..._handles_string_phases_field` — `if chunks:` lets
  it pass if loader silently drops the doc. Fix: assert chunks, text contains "valid".
- test_calibration.py:265 `test_calibration_index_uses_atomic_write` — regex source grep;
  doesn't execute writes. Fix: monkeypatch atomic_write_text, run save_curve/_write_index/
  .cof export, assert calls on expected paths.
- test_calibration_fitter.py:151 `test_downsample_preserves_curvature` — `low>=high*0.5`
  near-tautological (mid is downsampled median); uniform sampling passes. Fix: sharp-bend
  fixture, assert density near bend > flat region.

## MED
- test_v0_55_14_audit_fixes.py:74/93 — swap-replaces/cleanup assert row COUNT only; stale
  rows pass. Fix: assert chunk_ids, absence of chunk_99.
- test_v0_55_14_audit_fixes.py:255 `..._offloads_loaders_via_to_thread` — only exercises
  one loader, no event-loop responsiveness. Fix: enable each source, assert each path via
  to_thread + heartbeat around slow fake loader.
- test_calibration_fitter.py:74 `test_extract_pairs_basic` — count + positivity only. Fix:
  assert first/mid/last pairs == inserted SRDG + _synthetic_dt670(srdg).
- test_calibration_fitter.py:119 `test_time_alignment_filter` — one pair remains, could be
  wrong one. Fix: assert pairs[0]==approx((82.5,77.0)).
- test_cooldown_predictor.py:535 `..._legacy_model_without_floor_fields` — floors>0 only;
  fallback constants pass. Fix: compute expected floors from fixture minima, assert ==.

## LOW
- test_calibration_fitter.py:234 `test_coverage_empty_regions` — some bin empty; edge bugs
  pass. Fix: assert MIDDLE bins empty + endpoint counts.
- test_cooldown_predictor.py:457 `..._sets_floors` — re-derives prod min-margin+clamp. Fix:
  tiny curves w/ literal minima, assert literal floors + !=fallback.
- test_cooldown_predictor.py:352 `test_no_matplotlib_at_import` — no fresh import; skips if
  matplotlib already loaded. Fix: subprocess import-isolated check.

Clean: test_engine_multiline_burst_command, test_engine_rag_rebuild_command,
test_engine_rag_search_command, test_cooldown.
