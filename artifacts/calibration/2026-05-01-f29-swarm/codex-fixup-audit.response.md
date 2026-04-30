Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/vladimir/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019de039-1435-7e71-831f-d5e0287a1020
--------
user
Model: gpt-5.5 / Reasoning effort: high

Narrow single-verifier audit of F29 fix-up commit 7515c7f on feat/f29-periodic-reports.

## Context
CryoDAQ F29 periodic reports. A swarm audit (8 models) identified 5 findings.
3 were fixed in commit 7515c7f:
- CF-2: SQLite failure in build_periodic_report_context now logs WARNING + sets context_read_failed=True; handler bypasses skip_if_idle when context_read_failed
- CF-3: phase_entries filter now includes 'phase' tag (engine logs 'phase', was filtering 'phase_transition'); other_entries excludes 'phase' too
- CF-5: PERIODIC_REPORT_SYSTEM now has explicit LaTeX prohibition line; regression test added

## Your task
Verify these 3 fixes are correct and complete. Narrow scope ONLY — do not re-audit the full F29 feature.

Files changed:
- src/cryodaq/agents/assistant/live/context_builder.py (CF-2 + CF-3)
- src/cryodaq/agents/assistant/live/agent.py (CF-2 handler)
- src/cryodaq/agents/assistant/live/prompts.py (CF-5)
- tests/agents/assistant/test_periodic_report_handler.py (CF-5 test)

For each fix, verify:
1. Is the fix correct and complete?
2. Are there any regressions introduced?
3. Is the test adequate?

Output: PASS / FAIL with brief per-fix notes. Under 500 words.
codex
I’m using the GitHub/code-review style plus the verification discipline here: narrow audit only, centered on commit `7515c7f` and the four files you named. I’ll inspect the diff and nearby tests, then give you a compact PASS/FAIL with evidence.
exec
/opt/homebrew/bin/bash -lc 'git show --no-ext-diff --unified=80 --no-renames 7515c7f -- src/cryodaq/agents/assistant/live/context_builder.py src/cryodaq/agents/assistant/live/agent.py src/cryodaq/agents/assistant/live/prompts.py tests/agents/assistant/test_periodic_report_handler.py' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
commit 7515c7f9049dd9d43a4470128c4e3f10f71c71d3
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Fri May 1 00:07:17 2026 +0300

    fix(f29): swarm audit findings CF-2 CF-3 CF-5
    
    CF-2: distinguish SQLite context failure from idle window.
      get_operator_log() failure now logs at WARNING and sets
      context_read_failed=True on PeriodicReportContext. Handler
      bypasses skip_if_idle when context read failed so operators
      see an empty-data report rather than silent suppression.
    
    CF-3: phase tag mismatch fixed in build_periodic_report_context.
      Engine logs phase transitions with tag "phase"; context builder
      was filtering "phase_transition" only, causing the phase section
      to always show (нет). Now matches either tag.
      other_entries filter updated to exclude "phase" entries too.
    
    CF-5: LaTeX prohibition added to PERIODIC_REPORT_SYSTEM.
      Explicit instruction against $...$, \rightarrow etc.
      Regression test added in test_periodic_report_handler.py.
    
    Ref: CC_PROMPT_F29_SWARM_AUDIT_2026-05-01.md (fix-up cycle)
    Risk: prompt + context logic only; no engine wiring changes.

diff --git a/src/cryodaq/agents/assistant/live/agent.py b/src/cryodaq/agents/assistant/live/agent.py
index 88d5cde..0f43961 100644
--- a/src/cryodaq/agents/assistant/live/agent.py
+++ b/src/cryodaq/agents/assistant/live/agent.py
@@ -624,161 +624,167 @@ class AssistantLiveAgent:
             result.latency_s,
             ctx.channel,
         )
         if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
             await self._generate_diagnostic_suggestion(event, payload)
 
     async def _handle_shift_handover(self, event: EngineEvent) -> None:
         audit_id = self._audit.make_audit_id()
         payload = event.payload
 
         ctx = await self._ctx_builder.build_shift_handover_context(payload)
         user_prompt = SHIFT_HANDOVER_USER.format(
             experiment_id=ctx.experiment_id or "нет активного эксперимента",
             phase=ctx.phase or "—",
             experiment_age=ctx.experiment_age,
             active_alarms=ctx.active_alarms,
             recent_events=ctx.recent_events,
             shift_duration_h=ctx.shift_duration_h,
         )
 
         system_prompt = format_with_brand(SHIFT_HANDOVER_SYSTEM, self._config.brand_name)
         result = await self._ollama.generate(
             user_prompt,
             system=system_prompt,
             max_tokens=self._config.max_tokens,
             temperature=self._config.temperature,
             num_ctx=self._config.num_ctx,
         )
 
         errors: list[str] = []
         if result.truncated:
             errors.append("timeout_truncated")
             logger.warning(
                 "AssistantLiveAgent: ответ обрезан (shift_handover, audit_id=%s)", audit_id
             )
 
         targets = _build_targets(self._config)
         if result.truncated or not result.text.strip():
             logger.warning(
                 "AssistantLiveAgent: пустой ответ shift_handover (audit_id=%s)", audit_id
             )
             dispatched_sh: list[str] = []
         else:
             dispatched_sh = await self._router.dispatch(
                 event, result.text, targets=targets, audit_id=audit_id
             )
 
         await self._audit.log(
             audit_id=audit_id,
             trigger_event={
                 "event_type": event.event_type,
                 "payload": payload,
                 "experiment_id": event.experiment_id,
             },
             context_assembled=user_prompt,
             prompt_template="shift_handover",
             model=result.model,
             system_prompt=system_prompt,
             user_prompt=user_prompt,
             response=result.text,
             tokens={"in": result.tokens_in, "out": result.tokens_out},
             latency_s=result.latency_s,
             outputs_dispatched=dispatched_sh,
             errors=errors,
         )
         logger.info(
             "AssistantLiveAgent: shift_handover_request обработан (audit_id=%s, latency=%.1fs)",
             audit_id,
             result.latency_s,
         )
 
 
     async def _handle_periodic_report(self, event: EngineEvent) -> None:
         audit_id = self._audit.make_audit_id()
         window_minutes = int(event.payload.get("window_minutes", 60))
 
         ctx = await self._ctx_builder.build_periodic_report_context(
             window_minutes=window_minutes,
         )
 
-        if (
+        if ctx.context_read_failed:
+            logger.warning(
+                "AssistantLiveAgent: periodic report context read failed "
+                "(audit_id=%s) — proceeding with empty context",
+                audit_id,
+            )
+        elif (
             self._config.periodic_report_skip_if_idle
             and ctx.total_event_count < self._config.periodic_report_min_events
         ):
             logger.debug(
                 "AssistantLiveAgent: periodic report skipped "
                 "(idle: %d events < min=%d)",
                 ctx.total_event_count,
                 self._config.periodic_report_min_events,
             )
             return
 
         template_dict = ctx.to_template_dict()
         user_prompt = PERIODIC_REPORT_USER.format(
             window_minutes=window_minutes,
             **template_dict,
         )
         system_prompt = format_with_brand(PERIODIC_REPORT_SYSTEM, self._config.brand_name)
 
         result = await self._ollama.generate(
             user_prompt,
             system=system_prompt,
             max_tokens=self._config.max_tokens,
             temperature=self._config.temperature,
             num_ctx=self._config.num_ctx,
         )
 
         errors: list[str] = []
         if result.truncated:
             errors.append("timeout_truncated")
             logger.warning(
                 "AssistantLiveAgent: periodic report обрезан (audit_id=%s)", audit_id
             )
 
         targets = _build_targets(self._config)
         if result.truncated or not result.text.strip():
             logger.warning(
                 "AssistantLiveAgent: пустой periodic report (audit_id=%s)", audit_id
             )
             dispatched_pr: list[str] = []
         else:
             dispatched_pr = await self._router.dispatch(
                 event,
                 result.text,
                 targets=targets,
                 audit_id=audit_id,
                 prefix_suffix="(отчёт за час)",
             )
 
         await self._audit.log(
             audit_id=audit_id,
             trigger_event={
                 "event_type": event.event_type,
                 "payload": event.payload,
                 "experiment_id": event.experiment_id,
             },
             context_assembled=user_prompt,
             prompt_template="periodic_report",
             model=result.model,
             system_prompt=system_prompt,
             user_prompt=user_prompt,
             response=result.text,
             tokens={"in": result.tokens_in, "out": result.tokens_out},
             latency_s=result.latency_s,
             outputs_dispatched=dispatched_pr,
             errors=errors,
         )
         logger.info(
             "AssistantLiveAgent: periodic_report_request обработан "
             "(audit_id=%s, latency=%.1fs, events=%d, dispatched=%s)",
             audit_id,
             result.latency_s,
             ctx.total_event_count,
             dispatched_pr,
         )
 
 
 def _build_targets(config: AssistantConfig) -> list[OutputTarget]:
     targets = []
     if config.output_telegram:
         targets.append(OutputTarget.TELEGRAM)
diff --git a/src/cryodaq/agents/assistant/live/context_builder.py b/src/cryodaq/agents/assistant/live/context_builder.py
index e2ca452..abd794b 100644
--- a/src/cryodaq/agents/assistant/live/context_builder.py
+++ b/src/cryodaq/agents/assistant/live/context_builder.py
@@ -43,214 +43,221 @@ class ContextBuilder:
 
     def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
         self._reader = sqlite_reader
         self._em = experiment_manager
 
     async def build_alarm_context(
         self,
         alarm_payload: dict[str, Any],
         *,
         lookback_s: float = 60.0,
         recent_alarm_lookback_s: float = 3600.0,
     ) -> AlarmContext:
         """Assemble context for a Slice A alarm summary prompt.
 
         Reads experiment state from ExperimentManager (in-memory, fast).
         SQLite reading history and alarm history wired in Cycle 4 — historical SQLite context.
         """
         alarm_id = alarm_payload.get("alarm_id", "unknown")
         channels: list[str] = alarm_payload.get("channels", [])
         values: dict[str, float] = alarm_payload.get("values", {})
         level: str = alarm_payload.get("level", "WARNING")
 
         experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
 
         phase: str | None = None
         if hasattr(self._em, "get_current_phase"):
             try:
                 phase = self._em.get_current_phase()
             except Exception:
                 pass
 
         experiment_age_s: float | None = _compute_experiment_age(self._em)
 
         return AlarmContext(
             alarm_id=alarm_id,
             level=level,
             channels=channels,
             values=values,
             phase=phase,
             experiment_id=experiment_id,
             experiment_age_s=experiment_age_s,
             target_temp=None,
             active_interlocks=[],
             recent_readings_text=_readings_stub(channels, lookback_s),
             recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
         )
 
     async def build_experiment_finalize_context(
         self, payload: dict[str, Any]
     ) -> ExperimentFinalizeContext:
         """Assemble context for experiment finalize/stop/abort prompt."""
         return _build_experiment_finalize_context(self._em, payload)
 
     async def build_sensor_anomaly_context(
         self, payload: dict[str, Any]
     ) -> SensorAnomalyContext:
         """Assemble context for sensor anomaly analysis prompt."""
         return _build_sensor_anomaly_context(self._em, payload)
 
     async def build_shift_handover_context(
         self, payload: dict[str, Any]
     ) -> ShiftHandoverContext:
         """Assemble context for shift handover summary prompt."""
         return _build_shift_handover_context(self._em, payload)
 
     async def build_periodic_report_context(
         self,
         *,
         window_minutes: int = 60,
     ) -> PeriodicReportContext:
         """Aggregate engine activity over last window_minutes for periodic report.
 
         Uses get_operator_log() with time window — no new SQLite methods needed.
         All event types (alarms, phases, experiments, operator entries) are
         stored in the operator log with identifying tags.
         """
         now = datetime.now(UTC)
         start_time = now - timedelta(minutes=window_minutes)
 
         entries: list[Any] = []
+        _ctx_failed = False
         if hasattr(self._reader, "get_operator_log"):
             try:
                 entries = await self._reader.get_operator_log(
                     start_time=start_time,
                     end_time=now,
                     limit=50,
                 )
             except Exception:
-                logger.debug("PeriodicReportContext: get_operator_log failed", exc_info=True)
+                logger.warning(
+                    "PeriodicReportContext: get_operator_log failed — window data unavailable",
+                    exc_info=True,
+                )
+                _ctx_failed = True
 
         alarm_entries = [e for e in entries if "alarm" in e.tags]
-        phase_entries = [e for e in entries if "phase_transition" in e.tags]
+        phase_entries = [e for e in entries if "phase_transition" in e.tags or "phase" in e.tags]
         experiment_entries = [e for e in entries if "experiment" in e.tags]
         calibration_entries = [e for e in entries if "calibration" in e.tags]
         # Exclude machine-generated and AI-generated entries from operator section
         operator_entries = [
             e for e in entries
             if e.source != "auto" and "ai" not in e.tags and "auto" not in e.tags
         ]
         # Any auto event not classified above (calibration, leak_rate, etc.)
         other_entries = [
             e for e in entries
             if "auto" in e.tags
             and "alarm" not in e.tags
             and "phase_transition" not in e.tags
+            and "phase" not in e.tags
             and "experiment" not in e.tags
             and "calibration" not in e.tags
             and "ai" not in e.tags
         ]
 
         total_event_count = (
             len(alarm_entries) + len(phase_entries) + len(experiment_entries)
             + len(calibration_entries) + len(operator_entries) + len(other_entries)
         )
 
         experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
         phase: str | None = None
         if hasattr(self._em, "get_current_phase"):
             try:
                 phase = self._em.get_current_phase()
             except Exception:
                 pass
 
         return PeriodicReportContext(
             window_minutes=window_minutes,
             active_experiment_id=experiment_id,
             active_experiment_phase=phase,
             alarm_entries=alarm_entries,
             phase_entries=phase_entries,
             experiment_entries=experiment_entries,
             calibration_entries=calibration_entries,
             operator_entries=operator_entries,
             other_entries=other_entries,
             total_event_count=total_event_count,
+            context_read_failed=_ctx_failed,
         )
 
     async def build_diagnostic_suggestion_context(
         self,
         alarm_payload: dict[str, Any],
         *,
         lookback_min: int = 60,
     ) -> DiagnosticSuggestionContext:
         """Assemble context for Slice B diagnostic suggestion.
 
         Reads last lookback_min minutes of readings for alarm channels
         from SQLite. Alarm history, cooldown history, and pressure trend
         remain stubs until Cycle 4.1 wires those sources.
         """
         alarm_id = alarm_payload.get("alarm_id", "unknown")
         channels: list[str] = alarm_payload.get("channels", [])
         values: dict[str, float] = alarm_payload.get("values", {})
         channel_history = await self._read_channel_history(channels, lookback_min)
         pressure_trend = await self._read_pressure_trend()
         return DiagnosticSuggestionContext(
             alarm_id=alarm_id,
             channels=channels,
             values=values,
             channel_history=channel_history,
             recent_alarms="нет данных",
             past_cooldowns="нет истории",
             pressure_trend=pressure_trend,
             lookback_min=lookback_min,
         )
 
     async def _read_channel_history(self, channels: list[str], lookback_min: int) -> str:
         """Read recent readings for alarm channels from SQLite."""
         if not channels or not hasattr(self._reader, "read_readings_history"):
             return "нет данных"
         try:
             from_ts = _time.time() - lookback_min * 60
             data: dict[str, list[tuple[float, float]]] = (
                 await self._reader.read_readings_history(
                     channels=channels,
                     from_ts=from_ts,
                     limit_per_channel=20,
                 )
             )
             if not data:
                 return "нет данных"
             lines: list[str] = []
             for ch, readings in data.items():
                 if readings:
                     vals = [f"{v:.4g}" for _, v in readings[-5:]]
                     lines.append(f"- {ch}: [{', '.join(vals)}]")
             return "\n".join(lines) if lines else "нет данных"
         except Exception:
             logger.debug("ContextBuilder: channel history read failed", exc_info=True)
             return "нет данных"
 
     async def _read_pressure_trend(self) -> str:
         """Read recent pressure readings from SQLite."""
         if not hasattr(self._reader, "read_readings_history"):
             return "нет данных"
         try:
             from_ts = _time.time() - 30 * 60
             data: dict[str, list[tuple[float, float]]] = (
                 await self._reader.read_readings_history(
                     from_ts=from_ts,
                     limit_per_channel=10,
                 )
             )
             pressure = {
                 k: v
                 for k, v in data.items()
                 if "pressure" in k.lower() or "mbar" in k.lower()
             }
             if not pressure:
                 return "нет данных"
             lines: list[str] = []
             for ch, readings in pressure.items():
                 if len(readings) >= 2:
                     start = readings[0][1]
                     end = readings[-1][1]
                     threshold = 0.01 * max(abs(start), 1e-12)
@@ -436,112 +443,113 @@ class CampaignReportContext:
     """Context for Slice C campaign report intro (async EventBus path)."""
 
     experiment_id: str | None
     name: str
     duration_str: str
     phases_text: str
     channel_stats: str
     alarms_summary: str
     operator_notes: str
 
 
 # ---------------------------------------------------------------------------
 # Diagnostic suggestion context (Slice B)
 # ---------------------------------------------------------------------------
 
 
 @dataclass
 class DiagnosticSuggestionContext:
     """Context for diagnostic suggestion generation (Slice B)."""
 
     alarm_id: str
     channels: list[str]
     values: dict[str, float]
     channel_history: str
     recent_alarms: str
     past_cooldowns: str
     pressure_trend: str
     lookback_min: int = 60
 
 
 def _build_shift_handover_context(em: Any, payload: dict[str, Any]) -> ShiftHandoverContext:
     experiment_id: str | None = getattr(em, "active_experiment_id", None)
     phase: str | None = None
     if hasattr(em, "get_current_phase"):
         try:
             phase = em.get_current_phase()
         except Exception:
             pass
     age_s = _compute_experiment_age(em)
     experiment_age = _format_age(age_s) if age_s is not None else "—"
     shift_duration_h = int(payload.get("shift_duration_h", 8))
     return ShiftHandoverContext(
         experiment_id=experiment_id,
         phase=phase,
         experiment_age=experiment_age,
         active_alarms="нет данных",
         recent_events="нет данных",
         shift_duration_h=shift_duration_h,
     )
 
 
 def _format_age(age_s: float) -> str:
     h, rem = divmod(int(age_s), 3600)
     m, s = divmod(rem, 60)
     if h > 0:
         return f"{h}ч {m}м"
     if m > 0:
         return f"{m}м {s}с"
     return f"{s}с"
 
 
 # ---------------------------------------------------------------------------
 # Periodic report context (F29)
 # ---------------------------------------------------------------------------
 
 
 @dataclass
 class PeriodicReportContext:
     """Context for periodic narrative report (F29)."""
 
     window_minutes: int
     active_experiment_id: str | None
     active_experiment_phase: str | None
     alarm_entries: list[Any] = field(default_factory=list)
     phase_entries: list[Any] = field(default_factory=list)
     experiment_entries: list[Any] = field(default_factory=list)
     calibration_entries: list[Any] = field(default_factory=list)
     operator_entries: list[Any] = field(default_factory=list)
     other_entries: list[Any] = field(default_factory=list)
     total_event_count: int = 0
+    context_read_failed: bool = False
 
     def to_template_dict(self) -> dict[str, str]:
         """Format all context fields as prompt-ready strings."""
         if self.active_experiment_id:
             phase_str = (
                 f" (фаза: {self.active_experiment_phase})"
                 if self.active_experiment_phase else ""
             )
             active_exp = f"{self.active_experiment_id}{phase_str}"
         else:
             active_exp = "нет активного эксперимента"
 
         return {
             "active_experiment_summary": active_exp,
             "events_section": _format_log_entries(self.other_entries) or "(нет)",
             "alarms_section": _format_log_entries(self.alarm_entries) or "(нет)",
             "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
             "operator_entries_section": _format_log_entries(self.operator_entries) or "(нет)",
             "calibration_section": _format_log_entries(self.calibration_entries) or "(нет)",
             "total_event_count": str(self.total_event_count),
         }
 
 
 def _format_log_entries(entries: list[Any]) -> str:
     if not entries:
         return ""
     lines = []
     for e in entries[:10]:
         ts = e.timestamp.astimezone().strftime("%H:%M") if hasattr(e, "timestamp") else "?"
         msg = getattr(e, "message", str(e))[:120]
         lines.append(f"- {ts}: {msg}")
     return "\n".join(lines)
diff --git a/src/cryodaq/agents/assistant/live/prompts.py b/src/cryodaq/agents/assistant/live/prompts.py
index 4342d5b..c4f803a 100644
--- a/src/cryodaq/agents/assistant/live/prompts.py
+++ b/src/cryodaq/agents/assistant/live/prompts.py
@@ -166,127 +166,129 @@ DIAGNOSTIC_SUGGESTION_USER = """\
 ТРЕНД ДАВЛЕНИЯ (30 мин):
 {pressure_trend}
 
 Предложи конкретные диагностические действия оператору. Только русский язык.
 """
 
 # ---------------------------------------------------------------------------
 # Sensor anomaly — Slice A
 # Revision: 2026-05-01 v1 (initial)
 # ---------------------------------------------------------------------------
 
 SENSOR_ANOMALY_SYSTEM = """\
 Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
 краткий анализ аномалии датчика для оператора.
 
 Принципы:
 - Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
 - Используй только данные из запроса.
 - Объясни что именно не так: избыточный шум, дрейф, нарушение корреляции.
 - Предложи практические диагностические шаги (проверить контакты, кабель, крепление).
 - НИКОГДА не предлагай изменять параметры безопасности или отключать оборудование.
 - 60-100 слов. Telegram-friendly Markdown (жирный, курсив — ok).
 """
 
 SENSOR_ANOMALY_USER = """\
 АНОМАЛИЯ ДАТЧИКА:
 - Канал: {channel}
 - Аларм ID: {alarm_id}
 - Уровень: {level}
 - Описание: {message}
 
 ПОКАЗАТЕЛИ ЗДОРОВЬЯ:
 - Health score: {health_score}
 - Флаги: {fault_flags}
 - Текущее значение: {current_value}
 
 ЭКСПЕРИМЕНТ:
 - ID: {experiment_id}
 - Фаза: {phase}
 
 Сформируй краткий анализ аномалии для оператора. Только русский язык.
 """
 
 # ---------------------------------------------------------------------------
 # Shift handover summary — Slice A
 # Revision: 2026-05-01 v1 (initial)
 # ---------------------------------------------------------------------------
 
 SHIFT_HANDOVER_SYSTEM = """\
 Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
 подготовить сводку смены для передачи следующему оператору.
 
 Принципы:
 - Отвечай ТОЛЬКО на русском языке.
 - Структура: текущее состояние → ключевые события смены → что требует внимания.
 - Конкретные значения, никаких размытых фраз.
 - НИКОГДА не предлагай safety-действия автоматически.
 - 120-200 слов. Telegram-friendly Markdown.
 """
 
 def format_with_brand(template: str, brand_name: str) -> str:
     """Interpolate {brand_name} placeholder in a system prompt template."""
     return template.format(brand_name=brand_name)
 
 
 # ---------------------------------------------------------------------------
 # Periodic narrative report — F29
 # Revision: 2026-05-01 v1 (initial)
 # ---------------------------------------------------------------------------
 
 PERIODIC_REPORT_SYSTEM = """\
 Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.
 Твоя задача — краткий обзор активности за заданное окно времени для оператора в Telegram.
 
 Принципы:
 - Отвечай ТОЛЬКО на русском языке.
 - Не выдумывай контекст. Используй только данные ниже.
 - Конкретные значения, не размытые описания.
 - Тон conversational, не формальный (это сводка для оператора, не отчёт).
 - Если событий мало — короткий summary (5-10 слов про то что всё стабильно).
-- Если событий много — структурируй по категориям (алармы / фазы / операторский журнал / калибровка).
+- Если событий много — структурируй по категориям (алармы / фазы / операторский журнал /
+  калибровка).
 - 100-200 слов максимум. Telegram-friendly Markdown (жирный, курсив — ok).
+- Не используй LaTeX, формулы ($...$), \rightarrow и подобное. Для стрелок — →, ↑, ↓.
 - Если активного эксперимента нет — упомяни это в одной фразе.
 """
 
 PERIODIC_REPORT_USER = """\
 Окно времени: последние {window_minutes} минут.
 
 Активный эксперимент: {active_experiment_summary}
 
 Алармы:
 {alarms_section}
 
 Переходы фаз:
 {phase_transitions_section}
 
 События (прочие):
 {events_section}
 
 Записи операторского журнала:
 {operator_entries_section}
 
 Калибровка:
 {calibration_section}
 
 Всего событий: {total_event_count}
 
 Сгенерируй краткую сводку для оператора в Telegram. Только русский язык.
 """
 
 
 SHIFT_HANDOVER_USER = """\
 ЗАПРОС СВОДКИ ДЛЯ ПЕРЕДАЧИ СМЕНЫ:
 
 ТЕКУЩЕЕ СОСТОЯНИЕ:
 - Эксперимент: {experiment_id}
 - Фаза: {phase}
 - Продолжительность эксперимента: {experiment_age}
 
 АКТИВНЫЕ АЛАРМЫ:
 {active_alarms}
 
 СОБЫТИЯ ЗА СМЕНУ (последние {shift_duration_h}ч):
 {recent_events}
 
 Подготовь сводку для следующего оператора. Только русский язык.
 """
diff --git a/tests/agents/assistant/test_periodic_report_handler.py b/tests/agents/assistant/test_periodic_report_handler.py
index 0c949d4..3fd967b 100644
--- a/tests/agents/assistant/test_periodic_report_handler.py
+++ b/tests/agents/assistant/test_periodic_report_handler.py
@@ -151,80 +151,87 @@ async def test_periodic_report_handler_skips_when_idle(tmp_path: Path) -> None:
     await agent.stop()
 
 
 async def test_periodic_report_skip_if_idle_false_dispatches_always(tmp_path: Path) -> None:
     """skip_if_idle=False → dispatch even when no events."""
     telegram = AsyncMock()
     telegram._send_to_all = AsyncMock()
     ctx = _make_mock_context(total_event_count=0)
     cfg = _make_config(periodic_report_skip_if_idle=False)
     agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
     await agent.start()
 
     await bus.publish(_periodic_event())
     await asyncio.sleep(0.1)
 
     telegram._send_to_all.assert_awaited_once()
     await agent.stop()
 
 
 async def test_periodic_report_handler_handles_empty_response(tmp_path: Path) -> None:
     telegram = AsyncMock()
     telegram._send_to_all = AsyncMock()
     ctx = _make_mock_context(total_event_count=2)
     ollama = AsyncMock()
     ollama.generate = AsyncMock(
         return_value=GenerationResult(
             text="", tokens_in=10, tokens_out=0, latency_s=1.0, model="gemma4:e2b"
         )
     )
     ollama.close = AsyncMock()
     agent, bus = _make_agent(
         ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path
     )
     await agent.start()
 
     await bus.publish(_periodic_event())
     await asyncio.sleep(0.1)
 
     telegram._send_to_all.assert_not_awaited()
     await agent.stop()
 
 
 async def test_periodic_report_disabled_does_not_handle(tmp_path: Path) -> None:
     telegram = AsyncMock()
     telegram._send_to_all = AsyncMock()
     cfg = _make_config(periodic_report_enabled=False)
     ctx = _make_mock_context(total_event_count=5)
     agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
     await agent.start()
 
     await bus.publish(_periodic_event())
     await asyncio.sleep(0.05)
 
     telegram._send_to_all.assert_not_awaited()
     await agent.stop()
 
 
 # ---------------------------------------------------------------------------
 # OutputRouter prefix_suffix
 # ---------------------------------------------------------------------------
 
 
 def test_periodic_report_prefix_includes_suffix() -> None:
     router = OutputRouter(
         telegram_bot=None,
         event_logger=MagicMock(),
         event_bus=MagicMock(),
         brand_name="Гемма",
         brand_emoji="🤖",
     )
     # Verify brand_base used for suffix variant
     assert router._brand_base == "🤖 Гемма"
     # Verify standard prefix unchanged
     assert router._prefix == "🤖 Гемма:"
 
 
 def test_periodic_report_prompt_does_not_hardcode_hour_window() -> None:
     """Configured non-hourly windows must not fight a hardcoded system prompt."""
     assert "последний час" not in PERIODIC_REPORT_SYSTEM
     assert "{window_minutes}" in PERIODIC_REPORT_USER
+
+
+def test_periodic_report_prompt_prohibits_latex() -> None:
+    """PERIODIC_REPORT_SYSTEM must explicitly forbid LaTeX to prevent $\\rightarrow$ in Telegram."""
+    assert "LaTeX" in PERIODIC_REPORT_SYSTEM or "$" in PERIODIC_REPORT_SYSTEM
+    assert "rightarrow" not in PERIODIC_REPORT_SYSTEM
+    assert "→" in PERIODIC_REPORT_SYSTEM

exec
/opt/homebrew/bin/bash -lc 'git status --short && git rev-parse --show-toplevel && git rev-parse HEAD && git show --stat --oneline --decorate --no-renames 7515c7f' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
7515c7f9049dd9d43a4470128c4e3f10f71c71d3
7515c7f (HEAD -> feat/f29-periodic-reports) fix(f29): swarm audit findings CF-2 CF-3 CF-5
 src/cryodaq/agents/assistant/live/agent.py             |  8 +++++++-
 src/cryodaq/agents/assistant/live/context_builder.py   | 12 ++++++++++--
 src/cryodaq/agents/assistant/live/prompts.py           |  4 +++-
 tests/agents/assistant/test_periodic_report_handler.py |  7 +++++++
 4 files changed, 27 insertions(+), 4 deletions(-)

codex
The first pass already exposed one suspicious edge in CF-5: the prompt text uses `\rightarrow` inside a normal Python string, so I’m checking the actual runtime string representation rather than trusting the diff. That kind of escape-sequence wrinkle is exactly where prompt regressions like to hide.
exec
/opt/homebrew/bin/bash -lc "python - <<'PY'
from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM
print(repr(PERIODIC_REPORT_SYSTEM))
print('contains literal \\\\rightarrow:', '\\\\rightarrow' in PERIODIC_REPORT_SYSTEM)
print('contains carriage return:', '\\r' in PERIODIC_REPORT_SYSTEM)
print(PERIODIC_REPORT_SYSTEM.splitlines()[-2:])
PY" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
exec
/opt/homebrew/bin/bash -lc 'pytest -q tests/agents/assistant/test_periodic_report_handler.py' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: pytest: command not found

 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: python: command not found

exec
/opt/homebrew/bin/bash -lc 'rg -n "PeriodicReportContext|build_periodic_report_context|phase_transition|context_read_failed|operator_log|PERIODIC_REPORT_SYSTEM|rightarrow|LaTeX" src/cryodaq/agents/assistant/live tests/agents/assistant' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
tests/agents/assistant/test_periodic_report_handler.py:11:from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext
tests/agents/assistant/test_periodic_report_handler.py:13:from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM, PERIODIC_REPORT_USER
tests/agents/assistant/test_periodic_report_handler.py:34:        output_operator_log=True,
tests/agents/assistant/test_periodic_report_handler.py:46:def _make_mock_context(total_event_count: int = 3) -> PeriodicReportContext:
tests/agents/assistant/test_periodic_report_handler.py:47:    ctx = PeriodicReportContext(
tests/agents/assistant/test_periodic_report_handler.py:62:    context: PeriodicReportContext | None = None,
tests/agents/assistant/test_periodic_report_handler.py:73:    reader.get_operator_log = AsyncMock(return_value=[])
tests/agents/assistant/test_periodic_report_handler.py:77:        ctx_builder.build_periodic_report_context = AsyncMock(return_value=context)
tests/agents/assistant/test_periodic_report_handler.py:229:    assert "последний час" not in PERIODIC_REPORT_SYSTEM
tests/agents/assistant/test_periodic_report_handler.py:234:    """PERIODIC_REPORT_SYSTEM must explicitly forbid LaTeX to prevent $\\rightarrow$ in Telegram."""
tests/agents/assistant/test_periodic_report_handler.py:235:    assert "LaTeX" in PERIODIC_REPORT_SYSTEM or "$" in PERIODIC_REPORT_SYSTEM
tests/agents/assistant/test_periodic_report_handler.py:236:    assert "rightarrow" not in PERIODIC_REPORT_SYSTEM
tests/agents/assistant/test_periodic_report_handler.py:237:    assert "→" in PERIODIC_REPORT_SYSTEM
src/cryodaq/agents/assistant/live/agent.py:32:    PERIODIC_REPORT_SYSTEM,
src/cryodaq/agents/assistant/live/agent.py:72:    output_operator_log: bool = True
src/cryodaq/agents/assistant/live/agent.py:147:        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
src/cryodaq/agents/assistant/live/agent.py:700:        ctx = await self._ctx_builder.build_periodic_report_context(
src/cryodaq/agents/assistant/live/agent.py:704:        if ctx.context_read_failed:
src/cryodaq/agents/assistant/live/agent.py:727:        system_prompt = format_with_brand(PERIODIC_REPORT_SYSTEM, self._config.brand_name)
src/cryodaq/agents/assistant/live/agent.py:791:    if config.output_operator_log:
tests/agents/assistant/test_report_intro.py:48:    operator_log: list[_FakeLogRecord] = field(default_factory=list)
tests/agents/assistant/test_report_intro.py:58:    operator_log: list[_FakeLogRecord] | None = None,
tests/agents/assistant/test_report_intro.py:86:        operator_log=operator_log or [
tests/agents/assistant/test_report_intro.py:204:        operator_log=[
src/cryodaq/agents/assistant/live/prompts.py:236:PERIODIC_REPORT_SYSTEM = """\
src/cryodaq/agents/assistant/live/prompts.py:249:- Не используй LaTeX, формулы ($...$), \rightarrow и подобное. Для стрелок — →, ↑, ↓.
src/cryodaq/agents/assistant/live/prompts.py:262:{phase_transitions_section}
tests/agents/assistant/test_periodic_report_context.py:1:"""Tests for PeriodicReportContext and build_periodic_report_context (F29)."""
tests/agents/assistant/test_periodic_report_context.py:22:    reader.get_operator_log = AsyncMock(return_value=entries)
tests/agents/assistant/test_periodic_report_context.py:32:        _make_entry("Phase → COOL", ("auto", "phase_transition")),
tests/agents/assistant/test_periodic_report_context.py:36:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:48:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:62:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:74:        _make_entry("Phase", ("auto", "phase_transition")),
tests/agents/assistant/test_periodic_report_context.py:79:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:86:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:98:    ctx = await cb.build_periodic_report_context(window_minutes=60)
tests/agents/assistant/test_periodic_report_context.py:104:    assert "phase_transitions_section" in tmpl
tests/agents/assistant/test_periodic_report_context.py:116:    ctx = await cb.build_periodic_report_context(window_minutes=60)
src/cryodaq/agents/assistant/live/context_builder.py:108:    async def build_periodic_report_context(
src/cryodaq/agents/assistant/live/context_builder.py:112:    ) -> PeriodicReportContext:
src/cryodaq/agents/assistant/live/context_builder.py:115:        Uses get_operator_log() with time window — no new SQLite methods needed.
src/cryodaq/agents/assistant/live/context_builder.py:124:        if hasattr(self._reader, "get_operator_log"):
src/cryodaq/agents/assistant/live/context_builder.py:126:                entries = await self._reader.get_operator_log(
src/cryodaq/agents/assistant/live/context_builder.py:133:                    "PeriodicReportContext: get_operator_log failed — window data unavailable",
src/cryodaq/agents/assistant/live/context_builder.py:139:        phase_entries = [e for e in entries if "phase_transition" in e.tags or "phase" in e.tags]
src/cryodaq/agents/assistant/live/context_builder.py:152:            and "phase_transition" not in e.tags
src/cryodaq/agents/assistant/live/context_builder.py:172:        return PeriodicReportContext(
src/cryodaq/agents/assistant/live/context_builder.py:183:            context_read_failed=_ctx_failed,
src/cryodaq/agents/assistant/live/context_builder.py:510:class PeriodicReportContext:
src/cryodaq/agents/assistant/live/context_builder.py:523:    context_read_failed: bool = False
src/cryodaq/agents/assistant/live/context_builder.py:540:            "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
src/cryodaq/agents/assistant/live/output_router.py:22:    OPERATOR_LOG = "operator_log"
src/cryodaq/agents/assistant/live/output_router.py:80:                    dispatched.append("operator_log")
tests/agents/assistant/test_alarm_flow.py:48:        output_operator_log=True,
tests/agents/assistant/test_alarm_flow.py:150:        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},
tests/agents/assistant/test_alarm_flow.py:213:async def test_alarm_fired_dispatches_to_operator_log(tmp_path: Path) -> None:
tests/agents/assistant/test_alarm_flow.py:363:        output_operator_log=True,
tests/agents/assistant/test_alarm_flow.py:438:        output_operator_log=True,
tests/agents/assistant/test_alarm_flow.py:520:        output_operator_log=True,
tests/agents/assistant/test_diagnostic.py:44:        output_operator_log=True,

codex
The repo’s shell doesn’t have bare `python` or `pytest` on PATH, so I’m switching to the project’s runner instead of treating that as a test failure. I’ve also found existing periodic context tests, which matters for CF-2/CF-3 adequacy.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,170p' tests/agents/assistant/test_periodic_report_context.py" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
"""Tests for PeriodicReportContext and build_periodic_report_context (F29)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder


def _make_entry(message: str, tags: tuple[str, ...], source: str = "auto") -> MagicMock:
    entry = MagicMock()
    entry.timestamp = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    entry.message = message
    entry.tags = tags
    entry.source = source
    return entry


def _make_context_builder(entries: list, experiment_id: str | None = "exp-001") -> ContextBuilder:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=entries)
    em = MagicMock()
    em.active_experiment_id = experiment_id
    em.get_current_phase = MagicMock(return_value="COOL")
    return ContextBuilder(reader, em)


async def test_periodic_report_context_aggregates_window() -> None:
    entries = [
        _make_entry("Alarm fired", ("auto", "alarm", "alarm_T1")),
        _make_entry("Phase → COOL", ("auto", "phase_transition")),
        _make_entry("Experiment started", ("auto", "experiment")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert len(ctx.alarm_entries) == 1
    assert len(ctx.phase_entries) == 1
    assert len(ctx.experiment_entries) == 1
    assert ctx.total_event_count == 3
    assert ctx.active_experiment_id == "exp-001"
    assert ctx.active_experiment_phase == "COOL"


async def test_periodic_report_context_handles_empty_window() -> None:
    cb = _make_context_builder([])
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.total_event_count == 0
    assert ctx.alarm_entries == []
    assert ctx.phase_entries == []
    assert ctx.operator_entries == []


async def test_periodic_report_context_excludes_machine_log_entries() -> None:
    entries = [
        _make_entry("AI summary", ("auto", "ai", "abc123")),
        _make_entry("Manual note", (), source="operator"),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    # AI entry must NOT appear in operator_entries
    assert len(ctx.operator_entries) == 1
    assert ctx.operator_entries[0].message == "Manual note"
    assert ctx.total_event_count == 1  # only the operator entry


async def test_periodic_report_context_total_count_correct() -> None:
    entries = [
        _make_entry("Alarm 1", ("auto", "alarm")),
        _make_entry("Alarm 2", ("auto", "alarm")),
        _make_entry("Phase", ("auto", "phase_transition")),
        _make_entry("Operator note", (), source="operator"),
        _make_entry("Leak rate", ("auto", "leak_rate")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.total_event_count == 5


async def test_periodic_report_context_no_experiment() -> None:
    cb = _make_context_builder([], experiment_id=None)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.active_experiment_id is None
    tmpl = ctx.to_template_dict()
    assert "нет активного" in tmpl["active_experiment_summary"]


async def test_periodic_report_context_to_template_dict_structure() -> None:
    entries = [
        _make_entry("Alarm T1 high", ("auto", "alarm")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    tmpl = ctx.to_template_dict()
    assert "active_experiment_summary" in tmpl
    assert "events_section" in tmpl
    assert "alarms_section" in tmpl
    assert "phase_transitions_section" in tmpl
    assert "operator_entries_section" in tmpl
    assert "total_event_count" in tmpl
    assert "Alarm T1 high" in tmpl["alarms_section"]
    assert tmpl["total_event_count"] == "1"


async def test_periodic_report_context_formats_calibration_section() -> None:
    entries = [
        _make_entry("T1 offset +0.02 K", ("auto", "calibration")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    tmpl = ctx.to_template_dict()
    assert "T1 offset" in tmpl["calibration_section"]
    assert "T1 offset" not in tmpl["events_section"]
    assert ctx.total_event_count == 1

exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' tests/agents/assistant/test_periodic_report_handler.py" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
exec
/opt/homebrew/bin/bash -lc "rg -n \"\\[tool\\.pytest|pytest|uv|poetry|python_requires|requires-python|scripts\" pyproject.toml README* Makefile tox.ini noxfile.py setup.cfg" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
"""Tests for AssistantLiveAgent periodic_report_request handler (F29)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM, PERIODIC_REPORT_USER
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
from cryodaq.core.event_bus import EngineEvent, EventBus


def _periodic_event(window_minutes: int = 60) -> EngineEvent:
    return EngineEvent(
        event_type="periodic_report_request",
        timestamp=datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC),
        payload={"window_minutes": window_minutes, "trigger": "scheduled"},
        experiment_id="exp-001",
    )


def _make_config(**overrides) -> AssistantConfig:
    cfg = AssistantConfig(
        enabled=True,
        max_concurrent_inferences=1,
        max_calls_per_hour=60,
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=False,
        audit_enabled=False,
        periodic_report_enabled=True,
        periodic_report_min_events=1,
        periodic_report_skip_if_idle=True,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_mock_context(total_event_count: int = 3) -> PeriodicReportContext:
    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id="exp-001",
        active_experiment_phase="COOL",
        total_event_count=total_event_count,
    )
    return ctx


def _make_agent(
    *,
    config: AssistantConfig | None = None,
    ollama=None,
    telegram=None,
    event_logger=None,
    context: PeriodicReportContext | None = None,
    tmp_path: Path,
) -> tuple[AssistantLiveAgent, EventBus]:
    bus = EventBus()
    cfg = config or _make_config()
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="COOL")
    em.get_phase_history = MagicMock(return_value=[])

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    ctx_builder = ContextBuilder(reader, em)

    if context is not None:
        ctx_builder.build_periodic_report_context = AsyncMock(return_value=context)

    audit = AuditLogger(tmp_path / "audit", enabled=False)

    if telegram is None:
        telegram = AsyncMock()
        telegram._send_to_all = AsyncMock()
    if event_logger is None:
        event_logger = AsyncMock()
        event_logger.log_event = AsyncMock()

    router = OutputRouter(
        telegram_bot=telegram,
        event_logger=event_logger,
        event_bus=bus,
    )

    if ollama is None:
        ollama = AsyncMock()
        ollama.generate = AsyncMock(
            return_value=GenerationResult(
                text="Всё стабильно. Активный эксперимент в фазе охлаждения.",
                tokens_in=50,
                tokens_out=20,
                latency_s=2.0,
                model="gemma4:e2b",
            )
        )
        ollama.close = AsyncMock()

    agent = AssistantLiveAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ctx_builder,
        audit_logger=audit,
        output_router=router,
    )
    return agent, bus


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------


async def test_periodic_report_handler_dispatches_when_active(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=3)
    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_awaited_once()
    sent = telegram._send_to_all.call_args[0][0]
    assert "🤖 Гемма (отчёт за час):" in sent
    await agent.stop()


async def test_periodic_report_handler_skips_when_idle(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    # total_event_count=0 < min_events=1 → idle skip
    ctx = _make_mock_context(total_event_count=0)
    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_skip_if_idle_false_dispatches_always(tmp_path: Path) -> None:
    """skip_if_idle=False → dispatch even when no events."""
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    cfg = _make_config(periodic_report_skip_if_idle=False)
    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_awaited_once()
    await agent.stop()


async def test_periodic_report_handler_handles_empty_response(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=2)
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="", tokens_in=10, tokens_out=0, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(
        ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path
    )
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_disabled_does_not_handle(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    cfg = _make_config(periodic_report_enabled=False)
    ctx = _make_mock_context(total_event_count=5)
    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.05)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


# ---------------------------------------------------------------------------
# OutputRouter prefix_suffix
# ---------------------------------------------------------------------------


def test_periodic_report_prefix_includes_suffix() -> None:
    router = OutputRouter(
        telegram_bot=None,
        event_logger=MagicMock(),
        event_bus=MagicMock(),
        brand_name="Гемма",
        brand_emoji="🤖",
    )
    # Verify brand_base used for suffix variant
    assert router._brand_base == "🤖 Гемма"
    # Verify standard prefix unchanged
    assert router._prefix == "🤖 Гемма:"


def test_periodic_report_prompt_does_not_hardcode_hour_window() -> None:
    """Configured non-hourly windows must not fight a hardcoded system prompt."""
    assert "последний час" not in PERIODIC_REPORT_SYSTEM
    assert "{window_minutes}" in PERIODIC_REPORT_USER


def test_periodic_report_prompt_prohibits_latex() -> None:
    """PERIODIC_REPORT_SYSTEM must explicitly forbid LaTeX to prevent $\\rightarrow$ in Telegram."""
    assert "LaTeX" in PERIODIC_REPORT_SYSTEM or "$" in PERIODIC_REPORT_SYSTEM
    assert "rightarrow" not in PERIODIC_REPORT_SYSTEM
    assert "→" in PERIODIC_REPORT_SYSTEM

 exited 2 in 0ms:
rg: Makefile: No such file or directory (os error 2)
rg: tox.ini: No such file or directory (os error 2)
rg: noxfile.py: No such file or directory (os error 2)
rg: setup.cfg: No such file or directory (os error 2)
pyproject.toml:9:requires-python = ">=3.12"
pyproject.toml:51:    "pytest>=8",
pyproject.toml:52:    "pytest-asyncio>=0.23",
pyproject.toml:53:    "pytest-cov>=4",
pyproject.toml:54:    "pytest-timeout>=2.0",
pyproject.toml:61:    "uvicorn[standard]>=0.29",
pyproject.toml:69:[project.scripts]
pyproject.toml:83:[tool.pytest.ini_options]
README.md:139:Запуск `pytest` без `pip install -e ...` не поддерживается.
README.md:151:uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080  # опциональный web
README.md:219:tsp/             # Keithley TSP scripts (черновик, не загружен)
README.md:227:python -m pytest tests/core -q
README.md:228:python -m pytest tests/storage -q
README.md:229:python -m pytest tests/drivers -q
README.md:230:python -m pytest tests/analytics -q
README.md:231:python -m pytest tests/gui -q
README.md:232:python -m pytest tests/reporting -q

exec
/opt/homebrew/bin/bash -lc "sed -n '170,260p' tests/agents/assistant/test_periodic_report_context.py" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
exec
/opt/homebrew/bin/bash -lc 'ls -1' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
CHANGELOG.md
CLAUDE.md
LICENSE
PROJECT_STATUS.md
README.md
RELEASE_CHECKLIST.md
ROADMAP.md
THIRD_PARTY_NOTICES.md
artifacts
build_scripts
config
create_shortcut.py
data
docs
install.bat
plugins
pyproject.toml
requirements-lock.txt
scripts
src
start.bat
start.sh
start_mock.bat
start_mock.sh
tests
tools
tsp

exec
/opt/homebrew/bin/bash -lc 'command -v uv || command -v python3 || command -v hatch || command -v rye' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
/opt/homebrew/bin/uv

codex
There are no added context-builder tests for the new `phase` tag or read-failure flag in the existing context test file. I’m going to run the targeted tests through `uv` and separately print the prompt representation with the same interpreter, because the current regression test may be checking the wrong thing.
codex
`uv` is present but its default cache is outside the writable sandbox, so I’m rerunning with a temporary cache under `/tmp`. That keeps the verification local to this workspace and avoids asking for permissions we don’t have in this session.
exec
/opt/homebrew/bin/bash -lc "UV_CACHE_DIR=/tmp/uv-cache uv run python - <<'PY'
from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM
print(repr(PERIODIC_REPORT_SYSTEM))
print('literal \\\\rightarrow:', '\\\\rightarrow' in PERIODIC_REPORT_SYSTEM)
print('carriage return:', '\\r' in PERIODIC_REPORT_SYSTEM)
for i,line in enumerate(PERIODIC_REPORT_SYSTEM.splitlines(),1):
    if 'LaTeX' in line or 'ightarrow' in line or 'подобное' in line:
        print(i, repr(line))
PY" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
exec
/opt/homebrew/bin/bash -lc 'UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/agents/assistant/test_periodic_report_handler.py tests/agents/assistant/test_periodic_report_context.py' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 exited 2 in 5662ms:
error: Request failed after 3 retries in 5.6s
  Caused by: Failed to fetch: `https://pypi.org/simple/pyinstaller/`
  Caused by: error sending request for url (https://pypi.org/simple/pyinstaller/)
  Caused by: client error (Connect)
  Caused by: dns error
  Caused by: failed to lookup address information: nodename nor servname provided, or not known

 exited 2 in 10532ms:
error: Request failed after 3 retries in 4.9s
  Caused by: Failed to fetch: `https://pypi.org/simple/uvicorn/`
  Caused by: error sending request for url (https://pypi.org/simple/uvicorn/)
  Caused by: client error (Connect)
  Caused by: dns error
  Caused by: failed to lookup address information: nodename nor servname provided, or not known

codex
The temporary-cache run tried to resolve packages from PyPI and hit the network wall. I can still verify the prompt and pure source behavior with `python3` plus `PYTHONPATH=src`, and I’ll check whether there’s a local environment for pytest before I call that part unavailable.
exec
/opt/homebrew/bin/bash -lc "command -v python3 && command -v pytest || true && find . -maxdepth 2 -type f \\( -name python -o -name pytest \\) | sed -n '1,40p'" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
/opt/homebrew/bin/python3

exec
/opt/homebrew/bin/bash -lc "ls -la | sed -n '1,80p'" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
total 592
drwxr-xr-x@ 39 vladimir  staff    1248 May  1 00:03 .
drwxr-xr-x@  5 vladimir  staff     160 Apr 30 17:58 ..
drwxr-xr-x@  3 vladimir  staff      96 Apr 30 17:58 .claude
-rw-r--r--@  1 vladimir  staff      82 Apr 30 17:58 .git
-rw-r--r--@  1 vladimir  staff      26 Apr 30 17:58 .gitattributes
drwxr-xr-x@  3 vladimir  staff      96 Apr 30 17:58 .github
-rw-r--r--@  1 vladimir  staff    1574 Apr 30 17:58 .gitignore
-rw-r--r--@  1 vladimir  staff     879 Apr 30 17:58 .graphifyignore
drwxr-xr-x@  5 vladimir  staff     160 May  1 00:07 .omc
drwxr-xr-x@  6 vladimir  staff     192 Apr 30 18:00 .pytest_cache
drwxr-xr-x@  5 vladimir  staff     160 May  1 00:03 .ruff_cache
drwxr-xr-x@  9 vladimir  staff     288 Apr 30 18:00 .venv
-rw-r--r--@  1 vladimir  staff  110118 Apr 30 18:18 CHANGELOG.md
-rw-r--r--@  1 vladimir  staff   28855 Apr 30 17:58 CLAUDE.md
-rw-r--r--@  1 vladimir  staff   11339 Apr 30 17:58 LICENSE
-rw-r--r--@  1 vladimir  staff   25669 Apr 30 17:58 PROJECT_STATUS.md
-rw-r--r--@  1 vladimir  staff   17333 Apr 30 17:58 README.md
-rw-r--r--@  1 vladimir  staff    9594 Apr 30 17:58 RELEASE_CHECKLIST.md
-rw-r--r--@  1 vladimir  staff   27393 Apr 30 18:18 ROADMAP.md
-rw-r--r--@  1 vladimir  staff    2076 Apr 30 17:58 THIRD_PARTY_NOTICES.md
drwxr-xr-x@ 11 vladimir  staff     352 Apr 30 17:58 artifacts
drwxr-xr-x@  6 vladimir  staff     192 Apr 30 17:58 build_scripts
drwxr-xr-x@ 20 vladimir  staff     640 Apr 30 17:58 config
-rw-r--r--@  1 vladimir  staff    2578 Apr 30 17:58 create_shortcut.py
drwxr-xr-x@  3 vladimir  staff      96 Apr 30 18:02 data
drwxr-xr-x@ 24 vladimir  staff     768 Apr 30 17:58 docs
-rw-r--r--@  1 vladimir  staff    2504 Apr 30 17:58 install.bat
drwxr-xr-x@  9 vladimir  staff     288 Apr 30 17:58 plugins
-rw-r--r--@  1 vladimir  staff    3186 Apr 30 18:16 pyproject.toml
-rw-r--r--@  1 vladimir  staff    4203 Apr 30 17:58 requirements-lock.txt
drwxr-xr-x@  3 vladimir  staff      96 Apr 30 17:58 scripts
drwxr-xr-x@  3 vladimir  staff      96 Apr 30 17:58 src
-rw-r--r--@  1 vladimir  staff     221 Apr 30 17:58 start.bat
-rw-r--r--@  1 vladimir  staff     115 Apr 30 17:58 start.sh
-rw-r--r--@  1 vladimir  staff     267 Apr 30 17:58 start_mock.bat
-rw-r--r--@  1 vladimir  staff     130 Apr 30 17:58 start_mock.sh
drwxr-xr-x@ 30 vladimir  staff     960 Apr 30 18:00 tests
drwxr-xr-x@ 15 vladimir  staff     480 Apr 30 17:58 tools
drwxr-xr-x@  4 vladimir  staff     128 Apr 30 17:58 tsp

exec
/opt/homebrew/bin/bash -lc "PYTHONPATH=src python3 - <<'PY'
from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM
print(repr(PERIODIC_REPORT_SYSTEM))
print('literal \\\\rightarrow:', '\\\\rightarrow' in PERIODIC_REPORT_SYSTEM)
print('carriage return:', '\\r' in PERIODIC_REPORT_SYSTEM)
for i,line in enumerate(PERIODIC_REPORT_SYSTEM.splitlines(),1):
    if 'LaTeX' in line or 'ightarrow' in line or 'подобное' in line:
        print(i, repr(line))
PY" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
'Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.\nТвоя задача — краткий обзор активности за заданное окно времени для оператора в Telegram.\n\nПринципы:\n- Отвечай ТОЛЬКО на русском языке.\n- Не выдумывай контекст. Используй только данные ниже.\n- Конкретные значения, не размытые описания.\n- Тон conversational, не формальный (это сводка для оператора, не отчёт).\n- Если событий мало — короткий summary (5-10 слов про то что всё стабильно).\n- Если событий много — структурируй по категориям (алармы / фазы / операторский журнал /\n  калибровка).\n- 100-200 слов максимум. Telegram-friendly Markdown (жирный, курсив — ok).\n- Не используй LaTeX, формулы ($...$), \rightarrow и подобное. Для стрелок — →, ↑, ↓.\n- Если активного эксперимента нет — упомяни это в одной фразе.\n'
literal \rightarrow: False
carriage return: True
13 '- Не используй LaTeX, формулы ($...$), '
14 'ightarrow и подобное. Для стрелок — →, ↑, ↓.'

exec
/opt/homebrew/bin/bash -lc ".venv/bin/python - <<'PY'
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from cryodaq.agents.assistant.live.context_builder import ContextBuilder


def entry(msg, tags, source='auto'):
    e=MagicMock(); e.timestamp=datetime(2026,5,1,12,tzinfo=UTC); e.message=msg; e.tags=tags; e.source=source; return e

async def main():
    reader=MagicMock(); reader.get_operator_log=AsyncMock(return_value=[entry('Phase tag only', ('auto','phase')), entry('Leak', ('auto','leak_rate'))])
    em=MagicMock(); em.active_experiment_id='exp'; em.get_current_phase=MagicMock(return_value='COOL')
    ctx=await ContextBuilder(reader, em).build_periodic_report_context()
    print('phase_entries', len(ctx.phase_entries), [e.message for e in ctx.phase_entries])
    print('other_entries', len(ctx.other_entries), [e.message for e in ctx.other_entries])
    print('total', ctx.total_event_count, 'failed', ctx.context_read_failed)
    reader2=MagicMock(); reader2.get_operator_log=AsyncMock(side_effect=RuntimeError('boom'))
    ctx2=await ContextBuilder(reader2, em).build_periodic_report_context()
    print('failed ctx', ctx2.context_read_failed, ctx2.total_event_count)
asyncio.run(main())
PY" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 0ms:
PeriodicReportContext: get_operator_log failed — window data unavailable
Traceback (most recent call last):
  File "/Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports/src/cryodaq/agents/assistant/live/context_builder.py", line 126, in build_periodic_report_context
    entries = await self._reader.get_operator_log(
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/unittest/mock.py", line 2326, in _execute_mock_call
    raise effect
RuntimeError: boom
phase_entries 1 ['Phase tag only']
other_entries 1 ['Leak']
total 2 failed False
failed ctx True 0

exec
/opt/homebrew/bin/bash -lc '.venv/bin/python -m pytest -q tests/agents/assistant/test_periodic_report_handler.py tests/agents/assistant/test_periodic_report_context.py' in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 748ms:
...............                                                          [100%]
15 passed in 0.57s

codex
Targeted tests pass, but they pass despite the prompt string having an embedded carriage return. I’m doing one tiny behavior probe for the CF-2 handler path now: `total_event_count=0` plus `context_read_failed=True` should still dispatch.
exec
/opt/homebrew/bin/bash -lc ".venv/bin/python - <<'PY'
import asyncio
from pathlib import Path
from tests.agents.assistant.test_periodic_report_handler import _make_agent, _periodic_event, _make_mock_context

async def main():
    telegram = __import__('unittest.mock').mock.AsyncMock(); telegram._send_to_all = __import__('unittest.mock').mock.AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    ctx.context_read_failed = True
    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=Path('/tmp/f29-audit'))
    await agent.start()
    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)
    print('telegram awaited:', telegram._send_to_all.await_count)
    await agent.stop()
asyncio.run(main())
PY" in /Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports
 succeeded in 201ms:
telegram awaited: 1

codex
Overall: **FAIL** due CF-5. Narrow audit only.

**CF-2: PASS, with test gap**
Implementation is correct: `get_operator_log()` failure logs at WARNING, sets `context_read_failed=True`, and `_handle_periodic_report()` bypasses idle skip when that flag is set. I verified with a one-off handler probe: `total_event_count=0`, `context_read_failed=True` dispatched once.
Regression risk looks low. Test is not adequate as a committed regression: no test asserts failed context read bypasses `skip_if_idle`.

**CF-3: PASS, with test gap**
Implementation is correct: `phase_entries` now includes both `"phase_transition"` and `"phase"`, and `other_entries` excludes both, avoiding double-classification. I verified a `"phase"` entry lands in phase entries, not other entries.
No regression found in the scoped logic. Test is not adequate: existing tests still cover only `"phase_transition"`, not the actual fixed `"phase"` tag.

**CF-5: FAIL**
Prompt fix is not complete. In [prompts.py](/Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports/src/cryodaq/agents/assistant/live/prompts.py:249), `\rightarrow` is inside a normal Python string, so at runtime it becomes a carriage return plus `ightarrow`, splitting the prompt line. It does **not** contain literal `\\rightarrow`.
The regression test is inadequate and misleading: `assert "rightarrow" not in PERIODIC_REPORT_SYSTEM` passes because the escape was corrupted, not because the prompt correctly forbids it. It should likely assert no control chars and/or use `\\rightarrow` or a raw string.

Verification run: `.venv/bin/python -m pytest -q tests/agents/assistant/test_periodic_report_handler.py tests/agents/assistant/test_periodic_report_context.py` passed: `15 passed`.
tokens used
82 275
Overall: **FAIL** due CF-5. Narrow audit only.

**CF-2: PASS, with test gap**
Implementation is correct: `get_operator_log()` failure logs at WARNING, sets `context_read_failed=True`, and `_handle_periodic_report()` bypasses idle skip when that flag is set. I verified with a one-off handler probe: `total_event_count=0`, `context_read_failed=True` dispatched once.
Regression risk looks low. Test is not adequate as a committed regression: no test asserts failed context read bypasses `skip_if_idle`.

**CF-3: PASS, with test gap**
Implementation is correct: `phase_entries` now includes both `"phase_transition"` and `"phase"`, and `other_entries` excludes both, avoiding double-classification. I verified a `"phase"` entry lands in phase entries, not other entries.
No regression found in the scoped logic. Test is not adequate: existing tests still cover only `"phase_transition"`, not the actual fixed `"phase"` tag.

**CF-5: FAIL**
Prompt fix is not complete. In [prompts.py](/Users/vladimir/Projects/cryodaq/.worktrees/feat-f29-periodic-reports/src/cryodaq/agents/assistant/live/prompts.py:249), `\rightarrow` is inside a normal Python string, so at runtime it becomes a carriage return plus `ightarrow`, splitting the prompt line. It does **not** contain literal `\\rightarrow`.
The regression test is inadequate and misleading: `assert "rightarrow" not in PERIODIC_REPORT_SYSTEM` passes because the escape was corrupted, not because the prompt correctly forbids it. It should likely assert no control chars and/or use `\\rightarrow` or a raw string.

Verification run: `.venv/bin/python -m pytest -q tests/agents/assistant/test_periodic_report_handler.py tests/agents/assistant/test_periodic_report_context.py` passed: `15 passed`.
