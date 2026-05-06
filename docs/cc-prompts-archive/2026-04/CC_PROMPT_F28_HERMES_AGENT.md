# F28 — Гемма: local LLM agent for runtime insight

> Local-only Ollama-backed agent observing engine events, generating
> Telegram messages / operator log entries / GUI insights / report
> intros. Slice scope: A (notification authoring) + B (diagnostic
> suggestions) + C (campaign report writing) hopeful. C is stretch
> goal — drop if time-pressed before 15 May.
>
> Service name: **Гемма** (named after the underlying model — Gemma
> 3 e4b via Ollama). Russian-language operator-facing brand.

---

## 0. Operating posture

- **Architect synchronously available** — multi-cycle work with
  decisions surfacing throughout. Not overnight runner.
- **Demo-target deadline:** 15 May 2026 (Yandex Practicum award
  application).
- **Slice priority:** A first (week 1) → B (week 1-2) → C stretch
  (week 2 if time allows). Slice C explicitly droppable.
- **Branch:** `feat/f28-hermes-agent`
- **Cycles estimate:** 5-6 cycles total (Slice A: 2-3, B: 2, C: 1-2)
- **NEVER autonomous engine commands.** Hermes outputs to text
  channels (Telegram, log, GUI). NEVER executes engine actions
  per ORCHESTRATION v1.3 §13 autonomy constraints + safety-critical
  context.

---

## 1. Architect decisions baked in

| Decision | Verdict |
|---|---|
| Provider | Local-only via Ollama. NO external API (Anthropic, OpenAI). Network-isolated lab Ubuntu must work. |
| Default model | gemma3:e4b (Gemma 3 efficient 4B params, ~3GB, ~40-50 tok/s on M5). Fast enough for realtime alarm summaries. For batch/non-realtime tasks (Slice C campaign reports), gemma3:e4b sufficient — no need for larger model unless quality issues observed in cycle 5 polish. Configurable upgrade path to gemma3:12b if M5 has headroom. |
| Slice scope | A + B target. C stretch goal (drop if 15 May at risk). |
| Triggers | alarm_fired (warning + critical), experiment_finalize, sensor_anomaly_critical, shift_handover_request, phase_transition_to_finalize. NO per-reading triggers. |
| Outputs | Telegram messages + operator log entries + GUI insight panel — all three. |
| Naming | **Гемма** (after the Gemma model). Service module `src/cryodaq/agents/gemma.py`. Class name `GemmaAgent`. Operator-facing strings: "Гемма" / 🤖 emoji prefix. F5 "Hermes" remains a separate concept (engine→webhook integration, deferred). |
| Latency tolerance | Async, non-blocking. With gemma3:e4b expect insight within 3-10s of event (typical 4-7s for 200-token response at 40-50 tok/s). Much faster than qwen3:14b would have been. |
| Hardware target | M5 24GB primary (gemma3:e4b uses ~3GB, leaves plenty of headroom for engine + GUI). RTX 3050 8GB secondary fits comfortably. Lab Ubuntu PC: should run e4b on CPU if no GPU; latency may be 2-3x higher but still acceptable. |

---

## 2. Architecture

### 2.1 Module layout

```
src/cryodaq/agents/
  __init__.py
  gemma.py               # main service (GemmaAgent class)
  ollama_client.py       # Ollama HTTP wrapper, model abstraction
  context_builder.py     # gather state for LLM prompt
  prompts.py             # prompt templates per task type
  output_router.py       # Telegram / log / GUI dispatch
  audit.py               # log every LLM call for review
```

New top-level `agents/` directory — separate from existing
`analytics/` and `core/` to signal architectural distinction.

### 2.2 Service lifecycle

```python
class GemmaAgent:
    """Local-LLM agent observing engine events. Service named Гемма."""
    
    def __init__(
        self,
        *,
        config: GemmaConfig,
        broker: DataBroker,
        alarm_engine: AlarmStateManager,
        experiment_manager: ExperimentManager,
        event_logger: EventLogger,
        telegram_bot: TelegramCommandBot | None,
        sqlite_writer: SQLiteWriter,
    ) -> None:
        ...
    
    async def start(self) -> None:
        # Subscribe to: alarm transitions (callback), phase transitions
        # (callback), event_logger appends (in-memory bus, NEW), 
        # sensor_diagnostics critical anomaly (callback)
        ...
    
    async def stop(self) -> None:
        # Cancel inference tasks, close HTTP session
        ...
```

Engine wires Гемма during startup if `agent.enabled: true`. Failure
to start (Ollama unreachable) = warn + disable, do NOT crash engine.

### 2.3 Event bus — new minimal component

**Required new piece:** `EventBus` for non-Reading events.

Currently events flow through:
- `AlarmStateManager._listeners` callbacks (existing)
- `ExperimentManager` direct method calls (no bus)
- `EventLogger` SQLite writes (no in-memory broadcast)

Гемма needs a **single subscribe point** for all event types. Design
decision: **add minimal EventBus** as new component in
`src/cryodaq/core/event_bus.py`.

```python
@dataclass
class EngineEvent:
    event_type: str  # "alarm_fired", "phase_transition", "experiment_finalize", etc
    timestamp: datetime
    payload: dict[str, Any]
    experiment_id: str | None

class EventBus:
    """Lightweight pub/sub for engine events (not Reading data)."""
    
    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
        ...
    
    async def publish(self, event: EngineEvent) -> None:
        ...
```

Engine wires EventBus, AlarmStateManager publishes alarm transitions
to it, ExperimentManager publishes phase transitions, EventLogger
publishes event_type events parallel to SQLite write.

This is **foundational change** — affects engine.py + alarm_v2.py +
experiment.py + event_logger.py. Approximately 100-150 LOC.

**ARCHITECT DECISION NEEDED:** EventBus addition is broader scope
than Гемма alone. Either:
- (a) Add EventBus as foundational primitive in cycle 0, then Гемма
  builds on it. Cycle 0 is independent commit, low risk.
- (b) Гемма wraps existing callback patterns directly without
  EventBus, accepting fragmented integration.
- Architect default: **(a)** — EventBus is good engineering, makes
  Гемма cleaner, enables future agents.

### 2.4 Ollama client

`ollama_client.py` — HTTP wrapper around `http://localhost:11434`.

```python
class OllamaClient:
    def __init__(self, base_url: str, default_model: str, timeout_s: float = 30):
        # Default timeout reduced to 30s — gemma3:e4b is fast enough
        # that 60s indicates infrastructure problem, not slow model.
        ...
    
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> GenerationResult:
        """Returns GenerationResult(text, tokens_in, tokens_out, latency_s, model)."""
        ...
```

Uses `aiohttp` (already a dep). Streams response, accumulates text,
returns on completion or timeout.

Error handling:
- Connection refused → `OllamaUnavailableError`, caller decides
  graceful degradation
- Model not pulled → `OllamaModelMissingError` with hint to run
  `ollama pull <model>`
- Timeout → returns partial text + truncation flag

### 2.5 Context builder

`context_builder.py` — assembles relevant state for LLM prompt.

Different task types need different context. Examples:

**For alarm summary (Slice A):**
- Alarm id, level, channels, values
- Last 5 readings on affected channels
- Current experiment state (phase, age, target_temp)
- Active interlocks status
- Recent alarms (last hour) for pattern context

**For diagnostic suggestion (Slice B):**
- All Slice A context
- Plus: comparison to past cooldowns at similar phase
- Plus: cross-channel correlation matrix snippet
- Plus: pressure trend
- Plus: previous similar alarms outcome (if any)

**For campaign report intro (Slice C):**
- Full experiment summary (duration, phases, min/max per channel)
- All operator log entries this experiment
- All alarms triggered + their resolution
- Calibration curves applied
- Any custom metadata fields from template

Context builder reads SQLite via existing reader patterns, formats
as compact text (preserving token budget).

### 2.6 Prompt templates

`prompts.py` — collection of templates per task type. Russian
language for outputs (CryoDAQ is Russian-language project; operators
are Russian-speaking).

Architect-approved system prompt principles (apply to all):
- Honest about uncertainty: "если неуверен, скажи 'неуверен'"
- Cite specific values from context, not vague summaries
- No marketing speak / no hyperbole
- Brief: target 100-300 words for messages, longer for reports
- Suggest, never command operator
- Recognize own limits: "не могу определить причину без X"

Sample template for alarm summary:

```python
ALARM_SUMMARY_SYSTEM = """\
Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — 
краткий, точный summary сработавшего аларма для оператора в Telegram.

Принципы:
- Отвечай ТОЛЬКО на русском языке.
- Не выдумывай контекст. Используй только данные ниже.
- Конкретные значения, не размытые описания.
- Если возможна причина — предложи. Если неясно — скажи "причина неясна".
- Никогда не предлагай safety-actions автоматически (emergency_off, 
  переключение фаз). Только observations + suggestions для оператора.
- 80-150 слов. Telegram-friendly Markdown.
"""

ALARM_SUMMARY_USER = """\
ALARM TRIGGERED:
- ID: {alarm_id}
- Level: {level}
- Channels: {channels}
- Values: {values}

CURRENT STATE:
- Phase: {phase}
- Experiment: {experiment_id} (started {experiment_age})
- Target temp: {target_temp}
- Active interlocks: {interlocks}

RECENT READINGS (last 60s) on affected channels:
{recent_readings}

RECENT ALARMS (last hour):
{recent_alarms}

Generate brief summary for operator Telegram. Russian language.
"""
```

Templates are **versioned** in code with comment block explaining
intent + last revision date. Operator-facing language stays
consistent across versions via central template review.

### 2.7 Output router

`output_router.py` — dispatches LLM output to configured channels.

```python
class OutputRouter:
    async def dispatch(
        self,
        event: EngineEvent,
        llm_output: str,
        *,
        targets: list[OutputTarget],
        audit_id: str,
    ) -> None:
        ...
```

Targets:
- `OutputTarget.TELEGRAM` → existing TelegramCommandBot send path
  (all allowed_chat_ids, role-filtered per existing notifications)
- `OutputTarget.OPERATOR_LOG` → event_logger.log_event with
  `tag=gemma`
- `OutputTarget.GUI_INSIGHT` → publish to EventBus as
  `gemma_insight` event_type, GUI subscribes (Cycle 4)

Each output prefixed with `🤖 Гемма:` so operator immediately sees
what's AI-generated vs human input.

### 2.8 Audit log

`audit.py` — every LLM call recorded to disk for review.

```
data/agents/gemma/audit/<YYYY-MM-DD>/
  <ISO_timestamp>_<audit_id>.json
```

Each file:
```json
{
  "audit_id": "abc123",
  "timestamp": "2026-05-01T14:23:45+03:00",
  "trigger_event": {"event_type": "alarm_fired", "payload": {...}},
  "context_assembled": "...",
  "prompt_template": "alarm_summary",
  "model": "gemma3:e4b",
  "system_prompt": "...",
  "user_prompt": "...",
  "response": "...",
  "tokens": {"in": 1234, "out": 156},
  "latency_s": 4.7,
  "outputs_dispatched": ["telegram", "operator_log"],
  "errors": []
}
```

Why: post-hoc review of LLM behavior, debugging, future fine-tuning
data, accountability per ORCHESTRATION verification discipline.

Retention: 90 days, then archived/deleted (housekeeping).

### 2.9 Configuration

`config/agent.yaml` (new):

```yaml
gemma:
  enabled: true
  
  ollama:
    base_url: http://localhost:11434
    default_model: gemma3:e4b
    # Fallback to even smaller model if e4b unavailable; or upgrade
    # to e12b/12b later if quality issues observed.
    fallback_model: gemma3:e4b  # same — single-model deployment for now
    batch_model: gemma3:e4b      # Slice C campaign reports also use e4b
    timeout_s: 30
    temperature: 0.3
  
  triggers:
    alarm_fired:
      enabled: true
      min_level: WARNING  # ignore INFO-level
    experiment_finalize:
      enabled: true
    sensor_anomaly_critical:
      enabled: true
    shift_handover_request:
      enabled: true
    phase_transition_to_finalize:
      enabled: true
    # Disabled by default (noise):
    phase_transition_general: false
    every_reading: false
  
  outputs:
    telegram: true
    operator_log: true
    gui_insight_panel: true
  
  rate_limit:
    max_calls_per_hour: 60  # gemma3:e4b is small enough for higher cadence
    max_concurrent_inferences: 2  # e4b can run 2 concurrent on M5 (3GB × 2 = 6GB, comfortable)
  
  slices:
    a_notification: true       # always on
    b_suggestion: true          # cycle 4+
    c_campaign_report: false    # cycle 6, set to true when ready
  
  audit:
    enabled: true
    retention_days: 90
```

### 2.10 ARCHITECT DECISION NEEDED markers

Surfaced in Cycle 0/1 handoffs:

1. **EventBus addition (§2.3)** — architect default (a) approved here:
   add as foundational. Verify during cycle 0 implementation.

2. **GUI insight panel placement** — where in MainWindowV2?
   Candidates: separate overlay (Гемма overlay accessed from
   ToolRail), integrated into TopWatchBar (small badge for new
   insights), part of operator log panel (insights appear as log
   entries with marker). Architect default: **separate Гемма
   overlay** for clean separation.

3. **Telegram message threading** — when Гемма generates summary
   for an alarm that was already broadcast to Telegram by existing
   alarm pipeline, do we send Гемма output as reply to the alarm
   message (threaded), or as new message? Architect default:
   **reply (threaded)** for visual clarity that Гемма is
   commenting on the original alarm.

4. **Concurrent inference control** — gemma3:e4b is small (~3GB)
   so concurrent inferences feasible on M5 (2 parallel = 6GB,
   comfortable). But single-flight is simpler. Architect default:
   **2 concurrent max with FIFO queue** — better than single-flight
   for handling burst alarms (cluster of alarms in same tick all
   get summarized in parallel).

5. **Russian language consistency** — ensure Гемма always outputs
   Russian per system prompt. Hard-test with English-prompt
   ambiguity. Architect default: explicit Russian instruction in
   every system prompt.

6. **Ollama process lifecycle** — Гемма does NOT manage Ollama
   process. Operator runs `ollama serve` separately (or systemd
   unit on Ubuntu). Гемма connects to running endpoint, fails
   gracefully if down. Verify documentation in deployment notes.

---

## 3. Implementation cycles

### Cycle 0: EventBus foundation (~150 LOC)

- `src/cryodaq/core/event_bus.py` — new component
- Wire engine.py to instantiate EventBus
- AlarmStateManager publishes transitions
- ExperimentManager publishes phase transitions  
- EventLogger publishes parallel to SQLite write
- Tests: `tests/core/test_event_bus.py` (~80 LOC)

**Branch:** `feat/f28-hermes-agent` — start here.

**Audit:** Codex review for breaking changes. PASS required before
Cycle 1.

### Cycle 1: Ollama client + audit log + context builder skeleton (~250 LOC)

- `agents/__init__.py`
- `agents/ollama_client.py` — HTTP wrapper
- `agents/audit.py` — JSON file logging
- `agents/context_builder.py` — interface + alarm context assembly
- Smoke test: real Ollama call to qwen3:14b on dev machine
- Tests: `tests/agents/test_ollama_client.py` (~100 LOC, mock HTTP)

**Audit:** dual-verifier per ORCHESTRATION §14.2 (Codex + Gemini).

### Cycle 2: GemmaAgent service + alarm summary (Slice A first task) (~200 LOC)

- `agents/gemma.py` — main service class (GemmaAgent)
- `agents/prompts.py` — alarm summary templates (Russian)
- `agents/output_router.py` — Telegram + operator log dispatch
- Engine wiring (startup hook)
- Configuration loading
- Tests: `tests/agents/test_gemma_alarm_flow.py` (~150 LOC, mock Ollama)

**End of Cycle 2:** alarm fires → Гемма generates summary →
Telegram + log entry. Slice A first task working end-to-end.

**Audit:** dual-verifier. Architect smoke-test on M5 with real
gemma3:e4b — verify Russian output quality, latency, memory.

### Cycle 3: Slice A remaining tasks + GUI insight panel (~250 LOC)

- Experiment finalize handler (Slice A)
- Sensor anomaly critical handler (Slice A)
- Shift handover request handler (Slice A)
- GUI: `src/cryodaq/gui/shell/views/gemma_insight_panel.py`
  (~150 LOC) — overlay accessed from ToolRail, labeled "Гемма"
- Tests: extend test_gemma_alarm_flow + new test_gemma_insight_panel

**End of Cycle 3:** Slice A complete. All four notification tasks
working. **Demo-ready milestone.**

**Audit:** dual-verifier.

### Cycle 4: Slice B — diagnostic suggestions (~250 LOC)

- Extend context builder for diagnostic context (cross-channel
  correlation, past cooldown comparison, pressure trends)
- New prompt templates for diagnostic suggestions
- Hook diagnostic suggestion into alarm + sensor_anomaly triggers
  (in addition to summary)
- Tests: `tests/agents/test_gemma_diagnostic.py` (~120 LOC)

**End of Cycle 4:** Slice B complete. Suggestions appear alongside
summaries. **Substantial demo material.**

**Audit:** dual-verifier.

**CHECKPOINT:** assess time vs 15 May deadline. If <5 days remain,
SKIP Cycle 5 (Slice C), polish what we have, ship.

### Cycle 5 (stretch): Slice C — campaign report writing (~200 LOC)

- New context builder method: full experiment state for report
- Prompt template for report intro (Russian, formal scientific
  tone)
- Integration with reporting/ DOCX generator: Гемма-generated
  intro paragraph at top of "Аннотация" section
- Use gemma3:e4b — same as other slices. If quality insufficient 
  for formal report tone, surface ARCHITECT DECISION NEEDED for
  upgrade to gemma3:12b. Don't preemptively use larger model.
- Tests: `tests/agents/test_gemma_report_intro.py` (~80 LOC)

**End of Cycle 5:** Reports auto-include AI-written human-language
summary of campaign. Slice C complete.

**Audit:** dual-verifier.

### Cycle 6 (polish): final integration testing + docs (~100 LOC)

- End-to-end test on dev machine: real experiment lifecycle with
  Гемма active
- README section for Гемма agent (Russian)
- Vault note `~/Vault/CryoDAQ/10 Subsystems/Гемма agent.md`
- Configuration documentation in operator manual
- Audit log retention housekeeping

---

## 4. Acceptance criteria

After all cycles (or A+B if C dropped):

1. ✅ Гемма service starts/stops cleanly with engine
2. ✅ Ollama unavailable → graceful degradation, engine continues
3. ✅ Alarm fired → Гемма generates Russian summary → reaches
   Telegram + operator log within 10s (gemma3:e4b is fast)
4. ✅ Experiment finalize → Гемма generates summary message
5. ✅ Sensor anomaly critical → diagnostic suggestion (Slice B)
6. ✅ GUI insight panel ("Гемма") shows latest 10 insights with
   timestamp, trigger event, output text
7. ✅ Audit log captures every LLM call with full context
8. ✅ Rate limiting prevents inference spam (2-concurrent FIFO + 60/hr cap)
9. ✅ Russian-language outputs consistent (no English drift; Gemma
   3 is multilingual but defaults can drift — explicit instruction
   in every system prompt)
10. ✅ Configurable disable per `agent.yaml`
11. ✅ NO autonomous engine commands. NO modification of state. NO
    safety actions.
12. ✅ Tests cover: happy path per slice, Ollama unavailable,
    timeout, rate limit, audit log creation, config disable

If Slice C ships:
13. ✅ DOCX reports include AI-generated intro paragraph

---

## 5. Test budget

| Cycle | New LOC | Tests | Cumulative |
|---|---|---|---|
| 0 EventBus | 150 | 80 | 230 |
| 1 Ollama+audit+ctx | 250 | 100 | 580 |
| 2 Hermes alarm | 200 | 150 | 930 |
| 3 Slice A complete | 250 | 120 | 1300 |
| 4 Slice B | 250 | 120 | 1670 |
| 5 Slice C (stretch) | 200 | 80 | 1950 |
| 6 Polish | 100 | 50 | 2100 |

Total project: ~1300 LOC + ~600 tests if A+B; ~1500 LOC + ~700 tests
if A+B+C.

---

## 6. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| gemma3:e4b quality insufficient for diagnostic suggestions (Slice B) | MEDIUM | benchmark in cycle 4 smoke test; if poor, ARCHITECT DECISION to upgrade to gemma3:12b (~7GB, still M5-fittable) |
| Ollama process unstable | MEDIUM | graceful degradation pattern, audit error rate, document operator runbook |
| Russian output quality poor (Gemma 3 multilingual but English drift on edge cases) | MEDIUM | extensive prompt engineering in cycle 2-3, manual review during cycle 6 polish, prompt versioning for iteration |
| EventBus integration breaks existing alarm path | HIGH | Cycle 0 is foundational change requiring careful regression testing; full pytest suite must pass after Cycle 0 commit |
| OOM on M5 — much less likely with gemma3:e4b (~3GB) | LOW | 2-concurrent FIFO queue conservative cap, monitor memory in cycle 2 smoke test |
| Latency makes operator UX poor — gemma3:e4b should make this rare | LOW | async non-blocking, message arrives "later"; UI shows "Гемма думает..." state during inference |
| 15 May deadline slip | HIGH | Slice C is explicit stretch goal; A+B is target. After Cycle 4, freeze and polish if needed |
| LLM autonomous safety violation | LOW (but high impact if occurs) | Hardcoded constraint: no engine command APIs accessible from agents/. Code review enforces. |

---

## 7. Hard stops

These STOP the cycle (not necessarily project):

- Ollama not installed/running on dev machine — STOP cycle 1 smoke
  test, surface to architect
- gemma3:e4b inference >15s for typical prompt — investigate
  Ollama config / hardware issue, may need architect intervention
- EventBus regression breaks existing tests — STOP cycle 0, revert,
  redesign
- Russian output drifts to English consistently — STOP cycle 2,
  rework prompts before cycle 3
- LLM API call wired to allow side-effects — STOP, security review

---

## 8. Architect comm-out discipline

Architect available synchronously. Surface ARCHITECT DECISION NEEDED
markers in handoffs immediately. Continue with safest interpretation:

- §2.3 EventBus: adopt (a) (foundational addition)
- §2.10 #2 GUI placement: separate Hermes overlay
- §2.10 #3 Telegram threading: reply mode
- §2.10 #4 concurrent inference: single-flight queue
- §2.10 #5 Russian: explicit in system prompt
- §2.10 #6 Ollama lifecycle: external (not Hermes-managed)

---

## 9. Per-cycle handoff template

`artifacts/handoffs/<date>-f28-cycle<N>-handoff.md`:

```markdown
# F28 Hermes cycle <N> — architect review

## Branch
feat/f28-hermes-agent at <SHA>

## Implementation
Files changed: ...
LOC: +X / -Y
Tests added: <count>

## Cycle goal achieved
[per cycle, from §3]

## Smoke test results
[real Ollama latency, output sample, memory usage]

## Audit history
| Iter | Codex | Gemini | Action |

## ARCHITECT DECISION NEEDED
[from §2.10 or new]

## Time budget remaining vs 15 May
[days remaining + assessment of A+B+C feasibility]

## Spec deviations
- None / list with rationale
```

---

## 10. Demo readiness assessment

After A+B complete (end of Cycle 4):

- ✅ Live demo: trigger alarm in mock mode → show Гемма summary
  appear in Telegram + log + GUI panel within ~10s
- ✅ Show audit log entry for that call (full context + response
  + tokens)
- ✅ Toggle agent.enabled=false, show graceful degradation
- ✅ Show config file with rate limits + slice toggles
- ✅ Show prompt template with anti-hallucination + Russian
  instruction

Demo script for award submission:

> "В CryoDAQ работает локальный AI-агент **Гемма** на основе 
> Gemma 3 e4b через Ollama. Никаких внешних API — всё на 
> лабораторном железе (M5 24GB или серверный GPU). Когда срабатывает 
> аларм или завершается эксперимент, Гемма формулирует human-
> readable summary для оператора в Telegram, операторский журнал 
> и GUI. Агент не имеет доступа к инженерным командам — только 
> текстовые каналы. Все вызовы logged в audit log для ручного 
> review. Это правильное применение local LLM в safety-critical 
> lab automation: AI как force-multiplier, не заменитель 
> инженерного решения."

---

## 11. Begin

Read this prompt fully. Verify clean master post-v0.43.0 (likely
`c44c575` or later if recent feature branches merged).

Per ORCHESTRATION v1.3 §10:
- Recon before action
- Plugin auto-load awareness
- rtk-aware verification of HEAD
- Skill registry refresh

Cycle 0 first (EventBus foundation). DO NOT skip — Cycles 1+ depend
on it.

GO.
