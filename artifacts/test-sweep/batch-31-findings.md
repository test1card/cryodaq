# Batch 31 — tier 2 — analytics widgets (experiment-summary/vacuum/R-thermal/trajectory) (92 tests, 5 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 22 HIGH / 9 MED / 1 LOW. 0 files clean.
FIND pass only. No source-greps/guarded-passes/sleeps. Patterns: NUMERIC-DISPLAY-WEAK (assert a
value was forwarded/stored, not that the rendered label/curve shows the correct computed value+unit),
WIDGET-CONTRACT-WEAK (private `_series`/`_data` vs `getData()`), MOCK-BYPASS (vacuum tests spy on
`set_history`/`set_prediction` so real plot/readout rendering never runs), 1 TAUTOLOGY.

## test_analytics_widget_experiment_summary.py (9)
- HIGH :150 duration_computed — `"8.0" in text` ("18.0 ч" passes). Fix: exact "8.0 ч".
- HIGH :176 phases_rendered_in_label — substring; extra/"16.0 ч" pass. Fix: exact phase label.
- HIGH :241 alarm_count_zero — `"0" in text`. Fix: exact "0 (0 пред. / 0 крит.)".
- HIGH :248 alarm_count_with_warnings_criticals — digits anywhere, not slots. Fix: exact string.
- HIGH :310 top3_alarms_most_frequent — name presence, not order/counts (1703-1705). Fix:
  "t_high ×3; pressure ×2; drift ×1".
- HIGH :385 stats_loaded_renders_channel_stats — name+min/max substrings, miss mean/order (1661-1673).
  Fix: full lines incl "ср 20.00".
- MED :274 artifact_paths_derived — filename-only, miss wrong base dir. Fix: full "/data/exp_001/reports/…".
- MED :346 top3_at_most_three — delimiter count; wrong identities pass. Fix: assert the 3 names+counts.
- LOW :370 artifact_link_set_path — `_path` not displayed text. Fix: label text == full DOCX path.

## test_analytics_widget_fp2_vacuum.py (10) — many MOCK-BYPASS (spy on set_history/set_prediction)
- HIGH :92 updates_inner_history — replaces `PredictionWidget.set_history`; real history curve
  (prediction_widget.py:309-318) can be broken. Fix: assert `_history_curve.getData()` exact (x,y).
- HIGH :106 no_data_clears / :123 ok_false_clears / :230 stale_cleared_on_no_data / :253 stale_on_ok_false
  — spy bypasses real plot/readout clearing (320-346). Fix: seed forecast, clear, assert curves+readout cleared.
- HIGH :140 valid_result_forwarded — forwarded values checked, rendered curve/readout "мбар" not. Fix:
  assert `_central_curve.getData()` + horizon row text.
- HIGH :173 zero_residual_std_no_crash — forwarded lists equal, not plotted CI collapse. Fix: assert
  lower/upper curve data == central.
- HIGH :273 legacy_set_vacuum_prediction — call counts only. Fix: assert inner curve data + CI percent.
- MED :194 nan_logP_skipped — point count; wrong finite ts/values pass. Fix: assert exact 2 points.
- MED :217 raw_buffer_capped — length-only cap. Fix: assert first/last retained ts+values.

## test_analytics_widget_fp3_rthermal.py (4)
- HIGH :98 not_converged_overlay_hidden — could fail to display R/delta/history. Fix: assert exact
  "0.120 К/Вт" + delta + curve points.
- HIGH :243 high_confidence_narrow_band — only narrower/wider; wrong numeric width passes. Fix: assert exact
  low/high confidence regions.
- MED :83 none_data_hides_overlay — only overlay visibility, doc says curve cleared. Fix: labels dashes +
  `_curve.getData()` empty.
- MED :134 overlay_position_and_band — TAUTOLOGY: expected sigma re-derives prod formula (1073-1076). Fix:
  literal expected region values for fixed inputs.

## test_analytics_widget_temperature_trajectory.py (8) — WIDGET-CONTRACT (private _series vs curve getData)
- HIGH :127 history_loaded_populates_curves — `_series`+curve existence, not plotted (x,y) (567-587). Fix:
  assert each curve getData() exactly.
- HIGH :177 history_sorted_by_timestamp — private `_series` sort only; rendered curve order may be wrong.
  Fix: assert curve xs sorted + ys mapped.
- HIGH :212 live_append_adds_to_series · :231 updates_existing_curve (`xs==[1000,2000]`,`ys==[200,190]`) ·
  :241 trims_to_5000 (assert retained 2..5001 + curve data) · :270 snapshot_replay (assert plotted y 77.0/4.2)
  · :292 curve_legend_uses_channel_manager_name (assert legend display "Детектор" not raw id) — all
  VALUE-BLIND/WIDGET-CONTRACT. Fix per line as noted.
- MED :153 separate_plotitems (assert curve parent/legend per group) · :199 skips_empty_channel (assert
  "Т3" not in _curves) · :253 multi_channel_single_call (assert exact keys+curve data).

## test_analytics_widgets.py (2)
- HIGH :84 temperature_overview_accepts_readings — curve existence only. Fix: assert `_curves["Т1"].getData()`
  contains ts + 295.0.
- MED :119 r_thermal_live_set_data_updates_labels — substring. Fix: exact "1.234 К/Вт" + "ΔR / мин: +0.050".
