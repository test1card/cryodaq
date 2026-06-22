# Production-fix brief — for a SEPARATE CC session (worktree-isolated)

This is the companion workstream to the test-quality sweep (see TEST_SWEEP_STATUS.md).
The sweep is **test-only on `master`**. THIS brief is for fixing the **production**
problems it surfaced, in an **isolated git worktree on its own branch**, so the two
sessions never touch the same working tree / git index.

## Setup (run once, from the main repo)
```
git worktree add ../cryodaq-prodfix -b prod-fixes        # branches from current master
cd ../cryodaq-prodfix && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"
```
Then run the second CC session with cwd = ../cryodaq-prodfix. It owns `src/` + the
specific deferred tests below. The sweep session stays on `master` and will NOT touch
these. Merge `prod-fixes` → master when both are done (or open a PR).

## Hard rules for the prod-fix session
- One commit per fix; each fix must (a) make its un-deferred test assert the CORRECT
  behavior and pass, and (b) keep the full suite green (CI-mirroring gate before commit).
- Local SQLite is in the broken-WAL range → tests creating a real SQLiteWriter need
  `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE","1")`.
- Anything that's a genuine design/value call (timeout magnitudes) — propose, then let
  Vladimir (architect) confirm the number before finalizing.

---

## REAL PRODUCTION BUGS (fix these first)

### 1. 🔴 CRITICAL — ZMQ timeout-layer inversion
- Where: `src/cryodaq/core/zmq_bridge.py:41` (`HANDLER_TIMEOUT_SLOW_S = 55.0`) vs
  `src/cryodaq/core/zmq_subprocess.py:195-196` (REQ `RCVTIMEO/SNDTIMEO = 35000`).
- Bug: server slow-cap was bumped 30→55s without raising the 35s subprocess REQ timeout,
  so the documented ordering (helper 25s < server 30s < REQ 35s < GUI future) inverted.
  A 35–55s command (Ollama cold-start / experiment finalize / report) trips the REQ
  timeout first → GUI sees `cmd_timeout` while the engine is still working.
- Recommended fix (confirm values with architect): raise REQ RCVTIMEO/SNDTIMEO to
  `60000` (55s cap + 5s slack) and ensure the GUI future wait `_CMD_REPLY_TIMEOUT_S`
  exceeds that; update the comment at zmq_subprocess.py:188-194 with the new tiering.
- Un-defer test: `tests/core/test_zmq_bridge.py:319` — make it assert
  `SUBPROCESS_REQ_TIMEOUT_S > HANDLER_TIMEOUT_SLOW_S` via imported constants (behavioral),
  not a "35000" grep.

### 2. query format-timeout never fires
- Where: `src/cryodaq/agents/assistant/query/agent.py:142-148` awaits `generate()`
  UNWRAPPED, though `agent.py:90` stores `_format_timeout_s`.
- Bug: a hung Ollama format call hangs the query agent indefinitely.
- Fix: wrap the format `generate()` await in `asyncio.wait_for(..., _format_timeout_s)`
  with a bounded fallback.
- Un-defer test: `tests/agents/assistant/test_query_agent.py:359` — hang generate under a
  short timeout, assert bounded fallback.

### 3. periodic-report label hardcoded (minor correctness)
- Where: `src/cryodaq/agents/assistant/live/agent.py:865` emits `"(отчёт за час)"`
  regardless of `window_minutes`.
- Fix: derive the suffix from `window_minutes` (e.g. "за 30 минут" / "за час" / "за 2 часа").
- Test: `tests/agents/assistant/test_periodic_report_handler.py` — assert a 30-min report
  uses a 30-min label.

---

## TESTABILITY REFACTORS (production untestable-as-written; small, safe extractions)
These aren't bugs — production works — but the test can't reach the real path without a
src/ refactor. Each: extract a thin importable helper, then un-defer the test.
4. leak-rate command — extract dispatch from the `engine.py` monolith into an importable
   handler. Test: `tests/core/test_engine_leak_rate_command.py` (the `test_leak_rate_*`).
5. engine shutdown-drain — extract the drain block to a helper.
   Test: `tests/sinks/test_engine_shutdown_drains_dispatch.py`.
6. summary-metadata export — expose the finalize/export construction.
   Test: `tests/sinks/test_engine_summary_metadata_key.py`.
7. diagnostic→alarm→telegram — expose `_sensor_diag_tick` closure.
   Test: `tests/integration/test_diagnostic_alarm_pipeline.py`.
8. ReplayEngine PUB readiness — add a ready-signal/event for deterministic tests.
   Test: `tests/replay_engine/test_replay_predictor.py:316`.

NOTE: items 4-8 are the test-helper-copies / hand-built / sleep-handshake DEFERRED entries
from FIX_LOG.md. The reverted/weak tests for them are still in the tree (passing as-is);
the prod-fix session un-defers each as it lands the extraction.
