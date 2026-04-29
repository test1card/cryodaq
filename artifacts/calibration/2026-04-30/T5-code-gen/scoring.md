# Task class T5 — Code generation (generative) — scoring

## Rubric
- 0: code doesn't compile / breaks tests / regresses HF1
- 1: compiles but has clear bug (e.g., bypasses slew rate)
- 2: works correctly but doesn't preserve slew rate limiting semantics
- 3: works correctly + preserves all existing safety properties + notes design tradeoff vs delayed-update

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **3/3** | DEEP | `apply_p_target_step_now` helper on Keithley side. Slew limit ✓, compliance ✓, _last_v updated ✓, locking noted. Tradeoff: "lower command latency at cost of more coupling + new locking requirement between helper and read_channels." |
| Gemini | **2/3** | ADEQUATE | `_apply_immediate_step` helper. Slew-like logic present. BUT uses `getattr(runtime, "last_i", 0.0)` and `getattr(runtime, "last_r", 0.0)` — these attributes may not exist on real runtime objects. Fragile assumption about attribute presence. |
| R1-0528 | N/A | CAPACITY | |
| Chimera | N/A | CAPACITY | |
| Qwen3-Coder | **3/3** | DEEP | "Hybrid design — immediate SCPI write with constrained slew." Has compliance clamping and slew limit. Notes tradeoff with delayed-update design. |
| GLM-5.1 | **3/3** | DEEP | Cleanest design: `apply_regulation_step` as a Keithley driver method. Measures V/I fresh, computes resistance, applies compliance + slew exactly as `read_channels` does, updates `_last_v`. Separation of concerns preserved — SafetyManager calls Keithley helper, not transport directly. |
| Kimi-K2.6 | N/A | PARSE_ERROR | |
| MiniMax-M2.5 | **3/3** | DEEP | Correctly uses MAX_DELTA_V_PER_STEP. Compliance clamp. Updates _last_v. Explains continuity: "in-memory p_target and driver _last_v also updated so P=const loop picks up new target on next poll without breaking continuity." |

## Notable patterns
- **4/4 functional models scored 3/3 or 2/3** — strong showing overall.
- **GLM's architecture** (Keithley-side helper that mirrors read_channels exactly) is the cleanest: safety boundary between SafetyManager and Keithley driver preserved.
- **Codex** uniquely noted the locking requirement — `read_channels` and `apply_p_target_step_now` need to share a lock to prevent _last_v divergence.
- **Gemini weakness**: Relied on `getattr(runtime, "last_i")` — attributes that don't exist on ChannelRuntime, suggesting Gemini fabricated the resistance source.
- R1/Chimera capacity failures consistent across T5.

## Routing recommendation for code gen tasks
GLM (cleanest architecture), Codex (best locking analysis), MiniMax (good continuity reasoning), Qwen3 (correct and concise).
