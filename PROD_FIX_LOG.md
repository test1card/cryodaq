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

## Item log

| # | Item | Test (red→green) | Full-suite | Commit |
|--:|------|------------------|-----------|--------|
| 1 | ZMQ timeout inversion | pending | — | — |
| 2 | query format-timeout | pending | — | — |
| 3 | periodic-report label | pending | — | — |
| 4 | leak-rate dispatch extract | pending | — | — |
| 5 | engine shutdown-drain extract | pending | — | — |
| 6 | summary-metadata export | pending | — | — |
| 7 | diagnostic→alarm→telegram | pending | — | — |
| 8 | ReplayEngine PUB readiness | pending | — | — |
