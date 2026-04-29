# Task class T4 — Spec design (generative) — scoring

## Rubric
- 0: missing key sections, vague, or wrong scope
- 1: covers basics but lacks acceptance criteria or test plan
- 2: complete spec, adequate but generic
- 3: complete + demonstrates deep understanding (Reading.timestamp is datetime → .timestamp(); edge cases; RateEstimator patterns)

## Key depth indicators verified
All 6 functional models correctly identified:
- `reading.timestamp.timestamp()` as the fix (not just "use reading timestamp")
- That `reading.timestamp` is a `datetime` object requiring `.timestamp()` conversion
- Specific location: `_collect_loop` in safety_manager.py

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **3/3** | DEEP | All §0-§7. 5 edge cases: late readings, clock skew, out-of-order, naive datetimes, non-K units. Hard stops on out-of-order readings and existing tests. |
| Gemini | **3/3** | DEEP | Real response (quota cleared). Complete §0-§7. Hard stop "STOP if RateEstimator is used by other components that pass monotonic() — mixing catastrophically breaks sliding window." Queue burst test design is excellent. |
| R1-0528 | **2/3** | ADEQUATE | Correct fix with file:line ref. "Clock Skew Resilience" test case. But thinner section structure (acceptance criteria count=1). |
| Chimera | N/A | CAPACITY | |
| Qwen3-Coder | **2/3** | ADEQUATE | Correct fix. §0 present. Noted "POSIX timestamp (float, seconds since epoch)" — shows datetime understanding. Limited edge cases. |
| GLM-5.1 | **3/3** | DEEP | Unique insight: "monotonic clock has arbitrary epoch unrelated to wall-clock — subtraction is meaningless across clock domains." Backlog + out-of-order edge cases. Also noted `_latest` should also use measurement timestamp for consistency. |
| Kimi-K2.6 | **3/3** | DEEP | "Unifying timestamps from monotonic to epoch is safe ONLY if no other caller pushes monotonic values into same instance — must verify before merge." Late readings, future skew (→ purges buffer), backlog compression as rate spike. |
| MiniMax-M2.5 | **2/3** | ADEQUATE | Complete structure. 4 acceptance criteria. Late readings mentioned. No clock skew or invariant analysis. Adequate but generic. |

## Notable patterns
- **High scores across the board**: T4 had the best distribution of any task class so far.
- **Unique contributions**: GLM (monotonic epoch domain mismatch), Kimi (shared instance invariant), Gemini (monotonic mixing hard stop), Codex (naive datetime edge case).
- **R1 weakness**: Correct direction but thinner spec structure — lacks the depth of Codex/GLM/Kimi.
- **No hallucinations** in any functional response — all correctly identified the bug and fix.

## Recommended for skill routing
T4 (spec design): GLM, Kimi, Codex, Gemini all performed at 3/3. All are good choices for spec-writing tasks. Kimi and GLM brought unique safety insights.
