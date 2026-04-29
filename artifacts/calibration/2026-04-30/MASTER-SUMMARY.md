# Calibration Session — Master Summary
# 2026-04-30 | 7 task classes × 8 models

## Session overview

Controlled empirical calibration of 8 LLM models across 7 CryoDAQ-specific task classes.
Goal: derive routing rules for multi-model consultation based on observed strengths,
weaknesses, capacity reliability, and hallucination patterns. All dispatches used real
cryoDAQ source code as ground truth.

**Models tested:** Codex (gpt-5.5 high-reasoning), Gemini (gemini-3.1-pro-preview),
R1-0528 (DeepSeek), Chimera-TNG, Qwen3-Coder-480B, GLM-5.1, Kimi-K2.6, MiniMax-M2.5

**Infrastructure:** Chutes API direct dispatch (`llm.chutes.ai/v1/chat/completions`)
for Chutes-hosted models; native CLI for Codex and Gemini.

---

## Headline results

| Rank | Model | Scored Tasks | Total | Pct | Reliability |
|---|---|---|---|---|---|
| 1 | GLM-5.1 | 5/5 | 14/15 | **93.3%** | High (1 T1 capacity) |
| 2 | Codex (gpt-5.5) | 6/6 | 16.5/18 | **91.7%** | Perfect (0 failures) |
| 3 | Gemini | 5/5 | 12/15 | **80.0%** | High (1 T1 quota) |
| 4 | MiniMax-M2.5 | 6/6 | 14/18 | **77.8%** | Perfect (0 failures) |
| 4 | Chimera (TNG) | 3/3 | 7/9 | **77.8%** | Low (3/6 failures) |
| 6 | Qwen3-Coder | 6/6 | 13.5/18 | **75.0%** | Perfect (0 failures) |
| 6 | Kimi-K2.6 | 2/2 | 4.5/6 | **75.0%** | Very low (4/6 failures) |
| 8 | R1-0528 | 4/4 | 8/12 | **66.7%** | Low (2/6 failures) |

*Pct = scored points / (scored tasks × 3). T2 excluded (brief defect). Chimera/Kimi
percentages computed on limited samples — treat with low confidence.*

---

## Task class findings

### T1 — Bug hypothesis (asyncio/ZMQ)
Hardest task class. High variance (scores 1–3). **Only Codex identified pyzmq reactor
state** as the specific mechanism. R1 and Qwen3 analyzed adjacent code paths instead.
Chimera and MiniMax were directionally correct (2/3). GLM and Gemini had capacity failures.

→ **Route bug-hypothesis tasks to Codex first. Use Chimera/MiniMax for verification.**

### T2 — Narrow code review
**INVALIDATED.** Brief construction defect: test functions placed under production module
header in the diff. All models reading the brief correctly saw apparent tests-in-production.
Must re-run with `git show 189c4b7` raw diff.

→ **No routing data. Re-run required.**

### T3 — Architecture consistency review
Surprising result. **High-reasoning models (Codex, Qwen3, Kimi) systematically over-flagged**
DRIFT on HF1 docstring. All three found the same real issue ("converges within one poll
interval" oversimplifies slew-rate behavior) but rendered the wrong verdict. **GLM alone**
gave clean CONSISTENT + actionable test improvement suggestion.

Convergent finding from 3 independent models suggests the docstring claim may genuinely
be imprecise. Architect should evaluate update_target docstring "≤1 s" claim.

→ **Route arch-consistency review to GLM. Do NOT use Codex/Qwen3 alone for T3-class tasks.**

### T4 — Spec design
Strong showing across all available models. Codex, Gemini, GLM, Kimi all 3/3. Each model
brought unique insights: GLM found monotonic-epoch domain mismatch; Kimi flagged shared-
instance invariant; Gemini added a hard stop warning; Codex covered naive datetime edge case.

→ **All primary models suitable for spec design. Multi-model adds genuine diversity.**

### T5 — Code generation
Codex, Qwen3, GLM, MiniMax all 3/3. Gemini 2/3 (fabricated `getattr(runtime, "last_i")`
attributes that don't exist on ChannelRuntime). R1/Chimera had capacity failures this wave.

Codex uniquely identified the locking requirement between `apply_p_target_step_now` and
`read_channels`. GLM produced the cleanest architectural separation (Keithley-side helper
mirroring `read_channels` exactly).

→ **Codex + GLM for code-gen. Verify Gemini output for fabricated attribute access.**

### T6 — Long-context digest (96KB)
Only Codex and Qwen3 scored 3/3 by naming the overarching meta-arc explicitly. Others
(Gemini, R1, Chimera, GLM, MiniMax) produced adequate 2/3 responses missing the arc label.
Kimi failed (connection timeout on 96KB prompt).

→ **Codex + Qwen3 for narrative synthesis. Kimi excluded from long-context tasks.**

### T7 — Math derivation (GUM uncertainty)
Clean sweep: all 7 functional models scored 3/3. No discrimination value.
GLM and MiniMax independently produced the same numerical example (u=0.1K, D=0.2K → 71%),
suggesting convergent domain knowledge. All models correctly analyzed the correlation
caveat (positive covariance between ΔT and ΔT₀ *reduces* u(G)).

→ **Any single model suffices. No multi-model needed for math derivation.**

---

## Cross-model patterns

### Hallucinations observed
- **R1 on T1**: Invented "TCP keepalive timeout" as the 50s threshold cause — plausible but wrong mechanism.
- **Gemini on T5**: Used `getattr(runtime, "last_i", 0.0)` for resistance computation — attribute doesn't exist on ChannelRuntime.
- **GLM on T3 (previous session verification)**: Claimed `update_limits()` issues no SCPI command — actually wrong, `update_limits()` does call `_transport.write()`. (Note: this finding was from architect verification, not the T3 calibration wave.)

### Systematic biases
- **High-reasoning models overreach on consistency review** (T3): Codex, Qwen3, Kimi all over-read legitimate design choices as bugs. Best suited for finding issues, not confirming correctness.
- **GLM underreaches on bug hypothesis** (T1 was N/A, but T3 pattern suggests conservatism): GLM's conservative bias makes it ideal for review tasks, potentially weak on adversarial bug-finding.
- **Gemini recovers from 429**: After quota exhaustion on T1, Gemini provided useful responses on T3–T7. Quota issues are transient, not permanent exclusions.

### Capacity reliability ranking
1. Codex, Qwen3, MiniMax — 0% failure rate
2. GLM, Gemini — ~17% failure rate (single wave)
3. R1 — 33% failure rate (daytime UTC saturation)
4. Chimera — 50% failure rate
5. Kimi — 67% failure rate (connection instability on long prompts)

---

## Recommended routing table (v1.0)

```
Task class          Primary         Secondary           Avoid
─────────────────────────────────────────────────────────────────────
Bug hypothesis      Codex           Chimera, MiniMax    Qwen3 (wrong frame)
Code review         GLM             Gemini, MiniMax     Codex, Qwen3, Kimi (overreach)
Spec design         Codex+GLM+Gemini  Kimi (if short)   —
Code generation     Codex+GLM       MiniMax, Qwen3      Gemini (attr hallucination)
Long digest         Codex+Qwen3     R1 (structured)     Kimi (timeout)
Math derivation     Any single      —                   — (no routing needed)
```

---

## Infrastructure lessons

1. **Chutes API direct dispatch works reliably** for GLM, MiniMax, Qwen3, Chimera, Kimi.
   Use `~/.claude-code-router/config.json` for API key. Key extraction:
   `python3 -c "import json; cfg=json.load(open('$HOME/.claude-code-router/config.json')); [print(p['api_key']) for p in cfg['Providers'] if 'chutes' in p['name'].lower()]"`

2. **max_tokens caps**: MiniMax caps at 8192 non-streaming; R1/Kimi at 8000 in practice.
   GLM/Qwen3 stable at 4000 tokens per prompt.

3. **Codex `--sandbox`**: `--sandbox none` is invalid. Use `--sandbox workspace-write`.

4. **Inter-wave delay**: R1 and Chimera benefit from 30+ min gaps between waves.
   Daytime UTC = highest capacity contention for these models.

5. **Kimi long-prompt timeout**: All 96KB+ prompts to Kimi fail. Not context limit —
   connection drops. Chutes-side timeout suspected. Keep Kimi prompts under ~10KB.

---

## Open items

| Item | Priority | Action |
|---|---|---|
| T2 re-run | HIGH | Re-dispatch with `git show 189c4b7` diff to Codex/Gemini/GLM/MiniMax |
| T3 docstring fix | MEDIUM | Evaluate whether update_target "≤1 s" claim needs precision |
| T1 routing validation | MEDIUM | Run second asyncio bug scenario to confirm Codex-only T1 routing |
| R1/Chimera retry logic | LOW | Add 30min inter-wave delay or retry to dispatch script |
| Kimi investigation | LOW | Test with 5KB / 20KB / 50KB prompts to find connection threshold |

---

## Artifact index

```
artifacts/calibration/2026-04-30/
├── T1-bug-hypothesis/
│   ├── scoring.md       ← scored, valid
│   ├── codex.response.md
│   ├── chimera.response.md
│   ├── qwen3.response.md
│   ├── r1.response.md
│   └── minimax.response.md
├── T2-narrow-review/
│   ├── scoring.md       ← ⚠ INVALID (brief defect)
│   └── *.response.md
├── T3-arch-drift/
│   ├── scoring.md       ← scored, valid
│   └── *.response.md
├── T4-spec-design/
│   ├── scoring.md       ← scored, valid
│   └── *.response.md
├── T5-code-gen/
│   ├── scoring.md       ← scored, valid
│   └── *.response.md
├── T6-long-digest/
│   ├── scoring.md       ← scored, valid
│   └── *.response.md
├── T7-math-derivation/
│   ├── scoring.md       ← scored, valid (this session)
│   └── *.response.md
├── CALIBRATION-MATRIX.md   ← master score table + routing rules
├── architect-spot-check.md ← cells needing review + action items
└── MASTER-SUMMARY.md       ← this file
```

---

*Session executed 2026-04-30. Architect: Vladimir. Execution: Claude Code (claude-sonnet-4-6).*
*All scores based on ground truth verified against actual cryoDAQ source code.*
