# Task class T3 — Architectural drift detection (ground truth) — scoring

## Ground truth
No drift exists. Docstring says "delayed-update" (p_target updated immediately,
hardware follows on next poll cycle). Implementation is delayed-update. Test asserts
delayed-update. All three are consistent.

Rubric:
- 0: invented major drift that does not exist
- 1: invented minor drift that does not exist
- 2: correctly reports "no drift found"
- 3: correctly reports "no drift" + adds one valid observation

## Surprising cross-model finding
**3 of 4 responsive models (Codex, Kimi, Qwen3) flagged the slew-rate convergence
concern:** Docstring says "within one poll interval (typically ≤1 s)" but
MAX_DELTA_V_PER_STEP = 0.5V means large p_target changes require multiple cycles.
The test docstring also says "converges on the next poll cycle" without the "typically" hedge.
This is a real architectural observation. Whether this constitutes DRIFT or a valid note
is an ARCHITECT DECISION NEEDED item.

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **1.5/3** | ARCHITECT_NEEDED | DRIFT. Found slew-rate issue + compliance skip with specific file:line refs. Real observations but declared DRIFT rather than CONSISTENT+note. |
| Gemini | **2/3** | CONSISTENT | 429 then retried — got terse CONSISTENT response after backoff. |
| R1-0528 | N/A | CAPACITY | |
| Chimera | N/A | CAPACITY | |
| Qwen3-Coder | **1.5/3** | ARCHITECT_NEEDED | DRIFT. Docstring says "hardware voltage NOT changed here" — Qwen3 argues hardware IS changed (by concurrent loop). Linguistic ambiguity is real but interpreted as drift. |
| GLM-5.1 | **3/3** | CONSISTENT | CONSISTENT + valid observation: "test does not explicitly assert that no SCPI write was issued." Genuinely useful improvement. |
| Kimi-K2.6 | **1.5/3** | ARCHITECT_NEEDED | DRIFT. Found same slew-rate convergence issue as Codex. Valid observation, wrong verdict. Also noted test docstring imprecision. |
| MiniMax-M2.5 | **2/3** | CONSISTENT | CONSISTENT. Brief but correct. |

## Notable patterns
- **Convergent valid finding**: Codex + Kimi (+ Qwen3 different angle) all found the
  "converges within one poll interval" claim is oversimplified given slew-rate limiter.
  This may be a genuine docstring precision issue to fix.
- **GLM**: Only model to give clean 3/3 — CONSISTENT with actionable test improvement.
- **Surprising**: Gemini (post-retry) and MiniMax gave cleaner verdicts than the
  high-reasoning models (Codex, Qwen3) which over-read the drift.
- **R1/Chimera**: Capacity failures — missing data.

## Architect decisions needed
1. Is "within one poll interval (typically ≤1 s)" acceptable given slew-rate limiter?
   If a large p_target change (e.g., 0→5W) takes many cycles, the docstring is misleading.
2. Should the test docstring say "converges on the next poll cycle" (current) or
   "begins converging on the next poll cycle"?
3. Should the test add `k._transport.write.assert_not_called()` per GLM suggestion?
