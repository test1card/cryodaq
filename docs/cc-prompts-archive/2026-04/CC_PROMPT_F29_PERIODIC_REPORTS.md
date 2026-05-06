# F29 — Periodic narrative reports

> Hourly Russian-language narrative summary of last-N-minutes engine
> activity, dispatched to Telegram + operator log + GUI insight panel.
> First standalone Phase 1 feature of assistant v2 vision.
>
> Reference: `artifacts/architecture/assistant-v2-vision.md` §5 Phase 1.
> ROADMAP entry: F29.

---

## 0. Operating posture

- **Architect synchronously available**, single cycle.
- **Branch:** `feat/f29-periodic-reports`
- **Ships:** v0.46.0
- **Effort:** S-M (~250 LOC + ~150 tests = ~400 LOC total)
- **Verifier scaling per ORCHESTRATION v1.4 §16.3:** narrow feature
  extension → 2-model dispatch (Codex + GLM).
- **Active model:** `gemma4:e2b` (default in agent.yaml, ~1.5GB Q4,
  M5-friendly). e4b also pulled but doesn't fit on M5 24GB alongside
  engine + GUI — reserved for dedicated GPU box.

---

## 1. Architect decisions baked in

| Decision | Verdict | Rationale |
|---|---|---|
| Trigger mechanism | Engine timer task creating `periodic_report_request` events on EventBus | Mirrors existing `_alarm_v2_tick` / `_sensor_diag_tick` patterns |
| Default interval | 60 minutes | Hourly cadence matches typical lab shift granularity |
| Skip-if-idle threshold | `min_events_for_dispatch: 1` | Skip generation if NO events in window — no noise during idle hours |
| Time window | last interval_minutes (default 60 min) | Matches dispatch cadence; avoids overlap with prior report |
| Trigger location | Engine, NOT scheduler (instrument-poll-only) | Existing precedent: `_alarm_v2_tick` is engine-owned background task |
| Output channels | Same as Slice A (Telegram + operator log + GUI insight panel) | Consistency with existing assistant outputs |
| Output prefix | `🤖 {brand_name} (отчёт за час):` | Distinguishes from event-driven dispatches |
| Russian quality target | 90%+ Cyrillic, no English drift | Consistency with F28 Slice A baseline |
| Word count target | 100-200 words | Conversational summary, not formal report |

---

## 2. Architecture

### 2.1 Engine timer task

In `src/cryodaq/engine.py`, alongside existing periodic ticks
(`_alarm_v2_tick`, `_sensor_diag_tick`, `_vacuum_trend_tick`):

```python
async def _periodic_report_tick() -> None:
    """Publish periodic_report_request event on schedule.
    
    GemmaAgent (or any other subscriber) generates summary if subscribed.
    Engine just publishes the trigger; aggregation+inference is
    AssistantLiveAgent responsibility.
    """
    interval_s = float(_agent_config.get_periodic_report_interval_s())
    if interval_s <= 0:
        logger.info("Periodic reports disabled (interval=0)")
        return
    while True:
        await asyncio.sleep(interval_s)
        try:
            _active = experiment_manager.active_experiment
            await event_bus.publish(
                EngineEvent(
                    event_type="periodic_report_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "window_minutes": int(interval_s / 60),
                        "trigger": "scheduled",
                    },
                    experiment_id=_active.experiment_id if _active else None,
                )
            )
        except Exception as exc:
            logger.error("Periodic report tick error: %s", exc)
```

Created as `asyncio.create_task` after agent startup, cancelled in
shutdown sequence. **Only created if** `agent.triggers.periodic_report.enabled`
in config.

### 2.2 Agent handler

In `src/cryodaq/agents/assistant/live/agent.py`, new handler subscribed
to `periodic_report_request` event:

```python
async def _handle_periodic_report(self, event: EngineEvent) -> None:
    """Generate hourly narrative from last-N-minutes events.
    
    Skips if min_events_for_dispatch threshold not met (idle hour).
    """
    window_minutes = int(event.payload.get("window_minutes", 60))
    
    # Build context
    context = await self._context_builder.build_periodic_report_context(
        window_minutes=window_minutes,
    )
    
    # Skip-if-idle check
    if context.total_event_count < self._config.periodic_report_min_events:
        logger.debug(
            "Periodic report skipped: %d events < %d threshold (idle window)",
            context.total_event_count,
            self._config.periodic_report_min_events,
        )
        return
    
    # Rate limit check (shared bucket with other triggers)
    if not self._rate_limiter.try_acquire():
        logger.warning("Periodic report rate-limited, skipping")
        return
    
    # Inference + dispatch (same pattern as alarm_summary)
    response = await self._ollama_client.generate(
        system=PERIODIC_REPORT_SYSTEM.format(brand_name=self._config.brand_name),
        prompt=PERIODIC_REPORT_USER.format(
            window_minutes=window_minutes,
            **context.to_template_dict(),
        ),
        max_tokens=2048,  # thinking-first model
    )
    
    if not response or not response.text.strip():
        logger.warning("Periodic report: empty response from model")
        return
    
    # Audit + dispatch
    audit_id = await self._audit_logger.record(
        trigger="periodic_report",
        context=context,
        prompt=...,
        response=response,
    )
    await self._output_router.dispatch(
        text=response.text,
        trigger_type="periodic_report",
        prefix_suffix="(отчёт за час)",
        audit_id=audit_id,
    )
```

### 2.3 Context builder method

In `src/cryodaq/agents/assistant/live/context_builder.py`, new method:

```python
async def build_periodic_report_context(
    self,
    *,
    window_minutes: int,
) -> PeriodicReportContext:
    """Aggregate engine activity over last window_minutes.
    
    Reads SQLite for: events, alarms, phase transitions, operator log entries.
    Returns structured context object with total_event_count for skip-if-idle.
    """
    end_ts = datetime.now(UTC).timestamp()
    start_ts = end_ts - window_minutes * 60
    
    # Active experiment status
    active_experiment = self._experiment_manager.active_experiment
    
    # Events from operator_log (tagged events from event_logger)
    events = await self._writer.get_events_in_window(start_ts, end_ts)
    
    # Alarms (alarm_v2 history within window)
    alarms = await self._writer.get_alarms_in_window(start_ts, end_ts)
    
    # Phase transitions (subset of events, tag="phase")
    phase_transitions = [e for e in events if e.tag == "phase"]
    
    # Operator log entries (excluding machine events)
    operator_entries = await self._writer.get_operator_log(
        start_time=datetime.fromtimestamp(start_ts, UTC),
        end_time=datetime.fromtimestamp(end_ts, UTC),
        limit=20,
    )
    operator_entries = [e for e in operator_entries if e.source != "machine"]
    
    # Calibration events (subset of events, tag="calibration")
    calibration_events = [e for e in events if e.tag == "calibration"]
    
    # Sensor anomalies in window (from sensor_diagnostics events if any)
    # ... (similar pattern)
    
    total = (
        len(events) + len(alarms) + len(operator_entries) + len(calibration_events)
    )
    
    return PeriodicReportContext(
        window_minutes=window_minutes,
        active_experiment=active_experiment,
        events=events,
        alarms=alarms,
        phase_transitions=phase_transitions,
        operator_entries=operator_entries,
        calibration_events=calibration_events,
        total_event_count=total,
    )
```

`PeriodicReportContext` dataclass:
- `window_minutes: int`
- `active_experiment: ExperimentInfo | None`
- `events: list[EngineEventRecord]`
- `alarms: list[AlarmHistoryEntry]`
- `phase_transitions: list[EngineEventRecord]`
- `operator_entries: list[OperatorLogEntry]`
- `calibration_events: list[EngineEventRecord]`
- `total_event_count: int`
- Method `to_template_dict()` formats all above into prompt-ready strings

### 2.4 Prompt templates

In `src/cryodaq/agents/assistant/live/prompts.py`:

```python
PERIODIC_REPORT_SYSTEM = """\
Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.
Твоя задача — краткий обзор активности за последний час для
оператора в Telegram.

Принципы:
- Отвечай ТОЛЬКО на русском языке.
- Не выдумывай контекст. Используй только данные ниже.
- Конкретные значения, не размытые описания.
- Тон conversational, не формальный (это сводка для оператора, не отчёт).
- Если событий мало — короткий summary (5-10 слов про то что всё стабильно).
- Если событий много — структурируй по категориям (алармы / фазы / 
  операторский журнал / калибровка).
- 100-200 слов максимум. Telegram-friendly Markdown.
- Если активного эксперимента нет — упомяни это в одной фразе.
"""

PERIODIC_REPORT_USER = """\
Окно времени: последние {window_minutes} минут.

Активный эксперимент: {active_experiment_summary}

События:
{events_section}

Алармы:
{alarms_section}

Переходы фаз:
{phase_transitions_section}

Записи операторского журнала:
{operator_entries_section}

Калибровка:
{calibration_section}

Всего событий: {total_event_count}

Сгенерируй краткую сводку для оператора в Telegram.
"""
```

Each section uses "(нет)" placeholder if empty rather than empty string,
preventing prompt injection per ORCHESTRATION v1.4 §16.5 stub workaround
pattern.

### 2.5 Configuration

Add to `config/agent.yaml`:

```yaml
agent:
  triggers:
    periodic_report:
      enabled: true
      interval_minutes: 60
      skip_if_idle: true
      min_events_for_dispatch: 1
      # Inference can take 30-60s on gemma4:e2b. Multiple periodic_report
      # events stacking up would block other Гемма work. Single-flight via
      # rate_limit.max_concurrent_inferences (existing config) is sufficient.
```

Default in `AssistantConfig`:
- `periodic_report_enabled: bool = True`
- `periodic_report_interval_minutes: int = 60`
- `periodic_report_skip_if_idle: bool = True`
- `periodic_report_min_events: int = 1`

Method `get_periodic_report_interval_s() -> float`:
- Returns 0 if not enabled
- Otherwise returns `periodic_report_interval_minutes * 60`

### 2.6 Output router prefix variation

`OutputRouter.dispatch()` accepts optional `prefix_suffix` parameter:

```python
def dispatch(self, *, text: str, trigger_type: str, prefix_suffix: str = "", ...) -> None:
    if prefix_suffix:
        prefix = f"{self._brand_emoji} {self._brand_name} {prefix_suffix}: "
    else:
        prefix = f"{self._brand_emoji} {self._brand_name}: "
    # ... rest unchanged
```

Backward-compatible: existing handlers don't pass `prefix_suffix`, behavior
unchanged. Periodic handler passes `"(отчёт за час)"`, resulting in:

> 🤖 Гемма (отчёт за час): За последний час алармов нет, активный
> эксперимент cooldown_2026-05-XX в фазе measurement (T1=4.5K стабильно)...

### 2.7 GUI insight panel

`AssistantInsightPanel` already accepts trigger type chips. Add new type:
- `"periodic_report"` → chip text "Отчёт за час" (or similar)
- Color/style: same as informational events (not alarm severity)

No new GUI components needed — existing card system handles it.

---

## 3. Implementation cycle

Single cycle, 4 phases:

### 3.1 Phase A — Configuration + agent loader (~30 min)

1. Extend `AssistantConfig` with `periodic_report_*` fields
2. Add YAML loading + defaults
3. Update `config/agent.yaml` with new section
4. Tests: `test_periodic_report_config_defaults`, 
   `test_periodic_report_config_disabled`,
   `test_periodic_report_interval_seconds_calculation`

### 3.2 Phase B — Context builder (~45 min)

1. New method `build_periodic_report_context()` in `context_builder.py`
2. New dataclass `PeriodicReportContext` with `to_template_dict()`
3. Helper methods on SQLite reader for window queries (if not already
   present — verify during recon)
4. Tests:
   - `test_periodic_report_context_aggregates_window`
   - `test_periodic_report_context_handles_empty_window`
   - `test_periodic_report_context_excludes_machine_log_entries`
   - `test_periodic_report_context_total_count_correct`

### 3.3 Phase C — Agent handler + prompts (~45 min)

1. Add `PERIODIC_REPORT_SYSTEM` / `PERIODIC_REPORT_USER` templates
2. New handler `_handle_periodic_report()` in `agent.py`
3. Subscribe to `periodic_report_request` event in `start()`
4. Update `OutputRouter.dispatch()` to accept `prefix_suffix`
5. Tests:
   - `test_periodic_report_handler_dispatches_when_active`
   - `test_periodic_report_handler_skips_when_idle`
   - `test_periodic_report_handler_respects_rate_limit`
   - `test_periodic_report_handler_handles_empty_response`
   - `test_periodic_report_prefix_includes_suffix`

### 3.4 Phase D — Engine timer task + integration (~30 min)

1. New `_periodic_report_tick()` async function in `engine.py`
2. Create task only if `agent.triggers.periodic_report.enabled`
3. Cancel task in shutdown sequence
4. Integration test: mock engine, verify `periodic_report_request` event
   published at expected interval
5. Tests:
   - `test_engine_periodic_report_tick_publishes_event`
   - `test_engine_periodic_report_tick_disabled_when_config_off`
   - `test_engine_periodic_report_tick_cancelled_on_shutdown`

### 3.5 Phase E — Smoke test (mandatory before audit)

Per ORCHESTRATION v1.4 §16.4. Real Ollama, real engine in mock mode:

1. Set `interval_minutes: 2` in agent.yaml for test (override default 60)
2. Start engine `--mock`
3. Trigger several events in 2-min window (alarm via mock threshold,
   phase transition, operator log entry)
4. Wait for `_periodic_report_tick` to fire
5. Verify:
   - Telegram message arrives with `🤖 Гемма (отчёт за час):` prefix
   - Russian-language summary mentions actual events (alarms, phase, 
     log entries by name)
   - GUI insight panel shows new card with trigger chip "Отчёт за час"
   - Audit log JSON exists with `trigger: periodic_report`
   - Latency reasonable for gemma4:e2b on M5 (likely 20-40s — smaller
     model than e4b's 48s)
6. Test idle skip: trigger interval with NO events in window, verify NO
   message dispatched (skip-if-idle works)
7. Document in `artifacts/handoffs/2026-05-XX-f29-cycle1-smoke.md`:
   - Sample Russian text (real LLM output)
   - Latency observed
   - Memory observed
   - Idle skip verification
   - Quality assessment vs F28 Slice A baseline

After smoke PASS → restore `interval_minutes: 60` for normal operation
before commit.

### 3.6 Phase F — Audit dispatch

Per ORCHESTRATION v1.4 §16.3, narrow feature extension → 2-verifier:
- **Codex gpt-5.5** with `--sandbox workspace-write`
- **GLM-5.1** with `max_tokens=8192`, prompt diff-only ≤10KB

Skip Gemini (chronic 429), Kimi (capacity failures), MiniMax (Cycle 2
quality drop, deferred until recovery sessions).

Append both audit results to `artifacts/calibration/log.jsonl` with
session_id `"2026-05-XX-f29-cycle1"`. New task class:
`task_class: "narrow_feature_extension"`.

Architect classification per §14.6, fix-up loop max 5 iterations.

### 3.7 Phase G — v0.46.0 release

After audit PASS:
1. Bump `pyproject.toml`: 0.45.0 → 0.46.0
2. Update CHANGELOG with F29 section
3. Update ROADMAP: F29 ✅ DONE → v0.46.0
4. Commit + tag v0.46.0 + push

CHANGELOG entry:
```markdown
## [0.46.0] — 2026-05-XX — F29 Periodic narrative reports

### Added
- F29: hourly Russian-language narrative summary of engine activity
- New EventBus event type: `periodic_report_request`
- Engine timer task `_periodic_report_tick` (configurable interval)
- AssistantLiveAgent handler `_handle_periodic_report`
- New prompt templates `PERIODIC_REPORT_SYSTEM/USER`
- Context builder method `build_periodic_report_context`
- Skip-if-idle filtering (no dispatch when window has < min_events events)
- Output prefix variation: `🤖 Гемма (отчёт за час):`
- GUI insight panel chip type for periodic reports

### Changed
- Default Гемма model: gemma4:e4b → gemma4:e2b (M5 24GB compatibility)
  - e4b reserved for dedicated GPU deployments (≥16GB VRAM)
  - e2b ~1.5GB, fits comfortably alongside engine + GUI on M5
  - Quality similar per smoke samples; thinking-first behavior unchanged

### Configuration
- `config/agent.yaml`: new `triggers.periodic_report` section with
  `enabled`, `interval_minutes`, `skip_if_idle`, `min_events_for_dispatch`

### Tests
- ~150 LOC new tests: config, context builder, handler, engine integration
- Smoke test verified Russian quality + idle skip + GUI rendering

### Reference
- Architecture: `artifacts/architecture/assistant-v2-vision.md` §5 Phase 1
- Spec: `CC_PROMPT_F29_PERIODIC_REPORTS.md`
```

---

## 4. Acceptance criteria

After all phases complete and audit PASS:

1. ✅ `_periodic_report_tick` running in engine when enabled
2. ✅ Event published to EventBus at configured interval
3. ✅ AssistantLiveAgent generates Russian narrative on event receipt
4. ✅ Skip-if-idle: NO dispatch when total_event_count < threshold
5. ✅ Telegram receives message with `(отчёт за час)` prefix suffix
6. ✅ Operator log records entry tagged `assistant`
7. ✅ GUI insight panel shows card with periodic-report trigger chip
8. ✅ Russian quality: no English drift, grounded in actual events
9. ✅ Audit log captures trigger, context, response per existing pattern
10. ✅ Configurable disable: `enabled: false` → no task created
11. ✅ Tests cover all happy paths + skip-if-idle + rate limit + empty
    response + disabled state

If Slice C campaign report intro should also reference periodic reports
(post-F31 RAG enrichment per architecture vision §8), defer — that's
post-F31 work.

---

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Periodic dispatch interferes with event-driven dispatches (rate limit conflict) | LOW | Existing `max_concurrent_inferences=2` + single shared rate bucket; periodic just consumes one slot like any other handler |
| Russian quality regresses on conversational tone vs formal F28 prompts | MEDIUM | Smoke test mandatory; prompt iteration if needed before commit |
| Skip-if-idle threshold too aggressive (real activity gets skipped) | LOW | Default 1 event triggers dispatch; threshold configurable per deployment |
| Engine timer drift accumulates over hours | LOW | `asyncio.sleep` is monotonic, drift bounded; periodic event payload includes actual `window_minutes` aggregated |
| gemma4:e2b quality insufficient for narrative tone (smaller than e4b) | MEDIUM | Smoke test verifies; if regression observed, options: (a) tune prompt for e2b, (b) accept slightly weaker output, (c) revisit e4b on dedicated hardware |
| `interval_minutes: 2` test override accidentally committed | LOW | Phase E explicitly notes restore before commit; Phase F audit catches |
| SQLite window queries slow on large operator_log | LOW | Existing `get_operator_log()` already paginated/limited |

---

## 6. Hard stops

- Russian quality regresses (English drift OR hallucination of nonexistent
  events) → STOP, prompt engineering session
- Latency >120s per dispatch (engine event loop blocked too long) → STOP,
  investigate concurrency
- Skip-if-idle malfunctions (events sent during truly idle hours) → STOP,
  threshold logic bug
- Existing F28 tests regress → STOP, integration breakage
- e2b model quality unacceptable for narrative tone → ARCHITECT DECISION,
  options A/B/C from §5 risks table

---

## 7. Architect comm-out discipline

Surface ARCHITECT DECISION NEEDED markers immediately:

- §2.4 prompt template wording — minor tone/structure adjustments
  expected after first smoke samples
- §2.6 prefix suffix style — `(отчёт за час)` may need refinement based
  on how it reads in Telegram
- e2b vs e4b quality decision if smoke reveals significant quality drop

Continue with safest interpretation per §13.2, document in handoff.

---

## 8. Reference checklist

Before starting:
- [ ] Read this prompt fully
- [ ] Read `artifacts/architecture/assistant-v2-vision.md` §5 Phase 1
- [ ] Read `docs/ORCHESTRATION.md` §16 (multi-cycle work) and §17
  (calibration log)
- [ ] Verify clean master at v0.45.0 tag
- [ ] Verify gemma4:e2b model pulled: `ollama list | grep gemma4`
- [ ] Verify config/agent.yaml has `default_model: gemma4:e2b`
  (was changed pre-F29 by architect)

Per ORCHESTRATION v1.4 §10 session-start checklist:
- Recon before action (HEAD verification, branch state)
- Plugin auto-load awareness
- Skill registry refresh

---

## 9. Begin

Phase A first (configuration). Standalone, no dependencies.

After all phases A-G complete: F29 shipped, v0.46.0 tagged, ready for
Phase 2 (F30+F31 sinks foundation) when architect composes next spec.

GO.
