# Batch 34 — tier 2 — tray/vacuum-panel/cleanup/watchdog/plural/prediction/pressure (91 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 2 HIGH / 11 MED / 2 LOW. 3 files clean.
FIND pass only. FINAL batch of the sweep.

## HIGH (2)
- test_zmq_client_data_flow_watchdog.py:396 `launcher_poll_logs_reason_distinction` — SOURCE-GREP:
  `inspect.getsource(_poll_bridge_data)` + string-check "no heartbeat"/"no readings"/"poll_readings";
  launcher could log the wrong reason or never restart on a data stall while the strings persist. Fix:
  drive `_poll_bridge_data()` with fake bridges (heartbeat-stale vs data-flow-stalled), assert shutdown/start
  + caplog reason.
- test_pressure_plot.py:87 `non_positive_values_guarded` — GUARDED-PASS/VALUE-BLIND: assertions only run
  under `if raw_y is not None`; if pyqtgraph stops exposing `opts["y"]` the guard silently skips the contract.
  Fix: assert `raw_y is not None` first, then exact clamped Y / `getData()` has only positive expected values.

## MED (11)
- test_vacuum_trend_panel.py:107 `eta_display_format` — panel path asserts only `len(_eta_labels)==3`; wrong
  displayed ETA text/order passes (direct `_fmt_eta()` cases are exact). Fix: assert exact label texts
  ("1.0e-03: ✓", "1.0e-05: 1ч 0мин", "1.0e-08: —").
- test_vacuum_trend_panel.py:132 `graph_log_scale` — accepts any 5 Y in (-10,5) + any negative target-line
  positions. Fix: assert exact x/y arrays + exact `log10(target)` line positions.
- test_zmq_client_data_flow_watchdog.py:109 `poll_readings_updates_last_reading_time` — FIXED-SLEEP
  (`time.sleep(0.01)` vs mp.Queue) + only `len==1`; malformed Reading fields pass. Fix: injectable/sync fake
  queue + assert exact channel/value/unit/status.
- test_zmq_client_data_flow_watchdog.py:294 `command_channel_stalled_after_recent_timeout` — FIXED-SLEEP +
  private `_last_cmd_timeout`/flag, not launcher restart/log. Fix: deterministic drain + launcher fake-bridge
  coverage with caplog + restart asserts.
- test_prediction_widget.py:51 `set_history_populates_curve` — only `len(xs)==5`; wrong x/y or log-Y coercion
  pass. Fix: assert exact xs/ys from `_history_curve.getData()`.
- test_prediction_widget.py:58 `set_prediction_populates_all_three_curves` — non-empty/equal lengths only;
  swapped bands / wrong values pass. Fix: assert exact central/lower/upper (x,y) + CI bounds.
- test_prediction_widget.py:138 `prediction_readout_shows_all_horizons` — rows non-empty + "67% ДИ"; wrong
  per-horizon values/CI widths pass. Fix: assert exact value + CI text per horizon.
- test_prediction_widget.py:302 `does_not_import_global_window_controller` — SOURCE-GREP: absent-strings check;
  could subscribe indirectly. Fix: change global TimeWindowController, assert widget X-range/readouts unchanged.
- test_pressure_plot.py:62 `subscribes_to_global_window` — after set_window only asserts `plot_item is not
  None`; subscription could be missing. Fix: assert X range changes to the selected 1h window.
- test_pressure_plot.py:71 `forward_looking_skips_subscribe` — SOURCE-GREP + no-crash; doesn't prove forward
  plot ignores window changes. Fix: record X range, change global window, assert unchanged.
- test_pressure_plot.py:241 `dashboard_pressure_uses_shared_component` — SOURCE-GREP: source contains
  "PressurePlot"; wrapper could mis-instantiate. Fix: instantiate PressurePlotWidget, assert `_shared` is a
  PressurePlot, refresh(), assert shared curve gets expected (x,y).

## LOW (2)
- test_prediction_widget.py:41 `widget_constructs_log_y` — private `_log_y is True`, not actual plot log mode.
  Fix: assert left-axis log mode + valid positive pressure values.
- test_prediction_widget.py:124 `log_y_readout_uses_scientific_notation` — only "e"+unit; wrong value passes.
  Fix: assert exact "3.8e-06 мбар".

Clean: test_tray_status.py, test_widget_cleanup_sentinel.py, test_plural.py (legit value tests).
