# Test-quality work — HANDOFF / resume point (updated 2026-06-22)

Single source of truth for a fresh agent session. Two passes run on the test suite:
a **FIND** pass (Codex adversarial review, batches 0–34) and a **FIX** pass (Claude +
executor agents strengthening the found weak tests). State lives in
`artifacts/test-sweep/`; this file is the human-readable summary + resume instructions.

---

## CURRENT STATE (at a glance)

- **FIND pass:** batches 0–21 reviewed (22/35). **Paused at batch 22** — Codex hit its
  usage limit. 232 findings recorded (1 CRIT, 49 HIGH, 115 MED, 67 LOW).
- **FIX pass:** ✅ **COMPLETE — batches 0–21 all fixed & verified green** (~290 weak tests
  strengthened). Final clean CI-mirror gate (2026-06-23): **3248 pass / 0 fail / 3 skip**.
- **VERIFY pass (mode now `fix-verify`):** Codex amend-cycle review of the strengthened files,
  `verify_next_batch` 0→21. **This is the current activity.**
- **Committed (local, push held):** batches 0-5 `64590b0`, 6-10 `c548d34`, 11-15 `c805dcf`,
  16-20 `ee93591`, 21 + fix-pass-complete marker = latest commit.

Authoritative machine state: `artifacts/test-sweep/progress.json`
(`mode`, `verify_next_batch`, `fix_next_batch`, `find_next_batch`).

### ⚠️ GATE ENV CAVEATS (this machine — learned 2026-06-23, avoid re-tripping)
The CI-mirror full gate is `pytest tests/gui/test_app_palette.py` then
`pytest tests/ --deselect tests/gui/test_app_palette.py --timeout=120 --timeout-method=thread`.
Two LOCAL-ONLY hazards that produce false failures (CI is clean — fresh env, no ollama):
1. **Do NOT export `CRYODAQ_ALLOW_BROKEN_SQLITE=1` for the whole-suite gate.** It bypasses the
   broken-sqlite startup gate, so `tests/core/test_f23_f24_f25_misc.py`'s 5 gate-assertion
   tests fail (they expect a raise). Tests that need the flag set it per-test via
   `monkeypatch.setenv`. Run the full gate WITHOUT the global var.
2. **`tests/reporting/test_report_generator.py` hangs when Ollama is running locally** +
   local `agent.yaml` has `slices.c_campaign_report: true`. Its `generate()` tests reach the
   real `_call_ollama_sync` (live `urllib.urlopen` → localhost:11434) and block until the
   thread-timeout kills the session. Not ollama-marked, so `-m "not ollama"` won't skip it.
   For a local gate, `--deselect tests/reporting/test_report_generator.py` (unrelated to the
   sweep; CI passes it because ollama is down → ConnectionRefused → graceful None fallback).

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

7. **alarm_v2 status/ack command-shape tests** (batch 00 VERIFY, F3/F4) — `test_alarm_v2_status_shape`
   re-implements the engine's serialization dict inside the test and asserts on its own
   reconstruction (tautology); `test_alarm_v2_ack` tests `AlarmStateManager.acknowledge()`
   directly. Both miss the real command path `_handle_gui_command` `alarm_v2_status` /
   `alarm_v2_ack` (engine.py:2347 / 2392) — a nested closure inside the engine bootstrap.
   Testing the real path needs extracting the closure (prod change), same monolith pattern
   as items 2 & 6. NOT auto-fixed in the verify pass.

8. **ZMQ test-infra seams** (batch 07 VERIFY) — three test-only-impossible items needing src
   seams: (a) `test_engine_commands_keep_inner_timeouts_wired` — `_LOG_GET_TIMEOUT_S` /
   `_EXPERIMENT_STATUS_TIMEOUT_S` feed `asyncio.wait_for` inside engine command handlers; a
   behavioral test needs a live engine+storage or an injectable timeout seam (kept as a
   constant-existence check meanwhile). (b) real-timeout flake tests
   (`test_cmd_timeout_emits_warning`, `test_cmd_socket_recovers_after_timeout`,
   `test_subprocess_sends_heartbeat`, `test_heartbeat_has_timestamp`,
   `test_bridge_subprocess_receives_published_readings`) wait on the hardcoded 35s REQ timeout /
   5s heartbeat / slow-joiner deadlines — deterministic only with src-injectable timeouts/intervals;
   "adequate-slack" for now. (c) `test_overflow_counter_emits_warning_on_queue_full` — warning
   emission is a closure inside `zmq_bridge_main`; full determinism needs a src warning-emit helper.
   None block correctness; all are testability improvements coupled to the same ZMQ-layer refactor
   as item 1.

9. **RAGAdapter defensive sort** (batch 14 VERIFY, minor) — `KnowledgeQueryResult` schema docstring
   promises `hits` "sorted ascending by distance", but `RAGAdapter.search`
   (query/adapters/rag_adapter.py) does NOT sort — it preserves the searcher's order (LanceDB returns
   ascending-by-distance) and only applies a distance cutoff. The contract holds in practice via
   LanceDB; a defensive `sorted(hits, key=distance)` in the adapter would make the documented
   guarantee hold for any searcher. Test reframed honestly to assert "preserves searcher order +
   distance cutoff" (not "sorts"). Prod hardening only — not a correctness bug.

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
