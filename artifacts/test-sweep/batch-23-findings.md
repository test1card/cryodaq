# Batch 23 — tier 2 — GUI dashboard widgets + shell overlay design-system (87 tests, 11 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 15 HIGH / 13 MED / 6 LOW. 2 files clean.
FIND pass only. Dominant anti-pattern: WIDGET-CONTRACT-WEAK — tests call PRIVATE handlers
(`_on_back_clicked`, `_enter_rename_mode`) or assert PRIVATE attrs (`_current_phase`,
`_data_stale`) instead of exercising the real Qt event path and asserting the rendered
text/value/enabled/stylesheet. No source-greps or fixed-sleeps found.

## test_phase_aware_widget.py (14 findings)
- **HIGH :92 test_back_button_emits_signal** — calls `_on_back_clicked()` directly; a
  disconnected/hidden button passes. Fix: click `_back_btn`, assert emitted target + enabled/visible.
- **HIGH :107 test_forward_button_emits_signal** — bypasses real button signal path. Fix: click
  `_forward_btn`, assert emitted target.
- **HIGH :122 test_back_disabled_at_first_phase** — proves handler no-ops, not that the button is
  disabled. Fix: assert `_back_btn.isEnabled() is False`.
- **HIGH :137 test_forward_disabled_at_last_phase** — same handler-only bypass. Fix: assert
  `_forward_btn.isEnabled() is False`.
- **HIGH :232 test_context_label_shows_eta_when_cooldown_eta_received** — VALUE-BLIND: any text with
  "ETA" passes even if 12.5h formatted wrong. Fix: assert displayed converted duration (e.g. "12ч 30мин").
- **MED :33/39/53/72/190/270** (initial-inactive / activates / deactivates / phase-change /
  active-no-phase / cached-reset) — assert private flags/cache; UI text/controls/stepper could be
  wrong. Fix: assert visible label text + control visibility + stepper pill state via rendered widget.
- **MED :184 test_widget_handles_missing_keys** — NO assertion despite "inactive" comment. Fix: assert
  inactive state + text.
- **LOW :27 test_phase_labels_complete** — any non-empty wrong label passes. Fix: assert expected labels.
- **LOW :172 test_widget_handles_unknown_phase_gracefully** — no assertion after unknown phase. Fix:
  assert defined fallback UI.

## test_phase_stepper.py (3 HIGH)
- **HIGH :13 highlights_current_phase / :19 marks_completed_phases / :26 none_resets_all** — assert only
  `_current_phase`; pill STYLING (accent/filled/future) unchecked. Fix: assert current pill accent
  styling, prior pills filled/ok, future pills reset.

## test_sensor_cell.py (6 findings)
- **HIGH :38 refresh_from_empty_buffer_marks_stale** — private `_data_stale`; value/status/stale-border
  could be wrong. Fix: assert dash value, empty unit, stale text + stale style token.
- **HIGH :56 rename_escape_cancels** — calls `_exit_rename_mode()` directly, never sends Escape through
  eventFilter. Fix: enter rename, `QTest.keyClick(Escape)`, assert label restored.
- **MED :44 inline_rename_signals** — private `_enter_rename_mode`/`_commit_rename` bypass
  double-click/editingFinished. Fix: Qt events + assert signal + restored label.
- **MED :65 large_number / :110 small_number** — any sci-notation with "e" passes. Fix: assert exact
  "1.50e+03" / "5.00e-03".
- **LOW :11 constructs** — objectName only. Fix: assert initial label/dash/no-data hint/stale style.

## test_quick_log_block.py (3 findings)
- **HIGH :48 max_2_entries_visible** — zero rendered entries satisfies `<= 2`. Fix: assert exactly the
  newest two messages, no third.
- **HIGH :82 long_message_truncated_in_display** — GUARDED-PASS: loop exits OK if no label contains "A".
  Fix: collect matching labels, assert one exact truncated text + tooltip.
- **LOW :14 constructs** — non-None + name. Fix: assert composer input/send button/empty label.

## test_temp_plot_widget.py (3) / test_pressure_plot_widget.py (2)
- **HIGH temp:36 refresh_with_data** — no assertion that Т1 curve got [1000,1001]/[77.5,78.0]. Fix:
  inspect `_plot_items["Т1"]` data after refresh.
- **HIGH pressure:27 refresh_empty_and_filled** — no assertion refresh reads VSP63D_1/pressure or calls
  set_series([1000,1001],[1e-4,1e-5]). Fix: inspect plot data / spy set_series.
- **MED temp:29 refresh_empty_buffer** — no assertion curves cleared. Fix: assert each curve empty.
- **LOW temp:22 / pressure:21 constructs** — non-None only. Fix: assert embedded plot/channel/toolbar/axis.

## Other
- **MED test_time_window.py:13 all_options_returns_five** — middle options could be wrong (length/first/
  last only). Fix: assert full ordered `[MIN_1,HOUR_1,HOUR_6,HOUR_24,ALL]`.
- **MED test_drill_down_breadcrumb.py:36 overlay_name_updates_display** — tooltip only; visible label
  could be stale. Fix: assert `_overlay_label.text()` equals/elides the new name.
- **HIGH test_showcase.py:23 builds_all_phase_i1_primitives** — DESIGN-SYSTEM-WEAK: `findChild(...) is
  not None` passes with empty/misplaced primitives. Fix: assert modal content, breadcrumb visibility,
  seven tile labels, bento grid positions/spans.

Clean: test_bento_grid, test_modal_card.
