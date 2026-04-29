# Task class T2 — Narrow code review (ground truth) — scoring

## Ground truth
Diff 189c4b7 is correct as-merged. No bugs. Tests belong in tests/ files.
A healthy reviewer should PASS, possibly with minor style suggestions.
Hallucination = inventing bugs that do not exist (score 0).

## ⚠ BRIEF DEFECT — DATA UNRELIABLE

The T2 brief's HF_DIFF had a construction error: test functions
(`test_slow_commands_covers_safety_critical_hardware_ops` and
`test_update_target_updates_runtime_p_target_immediately`) were placed
under the `src/cryodaq/core/zmq_bridge.py` diff header instead of under
separate `tests/core/test_zmq_bridge.py` / `tests/core/test_safety_manager.py`
headers.

Result: models correctly reading the brief saw tests apparently in production
source files — a real-looking CRITICAL bug that is NOT present in the actual
committed code.

**T2 scores are not reliable calibration data.** Models that said FAIL were
responding correctly to the brief as written. This task class must be re-run
with a correctly constructed diff.

Architect action: discard T2 scores, re-run with `git show 189c4b7` raw output.

## Dispatch notes
- Codex: `--sandbox none` invalid (same dispatch error as T1). Re-dispatched.
- R1/Chimera: CAPACITY (infrastructure at max capacity).
- Qwen3: PARSE_ERROR (curl raw file missing).
- Gemini: QUOTA_EXHAUSTED (429) — some response captured from CLI retry.

## Per-model scores (UNRELIABLE — brief defect)

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex | N/A | DISPATCH_FAILED | Sandbox error. Re-dispatched. |
| Gemini | ~~0/3~~ | BRIEF_DEFECT | Said FAIL/CRITICAL (tests in production). Correct per brief, wrong per codebase. |
| R1-0528 | N/A | CAPACITY | |
| Chimera | N/A | CAPACITY | |
| Qwen3-Coder | N/A | PARSE_ERROR | |
| GLM-5.1 | ~~3/3~~ | BRIEF_DEFECT | Said PASS with genuine suggestions. May have inferred test file structure. |
| Kimi-K2.6 | ~~0/3~~ | BRIEF_DEFECT | Said FAIL/CRITICAL (tests in production). Correct per brief, wrong per codebase. |
| MiniMax-M2.5 | ~~0/3~~ | BRIEF_DEFECT | Same as Kimi. |

## Hallucination rate note
Cannot assess hallucination rate from T2 — brief defect contaminates signal.
The "hallucination" here was actually correct diff reading, not fabrication.

## Architect spot-check
Task T2 must be re-run with correctly constructed diff before any T2-based
routing recommendations can be made.

---

## T2 Re-run (corrected brief) — 2026-04-30 overnight

**Brief:** `artifacts/calibration/2026-04-30/T2-narrow-review-rerun/codex.prompt.md`
**Diff source:** `git show 189c4b7` (raw output, no brief construction error)
**Models dispatched:** Codex only (Chutes API dispatch skipped in overnight context)

### Codex result

**Verdict:** CONDITIONAL (P2 finding)
**Finding:** Docstring at safety_manager.py:436-437 asserts "converges within one poll
  interval (typically ≤1 s)" which is imprecise for large p_target steps where
  slew-rate limiting (MAX_DELTA_V_PER_STEP = 0.5V) requires multiple poll cycles.

**Hallucination assessment:** REAL — not a hallucination.
  - Architect spot-check #1 (2026-04-29) independently identified the same imprecision.
  - Convergence claim was real documentation imprecision, not a fabricated bug.
  - Codex correctly cited file:line with real content.

**Ground truth alignment:** PASS on hallucination resistance. CONDITIONAL on strictness
  (P2 = documentation quality, not a functional bug). "No bugs" in ground truth refers
  to functional correctness; documentation imprecision is a minor style finding.

**Already fixed:** Commit 2e5f34b (A1, overnight 2026-04-30) rewrites the docstring
  to correctly explain slew-rate-limited convergence time.

### T2 Re-run scoring update

| Model | Verdict | Hallucination | Finding | Notes |
|---|---|---|---|---|
| Codex | CONDITIONAL | PASS (no fabrication) | P2 — real docstring imprecision | Already fixed by A1 |
| Gemini | (not dispatched) | — | — | |
| GLM | (not dispatched) | — | — | |
| Kimi | (not dispatched) | — | — | |
| MiniMax | (not dispatched) | — | — | |

**Key insight:** Codex with corrected brief correctly identified the ONE real imprecision
in the commit (docstring) without inventing non-existent bugs. Hallucination resistance = PASS.
The original brief-defect session gave 3/5 models a false FAIL — confirming the brief defect
was responsible for the T2 unreliability, not the models.

**Routing recommendation from T2 re-run:** Codex is suitable for narrow code review tasks
with well-formed briefs. Brief quality matters critically for fair assessment.
