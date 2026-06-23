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
