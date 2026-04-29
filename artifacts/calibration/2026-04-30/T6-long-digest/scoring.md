# Task class T6 — Long document digest (generative) — scoring

## Rubric
- 0: cherry-picks single release, ignores narrative arc
- 1: accurate but list-format, no narrative
- 2: 500-word narrative covering major themes
- 3: 500-word narrative + identifies meta-arc (productionization: bug closure → UI maturation → safety hardening) + accessible language

## Notable: R1 and Chimera BOTH returned responses in T6 (first success for these models)
R1 and Chimera had CAPACITY failures in T1-T5. T6 prompt ~96KB. Both produced usable responses.
Likely explanation: these models cleared capacity during the hour-long session.

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **3/3** | BEST | Exactly 500 words (self-verified via wc). 5 themed narrative paragraphs: reliability → safety evidence → UX → analytics → engineering discipline. Explicit meta-arc: "maturation: from feature-rich control software into an audited, phase-aware, safety-centered laboratory platform." Accessible language. |
| Gemini | **2/3** | ADEQUATE | Narrative paragraphs, correct themes. Falls into business slop at end: "dedicated engineering team remains strongly and entirely focused on continuously delivering unparalleled excellence." Loses accessibility score for the final paragraph. |
| R1-0528 | **2/3** | ADEQUATE | Clear 5-section structure, covers B1 fix, alarm integration, analytics. Self-declares "Exactly 500 words." Uses headers which breaks pure narrative format. Accessible. Major themes covered but meta-arc not explicitly named. |
| Chimera (TNG) | **2/3** | ADEQUATE | v0.42.0-focused (not full arc). Good safety + analytics coverage. Narrative paragraphs. Mention of multi-model validation is an interesting touch. But single-release focus reduces arc score. |
| Qwen3-Coder | **3/3** | BEST | Explicitly names the arc: "safety maturation... operational integration... architectural consistency" and "The narrative arc over recent versions has been clear: stabilize foundations, harden reliability, integrate diagnostics." Mentions 1,931 tests. Accessible language throughout. |
| GLM-5.1 | **2/3** | ADEQUATE | 4 clear themed sections covering safety, UX modernization, analytics, lab operations. Good accessibility. Does not name the LabVIEW-replacement meta-arc explicitly. |
| Kimi-K2.6 | N/A | PARSE_ERROR | Same failure pattern as T1-T5. 96KB prompt likely too large for Kimi's connection timeout, not context limit. |
| MiniMax-M2.5 | **2/3** | ADEQUATE | Structured sections, good analytics coverage, safety framing accessible. Does not identify overarching meta-arc. |

## Notable patterns
- **Codex + Qwen3 at 3/3**: Both identified the meta-arc independently. Codex's "safety hardening through evidence, not assumption" framing is particularly strong.
- **R1/Chimera recovery**: Both models that failed T1-T5 on capacity produced T6 responses. The hour elapsed since T1 freed up capacity.
- **Kimi consistent failure**: Same PARSE_ERROR pattern despite 96KB not being larger than other tasks — suggests connection timeout, not context limit.
- **Gemini slop alert**: "unparalleled excellence" in the final paragraph is a sign of Gemini's training data distribution — scores it down for accessibility.

## Long-context routing recommendation
For 96KB+ digest tasks: Codex and Qwen3 perform best at narrative synthesis with explicit arc identification. R1 (when available) produces structured, accessible output. GLM is reliable but less arc-aware.
