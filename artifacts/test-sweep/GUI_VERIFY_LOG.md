# GUI VERIFY pass (batches 22-30) — live log

The FIX-only GUI batches 22-30 (strengthened in prior sessions) were never
Codex-VERIFY-reviewed (unlike tier-0/1 and batches 31-34 which carry an in-batch
Codex VERIFY PASS). This pass closes that gap: Codex gpt-5.5 high, read-only,
re-reviews each batch's *modified* test files for problems the FIX may have
INTRODUCED (over-fitting, over-mocking re-hiding prod, residual false-confidence,
tautology, weakened/wrong asserts). Findings fixed test-only; genuine prod gaps
escalated (not auto-patched in safety/routing paths — architect domain).

Scope = files modified vs origin/master per batch (CLEAN/untouched files skipped).

## Disposition table

| Batch | Codex | findings | disposition |
|------:|-------|----------|-------------|
| 22 | PASS | 2 MED + 1 LOW | fixed (wave-1 executor): mock_scenario two-sided pressure bounds; dynamic_sensor_grid seed+rendered-value assert; experiment_card drop redundant private `_current_phase`. |
| 23 | FAIL | 1 HIGH + 2 MED + 1 LOW | fixed: pressure_plot_widget exact paired (x,y) in log10 space (removed raw-or-log10 branch; teeth-confirmed); temp_plot_widget exact paired arrays; quick_log_block consistent descending-ts data; drill_down_breadcrumb wide=full-text + narrow=ellipsis. |
| 24 | PASS | (clean; NaN item deferred) | alarm_panel clean incl. v1/v2 ACK exact-command; `test_reading_invalid_value_defaults_to_zero` stays DEFERRED-NAN-11. |
| 25 | (in wave-1) | — | archive_panel cancel-export strengthened to `_export_workers==[]`/sentinel; calibration_panel clean. |
| 26 | FAIL | 1 HIGH + 2 LOW | conductivity stop-button HIGH: now real `_auto_start_btn.click()` → set_connected(False) → `_auto_stop_btn.click()` asserts exact `{"cmd":"keithley_stop","channel":"smua"}` (PROD-GAP check: keithley_stop DOES dispatch after disconnect — no gap); cooldown_footer drop hasattr→assert no rendered arm/disarm button; conductivity `_chain` internal-invariant noted. |
| 27 | FAIL | 1 HIGH | keithley_panel: tests patched private `_dispatch_command` boundary → patch `keithley_panel.ZmqCommandWorker` at source, assert exact dict + start(). (wave-2) |
| 28 | FAIL | 2 MED + 1 LOW | alarms_wiring vacuous ACK loops (inject alarm first); experiment_overlay More-menu abort via real action; accent QSS token overfit (LOW). (wave-2) |
| 29 | FAIL | 2 HIGH + 1 MED | mw_v2_keithley_wiring tests the panel not mw_v2 forwarding (premise) — INVESTIGATE/escalate; calibration_wiring admits shell doesn't route sensor_unit → CANDIDATE PROD GAP — INVESTIGATE/escalate (architect); conductivity_wiring assert rendered cells. (wave-2) |
| 30 | PASS | 2 MED + 3 LOW | chat worker-leak over-mock → real send_query; cooldown-history full X series; tool-rail/chat/top-bar QSS+show fixes. (wave-2) |

Wave-1 fixes committed together (batches 22/23/24/25/26 test-only): 147 pass, exit 0, ruff clean, no prod-gaps.

## Wave-2 (batches 27-30) results

Executor fixed the clear test-only findings (10 files); I handled the 3
architectural HIGHs myself.

- **27 keithley_panel HIGH** — replaced the private `_dispatch_command` spy with a
  source-level `ZmqCommandWorker` stub (captures cmd + start()), exact command
  dict asserted. FIXED.
- **28 alarms_wiring MED** — inject a real alarm first, assert ACK button list
  non-empty before state (kills the vacuous loop). **28 experiment_overlay MED —
  RESIDUAL/NOT FIXED:** the executor's fix drove the real ⋯ More menu, but
  `QMenu.exec` cannot be monkeypatched in PySide6 (shiboken resolves it from the
  C++ metaobject), so the menu modal blocks; driving it via a timer works in
  isolation but destabilizes combined-run teardown (process segfault, EXIT=139,
  bisected to this file). Reverted to the committed test (proves footer-absence +
  `_on_abort_clicked` dispatches the exact experiment_abort with patched
  confirmation). **Residual:** the menu *contains* the abort action is not directly
  asserted — closing it headlessly is genuinely hostile (un-patchable modal +
  teardown instability); the abort dispatch + footer-absence ARE asserted. **28
  accent LOW** — relaxed brittle token-name/count greps to behavior/role.
- **29 keithley_wiring HIGH (SAFETY)** — premise was wrong (mw_v2 does NOT forward
  keithley commands; the KeithleyPanel dispatches keithley_start/stop directly via
  its own worker — main_window_v2 has no command-forwarding). Reframed as a real
  host-integration test: open the mw_v2-hosted panel, click the REAL Start then
  Stop buttons (one MainWindowV2 to keep QThread churn at baseline), assert exact
  keithley_start + keithley_stop dicts. FIXED.
- **29 calibration_wiring HIGH** — **DEFERRED-CALIB-ROUTING (architect, candidate
  prod gap, NOT auto-patched):** the shell `_dispatch_reading` forwards only
  `unit=="K"` to CalibrationPanel (main_window_v2.py:438), but CalibrationPanel
  .on_reading is documented (calibration_panel.py:10) to route `_raw`/`sensor_unit`
  readings to the acquisition live feed. Acquisition stats actually arrive via the
  `calibration_acquisition_status` poll (_on_mode_result), so whether the shell
  SHOULD also forward sensor_unit readings to populate the live raw-pair feed is an
  open Calibration-v2 data-flow question for the architect. Test reframed to pin
  the CURRENT behavior (A: shell forwards only K) + the panel contract (B:
  on_reading renders raw directly), with the open question marked. ESCALATE.
- **29 conductivity_wiring MED** — assert rendered table cells after dispatch (was
  internal `_temps` + no-crash `_refresh()`). FIXED.
- **30 PASS** — chat worker-leak now drives real `send_query` + emits finished;
  cooldown-history asserts full X series; tool-rail/chat/top-bar QSS specificity +
  `bar.show()`. FIXED.

Wave-2: 12 files test-only, 0 prod-gaps. Full 11-file group 178 pass, exit 0,
ruff clean (after reverting the experiment_overlay modal test).

## ESCALATE to architect (Vladimir)
- **DEFERRED-CALIB-ROUTING** (above) — does the shell intentionally NOT forward
  `_raw`/`sensor_unit` readings to CalibrationPanel.on_reading during acquisition
  (live feed fed only by poll), or is that a routing gap? Candidate prod fix in
  main_window_v2._dispatch_reading if the live raw-pair feed should populate from
  the realtime stream.
