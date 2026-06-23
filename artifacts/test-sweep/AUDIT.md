# Test-sweep AUDIT — every Codex issue, what was done, and Codex's verdict

Complete accounting of the whole sweep. Per-test-line detail for every issue lives in the
`batch-NN-findings.md` files (those ARE Codex's raw issue lists); this audit cross-references them
with the disposition (FIX_LOG / VERIFY_LOG / GUI_FIX_LOG / deferred ledger) and Codex's approval.

## ⚠️ What "Codex said OK to the fix" actually means here (read first — no overclaiming)

The pipeline was **FIND (Codex finds) → FIX (we strengthen) → VERIFY (Codex re-reviews the fix)**.
"Codex approved" therefore only exists where a **VERIFY** pass ran:

- **tier-0/1 (batches 0–21): a Codex VERIFY pass DID run** — a fresh read-only Codex (gpt-5.5 high)
  re-reviewed every fixed file adversarially. **That re-review is the approval.** Outcome per batch:
  - tests Codex marked **CLEAN** in verify = **Codex-approved ✓**.
  - tests where Codex **raised a residual** = Codex said the first fix was **NOT good enough**; we then
    re-fixed (test-only) and independently re-ran. **Codex did not re-review the residual-fix a 2nd time**
    (the verify pass was one round). So those are "Codex-flagged → re-fixed → independently re-verified".
  - batches 19, 20, 21 were re-reviewed **inline by Claude** (Codex hit its usage limit), not Codex —
    flagged as such below.
- **tier-2 GUI (batches 22–34): NO Codex verify pass has run.** Codex *found* the issues (FIND); our GUI
  fixes (22–26) are green + independently re-run but **have NOT been Codex-re-approved**. 27–34 not yet fixed.
- **prod fixes (8 items, prod-fixes worktree): Codex was consulted on ONE design decision (item 8, XPUB
  rejected); it did not run a verify pass over the prod fixes.** Their validation is the CI-mirror gate.

Totals: tier-0/1 FIND = 232 (1C/20H/50M+... per SUMMARY); tier-2 GUI FIND = 346 (1C/153H/132M/60L);
VERIFY raised ≈ 60 residuals. Numbers below reconcile to these.

---

## A. tier-0/1 — FIND → FIX → VERIFY (Codex re-approved)  [batches 0–21]

Columns: Codex FIND (C/H/M/L) | fixed in FIX pass | VERIFY: Codex residuals raised | how resolved | **Codex verdict**.
Detail: `batch-NN-findings.md` (FIND) + `verify-batch-NN.md` (verify) + FIX_LOG.md / VERIFY_LOG.md.

| Batch | area | FIND C/H/M/L | VERIFY: Codex raised | resolved | Codex verdict on the batch |
|---|---|---|---:|---|---|
| 00 | alarm core | 0/0/4/3 | 5 | 3 fixed test-only, 2 DEFERRED (status_shape/ack = engine closure) | the 3 fixed → re-fixed+re-verified; rest CLEAN; **F3/F4 deferred (item 7)** |
| 01 | storage/calib/channel | 0/1/1/4 | 4 | all 4 fixed (inf-value, curve round-trip, channel_key) | **all CLEAN after re-fix** ✓ |
| 02 | cooldown/engine/event | 0/3/2/1 | 3 | all 3 fixed; leak-rate copied `_dispatch` HIGH **DEFERRED** | fixed re-verified; **leak-rate deferred → prod item 4** |
| 03 | experiment/photos | 0/1/2/2 | 4 | all 4 fixed (sidecar-atomic, public WAL, html-escape, offscreen) | **all CLEAN** ✓ |
| 04 | interlock/mem/p0/persistence | 0/3/4/3 | 7 | all 7 fixed — **F6 first fix WRONG, independent review caught + redone** | re-verified; F6 corrected (2-condition serial-await) |
| 05 | SAFETY-CRITICAL | 0/6/8/3 | 5 | 4 fixed; **F3 exposed a REAL FLAKE (sub-µs time.time) → fixed**; F4 kept by-design | re-verified 0/20; min_points=60 kept (contract) |
| 06 | sensor-diag/sqlite/prefs | 0/0/2/2 | 2 | both fixed (WAL kill-on-timeout, public save path) | **CLEAN** ✓ |
| 07 | ZMQ bridge/subprocess | **1**/4/9/5 | 11 | 5 fixed; **6 DEFERRED** (inner-timeouts, real-timeout flakes, overflow closure) | fixed re-verified; **CRIT timeout-inversion + flakes deferred → prod items 1, 8** |
| 08 | drivers keithley/gpib/etalon | 0/0/4/5 | 3 | all 3 fixed (gpib real _blocking_connect, timestamps) | **CLEAN** ✓ |
| 09 | drivers lakeshore/visa/archive | 0/2/8/3 | 3 | all 3 fixed — broke a calibration TAUTOLOGY (hand-computed 14.192) | **CLEAN** ✓ |
| 10 | storage/replay/alarm-flow | 0/0/6/3 | 7 | 7 fixed; **2 redundant grep tests DELETED**; real _broadcast_pump | **CLEAN** ✓ |
| 11 | agents chart/diagnostic | 0/0/4/2 | 4 | all 4 fixed (drain helper, _log_task_exception, rename barrier) | **CLEAN** ✓ |
| 12 | intent-classifier router | 0/5/6/5 | 5 | all 5 fixed (sentinel-identity + assert_awaited_once_with) | **CLEAN** ✓ |
| 13 | ollama/periodic/query | 0/1/7/1 | 4 | all 4 fixed; **2 prod bugs DEFERRED** (format-timeout, periodic label) | fixed re-verified; **deferred → prod items 2, 3** |
| 14 | rag/report/russification | 0/1/2/5 | 3 | all 3 fixed; RAG defensive-sort noted (item 9) | **CLEAN** ✓ |
| 15 | agents/rag indexer/cli | 0/4/5/1 | 2 | both fixed — **F1 NEW FLAKE (randomized hash()) → deterministic** | **CLEAN** ✓ |
| 16 | rag-audit/calib/cooldown | 0/3/6/3 | 4 | all 4 fixed — broke a cooldown-floors TAUTOLOGY (literal arithmetic) | **CLEAN** ✓ |
| 17 | analytics vacuum/cooldown/steady | 0/3/9/4 | 8 | all 8 fixed (B/α-identifiability, closed-form ETA cross-check) | **CLEAN** ✓ |
| 18 | integration/launcher/notif (SECURITY) | 0/3/9/5 | 8 | 5 fixed (secret-leak walker hardened); **3 DEFERRED** (launcher seam) | fixed re-verified; **launcher → item 10** |
| 19 | notifications/telegram + replay | 0/3/2/1 | 0 | (no residuals) | **CLEAN — reviewed INLINE (Codex usage-limit)** |
| 20 | replay/reporting/sinks/root | 0/3/5/2 | 0 | 5 already-fixed CLEAN; **3 DEFERRED** (shutdown-drain/summary/PUB) | **CLEAN inline; deferred → prod items 5, 6, 8** |
| 21 | launcher/web/logging/zmq-bind | 0/3/10/4 | 0 | 8 files CLEAN; residual source-checks share launcher seam (item 10) | **CLEAN — reviewed INLINE (Codex usage-limit)** |
| ⊕ | (checkpoint flakes) | — | 2 | bonus: load-only p0 await_count race + a time-of-day overlay bug | both fixed & re-verified |

**tier-0/1 result:** every FIND finding fixed or deferred; every fix re-reviewed (Codex 0–18, inline 19–21);
suite green 3246/0. Deferred items → carried to the prod-fix worktree (section C).

---

## B. tier-2 GUI — Codex FIND → GUI FIX (NOT yet Codex-re-approved)  [batches 22–34]

Columns: Codex FIND (C/H/M/L) | GUI-fix status | Codex verdict.
**No Codex verify pass has run on any of these.** Detail: `batch-NN-findings.md` + GUI_FIX_LOG.md.

| Batch | area | FIND C/H/M/L | GUI-fix status | Codex verdict |
|---|---|---|---|---|
| 22 | tools/web/dashboard | 0/5/4/5 | **FIXED** 10/14; 4 XSS DEFERRED (client-side JS → item 12) | **NOT Codex-re-reviewed** |
| 23 | GUI widgets | 0/15/13/6 | **FIXED** 34/34 (real clicks, getData, pill QSS) | **NOT Codex-re-reviewed** |
| 24 | alarm-panel (safety-adjacent) | **1**/12/8/1 | **FIXED** 21/22; **CRIT NaN DEFERRED (item 11)** | **NOT Codex-re-reviewed** |
| 25 | archive+calibration panels | 0/15/7/5 | **FIXED** 27/27 (button clicks + exact commands) | **NOT Codex-re-reviewed** |
| 26 | conductivity/cooldown/instruments | 0/5/21/5 | **FIXED** 31/31 (public on_reading + status text) | **NOT Codex-re-reviewed** |
| 27 | keithley(SAFETY)/kb/multiline | 0/12/10/4 | **PENDING** (not fixed) | found only |
| 28 | operator-log/accent/exp-overlay/mw_v2 | 0/6/12/16 | **PENDING** | found only |
| 29 | mw_v2↔panel wiring (10 files) | 0/43/5/2 | **PENDING** (incl keithley command-dispatch SAFETY GAP) | found only |
| 30 | tool-rail/top-bar + analytics views | 0/6/13/1 | **PENDING** | found only |
| 31 | analytics widgets | 0/22/9/1 | **PENDING** | found only |
| 32 | insight/steady/palette/theme/fonts | 0/7/8/8 | **PENDING** | found only |
| 33 | overview/preflight/shift/theme | 0/3/11/4 | **PENDING** (preflight safety-gate weak) | found only |
| 34 | tray/watchdog/prediction/pressure | 0/2/11/2 | **PENDING** | found only |

**tier-2 result:** 129 findings FIXED (batches 22–26, test-only, green) — but none Codex-re-approved.
217 findings PENDING (batches 27–34). 1 CRIT deferred (item 11).

---

## C. Deferred ledger — every deferred item, and who resolved it

| # | item | found | status |
|---|---|---|---|
| 1 | ZMQ timeout-layer inversion (CRIT) | b07 | **RESOLVED in prod-fixes** (item 1: SUBPROCESS_REQ_TIMEOUT_S=60, GUI 65; test on live constants) |
| 2 | leak-rate copied `_dispatch` (engine monolith) | b02 | **RESOLVED in prod-fixes** (item 4: extracted `_handle_leak_rate_command` + 3 new tests) |
| 3 | shutdown-during-timeout instrumentation | b07 | partially — prod item 5 extracted `_drain_dispatch_tasks` (shutdown-DRAIN); the recv_string()-entered probe still open |
| 4 | query format-timeout not enforced | b13 | **RESOLVED in prod-fixes** (item 2: `asyncio.wait_for(_format_timeout_s)` + behavioral test) |
| 5 | periodic-report label hardcoded | b13 | **RESOLVED in prod-fixes** (item 3: `_report_window_label` + `_plural_ru` + tests) |
| 6 | diagnostic-alarm pipeline (`_sensor_diag_tick`) | b18 | **RESOLVED in prod-fixes** (item 7: extracted `_format_diag_telegram_messages` + 3 tests) |
| 7 | alarm_v2 status/ack engine closure | b00 | **OPEN** — not in the prod-fix brief; still needs `_handle_gui_command` extraction |
| 8 | ZMQ test-infra seams (inner-timeouts/flakes/overflow) | b07 | partially — prod item 1 added the timeout constant + fixed 2 threading deadlines; inner-timeouts/overflow still source/grep |
| 9 | RAG defensive sort (minor) | b14 | **OPEN** (minor; schema vs LanceDB-delegation) |
| 10 | launcher real-construction seam (parse_args / LauncherWindow) | b18/b21 | **OPEN** — needs a `_parse_args` helper + a constructable LauncherWindow seam |
| 11 | alarm-panel NaN value not coerced (CRIT) | b24 | **OPEN — architect** (GUI prod gap; surfaced after the prod-fix brief) |
| 12 | XSS-escaping tests need a browser harness | b22 | **OPEN** (escapeHtml is client-side JS; needs Playwright/Selenium) |

`+ summary-metadata export` (b20) → **RESOLVED in prod-fixes** (item 6: `_build_experiment_export`).
`+ replay-predictor PUB handshake` (b20) → **RESOLVED in prod-fixes** (item 8: `publish_readiness_probe`).

---

## D. Prod fixes (prod-fixes worktree, 6 commits) — the prod bugs that strengthened tests exposed

These are the "test failed → fix the prod" cases. Codex-OK: only item 8 was Codex-consulted (design).

| item | prod fix (src) | test | Codex-OK |
|---|---|---|---|
| 1 | zmq_subprocess REQ timeout 35→60s, GUI 65s (337e2a8) | test_zmq_bridge ordering on live constants | gate-green; not Codex-verified |
| 2 | query/agent format generate wrapped in wait_for (d77c1b3) | new behavioral hang-under-timeout test | gate-green; not Codex-verified |
| 3 | live/agent periodic label from window_minutes + ru-plural (2f1f58a) | label-helper unit + 30-min integration | gate-green; not Codex-verified |
| 4–7 | engine.py extract 4 testability helpers (f271fcd) | real-handler tests + ~9 new path tests | gate-green; not Codex-verified |
| 8 | ReplayEngine `publish_readiness_probe` (061063e) | probe→recv readiness loop | **Codex consulted** (rejected XPUB) |

Prod-fixes branch self-reported green: ruff clean, palette 7, full suite 3255/0 (macOS). Windows/Linux pending CI.

---

## E. Open / remaining (NOT done)

1. **GUI FIX batches 27–34** — 217 Codex findings still PENDING (operator-log, the 50-finding mw_v2 wiring
   set incl. a keithley command-dispatch SAFETY gap, analytics widgets, preflight safety-gate). Test-only work.
2. **No Codex VERIFY pass on ANY tier-2 GUI fix** (22–26 done but unverified; 27–34 unfixed). A GUI verify
   pass would be the analogue of the tier-0/1 Codex re-review.
3. **Deferred items still open:** 7 (alarm_v2 engine closure), 9 (RAG sort, minor), 10 (launcher seam),
   11 (alarm-panel NaN — CRIT, architect), 12 (XSS browser harness); item 3/8 partially open.
4. **The prod-fixes merge** into master (this session) — pending its full-gate validation + commit.
