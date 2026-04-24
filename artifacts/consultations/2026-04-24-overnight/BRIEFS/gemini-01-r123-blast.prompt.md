Model: gemini-2.5-pro

# Blast-radius analysis — three repair options for b2b4fb5

## Mission

Commit `b2b4fb5` introduced a startup-probe that races with ipc://
engine bind. Repair options exist. Your job is not to pick the
"smartest" option — it is to map the blast radius of each:

- Which files and behaviors change outside `diag_zmq_b1_capture.py`?
- Which second-order ripples land in other diag tools, tests,
  launcher, docs?
- Which choice least constrains the future B1 root-cause
  investigation (still open: H4 shared-Context, H5 engine REP state
  machine)?

No preference is signaled. Read the evidence. Produce a table.

## Context files (use your 1M context generously)

- `docs/decisions/2026-04-24-b2b4fb5-investigation.md`
- `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py`
- `src/cryodaq/core/zmq_bridge.py`
- `src/cryodaq/core/zmq_subprocess.py`
- `src/cryodaq/core/zmq_transport.py`
- `src/cryodaq/gui/zmq_client.py`
- `tools/diag_zmq_*.py` (all 5 tools; each uses `ZmqBridge` and
  could be affected)
- `tests/core/test_zmq_*.py` (all; behavioral contracts for bridge)
- `tests/tools/test_diag_zmq_b1_capture.py` (the test that b2b4fb5
  added to)
- `docs/bug_B1_zmq_idle_death_handoff.md`
- `src/cryodaq/launcher.py` (imports `ZmqBridge`, may depend on
  `start()` semantics)

## The three options (alphabetical, equal space)

### R1 — Bounded-backoff retry inside the probe

Modify `_validate_bridge_startup()` in `tools/diag_zmq_b1_capture.py`
only: retry the `safety_status` command up to N times with 200-ms
spacing before raising. Everything else in the codebase unchanged.

### R2 — Move readiness into `ZmqBridge.start()`

Change `ZmqBridge.start()` in `src/cryodaq/gui/zmq_client.py` so it
blocks until the subprocess reports a successful first REQ-REP
round-trip, then returns. The tool's probe becomes just
`is_alive()`.

### R3 — Revert b2b4fb5

Delete `_validate_bridge_startup()` and its tests. Tool returns to
pre-2026-04-23 behavior.

## Specific questions

1. Which option has the smallest blast radius — i.e., the fewest
   files and behaviors changed outside `tools/diag_zmq_b1_capture.py`
   itself?
2. For each option, what second-order changes ripple into:
   - other `tools/diag_zmq_*.py` tools?
   - tests in `tests/core/test_zmq_*.py` and `tests/tools/`?
   - `src/cryodaq/launcher.py`?
   - docs (`docs/bug_B1_*`, `CHANGELOG.md`, `CLAUDE.md`,
     `PROJECT_STATUS.md`)?
3. Considering future B1 work:
   - **H4** (shared-Context) — will we want to swap Contexts in
     the bridge subprocess; does any option block that?
   - **H5** (engine REP state machine) — will we want to
     instrument / intercept REP-side handling; does any option
     interfere?
4. Load-bearing assumptions anywhere in the repo that any of the
   three options might silently break (e.g., tests that assert
   `start()` returns within X seconds, launcher timeouts, CI
   budgets)?

## Output format

- First line verbatim: `Model: gemini-2.5-pro`
- Primary deliverable: a single markdown table with columns:
  `Option | First-order impact | Second-order ripple (list) |
  B1-investigation interference | Overall verdict`
- After the table: ≤ 500 words commentary highlighting the single
  most important finding
- Total ≤ 1500 words

## Scope fence

- Do not relitigate whether b2b4fb5 is the cause of the IV.7
  misattribution — settled.
- Do not recommend a fourth option; the architect will consider
  alternatives based on Codex-01's output, not yours.
- Do not audit unrelated code quality (naming, style, comments).

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-01-r123-blast.response.md`
