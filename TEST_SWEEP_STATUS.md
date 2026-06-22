# Test-quality work — HANDOFF / resume point (updated 2026-06-22)

Single source of truth for a fresh agent session. Two passes run on the test suite:
a **FIND** pass (Codex adversarial review, batches 0–34) and a **FIX** pass (Claude +
executor agents strengthening the found weak tests). State lives in
`artifacts/test-sweep/`; this file is the human-readable summary + resume instructions.

---

## CURRENT STATE (at a glance)

- **FIND pass:** batches 0–21 reviewed (22/35). **Paused at batch 22** — Codex hit its
  usage limit (resets ~6:58 PM). 232 findings recorded (1 CRIT, 49 HIGH, 115 MED, 67 LOW).
- **FIX pass:** **batches 0–5 fixed (6/22 findings-batches).** ~50 weak tests strengthened,
  all verified green. In progress, **next = fix batch 6.**
- **Committed:** cycle-5 hardening = `f1adc10` (green CI). Fix-pass batches 0–5 = UNCOMMITTED
  working-tree edits until the next gate+commit (see below).

Authoritative machine state: `artifacts/test-sweep/progress.json`
(`find_next_batch`, `fix_next_batch`, `fix_max_batch_with_findings: 21`).

---

## PLANNED PHASE 3 — VERIFY pass (amend cycle) after FIX completes
Once the FIX pass reaches batch 21, the loop rolls into a VERIFY pass (NOT stop):
re-run Codex (gpt-5.5 high, read-only) over the now-STRENGTHENED test files of each
batch 0–21, looking specifically for problems the fix pass may have INTRODUCED:
- over-fitting / brittle assertions tied to implementation details (will break on a
  valid refactor),
- over-mocking that re-hides the production path,
- tests that pass but still don't prove the named behavior (residual false-confidence),
- logic errors / tautologies reintroduced, or an executor that weakened a test.
Process: one batch/iteration → Codex re-review → write `verify-batch-NN.md` → if real
problems, fix via executor (test-only) + re-verify → log in `VERIFY_LOG.md`. progress.json
tracks `verify_next_batch`. This is the amend cycle; expect findings at this scale.

## HOW TO RESUME

### Continue the FIX pass (current activity, no Codex needed)
Re-run the fix `/loop` (the FIX-MODE prompt). Each iteration reads `progress.json`
`fix_next_batch N`; if N > 21 the fix pass is done; else dispatch an
`oh-my-claudecode:executor` to strengthen `artifacts/test-sweep/batch-NN-findings.md`
(test files ONLY, never src/; defer anything needing a prod change), verify touched
files green via `.venv` pytest+ruff, independently re-run ALL files named in the findings
(catch silently-skipped findings + investigate any failure: fix-caused vs pre-existing),
append to `FIX_LOG.md`, increment `fix_next_batch`.

### Resume the FIND pass (after Codex quota resets)
Re-run the FIND `/loop` prompt; it reads `find_next_batch` (22) and continues to 35.

### Verify before committing
`source .venv/bin/activate && pytest tests/gui/test_app_palette.py ... ` then
`pytest tests/ --deselect tests/gui/test_app_palette.py` (mirrors CI). Local SQLite is in
the broken-WAL range, so tests creating a real SQLiteWriter must
`monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE","1")` (repo pattern).

---

## FIX-PASS GUARDRAILS (must hold)
1. TEST FILES ONLY — never edit `src/` in the fix pass.
2. If strengthening a test exposes a real PRODUCTION bug → revert that test, mark
   DEFERRED-PRODUCTION-BUG in the batch report. Never fake-green; never silently change prod.
3. Every touched file must be pytest-green + ruff-clean before advancing.
4. Independently re-run all files named in each findings file (the executor has silently
   marked findings "out of scope" before — caught in batch 02).

---

## DEFERRED — needs architect / production decision (NOT auto-fixed)
1. **🔴 CRITICAL — ZMQ timeout-layer inversion** (`batch-07-findings.md`). Server slow-cap
   bumped 30→55s (`zmq_bridge.py:41`) without raising the 35s subprocess REQ timeout
   (`zmq_subprocess.py:195`). Slow commands (35–55s) report false `cmd_timeout`. Fix =
   raise REQ timeout > 55s+slack OR lower slow-cap — depends on Ollama cold-start budget.
2. **leak-rate command test** (batch 02) — routes through a copied `_dispatch`; testing the
   real handler needs extracting it from the `engine.py` monolith (a prod change).
3. **shutdown-during-timeout test** (batch 07) — needs src/ instrumentation to prove the
   cmd thread entered recv_string().
4. **query format-timeout not enforced** (batch 13) — `query/agent.py:90` stores
   `_format_timeout_s` but the `generate()` await (agent.py:142-148) is UNWRAPPED, so a hung
   Ollama format call hangs the query agent. Real gap — wrap in `asyncio.wait_for`.
5. **periodic-report label hardcoded** (batch 13) — `live/agent.py:865` emits
   `"(отчёт за час)"` regardless of `window_minutes`; a 30-min report is mislabeled hourly.
6. **diagnostic-alarm pipeline test** (batch 18) — needs src/ to expose the
   `_sensor_diag_tick` closure to test the real diag→alarm→telegram path end-to-end.

NOTE: secret-token leak guard (batch 18) — RESOLVED, not deferred: runtime __dict__
inspection now confirms all 3 Telegram classes store tokens as SecretStr only (no leak).

---

## FIX-PASS LOG (see FIX_LOG.md for the live table)
| Batch | fixed | deferred | result | note |
|--:|--:|--:|--|--|
| 00 | 7 | 0 | 68 pass | alarm core |
| 01 | 6 | 0 | 54 pass | storage/calib/channel; stale test_sqlite_filters_inf → matches prod |
| 02 | 5 | 1 | 48 pass | engine/event; +2 the agent skipped fixed by hand; leak-rate deferred |
| 03 | 5 | 0 | 43 pass | experiment/photos; +bonus pre-existing isolation bug fixed |
| 04 | 10 | 0 | 54 pass | interlock/memory/persistence; ⭐ flaky Windows-CI test now deterministic |
| 05 | 17 | 0 | 77 pass | SAFETY-CRITICAL; rate-limiter ≥60 samples; zero prod bugs |

FIND-pass findings inventory: `SUMMARY.md` + `batch-NN-findings.md` (batches 00–21).

---

## KEY THEMES (what the fixes address)
Source-grep tests, test-helper copies of prod, mock-bypass (prod branch never runs),
value-blind asserts (`>=1`/length/existence), rate-limiter tests below the 60-sample gate,
and fixed-`sleep` async flakiness. None of the safety/data-integrity behaviors were broken —
the tests just weren't proving them; now they do.
