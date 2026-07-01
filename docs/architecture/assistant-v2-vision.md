# Assistant v2 — Architecture Vision

> Re-imagining of F28 (Гемма) from runtime narrator into a product
> family covering F5 Hermes webhook scope. Live + Sinks + Archive.
> Anti-hallucination as primary design constraint. Brand-name
> abstraction so model migrations don't require code rename.
> Phased migration over ~5-6 weeks after F28 v0.45.0 closure.

**Status:** Architecture spec, NOT implementation. Spec for individual
F-tasks branches off this document.
**Date created:** 2026-05-XX (post-Cycle-5)
**Last updated:** 2026-05-XX
**Owner:** architect (web Claude Opus 4.7) + Vladimir Fomenko

---

## 0. Why this exists

F28 (currently shipping in Cycle 5) делает Гемму runtime narrator:
alarm fires → Russian summary → Telegram + log + GUI panel. Slice
A+B+C complete with v0.45.0 release pending Cycle 6 polish.

F5 Hermes webhook было исходно отдельным треком: engine emits HTTP
POST на отдельный сервис, который consumes events and does
downstream things — Obsidian campaign notes, GraphRAG indexing,
Telegram Q&A.

**Architect decision 2026-05-XX:** F5 Hermes vision adapts into the
assistant architecture — not a separate service. Hermes deployment
overhead is not justified; existing EventBus + assistant Ollama
integration provides the foundation. Re-architect the assistant
into a product family covering all Hermes use cases.

**Result:** Assistant becomes a unified narrative + memory + query
layer over engine events.

---

## 1. Brand-name abstraction

**Critical architectural constraint:** the user-facing brand name
(currently "Гемма", named after the Gemma 3/4 model) must be
decoupled from the code structure. Migration to a different model
on more powerful hardware (e.g., a dedicated GPU box with `qwen3:32b`
or a future Mistral release) should not require any code rename.

### 1.1 Two layers

**User-facing brand** (operator perceives):
- Telegram message prefix
- Vault note frontmatter
- GUI panel label
- System prompt addressing
- Configurable via `agent.yaml: agent.brand_name`

**Code structure** (developer perceives):
- Module name: `agents/assistant/` (NOT `agents/gemma/`)
- Class names: `AssistantLiveAgent`, `AssistantSinksAgent`,
  `AssistantArchiveAgent`, `AssistantCoordinator`
- Configuration namespace: `agent` (NOT `gemma`)
- Storage paths: `data/agents/assistant/` (NOT
  `data/agents/gemma/`)

The string "Гемма" exists only as a value in `agent.yaml` and in
prompt templates as `{brand_name}` interpolation.

### 1.2 Configuration

```yaml
agent:
  enabled: true
  brand_name: "Гемма"        # operator-facing — change on model migration
  brand_emoji: "🤖"

  ollama:
    base_url: http://localhost:11434
    default_model: gemma4:e4b
    fallback_model: gemma4:e2b
    batch_model: gemma4:e4b
    timeout_s: 60
    temperature: 0.3
    num_ctx: 4096
```

### 1.3 Prompt templates use interpolation

```python
ALARM_SUMMARY_SYSTEM = """\
Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.
Твоя задача — краткий, точный summary сработавшего аларма для
оператора в Telegram.

Принципы:
- Отвечай ТОЛЬКО на русском языке.
- Не выдумывай контекст. Используй только данные ниже.
...
"""
```

`AssistantPrompts.format_system(template_id, brand_name=config.brand_name, ...)`
interpolates at call time.

### 1.4 Output prefixes

```python
prefix = f"{config.brand_emoji} {config.brand_name}: "
telegram_message = f"{prefix}{response_text}"
operator_log_entry.tag = "assistant"  # internal — never user-facing
```

### 1.5 Vault frontmatter carries brand history

```yaml
---
campaign_id: cooldown_2026-05-15
agent_brand: Гемма
agent_model: gemma4:e4b
agent_brand_history:
  - {date: 2026-05-01, brand: Гемма, model: gemma4:e4b}
  - {date: 2026-08-15, brand: Минерва, model: qwen3:32b}
last_synced: 2026-05-15
---
```

When brand changes, new entries reference the new brand. Old entries
preserved with their original brand. History accumulates.

### 1.6 Migration procedure

When migrating to a new model on different hardware:

1. Pull new model: `ollama pull qwen3:32b`
2. Edit `config/agent.yaml`:
   ```yaml
   agent:
     brand_name: "Минерва"
     brand_emoji: "🦉"
     ollama:
       default_model: qwen3:32b
   ```
3. Restart engine
4. Smoke test: trigger alarm, verify Telegram now says "🦉 Минерва: ..."
5. (Optional) Update vault note frontmatter for ongoing campaigns

Migration takes ~10 minutes. No code changes, no module renames, no
recompilation.

### 1.7 What is NOT renamed

**Historical record stays.** Commits, F-task numbers, ROADMAP entries
that say "Гемма" or "F28 Гемма" remain untouched. F28 was always
codenamed Гемма; that's part of git history. New F-tasks (F29+) use
generic "assistant" terminology in commit messages and specs.

**Audit logs use internal name.** `data/agents/assistant/audit/...`
does not change when brand changes. Internal storage = "assistant",
brand history captured in audit JSON metadata fields.

---

## 2. Three sub-systems

### 2.1 Assistant Live (existing F28)

**What:** Event-driven narrator. Subscribes to EventBus, generates
Russian commentary in real-time, dispatches to operator-facing
channels.

**Triggers (current):**
- `alarm_fired`
- `experiment_finalize` / `_stop` / `_abort`
- `sensor_anomaly_critical`
- `shift_handover_request`
- (NEW F29) `periodic_report_request`

**Outputs (current):**
- Telegram messages
- `operator_log` entries (tagged `assistant`)
- GUI insight panel (subscribes to `assistant_insight` EventBus event)

**Status:** Cycle 5 closed. F29 is the next addition.

### 2.2 Assistant Query Live (NEW, F30)

**What:** Free-text / `/ask` query handler. Operator asks a question
via Telegram; agent classifies intent, fetches live state
deterministically from engine services, formats a grounded Russian
answer in ≤15s.

**Three-step pipeline:**
1. **Intent classifier** (small LLM call, ~3-5s) — categorises query
   into one of 9 intents (current_value, eta_cooldown, eta_vacuum,
   range_stats, phase_info, alarm_status, composite_status,
   out_of_scope_historical, unknown).
2. **Deterministic fetch** (NO LLM, <1s) — dispatches to the matching
   ServiceAdapter (BrokerSnapshot, CooldownAdapter, VacuumAdapter,
   SQLiteAdapter, AlarmAdapter, ExperimentAdapter, CompositeAdapter).
3. **Russian format** (LLM call with tight scope, ~5-10s) — formats
   structured data into a conversational Russian response. Strict
   anti-hallucination: "ОТВЕТЬ ТОЛЬКО на основе данных ниже."

**Scope:** current live state only. Historical queries
(out_of_scope_historical) receive a polite refusal pointing to F33.

**Status:** Phase 1.5. Ships v0.47.0.

### 2.3 Assistant Sinks (NEW, F31)

**What:** Parallel output paths beyond Live's existing dispatch.
Each event-driven inference additionally writes to persistent sinks
for long-term archiving.

**New outputs:**
- **VaultWriter** — appends to Obsidian campaign notes per
  `experiment_id`
- **WebhookDispatcher** — HTTP POST to a configurable URL list
  (Hermes target if anyone deploys it, or Notion/Linear/external)
- **IndexQueue** — handoff to F32 RAG indexer

**Why this lives inside the assistant, not as a separate service:**
- EventBus already carries all engine events
- Ollama client + audit log infrastructure are share-able
- Avoids separate process/deployment burden
- Single configuration surface (`agent.yaml`)
- Single failure mode handling

### 2.4 Assistant Archive (NEW, F32 + F33)

**What:** Searchable memory over accumulated history. Vector
embeddings + graph relations + query interface.

**Components:**
- **Indexer (F31):** event finalize → embedding + graph relations →
  SQLite vector store + entity tables
- **Query interface (F32):** Telegram `/ask` (single-turn first),
  GUI overlay with multi-turn (later); user query → retrieval →
  grounded synthesis with mandatory citations

**Anti-hallucination as primary constraint** — see §4.

---

## 3. Component architecture

```
                    [engine + scheduler]
                            ↓
                       [EventBus]
                            ↓
                  ┌─────────┴─────────┐
                  ↓                   ↓
       [AssistantLive handlers] [AssistantSinks subs]
              ↓                       ↓
        [OllamaClient]          ┌─────┴─────┬──────────┐
              ↓                 ↓           ↓          ↓
        [OutputRouter]    [VaultWriter] [Webhook]  [IndexQueue]
              ↓                 ↓           ↓          ↓
   ┌──────────┼──────┐   [campaign      [HTTP       [bge-m3
   ↓          ↓      ↓    notes].md     POST]       embed +
[TG]    [oplog] [GUI]                                graph
                                                     update]
                                                       ↓
                                              [SQLite + sqlite-vec]
                                                       ↓
                                              ┌────────┴─────────┐
                                              ↓                  ↓
                                        [vector store]   [entity/relation
                                                            tables]
                                                       ↑
                                                       │
                                              [AssistantArchive
                                               query agent]
                                                       ↑
                                                       │
                                              [TG /ask] [GUI overlay]
```

### 3.1 Module layout (post-implementation)

```
src/cryodaq/agents/assistant/
  __init__.py
  coordinator.py             # AssistantCoordinator (top-level entry)
  config.py                  # AssistantConfig (brand_name, ollama, ...)

  live/                      # F28 (existing, refactored in Cycle 6)
    __init__.py
    agent.py                 # AssistantLiveAgent (was GemmaAgent)
    prompts.py               # uses {brand_name} interpolation
    output_router.py
    context_builder.py

  query/                     # F30 (new — Live Query Agent)
    __init__.py
    agent.py                 # AssistantQueryAgent — top-level entry
    intent_classifier.py     # LLM call → QueryIntent dataclass
    prompts.py               # INTENT_CLASSIFIER_*, FORMAT_RESPONSE_*
    router.py                # QueryIntent → ServiceAdapter dispatch
    schemas.py               # QueryIntent, FetchedData dataclasses
    adapters/
      __init__.py
      broker_snapshot.py     # LatestValueCache + lookup API
      cooldown_adapter.py    # wraps CooldownService.last_prediction
      vacuum_adapter.py      # wraps VacuumTrendPredictor.last_prediction
      sqlite_adapter.py      # range queries via existing reader
      alarm_adapter.py       # wraps AlarmEngine.active_alarms()
      experiment_adapter.py  # wraps ExperimentManager state
      composite_adapter.py   # parallel asyncio.gather of all above

  sinks/                     # F31 (new)
    __init__.py
    vault_writer.py          # writes to ~/Vault/CryoDAQ/40 Campaigns/
    webhook_dispatcher.py    # HTTP fanout to configurable URLs
    index_queue.py           # handoff to F32 indexer

  archive/                   # F32 + F33 (new)
    __init__.py
    indexer.py               # event → embed → store
    embedding_client.py      # Ollama bge-m3 wrapper
    graph_store.py           # SQLite entity/relation tables
    vector_store.py          # sqlite-vec wrapper
    retrieval.py             # query → top-K + graph traversal
    query_agent.py           # AssistantArchiveAgent — answer mode
    citation_extractor.py    # parse responses for [[wikilink]] citations

  shared/
    __init__.py
    ollama_client.py
    audit.py
    report_intro.py          # Slice C, refactored from current location
```

### 3.2 EventBus subscriptions

| Component | Subscribes to | Action |
|---|---|---|
| AssistantLiveAgent | `alarm_fired`, `experiment_*`, `sensor_anomaly_critical`, `shift_handover_request`, `periodic_report_request` | Generate narrative, dispatch to user-facing channels |
| VaultWriter | (same as Live) PLUS `phase_transition`, `calibration_applied`, `operator_log_entry` | Append to per-campaign vault note |
| WebhookDispatcher | All events (filterable per URL) | HTTP POST to configured URLs |
| IndexQueue | `experiment_finalize` PLUS each `assistant_inference_completed` | Embed + index |

Multiple subscribers same event = independent processing, no shared
mutable state.

---

## 4. Anti-hallucination architecture

This is the core engineering challenge for Phase 3 (Archive). Six
layers of defense.

### Layer 1 — Citation-mandatory prompts (Archive query)

Every Archive response MUST include `[[campaign_note_id]]` wikilink
references for each factual claim. Hardcoded in system prompt:

```
Каждое утверждение должно ссылаться на источник в формате
[[campaign_id]] или [[event_id]]. Утверждения без ссылок запрещены.

Если данных в полученном контексте недостаточно для какого-то
утверждения — не делай это утверждение. Скажи "в архиве недостаточно
данных для ответа на эту часть вопроса".
```

Post-processing step (`citation_extractor.py`) extracts citations
and validates they exist in vault. Responses with missing or invalid
citations are rejected → user gets a clean refusal, not a fabricated
answer.

### Layer 2 — Retrieval transparency

Before generating an answer, the bot shows retrieved chunks to the
user:

```
Гемма нашла 3 релевантные записи:
- [[cooldown_2026-04-22]] (similarity 0.89)
- [[cooldown_2026-04-15]] (similarity 0.81)
- [[cooldown_2026-04-29]] (similarity 0.77)

Использую эти данные для ответа. Жди ~30s.
```

User sees what data is being synthesized. Spot-checks possible.

### Layer 3 — Confidence indicators

Output structured by confidence level:

| Confidence | Trigger | Output style |
|---|---|---|
| High | 3+ sources agree, single answer | Direct answer |
| Medium | 1-2 sources OR sources conflict | "По одному источнику X, но это может не покрывать все случаи" |
| Low | No direct match, only tangential | "Прямого ответа в архиве не найдено. Возможно похожий случай — [[link]]" |

Confidence determined post-retrieval based on similarity scores +
source count.

### Layer 4 — Read-only query mode

Query interface NEVER writes to vault, indices, or persistent state.
Only audit log entries (separate path). Hallucinated content stays
in single Telegram message — does not pollute the archive.

### Layer 5 — Scope-limited query

System prompt hardcoded scope:

```
Ты отвечаешь ТОЛЬКО на вопросы об экспериментах, калибровках,
алармах и операторских записях из архива CryoDAQ.

Out-of-scope:
- Общие знания (что такое thermal conductance) → "вопрос вне архива"
- Hypotheticals (что было бы если) → "не отвечаю на гипотетические"
- Predictions (предскажи следующий cooldown) → "обратись к
  cooldown predictor"
```

Out-of-scope queries get refusal, not attempted answer.

### Layer 6 — Spot-check discipline

Audit log records every query response. Architect (Vladimir)
periodically reviews random 10% sample, classifies REAL/HALLUCINATION
per ORCHESTRATION v1.3 §14.6.

After N=20+ verified samples → empirical hallucination rate per
query type → adjustments to prompts / retrieval / scope.

This is **identical pattern** to existing calibration log
discipline — not new methodology, just applied to a new agent
surface.

### Net: layered defense

No single layer is sufficient. Combined:
1. **Structural** — citations required
2. **Transparent** — retrieval shown
3. **Honest** — confidence indicators
4. **Read-only** — no contamination
5. **Scope-bounded** — refusal default for out-of-scope
6. **Verifiable** — audit + spot-check

If any layer caught the hallucination, the response was not
user-misleading. If multiple layers fail simultaneously, the audit
log preserves evidence for post-hoc correction.

---

## 5. Phased implementation

### Phase 0 (current): F28 v0.45.0 ship

**Cycle 5 (closed) + Cycle 6 polish + tag.** Cycle 6 includes the
**module rename and brand abstraction** described in §1.

### Phase 1: F29 — Periodic narrative reports (~250 LOC, 1 cycle)

**Standalone trigger expansion in Live.** No new architecture
needed.

**Spec:**
- Engine timer task publishes `periodic_report_request` every N
  minutes (configurable, default 60)
- New handler `_handle_periodic_report` aggregates last-N-minutes
  events
- New prompt template `PERIODIC_REPORT_SYSTEM/USER` (Russian,
  100-200 words, conversational)
- Filter: skip if `min_events_for_dispatch` not met (don't spam
  on idle hours)

**Config:**
```yaml
agent:
  triggers:
    periodic_report:
      enabled: true
      interval_minutes: 60
      skip_if_idle: true
      min_events_for_dispatch: 1
```

**Ship:** v0.46.1 ✅

### Phase 1.5: F30 — Live Query Agent (~600 LOC, 1 cycle)

**New sub-system: AssistantQueryLive.** Operator asks questions
about current engine state via Telegram free-text or `/ask`.

Three-step pipeline (see §2.2 for detail):
1. Intent classifier (gemma4:e2b, temperature=0.1) → QueryIntent
2. Deterministic service adapter fetch (NO LLM)
3. Russian format LLM call (gemma4:e2b, temperature=0.3)

9 intent categories. 6 service adapters + composite.
Total latency target ≤15s p50.

**Spec:** `CC_PROMPT_F30_LIVE_QUERY_AGENT.md`

**Ship:** v0.47.0

### Phase 2: F31 + F32 — Sinks + RAG indexer (~1200 LOC, 4-5 cycles)

Combined because they share embedding pipeline and module structure.

#### F31 — Sinks subsystem

**Cycle 1:** VaultWriter
- Subscribes to EventBus
- Per-experiment campaign note creation (frontmatter + sections)
- Append-only updates per event type
- Cross-reference detection (when assistant spots patterns, add
  `[[wikilinks]]`)
- Tests

**Cycle 2:** WebhookDispatcher
- Configurable URL list in `agent.yaml`
- Async HTTP POST with retry on failure
- HMAC signature for non-localhost URLs
- Failure logging without crashing engine
- Tests

#### F32 — RAG indexer

**Cycle 3:** Storage layer
- sqlite-vec extension setup in SQLite
- Entity tables (`entities`, `relations`) schema
- Embedding client (Ollama bge-m3 wrapper)
- Tests

**Cycle 4:** Indexing pipeline
- IndexQueue subscribes to event types (`experiment_finalize`,
  `assistant_inference_completed`)
- Embed text content + metadata
- Extract entities + relations from event payload
- Write to vector store + entity tables
- Tests

**Cycle 5:** Initial backfill
- One-time script: read existing experiments archive
  (`data/experiments/<id>/`) → embed + index
- Skipped in production deploy (manual run by architect command)
- Tests

**Ship:** v0.48.0

### Phase 3: F33 — Archive query interface (~700 LOC, 3-4 cycles)

#### Cycle 1: Retrieval layer
- `retrieval.py` — query → embed → vector top-K + graph traversal
- Returns ranked chunks + entity context
- Tests

#### Cycle 2: Answer generation
- `query_agent.py` — AssistantArchiveAgent with answer-mode prompts
- Citation enforcement (Layer 1)
- Confidence calibration (Layer 3)
- Scope refusal (Layer 5)
- Tests

#### Cycle 3: Telegram integration
- `/ask <query>` handler in existing bot
- Retrieval transparency reply (Layer 2)
- Single-turn — operator iterates manually if needed
- Tests + smoke

#### Cycle 4: Audit + spot-check infrastructure
- Query audit log extension
- Random sampling helper for architect spot-check
- README documentation
- Tests

**Ship:** v0.49.0

### Phase 4: GUI chat overlay (deferred polish)

After v0.49.0 stable, add GUI overlay for conversational mode
(multi-turn, history). Not critical, ship after operator feedback
on F33 Telegram interface.

**Ship:** tbd (optional, post-v0.49.0)

---

## 6. Migration path (Cycle 6 polish work)

**Code re-organization happens in Cycle 6** (current next step):

### 6.1 Module moves

```
src/cryodaq/agents/gemma.py       →  src/cryodaq/agents/assistant/live/agent.py
src/cryodaq/agents/prompts.py     →  src/cryodaq/agents/assistant/live/prompts.py
src/cryodaq/agents/output_router.py → src/cryodaq/agents/assistant/live/output_router.py
src/cryodaq/agents/context_builder.py → src/cryodaq/agents/assistant/live/context_builder.py
src/cryodaq/agents/ollama_client.py → src/cryodaq/agents/assistant/shared/ollama_client.py
src/cryodaq/agents/audit.py       →  src/cryodaq/agents/assistant/shared/audit.py
src/cryodaq/agents/report_intro.py → src/cryodaq/agents/assistant/shared/report_intro.py
```

Use `git mv` to preserve history.

### 6.2 Class renames

- `GemmaAgent` → `AssistantLiveAgent`
- `GemmaConfig` → `AssistantConfig`

Class files updated; existing tests updated to import new names.

### 6.3 Storage path change

```
data/agents/gemma/audit/...  →  data/agents/assistant/audit/...
```

Migration: on first start under new path, copy any existing
`data/agents/gemma/audit/` contents to new location, then
`data/agents/gemma/` removed by architect manually (NEVER auto-delete).

### 6.4 Config schema migration

```yaml
# Before (F28 era)
gemma:
  enabled: true
  ollama: {...}
  triggers: {...}
  outputs: {...}
  rate_limit: {...}
  slices: {...}
  audit: {...}

# After (Phase 0+)
agent:
  enabled: true
  brand_name: "Гемма"
  brand_emoji: "🤖"
  ollama: {...}
  triggers: {...}
  outputs: {...}
  rate_limit: {...}
  slices: {...}
  audit: {...}
```

**Backward compatibility:** config loader auto-maps old `gemma.*`
namespace to new `agent.*` for one release cycle (v0.45.0). Warning
logged on legacy config use. v0.46.0 removes legacy mapping.

### 6.5 Prompt template interpolation

```python
# Before
ALARM_SUMMARY_SYSTEM = "Ты — Гемма, ассистент..."

# After
ALARM_SUMMARY_SYSTEM = "Ты — {brand_name}, ассистент..."

# At call site
system = ALARM_SUMMARY_SYSTEM.format(brand_name=config.brand_name)
```

All prompt templates updated. New test: verify brand string appears
in formatted output and is sourced from config, not hardcoded.

### 6.6 Output prefixes

```python
# Before
prefix = "🤖 Гемма: "

# After
prefix = f"{config.brand_emoji} {config.brand_name}: "
```

### 6.7 GUI panel

```python
# Before
panel = GemmaInsightPanel(parent=...)
panel.setWindowTitle("Гемма")

# After
panel = AssistantInsightPanel(parent=..., brand_name=config.brand_name, brand_emoji=config.brand_emoji)
panel.setWindowTitle(config.brand_name)
```

Panel internal name unchanged (`AssistantInsightPanel`); display
text comes from config.

### 6.8 EventBus event_type strings

```
gemma_insight  →  assistant_insight
```

Subscribers updated in same Cycle 6 commit.

---

## 7. Storage choices with rationale

### 7.1 sqlite-vec (vector store)

- ✅ In-process, no separate service
- ✅ Fits CryoDAQ SQLite-heavy stack
- ✅ Mature enough for laboratory scale (thousands not millions of
  documents)
- ✅ Migration to LanceDB/ChromaDB trivial if scale grows

### 7.2 SQLite tables (graph)

```sql
CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,    -- experiment | calibration | alarm | operator | instrument
    label TEXT NOT NULL,           -- human-readable, e.g. "cooldown_2026-04-22"
    metadata_json TEXT,
    embedding_id INTEGER,          -- FK to sqlite-vec table
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,   -- HAS_PHASE | USED_CALIBRATION | TRIGGERED_ALARM | OPERATED_BY
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (from_entity_id) REFERENCES entities(entity_id),
    FOREIGN KEY (to_entity_id) REFERENCES entities(entity_id)
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_relations_from ON relations(from_entity_id, relation_type);
CREATE INDEX idx_relations_to ON relations(to_entity_id, relation_type);
```

Graph traversal via recursive CTE queries — sufficient for
laboratory scale. Neo4j overhead not justified.

### 7.3 bge-m3 (embedding model)

- ✅ Multilingual (Russian operator queries)
- ✅ Runs through Ollama (existing infrastructure)
- ✅ Good quality for technical text
- Verify in Phase 2 Cycle 3 smoke test

---

## 8. Periodic reports + RAG enrichment (post-F32)

After F32 indexer ships, F29 periodic reports gain RAG context
awareness:

**Before F32:**
> За последний час: alarm threshold-T1 (295.4K). Pressure стабилен.
> Other channels nominal.

**After F32:**
> За последний час: alarm threshold-T1 (295.4K). Pressure стабилен.
> Other channels nominal.
>
> Похожий случай: [[cooldown_2026-04-15]] — там alarm на T1
> произошёл на той же фазе, причиной была потеря контакта
> радиационного экрана.

This is a **post-Phase-2 enhancement** to the existing F29 prompt
template. Add retrieval call to periodic report context builder; if
relevant past events found, include as advisory section. Layer 1-3
anti-hallucination apply.

Effort: ~80 LOC + spec'd in Cycle 1 after F32 ships.

---

## 9. F-task summary table

| F | Name | Effort | Cycles | Phase | Ships in |
|---|---|---|---|---|---|
| F28 | Gemma Live (closed) | L | 6 | Phase 0 | v0.45.0 |
| F29 | Periodic narrative reports | S-M | 1 | Phase 1 | v0.46.1 |
| F30 | Live Query Agent (current-state queries) | M | 1 | Phase 1.5 | v0.47.0 |
| F31 | Assistant Sinks (vault + webhook) | M | 2 | Phase 2 | v0.48.0 |
| F32 | RAG indexer | M | 3 | Phase 2 | v0.48.0 |
| F33 | Assistant Archive query interface | M+ | 4 | Phase 3 | v0.49.0 |
| F34 | (deferred) GUI chat overlay | M | 2-3 | Phase 4 | tbd |

**Retire from ROADMAP:**
- ❌ F5 (Hermes webhook) — adapted into F31 WebhookDispatcher
- ❌ F9 (TIM auto-report) — existing analyzer sufficient (per Vladimir
  decision 2026-05-XX)

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| sqlite-vec instability on Russian text | MEDIUM | Smoke test Phase 2 Cycle 3; fallback to ChromaDB if blocking |
| bge-m3 Russian quality insufficient for retrieval | MEDIUM | A/B test multiple embedding models in Phase 2 Cycle 3 smoke |
| Hallucination layers fail despite 6-layer defense | HIGH | Spot-check discipline mandatory; halt rollout if rate >5% in initial sample |
| Vault writer corrupts existing notes | HIGH | Read-modify-write atomic via temp file + rename; backup vault before F31 ship |
| Webhook fanout floods external systems | LOW | Rate limit per URL; configurable batching |
| Indexing latency blocks engine | MEDIUM | IndexQueue async, dropped on overflow with warning |
| Scope creep — operator wants chat-style multi-turn | MEDIUM | Explicit single-turn for Phase 3; multi-turn deferred to Phase 4 |
| Webhook target for Hermes never deployed | LOW | F31 still useful (vault writer alone justified); webhook just unused |
| Brand-name interpolation breaks on edge cases (special chars in name) | LOW | Restrict brand_name to ASCII + Cyrillic letters; tests cover Cyrillic |

---

## 11. Verification milestones

### After F28 v0.45.0 ship (Cycle 6)
- All F28 tests still passing after module rename
- Brand abstraction smoke test: change `brand_name` in config, restart,
  verify Telegram says new brand
- Migration path tested: old `gemma.*` config still loads with warning

### After F29 ship
- Real periodic report appears in Telegram every hour during active
  experiment
- Skip on idle hour verified
- Russian quality maintained per F28 levels

### After F30 ship
- Free-text Telegram queries return grounded Russian answers in ≤15s
- `/ask` command works identically to free-text
- Intent classifier correctly categorises 7 representative query patterns
- Out-of-scope (historical, general) queries get polite refusal
- No regressions in existing F29 periodic reports or F28 Live dispatch

### After F31 ship
- Vault `~/Vault/CryoDAQ/40 Campaigns/<exp_id>.md` populated with
  structured sections
- Webhook to localhost test endpoint receives all events
- HMAC signature verified for external URL test
- No regressions in existing F28/F29/F30 dispatch

### After F32 ship
- 1 month of accumulated history indexed
- Vector search returns relevant chunks for test queries
- Graph traversal works for "what calibrations were applied to sample
  X"

### After F33 ship
- `/ask <historical>` command returns grounded answer with citations
- Retrieval transparency layer visible in reply
- Out-of-scope queries refused
- Spot-check audit shows <5% hallucination rate in N=20 sample

---

## 12. Open architectural questions

To surface to architect (Vladimir) before/during implementation:

1. **Vault note structure** — single per-campaign note OR per-event
   mini-notes with link aggregation?
   *Architect default:* per-campaign with append-only sections.
   Verify in F30 Cycle 1 implementation.

2. **Webhook authentication** — HMAC signature? Bearer token? None
   (trust local network)?
   *Architect default:* HMAC for any external URL, none for
   `localhost:*`. Configurable per URL.

3. **Embedding refresh strategy** — re-embed historical entries when
   prompts/templates change?
   *Architect default:* append-only, no retroactive re-embed.
   Document strategy in README.

4. **Query rate limiting** — per-user, per-time, both?
   *Architect default:* 30 queries/hour shared bucket (lab is small
   team).

5. **Out-of-scope topic — calibration/physics knowledge** — should
   query refuse "что такое Chebyshev fit?" entirely, or try to answer
   based on indexed code/docs?
   *Architect default:* refuse — domain knowledge is out-of-scope;
   query is for archive content only.

6. **Audit log for queries** — same audit/<date>/<id>.json pattern?
   *Architect default:* yes, identical pattern; reuse existing
   infrastructure.

7. **Brand name in vault filenames** — should `~/Vault/CryoDAQ/10
   Subsystems/Гемма agent.md` rename to `Assistant agent.md` on brand
   migration?
   *Architect default:* keep historical filename, add aliases section
   in note frontmatter listing all past brand names. New campaigns
   use current brand.

---

## 13. Next concrete actions

In priority order:

1. **F28 v0.45.0 ship** — Cycle 6 polish (module rename + brand
   abstraction + docs + vault note + audit retention) → tag v0.45.0
2. **F29 spec** writing once v0.45.0 tagged (~30 min architect work)
3. **F29 ship** v0.46.0 (~1-2 days)
4. **Architect-Vladimir conversation** about Phase 2 details (vault
   note structure, webhook URLs, embedding model verification plan,
   open questions §12)
5. **F30 + F31 spec** combined writing (~2-3 hours architect work)
6. **F30 + F31 implementation** Cycles 0-5 (~1-1.5 weeks)
7. **F32 spec** writing (~1-2 hours)
8. **F32 implementation** Cycles 1-4 (~1-1.5 weeks)

Total timeline: **~4-5 weeks post-v0.45.0** for Phases 1-3 ship.

---

## 14. Document maintenance

This document is **living architecture spec.** Updates required when:
- New F-task added to assistant family
- Architectural decision changed (storage, embedding model, scope)
- Anti-hallucination strategy modified
- F-task split/merge happens
- Brand migration occurs (record in §1.5 brand history)

---

**End of document.**
