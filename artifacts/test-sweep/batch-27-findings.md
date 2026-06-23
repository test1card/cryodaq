# Batch 27 — tier 2 — keithley/knowledge-base/multiline overlay panels (100 tests, 4 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 12 HIGH / 10 MED / 4 LOW. 0 files clean.
FIND pass only. **Theme: keithley_panel SAFETY-CONTROL-WEAK** — every source on/off/emergency/
setpoint test asserts only the intermediate panel SIGNAL, not the exact safety COMMAND payload
dispatched to the engine (keithley_panel.py:552/973 → engine.py:141). A broken/wrong safety
command (wrong channel, wrong on/off, missing emergency_off, wrong target/limits) would pass.
Several also use `_wait(400)` fixed-sleep for debounce. No source-greps.

## test_keithley_panel.py — SAFETY (12 HIGH + 2 LOW)
HIGH — assert the SIGNAL but not the dispatched command dict; spy `_dispatch_command`/ZmqCommandWorker:
- :146 start_click_emits_signal_with_default_spin_values — Fix: assert exact
  `{"cmd":"keithley_start","channel":"smua","p_target":0.5,"v_comp":40.0,"i_comp":1.0}`.
- :155 start_click_reflects_user_adjusted_spins — Fix: assert exact adjusted keithley_start dict.
- :167 stop_click_emits_channel_signal — Fix: assert `{"cmd":"keithley_stop","channel":"smua"}`.
- :177 emergency_requires_warning_confirmation — Fix: one warning + exact keithley_emergency_off payload.
- :191 emergency_cancel_suppresses_signal — command could still dispatch on Cancel. Fix: spy dispatch,
  assert NO command.
- :272 p_spin_debounces_to_single_signal_when_on — SAFETY+FIXED-SLEEP (`_wait(400)`): wrong
  keithley_set_target misses. Fix: Qt timer-wait helper + assert exact command.
- :287 limits_spin_debounces_to_single_signal_when_on — FIXED-SLEEP: wrong keithley_set_limits passes.
  Fix: assert exact channel/v_comp/i_comp.
- :300 p_spin_suppressed_when_channel_off / :311 ..._when_channel_fault — assert no SIGNAL, not no
  COMMAND (a direct dispatch could occur). Fix: assert dispatch spy receives nothing.
- :327 start_ab_emits_panel_signal_and_shows_banner — count-only; misses per-channel keithley_start.
  Fix: assert exact smua/smub command list+payloads.
- :337 stop_ab_emits_panel_signal — no assertion both stop commands dispatched. Fix: assert both
  smua/smub keithley_stop.
- :348 emergency_ab_single_dialog_then_emits — checks signals/dialog count, not commands. Fix: assert two
  keithley_emergency_off dicts.
MED/LOW:
- MED :461 plot_buffer_receives_readings — VALUE-BLIND: only lengths; wrong plotted y/order. Fix: assert
  `ys == [1.5,1.5,1.5]` + monotonic x.
- LOW :58 / :537 channel label tests — assert private `_label_text` not rendered `_title_label.text()`.

## test_knowledge_base_panel.py (5)
- MED :102 clicking_category_switches_to_rag_page — WIDGET-CONTRACT/MOCK-BYPASS: calls `_on_item_clicked`
  directly + no `rag.search` command assert. Fix: select the list item, spy exact
  `{"cmd":"rag.search","query":"a","limit":5}`.
- MED :112 clicking_chat_switches_to_chat_page — direct handler bypasses itemClicked wiring. Fix: trigger item.
- MED :138 snippet_pane_renders_results — count-only; displayed source/text/score unchecked. Fix: assert body/source/score.
- MED :268 rebuild_concurrent_click_polls_status — internal flag unchanged even if `_poll_rebuild_status`
  sends nothing. Fix: click button, spy exact rag.rebuild_status command.
- LOW :41 load_categories_parses_valid_yaml / :93 constructs_with_categories — parse/label could be wrong.
  Fix: assert full category dict / item texts + UserRole ids.

## test_multiline_channel_selector.py (4 MED — all WIDGET-CONTRACT, call private vs click)
- :41 select_all_checks_every_box (`_select_all` vs "Выбрать все" btn) · :47 clear_all (`_clear_all` vs
  "Снять все") · :58 on_accept_empty_blocks_close (`_on_accept` vs OK btn) · :70 on_accept_valid_accepts —
  Fix: click the rendered button/`QDialogButtonBox.Ok`, assert state + selected channels.

## test_multiline_panel.py (1 MED)
- :223 reset_button_sets_baseline — name says button but calls public `reset_channel`; a disconnected row
  reset button passes. Fix: click the row reset cell widget (confirms disabled), assert displayed delta.

Solid: MultiLine state math, table ordering/value formatting, environment rendering, burst response-state,
knowledge-base rebuild response rendering (concrete value/state asserts).
