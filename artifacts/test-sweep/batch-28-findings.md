# Batch 28 — tier 2 — operator-log/accent/experiment-overlay/main_window_v2 (100 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 6 HIGH / 12 MED / 16 LOW. 1 file clean.
FIND pass only. Patterns: WIRING-WEAK (main_window_v2 routes engine events but tests assert private
flags/attrs not rendered panel effects), SOURCE-GREP (accent_decoupling regexes source vs rendered
QSS), WIDGET-CONTRACT/ACTION-WEAK (private handlers vs clicks), and many wall-clock-relative
timestamp tests.

## HIGH (6) — main_window_v2 + analytics WIRING-WEAK
- test_main_window_v2.py:47 `tool_rail_click_switches_overlay` — calls `_on_tool_clicked()` directly,
  bypassing ToolRail.tool_clicked. Fix: click the rail button / emit signal, assert
  `OverlayContainer.currentWidget()`.
- test_main_window_v2_alarms_wiring.py:87/98 `tick_sets_alarm_connected_true/false` — WIRING/wall-clock:
  mutate `_last_reading_time`, call private `_tick_status`, assert private `AlarmPanel._connected`. Fix:
  freeze monotonic + assert ACK buttons/timers enabled/disabled (rendered gating).
- test_main_window_v2_alarms_wiring.py:114 `dispatch_reading_routes_to_alarm_panel` — only private
  `_alarm_panel._alarms`; broken `_refresh_table()` render passes. Fix: assert rendered row chip/message/count.
- test_main_window_v2_alarms_wiring.py:154 `v2_count_signal_forwards_to_top_bar` — VALUE-BLIND: comment
  claims TopWatchBar forwarding but asserts only `get_active_v2_count()`. Fix: assert top-bar alarm label/count.
- test_main_window_v2_analytics_adapter.py:328 `mbar_latin_pressure_reading_reaches_analytics` — checks
  only `_analytics_snapshot` key exists, not the Reading value passed on. Fix: assert snapshot args / rendered
  `1.5e-6 mbar`.

## MED (12)
- accent_decoupling.py:58/118/135/148/166 — SOURCE-GREP: regex source for token usage instead of asserting
  the rendered button/badge/progress-chunk/palette QSS. Fix: instantiate the widget, apply theme, assert
  applied QSS uses ACCENT/ON_ACCENT / live `palette().color(Highlight)==SELECTION_BG`.
- accent_decoupling.py:189 `status_ok_still_used_in_status_display_contexts` — VALUE-BLIND: counts files
  containing STATUS_OK. Fix: assert a concrete status widget renders STATUS_OK.
- operator_log_panel.py:225 `chip_selection_mutual_exclusion` — private `_on_chip_selected`/`_active_filter`.
  Fix: click filter buttons, assert checked + rendered timeline.
- operator_log_panel.py:408 `on_reading_triggers_refresh_on_operator_log_entry` — MOCK-BYPASS: monkeypatches
  `refresh_entries`. Fix: stub worker result, assert timeline text updates.
- experiment_overlay.py:106 `overlay_card_save_payload` — calls private `_build_card_payload()` without
  clicking Save / asserting the ZMQ command. Fix: click Save (worker stub), assert command payload.
- experiment_overlay.py:128 `overlay_abort_in_more_menu` — proves only absence of a visible abort button.
  Fix: trigger the More-menu abort action, assert abort command path.
- experiment_overlay.py:509 `current_phase_pill_uses_accent_not_status_ok` — GUARDED-PASS/THEME: negative
  assert skipped when ACCENT==STATUS_OK. Fix: monkeypatch distinct sentinel colors, assert rendered QSS.
- main_window_v2_analytics_adapter.py:182 `unknown_analytics_channel_is_silently_dropped` — VALUE-BLIND:
  only `_last_cooldown`; accidental set_r_thermal/health/pressure mutation passes. Fix: assert all snapshot
  setter states unchanged.

## LOW (16)
- operator_log_panel.py:77/87 (constructs/filter-chips), :237/:249 (last_8h/24h wall-clock+private),
  :262 (all-filter private), :385 (ignores-non-log MOCK-BYPASS), :445 (failure id==99 only), :452
  (load_more private `_limit`). Fix: rendered labels / freeze time + assert rows / assert worker payload.
- main_window_v2.py:35 constructs — private components only. Fix: assert visible title/dashboard/rail/status.
- experiment_overlay.py:227 set_connected_default_true (private), :289 set_connected_idempotent (TAUTOLOGY),
  :390/:403/:414 format_time_{same_day,yesterday,older} — WALL-CLOCK-RELATIVE: Fix: freeze
  `experiment_overlay.datetime.now` and assert exact text. (NOTE: :390 same_day was midnight-bug-fixed in the
  fix-pass via a noon anchor — the stronger fix is to freeze time, which also fixes :403/:414.)
- main_window_v2_analytics_adapter.py:62 cooldown_eta (±1s wall-clock), :355 xaxis_scrolls (wall-clock).
  Fix: monkeypatch time.time / fixed timestamp.

Clean: test_alarm_panel_acknowledged.py (asserts real SeverityChip text/QSS + rendered cell styling).
