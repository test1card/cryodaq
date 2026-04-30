# F29 Cycle 1 audit — periodic narrative reports

## Context

CryoDAQ is a production cryogenic data-acquisition system. v0.46.0
ships F29: hourly Russian-language narrative summary of last-N-minutes
engine activity, dispatched to Telegram + operator log + GUI insight
panel.

This commit was already self-audited by Codex gpt-5.5 — that audit
found 2 real issues which were fixed before this audit. Your job
is independent verification: are there issues that Codex missed?

## Scope

Branch: feat/f29-periodic-reports
Final commit: ef0a1eb (release: v0.46.0)
Diff range: master..feat/f29-periodic-reports

## Files in scope

- src/cryodaq/engine.py — _periodic_report_tick coroutine, startup wiring
- src/cryodaq/agents/assistant/live/agent.py — _handle_periodic_report
- src/cryodaq/agents/assistant/live/context_builder.py — build_periodic_report_context, PeriodicReportContext
- src/cryodaq/agents/assistant/live/prompts.py — PERIODIC_REPORT_SYSTEM/USER
- src/cryodaq/agents/assistant/live/output_router.py — prefix_suffix support
- config/agent.yaml — triggers.periodic_report block
- tests/agents/assistant/test_engine_periodic_report_tick.py
- tests/agents/assistant/test_periodic_report_config.py
- tests/agents/assistant/test_periodic_report_context.py
- tests/agents/assistant/test_periodic_report_handler.py
- artifacts/scripts/smoke_f29_periodic_report.py
- CHANGELOG.md, ROADMAP.md, pyproject.toml (release bump)

## Already fixed in pre-audit pass (DO NOT report these as findings)

The following issues were caught by Codex self-audit and FIXED in
ef0a1eb. Reporting them again will be classified as
HALLUCINATION_ECHO and lower your score:

1. PERIODIC_REPORT_SYSTEM hardcoded "последний час" wording —
   FIXED to "заданное окно времени"
2. Calibration events bucketed into other-events instead of own
   section — FIXED with calibration_entries field + Калибровка:
   prompt section
3. Smoke harness fake timer sleep loop — FIXED with CancelledError
   on second sleep

## Your task

Independent review. Focus on:

1. **Engine integration** — _periodic_report_tick startup,
   shutdown, cancellation, exception handling. Could it crash
   the engine? Could it leak tasks? Could it block other
   periodic ticks?
2. **EventBus contract** — periodic_report_request payload schema.
   Does it match what handler expects? Is window_minutes int or
   float?
3. **Skip-if-idle correctness** — total_event_count threshold.
   Does it count what it should count? Could empty intervals
   slip through? Could populated intervals get suppressed?
4. **Rate limiter interaction** — periodic_report shares bucket
   with other triggers. Could a stuck periodic block other
   handlers? Could rate limit drop a periodic without
   acknowledgement?
5. **Russian prompt grounding** — does PERIODIC_REPORT_USER
   actually pass real data through? Could it hallucinate events?
   Could empty sections leak placeholders?
6. **Output dispatch path** — prefix_suffix passed to all 3
   channels (Telegram, log, GUI)? Could one fail silently?
7. **Test coverage gaps** — what scenarios are NOT tested?
   - Engine timer cancellation mid-inference
   - Concurrent periodic + alarm dispatch
   - Empty Ollama response handling
   - SQLite read failure during context build
   - Misconfigured interval (negative, zero, float)
8. **Russian quality regressions** — anything in PERIODIC_REPORT_*
   templates that could degrade quality vs F28 Slice A baseline?
9. **Markdown rendering in Telegram** — sample output contained
   `$\rightarrow$` (LaTeX). Does the prompt instruct against
   LaTeX? Does the output sanitizer strip it? This is a known
   architect concern not yet addressed.
10. **Locale / timezone** — do timestamps in summaries use
    consistent timezone? Could DST transition cause off-by-1h?

## Output format

Verdict: PASS / CONDITIONAL / FAIL

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- File:line reference (must exist in actual diff — verify)
- Description: what's wrong, in 1-3 sentences
- Why it matters: 1 sentence operational impact
- Recommended fix: 1-2 sentences

If no findings: brief explanation why confidence is high after
review.

## Constraints

- Be specific. Vague concerns ("may have issues") are not findings.
- Reference exact lines from the diff. Speculation about code not
  shown will be classified as hallucination.
- Keep response under 1500 words. Quality over quantity.
- Russian or English both fine. Russian preferred for findings
  about Russian prompt quality.
- DO NOT echo the 3 already-fixed findings in §"Already fixed".

## Diff
```diff
config/agent.yaml                                  |  49 ++
 src/cryodaq/agents/assistant/live/agent.py         | 801 +++++++++++++++++++++
 .../agents/assistant/live/context_builder.py       | 547 ++++++++++++++
 src/cryodaq/agents/assistant/live/output_router.py | 109 +++
 src/cryodaq/agents/assistant/live/prompts.py       | 292 ++++++++
 src/cryodaq/engine.py                              | 189 ++++-
 .../assistant/test_engine_periodic_report_tick.py  | 107 +++
 .../assistant/test_periodic_report_config.py       |  59 ++
 .../assistant/test_periodic_report_context.py      | 121 ++++
 .../assistant/test_periodic_report_handler.py      | 230 ++++++
 10 files changed, 2503 insertions(+), 1 deletion(-)

--- Changes ---

config/agent.yaml
  @@ -0,0 +1,49 @@
  +agent:
  +  enabled: true
  +  brand_name: "Гемма"
  +  brand_emoji: "🤖"
  +
  +  ollama:
  +    base_url: http://localhost:11434
  +    default_model: gemma4:e2b
  +    timeout_s: 60  # gemma4:e2b runs comfortably on M5 24GB; thinking-first still applies
  +    temperature: 0.3
  +    # num_ctx: 4096  # Uncomment to reduce context window for faster inference
  +    # Note: gemma4:e4b also pulled (~14GB) but doesn't fit on M5 alongside engine + GUI.
  +    # Switch to e4b only on dedicated GPU box (e.g. RTX with ≥16GB VRAM).
  +
  +  triggers:
  +    alarm_fired:
  +      enabled: true
  +      min_level: WARNING
  +    experiment_finalize:
  +      enabled: true
  +    sensor_anomaly_critical:
  +      enabled: true
  +    shift_handover_request:
  +      enabled: true
  +    phase_transition_to_finalize:
  +      enabled: true
  +    periodic_report:
  +      enabled: true
  +      interval_minutes: 60
  +      skip_if_idle: true
  +      min_events_for_dispatch: 1
  +
  +  outputs:
  +    telegram: true
  +    operator_log: true
  +    gui_insight_panel: true
  +
  +  rate_limit:
  +    max_calls_per_hour: 60
  +    max_concurrent_inferences: 2
  +
  +  slices:
  +    a_notification: true
  +    b_suggestion: true
  +    c_campaign_report: true
  +
  +  audit:
  +    enabled: true
  +    retention_days: 90
  +49 -0

src/cryodaq/agents/assistant/live/agent.py
  @@ -0,0 +1,801 @@
  +"""AssistantLiveAgent — local LLM agent observing engine events.
  +
  +Service named Гемма (after the underlying Gemma 4 model via Ollama).
  +Subscribes to EventBus, generates Russian-language operator insights,
  +dispatches to Telegram + operator log + GUI insight panel.
  +
  +Constraints (ORCHESTRATION v1.3 §13):
  +- NEVER executes engine commands or modifies engine state.
  +- Text-only output channels (Telegram, log, GUI).
  +- Fails gracefully if Ollama is unavailable — engine continues.
  +"""
  +
  +from __future__ import annotations
  +
  +import asyncio
  +import logging
  +import time
  +from collections import deque
  +from dataclasses import dataclass, field
  +from pathlib import Path
  +from typing import Any
  +
  +from cryodaq.agents.assistant.live.context_builder import ContextBuilder
  +from cryodaq.agents.assistant.live.output_router import OutputRouter, OutputTarget
  +from cryodaq.agents.assistant.live.prompts import (
  +    ALARM_SUMMARY_SYSTEM,
  +    ALARM_SUMMARY_USER,
  +    DIAGNOSTIC_SUGGESTION_SYSTEM,
  +    DIAGNOSTIC_SUGGESTION_USER,
  +    EXPERIMENT_FINALIZE_SYSTEM,
  +    EXPERIMENT_FINALIZE_USER,
  +    PERIODIC_REPORT_SYSTEM,
  +    PERIODIC_REPORT_USER,
  +    SENSOR_ANOMALY_SYSTEM,
  +    SENSOR_ANOMALY_USER,
  +    SHIFT_HANDOVER_SYSTEM,
  +    SHIFT_HANDOVER_USER,
  +    format_with_brand,
  +)
  +from cryodaq.agents.assistant.shared.audit import AuditLogger
  +from cryodaq.agents.assistant.shared.ollama_client import (
  +    OllamaClient,
  +    OllamaModelMissingError,
  +    OllamaUnavailableError,
  +)
  +from cryodaq.core.event_bus import EngineEvent, EventBus
  +
  +logger = logging.getLogger(__name__)
  +
  +_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
  +
  +
  +@dataclass
  +class AssistantConfig:
  +    enabled: bool = True
  +    ollama_base_url: str = "http://localhost:11434"
  +    default_model: str = "gemma4:e4b"
  +    timeout_s: float = 30.0
  +    temperature: float = 0.3
  +    max_tokens: int = 2048  # gemma4:e4b is thinking-first; needs 2048+ for thought + response
  +    max_concurrent_inferences: int = 2
  +    max_calls_per_hour: int = 60
  +    alarm_fired_enabled: bool = True
  +    alarm_min_level: str = "WARNING"
  +    experiment_finalize_enabled: bool = True
  +    sensor_anomaly_critical_enabled: bool = True
  +    shift_handover_request_enabled: bool = True
  +    slice_a_notification: bool = True
  +    slice_b_suggestion: bool = False
  +    slice_c_campaign_report: bool = False
  +    output_telegram: bool = True
  +    output_operator_log: bool = True
  +    output_gui_insight: bool = True
  +    audit_enabled: bool = True
  +    audit_retention_days: int = 90
  +    num_ctx: int | None = None  # Ollama context window override; None = use model default
  +    audit_dir: Path = field(default_factory=lambda: Path("data/agents/assistant/audit"))
  +    brand_name: str = "Гемма"
  +    brand_emoji: str = "🤖"
  +    periodic_report_enabled: bool = True
  +    periodic_report_interval_minutes: int = 60
  +    periodic_report_skip_if_idle: bool = True
  +    periodic_report_min_events: int = 1
  +
  +    def get_periodic_report_interval_s(self) -> float:
  +        """Return interval in seconds, or 0 if periodic reports are disabled."""
  +        if not self.periodic_report_enabled:
  +            return 0.0
  +        return float(self.periodic_report_interval_minutes * 60)
  +
  +    @classmethod
  +    def from_dict(cls, d: dict[str, Any]) -> AssistantConfig:
  +        """Build from agent.yaml agent section dict."""
  +        cfg = cls()
  +        cfg.enabled = bool(d.get("enabled", True))
  +        ollama = d.get("ollama", {})
  +        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
  +        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
  +        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
  +        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
  ... (701 lines truncated)
  +801 -0

src/cryodaq/agents/assistant/live/context_builder.py
  @@ -0,0 +1,547 @@
  +"""Context assembler for GemmaAgent LLM prompts.
  +
  +Each task type (alarm summary, diagnostic, campaign report) requires
  +different context. Builders read SQLite state and format compact text
  +for LLM token budget.
  +
  +Cycle 1: AlarmContext dataclass + build_alarm_context interface.
  +Cycle 3: ExperimentFinalizeContext, SensorAnomalyContext, ShiftHandoverContext added.
  +Cycle 4: DiagnosticSuggestionContext + real SQLite channel history reads.
  +Slice C (campaign) contexts deferred.
  +"""
  +
  +from __future__ import annotations
  +
  +import logging
  +import time as _time
  +from dataclasses import dataclass, field
  +from datetime import UTC, datetime, timedelta
  +from typing import Any
  +
  +logger = logging.getLogger(__name__)
  +
  +
  +@dataclass
  +class AlarmContext:
  +    """Context for alarm summary generation (Slice A)."""
  +
  +    alarm_id: str
  +    level: str
  +    channels: list[str]
  +    values: dict[str, float]
  +    phase: str | None
  +    experiment_id: str | None
  +    experiment_age_s: float | None
  +    target_temp: float | None
  +    active_interlocks: list[str] = field(default_factory=list)
  +    recent_readings_text: str = ""
  +    recent_alarms_text: str = ""
  +
  +
  +class ContextBuilder:
  +    """Assembles engine state for LLM prompt construction."""
  +
  +    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
  +        self._reader = sqlite_reader
  +        self._em = experiment_manager
  +
  +    async def build_alarm_context(
  +        self,
  +        alarm_payload: dict[str, Any],
  +        *,
  +        lookback_s: float = 60.0,
  +        recent_alarm_lookback_s: float = 3600.0,
  +    ) -> AlarmContext:
  +        """Assemble context for a Slice A alarm summary prompt.
  +
  +        Reads experiment state from ExperimentManager (in-memory, fast).
  +        SQLite reading history and alarm history wired in Cycle 4 — historical SQLite context.
  +        """
  +        alarm_id = alarm_payload.get("alarm_id", "unknown")
  +        channels: list[str] = alarm_payload.get("channels", [])
  +        values: dict[str, float] = alarm_payload.get("values", {})
  +        level: str = alarm_payload.get("level", "WARNING")
  +
  +        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
  +
  +        phase: str | None = None
  +        if hasattr(self._em, "get_current_phase"):
  +            try:
  +                phase = self._em.get_current_phase()
  +            except Exception:
  +                pass
  +
  +        experiment_age_s: float | None = _compute_experiment_age(self._em)
  +
  +        return AlarmContext(
  +            alarm_id=alarm_id,
  +            level=level,
  +            channels=channels,
  +            values=values,
  +            phase=phase,
  +            experiment_id=experiment_id,
  +            experiment_age_s=experiment_age_s,
  +            target_temp=None,
  +            active_interlocks=[],
  +            recent_readings_text=_readings_stub(channels, lookback_s),
  +            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
  +        )
  +
  +    async def build_experiment_finalize_context(
  +        self, payload: dict[str, Any]
  +    ) -> ExperimentFinalizeContext:
  +        """Assemble context for experiment finalize/stop/abort prompt."""
  +        return _build_experiment_finalize_context(self._em, payload)
  +
  +    async def build_sensor_anomaly_context(
  +        self, payload: dict[str, Any]
  +    ) -> SensorAnomalyContext:
  +        """Assemble context for sensor anomaly analysis prompt."""
  +        return _build_sensor_anomaly_context(self._em, payload)
  ... (447 lines truncated)
  +547 -0

src/cryodaq/agents/assistant/live/output_router.py
  @@ -0,0 +1,109 @@
  +"""Output routing for GemmaAgent LLM responses.
  +
  +Dispatches generated text to configured output channels.
  +Every output is prefixed with "🤖 Гемма:" so operators immediately
  +distinguish AI-generated content from human input.
  +"""
  +
  +from __future__ import annotations
  +
  +import enum
  +import logging
  +from typing import TYPE_CHECKING, Any
  +
  +if TYPE_CHECKING:
  +    from cryodaq.core.event_bus import EngineEvent, EventBus
  +    from cryodaq.core.event_logger import EventLogger
  +
  +logger = logging.getLogger(__name__)
  +
  +class OutputTarget(enum.Enum):
  +    TELEGRAM = "telegram"
  +    OPERATOR_LOG = "operator_log"
  +    GUI_INSIGHT = "gui_insight"
  +
  +
  +class OutputRouter:
  +    """Dispatches AssistantLiveAgent LLM output to configured channels."""
  +
  +    def __init__(
  +        self,
  +        *,
  +        telegram_bot: Any | None,
  +        event_logger: EventLogger,
  +        event_bus: EventBus,
  +        brand_name: str = "Гемма",
  +        brand_emoji: str = "🤖",
  +    ) -> None:
  +        self._telegram = telegram_bot
  +        self._event_logger = event_logger
  +        self._event_bus = event_bus
  +        self._brand_base = f"{brand_emoji} {brand_name}"
  +        self._prefix = f"{self._brand_base}:"
  +
  +    async def dispatch(
  +        self,
  +        trigger_event: EngineEvent,
  +        llm_output: str,
  +        *,
  +        targets: list[OutputTarget],
  +        audit_id: str,
  +        prefix_suffix: str = "",
  +    ) -> list[str]:
  +        """Send llm_output to all configured targets.
  +
  +        prefix_suffix: optional text inserted before the colon, e.g. "(отчёт за час)".
  +        Returns list of successfully dispatched target names.
  +        """
  +        dispatched: list[str] = []
  +        if prefix_suffix:
  +            prefix = f"{self._brand_base} {prefix_suffix}:"
  +        else:
  +            prefix = self._prefix
  +        prefixed = f"{prefix} {llm_output}"
  +
  +        for target in targets:
  +            try:
  +                if target == OutputTarget.TELEGRAM:
  +                    if self._telegram is not None:
  +                        await self._telegram._send_to_all(prefixed)
  +                        dispatched.append("telegram")
  +                    else:
  +                        logger.debug("OutputRouter: Telegram bot not configured, skipping")
  +
  +                elif target == OutputTarget.OPERATOR_LOG:
  +                    await self._event_logger.log_event(
  +                        "assistant",
  +                        prefixed,
  +                        extra_tags=["ai", audit_id],
  +                    )
  +                    dispatched.append("operator_log")
  +
  +                elif target == OutputTarget.GUI_INSIGHT:
  +                    from datetime import UTC, datetime
  +
  +                    from cryodaq.core.event_bus import EngineEvent as _EngineEvent
  +
  +                    await self._event_bus.publish(
  +                        _EngineEvent(
  +                            event_type="assistant_insight",
  +                            timestamp=datetime.now(UTC),
  +                            payload={
  +                                "text": llm_output,
  +                                "trigger_event_type": trigger_event.event_type,
  +                                "audit_id": audit_id,
  +                            },
  +                            experiment_id=trigger_event.experiment_id,
  +                        )
  +                    )
  +                    dispatched.append("gui_insight")
  +
  ... (9 lines truncated)
  +109 -0

src/cryodaq/agents/assistant/live/prompts.py
  @@ -0,0 +1,292 @@
  +"""Prompt templates for GemmaAgent.
  +
  +All operator-facing output is Russian per project standard (CryoDAQ is
  +a Russian-language product; operators are Russian-speaking).
  +
  +Templates are versioned via inline comments. Update the revision note
  +when changing wording to maintain an audit trail for prompt evolution.
  +"""
  +
  +from __future__ import annotations
  +
  +# ---------------------------------------------------------------------------
  +# Alarm summary — Slice A
  +# Revision: 2026-05-01 v1 (initial)
  +# ---------------------------------------------------------------------------
  +
  +ALARM_SUMMARY_SYSTEM = """\
  +Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
  +краткий, точный summary сработавшего аларма для оператора в Telegram.
  +
  +Принципы:
  +- Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
  +- Не выдумывай контекст. Используй только данные из запроса ниже.
  +- Конкретные значения, не размытые описания.
  +- Если возможна причина — предложи. Если неясно — напиши "причина неясна".
  +- НИКОГДА не предлагай safety-действия автоматически (аварийное отключение, \
  +переключение фаз). Только наблюдения и предложения для оператора.
  +- 80-150 слов. Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
  +"""
  +
  +ALARM_SUMMARY_USER = """\
  +АЛАРМ СРАБОТАЛ:
  +- ID: {alarm_id}
  +- Уровень: {level}
  +- Каналы: {channels}
  +- Значения: {values}
  +
  +ТЕКУЩЕЕ СОСТОЯНИЕ:
  +- Фаза: {phase}
  +- Эксперимент: {experiment_id} (запущен {experiment_age})
  +- Целевая температура: {target_temp}
  +- Активные блокировки: {interlocks}
  +
  +ПОСЛЕДНИЕ ПОКАЗАНИЯ (последние {lookback_s}с) на затронутых каналах:
  +{recent_readings}
  +
  +ПОСЛЕДНИЕ АЛАРМЫ (последний час):
  +{recent_alarms}
  +
  +Сформируй краткий summary для оператора в Telegram. Только русский язык.
  +"""
  +
  +# ---------------------------------------------------------------------------
  +# Experiment finalize summary — Slice A
  +# Revision: 2026-05-01 v1 (initial)
  +# ---------------------------------------------------------------------------
  +
  +EXPERIMENT_FINALIZE_SYSTEM = """\
  +Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
  +краткое резюме завершённого эксперимента для оператора.
  +
  +Принципы:
  +- Отвечай ТОЛЬКО на русском языке.
  +- Используй только данные из запроса.
  +- Конкретные факты: продолжительность, фазы, ключевые события.
  +- 80-120 слов. Telegram-friendly Markdown.
  +"""
  +
  +EXPERIMENT_FINALIZE_USER = """\
  +ЭКСПЕРИМЕНТ ЗАВЕРШЁН:
  +- ID: {experiment_id}
  +- Название: {name}
  +- Продолжительность: {duration}
  +- Финальный статус: {status}
  +
  +ФАЗЫ:
  +{phases}
  +
  +АЛАРМЫ ЗА ЭКСПЕРИМЕНТ:
  +{alarms_summary}
  +
  +Сформируй краткое резюме завершённого эксперимента. Только русский язык.
  +"""
  +
  +# ---------------------------------------------------------------------------
  +# Campaign report intro — Slice C
  +# Revision: 2026-05-01 v1 (initial)
  +# ---------------------------------------------------------------------------
  +
  +CAMPAIGN_REPORT_INTRO_SYSTEM = """\
  +Ты — {brand_name}, научный ассистент в криогенной лаборатории. Твоя задача — \
  +написать аннотацию к научному отчёту об эксперименте.
  +
  +Принципы:
  +- Отвечай ТОЛЬКО на русском языке.
  +- Формальный научный стиль, не разговорный. Без жаргона.
  +- Структура: Цель эксперимента → Условия проведения → Основные наблюдения → Заключение.
  +- Переходы между разделами — связными предложениями, без подзаголовков и нумерации.
  +- Используй только данные из запроса. Не выдумывай значения.
  +- Если данных для раздела недостаточно — опусти раздел, не выдумывай.
  ... (192 lines truncated)
  +292 -0

src/cryodaq/engine.py
  @@ -29,6 +29,11 @@ from typing import Any
  +from cryodaq.agents.assistant.shared.audit import AuditLogger
  +from cryodaq.agents.assistant.live.context_builder import ContextBuilder
  +from cryodaq.agents.assistant.live.agent import AssistantLiveAgent, AssistantConfig
  +from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
  +from cryodaq.agents.assistant.live.output_router import OutputRouter
   from cryodaq.analytics.calibration import CalibrationStore
   from cryodaq.analytics.leak_rate import LeakRateEstimator
   from cryodaq.analytics.plugin_loader import PluginPipeline
  @@ -45,6 +50,7 @@ from cryodaq.core.calibration_acquisition import (
  +from cryodaq.core.event_bus import EngineEvent, EventBus
   from cryodaq.core.event_logger import EventLogger
   from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
   from cryodaq.core.housekeeping import (
  @@ -89,6 +95,42 @@ _LOG_GET_TIMEOUT_S = 1.5
  +async def _periodic_report_tick(
  +    agent_config: AssistantConfig,
  +    event_bus: EventBus,
  +    experiment_manager: ExperimentManager,
  +    *,
  +    sleep=asyncio.sleep,
  +) -> None:
  +    """Publish periodic_report_request events on the assistant schedule."""
  +    interval_s = float(agent_config.get_periodic_report_interval_s())
  +    if interval_s <= 0:
  +        logger.info("Periodic assistant reports disabled (interval=0)")
  +        return
  +
  +    window_minutes = int(agent_config.periodic_report_interval_minutes)
  +    while True:
  +        await sleep(interval_s)

... (more changes truncated)
  +22 -0
[full diff: rtk git diff --no-compact]
```
