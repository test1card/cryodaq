# CryoDAQ Polish Assessment #2 — Analytics (numerical) + LLM query/agent surface

**Scope (read-only architect pass, 2026-06-24):** `analytics/` numerical modules
(calibration, calibration_fitter, cooldown_predictor, cooldown_service, steady_state,
vacuum_trend, plugin_loader, base_plugin) + the LLM query/agent surface
(`agents/assistant/query/**`, intent_classifier, prompts, rag_adapter, router,
ollama_client) + `core/sensor_diagnostics.py`, `core/rate_estimator.py`.

**Method:** read each file end-to-end; reproduced numerical edge cases against numpy 2.4
in the project venv; tested the prompt-injection `.format()` surface empirically;
grepped for the "no numpy/scipy in core/drivers" invariant. Every finding below was
verified at the cited line. Model-suggested findings that did not survive a source read
are in REJECTED.

**Headline:** No CRIT, no HIGH. This slice is well-guarded. The calibration fitter,
the vacuum/steady/cooldown analytics, and the LLM pipeline all reject non-finite inputs,
bound their LLM calls with timeouts, and never raise into the operator path. The genuine
polish surface is a small set of MED/LOW robustness and dead-code items. The prior pass's
SOUND verdict on vacuum_trend / steady_state / cooldown_predictor holds — re-verified.

---

## DO FIRST (ranked)

1. **[MED] Plugin hot-reload `exec`s arbitrary `.py` with no module-name isolation.**
   `plugin_loader.py:144-150` — `spec_from_file_location(f"cryodaq_plugin_{plugin_id}")`
   + `exec_module`. The fabricated module is never inserted into `sys.modules`, and on
   every mtime change the file is re-`exec`'d into a brand-new module object. Two real
   consequences: (a) a plugin that does `import cryodaq_plugin_<id>` or relies on
   pickling/dataclass `__module__` identity will not resolve; (b) repeated reloads leak
   nothing in `sys.modules` but any module-level resource the plugin opened (file handle,
   thread) is never closed because there is no plugin teardown hook. `_unload_plugin`
   (`:206-216`) just pops the dict. Fix: add an optional `plugin.close()`/`shutdown()` call
   in `_unload_plugin`, and document that plugin code is trusted-operator code (it is
   `exec`'d unsandboxed — acceptable for an operator-installed plugins dir, but should be
   stated). Trade-off: a teardown hook is a tiny API addition vs silent resource leak on
   hot-reload churn.

2. **[MED] Plugin hot-reload TOCTOU: file deleted/changed between scan and load.**
   `plugin_loader.py:303-310` — the watch loop reads `current_files` then calls
   `_load_plugin(self._plugins_dir / filename)`. If the file is removed in the 0–5 s gap,
   `exec_module` fails and is caught by the broad `except Exception` at `:203` (logged —
   acceptable). The subtler case: a half-written file (editor save-in-progress) `exec`s
   partially and registers a broken plugin that then runs in `_process_loop`. `process()`
   exceptions are caught (`:258`), so no crash, but the plugin silently produces nothing
   until the next mtime tick. Fix (optional): debounce by requiring mtime stable across
   two scans before load, or a stat-size>0 guard. Low blast radius; MED only because it
   touches the live analytics pipeline.

3. **[LOW] `cooldown_predictor.predict` has a dead bare expression + a fully dead
   cold-rate weighting branch.** `cooldown_predictor.py:503` —
   `float(np.mean(ref_rates_cold)) if len(ref_rates_cold) >= 2 else 0.0` is computed and
   discarded; the intended `rate_cold_mean = ...` assignment was dropped (grep confirms
   `rate_cold_mean` is never defined anywhere). Because `use_rate_cold` is hard-coded
   `False` (`:511`), the entire cold-rate kernel at `:533-536` is unreachable. Net effect:
   no runtime bug (the discarded mean and the dead branch are inert), but a maintainer will
   misread the intent and the line trips no linter. Fix: delete `:503` and the dead
   `use_rate_cold` block, or wire it (architect decision — the comment at `:509-511` says
   cold rate is deliberately disabled, so deletion is the honest move). Verified:
   `observed_rate_cold` None-arithmetic at `:535` is never reached.

4. **[LOW] `vacuum_trend` BIC selection lets a perfectly-fitting overfit model win via
   `-inf`.** `vacuum_trend.py:93-95` returns `float("-inf")` when `sigma_sq <= 0`
   (residuals ≈ 0). `_select_best` (`:331`) does `min(fits, key=bic)`, so an overfit
   5-param combined model that drives residuals to ~0 is always selected over a
   better-generalizing 3-param exponential. Realistic only with ≥200 near-noiseless
   log-pressure points; on real pump-down noise the residual is never exactly 0. Read-only
   GUI analytics, non-safety. Fix: clamp the perfect-fit BIC to a large finite negative
   number OR keep the `+ k*ln(n)` complexity term even at sigma→0 so the higher-param model
   still pays its penalty. Trade-off: a one-line clamp vs accepting the edge is practically
   unreachable.

5. **[LOW] `calibration_fitter.fit` metrics go NaN-quiet when every prediction throws.**
   `calibration_fitter.py:376-385` — the per-point error loop swallows all exceptions
   (`except Exception: pass`), then `rmse = ... if errors else float("nan")`. If the
   just-fitted curve cannot evaluate any downsampled point (degenerate zone), the returned
   `metrics["rmse_k"]`/`max_abs_error_k` are silently `nan` with no log. The fit itself
   already succeeded (CalibrationStore validated finiteness), so this is a reporting-only
   gap, but a silent-NaN metric on a calibration the operator is about to apply deserves a
   WARNING. Fix: log at WARNING when `errors` is empty after the loop.

6. **[LOW] `ollama_client.embed` re-raises `TimeoutError` (asymmetric with `generate`).**
   `ollama_client.py:176-186` wraps `embed` in `asyncio.timeout(self._timeout_s)` but does
   NOT catch `TimeoutError`, so a stalled embedding call raises up into `RAGAdapter.search`,
   which catches it at `:112` (`except Exception`) and returns `None` = "no relevant info".
   The operator path is safe, but the asymmetry with `generate` (which deliberately returns
   `truncated=True` on timeout, `:118-132`) is a latent trap for any future direct caller of
   `embed` that does not wrap in a broad except. Fix: document the asymmetry, or mirror
   `generate`'s timeout handling. Non-blocking.

---

## Theme A — LLM query/agent surface (timeout / cancellation / injection)

The pipeline is solid. Recording what was checked so it is not re-litigated:

- **Format LLM call is bounded.** `agent.py:150-159` wraps `_ollama.generate` in
  `asyncio.wait_for(..., timeout=self._format_timeout_s)`; timeout → `except Exception`
  (`:166`) → response stays `_FALLBACK`. `handle_query` (`:107-113`) never raises.
- **Intent LLM call is bounded** at the `OllamaClient` layer (`ollama_client.py:115`
  `asyncio.timeout`), and `IntentClassifier.classify` catches all
  (`intent_classifier.py:284-286`) → `_UNKNOWN_INTENT`.
- **CancelledError is propagated, not swallowed,** in `rag_adapter.py:110-111`
  (`except asyncio.CancelledError: raise`) before the broad adapter `except`. Correct.
- **Prompt-injection via operator query is NOT exploitable through `.format()`.**
  Every `FORMAT_*_USER.format(query=..., ...)` passes the operator text as a *value*.
  Verified empirically (numpy venv): `str.format` does not recurse into substituted values,
  and a stray `{`, `}`, `{query}`, `{0}`, `temp {bad`, or `%` in the value does not raise
  and is not re-evaluated. An operator cannot inject a format field or break the template.
- **Untrusted LLM JSON is hardened.** `intent_classifier._parse_intent:182-236` strips code
  fences, falls back to brace-slice extraction, validates `category` against
  `_VALID_CATEGORIES`, coerces `target_channels`/`time_window_minutes` defensively, and
  `_normalise_source_kind:151-179` rejects lists/dicts/comma-glued/whitespace/non-canonical
  source kinds → `None` (whole-corpus search) rather than a malformed LanceDB `WHERE`.
- **RAG snippet length is bounded** (`rag_adapter._truncate_snippet:46-57`, 280 chars) and
  `top_k` is capped (default 8) — context growth into the format prompt is bounded.
- **Rate limiting works** (`agent.py:211-221`): per-chat sliding 1 h window, deque trimmed.
  See LOW note below on dict eviction.
- **Prompt-injection via RETRIEVED content** (RAG snippets / archive titles) is the one
  residual exposure: a malicious vault note or experiment title is inserted verbatim into
  `hits_text` / `entries_text` and could instruct the format model. This is inherent to RAG;
  the system prompt's "answer ONLY from data" guard (`prompts.py:126-144`) is the mitigation.
  The output sink is operator-facing Russian Telegram text with no tool-calling, so blast
  radius is "model says something wrong", not action. Acceptable as-is; noted so a future
  tool-calling expansion re-evaluates it.

---

## Theme B — Calibration numerical robustness (verified guarded)

`calibration.py` is defensively coded. Confirmed against numpy 2.4:

- `fit_curve:246-249` rejects non-finite samples and zero-span raw/temperature ranges
  before any fit.
- `_preprocess_samples:976-1007` drops non-finite samples and collapses exact-duplicate
  temperatures (abs_tol 1e-9). **This is what makes `np.gradient(raw_values, temperatures)`
  at `:270` safe** — reproduced that `np.gradient` yields `inf`/`nan` on exactly-equal
  abscissa, then confirmed the aggregation guarantees strictly increasing temps reach
  `:270`. The sensitivity metric stays finite for the normal `fit_curve` path.
- `_fit_zone_cv:1174` `best_zone.rmse_k` is reached only inside
  `best_cv_rmse is None or score < (...)` — when `best_cv_rmse is None` the `or`
  short-circuits and `best_zone` (also None) is never dereferenced. Verified safe.
- `_build_zone:1189-1194` escalates numpy `RankWarning` to an error and converts it to a
  caught `RuntimeError` — ill-conditioned Chebyshev fits are rejected, not silently returned.
  `CalibrationZone.evaluate:113-117` clips to `[raw_min, raw_max]` and raises on inverted
  range.
- `calibration_fitter.generate_breakpoints:233` guards `seg_len ... or 1e-12`
  (Douglas-Peucker zero-length segment); `extract_pairs:94,112` filters non-finite and
  out-of-range SRDG/KRDG. `adaptive_downsample:147` adds `+1e-12` to the curvature
  denominator. All confirmed.

---

## Theme C — Core numerical (sensor_diagnostics, rate_estimator) — SOUND

- `rate_estimator._ols_slope_per_min:117` guards `den == 0 / isnan(den) / isnan(num)` →
  `None` (fail-safe: no rate). Deque `maxlen` (`:34`) is a finite config-derived cap.
- `sensor_diagnostics`: `_mad_sigma:162-168` guards `len < 2`; `_pearson_r:171-182` guards
  `len < 10`, zero-variance, and NaN `r`; `_count_outliers:558` guards `sigma == 0 / not
  finite`; `_compute_health/_compute_fault_flags` gate every branch on `math.isfinite`.
  Deque `maxlen` (`:216`) is config-bounded. numpy use here is the documented CLAUDE.md
  exception.

---

## CLAUDE.md invariant check — "no numpy/scipy in drivers/core"

PASS. `grep` of `core/` and `drivers/` finds no module-level `import scipy` / `from scipy`.
`cooldown_predictor` and the analytics modules import scipy, but they live in `analytics/`,
not `core/`. The single core consumer, `core/cooldown_alarm.py:264,435`, imports the
predictor **lazily inside functions** — no module-level numpy/scipy in core. numpy in
`core/sensor_diagnostics.py` (and stdlib-only `core/rate_estimator.py`) is the
explicitly-sanctioned exception.

---

## Items reviewed and found SOUND (do NOT re-flag)

- `steady_state.py` — `_fit_exponential` bounds `tau ≥ 0.1` and `max(tau,0.01)` in the model
  (`:265`), guards `rate < _MIN_RATE`, catches `ImportError` (no scipy) and curve_fit
  divergence → `valid=False`. Quasi-steady gate linear-detrends before stddev. Sound.
- `vacuum_trend.py` — `push:133` rejects `P <= 0` (log undefined); `_power_law_model:65` /
  `_combined_model:78` clamp `t` to ≥1.0; `_compute_bic:89` guards `n <= k`;
  `_compute_r_squared:101` guards `ss_tot == 0`; all curve_fits catch
  `(RuntimeError, ValueError, TypeError)`. The `-inf` BIC edge is the only nit (DO-FIRST 4).
- `cooldown_predictor.compute_progress:224-225` guards `dT_c > 0` / `dT_w > 0`;
  `_derive_floors:244-245` floors with `max(...)`; `load_curves`/`ingest_curve` validate
  shape, length, T_start, monotonicity. `predict` returns a populated zero-result when no
  estimates. Sound (besides the DO-FIRST 3 dead code).
- `cooldown_service.py` — all loops catch `CancelledError` and return; `_do_predict` runs
  scipy in an executor (no blocking the event loop); `expected_value` guards every
  precondition (model None, phase, channel, horizon). Sound.
- `base_plugin.py` — clean ABC; `DerivedMetric` frozen. Sound.
- `agent.py` `_rate_buckets` — per-chat deque trimmed to 1 h; the dict is never evicted but
  the chat_id keyspace is bounded by real operators (Telegram), each leaving one emptied
  deque. Negligible, not an OOM vector. SOUND.

---

## REJECTED (verified false — do not action)

Per ORCHESTRATION §14.6, checked at the cited line:

- "Operator query enables prompt-injection / format-field injection via
  `FORMAT_*_USER.format(query=...)`" — FALSE. Empirically verified: `str.format` inserts the
  value literally without recursion; stray braces/`%`/`{query}` in the value neither raise
  nor re-evaluate. Query is always a value, never spliced into the template.
- "`calibration.py:270 np.gradient` divides by zero on duplicate temperatures → NaN
  sensitivity poisons the curve" — FALSE for the real path. `np.gradient` does NaN on
  exactly-equal abscissa (reproduced), but `_preprocess_samples` collapses duplicate
  temperatures before `:270`, guaranteeing strictly increasing temps. The metric stays
  finite.
- "`_fit_zone_cv:1174` dereferences `best_zone` while None" — FALSE. The `or` short-circuits
  on `best_cv_rmse is None`, so `best_zone.rmse_k` is never evaluated while `best_zone` is
  None.
- "scipy/numpy imported in core violates CLAUDE.md" — FALSE. `core/cooldown_alarm.py`
  imports the predictor lazily inside functions; no module-level scipy/numpy in `core/` or
  `drivers/` beyond the sanctioned `sensor_diagnostics`.
- "`ollama_client.embed` unbounded — no timeout" — OVERSTATED. It IS wrapped in
  `asyncio.timeout`; the real (LOW) nit is that it re-raises `TimeoutError` instead of
  returning empty like `generate`, and the only caller already catches it. Captured as
  DO-FIRST 6.
- "`agent._rate_buckets` unbounded → OOM" — OVERSTATED. Bounded by the operator chat_id
  keyspace; each key holds one 1 h-trimmed deque. Negligible.

---

## Note vs prior pass

The prior `POLISH_ASSESSMENT.md` listed vacuum_trend / steady_state / cooldown_predictor as
SOUND read-only analytics and explicitly invited re-verification if touched. Re-verified here
against numpy 2.4: the guards it cited (`:93` sigma, `:78` t_safe, `P<=0`) hold. The only
additions this pass surfaces in those files are the LOW `-inf` BIC edge (vacuum_trend) and the
LOW dead-code in `cooldown_predictor.predict` — neither contradicts the prior SOUND verdict on
the safety-relevant behavior.
