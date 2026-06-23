# PROD_FIX_LOG — prod-fixes branch (worktree cryodaq-prodfix)

Companion to `PROD_FIX_BRIEF.md`. One section per item:
test-red → fix → test-green → CI-mirroring full-suite gate → commit SHA.
Plus a running **decision ledger** (autonomous mode — architect granted
full autonomy 2026-06-22; record every non-trivial call here instead of asking).

Branch: `prod-fixes`, based on master `c805dcf`.
CI gate = `pytest tests/gui/test_app_palette.py` then
`pytest tests/ --deselect tests/gui/test_app_palette.py`.
Tests creating a real SQLiteWriter set `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE","1")`.

---

## Decision ledger

### D1 — Item 1 ZMQ timeout magnitudes (architect-confirmed)
Thesis: REQ socket at 35s sits below the 55s server slow-cap → inversion.
Discovered reality (differs from brief prose): GUI future `_CMD_REPLY_TIMEOUT_S`
was ALREADY 60.0s (not 35s). So the only inverted layer is the subprocess REQ (35s).
Decision (Vladimir, via question before autonomy was granted): **REQ=60s, GUI=65s**.
Final strict tiering `25(helper) < 55(server) < 60(REQ) < 65(GUI)`.
Consulted: architect (explicit answer). Applies to item 1 only.

### D2 — Autonomy granted
Vladimir: "do not ask me anything, run fully autonomously. keep a log of all
your decisions." → From here, no AskUserQuestion. Genuine value/design calls get
my best judgment + an entry here (ORCHESTRATION §18.1 within-plan autonomy).
Corollary (Vladimir): consult Codex/Gemini/research agents when unsure rather
than asking him — applies to the subtle behavior-preservation calls in items 4–8.

### D3 — Local full-suite gate sets CRYODAQ_ALLOW_BROKEN_SQLITE=1  [REVISED → D3-FIX]
Original (WRONG): export the env var globally for the whole gate run.
**D3-FIX (2026-06-23):** Do NOT export it globally. Every test that creates a
real SQLiteWriter sets it itself via `monkeypatch.setenv` (verified: grep across
tests/ — test_persistence_ordering, test_sqlite_writer, test_experiment, etc.).
The guard tests in `test_f23_f24_f25_misc.py` deliberately run WITHOUT it to
assert the broken-WAL gate RAISES; a global export relaxed the guard and made
5 of them fail (`test_startup_gates_on_known_broken_sqlite_version`,
`test_sqlite_adjacent_versions_still_raise[0-3]`) — a self-inflicted gate
artifact, NOT a regression and NOT a CI failure (CI = fresh env, no export).
Corrected gate command runs with NO global env var.

### D7 — Item 1 blast radius: 2 ZMQ threading-test deadlines
Raising the REQ timeout 35→60 s broke `test_cmd_timeout_emits_warning` and
`test_cmd_socket_recovers_after_timeout` in `test_zmq_bridge_subprocess_threading.py`:
both hardcoded `deadline = monotonic() + 40.0` (35 s + 5 s slack), so the timeout
now fires (~60 s) AFTER the deadline. Fix (behavior-preserving, test-timing only):
import `SUBPROCESS_REQ_TIMEOUT_S` and set `deadline = monotonic() + const + 8.0`
so the tests self-adjust to future retunes. Folded into item 1's commit (direct
collateral of the constant change). Adds ~50 s wall-clock; well within `--timeout=120`.
Rejected adding a production env-var timeout override (scope creep / extra surface)
in favour of the minimal deadline fix.

### D5 — Item 2 fix shape (query format-timeout)
`query/agent.py` has NO `import asyncio`; will add it. Wrap the format
`generate()` await (lines 142-148) in `asyncio.wait_for(..., self._format_timeout_s)`.
On timeout, `asyncio.TimeoutError` (alias of builtin `TimeoutError`, an
`Exception` subclass) is caught by the existing broad `except Exception` at
line 155 → `errors.append`, `response` stays `_FALLBACK`. Bounded fallback,
no new branch. Test: add `format_timeout_s` kwarg to `_make_agent` helper
(default 20.0, behavior-preserving) + new test that hangs the 2nd generate
call under a short timeout and asserts prompt `_FALLBACK` return.

### D6 — Item 3 fix shape (periodic-report label)
`window_minutes` is in scope at `live/agent.py:807`. Replace hardcoded
`prefix_suffix="(отчёт за час)"` (line 865) with a derived label via a new
module-level `_report_window_label(window_minutes)` helper producing correct
Russian numeral agreement: 60→"за час", 30→"за 30 минут", 120→"за 2 часа".
Existing test (handler test :145) asserts "(отчёт за час)" for 60 → preserved.
Add new 30-min test asserting "(отчёт за 30 минут)".

### D4 — GOAL = CI GREEN; final validation mirrors CI exactly
`.github/workflows/main.yml` runs, in order:
  1. `ruff check src/ tests/`   ← lint FIRST; failure aborts the whole run
  2. `pytest tests/gui/test_app_palette.py --tb=short -v --timeout=120 --timeout-method=thread`
  3. `pytest tests/ --deselect tests/gui/test_app_palette.py -x --tb=short -v --timeout=120 --timeout-method=thread`
Per-batch gate = ruff + the two pytest steps. FINAL validation (loop goal) =
exact CI mirror incl. `--timeout=120` to catch hangs a plain run would miss.
NOTE: local macOS PySide6/Py3.14 Qt-teardown segfault dumps after pytest exits 0
— environment-only (CI is Linux/Py3.13), does NOT fail CI; capture summary to a
FILE (not `tail`) so the dump can't truncate the pass-count line.

---

### D8 — Batch strategy (user granted batching 2026-06-23)
User: "fix all prod in batches, choose batch size yourself." Plan: **Batch 1**
= items 1+2+3 (real bugs), implemented together, targeted-green each, ONE
full-suite gate (no global env, D3-FIX), then 3 separate commits (brief's
one-commit-per-item rule preserved; the single gate validates the combined
tree). **Batch 2** = items 4-8 (testability refactors), same pattern. Collapses
8 full-suite gates → 2.

### D9 — Item 4 extraction plan (leak-rate command)
Production logic lives in the `_handle_gui_command` closure (engine.py
2318-2348), capturing `leak_rate_estimator`, `_leak_cfg`, `event_logger`. The
test (`test_engine_leak_rate_command.py`) currently COPIES a simplified
`_dispatch` (missing the duration_s numeric/positive validation the real code
has). Extraction: module-level `async def handle_leak_rate_command(action, cmd,
estimator, leak_cfg, event_logger) -> dict | None` (None when action is not a
leak_rate action, so the closure falls through to other actions); closure block
becomes a call + early-return-if-not-None. Test rewritten to import & call the
real handler. Behavior-preserving (same returns, same validation, same event log).

### D10 — Items 5-8 extraction plans (all behaviour-preserving)
- **5 (shutdown-drain):** extracted the inline drain block (engine.py shutdown)
  to module-level `async _drain_dispatch_tasks(tasks, logger_, timeout=10.0)`;
  test imports it instead of mirroring. Timeout surfaced as a param (warning now
  reports the actual cap, previously hardcoded "10s"). Same gather/wait_for/cancel.
- **6 (summary-metadata):** extracted the `ExperimentExport(...)` construction
  (incl. started/ended/duration derivation) to `_build_experiment_export(exp_info,
  metadata)`; metadata-load stays in the closure (needs `to_thread`). Test now
  calls the real builder; added a stronger assertion that the bare `summary` key
  is ignored (only `summary_metadata` is read).
- **7 (diag→telegram):** extracted the `_sensor_diag_tick` Telegram formatting
  (incl. F20 aggregation) to pure `_format_diag_telegram_messages(new_events,
  threshold) -> list[(task_name, message)]`. Returns (name, msg) pairs to preserve
  exact asyncio task names. Test uses the real formatter + 3 new unit tests cover
  the aggregation/per-event/empty paths the copy never exercised.
- **8 (ReplayEngine PUB readiness):** RISKIEST. `ZMQPublisher` is plain `zmq.PUB`
  shared with the live engine; XPUB would change production semantics → rejected.
  Consulted Codex (gpt-5.5/high): a `pub_ready` event only signals "PUB bound"
  (useless for slow-joiner); socket-monitor EVENT_ACCEPTED is tighter-than-sleep
  but NOT deterministic. Codex-endorsed deterministic pattern = prove subscriber
  readiness by RECEIVING from the real PUB stream. Implemented test-only
  `ReplayEngine.publish_readiness_probe()` (+ `READINESS_PROBE_CHANNEL` sentinel)
  that publishes one sentinel Reading through the normal broker→PUB path;
  production never calls it → live stream byte-for-byte unchanged. Test loops
  probe→recv until it sees the sentinel, replacing the fixed `sleep(0.1)`.

### D11 — Batch 2 commit grouping (deviation from one-commit-per-item, justified)
Items 4-7 are four independent, non-overlapping extractions that all live in
`src/cryodaq/engine.py`. Splitting one file across four commits requires
interactive hunk staging (`git add -p`), which this environment blocks. User
authorized batching ("fix all prod in batches, choose batch size yourself"), so
I group the four engine.py extractions into ONE commit whose message enumerates
each item + its test file (each item also has its own separate test file, so
per-item traceability is preserved at the test level). Item 8 (separate file,
`replay_engine/server.py`) gets its own commit. Batch 2 = 2 commits.

## Item log

| # | Item | Test (red→green) | Full-suite | Commit |
|--:|------|------------------|-----------|--------|
| 1 | ZMQ timeout inversion | red→green (41) | batch1 green (3249 passed) | 337e2a8 |
| 2 | query format-timeout | red→green | batch1 green (3249 passed) | d77c1b3 |
| 3 | periodic-report label | red→green | batch1 green (3249 passed) | 2f1f58a |
| 4 | leak-rate dispatch extract | red→green (9) | batch2 green (3255 passed) | f271fcd |
| 5 | engine shutdown-drain extract | red→green (2) | batch2 green (3255 passed) | f271fcd |
| 6 | summary-metadata export | red→green (2) | batch2 green (3255 passed) | f271fcd |
| 7 | diagnostic→alarm→telegram | red→green (5) | batch2 green (3255 passed) | f271fcd |
| 8 | ReplayEngine PUB readiness | red→green (3) | batch2 green (3255 passed) | 061063e |

---

## Final status — ALL 8 ITEMS COMPLETE (2026-06-23)

5 commits on `prod-fixes` (not pushed; human merges):
- `337e2a8` item 1 — ZMQ REQ timeout inversion (+2 collateral threading-test deadlines)
- `d77c1b3` item 2 — query format-timeout bound
- `2f1f58a` item 3 — periodic-report label
- `f271fcd` items 4-7 — engine.py testability extractions
- `061063e` item 8 — ReplayEngine deterministic PUB-readiness probe

Final validation = batch-2 gate = exact CI mirror (ruff src/ tests/ → palette
isolated → full suite --timeout=120, no global env per D3-FIX). Result on the
current HEAD tree: **ruff clean · palette 7 passed · suite 3255 passed, 8
skipped, 0 failed**. CI-green goal met locally. `.gate/` is scratch (uncommitted).
