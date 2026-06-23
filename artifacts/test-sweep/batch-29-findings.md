# Batch 29 — tier 2 — main_window_v2 ↔ panel wiring + dialog + overlay-container (98 tests, 10 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 43 HIGH / 5 MED / 2 LOW. 1 file clean.
FIND pass only. No source-greps. The batch is dominated by a SYSTEMIC WIRING-WEAK pattern and a
keithley SAFETY GAP (below).

## SYSTEMIC (30 HIGH) — "connected `_connected` flag only"
Every `_tick_status` / lazy-open / overlay-open wiring test asserts only the private panel
`_connected` flag after `MainWindowV2._ensure_overlay()`/`_tick_status()`, even though prod fans
connection state into VISIBLE labels / enabled controls / polling timers / action gating
(main_window_v2.py:277/289/297/303/329/335/341/662). A broken panel `set_connected` UI effect
passes. **Fix (all): assert the user-visible contract — enabled/disabled buttons, connection label
text, polling timer active/inactive — not the private flag.**
Files/lines (each a HIGH of this class):
- archive_wiring: :50, :62, :73, :137, :148
- calibration_wiring: :63, :75, :157, :168
- conductivity_wiring: :60, :72, :159, :171
- experiment_wiring: :36, :48, :60, :71
- instruments_wiring: :53, :65, :137, :148
- keithley_wiring: :96, :109, :121, :193
- operator_log_wiring: :60, :72, :84, :207

## reading-routing HIGH (assert private attr / mock-call, not rendered reception)
- calibration_wiring.py:92 `k_reading_reaches_overlay` — GUARDED-PASS: dispatch then only assert
  panel exists. Fix: spy CalibrationPanel.on_reading / rendered value.
- calibration_wiring.py:108 `raw_reading_routes_through_to_acquisition_widget` — MOCK-BYPASS: asserted
  value comes from direct `on_reading()` (l122) while `_dispatch_reading()` doesn't route sensor_unit
  (main_window_v2.py:438). Fix: assert the dispatched reading reaches/renders, or fix expected non-routing.
- conductivity_wiring.py:89/115 `temperature/power_reading_reaches_overlay` — value checked only in
  private `_temps`/`_power`, not rendered readout/plot. Fix: assert visible channel/readout/curve.
- experiment_wiring.py:81 `operator_log_reading_reaches_experiment_overlay` — GUARDED-PASS: only overlay
  existence. Fix: stub timeline refresh boundary, assert log request / entry effect.
- instruments_wiring.py:82/95 `lakeshore/keithley_reading_creates_card` — private `_cards`/key, not
  rendered card label/status/value. Fix: assert visible card contents.
- operator_log_wiring.py:151 `entry_reading_triggers_refresh_on_overlay` — MOCK-BYPASS: monkeypatches
  `refresh_entries`, asserts call count. Fix: assert the log-refresh command / rendered refresh.

## keithley SAFETY GAP + control-gating (4 HIGH)
- keithley_wiring.py:143 `receives_safety_state_via_dispatch` / :156 `receives_safety_ready_via_dispatch`
  / :172 `safety_replay_on_lazy_open` — SAFETY/WIDGET-CONTRACT: assert private `_safety_ready`/label, NOT
  that dangerous controls are disabled/enabled-only-when-connected+safe. Fix: assert per-channel + A+B
  start/target/limit control enablement states.
- **SAFETY GAP (whole file): NO test proves the exact Keithley command dict is forwarded.** Prod dispatch
  is in `_SmuChannelBlock` (keithley_panel.py:552/567/598/613/630), not MainWindowV2 — needs a test that
  patches ZmqCommandWorker and asserts exact `{"cmd":...,"channel":"smua/smub","p_target":...,"v_comp":...,
  "i_comp":...}` for start/stop/emergency/target/limits. (Ties to batch-27 keithley SAFETY-CONTROL-WEAK.)

## f4_lazy_replay (3 HIGH + 2 MED)
- :111 cooldown_replayed / :128 phase_replayed / :152 close_and_reopen_replays — HIGH WIDGET-CONTRACT:
  assert private `_last_cooldown`/phase accessor / manually null `_analytics_view`, never switch the
  overlay container / show the widget. Fix: use real `_on_tool_clicked("analytics")` navigation + assert
  current stacked widget + rendered replay value.
- :439 keithley_snapshot_replayed / :486 k_reading_forwarded_to_analytics — MED VALUE-BLIND: assert only
  truthy cache / one key. Fix: assert all keys + exact rendered values (e.g. "4.2 K").

## Other
- MED archive_wiring.py:93 `on_reading_is_noop_and_does_not_crash` — TAUTOLOGY: calls panel.on_reading()
  directly, not shell routing. Fix: dispatch through MainWindowV2 or rename as pure panel no-op.
- MED new_experiment_dialog.py:20/28 `validates_empty_name/operator` — GUARDED-PASS: only validation label
  visible. Fix: assert no signal emitted + dialog not accepted + exact error/focus.
- LOW archive_wiring.py:169 `export_cancel_returns_promptly` — wall-clock `elapsed<1.0`. Fix: assert no
  worker / no in-flight state, no time threshold.
- LOW operator_log_wiring.py:171 `unrelated_analytics_reading_does_not_crash` — no assertion. Fix: assert
  no refresh command / unchanged entries.

Clean: test_overlay_container.py (asserts currentWidget()/current_overlay after switching).
