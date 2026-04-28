# CCR + Chutes recon — 2026-04-29

## Current CCR providers

| Provider | Endpoint | Models configured |
|---|---|---|
| chutes | https://llm.chutes.ai/v1/chat/completions | GLM-5.1-TEE, Kimi-K2.5-TEE, DeepSeek-V3.2-TEE |

## Current routes

| Route | Provider/model |
|---|---|
| default | chutes, zai-org/GLM-5.1-TEE |
| background | chutes, deepseek-ai/DeepSeek-V3.2-TEE |
| longContext | chutes, moonshotai/Kimi-K2.5-TEE |

## Recently used models (log: 2026-04-20, ~4.6M entries)

| Model | Calls |
|---|---|
| deepseek-ai/DeepSeek-V3.2-TEE | 214 |
| zai-org/GLM-5.1-TEE | 78 |
| claude-haiku-4-5-20251001 | 20 |
| claude-sonnet-4-6 | 5 |
| claude-sonnet-4 | 1 |

> Note: Logs for 2026-04-26 through 2026-04-28 are 0 bytes — no CCR dispatch in that window.
> The active log session was 2026-04-20. background/DeepSeek was the dominant route (214 calls vs 78 for default/GLM).

## Chutes catalog (39 models available)

### Tier A — modern reasoning / flagship

| Model ID | Type | Notes |
|---|---|---|
| deepseek-ai/DeepSeek-R1-0528-TEE | Reasoning | Latest R1 (May 2026 update), chain-of-thought, TEE |
| deepseek-ai/DeepSeek-V3.2-TEE | Instruct | **Currently configured** (background) |
| deepseek-ai/DeepSeek-V3.1-TEE | Instruct | One minor version older than V3.2 |
| deepseek-ai/DeepSeek-V3-0324-TEE | Instruct | March 2026 snapshot |
| tngtech/DeepSeek-TNG-R1T2-Chimera-TEE | Hybrid | Instruct+reasoning chimera, fast switching |
| Qwen/Qwen3-235B-A22B-Thinking-2507 | Reasoning | 235B MoE thinking variant, July 2025 |
| Qwen/Qwen3-235B-A22B-Instruct-2507-TEE | Instruct | 235B MoE instruct, July 2025, TEE |
| Qwen/Qwen3.5-397B-A17B-TEE | Instruct | Qwen3.5 flagship, 397B MoE |
| Qwen/Qwen3-Coder-Next-TEE | Code | Dedicated coder, next-gen, TEE |
| moonshotai/Kimi-K2.6-TEE | Long-ctx | **Newer than configured K2.5**, drop-in upgrade |
| moonshotai/Kimi-K2.5-TEE | Long-ctx | **Currently configured** (longContext) |
| MiniMaxAI/MiniMax-M2.5-TEE | Instruct | MiniMax flagship, TEE |
| openai/gpt-oss-120b-TEE | Instruct | OpenAI open-source 120B, TEE |

### Tier B — solid but not priority

| Model ID | Notes |
|---|---|
| zai-org/GLM-5.1-TEE | **Currently configured** (default) |
| zai-org/GLM-5-TEE | One minor behind 5.1 |
| zai-org/GLM-5-Turbo | Faster GLM-5, lower latency |
| zai-org/GLM-4.7-TEE / FP8 | Previous gen |
| Qwen/Qwen3-32B-TEE | Compact dense |
| Qwen/Qwen3.6-27B-TEE | Compact, recent |
| Qwen/Qwen3-Next-80B-A3B-Instruct | Mid-size MoE |
| Qwen/Qwen3-30B-A3B | Small MoE |
| XiaomiMiMo/MiMo-V2-Flash-TEE | Fast reasoning, flash-class |
| google/gemma-4-31B-turbo-TEE | Gemma 4, turbo |
| NousResearch/Hermes-4-14B | Hermes-4, 14B |
| NousResearch/DeepHermes-3-Mistral-24B-Preview | Hermes-3 preview |

### Not present on Chutes

- Llama-4-Scout / Llama-4-Maverick (only Llama 3.2 unsloth distills)
- DeepSeek-R2 (not released yet)
- Qwen3-Max by marketing name (Qwen3-235B is the "max" class model)
- GLM-4.6V is vision-only, not useful for code routing

## Recommendations for arsenal upgrade

### Drop
| Model | Reason |
|---|---|
| moonshotai/Kimi-K2.5-TEE | K2.6 is available as a direct drop-in; no reason to stay on K2.5 |

### Add
| Model | Route suggestion | Rationale |
|---|---|---|
| moonshotai/Kimi-K2.6-TEE | longContext (replace K2.5) | Newer drop-in; same long-context specialty, free upgrade |
| deepseek-ai/DeepSeek-R1-0528-TEE | New `reasoning` route | Latest thinking model; best for complex debugging, architecture decisions, multi-step code analysis |
| Qwen/Qwen3-Coder-Next-TEE | New `coder` route | Purpose-built coder, likely outperforms general models on code generation/completion tasks |
| tngtech/DeepSeek-TNG-R1T2-Chimera-TEE | Optional `think` alias | Hybrid instruct+reasoning; useful when you want reasoning mode without full R1 overhead |

### Keep
| Model | Route | Status |
|---|---|---|
| zai-org/GLM-5.1-TEE | default | Still current (5.1 is latest in GLM-5 line); keep for fast default |
| deepseek-ai/DeepSeek-V3.2-TEE | background | Most-used model in logs (214 calls); performing well |

## Open questions for architect

1. **Route naming**: Do we want a dedicated `reasoning` route for R1-0528, or should it replace `default`? R1 is slower than V3.2 — impacts interactive latency if made default.
2. **Coder route trigger**: CCR route selection is currently manual (default/background/longContext). How does the `coder` route get invoked — by model hint in the request, or by a new CCR routing rule?
3. **Chimera vs R1**: TNG Chimera is a hybrid that can switch modes per-token. Worth benchmarking against pure R1-0528 on our workload before committing to R1 as the reasoning route.
4. **MiniMax-M2.5**: Unknown quality on code tasks — worth a one-shot eval before adding to any route.
5. **Log gap**: No CCR activity 2026-04-26 to 2026-04-28 — is this expected (direct Claude API usage) or a CCR downtime?

## Summary

- **1 provider** (Chutes), **3 models** configured, **3 routes**
- **39 models** available on Chutes; catalog is substantially richer than what's configured
- **Primary workload** (from logs): background/DeepSeek-V3.2 (214 calls) >> default/GLM-5.1 (78 calls)
- **Quick wins**: Kimi K2.5 → K2.6 (zero-risk upgrade), add R1-0528 reasoning route, add Qwen3-Coder-Next coder route
- **Stale models**: none critically stale; V3.2-TEE and GLM-5.1-TEE are current
