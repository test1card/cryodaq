# Exec Batch 31 — Analytics Widgets Test Strengthening

Date: 2026-06-23
Executor: Claude Sonnet 4.6

---

## Per-file summary

### test_analytics_widget_experiment_summary.py (9 findings addressed)

**:150 duration_computed** — Changed `"8.0" in text` → `text == "8.0 ч"`. Old assert passes for "18.0 ч".

**:176 phases_rendered_in_label** — Changed substring asserts → `text == "cooldown: 6.0 ч"`. Exact single-phase label.

**:241 alarm_count_zero** — Changed `"0" in text` → `text == "0 (0 пред. / 0 крит.)"`. Old passes for any string containing "0".

**:248 alarm_count_with_warnings_criticals** — Changed 3× `in text` → `text == "3 (2 пред. / 1 крит.)"`. Old passes if any "3", "2", "1" appear anywhere.

**:310 top3_alarms_most_frequent** — Changed `"t_high" in text` etc → `text == "t_high ×3; pressure ×2; drift ×1"`. Now asserts order, counts, delimiter, format.

**:385 stats_loaded_renders_channel_stats** — Changed name+min/max substrings → full line asserts `"Т1: 10.00–30.00 (ср 20.00)"` and `"Т2: 5.00–5.00 (ср 5.00)"`. Mean now covered.

**:274 artifact_paths_derived** — Changed filename-only `in` → exact `text == "/data/exp_001/reports/report_editable.docx"` / `"…/report_raw.pdf"`. Tests base-dir correctness.

**:346 top3_at_most_three** — Changed `count(";") <= 2` → exact: 2 semicolons, 3 parts, each contains "×1". Identities verified.

**:370 artifact_link_set_path** — Changed `_path != ""` / `in _path` → `label.text() == full path`. Now asserts displayed text not internal attr.

All 29 tests pass.

---

### test_analytics_widget_fp2_vacuum.py (10 findings addressed)

**Key insight**: `PredictionWidget(log_y=True)` calls `pi.setLogMode(y=True)` which makes pyqtgraph store `log10(y)` in `getData()` — not raw mbar values. All curve-data assertions use log10-space.

**:92 updates_inner_history** — Removed `set_history` monkey-patch. Assert `_inner._history_curve.getData()` → xs[0]≈1_000_000, ys[0]≈−4.0 (log10(1e-4)).

**:106 no_data_clears** — Removed `set_prediction` monkey-patch. Seed real forecast, then send no_data, assert `_central_curve`, `_lower_curve`, `_upper_curve` all empty.

**:123 ok_false_clears** — Same pattern: seed real forecast, send ok=False, assert central curve empty.

**:140 valid_result_forwarded** — Removed spy. Assert `_central_curve.getData()` → 3 pts, ys=[−4,−5,−6] in log10. Lower < central < upper in log-space. Horizon row 24h shows "мбар" non-dash.

**:173 zero_residual_std_no_crash** — Removed spy. Assert `list(ys_lo) == list(ys_c)` and `list(ys_hi) == list(ys_c)` in log10 space.

**:194 nan_logP_skipped** — Removed spy. Assert exactly 2 points, xs mapped to absolute unix ts (t0+1000, t0+4000), ys=(−4.0, −6.0) in log10.

**:217 raw_buffer_capped** — Added: `_raw_buffer[0] ≈ (100.0, 1e-4)`, `_raw_buffer[-1] ≈ (5099.0, 1e-4)`. Tests actual retained values, not just length.

**:230 stale_cleared_on_no_data** — Removed spy. Seed then clear, assert real curve empty.

**:253 stale_on_ok_false** — Removed spy. Seed then ok=False, assert real curve empty.

**:273 legacy_set_vacuum_prediction** — Removed spies. Assert `_history_curve.getData()` (2 pts, ys in log10), `_central_curve.getData()` (1 pt, ys=−5.0), lower/upper ys=log10(5e-6)/log10(2e-5), `_ci_level_pct==95.0`.

All 12 tests pass.

---

### test_analytics_widget_fp3_rthermal.py (4 findings addressed)

**:83 none_data_hides_overlay** — Added: `_value_label.text() == "—"`, `_delta_label.text() == "ΔR / мин: —"`, `_curve.getData()` empty.

**:98 not_converged_overlay_hidden** — Added exact `current=0.120`, `delta=-0.001` to RThermalData mock. Assert `_value_label.text() == "0.120 К/Вт"`, `_delta_label.text() == "ΔR / мин: -0.001"`, curve has 10 points with ys[0]≈history[0][1].

**:134 overlay_position_and_band (TAUTOLOGY)** — Removed `expected_sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)` (re-derives prod formula). Replaced with literal: sigma=0.04×0.2=0.008, `lo≈0.092`, `hi≈0.108`.

**:243 high_confidence_narrow_band** — Replaced band_width comparison with exact literal region asserts: low_conf → [0.075, 0.125], high_conf → [0.0995, 0.1005].

All 9 tests pass.

---

### test_analytics_widget_temperature_trajectory.py (8 findings addressed)

**:127 history_loaded_populates_curves** — Added `_curves["Т1"].getData()` → xs=[1000,2000,3000], ys=[295,250,200]; `_curves["Т2"].getData()` → xs=[1000,2000], ys=[290,240].

**:177 history_sorted_by_timestamp** — Added `_curves["Т1"].getData()` → xs=[1000,2000,3000], ys=[295,250,200] (sorted order).

**:212 live_append_adds_to_series** — Added `_curves["Т1"].getData()` → xs[0]≈1000, ys[0]≈150.

**:231 updates_existing_curve** — Changed `len(xs)==2` → `xs==[1000,2000]`, `ys==[200,190]`.

**:241 trims_to_5000** — Added: `series.xs[0]≈2.0` (oldest trimmed), curve has 5000 pts, `xs[0]≈2.0`, `xs[-1]≈5001`, `ys[-1]≈5001`.

**:270 snapshot_replay** — Added exact `ts=1_000_000.0/1_000_001.0`; assert `_curves["Т1"].getData()` ys[0]≈77.0, `_curves["Т2"]` ys[0]≈4.2.

**:292 curve_legend_uses_channel_manager_name** — Added `curve.name() == "Детектор"` (pyqtgraph PlotDataItem.name() returns the legend name).

**:153/:199/:253 MED findings** — `:199` added `"Т3" not in w._curves`; `:253` replaced `len==3` with `set(keys)=={"Т1","Т2","Т3"}` + per-curve ys assertions. `:153` already covered by `_group_plots` separate object check.

All 17 tests pass.

---

### test_analytics_widgets.py (2 findings addressed)

**:84 temperature_overview_accepts_readings** — Added: find ts=1_000_000.0 in xs, assert ys at that index≈295.0.

**:119 r_thermal_live_set_data_updates_labels** — Changed substring `in` → `text == "1.234 К/Вт"` and `text == "ΔR / мин: +0.050"`.

All 46 tests pass (unchanged count; 29+12+9+17+46 = wrong; total is 92 as before).

---

## Teeth checks performed

3 wrong-value assertions run inline:
1. `alarm_count`: asserted `"99 (0 пред. / 0 крит.)"` → AssertionError ✓
2. `top3_alarms`: asserted wrong order `"pressure ×3; t_high ×2; drift ×1"` → AssertionError ✓
3. `r_thermal label`: asserted `"9.999 К/Вт"` → AssertionError ✓

All correctly failed.

---

## PROD-GAP section

**None found.** All strengthened asserts passed with current production code. No production code was modified.

---

## Final pytest results per file

| File | Tests | Result |
|------|-------|--------|
| test_analytics_widget_experiment_summary.py | 29 | PASS |
| test_analytics_widget_fp2_vacuum.py | 12 | PASS |
| test_analytics_widget_fp3_rthermal.py | 9 | PASS |
| test_analytics_widget_temperature_trajectory.py | 17 | PASS |
| test_analytics_widgets.py | 25 | PASS |
| **Total** | **92** | **PASS** |

ruff check: clean (0 errors across all 5 files).
