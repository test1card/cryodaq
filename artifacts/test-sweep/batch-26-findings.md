# Batch 26 — tier 2 — conductivity/cooldown-footer/instruments overlay panels (98 tests, 3 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 5 HIGH / 21 MED / 5 LOW. 0 files clean.
FIND pass only. No source-greps/fixed-sleeps/guarded-passes. Patterns: ACTION-WEAK (call
`_on_auto_start()`/`_on_move_up()` directly vs clicking → broken wiring passes), MOCK-BYPASS
(call private `_handle_reading()`/`_update_cooldown_ui()` instead of the public `on_reading()` /
`_on_cooldown_status()` result path), STATUS-WEAK (assert indicator COLOR only, not the
displayed status text), VALUE-BLIND (count/substring vs exact cell values).

## test_conductivity_panel.py (14)
HIGH:
- :354 auto_start_rejects_short_chain · :408 auto_stop_transitions_to_idle_and_sends_keithley_stop
  — ACTION-WEAK: call `_on_auto_start()`/`_on_auto_stop()` directly; broken Start/Stop wiring
  (696-703) passes. Fix: click the button, assert command + UI state + signal.
- :370 auto_start_generates_power_list — ACTION-WEAK/OVER-MOCK: broken wiring/timer/progress/
  `auto_sweep_started` emission (1201-1232) can pass. Fix: click Start, assert command/timer/status/signal.
- :484 auto_tick_advances_when_stable — VALUE-BLIND/STATUS: only step+result count; wrong recorded
  P/dT/R/G, next command, progress (1247-1327) pass. Fix: assert `_auto_results[0]` exact + next
  keithley_set_target + progress text.
MED:
- :152 reorder_up · :164 reorder_down — ACTION-WEAK private `_on_move_up/down` (429-436). Fix: click btn.
- :179 temperature_reading_updates_temps_and_buffer — MOCK-BYPASS: `_handle_reading()` + private buffer
  len; bypasses public `on_reading()` (877-889) + plot/empty-state. Fix: on_reading() + assert plot.
- :188 power_reading_updates_power_channel — STATUS-WEAK: private `_power` not displayed `P=… Вт`
  (925-935). Fix: assert `_power_label.text()`.
- :224 table_calculates_R_and_G — VALUE-BLIND substring ("2000" matches 20000); units unchecked. Fix:
  exact cell text + R/G headers.
- :238 table_total_row_present — only row count + "ИТОГО"; wrong total R/G (1013-1044). Fix: assert total cells.
- :645 get_auto_state_after_start — ACTION-WEAK private start setup. Fix: Start via btn then assert accessors.
- :793 power_label_waiting_after_channel_switch — ACTION-WEAK private `_on_power_changed` (344-347). Fix:
  change combo selection, assert text.
LOW:
- :102 constructs_and_exposes_core_surfaces — private widgets only. Fix: assert visible title/controls/btn.
- :124 table_has_eleven_columns — count only; wrong headers/units. Fix: assert exact `R (К/Вт)`/`G (Вт/К)`.

## test_cooldown_footer_v0_55_6_1.py (7) — all MOCK-BYPASS (call private `_update_cooldown_ui()` vs result path)
- :65 initial_waiting · :70 armed_active · :75 watchdog · :86 fired_fault_color · :92 auto_disarmed_ok_color ·
  :99 progress_bar_only_visible_while_watching — Fix: drive `_on_cooldown_status()` with the real payload
  ({"state":...,"t_cold":...,"progress","eta_h"}), assert rendered text + color.
- LOW :111 no_arm_handler_attributes — WIDGET-CONTRACT: private-attr-absence is impl-shaped. Fix: assert no
  arm/disarm control in the footer widget tree.

## test_instruments_panel.py (10)
HIGH:
- :325 poll_result_populates_table — VALUE-BLIND/STATUS: only row count; wrong channel name, health
  score/color, summary chips (499-571) pass. Fix: assert row "Т1 Plate", health 95, color, chip text.
MED:
- :180 new_instrument_creates_card — MOCK-BYPASS: `_handle_reading()` + count; bypasses public on_reading()
  (694-746) + card text/status. Fix: on_reading(), assert card label/indicator/empty-hidden.
- :187 repeated_reading_updates_same_card — private `total_readings` not the rendered counter (354-356).
  Fix: assert "Показания: 2 | Ошибки: 0".
- :195 two_distinct_instruments_create_two_cards — count/key subset; wrong displayed names/placement. Fix:
  assert both visible card names.
- :245 stale_detection_marks_fault · :255 fresh_reading_recovers_to_ok — STATUS-WEAK color only; missing
  "Статус: Нет связи"/"Норма" text + counters (326-356). Fix: assert color + status label + counters.
- :493 disconnect_keeps_diag_rows · :504 disconnect_keeps_cards_alive — row/card count only; could preserve
  one stale/wrong row or reset status. Fix: assert row/card text/health/color/status after disconnect.
LOW:
- :269 status_indicator_is_painted_qframe — TAUTOLOGY: `not hasattr(ind,"text") or callable(...)` passes for
  QLabel (text is callable). Fix: assert concrete `_StatusIndicator`/QFrame contract.
- :360 seven_columns_rendered — count only; wrong diagnostics headers/order (80-88). Fix: assert exact headers.

Solid: static instrument-id extraction, health-threshold helper, exact summary-chip-count tests, cooldown
"no push button" test.
