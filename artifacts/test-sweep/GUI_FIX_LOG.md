# GUI FIX pass (batches 22-34) — live log

Strengthening the weak GUI tests surfaced by the FIND pass (batch-22..34-findings.md). Same
guardrails as the tier-0/1 fix pass: **TEST FILES ONLY, never src/**; defer anything needing a
prod/src change (mark DEFERRED, keep in the ledger); every touched file pytest-green + ruff-clean;
Qt tests use `QT_QPA_PLATFORM=offscreen`; independent re-run after each executor. The CRIT
(alarm-panel NaN, item 11) + all deferred-ledger items stay deferred. Machine state:
`progress.json` `gui_fix_next_batch`.

| Batch | findings | fixed | deferred | result | notes |
|------:|---------:|------:|---------:|--------|-------|
| 24 | 22 | 21 | 1 | 60 pass | alarm-panel overlay (safety-adjacent). ACK tests now CLICK the rendered cellWidget button (col 7 v1 / col 5 v2) + assert exact dispatched command `{"cmd":"alarm_acknowledge","alarm_name":"hot"}` (proves button→command wiring); rendered table cells / SeverityChip muted+checkmark / disconnect keeps rows + disables ACK; exact summary "2 критических". **DEFERRED CRIT (item 11): test_reading_invalid_value_defaults_to_zero kept as-is with DEFERRED-NAN-11 marker — prod doesn't coerce NaN→0; needs architect.** Re-verified 60 pass + ruff, src untouched. |
| 23 | 34 | 34 | 0 | 62 pass | GUI widgets. WIDGET-CONTRACT-WEAK → rendered contract: phase_aware back/forward via real `_back_btn.click()` (catches disconnected wiring) + isEnabled() state; sensor_cell rename-escape via real QKeyEvent through eventFilter; phase_stepper pill accent/filled/future styling; temp/pressure plot curve getData() exact (x,y); quick_log exact 2 newest + truncation tooltip; time_window full ordered list; breadcrumb _overlay_label.text(); showcase asserts modal/breadcrumb/7 tiles/bento positions. No defers. Re-verified 62 pass + ruff, src untouched. |
| 22 | 14 | 10 | 4 | 63 pass | tools/dashboard. Fixed: sensor-grid guarded-pass (assert cell not None first + exact value), replay-session dry-run (publisher_socket raises-if-called), milestone exact "14ч 20мин"+labels, dynamic-grid per-cell refresh spies, experiment-card pill ACCENT/STATUS_OK/BORDER, mock-scenario monotone+exact values, eta/hero/milestone exact text. DEFERRED: 4 XSS-escaping tests — escapeHtml is CLIENT-SIDE JS (server.py:466, FastAPI returns raw JSON, browser escapes pre-innerHTML); needs Playwright/Selenium → ledger item 12. Re-verified 63 pass + ruff. |
