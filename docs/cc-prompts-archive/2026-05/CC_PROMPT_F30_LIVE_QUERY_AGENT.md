# F30 — Live Query Agent

> Гемма receives free-text or `/ask` queries from Telegram, classifies
> intent, fetches LIVE state from engine services deterministically,
> formats Russian response. NOT historical archive (that's F33+).
>
> Reference: `artifacts/architecture/assistant-v2-vision.md` §2.4
> (will be added). ROADMAP entry: F30 (post-renumbering — see §0.1).
>
> Goal: operator на телефоне может спросить "что по ETA вакуума",
> "как скоро охлаждение", "в каком диапазоне давление" и получить
> grounded Russian answer за <15s.

---

## 0. Operating posture

- Architect synchronously available
- Branch: `feat/f30-live-query-agent`
- Ships: v0.47.0
- Effort: M (~600 LOC code + ~250 tests = ~850 LOC total)
- Verifier scaling per ORCHESTRATION v1.4 §16.3:
  foundational change (new agent module + service adapters) →
  multi-verifier wave (Codex + GLM + Qwen3 minimum)

### 0.1 ROADMAP renumbering

Per architect decision 2026-05-XX, F30+ shift forward by one due
to Live Query Agent insertion. Update `ROADMAP.md`:

| Old | New | Name |
|---|---|---|
| F30 | F31 | Sinks (vault writer + webhook) |
| F31 | F32 | RAG indexer |
| F32 | F33 | Archive query (historical, RAG) |
| F33 | F34 | GUI chat overlay |

F30 (NEW) = Live Query Agent.

Update `artifacts/architecture/assistant-v2-vision.md` §2 to add
new sub-system `Assistant Query Live` between `Live` and `Sinks`.
F-task summary table in §9 reflects renumbering.

This change happens **first** as Phase 0 of this cycle, before
any code work, so commit history references stay clean.

---

## 1. Architecture

### 1.1 Three-step pipeline

```
operator query (Telegram free-text or /ask)
        ↓
[1] Intent classifier (small LLM call, ~3-5s)
    Input: query text
    Output: structured intent
      { category: enum,
        target_channels: list[str] | None,
        time_window_minutes: int | None,
        quantity: enum }
        ↓
[2] Deterministic data fetch (NO LLM, <1s)
    Per category: call corresponding ServiceAdapter
      - current_value → BrokerSnapshot.latest(channels)
      - eta_cooldown → CooldownAdapter.eta()
      - eta_vacuum → VacuumAdapter.eta_to_target(target_mbar)
      - range_stats → SQLiteAdapter.range_stats(channel, window)
      - phase → ExperimentAdapter.phase_info()
      - alarm → AlarmAdapter.active()
      - status → composite of all above
    Output: structured data dict
        ↓
[3] Russian format (LLM call with TIGHT scope, ~5-10s)
    System prompt: "ОТВЕТЬ ТОЛЬКО на основе данных ниже.
                    Не додумывай. Если данных нет — скажи 'нет данных'."
    Input: query + structured data
    Output: Russian NL response
        ↓
audit log + Telegram reply
```

Total latency target: ≤ 15s p50, ≤ 25s p95.

### 1.2 Intent categories

```python
class QueryCategory(Enum):
    CURRENT_VALUE = "current_value"      # "какая сейчас T1?"
    ETA_COOLDOWN = "eta_cooldown"         # "когда охлаждение?"
    ETA_VACUUM = "eta_vacuum"             # "ETA вакуума?"
    RANGE_STATS = "range_stats"           # "в каком диапазоне P?"
    PHASE_INFO = "phase_info"             # "в какой фазе?"
    ALARM_STATUS = "alarm_status"         # "есть ли тревоги?"
    COMPOSITE_STATUS = "composite_status" # "что сейчас?" / "как дела?"
    OUT_OF_SCOPE_HISTORICAL = "out_of_scope_historical"  # "что было вчера?"
    OUT_OF_SCOPE_GENERAL = "out_of_scope_general"        # "что такое вакуум?"
    UNKNOWN = "unknown"                   # cannot classify
```

OUT_OF_SCOPE → polite refusal pointing to current capabilities
or future F33 archive query.

### 1.3 Module layout

```
src/cryodaq/agents/assistant/query/
  __init__.py
  agent.py                  # AssistantQueryAgent — top-level entry
  intent_classifier.py      # LLM call → QueryIntent dataclass
  prompts.py                # INTENT_CLASSIFIER_*, FORMAT_RESPONSE_*
  router.py                 # QueryIntent → ServiceAdapter dispatch
  adapters/
    __init__.py
    broker_snapshot.py      # LatestValueCache + lookup API
    cooldown_adapter.py     # wraps CooldownService.last_prediction
    vacuum_adapter.py       # wraps VacuumTrendPredictor.last_prediction
    sqlite_adapter.py       # range queries via existing reader
    alarm_adapter.py        # wraps AlarmEngine.active_alarms()
    experiment_adapter.py   # wraps ExperimentManager state
  schemas.py                # QueryIntent, FetchedData dataclasses

src/cryodaq/agents/assistant/shared/
  (existing — query reuses ollama_client, audit, etc)
```

### 1.4 BrokerSnapshot — new infrastructure

Existing `DataBroker` is pure pub/sub — no "latest per channel"
snapshot. Add lightweight subscriber that caches latest per
channel:

```python
# In src/cryodaq/agents/assistant/query/adapters/broker_snapshot.py
class BrokerSnapshot:
    """Subscribes to DataBroker, maintains latest-per-channel cache.
    
    Read-only consumer pattern. No state mutation.
    """
    def __init__(self, broker: DataBroker) -> None:
        self._latest: dict[str, Reading] = {}
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[Reading] | None = None
        self._task: asyncio.Task | None = None
    
    async def start(self) -> None:
        self._queue = await self._broker.subscribe(
            "assistant_query_snapshot", maxsize=1000
        )
        self._task = asyncio.create_task(self._consume_loop())
    
    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self._broker.unsubscribe("assistant_query_snapshot")
    
    async def _consume_loop(self) -> None:
        while True:
            try:
                reading = await self._queue.get()
                async with self._lock:
                    self._latest[reading.channel] = reading
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("BrokerSnapshot consume error: %s", exc)
    
    async def latest(self, channel: str) -> Reading | None:
        async with self._lock:
            return self._latest.get(channel)
    
    async def latest_all(self) -> dict[str, Reading]:
        async with self._lock:
            return dict(self._latest)
    
    async def latest_age_s(self, channel: str) -> float | None:
        reading = await self.latest(channel)
        if reading is None:
            return None
        return (datetime.now(UTC) - reading.timestamp).total_seconds()
```

### 1.5 CooldownAdapter — wraps existing service

```python
class CooldownAdapter:
    """Reads CooldownService cached prediction. No new computation.
    
    CooldownService publishes DerivedMetric every 30s. We cache the
    latest. Or call service.last_prediction() if API exists.
    """
    def __init__(self, cooldown_service: CooldownService | None) -> None:
        self._service = cooldown_service
    
    async def eta(self) -> CooldownETA | None:
        if self._service is None:
            return None
        # Read cached prediction from service
        pred = self._service.last_prediction()
        if pred is None:
            return None
        return CooldownETA(
            t_remaining_hours=pred.t_remaining_hours,
            t_remaining_low_68=pred.t_remaining_low_68,
            t_remaining_high_68=pred.t_remaining_high_68,
            progress=pred.progress,
            phase=pred.phase,
            n_references=pred.n_references,
            cooldown_active=pred.metadata.get("cooldown_active", False),
        )
```

If `CooldownService.last_prediction()` API doesn't exist —
add it as part of this cycle (small ~10 LOC addition to
existing service to expose cached state). Verify during recon.

### 1.6 VacuumAdapter — wraps existing predictor

Similar pattern. Need to verify `VacuumTrendPredictor.last_prediction()`
API or equivalent. If service has periodic update loop, cache
last result. Surface as `last_prediction()` method.

```python
class VacuumAdapter:
    async def eta_to_target(self, target_mbar: float) -> VacuumETA | None:
        pred = self._service.last_prediction()
        if pred is None:
            return None
        # Pred returns eta_targets: dict[str, float | None]
        # where keys are stringified targets like "1e-06"
        target_key = f"{target_mbar:.0e}"  # may need format adjustment
        eta_seconds = pred.eta_targets.get(target_key)
        return VacuumETA(
            current_mbar=...,  # from BrokerSnapshot
            eta_seconds=eta_seconds,
            target_mbar=target_mbar,
            trend=pred.trend,
            confidence=pred.confidence,
        )
```

### 1.7 SQLiteAdapter — range stats

```python
class SQLiteAdapter:
    """Range queries on readings table for window statistics."""
    
    def __init__(self, sqlite_reader: Any) -> None:
        self._reader = sqlite_reader
    
    async def range_stats(
        self,
        channel: str,
        window_minutes: int,
    ) -> RangeStats | None:
        end_ts = datetime.now(UTC).timestamp()
        start_ts = end_ts - window_minutes * 60
        readings = await self._reader.get_readings(
            channel=channel,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=10_000,
        )
        if not readings:
            return None
        values = [r.value for r in readings]
        return RangeStats(
            channel=channel,
            window_minutes=window_minutes,
            n_samples=len(values),
            min_value=min(values),
            max_value=max(values),
            mean_value=statistics.mean(values),
            std_value=statistics.stdev(values) if len(values) > 1 else 0.0,
            unit=readings[0].unit,
        )
```

### 1.8 AlarmAdapter, ExperimentAdapter — thin wrappers

```python
class AlarmAdapter:
    def __init__(self, alarm_engine: AlarmEngine) -> None:
        self._engine = alarm_engine
    
    async def active(self) -> list[ActiveAlarmInfo]:
        return [
            ActiveAlarmInfo(
                alarm_id=a.alarm_id,
                level=a.level.name,
                channels=a.channels,
                values=a.last_values,
                triggered_at=a.triggered_at,
            )
            for a in self._engine.active_alarms()
        ]


class ExperimentAdapter:
    def __init__(self, em: ExperimentManager) -> None:
        self._em = em
    
    async def status(self) -> ExperimentStatus | None:
        if not self._em.active_experiment_id:
            return None
        active = self._em.active_experiment
        phase_age_s = ...  # compute time in current phase
        return ExperimentStatus(
            experiment_id=active.experiment_id,
            phase=self._em.get_current_phase(),
            phase_started_at=...,
            time_in_phase_s=phase_age_s,
            experiment_age_s=...,
            target_temp=active.target_temp,
            sample_id=active.sample_id,
        )
```

### 1.9 CompositeStatusAdapter

```python
class CompositeStatusAdapter:
    """For 'что сейчас?' / 'status' queries."""
    
    def __init__(self, *, broker_snapshot, cooldown, vacuum, alarms,
                 experiment, sqlite) -> None:
        ...
    
    async def status(self) -> CompositeStatus:
        # Fetch all in parallel via asyncio.gather
        snapshot, cd_eta, vac_eta, active_alarms, exp_status = (
            await asyncio.gather(
                self._broker_snapshot.latest_all(),
                self._cooldown.eta(),
                self._vacuum.eta_to_target(1e-6),
                self._alarms.active(),
                self._experiment.status(),
                return_exceptions=True,
            )
        )
        return CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=exp_status if not isinstance(exp_status, Exception) else None,
            cooldown_eta=cd_eta if not isinstance(cd_eta, Exception) else None,
            vacuum_eta=vac_eta if not isinstance(vac_eta, Exception) else None,
            active_alarms=active_alarms if not isinstance(active_alarms, Exception) else [],
            key_temperatures={
                "T_cold": snapshot.get("T_cold").value if "T_cold" in snapshot else None,
                "T_warm": snapshot.get("T_warm").value if "T_warm" in snapshot else None,
                # ... per channels.yaml
            },
            current_pressure=snapshot.get("pressure_chamber").value 
                if "pressure_chamber" in snapshot else None,
        )
```

Parallel fetch keeps latency bounded. Exception per-adapter
graceful (one service failure doesn't kill whole status).

---

## 2. Prompts

### 2.1 Intent classifier

```python
INTENT_CLASSIFIER_SYSTEM = """\
Ты — классификатор запросов оператора криогенной лаборатории.
Твоя задача: получить запрос, вернуть СТРОГО JSON со схемой:

{{
  "category": "<one of: current_value | eta_cooldown | eta_vacuum | range_stats | phase_info | alarm_status | composite_status | out_of_scope_historical | out_of_scope_general | unknown>",
  "target_channels": ["list of channel names mentioned in query, or null"],
  "time_window_minutes": <int or null>,
  "quantity": "<short description of what's asked>"
}}

Правила классификации:
- "что сейчас", "как дела", "статус" → composite_status
- "ETA охлаждения", "когда 4К", "сколько до 4К" → eta_cooldown
- "ETA вакуума", "когда 1e-6", "сколько до 10⁻⁶" → eta_vacuum
- "какая T1", "температура T1" → current_value
- "в каком диапазоне P", "колебания давления" → range_stats
- "в какой фазе", "фаза эксперимента" → phase_info
- "есть ли тревоги", "active alarms" → alarm_status
- "что было вчера", "история", "последний месяц" → out_of_scope_historical
- "что такое X", "как работает Y" (вопросы знаний) → out_of_scope_general
- Не можешь классифицировать → unknown

ВЕРНИ ТОЛЬКО JSON. Никаких пояснений.
"""

INTENT_CLASSIFIER_USER = """\
Запрос оператора: {query}

JSON:
"""
```

Use `gemma4:e2b` model with `temperature=0.1` (low for structured
output). Parse JSON; fallback to UNKNOWN on parse failure.

### 2.2 Format response prompts

Per-category templates. All share strict anti-hallucination rule.

```python
FORMAT_RESPONSE_SYSTEM = """\
Ты — {brand_name}, ассистент в криогенной лаборатории. Получил запрос
оператора и СТРУКТУРИРОВАННЫЕ ДАННЫЕ от engine.

КРИТИЧНО:
- Ответь ТОЛЬКО на основе данных ниже.
- НЕ ДОДУМЫВАЙ ничего сверх данных.
- Если данных нет (None / null / отсутствует) — честно скажи
  "нет данных" или "сервис недоступен".
- Числа приводи с правильной precision (температуры: 0.01 K,
  давление: научная нотация, время: ч:мин).
- Тон conversational, дружелюбный, краткий.
- Длина 1-3 предложения для простых запросов, 3-5 для composite_status.
- Никакого LaTeX. Только Unicode (→ ← α β µ Ω).
- Только русский язык.

Если ответить полноценно невозможно — скажи это явно.
"""


FORMAT_CURRENT_VALUE_USER = """\
Запрос: {query}

Текущие значения каналов:
{channel_values_text}

Возраст последнего показания (старше 60s?):
{staleness_text}

Сгенерируй краткий ответ.
"""


FORMAT_ETA_COOLDOWN_USER = """\
Запрос: {query}

Прогноз охлаждения:
- T_cold сейчас: {t_cold} K
- Прогресс: {progress_pct:.1f}%
- Фаза: {phase}
- Осталось до 4К: {t_remaining_str} (CI 68%: {ci_low}-{ci_high} ч)
- Кривых в ансамбле: {n_references}
- Cooldown активен: {cooldown_active}

Если cooldown не активен или прогноза нет — честно скажи.
"""


FORMAT_ETA_VACUUM_USER = """\
Запрос: {query}

Прогноз вакуума:
- P сейчас: {current_mbar:.2e} mbar
- Цель: {target_mbar:.0e} mbar
- ETA до цели: {eta_str}
- Тренд: {trend}
- Уверенность фита (R²): {confidence:.2f}

Если ETA = None — значит модель ещё не сошлась или цель не
достижима по текущему тренду. Так и скажи.
"""


FORMAT_RANGE_STATS_USER = """\
Запрос: {query}

Статистика канала {channel} за последние {window_minutes} минут:
- Точек: {n_samples}
- Min: {min_value:.4g} {unit}
- Max: {max_value:.4g} {unit}
- Среднее: {mean_value:.4g} {unit}
- σ: {std_value:.4g} {unit}

Сгенерируй ответ. Опиши диапазон и стабильность.
"""


FORMAT_COMPOSITE_STATUS_USER = """\
Запрос: {query}

Полный статус системы:

Эксперимент: {experiment_text}
Фаза: {phase_text}
Ключевые температуры: {temps_text}
Давление: {pressure_text}
ETA охлаждения: {cooldown_eta_text}
ETA вакуума (до 10⁻⁶): {vacuum_eta_text}
Активные тревоги: {alarms_text}

Сгенерируй краткую сводку (3-5 предложений).
"""


FORMAT_OUT_OF_SCOPE_HISTORICAL = """\
Запрос: {query}

Это вопрос про историю / архив. Live Query Agent (Гемма) сейчас
работает только с текущим состоянием системы.

Скажи оператору что исторические запросы будут добавлены в F33
(после v0.49.0 ориентировочно). Сейчас доступны:
- Текущие значения (current state)
- ETA охлаждения / вакуума
- Диапазон статистики за последние N минут
- Активные тревоги
- Фаза эксперимента

Будь дружелюбным.
"""


FORMAT_OUT_OF_SCOPE_GENERAL = """\
Запрос: {query}

Это общий / knowledge вопрос. Гемма не отвечает на общие вопросы
по physics / engineering — только на запросы по текущему состоянию
системы CryoDAQ.

Скажи это вежливо. Предложи операторские команды если уместно.
"""
```

### 2.3 Brand interpolation

All system prompts use `{brand_name}` per Cycle 6 brand abstraction.
`format_with_brand(template, config)` helper from existing codebase.

---

## 3. Telegram integration

### 3.1 Free-text handler

Update `TelegramCommandBot._handle_message` to detect non-command
messages (no leading `/`):

```python
async def _handle_text(self, message: dict) -> None:
    """Free-text query → AssistantQueryAgent."""
    text = message.get("text", "").strip()
    chat_id = message["chat"]["id"]
    
    # Skip empty, command, or non-allowed
    if not text or text.startswith("/"):
        return
    if chat_id not in self._allowed_ids:
        # Optional: send "доступ ограничен" reply
        return
    
    # Dispatch to query agent (if configured)
    if self._query_agent is None:
        # Stub fallback (per v0.46.1)
        await self._send_message(chat_id, 
            "Я понимаю только slash-команды. /help для списка.")
        return
    
    try:
        response = await asyncio.wait_for(
            self._query_agent.handle_query(text, chat_id=chat_id),
            timeout=30.0,
        )
        await self._send_message(chat_id, response)
    except asyncio.TimeoutError:
        await self._send_message(chat_id,
            "🤖 Гемма: запрос обрабатывался слишком долго (>30s). Попробуй короче.")
    except Exception as exc:
        logger.error("Query agent error: %s", exc, exc_info=True)
        await self._send_message(chat_id,
            "🤖 Гемма: внутренняя ошибка. См. логи.")
```

### 3.2 `/ask` command handler — same path

`/ask <query>` strips prefix and routes to same `_handle_text` path.
Removes v0.46.1 stub. Both free-text AND `/ask` work.

### 3.3 Engine wiring

`engine.py` constructs `AssistantQueryAgent` if
`agent.query.enabled` in config:

```python
# In engine startup
if agent_config.query_enabled:
    broker_snapshot = BrokerSnapshot(broker)
    await broker_snapshot.start()
    
    query_agent = AssistantQueryAgent(
        ollama_client=ollama_client,  # shared with live
        audit_logger=audit_logger,    # shared
        config=agent_config,
        adapters=QueryAdapters(
            broker_snapshot=broker_snapshot,
            cooldown=CooldownAdapter(cooldown_service),
            vacuum=VacuumAdapter(vacuum_predictor),
            sqlite=SQLiteAdapter(sqlite_reader),
            alarms=AlarmAdapter(alarm_engine),
            experiment=ExperimentAdapter(experiment_manager),
        ),
    )
    
    # Pass to telegram_bot
    telegram_bot = TelegramCommandBot(
        ...,
        query_agent=query_agent,
    )
```

---

## 4. Configuration

`config/agent.yaml` extension:

```yaml
agent:
  # ... existing fields ...
  
  query:
    enabled: true
    intent_model: gemma4:e2b      # small fast model
    format_model: gemma4:e2b      # could differ if e4b available
    intent_temperature: 0.1
    format_temperature: 0.3
    intent_timeout_s: 10
    format_timeout_s: 20
    total_timeout_s: 30
    max_concurrent_queries: 2
    rate_limit:
      max_queries_per_chat_per_hour: 60
    out_of_scope_messages:
      historical_redirect: true   # mention F33 in refusal
      general_redirect: true      # mention slash commands in refusal
```

---

## 5. Implementation phases

### Phase 0 — ROADMAP renumbering (~30 min)

1. Edit `ROADMAP.md`: rename old F30→F31, F31→F32, etc. Add new F30.
2. Edit `artifacts/architecture/assistant-v2-vision.md`:
   - §2 add new sub-system "Assistant Query Live"
   - §9 F-task summary table updated with renumbering
   - §5 implementation phases updated (Phase 1 stays F29, new Phase 1.5
     becomes F30, Phase 2 = F31+F32 sinks+indexer, Phase 3 = F33 archive,
     Phase 4 = F34 GUI overlay)

3. Single commit:
```
docs(roadmap): renumber F30+ for Live Query Agent insertion

F30 (NEW) = Live Query Agent (assistant query of current state)
F31 (was F30) = Sinks foundation (vault writer + webhook)
F32 (was F31) = RAG indexer
F33 (was F32) = Archive query (historical, RAG)
F34 (was F33) = GUI chat overlay (deferred)

assistant-v2-vision.md updated with new sub-system "Assistant 
Query Live" between Live and Sinks. F-task table reflects 
renumbering.

Architect decision 2026-05-XX: live state queries (operator asks
"what's ETA vacuum") architecturally distinct from historical 
archive queries (Phase 3 RAG). Insert as new F30; renumber 
Phase 2-4 forward.

Risk: docs only, no code changes.
```

### Phase A — Schemas + adapters (~200 LOC, ~1 day)

1. `agents/assistant/query/schemas.py` — QueryIntent, FetchedData,
   per-category result dataclasses
2. `adapters/broker_snapshot.py` — LatestValueCache subscriber
3. `adapters/cooldown_adapter.py` — wraps CooldownService.last_prediction
   (verify API exists; add if missing as ~10 LOC service extension)
4. `adapters/vacuum_adapter.py` — wraps VacuumTrendPredictor
5. `adapters/sqlite_adapter.py` — range_stats query
6. `adapters/alarm_adapter.py` — wraps AlarmEngine.active_alarms
7. `adapters/experiment_adapter.py` — wraps ExperimentManager
8. `adapters/composite_adapter.py` — parallel fetch via asyncio.gather

Tests for each adapter in isolation:
- `test_broker_snapshot_latest_per_channel`
- `test_broker_snapshot_handles_no_data`
- `test_cooldown_adapter_returns_none_when_inactive`
- `test_vacuum_adapter_target_format`
- `test_sqlite_adapter_range_stats_window`
- `test_alarm_adapter_active_alarms`
- `test_experiment_adapter_phase_age`
- `test_composite_adapter_parallel_fetch`
- `test_composite_adapter_handles_partial_failure`

Commit:
```
feat(f30): query adapters + BrokerSnapshot

7 service adapters extracted from engine state for read-only
query consumption. BrokerSnapshot adds new subscriber pattern
for latest-per-channel caching (Broker is pure pub/sub).

Composite adapter parallelizes fetch for status queries.

Per-adapter tests + composite parallel-fetch + partial-failure
graceful handling.

Ref: artifacts/architecture/assistant-v2-vision.md §2.4 (new)
Risk: medium — new module, but read-only consumer pattern.
```

### Phase B — Intent classifier + router (~150 LOC, ~1 day)

1. `prompts.py` — INTENT_CLASSIFIER_SYSTEM/USER + JSON schema doc
2. `intent_classifier.py` — LLM call + JSON parse + UNKNOWN fallback
3. `router.py` — QueryIntent → adapter dispatch logic
4. Tests:
   - `test_intent_classifier_categorizes_eta_vacuum_query`
   - `test_intent_classifier_handles_misspelled_query`
   - `test_intent_classifier_returns_unknown_on_gibberish`
   - `test_intent_classifier_handles_json_parse_failure`
   - `test_intent_classifier_handles_llm_timeout`
   - `test_router_dispatches_eta_cooldown_to_cooldown_adapter`
   - `test_router_dispatches_composite_status_to_composite`
   - `test_router_handles_out_of_scope_historical`

Commit:
```
feat(f30): intent classifier + router

Intent classifier uses gemma4:e2b with temperature=0.1 for
structured JSON output. Falls back to UNKNOWN on parse failure
or timeout. Router dispatches QueryIntent to corresponding
ServiceAdapter.

Out-of-scope queries (historical, general knowledge) routed to
refusal templates without engine state fetch.

Tests cover happy paths + JSON parse failure + LLM timeout +
out-of-scope detection.

Risk: medium — LLM-based classification, calibration needed
post-deploy via real-world observation.
```

### Phase C — Format prompts + agent assembly (~150 LOC, ~1 day)

1. `prompts.py` — FORMAT_RESPONSE_* templates per category
2. `agent.py` — `AssistantQueryAgent` orchestrator
3. Audit logging integration (reuse `AuditLogger` from shared)
4. Russian quality emphasis in prompts
5. Tests:
   - `test_query_agent_handles_eta_cooldown_full_flow`
   - `test_query_agent_handles_eta_vacuum_with_no_active_pumping`
   - `test_query_agent_composite_status_parallel`
   - `test_query_agent_out_of_scope_historical_response`
   - `test_query_agent_handles_intent_classifier_failure`
   - `test_query_agent_audit_log_per_query`
   - `test_query_agent_rate_limit_per_chat`
   - `test_query_agent_total_timeout_enforcement`

Commit:
```
feat(f30): AssistantQueryAgent + format prompts

Top-level orchestrator. Three-step pipeline:
1. Intent classifier (gemma4:e2b, temperature=0.1)
2. Service adapter dispatch (deterministic fetch)
3. Russian format LLM call (gemma4:e2b, temperature=0.3)

Per-category format prompts with strict anti-hallucination.
Brand-name interpolation throughout.

Audit log per query (intent + fetched data + response). Rate
limit per chat (60/hr default). Total 30s timeout enforced.

Russian-only output, no LaTeX, conversational tone.

Risk: medium — full pipeline integration. Smoke required.
```

### Phase D — Telegram integration + engine wiring (~100 LOC, ~0.5 days)

1. `TelegramCommandBot._handle_text` — free-text dispatch to
   query agent (replace v0.46.1 stub)
2. `/ask <query>` command handler — routes to same path
3. `engine.py` — construct query agent if `agent.query.enabled`,
   pass to TelegramCommandBot
4. Config schema additions in `AssistantConfig`
5. Tests:
   - `test_telegram_free_text_routes_to_query_agent`
   - `test_telegram_ask_command_routes_to_query_agent`
   - `test_telegram_query_timeout_user_message`
   - `test_telegram_query_error_user_message`
   - `test_engine_constructs_query_agent_when_enabled`
   - `test_engine_skips_query_agent_when_disabled`

Commit:
```
feat(f30): Telegram free-text + /ask integration

TelegramCommandBot routes non-command messages and /ask <query>
to AssistantQueryAgent. v0.46.1 stub removed.

Engine wires query agent if agent.query.enabled. BrokerSnapshot
subscriber starts on engine startup, stops on shutdown.

User-facing error messages on timeout / internal error /
query agent disabled.

Risk: medium — Telegram ingress path widened. Allowlist still
enforced (default-deny per existing TelegramCommandBot).
```

### Phase E — Smoke test (mandatory before audit)

Per ORCHESTRATION v1.4 §16.4. Real Ollama + real engine in mock
mode + real Telegram (with test bot, NOT production).

Setup:
1. Start `cryodaq-engine --mock`
2. Use test Telegram bot (separate token, not production)
3. Add yourself as `allowed_chat_id` in `notifications.local.yaml`

Scenarios:
1. **Free-text "что сейчас?"** — verify composite status response,
   3-5 sentences Russian, includes experiment/phase/temperatures/pressure
2. **Free-text "ETA вакуума"** — verify vacuum eta with current P,
   target, eta string
3. **Free-text "как скоро охлаждение"** — verify cooldown eta with
   progress, phase, time remaining + CI
4. **Free-text "в каком диапазоне P"** — verify range stats with
   min/max/mean/std over last 60min
5. **Free-text "какая T1?"** — current value response
6. **Free-text "есть тревоги?"** — alarm status (none active in
   mock unless triggered)
7. **Free-text "что было вчера в 14?"** — out-of-scope historical
   refusal mentioning F33
8. **Free-text "что такое thermal conductance?"** — out-of-scope
   general refusal
9. **`/ask что сейчас?`** — verify same path as free-text
10. **Gibberish query** — UNKNOWN intent, polite refusal

Per scenario document:
- Latency wall (target ≤15s p50)
- Russian quality % (target ≥90%)
- Hallucination check (any fact not in fetched data?)
- Tone check (conversational, не robot)

Smoke output: `artifacts/handoffs/2026-05-XX-f30-cycle1-smoke.md`

If any FAIL → STOP, prompt engineering session before audit.

### Phase F — Audit + ratify

Per ORCHESTRATION v1.4 §16.3 — foundational change (new agent module
+ infrastructure):
- **Codex gpt-5.5** (workspace-write)
- **GLM-5.1** (max_tokens=16384 — large diff likely)
- **Qwen3-Coder-Next** (counter-signal probe)

Skip Kimi (per recent calibration), MiniMax (deteriorating), Gemini
(chronic 429), R1/Chimera (capacity).

Append all 3 to calibration log. New task class entry as
`new_agent_module` (granular variant of foundational_change_review).

Architect classification per §14.6, fix-up loop max 5 iterations.

### Phase G — v0.47.0 release

After audit PASS:
1. pyproject.toml: 0.46.1 → 0.47.0
2. CHANGELOG entry for F30
3. ROADMAP: F30 ✅ DONE → v0.47.0
4. Commit + tag v0.47.0 + push to master

---

## 6. Acceptance criteria

After all phases:

1. ✅ ROADMAP renumbering committed and visible in vision doc
2. ✅ AssistantQueryAgent constructed when `agent.query.enabled`
3. ✅ Telegram free-text routes to query agent
4. ✅ `/ask <query>` works identically to free-text
5. ✅ Intent classifier categorizes correctly for 7 representative
   query patterns
6. ✅ All 5 in-scope adapters return structured data
7. ✅ Composite status parallel-fetches via asyncio.gather
8. ✅ Russian format quality ≥ 90% per smoke
9. ✅ Latency p50 ≤ 15s, p95 ≤ 25s
10. ✅ Out-of-scope (historical, general) gets polite refusal
11. ✅ Audit log per query (intent + fetched + response)
12. ✅ Rate limit per chat enforced (60/hr default)
13. ✅ All existing tests pass (no regressions)
14. ✅ ≥ 25 new tests across adapters/classifier/agent/integration

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Intent classifier mis-categorizes operator queries | MEDIUM | Smoke test 10 representative queries; iterate prompts |
| LLM hallucinates fact not in fetched data | HIGH | TIGHT format prompt + audit log review for first week deployment |
| Latency exceeds 15s p50 — operator frustrated | MEDIUM | Two LLM calls (intent + format) is the cost; optimize via prompt brevity |
| BrokerSnapshot consumer queue overflow at high data rate | LOW | maxsize=1000 + DROP_OLDEST policy (pub/sub semantic) |
| CooldownService.last_prediction() API doesn't exist | LOW | Add ~10 LOC during Phase A; small extension |
| VacuumTrendPredictor doesn't expose last result | LOW | Add cache method during Phase A |
| Free-text from non-allowlist users hits LLM | HIGH | Allowlist enforced in TelegramCommandBot before query routing |
| Russian classifier instructions too rigid for natural variation | MEDIUM | Real-world observation post-deploy; prompt iteration |
| Out-of-scope detection misses (historical query gets in-scope handling) | MEDIUM | Strict prompt rules + smoke test edge cases |
| Concurrent queries from multiple chats overload Ollama | LOW | max_concurrent_queries=2 limit |

---

## 8. Hard stops

- Phase A: any adapter test fails → STOP, fix before continuing
- Phase B: intent classifier returns valid JSON < 80% on
  representative query suite → STOP, prompt iteration
- Phase C: query agent integration test breaks existing
  AssistantLiveAgent → STOP, regression
- Phase E smoke: Russian quality < 85% on any scenario → STOP
- Phase E smoke: hallucinated fact detected (something not in
  fetched data) → STOP, format prompt fix
- Phase F: architect-verified CRITICAL finding → STOP, fix-up
  cycle before tag

---

## 9. Architect comm-out discipline

Surface ARCHITECT DECISION NEEDED markers immediately:

- §1.5 CooldownService.last_prediction() API addition (existing or
  new method?)
- §1.6 VacuumTrendPredictor cache exposure
- §2 prompt template wording (calibration via smoke iteration)
- §4 config schema fields (defaults sensible?)
- Phase E smoke quality borderline (85-90%) — accept or iterate?

Continue with safest interpretation per §13.2, document in handoff.

---

## 10. Begin

1. Phase 0 — ROADMAP renumbering (commit before any code)
2. Phase A — adapters
3. Phase B — intent + router
4. Phase C — agent + format prompts
5. Phase D — Telegram integration + engine wiring
6. Phase E — smoke (mandatory before audit)
7. Phase F — multi-verifier audit
8. Phase G — v0.47.0 release

Ref:
- `artifacts/architecture/assistant-v2-vision.md` §2.4 (will be
  added in Phase 0)
- `docs/ORCHESTRATION.md` §16.3, §16.4, §17

GO.
