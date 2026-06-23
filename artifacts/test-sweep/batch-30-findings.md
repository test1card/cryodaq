# Batch 30 — tier 2 — shell chrome (tool-rail/top-bar) + analytics views (95 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 6 HIGH / 13 MED / 1 LOW. 2 files clean.
FIND pass only. WIDGET-CONTRACT-WEAK (private active/cache vs rendered styling/text) + VALUE-BLIND
(count/substring vs exact value/order). Two CLEAN files are good models (assert rendered badge/text).

## HIGH (6)
- test_tool_rail.py:47 `set_active_marks_one_button` — asserts private `_active`, not the rendered
  border-left/active-icon-color from `ToolRailButton._apply_style()`/`_refresh_icon()`. Fix: assert active
  vs inactive stylesheet/icon-color.
- test_top_watch_bar.py:29 `seed_visible_channels_marks_them_ok` — private `_channel_last_seen` not the
  `_channel_label` text/color. Fix: refresh + assert "2/2 норма" / no waiting text.
- test_top_watch_bar.py:51 `on_reading_stores_under_short_id` — private cache passes even if visible
  channel summary shows stale/waiting. Fix: assert rendered summary after full-name reading.
- test_v0_55_15_audit_fixes.py:178 `overlay_container_register_overwrite_releases_displaced_widget` —
  VALUE-BLIND: the regression is `deleteLater()` on the displaced widget, but test checks only
  `_pages["test"] is second`. Fix: spy/override deleteLater or observe `destroyed` after posted events.
- test_v0_55_15_audit_fixes.py:217 `chat_panel_worker_list_does_not_grow_unbounded` — MOCK-BYPASS/TAUTOLOGY:
  builds a MagicMock panel and manually MIRRORS `_on_response()` cleanup (assistant_chat_widget.py:267);
  prod can regress while the copied logic passes. Fix: instantiate AssistantChatPanel, patch worker/sender
  minimally, call `_on_response()`, assert workers/inflight/busy state.
- test_analytics_widget_cooldown_history.py:158 `twenty_cooldowns_all_rendered` — VALUE-BLIND: `len(xs)==20`
  lets all dates/durations/order be wrong. Fix: assert full `ys == [1.0..20.0]` + representative parsed X.

## MED (13)
- test_tool_rail.py:19 constructs — `expected.issubset(_buttons.keys())`; missing/extra/wrong-order rendered
  slots pass (prod now has multiline + knowledge_base). Fix: assert exact visible button keys/order+tooltips.
- test_tool_rail.py:75 mnemonic_shortcuts_defined — shortcut keys exist, not the overlay mapping. Fix:
  assert exact `_MNEMONIC_SHORTCUTS` map or activate each + assert emitted overlay key.
- test_top_watch_bar.py:88/100 experiment/alarms_click_emits_signal — MOCK-BYPASS: emit the label's private
  `clicked` directly, bypassing `_ClickableLabel.mousePressEvent`. Fix: `QTest.mouseClick` on the label.
- test_top_watch_bar.py:112 set_alarm_count_updates_label — substring "0"/"3" miss full text/pluralization/
  color. Fix: assert exact text + stylesheet color for zero/nonzero.
- test_top_watch_bar.py:242 mode_badge_stores_current_mode — private `_app_mode` not rendered badge/click.
  Fix: assert badge text/visibility/style + drive click path.
- test_v0_55_15_audit_fixes.py:76/83 multiline on_reading skips/accepts — private `_states` absence/presence
  not the rendered row/value/channel-count label. Fix: assert table rows + formatted value + count label.
- test_v0_55_6_1_chat_unification.py:17 knowledge_base_in_main_overlay_items — SOURCE-GREP/WIDGET-CONTRACT:
  checks private `_OVERLAY_ITEMS` not the rendered ToolRail button. Fix: instantiate ToolRail, assert button
  presence/tooltip/signal-key/active styling.
- test_analytics_view_phase_aware.py:220 pressure_forwards — only `len(_series)==1`; wrong ts/value/no
  rendered update. Fix: assert stored (ts,value) + PressurePlot rendered series.
- test_analytics_view_phase_aware.py:237 instrument_health_forwards — chip keys only, not rendered sensor
  names/severity text/color/order. Fix: assert grid labels + SeverityChip state.
- test_analytics_view_phase_aware.py:246 setter_without_method_does_not_raise — GUARDED-PASS: never applies
  fallback layout, only proves empty view doesn't raise. Fix: set_phase(None) + assert no crash for an active
  widget lacking the setter.
- test_analytics_widget_cooldown_history.py:140 one_cooldown_populates_scatter — point count + Y only; wrong
  X date mapping passes. Fix: assert X == parsed cooldown_started_at + Y == duration.

## LOW
- test_analytics_widget_cooldown_history.py:204 zmq_failure_graceful_empty — GUARDED-PASS: `empty OR error`
  accepts either state. Fix: pick the expected state for ok=False, assert exact label visibility/text.

Clean: test_top_watch_bar_persistent_context.py (rendered pressure/temp text + ignored-channel),
test_topwatchbar_replay_mode.py (rendered replay badge text/basename/speed/visibility/warning color).
