# F28 Гемма — Cycle 2 architect review

## Branch
`feat/f28-hermes-agent` at `535cc95`

## Implementation

**Pre-Cycle-2 fixes (from Cycle 0 ledger):**
- `phase_transition` now published BEFORE `event_logger.log_event()` in advance_phase handler (correct causal order)
- `experiment_stop` / `experiment_finalize` / `experiment_abort` now produce distinct `event_type` strings (was: all non-abort → `"experiment_finalize"`)

**Files changed:**
- `src/cryodaq/agents/gemma.py` (NEW — 291 LOC)
- `src/cryodaq/agents/output_router.py` (NEW — 102 LOC)
- `src/cryodaq/agents/prompts.py` (NEW — 83 LOC)
- `config/agent.yaml` (NEW — 39 lines)
- `src/cryodaq/engine.py` (MODIFIED — +63 LOC)
- `tests/agents/test_gemma_alarm_flow.py` (NEW — 307 LOC)

LOC: +881 / -4  
Tests added: 15 (test_gemma_alarm_flow.py)

## Cycle goal achieved

Per spec §3 Cycle 2:
- ✅ `agents/gemma.py` — GemmaAgent service class (Гемма)
- ✅ `agents/prompts.py` — Russian alarm summary templates per spec §2.6
- ✅ `agents/output_router.py` — Telegram + operator log + GUI insight dispatch
- ✅ Engine wiring: startup after telegram_bot, shutdown before telegram_bot
- ✅ Configuration loading from `config/agent.yaml`
- ✅ Tests: 15 unit tests covering happy path, error resilience, rate limiting

**Cycle 2 milestone:** alarm fires → Гемма generates Russian summary → Telegram + operator log entry.  
Slice A first task working end-to-end (mock Ollama verified; real smoke test pending architect verification).

## Key design decisions

- **EventBus-only subscription** — GemmaAgent subscribes to EventBus (not per-component callbacks), clean architecture per Cycle 0 foundation
- **Rate limiting** — asyncio.Semaphore(2) for concurrent + deque-based hourly bucket. Simple and correct for asyncio single-threaded model
- **Error isolation** — OllamaUnavailableError/OllamaModelMissingError caught in `_safe_handle`, engine continues. `_event_loop` catches all exceptions from `create_task`
- **Fail-soft init** — if agent.yaml missing or init fails, engine logs warning and continues without GemmaAgent
- **Safety** — no engine API accessible from agents/. OutputRouter only calls `_send_to_all`, `log_event`, `event_bus.publish("gemma_insight")` — all text-only channels
- **Russian language** — ALARM_SUMMARY_SYSTEM explicitly instructs "ТОЛЬКО на русском языке. Никакого английского в ответе." Multiple fail-safes against English drift

## Test results

```
tests/agents/test_gemma_alarm_flow.py: 15 passed
tests/agents/test_ollama_client.py: 16 passed
tests/core/test_event_bus.py: 14 passed
tests/core/test_event_logger.py: 5 passed
tests/core/test_experiment_commands.py: 9 passed
tests/core/test_advance_phase_command.py: 5 passed
ruff: clean
```

## Audit (pending)

| Iter | Model | Verdict | Action |
|------|-------|---------|--------|
| 1 | codex/gpt-5.5 | pending | — |
| 1 | glm/5.1 (8192 tokens) | pending | — |
| 1 | gemini/2.5-pro | pending | — |
| 1 | minimax/m2.5 | pending | — |

## ARCHITECT DECISION NEEDED

None introduced in Cycle 2. All §2.10 decisions remain as baked-in.

**Decision deferred from Cycle 0:**
- v1 AlarmEngine wiring: DEFERRED (Option C) — v1 hardware fault alarms (keithley_overpower) intentionally excluded from GemmaAgent scope

## CRITICAL ARCHITECT VERIFICATION REQUIRED

Per spec §3 Cycle 2 and architect instruction:
1. Start `cryodaq-engine --mock`
2. Trigger alarm in mock mode (e.g., via mock data injection)
3. Verify Russian summary appears in Telegram within ~10s
4. Verify operator log entry with `gemma` tag
5. Note: actual model in use is `gemma4:e4b` (not gemma3 — spec model different from installed)
6. Document latency observed (target <10s per spec)
7. Check for English drift or hallucination patterns in output
8. If Russian output quality weak → STOP, surface architect, prompt engineering iteration before Cycle 3

## Spec deviations

| Item | Spec | Actual | Rationale |
|---|---|---|---|
| Default model | gemma3:e4b | gemma4:e4b | Only model installed on dev M5 |
| GemmaAgent constructor | Takes AlarmStateManager, ExperimentManager directly | Takes EventBus | Cycle 0 built EventBus — cleaner than per-component callbacks |
| Concurrent inference limit | 2 (spec §2.10 #4) | 2 ✓ | Matches spec |

## Time budget vs 15 May

Today: 2026-05-01. Deadline: 2026-05-15 = **14 days remaining**.  
Cycles done: 0, 1, 2. Remaining: Cycle 3 (Slice A complete), Cycle 4 (Slice B).  
On track. A+B by deadline is highly feasible.

## Next: Cycle 3

Slice A remaining tasks + GUI insight panel:
- Experiment finalize handler
- Sensor anomaly critical handler  
- Shift handover request handler
- GUI: `src/cryodaq/gui/shell/views/gemma_insight_panel.py` (~150 LOC)
