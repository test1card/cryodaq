# Batch 17 — tier 1 — analytics (cooldown/phase/steady/vacuum) + config + design (98 tests, 14 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 9 MED / 4 LOW. 10 files clean.
All config-YAML tests clean (legit value loading).

## HIGH
- test_cooldown_service.py:425 `..._does_not_predict_without_model` — only publishes T_cold;
  prod also requires T_warm, so passes even if a model existed. Fix: publish both, assert
  no prediction over intervals.
- test_vacuum_trend.py:104 `test_fit_combined_synthetic` — asserts only not insufficient;
  wrong model selection passes. Fix: assert model_type=="combined" + params.
- test_vacuum_trend.py:443 `test_update_interval_respected` — predictor doesn't enforce
  interval (engine loop does); test checks only config storage. Fix: engine tick test w/
  fake clock, or rename.

## MED
- test_cooldown_service.py:350 `..._metadata_contains_trajectory` — key presence only. Fix:
  assert list type, equal lengths, finite, monotonic future_t.
- test_phase_detector.py:184 `test_full_phase_sequence` — clears buffers between phases,
  asserts membership not order. Fix: one chronological stream, assert exact sequence.
- test_steady_state_quasi_steady.py:74 `..._fast_drift_NOT_quasi_steady` — invalid fallback
  also passes. Fix: assert pred.valid + nonzero tau/amplitude.
- test_vacuum_trend.py:68/86 fit_{exponential,power_law}_synthetic — assert any model + high
  confidence, not model_type/params. Fix: assert model_type + fit_params within tol.
- test_vacuum_trend.py:146/168 eta_computation_{exp,power} — eta>=0 only; "already reached"
  zero passes. Fix: target ahead, assert closed-form ETA + model.
- test_vacuum_trend.py:323 `test_all_log_scale` — confidence doesn't distinguish log-space.
  Fix: assert log-space params / independent log trajectory.
- test_vacuum_trend.py:487 `..._engine_feed_and_command_response` — hand-builds
  {ok,**asdict(p)} not engine handler. Fix: exercise real command handler or rename.

## LOW
- test_cooldown_service.py:201/250 — fixed sleeps for background consumer. Fix: poll deadline.
- test_steady_state_quasi_steady.py:93 — only proves gate didn't fire. Fix: assert fit fields
  or narrow claim.
- test_vacuum_trend.py:308 `test_buffer_sliding_window` — length-only; over-drop passes. Fix:
  assert retained timestamps within cutoff + values.

Clean: cooldown_schema, cooldown_service_expected_value, leak_rate, plugins, thermal,
all 4 config tests, design_system/test_no_internal_versioning_ast.
