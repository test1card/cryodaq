# Verify (amend cycle) — Batch 17 — analytics vacuum-trend/cooldown-service/phase/steady

Codex gpt-5.5 high, READ-ONLY. 8 findings, all test-only. Codex confirmed CLEAN: fit_exponential,
all_log_scale, buffer_sliding_window, the honestly-renamed update_interval_config_stored +
serialization-contract tests (prod uses {ok, **asdict(pred)}), and test_full_phase_sequence (the
single-chronological-stream exact-order fix held).

## FIXED (test-only)
- **F1 `test_vacuum_trend.py:68/86` fit_power_law / F2 :104 fit_combined** — incomplete fit-param
  asserts (only log_p_ult / first-three). Strengthened with rigor: log_p_ult (F1) and log_p_ult+A+tau
  (F2) asserted within ±10%; B & alpha are JOINTLY UNIDENTIFIABLE (concrete counter-example given), so
  instead of brittle raw-param asserts the test verifies the fitted power-law TERM B_fit·t^(−alpha_fit)
  reproduces ground truth at two timepoints within 0.1 (F1) / 0.15 (F2) log-decades — proves curve
  shape without spurious param-recovery failures. (more correct than the naive "assert B≈3" suggestion.)
- **F3 `test_vacuum_trend.py:146` eta_exponential / F4 :168 eta_power_law** — were eta>0-only. Now set
  a target AHEAD of the last data point and cross-check the production binary-search ETA against the
  CLOSED-FORM analytical root of the FITTED model (exp: tau·ln(...)−t0 ≈ 29.888s; power: (B_fit/(log_target
  −lpu_fit))^(1/alpha_fit)−t_current), asserting agreement (abs < 1s / < 15s, the latter justified by the
  flat curve near t_star). Independent of the binary search → proves the root-finder is correct, not circular.
- **F5 `test_cooldown_service.py:350` metadata_contains_trajectory** — trajectory asserts were skipped
  when progress≥0.98. Now asserts `progress < 0.98` (early-cooldown scenario) then requires trajectory
  fields UNCONDITIONALLY (list, equal lengths, finite, monotonic future_t).
- **F6 `test_cooldown_service.py:201` cooldown_detection_start** — fixed sleeps for the bg consumer →
  bounded deadline-poll on observable state.
- **F7 `test_cooldown_service.py:425` does_not_predict_without_model** — sleep+queue.empty() could pass if
  the loop never ran. Now drives `await service._do_predict()` deterministically with _model=None and
  asserts no result (one iteration provably ran). Teeth: giving it a model → would predict → FAIL.
- **F8 `test_steady_state_quasi_steady.py:74` fast_drift_NOT_quasi_steady** — added `pred.tau_s > 0` +
  `abs(pred.amplitude) > 1e-6` so a degenerate valid fallback can't pass.

Independently re-verified: 47 pass (4 files, -m "not ollama") + ruff-clean; cooldown_service 3× no-flake.
No DEFERRALS.
