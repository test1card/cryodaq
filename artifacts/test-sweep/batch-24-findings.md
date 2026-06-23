# Batch 24 — tier 2 — alarm-panel overlay (60 tests, 1 file)

Codex gpt-5.5 high, read-only. **1 CRIT** / 12 HIGH / 8 MED / 1 LOW.
FIND pass only (safety-adjacent: alarm display / acknowledge / severity rendering). No
source-greps, fixed-sleeps, or guarded-passes found. Dominant patterns: ACK/STATE-WEAK (ack
tests call private `_acknowledge`/`_acknowledge_v2` instead of CLICKING the rendered button —
a broken button→command wiring would pass) and WIDGET-CONTRACT-WEAK (assert private `_alarms`/
`_v2_alarms`/`_v*_ack_buttons` instead of the rendered table cells / SeverityChip / ack state).

## CRIT — potential prod gap the test hides (architect confirm; do NOT fix here)
- **:261 test_reading_invalid_value_defaults_to_zero** — VALUE-BLIND. Sends `value=float("nan")`
  but asserts only the (bad) threshold; prod `float(reading.value)` leaves NaN in the row
  (alarm_panel.py:608-611), so the test's named "value defaults to zero" contract is NOT
  exercised and (per static analysis) prod does NOT coerce NaN→0. Needs architect confirmation:
  either prod should coerce non-finite values to 0 (prod fix) and the test assert the rendered
  value cell == "0"/"0.0", or the test name is wrong. Same handling as the batch-07 CRIT —
  surfaced, not auto-fixed.

## HIGH (12)
- **:227 reading_activated_adds_row** — asserts private `_alarms`; rendered severity/name/value/
  action cells + SeverityChip("CRITICAL") + ACK button unchecked. Fix: assert table row cells.
- **:239 reading_acknowledged_updates_state** — ACK/STATE: private state only; rendered "Подтв."
  label, removed ACK button, muted chip (667-695) unchecked. Fix: assert action cell + no button + chip.
- **:246 reading_cleared_updates_state** — private state only; cleared-state label + ACK absence
  unchecked. Fix: assert action cell "Сброшена", no widget, summary updated.
- **:338 update_v2_status_populates_table** — VALUE-BLIND: row count + private payload; rendered
  v2 severity/id/message/channels/time cells (715-775) unchecked. Fix: assert exact cell texts + chip.
- **:414 v2_acknowledged_row_replaces_button_with_label** — ACK/STATE: action label checked but the
  acknowledged chip muted/checkmark state (732-735) not; a fresh red CRITICAL chip would pass. Fix:
  assert chip uses acknowledged palette.
- **:470 v2_ack_button_transitions_to_label_on_engine_update** — ACK/STATE: chip/operator display
  underchecked. Fix: assert chip muted + `acknowledged_by` text.
- **:574 poll_result_ok_updates_table** — name says updates table, asserts only private `_v2_alarms`.
  Fix: assert v2 row/cells/chip after `_on_poll_v2_result`.
- **:586 poll_result_failure_preserves_last_state** — VALUE-BLIND: only key presence; fail-open could
  drop severity/message. Fix: assert exact previous payload + rendered cells unchanged.
- **:612 v1_acknowledge_dispatches_zmq_command** — ACK/STATE: calls private `_acknowledge("hot")`; a
  broken table-button connection (683-685) would pass. Fix: CLICK the rendered ACK button, assert command.
- **:622 v2_acknowledge_dispatches_zmq_command** — ACK/STATE: calls private `_acknowledge_v2("cold")`;
  broken v2 button lambda (771-772) would pass. Fix: click `cellWidget(0,5)`, assert command.
- **:637 disconnect_keeps_v1_rows / :645 disconnect_keeps_v2_rows** — VALUE-BLIND: private dict
  non-empty; the visible fail-open table could be cleared/stale. Fix: assert rendered rows still
  visible + ACK button disabled.

## MED (8)
- **:253 reactivated_increments_trigger_count** — private count; displayed count cell (676) unchecked.
  Fix: assert count cell text "2".
- **:313 set_connected_enables_v1_ack_buttons** — private `_v1_ack_buttons[0]` not the table cell
  button. Fix: `cellWidget(row,7)` enabled.
- **:369 update_v2_status_truncates_long_message** — only `endswith("…")`+shorter; wrong prefix passes.
  Fix: assert exact max length + preserved prefix.
- **:400/:406 v2_row_ack_button_disabled/enabled_before/after_connect** — private `_v2_ack_buttons`
  list, not rendered button. Fix: `cellWidget(0,5)` disabled QPushButton "ПОДТВЕРДИТЬ" / enabled.
- **:449 v2_unacknowledged_row_keeps_ack_button** — only widget existence/length. Fix: assert button
  text/state + click to verify command alarm name.
- **:514 summary_shows_criticals / :523 summary_shows_warnings** — only the word; wrong count passes.
  Fix: assert exact "2 критических" / "1 предупреждение".

## LOW
- **:564 poll_in_flight_guard_prevents_double_dispatch** — asserts dispatch count only. Fix: assert
  exact dispatched list `[{"cmd": "alarm_v2_status"}]`.

Solid: SeverityChip, _make_ack_button, _elapsed_text direct-helper tests (narrow but adequate).
