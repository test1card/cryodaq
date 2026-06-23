# Batch 32 — tier 2 — insight/steady-state/time-window/palette/theme/fonts (99 tests, 14 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 7 HIGH / 8 MED / 8 LOW. 6 files clean.
FIND pass only. NOTE: test_design_system_rules.py is a LEGITIMATE design-governance AST/source scan
(enforces no-hardcoded-hex/px RULEs) — CLEAN, not a behavioral source-grep.

## HIGH (7)
- test_fonts.py:19 `launcher_loads_fonts` / :36 `gui_app_loads_fonts` — SOURCE-GREP: `inspect.getsource()`
  substring can pass on a comment/dead branch; never proves startup loads fonts (launcher.py:1495 /
  app.py:226). Fix: monkeypatch `_load_bundled_fonts`, stub startup, invoke main(), assert call.
- test_launcher_theme_switch.py:39/50/61/82 (shuts_down_bridge/stops_engine/releases_lock/order_bridge_then_
  engine) — MOCK-BYPASS: mocked `os.execv` RETURNS, so teardown "before execv" is observed even though real
  execv never returns; ordering unproven. Fix: ordered call-log + `mock_execv.side_effect = SystemExit`,
  assert full sequence (bridge shutdown → engine stop → `_wait_engine_stopped` → lock release → execv).
- test_temperature_steady_state_widget.py:156 `predictor_only_fed_on_new_timestamps` — VALUE-BLIND: checks
  `_last_ts` cursor only; duplicate timestamps could double-call `add_point` while `_last_ts` unchanged. Fix:
  spy `_predictors["T12"].add_point`, assert call count/args.

## MED (8)
- test_assistant_insight_panel.py:70 `push_insight_renders_one_card` — counts `_InsightCard` but not the
  rendered message/trigger/timestamp (assistant_insight_panel.py:92-110). Fix: assert card label texts.
- test_assistant_insight_panel.py:86 `uses_provided_timestamp` — only `_entries[0].timestamp`; card could
  ignore it. Fix: assert rendered timestamp label.
- test_assistant_insight_panel.py:103 `keeps_last_10_insights` — private deque cap/order, not visible card
  list/count (239-243). Fix: assert rendered cards = newest 10 in order + `_count_label` "10/10".
- test_cooldown_prediction_widget_steady_state.py:111 `active_prediction_renders_trajectory` — VALUE-BLIND:
  name claims trajectory but only checks placeholder/overlay visibility; never verifies set_prediction args
  (analytics_widgets.py:904-912). Fix: spy set_prediction / inspect inner central/lower/upper data.
- test_temperature_steady_state_widget.py:72/80 `routes_t12/t11_reading_to_predictor` — private `_buffers`;
  rendered curve/hero/predictor feed (1900-1943) could be broken. Fix: assert curve data / spy add_point + hero.
- test_temperature_steady_state_widget.py:88 `short_id_split_handles_full_channel_names` — buffer key only;
  visible T12 row/curve could be unchanged. Fix: assert full-name reading updates T12 curve/hero.
- test_app_palette.py:28 `apply_fusion_dark_palette_sets_fusion_style` — THEME/PALETTE-WEAK: asserts
  `_cryodaq_fusion_applied` flag set by the same helper; deleting `app.setStyle("Fusion")` (app.py:137) would
  still pass. Fix: spy `app.setStyle` or verify active style.

## LOW (8)
- test_assistant_insight_panel.py:116 layout_count_matches_entries — card count can match while text wrong.
  Fix: assert visible card texts == pushed messages.
- test_cooldown_prediction_widget_steady_state.py:235 invalid_predictor_shows_placeholder — GUARDED-PASS:
  stale `_asym_band`/`_steady_badge` could remain (954-958). Fix: also assert band+badge hidden.
- test_temperature_overview_noops.py:32/38/43/49 (pressure/keithley/experiment_status/cold_temperature
  setters are no-op) — VALUE-BLIND: no postcondition; a mutating impl would pass. Fix: snapshot
  `_series`/`_curves`/warnings before+after, assert unchanged.
- test_time_window_selector.py (gui/state):33 default_four_buttons / :43 show_6h_adds_button — private
  `_buttons.keys()` not rendered buttons. Fix: `findChildren(QPushButton)`, assert labels/"6ч"/checked.

Clean: test_time_window_selector.py (views), test_time_window_controller.py, test_common_widgets.py,
test_design_system_rules.py (legitimate governance AST scan), test_experiment_dialogs.py,
test_experiment_status_widget.py.
