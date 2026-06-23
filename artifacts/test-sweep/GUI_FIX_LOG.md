# GUI FIX pass (batches 22-34) — live log

Strengthening the weak GUI tests surfaced by the FIND pass (batch-22..34-findings.md). Same
guardrails as the tier-0/1 fix pass: **TEST FILES ONLY, never src/**; defer anything needing a
prod/src change (mark DEFERRED, keep in the ledger); every touched file pytest-green + ruff-clean;
Qt tests use `QT_QPA_PLATFORM=offscreen`; independent re-run after each executor. The CRIT
(alarm-panel NaN, item 11) + all deferred-ledger items stay deferred. Machine state:
`progress.json` `gui_fix_next_batch`.

| Batch | findings | fixed | deferred | result | notes |
|------:|---------:|------:|---------:|--------|-------|
| 22 | 14 | 10 | 4 | 63 pass | tools/dashboard. Fixed: sensor-grid guarded-pass (assert cell not None first + exact value), replay-session dry-run (publisher_socket raises-if-called), milestone exact "14ч 20мин"+labels, dynamic-grid per-cell refresh spies, experiment-card pill ACCENT/STATUS_OK/BORDER, mock-scenario monotone+exact values, eta/hero/milestone exact text. DEFERRED: 4 XSS-escaping tests — escapeHtml is CLIENT-SIDE JS (server.py:466, FastAPI returns raw JSON, browser escapes pre-innerHTML); needs Playwright/Selenium → ledger item 12. Re-verified 63 pass + ruff. |
