# POLISH FIXES #2 — Analytics (robustness/dead-code)

**Date:** 2026-06-24
**Source assessment:** `artifacts/test-sweep/POLISH_ASSESSMENT_2_analytics.md`
**Scope:** all MED/LOW findings. Minimal, pattern-consistent changes. No commit.

**Verification (all touched files):**
- `ruff check --line-length 120 <touched src + test files>` → **All checks passed!**
- `pytest tests/analytics tests/agents -p no:cacheprovider -q -k "plugin or cooldown or vacuum or calibration or ollama or embed"` → **159 passed, 537 deselected**
- Broad: `pytest tests/analytics tests/agents -p no:cacheprovider -q` → **695 passed, 1 deselected** (deselected = `@pytest.mark.ollama` live-server smoke)
- New-tests-only run → **8 passed**

---

## MED — plugin_loader hot-reload teardown leak

**Change:**
- `analytics/base_plugin.py` — added optional no-op `AnalyticsPlugin.teardown()` to the ABC (concrete, default no-op; subclasses override to release module-level resources).
- `analytics/plugin_loader.py` `_unload_plugin` — before logging unload, fetch `getattr(removed, "teardown", None)`, and if callable, call it inside `try/except Exception` (logs an error and continues so a bad teardown never breaks reload). Guard mirrors the existing broad-except isolation style in this module.

**Test (TDD):** `tests/analytics/test_plugins.py`
- `test_teardown_called_on_unload` — plugin with `teardown()` writes a sentinel; asserts it runs on `_unload_plugin`.
- `test_bad_teardown_does_not_break_unload` — `teardown()` raises; plugin still removed, error logged.
- `test_default_teardown_is_noop` — ABC default returns `None`, no raise.

**Result:** PASS.

---

## MED — plugin_loader scan→load TOCTOU (half-written file)

**Change:** `analytics/plugin_loader.py` `_watch_loop` — added an mtime-stability gate. A new/changed file is recorded in a `pending` map on first sighting and only loaded once its mtime is unchanged across two consecutive scans (a partially-written save-in-progress file has a shifting mtime, so it is deferred until stable). `known_files` is now updated incrementally (per-file on load/delete) rather than wholesale-reassigned; `pending` is cleaned up for vanished files. Broad-except isolation in the loop is unchanged. Existing import/parse isolation (broad `except` in `_load_plugin`) already skips files that fail to import.

**Test (TDD):** `tests/analytics/test_plugins.py::test_watch_loop_skips_unstable_file` — drives the real `_watch_loop` with a patched fast interval and a scripted `_scan_plugins` sequence (new mtime → shifted mtime → stable); asserts the file loads exactly once, only after the mtime stabilises.

**Result:** PASS.

---

## LOW — cooldown_predictor dead code

**Change:** `analytics/cooldown_predictor.py` `predict` —
- deleted the bare discarded expression `float(np.mean(ref_rates_cold)) ...` (intended `rate_cold_mean` assignment was dropped; `rate_cold_mean` is never referenced — grep-confirmed).
- removed the now-unused `ref_rates_cold` array, the `rate_cold_std` line, the `use_rate_cold = False` flag, and the unreachable cold-rate kernel branch (`if use_rate_cold and ...`).
- updated the fallback guard `if (use_rate_cold or use_rate_warm) ...` → `if use_rate_warm ...`.
- Kept the public `observed_rate_cold` parameter (callers at predict-call sites still pass it) and the `initial_rate_cold` dataclass field (set during ensemble build). Behavior-neutral: the removed branch was statically unreachable (`use_rate_cold` hard-coded `False`).

**Test:** No new test — the existing `tests/analytics/test_cooldown_predictor.py` exercises `predict` end-to-end (synthetic ensemble, early/near-end, required-fields). Those passing is the regression guard for behavior-neutrality.

**Result:** PASS (existing cooldown tests green).

---

## LOW — vacuum_trend `-inf` BIC overfit edge

**Change:** `analytics/vacuum_trend.py` `_compute_bic` — when `sigma_sq <= 0` (perfect fit, residuals ≈ 0), return a large finite floor `-1e9 + k*math.log(n)` instead of `float("-inf")`. The retained `+k*ln(n)` complexity term ensures a higher-param overfit model pays a strictly larger BIC, so `min(BIC)` no longer auto-selects the most complex model on a residual≈0 tie.

**Test (TDD):** `tests/analytics/test_vacuum_trend.py::test_bic_perfect_fit_is_finite_and_penalises_complexity` — `_compute_bic(200, 3, zeros)` and `(200, 5, zeros)` are both finite and `bic_5 > bic_3`.

**Result:** PASS.

---

## LOW — calibration_fitter silent-NaN metrics

**Change:** `analytics/calibration_fitter.py` `fit` — when the per-point error loop yields no successes (`not errors`), log a `logger.warning(...)` naming the sensor and stating that `rmse_k`/`max_abs_error_k` will be NaN. Returned values unchanged (still NaN); only surfaced, per the finding.

**Test (TDD):** `tests/analytics/test_calibration_fitter.py::test_fit_logs_warning_when_all_metric_points_fail` — monkeypatches `store.evaluate` to always raise; asserts the fit still succeeds (curve built), metrics are NaN, and a WARNING is logged.

**Result:** PASS.

---

## LOW — ollama_client.embed timeout asymmetry

**Change:** `agents/assistant/shared/ollama_client.py` `embed` — added `except TimeoutError` (mirroring `generate`): logs a WARNING and returns `[]` instead of re-raising. A stalled embedding now degrades to "no embedding" rather than propagating `TimeoutError` to callers. Added `t0 = time.monotonic()` for the latency log line, matching `generate`'s pattern.

**Test (TDD):** `tests/agents/assistant/test_ollama_client.py`
- `test_embed_returns_empty_on_timeout` — patches `asyncio.timeout` to raise `TimeoutError`; asserts `embed(...) == []` (no raise). Mirrors the existing `test_generate_returns_truncated_on_timeout`.
- `test_embed_returns_vector_on_success` — happy path returns the first batched vector.

**Result:** PASS.

---

## Notes
- The two REJECTED findings from the assessment (`np.gradient` duplicate-temp, `_fit_zone_cv` None-deref) and the format-injection/SOUND items were not touched.
- No debug code, no scope creep. `observed_rate_cold` kept as a public-API parameter despite being internally unused post-cleanup (callers pass it positionally/by-keyword).
