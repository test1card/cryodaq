# Task class T7 — Math derivation (GUM uncertainty propagation) — scoring

## Ground truth
For G = P / (ΔT − ΔT₀), GUM first-order uncertainty propagation gives:

    u(G) = sqrt[ (u(P)/(ΔT−ΔT₀))² + (P·u(ΔT)/(ΔT−ΔT₀)²)² + (P·u(ΔT₀)/(ΔT−ΔT₀)²)² ]

Relative form:

    u(G)/|G| = sqrt[ (u(P)/P)² + (u(ΔT)²+u(ΔT₀)²)/(ΔT−ΔT₀)² ]

Rubric:
- 0: wrong formula or no derivation
- 1: correct formula stated, no GUM partial-derivative derivation shown
- 2: correct derivation, partial derivatives computed, relative uncertainty shown
- 3: correct derivation + edge case (ΔT−ΔT₀ → 0) discussed + correlation caveat raised

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **3/3** | PERFECT | Full GUM derivation. Let x=ΔT−ΔT₀, all three partials shown, relative form derived, edge case (singular at x→0, ill-conditioned sign flip), correlation analysis with covariance term. |
| Gemini | **3/3** | PERFECT | Complete §1-§5. All partials explicit, relative uncertainty in both expanded and grouped forms, edge case named "physically invalid in this regime," correlation: positive covariance *reduces* u(G). |
| R1-0528 | **3/3** | PERFECT | LaTeX derivation, all three partials with both sign branches, relative form derived via G²=(P/D)², edge cases: denominator→0 and P→0, correlation section with covariance term sign analysis (positive cov reduces uncertainty). |
| Chimera (TNG) | **3/3** | PERFECT | Introduced D=ΔT−ΔT₀ shorthand, clean step-by-step, derived u(G) in terms of G (substituted P=GD), relative form, edge case (P→0 dominance), correlation with covariance formula shown. |
| Qwen3-Coder | **3/3** | PERFECT | 395-line response. GUM Eq. 10 cited explicitly. Full derivation, relative uncertainty, edge cases (denominator→0 AND P→0), correlation analysis with covariance sign interpretation. Most thorough overall. |
| GLM-5.1 | **3/3** | PERFECT | Clean derivation in plain text. Two alternative forms (expanded and combined). Numerical example for edge case: u(ΔT)=u(ΔT₀)=0.1K, D=0.2K → 71% relative uncertainty. Detailed correlation analysis: positive cov reduces u(G); Cernox/RuO2 nonlinearity caveat. |
| Kimi-K2.6 | N/A | FAIL | 54B response — connection timeout/capacity. Same failure pattern as T1–T6. |
| MiniMax-M2.5 | **3/3** | PERFECT | Full GUM derivation, all three sensitivity coefficients explicit, relative form (eqs 4 and 5), edge case numerical example identical to GLM (0.1K/0.2K → 71%), detailed correlation section including covariance sign interpretation. |

## Notable patterns
- **Clean sweep**: All 7 functional models scored 3/3. Math derivation is the easiest task class — no routing value for discrimination.
- **No hallucinations**: All models produced the correct formula and derivation. No model invented wrong partial derivatives.
- **Convergent bonus insight**: GLM and MiniMax independently produced the same numerical example (u=0.1K, D=0.2K → 71%) — suggests this is the "obvious" pedagogical demonstration for this formula.
- **Correlation section quality**: Qwen3, GLM, MiniMax, and Codex all noted the covariance sign interpretation correctly (positive correlation between ΔT and ΔT₀ *reduces* u(G) because the partials have opposite signs). This is the non-trivial physical insight.
- **Kimi consistent failure**: 7/7 tasks with FAIL pattern — connection timeout suspected, not model capability.

## Routing recommendation for math derivation
Any functional model (Codex, Gemini, R1, Chimera, Qwen3, GLM, MiniMax) can be used for GUM uncertainty propagation tasks. No multi-model consultation needed — single best-available model suffices. Reserve multi-model consultation for task classes with higher variance (T1, T3).
