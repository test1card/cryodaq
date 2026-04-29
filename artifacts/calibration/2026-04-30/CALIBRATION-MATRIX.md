# Calibration Matrix — 2026-04-30
# 7 task classes × 8 models — empirical scoring

## Score legend
- **3/3** — PERFECT: meets all rubric criteria including edge cases / arc / safety insights
- **2/3** — ADEQUATE: correct core answer, missing depth or one key criterion
- **1.5/3** — BORDERLINE: partial credit (half-point rubric)
- **1/3** — PARTIAL: correct direction, wrong mechanism or shallow
- **0/3** — WRONG: hallucinated, wrong formula, or invented bugs
- **N/A** — CAPACITY / QUOTA: model unavailable during wave (request-time failure)
- **INVALID** — Task brief had a construction defect; scores discarded

## Task class definitions
| ID | Name | Ground truth anchor |
|---|---|---|
| T1 | Bug hypothesis | asyncio.wait_for(recv()) + pyzmq reactor state = B1 root cause |
| T2 | Narrow code review | ⚠ INVALID — diff brief defect placed tests in production module header |
| T3 | Arch drift review | HF1 docstring is CONSISTENT (delayed-update design); overcalling is penalized |
| T4 | Spec design | RateEstimator timestamp bug (F23) — full fix spec required |
| T5 | Code gen | F23 immediate-update helper on Keithley side |
| T6 | Long digest | 96KB CHANGELOG → 500-word narrative arc summary |
| T7 | Math derivation | GUM uncertainty propagation for G = P/(ΔT−ΔT₀) |

## Score matrix (raw)

| Model | T1 | T2 | T3 | T4 | T5 | T6 | T7 | Scored | Total | Pct |
|---|---|---|---|---|---|---|---|---|---|---|
| Codex (gpt-5.5) | 3 | — | 1.5 | 3 | 3 | 3 | 3 | 6/6 | 16.5 | **91.7%** |
| GLM-5.1 | — | — | 3 | 3 | 3 | 2 | 3 | 5/5 | 14 | **93.3%** |
| MiniMax-M2.5 | 2 | — | 2 | 2 | 3 | 2 | 3 | 6/6 | 14 | **77.8%** |
| Gemini | — | — | 2 | 3 | 2 | 2 | 3 | 5/5 | 12 | **80.0%** |
| Qwen3-Coder | 1 | — | 1.5 | 2 | 3 | 3 | 3 | 6/6 | 13.5 | **75.0%** |
| Chimera (TNG) | 2 | — | — | — | — | 2 | 3 | 3/3 | 7 | **77.8%** |
| R1-0528 | 1 | — | — | 2 | — | 2 | 3 | 4/4 | 8 | **66.7%** |
| Kimi-K2.6 | — | — | 1.5 | 3 | — | — | — | 2/2 | 4.5 | **75.0%** |

Notes:
- `—` = N/A (capacity/quota failure during that wave)
- T2 scores discarded for all models; column excluded from totals
- "Scored" = tasks answered / tasks attempted (excluding T2 and N/A cells)
- "Pct" = Total / (Scored × 3) × 100

## Per-task score distribution

| Task | Codex | GLM | MiniMax | Gemini | Qwen3 | Chimera | R1 | Kimi | μ (valid) |
|---|---|---|---|---|---|---|---|---|---|
| T1 bug-hyp | **3** | — | 2 | — | 1 | 2 | 1 | — | 1.8 |
| T2 review | INVALID | INVALID | INVALID | INVALID | INVALID | INVALID | INVALID | INVALID | — |
| T3 arch-drift | 1.5 | **3** | 2 | 2 | 1.5 | — | — | 1.5 | 1.9 |
| T4 spec-design | **3** | **3** | 2 | **3** | 2 | — | 2 | **3** | 2.6 |
| T5 code-gen | **3** | **3** | **3** | 2 | **3** | — | — | — | 2.8 |
| T6 long-digest | **3** | 2 | 2 | 2 | **3** | 2 | 2 | — | 2.3 |
| T7 math-deriv | **3** | **3** | **3** | **3** | **3** | **3** | **3** | — | 3.0 |

## Routing rules derived from this matrix

### Route to Codex (gpt-5.5) when:
- Bug root-cause hypothesis on asyncio/ZMQ/driver code (T1: 3/3, only model to identify pyzmq reactor state)
- Long digest requiring arc identification (T6: 3/3, self-verified word count)
- Code generation with safety-critical locking analysis (T5: 3/3, uniquely flagged _last_v locking requirement)
- **Avoid for**: conservative consistency review (T3: 1.5/3 — over-reads slew-rate "DRIFT")

### Route to GLM-5.1 when:
- Architecture consistency review / code review requiring conservative judgment (T3: 3/3 — only model with clean CONSISTENT verdict)
- Any spec or code task where unique domain insights are needed (T4: monotonic-epoch mismatch; T5: cleanest Keithley separation-of-concerns design)
- **Best overall**: highest percentage on scored tasks (93.3%) with zero capacity failures after T1

### Route to Gemini when:
- Spec design (T4: 3/3)
- Tasks where quota is available — watch for 429 capacity failures
- **Avoid for**: tasks requiring hard safety stops (T5: fabricated `getattr(runtime, "last_i")`)

### Route to Qwen3-Coder when:
- Narrative synthesis (T6: 3/3 — named meta-arc explicitly: "safety maturation... architectural consistency")
- Math derivation (T7: 3/3 — most thorough response at 395 lines)
- Code generation (T5: 3/3)
- **Avoid for**: bug hypothesis (T1: 1/3 — "wrong frame," analyzed CancelledError handler quality instead of wait_for pattern)

### Route to MiniMax-M2.5 when:
- Reliable mid-tier fallback when primary models are at capacity
- Code generation (T5: 3/3)
- **Characteristics**: consistent 2-3 scores, no catastrophic failures, no unique insights

### Route to R1-0528 when:
- Math derivation (T7: 3/3)
- **Avoid for**: sessions requiring high availability — heavy capacity constraints observed in T3/T5 waves

### Route to Chimera (TNG) when:
- Math tasks (T7: 3/3)
- **Limitations**: only 3 scored tasks — insufficient data for task-specific routing; treat as fallback

### Route to Kimi-K2.6 when:
- Short prompts only — consistent connection failure on 96KB+ prompts (T6/T7 waves)
- Spec design when available (T4: 3/3 with unique shared-instance invariant finding)
- **Avoid for**: long-context tasks — 7/7 consistent failure pattern

## Multi-model consultation guidance

| Use case | Recommended models | Rationale |
|---|---|---|
| Bug diagnosis (T1-class) | Codex + Chimera + MiniMax | Only high scorers on T1; GLM/Gemini had N/A |
| Arch review (T3-class) | GLM alone or GLM + Gemini | High-reasoning models (Codex, Qwen3, Kimi) systematically over-flag |
| Spec design (T4-class) | Codex + GLM + Gemini | All 3/3; each brings unique insights |
| Code gen (T5-class) | Codex + GLM + MiniMax | All 3/3; Codex adds locking analysis, GLM adds architecture clarity |
| Long digest (T6-class) | Codex + Qwen3 | Only two models at 3/3; both name meta-arc explicitly |
| Math derivation (T7-class) | Any single model | Clean sweep — no discrimination value |

## Capacity failure summary

| Model | T1 | T2 | T3 | T4 | T5 | T6 | T7 | Failure rate |
|---|---|---|---|---|---|---|---|---|
| Kimi-K2.6 | FAIL | — | OK | OK | FAIL | FAIL | FAIL | 4/6 non-T2 = 67% |
| R1-0528 | OK | — | FAIL | OK | FAIL | OK | OK | 2/6 = 33% |
| Chimera | OK | — | FAIL | FAIL | FAIL | OK | OK | 3/6 = 50% |
| GLM-5.1 | FAIL | — | OK | OK | OK | OK | OK | 1/6 = 17% |
| Gemini | FAIL | — | OK* | OK | OK | OK | OK | 1/6 = 17% |
| Codex | OK | — | OK | OK | OK | OK | OK | 0/6 = 0% |
| Qwen3-Coder | OK | — | OK | OK | OK | OK | OK | 0/6 = 0% |
| MiniMax-M2.5 | OK | — | OK | OK | OK | OK | OK | 0/6 = 0% |

*Gemini T3: got terse response after 429 backoff — scored 2/3.
