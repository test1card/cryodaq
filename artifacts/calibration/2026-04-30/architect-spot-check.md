# Architect Spot-Check — 2026-04-30 Calibration

## Purpose
Cells requiring architect review: scores of 0, high variance across models on same task,
or surprising results that challenge prior assumptions.

## No-zero finding
**No model scored 0/3 on any task it attempted.** Lowest scores:
- R1/Qwen3 on T1: 1/3 (wrong mechanism, not hallucination)
- Codex/Qwen3/Kimi on T3: 1.5/3 (over-flagged consistency; found a real issue, wrong verdict)

Interpretation: all tested models have sufficient baseline competence. Routing failure
modes are mechanism errors and wrong frames, not catastrophic hallucination on these task types.

---

## HIGH VARIANCE CELLS

### T1 Bug Hypothesis — spread 3→1 (range: 2 points)
| Codex | Chimera | MiniMax | R1 | Qwen3 |
|---|---|---|---|---|
| 3/3 | 2/3 | 2/3 | 1/3 | 1/3 |

**Why the variance matters:** This is the task class most relevant to production incident
response. Only Codex identified the pyzmq reactor state mechanism. R1 and Qwen3 analyzed
adjacent code (CancelledError handler, TCP keepalive) rather than the wait_for pattern itself.

**Architect decision needed:**
- Is Codex the sole reliable model for asyncio/ZMQ bug diagnosis? Or is the T1 brief
  too narrow to generalize? (Only 1 data point per model — consider re-running with a
  different asyncio bug for validation.)

---

### T3 Arch Drift Review — systematic high-reasoner overreach
| GLM | Gemini | MiniMax | Codex | Qwen3 | Kimi |
|---|---|---|---|---|---|
| 3/3 | 2/3 | 2/3 | 1.5/3 | 1.5/3 | 1.5/3 |

**Pattern:** High-reasoning models (Codex gpt-5.5 high-effort, Qwen3, Kimi) all flagged
"slew-rate convergence oversimplification" as DRIFT. GLM alone produced clean CONSISTENT.

**The underlying finding is real:** The docstring says "converges within one poll interval
(typically ≤1 s)" but the slew-rate limiter can extend convergence over multiple polls.
Three independent models flagged this independently. This may be a genuine docstring
precision issue, not a model hallucination.

**Architect decision needed:**
1. Is the "typically ≤1 s" claim in the update_target docstring accurate or does the
   slew limiter make it misleading?
2. If misleading: fix the docstring (small scope, assign to next batch)
3. If accurate: note in routing rules that Codex/Qwen3/Kimi over-read in T3-class tasks

---

### T4 Spec Design — Kimi 3/3 despite long-prompt failure everywhere else
Kimi scored 3/3 on T4 (RateEstimator spec) but failed 4/6 other task classes.

**Observation:** T4 prompt was medium-length (not 96KB). Kimi failures correlate with
long prompts (T6=96KB) and wave timing (capacity). T4 success is consistent with Kimi
being capable but connection-unstable on long dispatches.

**No action needed** — confirm Kimi routing: "short prompts only, spec-class tasks."

---

## INVALIDATED TASK CLASS

### T2 Narrow Code Review — brief defect
**Defect:** HF_DIFF header placed test functions under `src/cryodaq/core/zmq_bridge.py`
instead of `tests/core/test_zmq_bridge.py`. All models that read the brief correctly saw
apparent tests-in-production — a real-looking CRITICAL that doesn't exist in the codebase.

**Action required:** Re-run T2 with `git show 189c4b7` raw diff output as the brief.
This is the only task class with no valid calibration data.

**Affected models for re-run:** Codex, Gemini, GLM, Kimi, MiniMax (R1/Chimera/Qwen3 had
capacity failures during the T2 wave and didn't produce scored responses anyway).

---

## T7 MATH DERIVATION — clean sweep (low priority)
All 7 functional models scored 3/3. No discrimination value. Math derivation tasks need
no multi-model consultation — single best-available model suffices.

**Notable convergent finding:** GLM and MiniMax independently produced the same numerical
example: u(ΔT)=u(ΔT₀)=0.1K, D=0.2K → 71% relative uncertainty. Both also noted that
positive correlation between ΔT and ΔT₀ *reduces* u(G) because the sensitivity coefficients
have opposite signs. This is the correct physical insight and appears to be the canonical
pedagogical demonstration for this formula.

---

## CAPACITY FAILURE REVIEW

### Kimi-K2.6: 4/6 failure rate — likely timeout not capacity
All Kimi failures show 54-107B response (connection dropped mid-transfer or on empty
response). T3 prompt was ~2KB (succeeded), T6 was 96KB (failed), T7 was ~1.2KB (failed).
The size-failure correlation is not clean. Likely infrastructure instability, not context
limit. No routing fix available without retry logic in the dispatch script.

### R1-0528 and Chimera: 33-50% failure rate
Both had consistent capacity failures on T3 and T5 waves (daytime UTC). These waves ran
approximately 2-3 hours after T1 (which they successfully answered). Suggests session-
level capacity throttling, not permanent unavailability.

**Architect recommendation:** For production multi-model dispatch, add a 30-minute
inter-wave delay or use Chutes retry logic for R1/Chimera.

---

## SUMMARY ACTIONS FOR ARCHITECT

| Priority | Action | Scope |
|---|---|---|
| HIGH | Re-run T2 with correct git diff | T2 re-run brief, same 8-model dispatch |
| MEDIUM | Evaluate T3 docstring precision finding | update_target "≤1 s" claim vs slew limiter |
| MEDIUM | Validate T1 routing (Codex-only for bug-hyp) | Run second asyncio bug scenario |
| LOW | Add retry/delay to Chutes dispatch for R1/Chimera | dispatch script hardening |
| LOW | Kimi connection investigation | Chutes support or timeout tuning |
