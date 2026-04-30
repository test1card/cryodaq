Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/vladimir/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019de020-8bc1-7682-bb9c-d6ac2f8c64b7
--------
user
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
codex
I’ll do this as a code-review pass against the actual branch, not just the pasted diff. First I’m loading the required review workflow, then I’ll pin the exact changed lines so any findings are grounded.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/886026e9/skills/using-superpowers/SKILL.md && sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/886026e9/skills/requesting-code-review/SKILL.md" in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
sed: /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/886026e9/skills/using-superpowers/SKILL.md: No such file or directory

codex
That listed skill path is stale on disk, so I’m falling back to the code-review behavior already specified here and continuing with direct repository inspection.
exec
/opt/homebrew/bin/bash -lc 'rg -n "periodic_report|PERIODIC_REPORT|prefix_suffix|total_event_count|latex|Markdown|assistant_insight" src/cryodaq config tests artifacts/scripts pyproject.toml CHANGELOG.md ROADMAP.md' in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
rg: artifacts/scripts: No such file or directory (os error 2)
ROADMAP.md:327:- Export handover → Markdown / PDF / Telegram
config/notifications.local.yaml.example:17:periodic_report:
tests/gui/test_shift_handover.py:152:    the compiled Markdown body is embedded in the ``message`` field — the
tests/gui/test_shift_handover.py:154:    by the full Markdown summary."""
tests/gui/test_shift_handover.py:187:    # Body is the full Markdown summary.
tests/gui/test_shift_handover.py:245:    """Events reply with phase/experiment tags renders as Markdown list."""
tests/gui/test_shift_handover.py:289:    """min / max / delta rendered as a 4-column Markdown table."""
tests/gui/test_shift_handover.py:328:    """Markdown export glues sections + metadata in a stable layout."""
tests/gui/test_shift_handover.py:354:    """_on_end embeds the compiled Markdown in the log entry's ``message``
tests/gui/test_shift_handover.py:381:    # Markdown body is appended after the header line.
config/notifications.yaml:11:periodic_report:
tests/notifications/test_secret_str.py:69:def test_periodic_report_no_plain_url_attribute():
tests/notifications/test_secret_str.py:71:    from cryodaq.notifications import periodic_report
tests/notifications/test_secret_str.py:73:    src = inspect.getsource(periodic_report)
tests/gui/test_overview_contract.py:139:    """IV.4 F11: shift_end log entries embed a full Markdown body in the
tests/gui/test_overview_contract.py:141:    first line so it doesn't dump the Markdown summary into its label."""
tests/gui/test_overview_contract.py:162:    # Markdown body must not leak into the compact widget.
src/cryodaq/notifications/periodic_report.py:8:    periodic_report:
src/cryodaq/notifications/periodic_report.py:32:logger = logging.getLogger("cryodaq.notifications.periodic_report")
src/cryodaq/notifications/periodic_report.py:35:_SUBSCRIPTION_NAME = "periodic_reporter"
src/cryodaq/notifications/periodic_report.py:116:            self._collect_loop(), name="periodic_reporter_collect"
src/cryodaq/notifications/periodic_report.py:119:            self._report_loop(), name="periodic_reporter_report"
src/cryodaq/gui/widgets/shift_handover.py:376:    """Render the events section of the shift handover as Markdown lines.
src/cryodaq/gui/widgets/shift_handover.py:438:    """Render min/max/delta per temperature channel as a Markdown table.
src/cryodaq/gui/widgets/shift_handover.py:522:    """Assemble the full Markdown body used by clipboard export + log save."""
src/cryodaq/gui/widgets/shift_handover.py:562:    «Скопировать в Markdown» button ships the full summary to the
src/cryodaq/gui/widgets/shift_handover.py:564:    log under tag ``shift_end`` with the Markdown body embedded in
src/cryodaq/gui/widgets/shift_handover.py:650:            "Скопировать в Markdown",
src/cryodaq/gui/widgets/shift_handover.py:785:    # Markdown export + save
src/cryodaq/gui/widgets/shift_handover.py:817:        # compiled Markdown summary is stored as the message body itself.
src/cryodaq/gui/widgets/shift_handover.py:818:        # Format: one-line header + blank line + full Markdown so
src/cryodaq/engine.py:69:from cryodaq.notifications.periodic_report import PeriodicReporter
src/cryodaq/engine.py:1741:    periodic_reporter: PeriodicReporter | None = None
src/cryodaq/engine.py:1755:            pr_cfg = notif_raw.get("periodic_report", {})
src/cryodaq/engine.py:1757:                periodic_reporter = PeriodicReporter(
src/cryodaq/engine.py:1829:    if periodic_reporter is not None:
src/cryodaq/engine.py:1830:        await periodic_reporter.start()
src/cryodaq/engine.py:1958:    if periodic_reporter is not None:
src/cryodaq/engine.py:1959:        await periodic_reporter.stop()

exec
/opt/homebrew/bin/bash -lc 'pwd && git status --short && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
/Users/vladimir/Projects/cryodaq
 M docs/ORCHESTRATION.md
?? CC_PROMPT_CALIBRATION_2026-04-30.md
?? CC_PROMPT_DOCS_AUDIT_REWRITE_2026-04-30.md
?? CC_PROMPT_DOCS_REWRITE_PHASE2_2026-04-30.md
?? CC_PROMPT_F28_CYCLE0_MULTI_AUDIT_2026-05-01.md
?? CC_PROMPT_F28_CYCLE6_2026-05-XX.md
?? CC_PROMPT_F28_HERMES_AGENT.md
?? CC_PROMPT_F29_PERIODIC_REPORTS.md
?? CC_PROMPT_F29_SWARM_AUDIT_2026-05-01.md
?? CC_PROMPT_METASWARM_F17.md
?? CC_PROMPT_OVERNIGHT_2026-04-30.md
?? CC_PROMPT_OVERNIGHT_2026-05-01.md
?? CC_PROMPT_PARALLEL_WORK_2026-05-01.md
?? CC_PROMPT_REPO_CLEANUP_2026-04-30.md
?? artifacts/architecture/
?? artifacts/calibration/2026-05-01-f29-swarm/
?? artifacts/consultations/2026-04-29-f10-cycle1/
?? artifacts/consultations/2026-04-29-f10-cycle2/
?? artifacts/consultations/2026-04-29-f10-cycle3/
?? artifacts/consultations/2026-04-29-f3-cycle1/
?? artifacts/consultations/2026-04-29-f3-cycle2/
?? artifacts/consultations/2026-04-29-f3-cycle3/
?? artifacts/consultations/2026-04-29-metaswarm/
?? artifacts/consultations/2026-04-30/
?? artifacts/consultations/2026-05-01-overnight-f17/
?? artifacts/consultations/2026-05-01-overnight-f26/
?? artifacts/handoffs/2026-04-29-f10-cycle1-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle2-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle3-handoff.md
?? artifacts/handoffs/2026-04-29-f28-cycle0-handoff.md
?? artifacts/handoffs/2026-04-29-hf1-hf2-review.md
?? artifacts/handoffs/2026-04-29-metaswarm-summary.md
?? artifacts/handoffs/2026-04-29-overnight-summary.md
?? artifacts/handoffs/2026-04-29-task-a-verification.md
?? artifacts/handoffs/2026-05-01-cooldown-predictor-readthrough.md
?? artifacts/handoffs/2026-05-01-f26-handoff.md
?? draft.py
?? draft2.py
?? release_notes.py
master
863ddc17249c9cd1008f07a54a0f92a27a9db74b

exec
/opt/homebrew/bin/bash -lc 'git diff --stat master..feat/f29-periodic-reports && git diff --unified=80 master..feat/f29-periodic-reports -- src/cryodaq/engine.py src/cryodaq/agents/assistant/live/agent.py src/cryodaq/agents/assistant/live/context_builder.py src/cryodaq/agents/assistant/live/prompts.py src/cryodaq/agents/assistant/live/output_router.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
 CHANGELOG.md                                       |  124 +
 README.md                                          |   67 +-
 ROADMAP.md                                         |   91 +-
 .../calibration/2026-04-30/CALIBRATION-MATRIX.md   |  121 +
 artifacts/calibration/2026-04-30/MASTER-SUMMARY.md |  202 +
 .../T1-bug-hypothesis/chimera.response.md          |   33 +
 .../T1-bug-hypothesis/chimera.response.md.status   |    1 +
 .../2026-04-30/T1-bug-hypothesis/chutes.prompt.txt |   76 +
 .../2026-04-30/T1-bug-hypothesis/codex.prompt.md   |   23 +
 .../2026-04-30/T1-bug-hypothesis/codex.response.md | 1370 +++++++
 .../2026-04-30/T1-bug-hypothesis/gemini.prompt.md  |   23 +
 .../T1-bug-hypothesis/gemini.response.md           |  129 +
 .../2026-04-30/T1-bug-hypothesis/glm.response.md   |    1 +
 .../T1-bug-hypothesis/glm.response.md.status       |    1 +
 .../2026-04-30/T1-bug-hypothesis/kimi.response.md  |    1 +
 .../T1-bug-hypothesis/kimi.response.md.status      |    1 +
 .../T1-bug-hypothesis/minimax.response.md          |  224 ++
 .../T1-bug-hypothesis/minimax.response.md.status   |    1 +
 .../T1-bug-hypothesis/minimax.response.raw         |    1 +
 .../2026-04-30/T1-bug-hypothesis/qwen3.response.md |  210 +
 .../T1-bug-hypothesis/qwen3.response.md.status     |    1 +
 .../2026-04-30/T1-bug-hypothesis/r1.response.md    |   39 +
 .../T1-bug-hypothesis/r1.response.md.status        |    1 +
 .../2026-04-30/T1-bug-hypothesis/scoring.md        |   43 +
 .../2026-04-30/T1-bug-hypothesis/wave.log          |   19 +
 .../T2-narrow-review/chimera.response.md           |    1 +
 .../T2-narrow-review/chimera.response.md.status    |    1 +
 .../2026-04-30/T2-narrow-review/chutes.prompt.txt  |   65 +
 .../2026-04-30/T2-narrow-review/codex.prompt.md    |   65 +
 .../2026-04-30/T2-narrow-review/codex.response.md  | 1693 ++++++++
 .../2026-04-30/T2-narrow-review/gemini.prompt.md   |   65 +
 .../2026-04-30/T2-narrow-review/gemini.response.md |  927 +++++
 .../2026-04-30/T2-narrow-review/glm.response.md    |    9 +
 .../T2-narrow-review/glm.response.md.status        |    1 +
 .../2026-04-30/T2-narrow-review/kimi.response.md   |   10 +
 .../T2-narrow-review/kimi.response.md.status       |    1 +
 .../T2-narrow-review/minimax.response.md           |   20 +
 .../T2-narrow-review/minimax.response.md.status    |    1 +
 .../2026-04-30/T2-narrow-review/qwen3.response.md  |    1 +
 .../T2-narrow-review/qwen3.response.md.status      |    1 +
 .../2026-04-30/T2-narrow-review/r1.response.md     |    1 +
 .../T2-narrow-review/r1.response.md.status         |    1 +
 .../2026-04-30/T2-narrow-review/wave.log           |   18 +
 .../2026-04-30/T3-arch-drift/chimera.response.md   |    1 +
 .../T3-arch-drift/chimera.response.md.status       |    1 +
 .../2026-04-30/T3-arch-drift/chutes.prompt.txt     |  104 +
 .../2026-04-30/T3-arch-drift/codex.prompt.md       |   15 +
 .../2026-04-30/T3-arch-drift/codex.response.md     |  386 ++
 .../2026-04-30/T3-arch-drift/gemini.prompt.md      |   15 +
 .../2026-04-30/T3-arch-drift/gemini.response.md    |  120 +
 .../2026-04-30/T3-arch-drift/glm.response.md       |    3 +
 .../T3-arch-drift/glm.response.md.status           |    1 +
 .../2026-04-30/T3-arch-drift/kimi.response.md      |    5 +
 .../T3-arch-drift/kimi.response.md.status          |    1 +
 .../2026-04-30/T3-arch-drift/minimax.response.md   |    3 +
 .../T3-arch-drift/minimax.response.md.status       |    1 +
 .../2026-04-30/T3-arch-drift/qwen3.response.md     |   12 +
 .../T3-arch-drift/qwen3.response.md.status         |    1 +
 .../2026-04-30/T3-arch-drift/r1.response.md        |    1 +
 .../2026-04-30/T3-arch-drift/r1.response.md.status |    1 +
 .../2026-04-30/T3-arch-drift/scoring.md            |   49 +
 .../calibration/2026-04-30/T3-arch-drift/wave.log  |   15 +
 .../2026-04-30/T4-spec-design/chimera.response.md  |    1 +
 .../T4-spec-design/chimera.response.md.status      |    1 +
 .../2026-04-30/T4-spec-design/chutes.prompt.txt    |   56 +
 .../2026-04-30/T4-spec-design/codex.prompt.md      |   56 +
 .../2026-04-30/T4-spec-design/codex.response.md    | 1043 +++++
 .../2026-04-30/T4-spec-design/gemini.prompt.md     |   56 +
 .../2026-04-30/T4-spec-design/gemini.response.md   |  656 ++++
 .../2026-04-30/T4-spec-design/glm.response.md      |  173 +
 .../T4-spec-design/glm.response.md.status          |    1 +
 .../2026-04-30/T4-spec-design/kimi.response.md     |  129 +
 .../T4-spec-design/kimi.response.md.status         |    1 +
 .../2026-04-30/T4-spec-design/minimax.response.md  |  272 ++
 .../T4-spec-design/minimax.response.md.status      |    1 +
 .../2026-04-30/T4-spec-design/qwen3.response.md    |  191 +
 .../T4-spec-design/qwen3.response.md.status        |    1 +
 .../2026-04-30/T4-spec-design/r1.response.md       |  133 +
 .../T4-spec-design/r1.response.md.status           |    1 +
 .../2026-04-30/T4-spec-design/scoring.md           |   35 +
 .../calibration/2026-04-30/T4-spec-design/wave.log |   16 +
 .../2026-04-30/T5-code-gen/chimera.response.md     |    1 +
 .../T5-code-gen/chimera.response.md.status         |    1 +
 .../2026-04-30/T5-code-gen/chutes.prompt.txt       |   75 +
 .../2026-04-30/T5-code-gen/codex.prompt.md         |   75 +
 .../2026-04-30/T5-code-gen/codex.response.md       |  589 +++
 .../2026-04-30/T5-code-gen/gemini.prompt.md        |   75 +
 .../2026-04-30/T5-code-gen/gemini.response.md      |   67 +
 .../2026-04-30/T5-code-gen/glm.response.md         |  161 +
 .../2026-04-30/T5-code-gen/glm.response.md.status  |    1 +
 .../2026-04-30/T5-code-gen/kimi.response.md        |    1 +
 .../2026-04-30/T5-code-gen/kimi.response.md.status |    1 +
 .../2026-04-30/T5-code-gen/minimax.response.md     |   91 +
 .../T5-code-gen/minimax.response.md.status         |    1 +
 .../2026-04-30/T5-code-gen/qwen3.response.md       |  107 +
 .../T5-code-gen/qwen3.response.md.status           |    1 +
 .../2026-04-30/T5-code-gen/r1.response.md          |    1 +
 .../2026-04-30/T5-code-gen/r1.response.md.status   |    1 +
 .../calibration/2026-04-30/T5-code-gen/scoring.md  |   30 +
 .../calibration/2026-04-30/T5-code-gen/wave.log    |   18 +
 .../2026-04-30/T6-long-digest/chimera.response.md  |   35 +
 .../T6-long-digest/chimera.response.md.status      |    1 +
 .../2026-04-30/T6-long-digest/chutes.prompt.txt    | 1954 ++++++++++
 .../2026-04-30/T6-long-digest/codex.prompt.md      |   12 +
 .../2026-04-30/T6-long-digest/codex.response.md    | 2176 +++++++++++
 .../2026-04-30/T6-long-digest/gemini.prompt.md     |   12 +
 .../2026-04-30/T6-long-digest/gemini.response.md   |   11 +
 .../2026-04-30/T6-long-digest/glm.response.md      |   13 +
 .../T6-long-digest/glm.response.md.status          |    1 +
 .../2026-04-30/T6-long-digest/kimi.response.md     |    1 +
 .../T6-long-digest/kimi.response.md.status         |    1 +
 .../2026-04-30/T6-long-digest/minimax.response.md  |   35 +
 .../T6-long-digest/minimax.response.md.status      |    1 +
 .../2026-04-30/T6-long-digest/qwen3.response.md    |   13 +
 .../T6-long-digest/qwen3.response.md.status        |    1 +
 .../2026-04-30/T6-long-digest/r1.response.md       |   18 +
 .../T6-long-digest/r1.response.md.status           |    1 +
 .../2026-04-30/T6-long-digest/scoring.md           |   33 +
 .../calibration/2026-04-30/T6-long-digest/wave.log |   19 +
 .../T7-math-derivation/chimera.response.md         |  126 +
 .../T7-math-derivation/chimera.response.md.status  |    1 +
 .../T7-math-derivation/chutes.prompt.txt           |   28 +
 .../2026-04-30/T7-math-derivation/codex.prompt.md  |   28 +
 .../T7-math-derivation/codex.response.md           |  530 +++
 .../2026-04-30/T7-math-derivation/gemini.prompt.md |   28 +
 .../T7-math-derivation/gemini.response.md          |   90 +
 .../2026-04-30/T7-math-derivation/glm.response.md  |  105 +
 .../T7-math-derivation/glm.response.md.status      |    1 +
 .../2026-04-30/T7-math-derivation/kimi.response.md |    1 +
 .../T7-math-derivation/kimi.response.md.status     |    1 +
 .../T7-math-derivation/minimax.response.md         |  281 ++
 .../T7-math-derivation/minimax.response.md.status  |    1 +
 .../T7-math-derivation/qwen3.response.md           |  395 ++
 .../T7-math-derivation/qwen3.response.md.status    |    1 +
 .../2026-04-30/T7-math-derivation/r1.response.md   |   97 +
 .../T7-math-derivation/r1.response.md.status       |    1 +
 .../2026-04-30/T7-math-derivation/scoring.md       |   39 +
 .../2026-04-30/T7-math-derivation/wave.log         |   16 +
 .../calibration/2026-04-30/architect-spot-check.md |  120 +
 .../2026-05-01-f28-cycle0/GLM-5.1.latency.txt      |    1 +
 .../2026-05-01-f28-cycle0/GLM-5.1.raw.json         |    1 +
 .../2026-05-01-f28-cycle0/GLM-5.1.response.md      |   75 +
 .../2026-05-01-f28-cycle0/Kimi-K2.6.latency.txt    |    1 +
 .../2026-05-01-f28-cycle0/Kimi-K2.6.raw.json       |    1 +
 .../2026-05-01-f28-cycle0/Kimi-K2.6.response.md    |    1 +
 .../2026-05-01-f28-cycle0/MiniMax-M2.5.latency.txt |    1 +
 .../2026-05-01-f28-cycle0/MiniMax-M2.5.raw.json    |    1 +
 .../2026-05-01-f28-cycle0/MiniMax-M2.5.response.md |  169 +
 .../Qwen3-Coder-Next.latency.txt                   |    1 +
 .../Qwen3-Coder-Next.raw.json                      |    1 +
 .../Qwen3-Coder-Next.response.md                   |  123 +
 .../2026-05-01-f28-cycle0/audit-prompt.md          |  371 ++
 .../2026-05-01-f28-cycle0/gemini.latency.txt       |    1 +
 .../2026-05-01-f28-cycle0/gemini.response.md       | 1057 +++++
 .../2026-05-01-f28-cycle0/verification-ledger.md   |  189 +
 .../2026-05-01-f28-cycle1/GLM-5.1.latency.txt      |    1 +
 .../2026-05-01-f28-cycle1/GLM-5.1.raw.json         |    1 +
 .../2026-05-01-f28-cycle1/GLM-5.1.response.md      |    1 +
 .../2026-05-01-f28-cycle1/audit-prompt.md          |  481 +++
 .../2026-05-01-f28-cycle1/codex.latency.txt        |    1 +
 .../2026-05-01-f28-cycle1/codex.response.md        | 1355 +++++++
 .../2026-05-01-f28-cycle2/GLM-5.1.latency.txt      |    1 +
 .../2026-05-01-f28-cycle2/GLM-5.1.raw.json         |    1 +
 .../2026-05-01-f28-cycle2/GLM-5.1.response.md      |  116 +
 .../2026-05-01-f28-cycle2/MiniMax-M2.5.latency.txt |    1 +
 .../2026-05-01-f28-cycle2/MiniMax-M2.5.raw.json    |    1 +
 .../2026-05-01-f28-cycle2/MiniMax-M2.5.response.md |   47 +
 .../2026-05-01-f28-cycle2/codex.latency.txt        |    1 +
 .../2026-05-01-f28-cycle2/codex.response.md        | 4027 ++++++++++++++++++++
 .../2026-05-01-f28-cycle2/full-prompt.md           |  570 +++
 .../2026-05-01-f28-cycle2/gemini.latency.txt       |    1 +
 .../2026-05-01-f28-cycle2/gemini.response.md       | 1057 +++++
 .../2026-05-01-f28-cycle2/glm-prompt.md            |  542 +++
 artifacts/calibration/README.md                    |   42 +
 artifacts/calibration/log.jsonl                    |   77 +
 .../2026-04-30/f29-cycle1-audit/codex.response.md  |   38 +
 .../2026-04-30/f29-cycle1-audit/glm.prompt.md      |   36 +
 .../2026-04-30/f29-cycle1-audit/glm.response.md    |   22 +
 .../2026-04-30/f29-cycle1-audit/synthesis.md       |   41 +
 .../handoffs/2026-04-29-f28-cycle2-handoff.md      |  105 +
 artifacts/handoffs/2026-04-30-f29-cycle1-smoke.md  |   92 +
 .../handoffs/2026-05-01-f28-cycle3-handoff.md      |   93 +
 artifacts/handoffs/2026-05-01-f28-cycle3-smoke.md  |  269 ++
 artifacts/handoffs/2026-05-01-f28-cycle4-smoke.md  |  103 +
 artifacts/handoffs/2026-05-01-f28-cycle5-smoke.md  |  122 +
 artifacts/handoffs/2026-05-01-f28-cycle6-smoke.md  |   83 +
 .../handoffs/2026-05-01-f28-cycle6-summary.md      |   72 +
 artifacts/scripts/smoke_f29_periodic_report.py     |  212 ++
 artifacts/scripts/smoke_gemma.py                   |  199 +
 artifacts/scripts/smoke_gemma_cycle3.py            |  324 ++
 config/agent.yaml                                  |   49 +
 docs/operator_manual.md                            |   30 +-
 pyproject.toml                                     |    6 +-
 src/cryodaq/agents/__init__.py                     |    0
 src/cryodaq/agents/assistant/__init__.py           |    0
 src/cryodaq/agents/assistant/live/__init__.py      |    0
 src/cryodaq/agents/assistant/live/agent.py         |  801 ++++
 .../agents/assistant/live/context_builder.py       |  547 +++
 src/cryodaq/agents/assistant/live/output_router.py |  109 +
 src/cryodaq/agents/assistant/live/prompts.py       |  292 ++
 src/cryodaq/agents/assistant/shared/__init__.py    |    0
 src/cryodaq/agents/assistant/shared/audit.py       |   95 +
 .../agents/assistant/shared/ollama_client.py       |  149 +
 .../agents/assistant/shared/report_intro.py        |  277 ++
 src/cryodaq/agents/assistant/shared/retention.py   |   45 +
 src/cryodaq/core/event_bus.py                      |   62 +
 src/cryodaq/core/event_logger.py                   |   35 +-
 src/cryodaq/engine.py                              |  189 +-
 .../gui/shell/views/assistant_insight_panel.py     |  246 ++
 src/cryodaq/reporting/generator.py                 |   44 +-
 tests/agents/__init__.py                           |    0
 tests/agents/assistant/__init__.py                 |    0
 tests/agents/assistant/test_alarm_flow.py          |  599 +++
 tests/agents/assistant/test_brand_abstraction.py   |  142 +
 tests/agents/assistant/test_diagnostic.py          |  272 ++
 .../assistant/test_engine_periodic_report_tick.py  |  107 +
 tests/agents/assistant/test_ollama_client.py       |  285 ++
 .../assistant/test_periodic_report_config.py       |   59 +
 .../assistant/test_periodic_report_context.py      |  121 +
 .../assistant/test_periodic_report_handler.py      |  230 ++
 tests/agents/assistant/test_report_intro.py        |  211 +
 tests/agents/assistant/test_retention.py           |   58 +
 tests/core/test_event_bus.py                       |  195 +
 .../shell/views/test_assistant_insight_panel.py    |  177 +
 224 files changed, 34303 insertions(+), 25 deletions(-)
diff --git a/src/cryodaq/agents/assistant/live/agent.py b/src/cryodaq/agents/assistant/live/agent.py
new file mode 100644
index 0000000..88d5cde
--- /dev/null
+++ b/src/cryodaq/agents/assistant/live/agent.py
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
+        _num_ctx = ollama.get("num_ctx")
+        cfg.num_ctx = int(_num_ctx) if _num_ctx is not None else None
+        rl = d.get("rate_limit", {})
+        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
+        cfg.max_concurrent_inferences = int(
+            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
+        )
+        triggers = d.get("triggers", {})
+        alarm_t = triggers.get("alarm_fired", {})
+        if isinstance(alarm_t, dict):
+            cfg.alarm_fired_enabled = bool(alarm_t.get("enabled", cfg.alarm_fired_enabled))
+            raw_level = str(alarm_t.get("min_level", cfg.alarm_min_level)).upper()
+            if raw_level not in _MIN_LEVELS:
+                raise ValueError(
+                    f"alarm_min_level must be one of {list(_MIN_LEVELS)}, got {raw_level!r}"
+                )
+            cfg.alarm_min_level = raw_level
+        exp_t = triggers.get("experiment_finalize", {})
+        if isinstance(exp_t, dict):
+            cfg.experiment_finalize_enabled = bool(
+                exp_t.get("enabled", cfg.experiment_finalize_enabled)
+            )
+        sa_t = triggers.get("sensor_anomaly_critical", {})
+        if isinstance(sa_t, dict):
+            cfg.sensor_anomaly_critical_enabled = bool(
+                sa_t.get("enabled", cfg.sensor_anomaly_critical_enabled)
+            )
+        sh_t = triggers.get("shift_handover_request", {})
+        if isinstance(sh_t, dict):
+            cfg.shift_handover_request_enabled = bool(
+                sh_t.get("enabled", cfg.shift_handover_request_enabled)
+            )
+        pr_t = triggers.get("periodic_report", {})
+        if isinstance(pr_t, dict):
+            cfg.periodic_report_enabled = bool(pr_t.get("enabled", cfg.periodic_report_enabled))
+            cfg.periodic_report_interval_minutes = int(
+                pr_t.get("interval_minutes", cfg.periodic_report_interval_minutes)
+            )
+            cfg.periodic_report_skip_if_idle = bool(
+                pr_t.get("skip_if_idle", cfg.periodic_report_skip_if_idle)
+            )
+            cfg.periodic_report_min_events = int(
+                pr_t.get("min_events_for_dispatch", cfg.periodic_report_min_events)
+            )
+        outputs = d.get("outputs", {})
+        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
+        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
+        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
+        slices = d.get("slices", {})
+        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
+        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
+        cfg.slice_c_campaign_report = bool(
+            slices.get("c_campaign_report", cfg.slice_c_campaign_report)
+        )
+        audit = d.get("audit", {})
+        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
+        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
+        cfg.brand_name = str(d.get("brand_name", cfg.brand_name))
+        cfg.brand_emoji = str(d.get("brand_emoji", cfg.brand_emoji))
+        return cfg
+
+    @classmethod
+    def from_yaml_string(cls, content: str) -> AssistantConfig:
+        """Load from YAML string; handles agent.* and legacy gemma.* namespaces."""
+        import yaml  # noqa: PLC0415
+        raw = yaml.safe_load(content) or {}
+        return cls._from_raw(raw)
+
+    @classmethod
+    def from_yaml_path(cls, path: Path) -> AssistantConfig:
+        """Load from agent.yaml file; handles agent.* and legacy gemma.* namespaces."""
+        import yaml  # noqa: PLC0415
+        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
+        return cls._from_raw(raw)
+
+    @classmethod
+    def _from_raw(cls, raw: dict) -> AssistantConfig:
+        if "agent" in raw:
+            return cls.from_dict(raw["agent"])
+        if "gemma" in raw:
+            logger.warning(
+                "AssistantConfig: legacy gemma.* config namespace detected; "
+                "please migrate to agent.*. Backward compatibility removed in v0.46.0."
+            )
+            return cls.from_dict(raw["gemma"])
+        return cls()
+
+
+class AssistantLiveAgent:
+    """Local LLM agent. Operator-facing brand: Гемма."""
+
+    def __init__(
+        self,
+        *,
+        config: AssistantConfig,
+        event_bus: EventBus,
+        ollama_client: OllamaClient,
+        context_builder: ContextBuilder,
+        audit_logger: AuditLogger,
+        output_router: OutputRouter,
+    ) -> None:
+        self._config = config
+        self._bus = event_bus
+        self._ollama = ollama_client
+        self._ctx_builder = context_builder
+        self._audit = audit_logger
+        self._router = output_router
+
+        self._semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
+        self._call_timestamps: deque[float] = deque()
+        self._handler_tasks: set[asyncio.Task] = set()
+        self._task: asyncio.Task[None] | None = None
+        self._queue: asyncio.Queue[EngineEvent] | None = None
+
+    async def start(self) -> None:
+        """Subscribe to EventBus and begin event processing."""
+        if not self._config.enabled:
+            logger.info("AssistantLiveAgent (Гемма): отключён в конфигурации")
+            return
+        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
+        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
+        logger.info(
+            "AssistantLiveAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
+            self._config.default_model,
+            self._config.timeout_s,
+        )
+
+    async def stop(self) -> None:
+        """Cancel the event loop and in-flight handlers, release resources."""
+        if self._task is not None:
+            self._task.cancel()
+            try:
+                await self._task
+            except asyncio.CancelledError:
+                pass
+            self._task = None
+        # Cancel in-flight inference tasks to avoid racing with shutdown
+        for t in list(self._handler_tasks):
+            t.cancel()
+        for t in list(self._handler_tasks):
+            try:
+                await t
+            except asyncio.CancelledError:
+                pass
+        if self._queue is not None:
+            self._bus.unsubscribe("gemma_agent")
+            self._queue = None
+        await self._ollama.close()
+        logger.info("AssistantLiveAgent (Гемма): остановлен")
+
+    async def _event_loop(self) -> None:
+        """Drain the EventBus queue and dispatch handlers."""
+        assert self._queue is not None
+        while True:
+            try:
+                event = await self._queue.get()
+                if self._should_handle(event):
+                    t = asyncio.create_task(
+                        self._safe_handle(event),
+                        name=f"gemma_{event.event_type}",
+                    )
+                    self._handler_tasks.add(t)
+                    t.add_done_callback(self._handler_tasks.discard)
+            except asyncio.CancelledError:
+                return
+            except Exception:
+                logger.warning("AssistantLiveAgent: event loop error", exc_info=True)
+
+    def _should_handle(self, event: EngineEvent) -> bool:
+        if not self._config.slice_a_notification:
+            return False
+        if event.event_type == "alarm_fired":
+            if not self._config.alarm_fired_enabled:
+                return False
+            level = event.payload.get("level", "INFO")
+            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
+                self._config.alarm_min_level, 1
+            )
+        if event.event_type in {"experiment_finalize", "experiment_stop", "experiment_abort"}:
+            return self._config.experiment_finalize_enabled
+        if event.event_type == "sensor_anomaly_critical":
+            return self._config.sensor_anomaly_critical_enabled
+        if event.event_type == "shift_handover_request":
+            return self._config.shift_handover_request_enabled
+        if event.event_type == "periodic_report_request":
+            return self._config.periodic_report_enabled
+        return False
+
+    def _check_rate_limit(self) -> bool:
+        """True if we can make a call now (hourly bucket)."""
+        now = time.monotonic()
+        cutoff = now - 3600.0
+        while self._call_timestamps and self._call_timestamps[0] < cutoff:
+            self._call_timestamps.popleft()
+        return len(self._call_timestamps) < self._config.max_calls_per_hour
+
+    async def _safe_handle(self, event: EngineEvent) -> None:
+        """Handle one event with rate-limit + semaphore + error isolation."""
+        if not self._check_rate_limit():
+            logger.warning(
+                "AssistantLiveAgent: rate limit reached (%d/hr), dropping %s",
+                self._config.max_calls_per_hour,
+                event.event_type,
+            )
+            return
+
+        async with self._semaphore:
+            self._call_timestamps.append(time.monotonic())
+            try:
+                if event.event_type in {
+                    "experiment_finalize",
+                    "experiment_stop",
+                    "experiment_abort",
+                }:
+                    await self._handle_experiment_finalize(event)
+                elif event.event_type == "sensor_anomaly_critical":
+                    await self._handle_sensor_anomaly(event)
+                elif event.event_type == "shift_handover_request":
+                    await self._handle_shift_handover(event)
+                elif event.event_type == "periodic_report_request":
+                    await self._handle_periodic_report(event)
+                else:
+                    await self._handle_alarm_fired(event)
+            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
+                logger.warning("AssistantLiveAgent: Ollama недоступен — %s", exc)
+            except Exception:
+                logger.warning(
+                    "AssistantLiveAgent: ошибка обработки %s", event.event_type, exc_info=True
+                )
+
+    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        payload = event.payload
+
+        ctx = await self._ctx_builder.build_alarm_context(payload)
+        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
+        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
+        age_str = _format_age(ctx.experiment_age_s)
+
+        user_prompt = ALARM_SUMMARY_USER.format(
+            alarm_id=ctx.alarm_id,
+            level=ctx.level,
+            channels=channels_str,
+            values=values_str,
+            phase=ctx.phase or "—",
+            experiment_id=ctx.experiment_id or "—",
+            experiment_age=age_str,
+            target_temp=ctx.target_temp if ctx.target_temp is not None else "—",
+            interlocks=", ".join(ctx.active_interlocks) if ctx.active_interlocks else "нет",
+            lookback_s=60,
+            recent_readings=ctx.recent_readings_text,
+            recent_alarms=ctx.recent_alarms_text,
+        )
+
+        system_prompt = format_with_brand(ALARM_SUMMARY_SYSTEM, self._config.brand_name)
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning("AssistantLiveAgent: ответ обрезан по таймауту (audit_id=%s)", audit_id)
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning(
+                "AssistantLiveAgent: пустой ответ, dispatch пропущен (truncated=%s, audit_id=%s)",
+                result.truncated,
+                audit_id,
+            )
+            dispatched: list[str] = []
+        else:
+            dispatched = await self._router.dispatch(
+                event, result.text, targets=targets, audit_id=audit_id
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="alarm_summary",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched,
+            errors=errors,
+        )
+
+        logger.info(
+            "AssistantLiveAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
+            audit_id,
+            result.latency_s,
+            dispatched,
+        )
+        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
+            await self._generate_diagnostic_suggestion(event, payload)
+
+
+    async def _generate_diagnostic_suggestion(
+        self, event: EngineEvent, alarm_payload: dict[str, Any]
+    ) -> None:
+        """Generate and dispatch Slice B diagnostic suggestion (second LLM call).
+
+        Records a separate rate-limit timestamp so each Ollama call counts
+        toward the hourly budget (Slice B makes 2 calls per alarm event).
+        """
+        # Count diagnostic as a separate call toward the hourly rate limit
+        self._call_timestamps.append(time.monotonic())
+        audit_id = self._audit.make_audit_id()
+        ctx = await self._ctx_builder.build_diagnostic_suggestion_context(alarm_payload)
+        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
+        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
+
+        user_prompt = DIAGNOSTIC_SUGGESTION_USER.format(
+            alarm_id=ctx.alarm_id,
+            channels=channels_str,
+            values=values_str,
+            lookback_min=ctx.lookback_min,
+            channel_history=ctx.channel_history,
+            recent_alarms=ctx.recent_alarms,
+            past_cooldowns=ctx.past_cooldowns,
+            pressure_trend=ctx.pressure_trend,
+        )
+
+        system_prompt = format_with_brand(DIAGNOSTIC_SUGGESTION_SYSTEM, self._config.brand_name)
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning(
+                "AssistantLiveAgent: diagnostic ответ обрезан (audit_id=%s)", audit_id
+            )
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning("AssistantLiveAgent: пустой diagnostic ответ (audit_id=%s)", audit_id)
+            dispatched_diag: list[str] = []
+        else:
+            dispatched_diag = await self._router.dispatch(
+                event, result.text, targets=targets, audit_id=audit_id
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": alarm_payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="diagnostic_suggestion",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched_diag,
+            errors=errors,
+        )
+        logger.info(
+            "AssistantLiveAgent: diagnostic_suggestion dispatched (audit_id=%s, latency=%.1fs)",
+            audit_id,
+            result.latency_s,
+        )
+
+    async def _handle_experiment_finalize(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        payload = event.payload
+
+        ctx = await self._ctx_builder.build_experiment_finalize_context(payload)
+        _action_labels = {
+            "experiment_finalize": "Завершён штатно",
+            "experiment_stop": "Остановлен",
+            "experiment_abort": "Прерван аварийно",
+        }
+        user_prompt = EXPERIMENT_FINALIZE_USER.format(
+            experiment_id=ctx.experiment_id or "—",
+            name=ctx.name,
+            duration=ctx.duration_str,
+            status=_action_labels.get(ctx.action, ctx.action),
+            phases=ctx.phases_text,
+            alarms_summary=ctx.alarms_summary_text,
+        )
+
+        system_prompt = format_with_brand(EXPERIMENT_FINALIZE_SYSTEM, self._config.brand_name)
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning(
+                "AssistantLiveAgent: ответ обрезан (experiment_finalize, audit_id=%s)", audit_id
+            )
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning(
+                "AssistantLiveAgent: пустой ответ experiment_finalize (audit_id=%s)", audit_id
+            )
+            dispatched: list[str] = []
+        else:
+            dispatched = await self._router.dispatch(
+                event, result.text, targets=targets, audit_id=audit_id
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="experiment_finalize",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched,
+            errors=errors,
+        )
+        logger.info(
+            "AssistantLiveAgent: %s обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
+            event.event_type,
+            audit_id,
+            result.latency_s,
+            dispatched,
+        )
+
+    async def _handle_sensor_anomaly(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        payload = event.payload
+
+        ctx = await self._ctx_builder.build_sensor_anomaly_context(payload)
+        user_prompt = SENSOR_ANOMALY_USER.format(
+            channel=ctx.channel,
+            alarm_id=ctx.alarm_id,
+            level=ctx.level,
+            message=ctx.message,
+            health_score=ctx.health_score,
+            fault_flags=ctx.fault_flags,
+            current_value=ctx.current_value,
+            experiment_id=ctx.experiment_id or "—",
+            phase=ctx.phase or "—",
+        )
+
+        system_prompt = format_with_brand(SENSOR_ANOMALY_SYSTEM, self._config.brand_name)
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning(
+                "AssistantLiveAgent: ответ обрезан (sensor_anomaly, audit_id=%s)", audit_id
+            )
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning(
+                "AssistantLiveAgent: пустой ответ sensor_anomaly (audit_id=%s)", audit_id
+            )
+            dispatched_sa: list[str] = []
+        else:
+            dispatched_sa = await self._router.dispatch(
+                event, result.text, targets=targets, audit_id=audit_id
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="sensor_anomaly",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched_sa,
+            errors=errors,
+        )
+        logger.info(
+            "AssistantLiveAgent: sensor_anomaly_critical обработан "
+            "(audit_id=%s, latency=%.1fs, channel=%s)",
+            audit_id,
+            result.latency_s,
+            ctx.channel,
+        )
+        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
+            await self._generate_diagnostic_suggestion(event, payload)
+
+    async def _handle_shift_handover(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        payload = event.payload
+
+        ctx = await self._ctx_builder.build_shift_handover_context(payload)
+        user_prompt = SHIFT_HANDOVER_USER.format(
+            experiment_id=ctx.experiment_id or "нет активного эксперимента",
+            phase=ctx.phase or "—",
+            experiment_age=ctx.experiment_age,
+            active_alarms=ctx.active_alarms,
+            recent_events=ctx.recent_events,
+            shift_duration_h=ctx.shift_duration_h,
+        )
+
+        system_prompt = format_with_brand(SHIFT_HANDOVER_SYSTEM, self._config.brand_name)
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning(
+                "AssistantLiveAgent: ответ обрезан (shift_handover, audit_id=%s)", audit_id
+            )
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning(
+                "AssistantLiveAgent: пустой ответ shift_handover (audit_id=%s)", audit_id
+            )
+            dispatched_sh: list[str] = []
+        else:
+            dispatched_sh = await self._router.dispatch(
+                event, result.text, targets=targets, audit_id=audit_id
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="shift_handover",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched_sh,
+            errors=errors,
+        )
+        logger.info(
+            "AssistantLiveAgent: shift_handover_request обработан (audit_id=%s, latency=%.1fs)",
+            audit_id,
+            result.latency_s,
+        )
+
+
+    async def _handle_periodic_report(self, event: EngineEvent) -> None:
+        audit_id = self._audit.make_audit_id()
+        window_minutes = int(event.payload.get("window_minutes", 60))
+
+        ctx = await self._ctx_builder.build_periodic_report_context(
+            window_minutes=window_minutes,
+        )
+
+        if (
+            self._config.periodic_report_skip_if_idle
+            and ctx.total_event_count < self._config.periodic_report_min_events
+        ):
+            logger.debug(
+                "AssistantLiveAgent: periodic report skipped "
+                "(idle: %d events < min=%d)",
+                ctx.total_event_count,
+                self._config.periodic_report_min_events,
+            )
+            return
+
+        template_dict = ctx.to_template_dict()
+        user_prompt = PERIODIC_REPORT_USER.format(
+            window_minutes=window_minutes,
+            **template_dict,
+        )
+        system_prompt = format_with_brand(PERIODIC_REPORT_SYSTEM, self._config.brand_name)
+
+        result = await self._ollama.generate(
+            user_prompt,
+            system=system_prompt,
+            max_tokens=self._config.max_tokens,
+            temperature=self._config.temperature,
+            num_ctx=self._config.num_ctx,
+        )
+
+        errors: list[str] = []
+        if result.truncated:
+            errors.append("timeout_truncated")
+            logger.warning(
+                "AssistantLiveAgent: periodic report обрезан (audit_id=%s)", audit_id
+            )
+
+        targets = _build_targets(self._config)
+        if result.truncated or not result.text.strip():
+            logger.warning(
+                "AssistantLiveAgent: пустой periodic report (audit_id=%s)", audit_id
+            )
+            dispatched_pr: list[str] = []
+        else:
+            dispatched_pr = await self._router.dispatch(
+                event,
+                result.text,
+                targets=targets,
+                audit_id=audit_id,
+                prefix_suffix="(отчёт за час)",
+            )
+
+        await self._audit.log(
+            audit_id=audit_id,
+            trigger_event={
+                "event_type": event.event_type,
+                "payload": event.payload,
+                "experiment_id": event.experiment_id,
+            },
+            context_assembled=user_prompt,
+            prompt_template="periodic_report",
+            model=result.model,
+            system_prompt=system_prompt,
+            user_prompt=user_prompt,
+            response=result.text,
+            tokens={"in": result.tokens_in, "out": result.tokens_out},
+            latency_s=result.latency_s,
+            outputs_dispatched=dispatched_pr,
+            errors=errors,
+        )
+        logger.info(
+            "AssistantLiveAgent: periodic_report_request обработан "
+            "(audit_id=%s, latency=%.1fs, events=%d, dispatched=%s)",
+            audit_id,
+            result.latency_s,
+            ctx.total_event_count,
+            dispatched_pr,
+        )
+
+
+def _build_targets(config: AssistantConfig) -> list[OutputTarget]:
+    targets = []
+    if config.output_telegram:
+        targets.append(OutputTarget.TELEGRAM)
+    if config.output_operator_log:
+        targets.append(OutputTarget.OPERATOR_LOG)
+    if config.output_gui_insight:
+        targets.append(OutputTarget.GUI_INSIGHT)
+    return targets
+
+
+def _format_age(age_s: float | None) -> str:
+    if age_s is None:
+        return "неизвестно"
+    h, rem = divmod(int(age_s), 3600)
+    m, s = divmod(rem, 60)
+    if h > 0:
+        return f"{h}ч {m}м"
+    if m > 0:
+        return f"{m}м {s}с"
+    return f"{s}с"
diff --git a/src/cryodaq/agents/assistant/live/context_builder.py b/src/cryodaq/agents/assistant/live/context_builder.py
new file mode 100644
index 0000000..e2ca452
--- /dev/null
+++ b/src/cryodaq/agents/assistant/live/context_builder.py
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
+
+    async def build_shift_handover_context(
+        self, payload: dict[str, Any]
+    ) -> ShiftHandoverContext:
+        """Assemble context for shift handover summary prompt."""
+        return _build_shift_handover_context(self._em, payload)
+
+    async def build_periodic_report_context(
+        self,
+        *,
+        window_minutes: int = 60,
+    ) -> PeriodicReportContext:
+        """Aggregate engine activity over last window_minutes for periodic report.
+
+        Uses get_operator_log() with time window — no new SQLite methods needed.
+        All event types (alarms, phases, experiments, operator entries) are
+        stored in the operator log with identifying tags.
+        """
+        now = datetime.now(UTC)
+        start_time = now - timedelta(minutes=window_minutes)
+
+        entries: list[Any] = []
+        if hasattr(self._reader, "get_operator_log"):
+            try:
+                entries = await self._reader.get_operator_log(
+                    start_time=start_time,
+                    end_time=now,
+                    limit=50,
+                )
+            except Exception:
+                logger.debug("PeriodicReportContext: get_operator_log failed", exc_info=True)
+
+        alarm_entries = [e for e in entries if "alarm" in e.tags]
+        phase_entries = [e for e in entries if "phase_transition" in e.tags]
+        experiment_entries = [e for e in entries if "experiment" in e.tags]
+        calibration_entries = [e for e in entries if "calibration" in e.tags]
+        # Exclude machine-generated and AI-generated entries from operator section
+        operator_entries = [
+            e for e in entries
+            if e.source != "auto" and "ai" not in e.tags and "auto" not in e.tags
+        ]
+        # Any auto event not classified above (calibration, leak_rate, etc.)
+        other_entries = [
+            e for e in entries
+            if "auto" in e.tags
+            and "alarm" not in e.tags
+            and "phase_transition" not in e.tags
+            and "experiment" not in e.tags
+            and "calibration" not in e.tags
+            and "ai" not in e.tags
+        ]
+
+        total_event_count = (
+            len(alarm_entries) + len(phase_entries) + len(experiment_entries)
+            + len(calibration_entries) + len(operator_entries) + len(other_entries)
+        )
+
+        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
+        phase: str | None = None
+        if hasattr(self._em, "get_current_phase"):
+            try:
+                phase = self._em.get_current_phase()
+            except Exception:
+                pass
+
+        return PeriodicReportContext(
+            window_minutes=window_minutes,
+            active_experiment_id=experiment_id,
+            active_experiment_phase=phase,
+            alarm_entries=alarm_entries,
+            phase_entries=phase_entries,
+            experiment_entries=experiment_entries,
+            calibration_entries=calibration_entries,
+            operator_entries=operator_entries,
+            other_entries=other_entries,
+            total_event_count=total_event_count,
+        )
+
+    async def build_diagnostic_suggestion_context(
+        self,
+        alarm_payload: dict[str, Any],
+        *,
+        lookback_min: int = 60,
+    ) -> DiagnosticSuggestionContext:
+        """Assemble context for Slice B diagnostic suggestion.
+
+        Reads last lookback_min minutes of readings for alarm channels
+        from SQLite. Alarm history, cooldown history, and pressure trend
+        remain stubs until Cycle 4.1 wires those sources.
+        """
+        alarm_id = alarm_payload.get("alarm_id", "unknown")
+        channels: list[str] = alarm_payload.get("channels", [])
+        values: dict[str, float] = alarm_payload.get("values", {})
+        channel_history = await self._read_channel_history(channels, lookback_min)
+        pressure_trend = await self._read_pressure_trend()
+        return DiagnosticSuggestionContext(
+            alarm_id=alarm_id,
+            channels=channels,
+            values=values,
+            channel_history=channel_history,
+            recent_alarms="нет данных",
+            past_cooldowns="нет истории",
+            pressure_trend=pressure_trend,
+            lookback_min=lookback_min,
+        )
+
+    async def _read_channel_history(self, channels: list[str], lookback_min: int) -> str:
+        """Read recent readings for alarm channels from SQLite."""
+        if not channels or not hasattr(self._reader, "read_readings_history"):
+            return "нет данных"
+        try:
+            from_ts = _time.time() - lookback_min * 60
+            data: dict[str, list[tuple[float, float]]] = (
+                await self._reader.read_readings_history(
+                    channels=channels,
+                    from_ts=from_ts,
+                    limit_per_channel=20,
+                )
+            )
+            if not data:
+                return "нет данных"
+            lines: list[str] = []
+            for ch, readings in data.items():
+                if readings:
+                    vals = [f"{v:.4g}" for _, v in readings[-5:]]
+                    lines.append(f"- {ch}: [{', '.join(vals)}]")
+            return "\n".join(lines) if lines else "нет данных"
+        except Exception:
+            logger.debug("ContextBuilder: channel history read failed", exc_info=True)
+            return "нет данных"
+
+    async def _read_pressure_trend(self) -> str:
+        """Read recent pressure readings from SQLite."""
+        if not hasattr(self._reader, "read_readings_history"):
+            return "нет данных"
+        try:
+            from_ts = _time.time() - 30 * 60
+            data: dict[str, list[tuple[float, float]]] = (
+                await self._reader.read_readings_history(
+                    from_ts=from_ts,
+                    limit_per_channel=10,
+                )
+            )
+            pressure = {
+                k: v
+                for k, v in data.items()
+                if "pressure" in k.lower() or "mbar" in k.lower()
+            }
+            if not pressure:
+                return "нет данных"
+            lines: list[str] = []
+            for ch, readings in pressure.items():
+                if len(readings) >= 2:
+                    start = readings[0][1]
+                    end = readings[-1][1]
+                    threshold = 0.01 * max(abs(start), 1e-12)
+                    arrow = "→" if abs(end - start) < threshold else ("↑" if end > start else "↓")
+                    lines.append(f"- {ch}: {start:.2e} → {end:.2e} {arrow}")
+            return "\n".join(lines) if lines else "нет данных"
+        except Exception:
+            logger.debug("ContextBuilder: pressure trend read failed", exc_info=True)
+            return "нет данных"
+
+
+def _compute_experiment_age(em: Any) -> float | None:
+    try:
+        history = em.get_phase_history()
+        if not history:
+            return None
+        first = history[0].get("started_at")
+        if not first:
+            return None
+        from datetime import UTC, datetime
+
+        started = datetime.fromisoformat(first)
+        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
+    except Exception:
+        return None
+
+
+def _readings_stub(_channels: list[str], _lookback_s: float) -> str:
+    return "нет данных"
+
+
+def _alarms_stub(_lookback_s: float) -> str:
+    return "нет данных"
+
+
+# ---------------------------------------------------------------------------
+# Experiment finalize context
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class ExperimentFinalizeContext:
+    """Context for experiment finalize/stop/abort summary (Slice A)."""
+
+    experiment_id: str | None
+    name: str
+    action: str
+    duration_str: str
+    phases_text: str
+    alarms_summary_text: str
+
+
+# ---------------------------------------------------------------------------
+# Sensor anomaly context
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class SensorAnomalyContext:
+    """Context for sensor anomaly analysis (Slice A)."""
+
+    alarm_id: str
+    level: str
+    channel: str
+    channels: list[str]
+    values: dict[str, float]
+    message: str
+    health_score: str
+    fault_flags: str
+    current_value: str
+    experiment_id: str | None
+    phase: str | None
+
+
+# ---------------------------------------------------------------------------
+# Shift handover context
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class ShiftHandoverContext:
+    """Context for shift handover summary (Slice A)."""
+
+    experiment_id: str | None
+    phase: str | None
+    experiment_age: str
+    active_alarms: str
+    recent_events: str
+    shift_duration_h: int
+
+
+# ---------------------------------------------------------------------------
+# Concrete build methods on ContextBuilder
+# ---------------------------------------------------------------------------
+
+
+def _build_experiment_finalize_context(
+    em: Any, payload: dict[str, Any]
+) -> ExperimentFinalizeContext:
+    action = payload.get("action", "experiment_finalize")
+    experiment = payload.get("experiment", {})
+    experiment_id = experiment.get("experiment_id")
+    name = experiment.get("name") or experiment.get("title") or "—"
+    age_float = _compute_experiment_age(em)
+    if age_float is None:
+        # Fallback: try to compute from experiment dict
+        started = experiment.get("started_at") or experiment.get("created_at")
+        if started:
+            try:
+                from datetime import UTC, datetime
+
+                start_dt = datetime.fromisoformat(started)
+                age_s = (datetime.now(UTC) - start_dt.astimezone(UTC)).total_seconds()
+                duration_str = _format_age(age_s)
+            except Exception:
+                duration_str = "—"
+        else:
+            duration_str = "—"
+    else:
+        duration_str = _format_age(age_float)
+    phases = experiment.get("phases") or experiment.get("phase_history") or []
+    if phases:
+        phases_text = "\n".join(
+            f"- {p.get('phase', '?')}: {p.get('started_at', '?')}" for p in phases
+        )
+    else:
+        phases_text = "нет данных"
+    return ExperimentFinalizeContext(
+        experiment_id=experiment_id,
+        name=name,
+        action=action,
+        duration_str=duration_str,
+        phases_text=phases_text,
+        alarms_summary_text="нет данных",
+    )
+
+
+def _build_sensor_anomaly_context(
+    em: Any, payload: dict[str, Any]
+) -> SensorAnomalyContext:
+    alarm_id = payload.get("alarm_id", "unknown")
+    level = payload.get("level", "CRITICAL")
+    channels: list[str] = payload.get("channels", [])
+    values: dict[str, float] = payload.get("values", {})
+    message = payload.get("message", "—")
+    channel = channels[0] if channels else alarm_id.replace("diag:", "")
+    current_value = "—"
+    if values:
+        first_ch = next(iter(values))
+        current_value = f"{values[first_ch]:.4g}"
+    experiment_id: str | None = getattr(em, "active_experiment_id", None)
+    phase: str | None = None
+    if hasattr(em, "get_current_phase"):
+        try:
+            phase = em.get_current_phase()
+        except Exception:
+            pass
+    health_score = payload.get("health_score", "—")
+    fault_flags_raw = payload.get("fault_flags", [])
+    fault_flags = ", ".join(fault_flags_raw) if fault_flags_raw else "—"
+    return SensorAnomalyContext(
+        alarm_id=alarm_id,
+        level=level,
+        channel=channel,
+        channels=channels,
+        values=values,
+        message=message,
+        health_score=str(health_score),
+        fault_flags=fault_flags,
+        current_value=current_value,
+        experiment_id=experiment_id,
+        phase=phase,
+    )
+
+
+# ---------------------------------------------------------------------------
+# Campaign report context (Slice C) — async path for future event-driven use
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class CampaignReportContext:
+    """Context for Slice C campaign report intro (async EventBus path)."""
+
+    experiment_id: str | None
+    name: str
+    duration_str: str
+    phases_text: str
+    channel_stats: str
+    alarms_summary: str
+    operator_notes: str
+
+
+# ---------------------------------------------------------------------------
+# Diagnostic suggestion context (Slice B)
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class DiagnosticSuggestionContext:
+    """Context for diagnostic suggestion generation (Slice B)."""
+
+    alarm_id: str
+    channels: list[str]
+    values: dict[str, float]
+    channel_history: str
+    recent_alarms: str
+    past_cooldowns: str
+    pressure_trend: str
+    lookback_min: int = 60
+
+
+def _build_shift_handover_context(em: Any, payload: dict[str, Any]) -> ShiftHandoverContext:
+    experiment_id: str | None = getattr(em, "active_experiment_id", None)
+    phase: str | None = None
+    if hasattr(em, "get_current_phase"):
+        try:
+            phase = em.get_current_phase()
+        except Exception:
+            pass
+    age_s = _compute_experiment_age(em)
+    experiment_age = _format_age(age_s) if age_s is not None else "—"
+    shift_duration_h = int(payload.get("shift_duration_h", 8))
+    return ShiftHandoverContext(
+        experiment_id=experiment_id,
+        phase=phase,
+        experiment_age=experiment_age,
+        active_alarms="нет данных",
+        recent_events="нет данных",
+        shift_duration_h=shift_duration_h,
+    )
+
+
+def _format_age(age_s: float) -> str:
+    h, rem = divmod(int(age_s), 3600)
+    m, s = divmod(rem, 60)
+    if h > 0:
+        return f"{h}ч {m}м"
+    if m > 0:
+        return f"{m}м {s}с"
+    return f"{s}с"
+
+
+# ---------------------------------------------------------------------------
+# Periodic report context (F29)
+# ---------------------------------------------------------------------------
+
+
+@dataclass
+class PeriodicReportContext:
+    """Context for periodic narrative report (F29)."""
+
+    window_minutes: int
+    active_experiment_id: str | None
+    active_experiment_phase: str | None
+    alarm_entries: list[Any] = field(default_factory=list)
+    phase_entries: list[Any] = field(default_factory=list)
+    experiment_entries: list[Any] = field(default_factory=list)
+    calibration_entries: list[Any] = field(default_factory=list)
+    operator_entries: list[Any] = field(default_factory=list)
+    other_entries: list[Any] = field(default_factory=list)
+    total_event_count: int = 0
+
+    def to_template_dict(self) -> dict[str, str]:
+        """Format all context fields as prompt-ready strings."""
+        if self.active_experiment_id:
+            phase_str = (
+                f" (фаза: {self.active_experiment_phase})"
+                if self.active_experiment_phase else ""
+            )
+            active_exp = f"{self.active_experiment_id}{phase_str}"
+        else:
+            active_exp = "нет активного эксперимента"
+
+        return {
+            "active_experiment_summary": active_exp,
+            "events_section": _format_log_entries(self.other_entries) or "(нет)",
+            "alarms_section": _format_log_entries(self.alarm_entries) or "(нет)",
+            "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
+            "operator_entries_section": _format_log_entries(self.operator_entries) or "(нет)",
+            "calibration_section": _format_log_entries(self.calibration_entries) or "(нет)",
+            "total_event_count": str(self.total_event_count),
+        }
+
+
+def _format_log_entries(entries: list[Any]) -> str:
+    if not entries:
+        return ""
+    lines = []
+    for e in entries[:10]:
+        ts = e.timestamp.astimezone().strftime("%H:%M") if hasattr(e, "timestamp") else "?"
+        msg = getattr(e, "message", str(e))[:120]
+        lines.append(f"- {ts}: {msg}")
+    return "\n".join(lines)
diff --git a/src/cryodaq/agents/assistant/live/output_router.py b/src/cryodaq/agents/assistant/live/output_router.py
new file mode 100644
index 0000000..93c3933
--- /dev/null
+++ b/src/cryodaq/agents/assistant/live/output_router.py
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
+            except Exception:
+                logger.warning(
+                    "OutputRouter: failed to dispatch to %s (audit_id=%s)",
+                    target.value,
+                    audit_id,
+                    exc_info=True,
+                )
+
+        return dispatched
diff --git a/src/cryodaq/agents/assistant/live/prompts.py b/src/cryodaq/agents/assistant/live/prompts.py
new file mode 100644
index 0000000..4342d5b
--- /dev/null
+++ b/src/cryodaq/agents/assistant/live/prompts.py
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
+- НЕ используй Markdown (жирный, курсив, заголовки). Текст пойдёт в DOCX напрямую.
+- 200-400 слов.
+"""
+
+CAMPAIGN_REPORT_INTRO_USER = """\
+ДАННЫЕ ОБ ЭКСПЕРИМЕНТЕ:
+- ID: {experiment_id}
+- Название: {name}
+- Оператор: {operator}
+- Образец: {sample}
+- Начало: {start_time}
+- Завершение: {end_time}
+- Длительность: {duration}
+- Итоговый статус: {status}
+
+ФАЗЫ ЭКСПЕРИМЕНТА:
+{phases_text}
+
+ПАРАМЕТРЫ ИЗМЕРЕНИЙ (мин / макс / среднее):
+{channel_stats}
+
+АЛАРМЫ ЗА ЭКСПЕРИМЕНТ:
+{alarms_summary}
+
+КЛЮЧЕВЫЕ ЗАПИСИ ОПЕРАТОРА:
+{operator_notes}
+
+Напиши аннотацию к научному отчёту. Только русский язык, формальный стиль, без Markdown.
+"""
+
+# ---------------------------------------------------------------------------
+# Diagnostic suggestion — Slice B
+# Revision: 2026-05-01 v1 (initial)
+# ---------------------------------------------------------------------------
+
+DIAGNOSTIC_SUGGESTION_SYSTEM = """\
+Ты — {brand_name}, аналитик-диагностик в криогенной лаборатории. Твоя задача — \
+предложить конкретные диагностические действия по сработавшему аларму.
+
+Принципы:
+- Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
+- Предлагай, не командуй: "рекомендуется проверить", не "проверь".
+- Если данных недостаточно — напиши "недостаточно данных для диагноза".
+- Не более 4 numbered шагов. Конкретные шаги, не общие фразы.
+- Используй только данные из запроса — не выдумывай значения.
+- НИКОГДА не предлагай safety-действия автоматически (аварийное \
+отключение, переключение фаз).
+- 80-130 слов. Telegram-friendly Markdown (жирный, курсив — ok).
+"""
+
+DIAGNOSTIC_SUGGESTION_USER = """\
+АЛАРМ:
+- ID: {alarm_id}
+- Каналы: {channels}
+- Текущие значения: {values}
+
+ИСТОРИЯ КАНАЛОВ (последние {lookback_min} минут):
+{channel_history}
+
+НЕДАВНИЕ АЛАРМЫ (последний час):
+{recent_alarms}
+
+ИСТОРИЯ ОХЛАЖДЕНИЙ (последние 5):
+{past_cooldowns}
+
+ТРЕНД ДАВЛЕНИЯ (30 мин):
+{pressure_trend}
+
+Предложи конкретные диагностические действия оператору. Только русский язык.
+"""
+
+# ---------------------------------------------------------------------------
+# Sensor anomaly — Slice A
+# Revision: 2026-05-01 v1 (initial)
+# ---------------------------------------------------------------------------
+
+SENSOR_ANOMALY_SYSTEM = """\
+Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
+краткий анализ аномалии датчика для оператора.
+
+Принципы:
+- Отвечай ТОЛЬКО на русском языке. Никакого английского в ответе.
+- Используй только данные из запроса.
+- Объясни что именно не так: избыточный шум, дрейф, нарушение корреляции.
+- Предложи практические диагностические шаги (проверить контакты, кабель, крепление).
+- НИКОГДА не предлагай изменять параметры безопасности или отключать оборудование.
+- 60-100 слов. Telegram-friendly Markdown (жирный, курсив — ok).
+"""
+
+SENSOR_ANOMALY_USER = """\
+АНОМАЛИЯ ДАТЧИКА:
+- Канал: {channel}
+- Аларм ID: {alarm_id}
+- Уровень: {level}
+- Описание: {message}
+
+ПОКАЗАТЕЛИ ЗДОРОВЬЯ:
+- Health score: {health_score}
+- Флаги: {fault_flags}
+- Текущее значение: {current_value}
+
+ЭКСПЕРИМЕНТ:
+- ID: {experiment_id}
+- Фаза: {phase}
+
+Сформируй краткий анализ аномалии для оператора. Только русский язык.
+"""
+
+# ---------------------------------------------------------------------------
+# Shift handover summary — Slice A
+# Revision: 2026-05-01 v1 (initial)
+# ---------------------------------------------------------------------------
+
+SHIFT_HANDOVER_SYSTEM = """\
+Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
+подготовить сводку смены для передачи следующему оператору.
+
+Принципы:
+- Отвечай ТОЛЬКО на русском языке.
+- Структура: текущее состояние → ключевые события смены → что требует внимания.
+- Конкретные значения, никаких размытых фраз.
+- НИКОГДА не предлагай safety-действия автоматически.
+- 120-200 слов. Telegram-friendly Markdown.
+"""
+
+def format_with_brand(template: str, brand_name: str) -> str:
+    """Interpolate {brand_name} placeholder in a system prompt template."""
+    return template.format(brand_name=brand_name)
+
+
+# ---------------------------------------------------------------------------
+# Periodic narrative report — F29
+# Revision: 2026-05-01 v1 (initial)
+# ---------------------------------------------------------------------------
+
+PERIODIC_REPORT_SYSTEM = """\
+Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.
+Твоя задача — краткий обзор активности за заданное окно времени для оператора в Telegram.
+
+Принципы:
+- Отвечай ТОЛЬКО на русском языке.
+- Не выдумывай контекст. Используй только данные ниже.
+- Конкретные значения, не размытые описания.
+- Тон conversational, не формальный (это сводка для оператора, не отчёт).
+- Если событий мало — короткий summary (5-10 слов про то что всё стабильно).
+- Если событий много — структурируй по категориям (алармы / фазы / операторский журнал / калибровка).
+- 100-200 слов максимум. Telegram-friendly Markdown (жирный, курсив — ok).
+- Если активного эксперимента нет — упомяни это в одной фразе.
+"""
+
+PERIODIC_REPORT_USER = """\
+Окно времени: последние {window_minutes} минут.
+
+Активный эксперимент: {active_experiment_summary}
+
+Алармы:
+{alarms_section}
+
+Переходы фаз:
+{phase_transitions_section}
+
+События (прочие):
+{events_section}
+
+Записи операторского журнала:
+{operator_entries_section}
+
+Калибровка:
+{calibration_section}
+
+Всего событий: {total_event_count}
+
+Сгенерируй краткую сводку для оператора в Telegram. Только русский язык.
+"""
+
+
+SHIFT_HANDOVER_USER = """\
+ЗАПРОС СВОДКИ ДЛЯ ПЕРЕДАЧИ СМЕНЫ:
+
+ТЕКУЩЕЕ СОСТОЯНИЕ:
+- Эксперимент: {experiment_id}
+- Фаза: {phase}
+- Продолжительность эксперимента: {experiment_age}
+
+АКТИВНЫЕ АЛАРМЫ:
+{active_alarms}
+
+СОБЫТИЯ ЗА СМЕНУ (последние {shift_duration_h}ч):
+{recent_events}
+
+Подготовь сводку для следующего оператора. Только русский язык.
+"""
diff --git a/src/cryodaq/engine.py b/src/cryodaq/engine.py
index d7f0854..95c6260 100644
--- a/src/cryodaq/engine.py
+++ b/src/cryodaq/engine.py
@@ -1,171 +1,213 @@
 """Головной процесс CryoDAQ Engine (безголовый).
 
 Запуск:
     cryodaq-engine          # через entry point
     python -m cryodaq.engine  # напрямую
 
 Загружает конфигурации, создаёт и связывает все подсистемы:
     drivers → DataBroker →
     [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
 
 Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
 """
 
 from __future__ import annotations
 
 import asyncio
 import logging
 import os
 import signal
 import sys
 import time
 from datetime import UTC, datetime
 
 # Windows: pyzmq требует SelectorEventLoop (не Proactor)
 if sys.platform == "win32":
     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
 from pathlib import Path
 from typing import Any
 
 import yaml
 
+from cryodaq.agents.assistant.shared.audit import AuditLogger
+from cryodaq.agents.assistant.live.context_builder import ContextBuilder
+from cryodaq.agents.assistant.live.agent import AssistantLiveAgent, AssistantConfig
+from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
+from cryodaq.agents.assistant.live.output_router import OutputRouter
 from cryodaq.analytics.calibration import CalibrationStore
 from cryodaq.analytics.leak_rate import LeakRateEstimator
 from cryodaq.analytics.plugin_loader import PluginPipeline
 from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
 from cryodaq.core.alarm import AlarmEngine
 from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
 from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
 from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
 from cryodaq.core.broker import DataBroker
 from cryodaq.core.calibration_acquisition import (
     CalibrationAcquisitionService,
     CalibrationCommandError,
 )
 from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
 from cryodaq.core.channel_state import ChannelStateTracker
 from cryodaq.core.disk_monitor import DiskMonitor
+from cryodaq.core.event_bus import EngineEvent, EventBus
 from cryodaq.core.event_logger import EventLogger
 from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
 from cryodaq.core.housekeeping import (
     AdaptiveThrottle,
     HousekeepingConfigError,
     HousekeepingService,
     load_critical_channels_from_alarms_v3,
     load_housekeeping_config,
     load_protected_channel_patterns,
 )
 from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
 from cryodaq.core.operator_log import OperatorLogEntry
 from cryodaq.core.rate_estimator import RateEstimator
 from cryodaq.core.safety_broker import SafetyBroker
 from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
 from cryodaq.core.scheduler import InstrumentConfig, Scheduler
 from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
 from cryodaq.core.smu_channel import normalize_smu_channel
 from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
 from cryodaq.drivers.base import Reading
 from cryodaq.notifications.escalation import EscalationService
 from cryodaq.notifications.periodic_report import PeriodicReporter
 from cryodaq.notifications.telegram_commands import TelegramCommandBot
 from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
 from cryodaq.reporting.generator import ReportGenerator
 from cryodaq.storage.sqlite_writer import SQLiteWriter
 
 logger = logging.getLogger("cryodaq.engine")
 
 # ---------------------------------------------------------------------------
 # Пути по умолчанию (относительно корня проекта)
 # ---------------------------------------------------------------------------
 
 _PROJECT_ROOT = get_project_root()
 _CONFIG_DIR = get_config_dir()
 _PLUGINS_DIR = _PROJECT_ROOT / "plugins"
 _DATA_DIR = get_data_dir()
 
 # Интервал самодиагностики (секунды)
 _WATCHDOG_INTERVAL_S = 30.0
 _LOG_GET_TIMEOUT_S = 1.5
 _EXPERIMENT_STATUS_TIMEOUT_S = 1.5
 
 
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
+        try:
+            experiment_id = getattr(experiment_manager, "active_experiment_id", None)
+            if experiment_id is None:
+                active = getattr(experiment_manager, "active_experiment", None)
+                experiment_id = getattr(active, "experiment_id", None) if active else None
+            await event_bus.publish(
+                EngineEvent(
+                    event_type="periodic_report_request",
+                    timestamp=datetime.now(UTC),
+                    payload={
+                        "window_minutes": window_minutes,
+                        "trigger": "scheduled",
+                    },
+                    experiment_id=experiment_id,
+                )
+            )
+        except Exception as exc:
+            logger.error("Periodic assistant report tick error: %s", exc)
+
+
 async def _run_keithley_command(
     action: str,
     cmd: dict[str, Any],
     safety_manager: SafetyManager,
 ) -> dict[str, Any]:
     """Dispatch channel-scoped Keithley commands to SafetyManager."""
     channel = cmd.get("channel")
 
     if action == "keithley_start":
         smu_channel = normalize_smu_channel(channel)
         p = float(cmd.get("p_target", 0))
         v = float(cmd.get("v_comp", 40))
         i = float(cmd.get("i_comp", 1.0))
         return await safety_manager.request_run(p, v, i, channel=smu_channel)
 
     if action == "keithley_stop":
         smu_channel = normalize_smu_channel(channel)
         return await safety_manager.request_stop(channel=smu_channel)
 
     if action == "keithley_emergency_off":
         smu_channel = normalize_smu_channel(channel)
         return await safety_manager.emergency_off(channel=smu_channel)
 
     if action == "keithley_set_target":
         smu_channel = normalize_smu_channel(cmd.get("channel"))
         p = float(cmd.get("p_target", 0))
         return await safety_manager.update_target(p, channel=smu_channel)
 
     if action == "keithley_set_limits":
         smu_channel = normalize_smu_channel(cmd.get("channel"))
         return await safety_manager.update_limits(
             channel=smu_channel,
             v_comp=float(cmd["v_comp"]) if cmd.get("v_comp") is not None else None,
             i_comp=float(cmd["i_comp"]) if cmd.get("i_comp") is not None else None,
         )
 
     raise ValueError(f"Unsupported Keithley command: {action}")
 
 
 def _parse_log_time(raw: Any) -> datetime | None:
     if raw in (None, ""):
         return None
     if isinstance(raw, (int, float)):
         return datetime.fromtimestamp(float(raw), tz=UTC)
     if isinstance(raw, str):
         value = raw.strip()
         if not value:
             return None
         if value.endswith("Z"):
             value = f"{value[:-1]}+00:00"
         parsed = datetime.fromisoformat(value)
         if parsed.tzinfo is None:
             return parsed.replace(tzinfo=UTC)
         return parsed.astimezone(UTC)
     raise ValueError("Invalid log time filter.")
 
 
 def _parse_experiment_time(raw: Any) -> datetime | None:
     return _parse_log_time(raw)
 
 
 async def _publish_operator_log_entry(
     broker: DataBroker | None,
     entry: OperatorLogEntry,
 ) -> None:
     if broker is None:
         return
     await broker.publish(
         Reading(
             timestamp=entry.timestamp,
             instrument_id="operator_log",
             channel="analytics/operator_log_entry",
             value=float(entry.id),
             unit="",
             metadata=entry.to_payload(),
         )
     )
 
 
 async def _run_operator_log_command(
@@ -1040,386 +1082,426 @@ async def _run_engine(*, mock: bool = False) -> None:
     )
     for cfg in driver_configs:
         scheduler.add(cfg)
 
     # ZMQ PUB
     zmq_queue = await broker.subscribe("zmq_publisher")
     zmq_pub = ZMQPublisher()
 
     # Alarm Engine
     alarm_engine = AlarmEngine(broker)
     if alarms_cfg.exists():
         alarm_engine.load_config(alarms_cfg)
     else:
         logger.warning("Файл тревог не найден: %s", alarms_cfg)
 
     # Interlock Engine — действия делегируются SafetyManager.
     # Phase 2a Codex I.1: the actions-dict callables are kept as no-ops for
     # backwards compatibility with InterlockEngine's required interface, but
     # the REAL safety routing happens via trip_handler which receives the
     # full (condition, reading) context. Without this the action name and
     # channel would be discarded and stop_source would behave as emergency_off.
     async def _interlock_noop() -> None:
         return None
 
     interlock_actions: dict[str, Any] = {
         "emergency_off": _interlock_noop,
         "stop_source": _interlock_noop,
     }
 
     async def _interlock_trip_handler(condition: Any, reading: Any) -> None:
         # SAFETY (Phase 2a Codex P1): the actions-dict callables are no-ops,
         # so this handler is the SOLE path that triggers a SafetyManager
         # response. If anything raises here, InterlockEngine._trip will
         # log-and-swallow → fail-open. We catch ourselves and escalate to
         # a guaranteed _fault as a last resort. _fault is unlocked and
         # idempotent on the Keithley side (verified Phase 1).
         try:
             await safety_manager.on_interlock_trip(
                 interlock_name=condition.name,
                 channel=reading.channel,
                 value=float(reading.value) if reading.value is not None else 0.0,
                 action=condition.action,
             )
         except Exception as exc:
             logger.critical(
                 "INTERLOCK trip_handler FAILED for '%s' (action=%s): %s — "
                 "escalating to guaranteed fault.",
                 condition.name,
                 condition.action,
                 exc,
                 exc_info=True,
             )
             try:
                 await safety_manager._fault(
                     f"Interlock trip_handler failed: {condition.name}: {exc}",
                     channel=reading.channel,
                     value=float(reading.value) if reading.value is not None else 0.0,
                 )
             except Exception as exc2:
                 logger.critical(
                     "INTERLOCK escalation _fault FAILED for '%s': %s — "
                     "instrument state UNKNOWN, immediate operator intervention!",
                     condition.name,
                     exc2,
                     exc_info=True,
                 )
 
     interlock_engine = InterlockEngine(
         broker,
         actions=interlock_actions,
         trip_handler=_interlock_trip_handler,
     )
     interlock_engine.load_config(interlocks_cfg)
 
     # ExperimentManager
     experiment_manager = ExperimentManager(
         data_dir=_DATA_DIR,
         instruments_config=instruments_cfg,
         templates_dir=_CONFIG_DIR / "experiment_templates",
     )
-    event_logger = EventLogger(writer, experiment_manager)
+    event_bus = EventBus()
+    event_logger = EventLogger(writer, experiment_manager, event_bus=event_bus)
 
     # --- F13: Leak rate estimator ---
     _instruments_raw = yaml.safe_load(instruments_cfg.read_text(encoding="utf-8"))
     _chamber_cfg = _instruments_raw.get("chamber", {})
     _leak_cfg = _chamber_cfg.get("leak_rate", {})
     leak_rate_estimator = LeakRateEstimator(
         chamber_volume_l=float(_chamber_cfg.get("volume_l", 0.0)),
         sample_window_s=float(_leak_cfg.get("default_sample_window_s", 300.0)),
         data_dir=_DATA_DIR,
     )
 
     # --- Alarm Engine v2 ---
     _alarms_v3_cfg = _CONFIG_DIR / "alarms_v3.yaml"
     _alarm_v2_engine_cfg, _alarm_v2_configs = load_alarm_config(_alarms_v3_cfg)
     _alarm_v2_state_tracker = ChannelStateTracker(
         stale_timeout_s=30.0,
         fault_window_s=300.0,
     )
     _alarm_v2_rate = RateEstimator(
         window_s=_alarm_v2_engine_cfg.rate_window_s,
         min_points=_alarm_v2_engine_cfg.rate_min_points,
     )
     _alarm_v2_phase = ExperimentPhaseProvider(experiment_manager)
     _alarm_v2_setpoint = ExperimentSetpointProvider(
         experiment_manager, _alarm_v2_engine_cfg.setpoints
     )
     alarm_v2_evaluator = AlarmEvaluator(
         _alarm_v2_state_tracker, _alarm_v2_rate, _alarm_v2_phase, _alarm_v2_setpoint
     )
     alarm_v2_state_mgr = AlarmStateManager()
     if _alarm_v2_configs:
         logger.info("Alarm Engine v2: загружено %d алармов", len(_alarm_v2_configs))
     else:
         logger.info("Alarm Engine v2: config/alarms_v3.yaml не найден, v2 отключён")
 
     # --- Sensor Diagnostics Engine ---
     _plugins_cfg_path = _cfg("plugins")
     _plugins_raw: dict[str, Any] = {}
     if _plugins_cfg_path.exists():
         with _plugins_cfg_path.open(encoding="utf-8") as fh:
             _plugins_raw = yaml.safe_load(fh) or {}
     _sd_cfg = _plugins_raw.get("sensor_diagnostics", {})
     _sd_enabled = _sd_cfg.get("enabled", False)
     sensor_diag: SensorDiagnosticsEngine | None = None
     if _sd_enabled:
         _ch_mgr = get_channel_manager()
         # Build correlation groups from config; channel ids use display prefix (Т1→T1)
         _sd_alarm_publisher = (
             alarm_v2_state_mgr
             if _sd_cfg.get("alarm_publishing_enabled", True)
             else None
         )
         sensor_diag = SensorDiagnosticsEngine(
             config=_sd_cfg,
             alarm_publisher=_sd_alarm_publisher,
             warning_duration_s=float(_sd_cfg.get("warning_duration_s", 300.0)),
             critical_duration_s=float(_sd_cfg.get("critical_duration_s", 900.0)),
         )
         # Set display names from channel_manager
         sensor_diag.set_channel_names(
             {ch_id: _ch_mgr.get_display_name(ch_id) for ch_id in _ch_mgr.get_all()}
         )
         logger.info(
             "SensorDiagnostics: enabled, update_interval=%ds, groups=%d, alarm_publishing=%s",
             _sd_cfg.get("update_interval_s", 10),
             len(_sd_cfg.get("correlation_groups", {})),
             _sd_alarm_publisher is not None,
         )
     else:
         logger.info("SensorDiagnostics: отключён (plugins.yaml не найден или enabled=false)")
 
     # --- Vacuum Trend Predictor ---
     _vt_cfg = _plugins_raw.get("vacuum_trend", {})
     _vt_enabled = _vt_cfg.get("enabled", False)
     vacuum_trend: VacuumTrendPredictor | None = None
     if _vt_enabled:
         vacuum_trend = VacuumTrendPredictor(config=_vt_cfg)
         logger.info(
             "VacuumTrendPredictor: enabled, window=%ds, targets=%s",
             _vt_cfg.get("window_s", 3600),
             _vt_cfg.get("targets_mbar", [1e-4, 1e-5, 1e-6]),
         )
     else:
         logger.info("VacuumTrendPredictor: отключён")
 
     housekeeping_service = HousekeepingService(
         _DATA_DIR,
         experiment_manager.data_dir / "experiments",
         config=housekeeping_raw.get("retention", {}),
     )
 
     async def _track_runtime_signals() -> None:
         queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
         try:
             while True:
                 adaptive_throttle.observe_runtime_signal(await queue.get())
         except asyncio.CancelledError:
             return
 
     async def _alarm_v2_feed_readings() -> None:
         """Подписаться на DataBroker и кормить v2 channel_state + rate_estimator."""
         queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
         try:
             while True:
                 reading: Reading = await queue.get()
                 _alarm_v2_state_tracker.update(reading)
                 _alarm_v2_rate.push(
                     reading.channel,
                     reading.timestamp.timestamp(),
                     reading.value,
                 )
         except asyncio.CancelledError:
             return
 
     # Strong-ref set for fire-and-forget Telegram dispatch tasks.
     # Without this the loop only weak-refs tasks and GC can drop a pending
     # alarm notification mid-flight. See DEEP_AUDIT_CC.md A.1/A.2/I.2.
     _alarm_dispatch_tasks: set[asyncio.Task] = set()
 
     async def _alarm_v2_tick() -> None:
         """Периодически вычислять алармы v2 и диспетчеризировать события."""
         poll_s = _alarm_v2_engine_cfg.poll_interval_s
         while True:
             await asyncio.sleep(poll_s)
             if not _alarm_v2_configs:
                 continue
             current_phase = _alarm_v2_phase.get_current_phase()
             for alarm_cfg in _alarm_v2_configs:
                 # Проверка фазового фильтра
                 if alarm_cfg.phase_filter is not None:
                     if current_phase not in alarm_cfg.phase_filter:
                         # Вне фазы — явно очистить если был активен
                         alarm_v2_state_mgr.process(alarm_cfg.alarm_id, None, alarm_cfg.config)
                         continue
                 try:
                     _active_alarms = alarm_v2_state_mgr.get_active()
                     _active_event = _active_alarms.get(alarm_cfg.alarm_id)
                     event = alarm_v2_evaluator.evaluate(
                         alarm_cfg.alarm_id,
                         alarm_cfg.config,
                         is_active=_active_event is not None,
                         active_channels=(
                             frozenset(_active_event.channels)
                             if _active_event is not None
                             else None
                         ),
                     )
                     transition = alarm_v2_state_mgr.process(
                         alarm_cfg.alarm_id, event, alarm_cfg.config
                     )
                     if transition == "TRIGGERED" and event is not None:
                         # GUI polls via alarm_v2_status command; optionally notify via Telegram
                         if "telegram" in alarm_cfg.notify and telegram_bot is not None:
                             msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                             t = asyncio.create_task(
                                 telegram_bot._send_to_all(msg),
                                 name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
                             )
                             _alarm_dispatch_tasks.add(t)
                             t.add_done_callback(_alarm_dispatch_tasks.discard)
+                        await event_bus.publish(
+                            EngineEvent(
+                                event_type="alarm_fired",
+                                timestamp=datetime.now(UTC),
+                                payload={
+                                    "alarm_id": event.alarm_id,
+                                    "level": event.level,
+                                    "message": event.message,
+                                    "channels": event.channels,
+                                    "values": event.values,
+                                },
+                                experiment_id=experiment_manager.active_experiment_id,
+                            )
+                        )
+                    elif transition == "CLEARED":
+                        await event_bus.publish(
+                            EngineEvent(
+                                event_type="alarm_cleared",
+                                timestamp=datetime.now(UTC),
+                                payload={"alarm_id": alarm_cfg.alarm_id},
+                                experiment_id=experiment_manager.active_experiment_id,
+                            )
+                        )
                 except Exception as exc:
                     logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)
 
     # --- Sensor diagnostics feed + tick tasks ---
     async def _sensor_diag_feed() -> None:
         """Feed readings into SensorDiagnosticsEngine buffers."""
         if sensor_diag is None:
             return
         queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
         try:
             while True:
                 reading: Reading = await queue.get()
                 sensor_diag.push(
                     reading.channel,
                     reading.timestamp.timestamp(),
                     reading.value,
                 )
         except asyncio.CancelledError:
             return
 
     async def _sensor_diag_tick() -> None:
         """Periodically recompute sensor diagnostics and dispatch alarm notifications."""
         if sensor_diag is None:
             return
         interval = _sd_cfg.get("update_interval_s", 10)
         _notify_telegram = _sd_cfg.get("notify_telegram", True)
         while True:
             await asyncio.sleep(interval)
             try:
                 new_events = sensor_diag.update()
                 if _notify_telegram and telegram_bot is not None and new_events:
                     aggregation_threshold = _sd_cfg.get("aggregation_threshold", 3)
                     # F20 aggregation: batch > N simultaneous events into one message
                     if len(new_events) > aggregation_threshold:
                         criticals = [e for e in new_events if e.level == "CRITICAL"]
                         warnings = [e for e in new_events if e.level == "WARNING"]
                         parts: list[str] = []
                         if criticals:
                             names = ", ".join(
                                 e.channels[0] if e.channels else e.alarm_id
                                 for e in criticals
                             )
                             parts.append(f"{len(criticals)} channels critical: {names}")
                         if warnings:
                             names = ", ".join(
                                 e.channels[0] if e.channels else e.alarm_id
                                 for e in warnings
                             )
                             parts.append(f"{len(warnings)} channels warning: {names}")
                         msg = "⚠ Diagnostic alarm batch:\n" + "\n".join(parts)
                         t = asyncio.create_task(
                             telegram_bot._send_to_all(msg),
                             name="diag_tg_batch",
                         )
                         _alarm_dispatch_tasks.add(t)
                         t.add_done_callback(_alarm_dispatch_tasks.discard)
                     else:
                         for event in new_events:
                             msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                             t = asyncio.create_task(
                                 telegram_bot._send_to_all(msg),
                                 name=f"diag_tg_{event.alarm_id}",
                             )
                             _alarm_dispatch_tasks.add(t)
                             t.add_done_callback(_alarm_dispatch_tasks.discard)
+                for _sd_ev in new_events:
+                    if _sd_ev.level.upper() == "CRITICAL":
+                        await event_bus.publish(
+                            EngineEvent(
+                                event_type="sensor_anomaly_critical",
+                                timestamp=datetime.now(UTC),
+                                payload={
+                                    "alarm_id": _sd_ev.alarm_id,
+                                    "level": _sd_ev.level,
+                                    "channels": _sd_ev.channels,
+                                    "values": _sd_ev.values,
+                                    "message": _sd_ev.message,
+                                },
+                                experiment_id=experiment_manager.active_experiment_id,
+                            )
+                        )
             except Exception as exc:
                 logger.error("SensorDiagnostics tick error: %s", exc)
 
     # --- Vacuum trend feed + tick tasks ---
     async def _vacuum_trend_feed() -> None:
         """Feed pressure readings into VacuumTrendPredictor."""
         if vacuum_trend is None:
             return
         pressure_channel = _vt_cfg.get("pressure_channel", "")
         queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
         try:
             while True:
                 reading: Reading = await queue.get()
                 # Accept readings from the pressure channel or any mbar-unit reading
                 if pressure_channel and reading.channel != pressure_channel:
                     if reading.unit != "mbar":
                         continue
                 elif not pressure_channel and reading.unit != "mbar":
                     continue
                 vacuum_trend.push(reading.timestamp.timestamp(), reading.value)
         except asyncio.CancelledError:
             return
 
     async def _vacuum_trend_tick() -> None:
         """Periodically recompute vacuum trend prediction."""
         if vacuum_trend is None:
             return
         interval = _vt_cfg.get("update_interval_s", 30)
         while True:
             await asyncio.sleep(interval)
             try:
                 vacuum_trend.update()
             except Exception as exc:
                 logger.error("VacuumTrendPredictor tick error: %s", exc)
 
     async def _leak_rate_feed() -> None:
         """Feed pressure readings into LeakRateEstimator; auto-finalize on window expiry."""
         pressure_channel = _vt_cfg.get("pressure_channel", "")
         queue = await broker.subscribe("leak_rate_feed", maxsize=500)
         try:
             while True:
                 reading: Reading = await queue.get()
                 if pressure_channel and reading.channel != pressure_channel:
                     continue
                 if reading.unit != "mbar":
                     continue
                 if not leak_rate_estimator.is_active:
                     continue
                 leak_rate_estimator.add_sample(reading.timestamp, reading.value)
                 if leak_rate_estimator.should_finalize():
                     try:
                         result = leak_rate_estimator.finalize()
                         await event_logger.log_event(
                             "leak_rate",
                             f"Leak rate (auto): {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
                         )
                     except (ValueError, Exception) as exc:  # noqa: BLE001
                         logger.error("Leak rate auto-finalize failed: %s", exc)
         except asyncio.CancelledError:
             return
 
     # Обработчик команд от GUI — через SafetyManager
     async def _handle_gui_command(cmd: dict[str, Any]) -> dict[str, Any]:
         action = cmd.get("cmd", "")
         try:
             if action in {
                 "keithley_emergency_off",
                 "keithley_stop",
                 "keithley_start",
                 "keithley_set_target",
                 "keithley_set_limits",
             }:
                 result = await _run_keithley_command(action, cmd, safety_manager)
                 if result.get("ok"):
                     ch = cmd.get("channel", "?")
                     if action == "keithley_start":
                         await event_logger.log_event("keithley", f"Keithley {ch}: запуск")
                     elif action == "keithley_stop":
                         await event_logger.log_event("keithley", f"Keithley {ch}: остановка")
                     elif action == "keithley_emergency_off":
@@ -1533,509 +1615,614 @@ async def _run_engine(*, mock: bool = False) -> None:
                 operator = cmd.get("operator", "")
                 reason = cmd.get("reason", "")
                 ack_event = alarm_v2_state_mgr.acknowledge(
                     name,
                     operator=operator,
                     reason=reason,
                 )
                 if ack_event is not None:
                     await broker.publish(
                         Reading(
                             timestamp=datetime.now(UTC),
                             instrument_id="alarm_v2",
                             channel="alarm_v2/acknowledged",
                             value=ack_event["acknowledged_at"],
                             unit="",
                             metadata=ack_event,
                         )
                     )
                 return {
                     "ok": ack_event is not None or name in alarm_v2_state_mgr.get_active(),
                     "alarm_name": name,
                     "event_emitted": ack_event is not None,
                 }
             if action in {
                 "get_app_mode",
                 "set_app_mode",
                 "experiment_templates",
                 "experiment_status",
                 "experiment_archive_list",
                 "experiment_list_archive",
                 "experiment_start",
                 "experiment_create",
                 "experiment_get_active",
                 "experiment_update",
                 "experiment_finalize",
                 "experiment_stop",
                 "experiment_abort",
                 "experiment_get_archive_item",
                 "experiment_attach_run_record",
                 "experiment_create_retroactive",
                 "experiment_generate_report",
                 "experiment_advance_phase",
                 "experiment_phase_status",
             }:
                 experiment_call = asyncio.to_thread(
                     _run_experiment_command,
                     action,
                     cmd,
                     experiment_manager,
                 )
                 if action == "experiment_status":
                     # NOTE: asyncio.wait_for on an asyncio.to_thread() call times out the AWAIT,
                     # not the worker thread. If get_status_payload() is pathologically slow, the
                     # background thread keeps running until it returns naturally. This is an
                     # accepted residual risk — REP is still protected by the outer 2.0s handler
                     # timeout envelope in ZMQCommandServer._run_handler(); this inner 1.5s wrapper
                     # only gives faster client feedback and frees the REP loop earlier. There is
                     # no safe way to terminate a Python thread mid-call, so Option C
                     # ("actually interrupt") is not available. See Codex commit-7 review.
                     try:
                         result = await asyncio.wait_for(
                             experiment_call,
                             timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                         )
                     except TimeoutError as exc:
                         raise TimeoutError(
                             f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)"
                         ) from exc
                 else:
                     result = await experiment_call
                 # Hook calibration acquisition on experiment lifecycle
                 if result.get("ok") and action in {"experiment_start", "experiment_create"}:
                     await asyncio.to_thread(
                         _try_activate_calibration_acquisition,
                         calibration_acquisition,
                         experiment_manager,
                         cmd,
                     )
                     name = cmd.get("name") or cmd.get("title") or "?"
                     await event_logger.log_event("experiment", f"Эксперимент начат: {name}")
+                    await event_bus.publish(
+                        EngineEvent(
+                            event_type="experiment_start",
+                            timestamp=datetime.now(UTC),
+                            payload={"name": name, "experiment_id": result.get("experiment_id")},
+                            experiment_id=result.get("experiment_id"),
+                        )
+                    )
                 elif result.get("ok") and action in {
                     "experiment_finalize",
                     "experiment_stop",
                     "experiment_abort",
                 }:
                     calibration_acquisition.deactivate()
                     if action == "experiment_abort":
                         await event_logger.log_event("experiment", "\u26a0 Эксперимент прерван")
                     else:
                         await event_logger.log_event("experiment", "Эксперимент завершён")
+                    _exp_info = result.get("experiment", {})
+                    await event_bus.publish(
+                        EngineEvent(
+                            event_type=action,
+                            timestamp=datetime.now(UTC),
+                            payload={"action": action, "experiment": _exp_info},
+                            experiment_id=_exp_info.get("experiment_id"),
+                        )
+                    )
                 elif result.get("ok") and action == "experiment_advance_phase":
                     phase = cmd.get("phase", "?")
                     await event_logger.log_event("phase", f"Фаза: → {phase}")
+                    _active = experiment_manager.active_experiment
+                    await event_bus.publish(
+                        EngineEvent(
+                            event_type="phase_transition",
+                            timestamp=datetime.now(UTC),
+                            payload={"phase": phase, "entry": result.get("phase", {})},
+                            experiment_id=_active.experiment_id if _active else None,
+                        )
+                    )
                 return result
             if action == "calibration_acquisition_status":
                 return {"ok": True, **calibration_acquisition.stats}
             if action in {
                 "calibration_v2_extract",
                 "calibration_v2_fit",
                 "calibration_v2_coverage",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_v2_command,
                     action,
                     cmd,
                     calibration_store,
                 )
             if action == "readings_history":
                 channels_raw = cmd.get("channels")
                 channels = list(channels_raw) if channels_raw else None
                 from_ts = cmd.get("from_ts")
                 to_ts = cmd.get("to_ts")
                 limit = int(cmd.get("limit_per_channel", 3600))
                 data = await writer.read_readings_history(
                     channels=channels,
                     from_ts=float(from_ts) if from_ts is not None else None,
                     to_ts=float(to_ts) if to_ts is not None else None,
                     limit_per_channel=limit,
                 )
                 # Serialize: {channel: [[ts, value], ...]}
                 return {
                     "ok": True,
                     "data": {ch: pts for ch, pts in data.items()},
                 }
             if action == "cooldown_history_get":
                 return await _run_cooldown_history_command(
                     cmd, experiment_manager, writer
                 )
             if action in {"log_entry", "log_get"}:
                 return await _run_operator_log_command(
                     action,
                     cmd,
                     writer,
                     experiment_manager,
                     broker,
                 )
             if action in {
                 "calibration_curve_evaluate",
                 "calibration_curve_list",
                 "calibration_curve_get",
                 "calibration_curve_lookup",
                 "calibration_curve_assign",
                 "calibration_runtime_status",
                 "calibration_runtime_set_global",
                 "calibration_runtime_set_channel_policy",
                 "calibration_curve_export",
                 "calibration_curve_import",
             }:
                 return await asyncio.to_thread(
                     _run_calibration_command,
                     action,
                     cmd,
                     calibration_store=calibration_store,
                     experiment_manager=experiment_manager,
                     drivers_by_name=drivers_by_name,
                 )
             if action == "get_sensor_diagnostics":
                 if sensor_diag is None:
                     return {"ok": False, "error": "SensorDiagnostics отключён"}
                 from dataclasses import asdict
 
                 diag = sensor_diag.get_diagnostics()
                 summary = sensor_diag.get_summary()
                 return {
                     "ok": True,
                     "channels": {k: asdict(v) for k, v in diag.items()},
                     "summary": asdict(summary),
                 }
             if action == "get_vacuum_trend":
                 if vacuum_trend is None:
                     return {"ok": False, "error": "VacuumTrendPredictor отключён"}
                 from dataclasses import asdict
 
                 pred = vacuum_trend.get_prediction()
                 if pred is None:
                     return {"ok": True, "status": "no_data"}
                 return {"ok": True, **asdict(pred)}
+            if action == "shift_handover_summary":
+                _sh_active = experiment_manager.active_experiment
+                await event_bus.publish(
+                    EngineEvent(
+                        event_type="shift_handover_request",
+                        timestamp=datetime.now(UTC),
+                        payload={
+                            "requested_by": cmd.get("operator", ""),
+                            "shift_duration_h": int(cmd.get("shift_duration_h", 8)),
+                        },
+                        experiment_id=_sh_active.experiment_id if _sh_active else None,
+                    )
+                )
+                return {"ok": True, "status": "queued"}
             return {"ok": False, "error": f"unknown command: {action}"}
         except Exception as exc:
             logger.error("Ошибка выполнения команды '%s': %s", action, exc)
             return {"ok": False, "error": str(exc)}
 
     cmd_server = ZMQCommandServer(handler=_handle_gui_command)
 
     # Plugin Pipeline
     plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)
 
     # --- CooldownService (прогноз охлаждения) ---
     cooldown_service: Any = None
     cooldown_cfg_path = _cfg("cooldown")
     if cooldown_cfg_path.exists():
         try:
             with cooldown_cfg_path.open(encoding="utf-8") as fh:
                 _cd_raw = yaml.safe_load(fh) or {}
             _cd_cfg = _cd_raw.get("cooldown", {})
             if _cd_cfg.get("enabled", False):
                 from cryodaq.analytics.cooldown_service import CooldownService
 
                 cooldown_service = CooldownService(
                     broker=broker,
                     config=_cd_cfg,
                     model_dir=_PROJECT_ROOT / _cd_cfg.get("model_dir", "data/cooldown_model"),
                 )
                 logger.info("CooldownService создан")
         except Exception as exc:
             logger.error("Ошибка создания CooldownService: %s", exc)
 
     # --- Уведомления (один раз разбираем YAML) ---
     periodic_reporter: PeriodicReporter | None = None
     telegram_bot: TelegramCommandBot | None = None
     escalation_service: EscalationService | None = None
     notifications_cfg = _cfg("notifications")
     if notifications_cfg.exists():
         try:
             with notifications_cfg.open(encoding="utf-8") as fh:
                 notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}
 
             tg_cfg = notif_raw.get("telegram", {})
             bot_token = str(tg_cfg.get("bot_token", ""))
             token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
 
             # PeriodicReporter
             pr_cfg = notif_raw.get("periodic_report", {})
             if pr_cfg.get("enabled", False) and token_valid:
                 periodic_reporter = PeriodicReporter(
                     broker,
                     alarm_engine,
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                     report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                     chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                     include_channels=pr_cfg.get("include_channels"),
                 )
                 logger.info("PeriodicReporter создан")
 
             # TelegramCommandBot
             cmd_cfg = notif_raw.get("commands", {})
             commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
             if commands_enabled:
                 allowed_raw = (
                     tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
                 )
                 allowed_ids = [int(x) for x in allowed_raw]
                 # Phase 2b Codex K.1 — TelegramCommandBot raises on empty list,
                 # so refuse to enable cleanly here with a config-error log
                 # rather than letting the constructor surface an exception
                 # mid-startup.
                 if not allowed_ids:
                     logger.error(
                         "Telegram commands are enabled but allowed_chat_ids "
                         "is empty. Refusing to start TelegramCommandBot. "
                         "Add at least one chat ID or set commands.enabled: false."
                     )
                 else:
                     telegram_bot = TelegramCommandBot(
                         broker,
                         alarm_engine,
                         bot_token=bot_token,
                         allowed_chat_ids=allowed_ids,
                         poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                         command_handler=_handle_gui_command,
                     )
                     logger.info(
                         "TelegramCommandBot создан (allowed=%d chat ids)",
                         len(allowed_ids),
                     )
 
             # EscalationService
             if token_valid and notif_raw.get("escalation"):
                 from cryodaq.notifications.telegram import TelegramNotifier
 
                 _esc_notifier = TelegramNotifier(
                     bot_token=bot_token,
                     chat_id=tg_cfg.get("chat_id", 0),
                 )
                 escalation_service = EscalationService(_esc_notifier, notif_raw)
                 logger.info("EscalationService создан (%d уровней)", len(notif_raw["escalation"]))
 
             if not token_valid:
                 logger.info("Telegram-уведомления отключены (bot_token не настроен)")
         except Exception as exc:
             logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
     else:
         logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)
 
+    # --- AssistantLiveAgent (Гемма local LLM agent) ---
+    _agent_cfg_path = _CONFIG_DIR / "agent.yaml"
+    _gemma_config: AssistantConfig | None = None
+    gemma_agent: AssistantLiveAgent | None = None
+    if _agent_cfg_path.exists():
+        try:
+            _gemma_config = AssistantConfig.from_yaml_path(_agent_cfg_path)
+            if _gemma_config.enabled:
+                _gemma_ollama = OllamaClient(
+                    base_url=_gemma_config.ollama_base_url,
+                    default_model=_gemma_config.default_model,
+                    timeout_s=_gemma_config.timeout_s,
+                )
+                _gemma_ctx = ContextBuilder(writer, experiment_manager)
+                _gemma_audit = AuditLogger(
+                    _DATA_DIR / "agents" / "assistant" / "audit",
+                    enabled=_gemma_config.audit_enabled,
+                    retention_days=_gemma_config.audit_retention_days,
+                )
+                _gemma_router = OutputRouter(
+                    telegram_bot=telegram_bot,
+                    event_logger=event_logger,
+                    event_bus=event_bus,
+                    brand_name=_gemma_config.brand_name,
+                    brand_emoji=_gemma_config.brand_emoji,
+                )
+                gemma_agent = AssistantLiveAgent(
+                    config=_gemma_config,
+                    event_bus=event_bus,
+                    ollama_client=_gemma_ollama,
+                    context_builder=_gemma_ctx,
+                    audit_logger=_gemma_audit,
+                    output_router=_gemma_router,
+                )
+                logger.info(
+                    "AssistantLiveAgent (Гемма): инициализирован, модель=%s",
+                    _gemma_config.default_model,
+                )
+        except Exception as _gemma_exc:
+            logger.warning("AssistantLiveAgent: ошибка инициализации — %s", _gemma_exc, exc_info=True)
+    else:
+        logger.info("AssistantLiveAgent: config/agent.yaml не найден, агент отключён")
+
     # --- Запуск всех подсистем ---
     await safety_manager.start()
     logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
     # writer уже запущен через start_immediate() выше
     await zmq_pub.start(zmq_queue)
     await cmd_server.start()
     await alarm_engine.start()
     await interlock_engine.start()
     await plugin_pipeline.start()
     if cooldown_service is not None:
         await cooldown_service.start()
     if periodic_reporter is not None:
         await periodic_reporter.start()
     if telegram_bot is not None:
         await telegram_bot.start()
+    if gemma_agent is not None:
+        try:
+            await gemma_agent.start()
+        except Exception as _gemma_start_exc:
+            logger.warning("AssistantLiveAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
+            gemma_agent = None
+    periodic_report_tick_task: asyncio.Task | None = None
+    if _gemma_config is not None and _gemma_config.periodic_report_enabled:
+        periodic_report_tick_task = asyncio.create_task(
+            _periodic_report_tick(_gemma_config, event_bus, experiment_manager),
+            name="periodic_report_tick",
+        )
     await scheduler.start()
     throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
     alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
     alarm_v2_tick_task: asyncio.Task | None = None
     if _alarm_v2_configs:
         alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
     sd_feed_task: asyncio.Task | None = None
     sd_tick_task: asyncio.Task | None = None
     if sensor_diag is not None:
         sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
         sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
     vt_feed_task: asyncio.Task | None = None
     vt_tick_task: asyncio.Task | None = None
     if vacuum_trend is not None:
         vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
         vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
     leak_rate_feed_task = asyncio.create_task(_leak_rate_feed(), name="leak_rate_feed")
     await housekeeping_service.start()
 
     # Watchdog
     watchdog_task = asyncio.create_task(
         _watchdog(broker, scheduler, writer, start_ts),
         name="engine_watchdog",
     )
 
     # DiskMonitor — also wires the writer so disk-recovery can clear the
     # _disk_full flag (Phase 2a H.1).
     disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
     await disk_monitor.start()
 
     logger.info(
         "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
         len(driver_configs),
         len(alarm_engine.get_state()),
         len(interlock_engine.get_state()),
         mock,
     )
 
     # --- Ожидание сигнала завершения ---
     shutdown_event = asyncio.Event()
 
     def _request_shutdown() -> None:
         logger.info("Получен сигнал завершения")
         shutdown_event.set()
 
     # Регистрация обработчиков сигналов
     loop = asyncio.get_running_loop()
     if sys.platform != "win32":
         loop.add_signal_handler(signal.SIGINT, _request_shutdown)
         loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
     else:
         # Windows: signal.signal работает только в главном потоке
         signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
 
     await shutdown_event.wait()
 
     # --- Корректное завершение ---
     logger.info("═══ Завершение CryoDAQ Engine ═══")
 
     watchdog_task.cancel()
     try:
         await watchdog_task
     except asyncio.CancelledError:
         pass
 
     throttle_task.cancel()
     try:
         await throttle_task
     except asyncio.CancelledError:
         pass
 
     alarm_v2_feed_task.cancel()
     try:
         await alarm_v2_feed_task
     except asyncio.CancelledError:
         pass
     if alarm_v2_tick_task is not None:
         alarm_v2_tick_task.cancel()
         try:
             await alarm_v2_tick_task
         except asyncio.CancelledError:
             pass
 
     if sd_feed_task is not None:
         sd_feed_task.cancel()
         try:
             await sd_feed_task
         except asyncio.CancelledError:
             pass
     if sd_tick_task is not None:
         sd_tick_task.cancel()
         try:
             await sd_tick_task
         except asyncio.CancelledError:
             pass
 
     if vt_feed_task is not None:
         vt_feed_task.cancel()
         try:
             await vt_feed_task
         except asyncio.CancelledError:
             pass
     if vt_tick_task is not None:
         vt_tick_task.cancel()
         try:
             await vt_tick_task
         except asyncio.CancelledError:
             pass
+    if periodic_report_tick_task is not None:
+        periodic_report_tick_task.cancel()
+        try:
+            await periodic_report_tick_task
+        except asyncio.CancelledError:
+            pass
     leak_rate_feed_task.cancel()
     try:
         await leak_rate_feed_task
     except asyncio.CancelledError:
         pass
 
     # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
     await scheduler.stop()
     logger.info("Планировщик остановлен")
 
     await plugin_pipeline.stop()
     logger.info("Пайплайн плагинов остановлен")
 
     if cooldown_service is not None:
         await cooldown_service.stop()
         logger.info("CooldownService остановлен")
 
     if periodic_reporter is not None:
         await periodic_reporter.stop()
         logger.info("PeriodicReporter остановлен")
 
+    if gemma_agent is not None:
+        await gemma_agent.stop()
+        logger.info("AssistantLiveAgent (Гемма) остановлен")
+
     if telegram_bot is not None:
         await telegram_bot.stop()
         logger.info("TelegramCommandBot остановлен")
 
     await alarm_engine.stop()
     logger.info("Движок тревог остановлен")
 
     await interlock_engine.stop()
     logger.info("Движок блокировок остановлен")
 
     await safety_manager.stop()
     logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
 
     await disk_monitor.stop()
     logger.info("DiskMonitor остановлен")
 
     await housekeeping_service.stop()
     logger.info("HousekeepingService остановлен")
 
     await writer.stop()
     logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
 
     await cmd_server.stop()
     logger.info("ZMQ CommandServer остановлен")
 
     await zmq_pub.stop()
     logger.info("ZMQ Publisher остановлен")
 
     from cryodaq.drivers.transport.gpib import GPIBTransport
 
     GPIBTransport.close_all_managers()
     logger.info("GPIB ResourceManagers закрыты")
 
     uptime = time.monotonic() - start_ts
     logger.info(
         "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
         uptime,
     )
 
 
 # ---------------------------------------------------------------------------
 # Single-instance guard
 # ---------------------------------------------------------------------------
 
 _LOCK_FILE = get_data_dir() / ".engine.lock"
 
 
 def _is_pid_alive(pid: int) -> bool:
     """Check if process with given PID exists."""
     try:
         if sys.platform == "win32":
             import ctypes
 
             handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
             if handle:
                 ctypes.windll.kernel32.CloseHandle(handle)
                 return True
             return False
         else:
             os.kill(pid, 0)
             return True
     except (OSError, ProcessLookupError):
         return False
 
 
 def _acquire_engine_lock() -> int:
     """Acquire exclusive engine lock via flock/msvcrt. Returns fd.
 
     If lock is held by a dead process, auto-cleans and retries.
     Shows helpful error with PID and kill command if lock is live.
     """
     _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
     fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
     try:
         if sys.platform == "win32":
             import msvcrt
 
             msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
         else:
             import fcntl

codex
The checkout itself is on `master` with unrelated dirty files, so I’m reviewing the target branch via `git show`/`git diff` rather than switching branches. That keeps the workspace untouched and still gives exact branch line numbers.
exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/engine.py | nl -ba | sed -n '80,150p;1790,1870p;1950,1995p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    80	
    81	logger = logging.getLogger("cryodaq.engine")
    82	
    83	# ---------------------------------------------------------------------------
    84	# Пути по умолчанию (относительно корня проекта)
    85	# ---------------------------------------------------------------------------
    86	
    87	_PROJECT_ROOT = get_project_root()
    88	_CONFIG_DIR = get_config_dir()
    89	_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
    90	_DATA_DIR = get_data_dir()
    91	
    92	# Интервал самодиагностики (секунды)
    93	_WATCHDOG_INTERVAL_S = 30.0
    94	_LOG_GET_TIMEOUT_S = 1.5
    95	_EXPERIMENT_STATUS_TIMEOUT_S = 1.5
    96	
    97	
    98	async def _periodic_report_tick(
    99	    agent_config: AssistantConfig,
   100	    event_bus: EventBus,
   101	    experiment_manager: ExperimentManager,
   102	    *,
   103	    sleep=asyncio.sleep,
   104	) -> None:
   105	    """Publish periodic_report_request events on the assistant schedule."""
   106	    interval_s = float(agent_config.get_periodic_report_interval_s())
   107	    if interval_s <= 0:
   108	        logger.info("Periodic assistant reports disabled (interval=0)")
   109	        return
   110	
   111	    window_minutes = int(agent_config.periodic_report_interval_minutes)
   112	    while True:
   113	        await sleep(interval_s)
   114	        try:
   115	            experiment_id = getattr(experiment_manager, "active_experiment_id", None)
   116	            if experiment_id is None:
   117	                active = getattr(experiment_manager, "active_experiment", None)
   118	                experiment_id = getattr(active, "experiment_id", None) if active else None
   119	            await event_bus.publish(
   120	                EngineEvent(
   121	                    event_type="periodic_report_request",
   122	                    timestamp=datetime.now(UTC),
   123	                    payload={
   124	                        "window_minutes": window_minutes,
   125	                        "trigger": "scheduled",
   126	                    },
   127	                    experiment_id=experiment_id,
   128	                )
   129	            )
   130	        except Exception as exc:
   131	            logger.error("Periodic assistant report tick error: %s", exc)
   132	
   133	
   134	async def _run_keithley_command(
   135	    action: str,
   136	    cmd: dict[str, Any],
   137	    safety_manager: SafetyManager,
   138	) -> dict[str, Any]:
   139	    """Dispatch channel-scoped Keithley commands to SafetyManager."""
   140	    channel = cmd.get("channel")
   141	
   142	    if action == "keithley_start":
   143	        smu_channel = normalize_smu_channel(channel)
   144	        p = float(cmd.get("p_target", 0))
   145	        v = float(cmd.get("v_comp", 40))
   146	        i = float(cmd.get("i_comp", 1.0))
   147	        return await safety_manager.request_run(p, v, i, channel=smu_channel)
   148	
   149	    if action == "keithley_stop":
   150	        smu_channel = normalize_smu_channel(channel)
  1790	                    _run_calibration_command,
  1791	                    action,
  1792	                    cmd,
  1793	                    calibration_store=calibration_store,
  1794	                    experiment_manager=experiment_manager,
  1795	                    drivers_by_name=drivers_by_name,
  1796	                )
  1797	            if action == "get_sensor_diagnostics":
  1798	                if sensor_diag is None:
  1799	                    return {"ok": False, "error": "SensorDiagnostics отключён"}
  1800	                from dataclasses import asdict
  1801	
  1802	                diag = sensor_diag.get_diagnostics()
  1803	                summary = sensor_diag.get_summary()
  1804	                return {
  1805	                    "ok": True,
  1806	                    "channels": {k: asdict(v) for k, v in diag.items()},
  1807	                    "summary": asdict(summary),
  1808	                }
  1809	            if action == "get_vacuum_trend":
  1810	                if vacuum_trend is None:
  1811	                    return {"ok": False, "error": "VacuumTrendPredictor отключён"}
  1812	                from dataclasses import asdict
  1813	
  1814	                pred = vacuum_trend.get_prediction()
  1815	                if pred is None:
  1816	                    return {"ok": True, "status": "no_data"}
  1817	                return {"ok": True, **asdict(pred)}
  1818	            if action == "shift_handover_summary":
  1819	                _sh_active = experiment_manager.active_experiment
  1820	                await event_bus.publish(
  1821	                    EngineEvent(
  1822	                        event_type="shift_handover_request",
  1823	                        timestamp=datetime.now(UTC),
  1824	                        payload={
  1825	                            "requested_by": cmd.get("operator", ""),
  1826	                            "shift_duration_h": int(cmd.get("shift_duration_h", 8)),
  1827	                        },
  1828	                        experiment_id=_sh_active.experiment_id if _sh_active else None,
  1829	                    )
  1830	                )
  1831	                return {"ok": True, "status": "queued"}
  1832	            return {"ok": False, "error": f"unknown command: {action}"}
  1833	        except Exception as exc:
  1834	            logger.error("Ошибка выполнения команды '%s': %s", action, exc)
  1835	            return {"ok": False, "error": str(exc)}
  1836	
  1837	    cmd_server = ZMQCommandServer(handler=_handle_gui_command)
  1838	
  1839	    # Plugin Pipeline
  1840	    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)
  1841	
  1842	    # --- CooldownService (прогноз охлаждения) ---
  1843	    cooldown_service: Any = None
  1844	    cooldown_cfg_path = _cfg("cooldown")
  1845	    if cooldown_cfg_path.exists():
  1846	        try:
  1847	            with cooldown_cfg_path.open(encoding="utf-8") as fh:
  1848	                _cd_raw = yaml.safe_load(fh) or {}
  1849	            _cd_cfg = _cd_raw.get("cooldown", {})
  1850	            if _cd_cfg.get("enabled", False):
  1851	                from cryodaq.analytics.cooldown_service import CooldownService
  1852	
  1853	                cooldown_service = CooldownService(
  1854	                    broker=broker,
  1855	                    config=_cd_cfg,
  1856	                    model_dir=_PROJECT_ROOT / _cd_cfg.get("model_dir", "data/cooldown_model"),
  1857	                )
  1858	                logger.info("CooldownService создан")
  1859	        except Exception as exc:
  1860	            logger.error("Ошибка создания CooldownService: %s", exc)
  1861	
  1862	    # --- Уведомления (один раз разбираем YAML) ---
  1863	    periodic_reporter: PeriodicReporter | None = None
  1864	    telegram_bot: TelegramCommandBot | None = None
  1865	    escalation_service: EscalationService | None = None
  1866	    notifications_cfg = _cfg("notifications")
  1867	    if notifications_cfg.exists():
  1868	        try:
  1869	            with notifications_cfg.open(encoding="utf-8") as fh:
  1870	                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}
  1950	                    default_model=_gemma_config.default_model,
  1951	                    timeout_s=_gemma_config.timeout_s,
  1952	                )
  1953	                _gemma_ctx = ContextBuilder(writer, experiment_manager)
  1954	                _gemma_audit = AuditLogger(
  1955	                    _DATA_DIR / "agents" / "assistant" / "audit",
  1956	                    enabled=_gemma_config.audit_enabled,
  1957	                    retention_days=_gemma_config.audit_retention_days,
  1958	                )
  1959	                _gemma_router = OutputRouter(
  1960	                    telegram_bot=telegram_bot,
  1961	                    event_logger=event_logger,
  1962	                    event_bus=event_bus,
  1963	                    brand_name=_gemma_config.brand_name,
  1964	                    brand_emoji=_gemma_config.brand_emoji,
  1965	                )
  1966	                gemma_agent = AssistantLiveAgent(
  1967	                    config=_gemma_config,
  1968	                    event_bus=event_bus,
  1969	                    ollama_client=_gemma_ollama,
  1970	                    context_builder=_gemma_ctx,
  1971	                    audit_logger=_gemma_audit,
  1972	                    output_router=_gemma_router,
  1973	                )
  1974	                logger.info(
  1975	                    "AssistantLiveAgent (Гемма): инициализирован, модель=%s",
  1976	                    _gemma_config.default_model,
  1977	                )
  1978	        except Exception as _gemma_exc:
  1979	            logger.warning("AssistantLiveAgent: ошибка инициализации — %s", _gemma_exc, exc_info=True)
  1980	    else:
  1981	        logger.info("AssistantLiveAgent: config/agent.yaml не найден, агент отключён")
  1982	
  1983	    # --- Запуск всех подсистем ---
  1984	    await safety_manager.start()
  1985	    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
  1986	    # writer уже запущен через start_immediate() выше
  1987	    await zmq_pub.start(zmq_queue)
  1988	    await cmd_server.start()
  1989	    await alarm_engine.start()
  1990	    await interlock_engine.start()
  1991	    await plugin_pipeline.start()
  1992	    if cooldown_service is not None:
  1993	        await cooldown_service.start()
  1994	    if periodic_reporter is not None:
  1995	        await periodic_reporter.start()

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/agent.py | nl -ba | sed -n '90,190p;210,340p;610,740p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
    90	
    91	    @classmethod
    92	    def from_dict(cls, d: dict[str, Any]) -> AssistantConfig:
    93	        """Build from agent.yaml agent section dict."""
    94	        cfg = cls()
    95	        cfg.enabled = bool(d.get("enabled", True))
    96	        ollama = d.get("ollama", {})
    97	        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
    98	        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
    99	        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
   100	        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
   101	        _num_ctx = ollama.get("num_ctx")
   102	        cfg.num_ctx = int(_num_ctx) if _num_ctx is not None else None
   103	        rl = d.get("rate_limit", {})
   104	        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
   105	        cfg.max_concurrent_inferences = int(
   106	            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
   107	        )
   108	        triggers = d.get("triggers", {})
   109	        alarm_t = triggers.get("alarm_fired", {})
   110	        if isinstance(alarm_t, dict):
   111	            cfg.alarm_fired_enabled = bool(alarm_t.get("enabled", cfg.alarm_fired_enabled))
   112	            raw_level = str(alarm_t.get("min_level", cfg.alarm_min_level)).upper()
   113	            if raw_level not in _MIN_LEVELS:
   114	                raise ValueError(
   115	                    f"alarm_min_level must be one of {list(_MIN_LEVELS)}, got {raw_level!r}"
   116	                )
   117	            cfg.alarm_min_level = raw_level
   118	        exp_t = triggers.get("experiment_finalize", {})
   119	        if isinstance(exp_t, dict):
   120	            cfg.experiment_finalize_enabled = bool(
   121	                exp_t.get("enabled", cfg.experiment_finalize_enabled)
   122	            )
   123	        sa_t = triggers.get("sensor_anomaly_critical", {})
   124	        if isinstance(sa_t, dict):
   125	            cfg.sensor_anomaly_critical_enabled = bool(
   126	                sa_t.get("enabled", cfg.sensor_anomaly_critical_enabled)
   127	            )
   128	        sh_t = triggers.get("shift_handover_request", {})
   129	        if isinstance(sh_t, dict):
   130	            cfg.shift_handover_request_enabled = bool(
   131	                sh_t.get("enabled", cfg.shift_handover_request_enabled)
   132	            )
   133	        pr_t = triggers.get("periodic_report", {})
   134	        if isinstance(pr_t, dict):
   135	            cfg.periodic_report_enabled = bool(pr_t.get("enabled", cfg.periodic_report_enabled))
   136	            cfg.periodic_report_interval_minutes = int(
   137	                pr_t.get("interval_minutes", cfg.periodic_report_interval_minutes)
   138	            )
   139	            cfg.periodic_report_skip_if_idle = bool(
   140	                pr_t.get("skip_if_idle", cfg.periodic_report_skip_if_idle)
   141	            )
   142	            cfg.periodic_report_min_events = int(
   143	                pr_t.get("min_events_for_dispatch", cfg.periodic_report_min_events)
   144	            )
   145	        outputs = d.get("outputs", {})
   146	        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
   147	        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
   148	        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
   149	        slices = d.get("slices", {})
   150	        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
   151	        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
   152	        cfg.slice_c_campaign_report = bool(
   153	            slices.get("c_campaign_report", cfg.slice_c_campaign_report)
   154	        )
   155	        audit = d.get("audit", {})
   156	        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
   157	        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
   158	        cfg.brand_name = str(d.get("brand_name", cfg.brand_name))
   159	        cfg.brand_emoji = str(d.get("brand_emoji", cfg.brand_emoji))
   160	        return cfg
   161	
   162	    @classmethod
   163	    def from_yaml_string(cls, content: str) -> AssistantConfig:
   164	        """Load from YAML string; handles agent.* and legacy gemma.* namespaces."""
   165	        import yaml  # noqa: PLC0415
   166	        raw = yaml.safe_load(content) or {}
   167	        return cls._from_raw(raw)
   168	
   169	    @classmethod
   170	    def from_yaml_path(cls, path: Path) -> AssistantConfig:
   171	        """Load from agent.yaml file; handles agent.* and legacy gemma.* namespaces."""
   172	        import yaml  # noqa: PLC0415
   173	        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
   174	        return cls._from_raw(raw)
   175	
   176	    @classmethod
   177	    def _from_raw(cls, raw: dict) -> AssistantConfig:
   178	        if "agent" in raw:
   179	            return cls.from_dict(raw["agent"])
   180	        if "gemma" in raw:
   181	            logger.warning(
   182	                "AssistantConfig: legacy gemma.* config namespace detected; "
   183	                "please migrate to agent.*. Backward compatibility removed in v0.46.0."
   184	            )
   185	            return cls.from_dict(raw["gemma"])
   186	        return cls()
   187	
   188	
   189	class AssistantLiveAgent:
   190	    """Local LLM agent. Operator-facing brand: Гемма."""
   210	        self._call_timestamps: deque[float] = deque()
   211	        self._handler_tasks: set[asyncio.Task] = set()
   212	        self._task: asyncio.Task[None] | None = None
   213	        self._queue: asyncio.Queue[EngineEvent] | None = None
   214	
   215	    async def start(self) -> None:
   216	        """Subscribe to EventBus and begin event processing."""
   217	        if not self._config.enabled:
   218	            logger.info("AssistantLiveAgent (Гемма): отключён в конфигурации")
   219	            return
   220	        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
   221	        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
   222	        logger.info(
   223	            "AssistantLiveAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
   224	            self._config.default_model,
   225	            self._config.timeout_s,
   226	        )
   227	
   228	    async def stop(self) -> None:
   229	        """Cancel the event loop and in-flight handlers, release resources."""
   230	        if self._task is not None:
   231	            self._task.cancel()
   232	            try:
   233	                await self._task
   234	            except asyncio.CancelledError:
   235	                pass
   236	            self._task = None
   237	        # Cancel in-flight inference tasks to avoid racing with shutdown
   238	        for t in list(self._handler_tasks):
   239	            t.cancel()
   240	        for t in list(self._handler_tasks):
   241	            try:
   242	                await t
   243	            except asyncio.CancelledError:
   244	                pass
   245	        if self._queue is not None:
   246	            self._bus.unsubscribe("gemma_agent")
   247	            self._queue = None
   248	        await self._ollama.close()
   249	        logger.info("AssistantLiveAgent (Гемма): остановлен")
   250	
   251	    async def _event_loop(self) -> None:
   252	        """Drain the EventBus queue and dispatch handlers."""
   253	        assert self._queue is not None
   254	        while True:
   255	            try:
   256	                event = await self._queue.get()
   257	                if self._should_handle(event):
   258	                    t = asyncio.create_task(
   259	                        self._safe_handle(event),
   260	                        name=f"gemma_{event.event_type}",
   261	                    )
   262	                    self._handler_tasks.add(t)
   263	                    t.add_done_callback(self._handler_tasks.discard)
   264	            except asyncio.CancelledError:
   265	                return
   266	            except Exception:
   267	                logger.warning("AssistantLiveAgent: event loop error", exc_info=True)
   268	
   269	    def _should_handle(self, event: EngineEvent) -> bool:
   270	        if not self._config.slice_a_notification:
   271	            return False
   272	        if event.event_type == "alarm_fired":
   273	            if not self._config.alarm_fired_enabled:
   274	                return False
   275	            level = event.payload.get("level", "INFO")
   276	            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
   277	                self._config.alarm_min_level, 1
   278	            )
   279	        if event.event_type in {"experiment_finalize", "experiment_stop", "experiment_abort"}:
   280	            return self._config.experiment_finalize_enabled
   281	        if event.event_type == "sensor_anomaly_critical":
   282	            return self._config.sensor_anomaly_critical_enabled
   283	        if event.event_type == "shift_handover_request":
   284	            return self._config.shift_handover_request_enabled
   285	        if event.event_type == "periodic_report_request":
   286	            return self._config.periodic_report_enabled
   287	        return False
   288	
   289	    def _check_rate_limit(self) -> bool:
   290	        """True if we can make a call now (hourly bucket)."""
   291	        now = time.monotonic()
   292	        cutoff = now - 3600.0
   293	        while self._call_timestamps and self._call_timestamps[0] < cutoff:
   294	            self._call_timestamps.popleft()
   295	        return len(self._call_timestamps) < self._config.max_calls_per_hour
   296	
   297	    async def _safe_handle(self, event: EngineEvent) -> None:
   298	        """Handle one event with rate-limit + semaphore + error isolation."""
   299	        if not self._check_rate_limit():
   300	            logger.warning(
   301	                "AssistantLiveAgent: rate limit reached (%d/hr), dropping %s",
   302	                self._config.max_calls_per_hour,
   303	                event.event_type,
   304	            )
   305	            return
   306	
   307	        async with self._semaphore:
   308	            self._call_timestamps.append(time.monotonic())
   309	            try:
   310	                if event.event_type in {
   311	                    "experiment_finalize",
   312	                    "experiment_stop",
   313	                    "experiment_abort",
   314	                }:
   315	                    await self._handle_experiment_finalize(event)
   316	                elif event.event_type == "sensor_anomaly_critical":
   317	                    await self._handle_sensor_anomaly(event)
   318	                elif event.event_type == "shift_handover_request":
   319	                    await self._handle_shift_handover(event)
   320	                elif event.event_type == "periodic_report_request":
   321	                    await self._handle_periodic_report(event)
   322	                else:
   323	                    await self._handle_alarm_fired(event)
   324	            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
   325	                logger.warning("AssistantLiveAgent: Ollama недоступен — %s", exc)
   326	            except Exception:
   327	                logger.warning(
   328	                    "AssistantLiveAgent: ошибка обработки %s", event.event_type, exc_info=True
   329	                )
   330	
   331	    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
   332	        audit_id = self._audit.make_audit_id()
   333	        payload = event.payload
   334	
   335	        ctx = await self._ctx_builder.build_alarm_context(payload)
   336	        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
   337	        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
   338	        age_str = _format_age(ctx.experiment_age_s)
   339	
   340	        user_prompt = ALARM_SUMMARY_USER.format(
   610	            prompt_template="sensor_anomaly",
   611	            model=result.model,
   612	            system_prompt=system_prompt,
   613	            user_prompt=user_prompt,
   614	            response=result.text,
   615	            tokens={"in": result.tokens_in, "out": result.tokens_out},
   616	            latency_s=result.latency_s,
   617	            outputs_dispatched=dispatched_sa,
   618	            errors=errors,
   619	        )
   620	        logger.info(
   621	            "AssistantLiveAgent: sensor_anomaly_critical обработан "
   622	            "(audit_id=%s, latency=%.1fs, channel=%s)",
   623	            audit_id,
   624	            result.latency_s,
   625	            ctx.channel,
   626	        )
   627	        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
   628	            await self._generate_diagnostic_suggestion(event, payload)
   629	
   630	    async def _handle_shift_handover(self, event: EngineEvent) -> None:
   631	        audit_id = self._audit.make_audit_id()
   632	        payload = event.payload
   633	
   634	        ctx = await self._ctx_builder.build_shift_handover_context(payload)
   635	        user_prompt = SHIFT_HANDOVER_USER.format(
   636	            experiment_id=ctx.experiment_id or "нет активного эксперимента",
   637	            phase=ctx.phase or "—",
   638	            experiment_age=ctx.experiment_age,
   639	            active_alarms=ctx.active_alarms,
   640	            recent_events=ctx.recent_events,
   641	            shift_duration_h=ctx.shift_duration_h,
   642	        )
   643	
   644	        system_prompt = format_with_brand(SHIFT_HANDOVER_SYSTEM, self._config.brand_name)
   645	        result = await self._ollama.generate(
   646	            user_prompt,
   647	            system=system_prompt,
   648	            max_tokens=self._config.max_tokens,
   649	            temperature=self._config.temperature,
   650	            num_ctx=self._config.num_ctx,
   651	        )
   652	
   653	        errors: list[str] = []
   654	        if result.truncated:
   655	            errors.append("timeout_truncated")
   656	            logger.warning(
   657	                "AssistantLiveAgent: ответ обрезан (shift_handover, audit_id=%s)", audit_id
   658	            )
   659	
   660	        targets = _build_targets(self._config)
   661	        if result.truncated or not result.text.strip():
   662	            logger.warning(
   663	                "AssistantLiveAgent: пустой ответ shift_handover (audit_id=%s)", audit_id
   664	            )
   665	            dispatched_sh: list[str] = []
   666	        else:
   667	            dispatched_sh = await self._router.dispatch(
   668	                event, result.text, targets=targets, audit_id=audit_id
   669	            )
   670	
   671	        await self._audit.log(
   672	            audit_id=audit_id,
   673	            trigger_event={
   674	                "event_type": event.event_type,
   675	                "payload": payload,
   676	                "experiment_id": event.experiment_id,
   677	            },
   678	            context_assembled=user_prompt,
   679	            prompt_template="shift_handover",
   680	            model=result.model,
   681	            system_prompt=system_prompt,
   682	            user_prompt=user_prompt,
   683	            response=result.text,
   684	            tokens={"in": result.tokens_in, "out": result.tokens_out},
   685	            latency_s=result.latency_s,
   686	            outputs_dispatched=dispatched_sh,
   687	            errors=errors,
   688	        )
   689	        logger.info(
   690	            "AssistantLiveAgent: shift_handover_request обработан (audit_id=%s, latency=%.1fs)",
   691	            audit_id,
   692	            result.latency_s,
   693	        )
   694	
   695	
   696	    async def _handle_periodic_report(self, event: EngineEvent) -> None:
   697	        audit_id = self._audit.make_audit_id()
   698	        window_minutes = int(event.payload.get("window_minutes", 60))
   699	
   700	        ctx = await self._ctx_builder.build_periodic_report_context(
   701	            window_minutes=window_minutes,
   702	        )
   703	
   704	        if (
   705	            self._config.periodic_report_skip_if_idle
   706	            and ctx.total_event_count < self._config.periodic_report_min_events
   707	        ):
   708	            logger.debug(
   709	                "AssistantLiveAgent: periodic report skipped "
   710	                "(idle: %d events < min=%d)",
   711	                ctx.total_event_count,
   712	                self._config.periodic_report_min_events,
   713	            )
   714	            return
   715	
   716	        template_dict = ctx.to_template_dict()
   717	        user_prompt = PERIODIC_REPORT_USER.format(
   718	            window_minutes=window_minutes,
   719	            **template_dict,
   720	        )
   721	        system_prompt = format_with_brand(PERIODIC_REPORT_SYSTEM, self._config.brand_name)
   722	
   723	        result = await self._ollama.generate(
   724	            user_prompt,
   725	            system=system_prompt,
   726	            max_tokens=self._config.max_tokens,
   727	            temperature=self._config.temperature,
   728	            num_ctx=self._config.num_ctx,
   729	        )
   730	
   731	        errors: list[str] = []
   732	        if result.truncated:
   733	            errors.append("timeout_truncated")
   734	            logger.warning(
   735	                "AssistantLiveAgent: periodic report обрезан (audit_id=%s)", audit_id
   736	            )
   737	
   738	        targets = _build_targets(self._config)
   739	        if result.truncated or not result.text.strip():
   740	            logger.warning(

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py | nl -ba | sed -n '280,460p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   280	
   281	def _readings_stub(_channels: list[str], _lookback_s: float) -> str:
   282	    return "нет данных"
   283	
   284	
   285	def _alarms_stub(_lookback_s: float) -> str:
   286	    return "нет данных"
   287	
   288	
   289	# ---------------------------------------------------------------------------
   290	# Experiment finalize context
   291	# ---------------------------------------------------------------------------
   292	
   293	
   294	@dataclass
   295	class ExperimentFinalizeContext:
   296	    """Context for experiment finalize/stop/abort summary (Slice A)."""
   297	
   298	    experiment_id: str | None
   299	    name: str
   300	    action: str
   301	    duration_str: str
   302	    phases_text: str
   303	    alarms_summary_text: str
   304	
   305	
   306	# ---------------------------------------------------------------------------
   307	# Sensor anomaly context
   308	# ---------------------------------------------------------------------------
   309	
   310	
   311	@dataclass
   312	class SensorAnomalyContext:
   313	    """Context for sensor anomaly analysis (Slice A)."""
   314	
   315	    alarm_id: str
   316	    level: str
   317	    channel: str
   318	    channels: list[str]
   319	    values: dict[str, float]
   320	    message: str
   321	    health_score: str
   322	    fault_flags: str
   323	    current_value: str
   324	    experiment_id: str | None
   325	    phase: str | None
   326	
   327	
   328	# ---------------------------------------------------------------------------
   329	# Shift handover context
   330	# ---------------------------------------------------------------------------
   331	
   332	
   333	@dataclass
   334	class ShiftHandoverContext:
   335	    """Context for shift handover summary (Slice A)."""
   336	
   337	    experiment_id: str | None
   338	    phase: str | None
   339	    experiment_age: str
   340	    active_alarms: str
   341	    recent_events: str
   342	    shift_duration_h: int
   343	
   344	
   345	# ---------------------------------------------------------------------------
   346	# Concrete build methods on ContextBuilder
   347	# ---------------------------------------------------------------------------
   348	
   349	
   350	def _build_experiment_finalize_context(
   351	    em: Any, payload: dict[str, Any]
   352	) -> ExperimentFinalizeContext:
   353	    action = payload.get("action", "experiment_finalize")
   354	    experiment = payload.get("experiment", {})
   355	    experiment_id = experiment.get("experiment_id")
   356	    name = experiment.get("name") or experiment.get("title") or "—"
   357	    age_float = _compute_experiment_age(em)
   358	    if age_float is None:
   359	        # Fallback: try to compute from experiment dict
   360	        started = experiment.get("started_at") or experiment.get("created_at")
   361	        if started:
   362	            try:
   363	                from datetime import UTC, datetime
   364	
   365	                start_dt = datetime.fromisoformat(started)
   366	                age_s = (datetime.now(UTC) - start_dt.astimezone(UTC)).total_seconds()
   367	                duration_str = _format_age(age_s)
   368	            except Exception:
   369	                duration_str = "—"
   370	        else:
   371	            duration_str = "—"
   372	    else:
   373	        duration_str = _format_age(age_float)
   374	    phases = experiment.get("phases") or experiment.get("phase_history") or []
   375	    if phases:
   376	        phases_text = "\n".join(
   377	            f"- {p.get('phase', '?')}: {p.get('started_at', '?')}" for p in phases
   378	        )
   379	    else:
   380	        phases_text = "нет данных"
   381	    return ExperimentFinalizeContext(
   382	        experiment_id=experiment_id,
   383	        name=name,
   384	        action=action,
   385	        duration_str=duration_str,
   386	        phases_text=phases_text,
   387	        alarms_summary_text="нет данных",
   388	    )
   389	
   390	
   391	def _build_sensor_anomaly_context(
   392	    em: Any, payload: dict[str, Any]
   393	) -> SensorAnomalyContext:
   394	    alarm_id = payload.get("alarm_id", "unknown")
   395	    level = payload.get("level", "CRITICAL")
   396	    channels: list[str] = payload.get("channels", [])
   397	    values: dict[str, float] = payload.get("values", {})
   398	    message = payload.get("message", "—")
   399	    channel = channels[0] if channels else alarm_id.replace("diag:", "")
   400	    current_value = "—"
   401	    if values:
   402	        first_ch = next(iter(values))
   403	        current_value = f"{values[first_ch]:.4g}"
   404	    experiment_id: str | None = getattr(em, "active_experiment_id", None)
   405	    phase: str | None = None
   406	    if hasattr(em, "get_current_phase"):
   407	        try:
   408	            phase = em.get_current_phase()
   409	        except Exception:
   410	            pass
   411	    health_score = payload.get("health_score", "—")
   412	    fault_flags_raw = payload.get("fault_flags", [])
   413	    fault_flags = ", ".join(fault_flags_raw) if fault_flags_raw else "—"
   414	    return SensorAnomalyContext(
   415	        alarm_id=alarm_id,
   416	        level=level,
   417	        channel=channel,
   418	        channels=channels,
   419	        values=values,
   420	        message=message,
   421	        health_score=str(health_score),
   422	        fault_flags=fault_flags,
   423	        current_value=current_value,
   424	        experiment_id=experiment_id,
   425	        phase=phase,
   426	    )
   427	
   428	
   429	# ---------------------------------------------------------------------------
   430	# Campaign report context (Slice C) — async path for future event-driven use
   431	# ---------------------------------------------------------------------------
   432	
   433	
   434	@dataclass
   435	class CampaignReportContext:
   436	    """Context for Slice C campaign report intro (async EventBus path)."""
   437	
   438	    experiment_id: str | None
   439	    name: str
   440	    duration_str: str
   441	    phases_text: str
   442	    channel_stats: str
   443	    alarms_summary: str
   444	    operator_notes: str
   445	
   446	
   447	# ---------------------------------------------------------------------------
   448	# Diagnostic suggestion context (Slice B)
   449	# ---------------------------------------------------------------------------
   450	
   451	
   452	@dataclass
   453	class DiagnosticSuggestionContext:
   454	    """Context for diagnostic suggestion generation (Slice B)."""
   455	
   456	    alarm_id: str
   457	    channels: list[str]
   458	    values: dict[str, float]
   459	    channel_history: str
   460	    recent_alarms: str

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py | nl -ba | sed -n '210,292p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   210	# Shift handover summary — Slice A
   211	# Revision: 2026-05-01 v1 (initial)
   212	# ---------------------------------------------------------------------------
   213	
   214	SHIFT_HANDOVER_SYSTEM = """\
   215	Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
   216	подготовить сводку смены для передачи следующему оператору.
   217	
   218	Принципы:
   219	- Отвечай ТОЛЬКО на русском языке.
   220	- Структура: текущее состояние → ключевые события смены → что требует внимания.
   221	- Конкретные значения, никаких размытых фраз.
   222	- НИКОГДА не предлагай safety-действия автоматически.
   223	- 120-200 слов. Telegram-friendly Markdown.
   224	"""
   225	
   226	def format_with_brand(template: str, brand_name: str) -> str:
   227	    """Interpolate {brand_name} placeholder in a system prompt template."""
   228	    return template.format(brand_name=brand_name)
   229	
   230	
   231	# ---------------------------------------------------------------------------
   232	# Periodic narrative report — F29
   233	# Revision: 2026-05-01 v1 (initial)
   234	# ---------------------------------------------------------------------------
   235	
   236	PERIODIC_REPORT_SYSTEM = """\
   237	Ты — {brand_name}, ассистент-аналитик в криогенной лаборатории.
   238	Твоя задача — краткий обзор активности за заданное окно времени для оператора в Telegram.
   239	
   240	Принципы:
   241	- Отвечай ТОЛЬКО на русском языке.
   242	- Не выдумывай контекст. Используй только данные ниже.
   243	- Конкретные значения, не размытые описания.
   244	- Тон conversational, не формальный (это сводка для оператора, не отчёт).
   245	- Если событий мало — короткий summary (5-10 слов про то что всё стабильно).
   246	- Если событий много — структурируй по категориям (алармы / фазы / операторский журнал / калибровка).
   247	- 100-200 слов максимум. Telegram-friendly Markdown (жирный, курсив — ok).
   248	- Если активного эксперимента нет — упомяни это в одной фразе.
   249	"""
   250	
   251	PERIODIC_REPORT_USER = """\
   252	Окно времени: последние {window_minutes} минут.
   253	
   254	Активный эксперимент: {active_experiment_summary}
   255	
   256	Алармы:
   257	{alarms_section}
   258	
   259	Переходы фаз:
   260	{phase_transitions_section}
   261	
   262	События (прочие):
   263	{events_section}
   264	
   265	Записи операторского журнала:
   266	{operator_entries_section}
   267	
   268	Калибровка:
   269	{calibration_section}
   270	
   271	Всего событий: {total_event_count}
   272	
   273	Сгенерируй краткую сводку для оператора в Telegram. Только русский язык.
   274	"""
   275	
   276	
   277	SHIFT_HANDOVER_USER = """\
   278	ЗАПРОС СВОДКИ ДЛЯ ПЕРЕДАЧИ СМЕНЫ:
   279	
   280	ТЕКУЩЕЕ СОСТОЯНИЕ:
   281	- Эксперимент: {experiment_id}
   282	- Фаза: {phase}
   283	- Продолжительность эксперимента: {experiment_age}
   284	
   285	АКТИВНЫЕ АЛАРМЫ:
   286	{active_alarms}
   287	
   288	СОБЫТИЯ ЗА СМЕНУ (последние {shift_duration_h}ч):
   289	{recent_events}
   290	
   291	Подготовь сводку для следующего оператора. Только русский язык.
   292	"""

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/output_router.py | nl -ba | sed -n '1,130p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Output routing for GemmaAgent LLM responses.
     2	
     3	Dispatches generated text to configured output channels.
     4	Every output is prefixed with "🤖 Гемма:" so operators immediately
     5	distinguish AI-generated content from human input.
     6	"""
     7	
     8	from __future__ import annotations
     9	
    10	import enum
    11	import logging
    12	from typing import TYPE_CHECKING, Any
    13	
    14	if TYPE_CHECKING:
    15	    from cryodaq.core.event_bus import EngineEvent, EventBus
    16	    from cryodaq.core.event_logger import EventLogger
    17	
    18	logger = logging.getLogger(__name__)
    19	
    20	class OutputTarget(enum.Enum):
    21	    TELEGRAM = "telegram"
    22	    OPERATOR_LOG = "operator_log"
    23	    GUI_INSIGHT = "gui_insight"
    24	
    25	
    26	class OutputRouter:
    27	    """Dispatches AssistantLiveAgent LLM output to configured channels."""
    28	
    29	    def __init__(
    30	        self,
    31	        *,
    32	        telegram_bot: Any | None,
    33	        event_logger: EventLogger,
    34	        event_bus: EventBus,
    35	        brand_name: str = "Гемма",
    36	        brand_emoji: str = "🤖",
    37	    ) -> None:
    38	        self._telegram = telegram_bot
    39	        self._event_logger = event_logger
    40	        self._event_bus = event_bus
    41	        self._brand_base = f"{brand_emoji} {brand_name}"
    42	        self._prefix = f"{self._brand_base}:"
    43	
    44	    async def dispatch(
    45	        self,
    46	        trigger_event: EngineEvent,
    47	        llm_output: str,
    48	        *,
    49	        targets: list[OutputTarget],
    50	        audit_id: str,
    51	        prefix_suffix: str = "",
    52	    ) -> list[str]:
    53	        """Send llm_output to all configured targets.
    54	
    55	        prefix_suffix: optional text inserted before the colon, e.g. "(отчёт за час)".
    56	        Returns list of successfully dispatched target names.
    57	        """
    58	        dispatched: list[str] = []
    59	        if prefix_suffix:
    60	            prefix = f"{self._brand_base} {prefix_suffix}:"
    61	        else:
    62	            prefix = self._prefix
    63	        prefixed = f"{prefix} {llm_output}"
    64	
    65	        for target in targets:
    66	            try:
    67	                if target == OutputTarget.TELEGRAM:
    68	                    if self._telegram is not None:
    69	                        await self._telegram._send_to_all(prefixed)
    70	                        dispatched.append("telegram")
    71	                    else:
    72	                        logger.debug("OutputRouter: Telegram bot not configured, skipping")
    73	
    74	                elif target == OutputTarget.OPERATOR_LOG:
    75	                    await self._event_logger.log_event(
    76	                        "assistant",
    77	                        prefixed,
    78	                        extra_tags=["ai", audit_id],
    79	                    )
    80	                    dispatched.append("operator_log")
    81	
    82	                elif target == OutputTarget.GUI_INSIGHT:
    83	                    from datetime import UTC, datetime
    84	
    85	                    from cryodaq.core.event_bus import EngineEvent as _EngineEvent
    86	
    87	                    await self._event_bus.publish(
    88	                        _EngineEvent(
    89	                            event_type="assistant_insight",
    90	                            timestamp=datetime.now(UTC),
    91	                            payload={
    92	                                "text": llm_output,
    93	                                "trigger_event_type": trigger_event.event_type,
    94	                                "audit_id": audit_id,
    95	                            },
    96	                            experiment_id=trigger_event.experiment_id,
    97	                        )
    98	                    )
    99	                    dispatched.append("gui_insight")
   100	
   101	            except Exception:
   102	                logger.warning(
   103	                    "OutputRouter: failed to dispatch to %s (audit_id=%s)",
   104	                    target.value,
   105	                    audit_id,
   106	                    exc_info=True,
   107	                )
   108	
   109	        return dispatched

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/agent.py | nl -ba | sed -n '738,790p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   738	        targets = _build_targets(self._config)
   739	        if result.truncated or not result.text.strip():
   740	            logger.warning(
   741	                "AssistantLiveAgent: пустой periodic report (audit_id=%s)", audit_id
   742	            )
   743	            dispatched_pr: list[str] = []
   744	        else:
   745	            dispatched_pr = await self._router.dispatch(
   746	                event,
   747	                result.text,
   748	                targets=targets,
   749	                audit_id=audit_id,
   750	                prefix_suffix="(отчёт за час)",
   751	            )
   752	
   753	        await self._audit.log(
   754	            audit_id=audit_id,
   755	            trigger_event={
   756	                "event_type": event.event_type,
   757	                "payload": event.payload,
   758	                "experiment_id": event.experiment_id,
   759	            },
   760	            context_assembled=user_prompt,
   761	            prompt_template="periodic_report",
   762	            model=result.model,
   763	            system_prompt=system_prompt,
   764	            user_prompt=user_prompt,
   765	            response=result.text,
   766	            tokens={"in": result.tokens_in, "out": result.tokens_out},
   767	            latency_s=result.latency_s,
   768	            outputs_dispatched=dispatched_pr,
   769	            errors=errors,
   770	        )
   771	        logger.info(
   772	            "AssistantLiveAgent: periodic_report_request обработан "
   773	            "(audit_id=%s, latency=%.1fs, events=%d, dispatched=%s)",
   774	            audit_id,
   775	            result.latency_s,
   776	            ctx.total_event_count,
   777	            dispatched_pr,
   778	        )
   779	
   780	
   781	def _build_targets(config: AssistantConfig) -> list[OutputTarget]:
   782	    targets = []
   783	    if config.output_telegram:
   784	        targets.append(OutputTarget.TELEGRAM)
   785	    if config.output_operator_log:
   786	        targets.append(OutputTarget.OPERATOR_LOG)
   787	    if config.output_gui_insight:
   788	        targets.append(OutputTarget.GUI_INSIGHT)
   789	    return targets
   790	

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py | nl -ba | sed -n '1,140p;150,278p;515,547p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Context assembler for GemmaAgent LLM prompts.
     2	
     3	Each task type (alarm summary, diagnostic, campaign report) requires
     4	different context. Builders read SQLite state and format compact text
     5	for LLM token budget.
     6	
     7	Cycle 1: AlarmContext dataclass + build_alarm_context interface.
     8	Cycle 3: ExperimentFinalizeContext, SensorAnomalyContext, ShiftHandoverContext added.
     9	Cycle 4: DiagnosticSuggestionContext + real SQLite channel history reads.
    10	Slice C (campaign) contexts deferred.
    11	"""
    12	
    13	from __future__ import annotations
    14	
    15	import logging
    16	import time as _time
    17	from dataclasses import dataclass, field
    18	from datetime import UTC, datetime, timedelta
    19	from typing import Any
    20	
    21	logger = logging.getLogger(__name__)
    22	
    23	
    24	@dataclass
    25	class AlarmContext:
    26	    """Context for alarm summary generation (Slice A)."""
    27	
    28	    alarm_id: str
    29	    level: str
    30	    channels: list[str]
    31	    values: dict[str, float]
    32	    phase: str | None
    33	    experiment_id: str | None
    34	    experiment_age_s: float | None
    35	    target_temp: float | None
    36	    active_interlocks: list[str] = field(default_factory=list)
    37	    recent_readings_text: str = ""
    38	    recent_alarms_text: str = ""
    39	
    40	
    41	class ContextBuilder:
    42	    """Assembles engine state for LLM prompt construction."""
    43	
    44	    def __init__(self, sqlite_reader: Any, experiment_manager: Any) -> None:
    45	        self._reader = sqlite_reader
    46	        self._em = experiment_manager
    47	
    48	    async def build_alarm_context(
    49	        self,
    50	        alarm_payload: dict[str, Any],
    51	        *,
    52	        lookback_s: float = 60.0,
    53	        recent_alarm_lookback_s: float = 3600.0,
    54	    ) -> AlarmContext:
    55	        """Assemble context for a Slice A alarm summary prompt.
    56	
    57	        Reads experiment state from ExperimentManager (in-memory, fast).
    58	        SQLite reading history and alarm history wired in Cycle 4 — historical SQLite context.
    59	        """
    60	        alarm_id = alarm_payload.get("alarm_id", "unknown")
    61	        channels: list[str] = alarm_payload.get("channels", [])
    62	        values: dict[str, float] = alarm_payload.get("values", {})
    63	        level: str = alarm_payload.get("level", "WARNING")
    64	
    65	        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
    66	
    67	        phase: str | None = None
    68	        if hasattr(self._em, "get_current_phase"):
    69	            try:
    70	                phase = self._em.get_current_phase()
    71	            except Exception:
    72	                pass
    73	
    74	        experiment_age_s: float | None = _compute_experiment_age(self._em)
    75	
    76	        return AlarmContext(
    77	            alarm_id=alarm_id,
    78	            level=level,
    79	            channels=channels,
    80	            values=values,
    81	            phase=phase,
    82	            experiment_id=experiment_id,
    83	            experiment_age_s=experiment_age_s,
    84	            target_temp=None,
    85	            active_interlocks=[],
    86	            recent_readings_text=_readings_stub(channels, lookback_s),
    87	            recent_alarms_text=_alarms_stub(recent_alarm_lookback_s),
    88	        )
    89	
    90	    async def build_experiment_finalize_context(
    91	        self, payload: dict[str, Any]
    92	    ) -> ExperimentFinalizeContext:
    93	        """Assemble context for experiment finalize/stop/abort prompt."""
    94	        return _build_experiment_finalize_context(self._em, payload)
    95	
    96	    async def build_sensor_anomaly_context(
    97	        self, payload: dict[str, Any]
    98	    ) -> SensorAnomalyContext:
    99	        """Assemble context for sensor anomaly analysis prompt."""
   100	        return _build_sensor_anomaly_context(self._em, payload)
   101	
   102	    async def build_shift_handover_context(
   103	        self, payload: dict[str, Any]
   104	    ) -> ShiftHandoverContext:
   105	        """Assemble context for shift handover summary prompt."""
   106	        return _build_shift_handover_context(self._em, payload)
   107	
   108	    async def build_periodic_report_context(
   109	        self,
   110	        *,
   111	        window_minutes: int = 60,
   112	    ) -> PeriodicReportContext:
   113	        """Aggregate engine activity over last window_minutes for periodic report.
   114	
   115	        Uses get_operator_log() with time window — no new SQLite methods needed.
   116	        All event types (alarms, phases, experiments, operator entries) are
   117	        stored in the operator log with identifying tags.
   118	        """
   119	        now = datetime.now(UTC)
   120	        start_time = now - timedelta(minutes=window_minutes)
   121	
   122	        entries: list[Any] = []
   123	        if hasattr(self._reader, "get_operator_log"):
   124	            try:
   125	                entries = await self._reader.get_operator_log(
   126	                    start_time=start_time,
   127	                    end_time=now,
   128	                    limit=50,
   129	                )
   130	            except Exception:
   131	                logger.debug("PeriodicReportContext: get_operator_log failed", exc_info=True)
   132	
   133	        alarm_entries = [e for e in entries if "alarm" in e.tags]
   134	        phase_entries = [e for e in entries if "phase_transition" in e.tags]
   135	        experiment_entries = [e for e in entries if "experiment" in e.tags]
   136	        calibration_entries = [e for e in entries if "calibration" in e.tags]
   137	        # Exclude machine-generated and AI-generated entries from operator section
   138	        operator_entries = [
   139	            e for e in entries
   140	            if e.source != "auto" and "ai" not in e.tags and "auto" not in e.tags
   150	            and "ai" not in e.tags
   151	        ]
   152	
   153	        total_event_count = (
   154	            len(alarm_entries) + len(phase_entries) + len(experiment_entries)
   155	            + len(calibration_entries) + len(operator_entries) + len(other_entries)
   156	        )
   157	
   158	        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
   159	        phase: str | None = None
   160	        if hasattr(self._em, "get_current_phase"):
   161	            try:
   162	                phase = self._em.get_current_phase()
   163	            except Exception:
   164	                pass
   165	
   166	        return PeriodicReportContext(
   167	            window_minutes=window_minutes,
   168	            active_experiment_id=experiment_id,
   169	            active_experiment_phase=phase,
   170	            alarm_entries=alarm_entries,
   171	            phase_entries=phase_entries,
   172	            experiment_entries=experiment_entries,
   173	            calibration_entries=calibration_entries,
   174	            operator_entries=operator_entries,
   175	            other_entries=other_entries,
   176	            total_event_count=total_event_count,
   177	        )
   178	
   179	    async def build_diagnostic_suggestion_context(
   180	        self,
   181	        alarm_payload: dict[str, Any],
   182	        *,
   183	        lookback_min: int = 60,
   184	    ) -> DiagnosticSuggestionContext:
   185	        """Assemble context for Slice B diagnostic suggestion.
   186	
   187	        Reads last lookback_min minutes of readings for alarm channels
   188	        from SQLite. Alarm history, cooldown history, and pressure trend
   189	        remain stubs until Cycle 4.1 wires those sources.
   190	        """
   191	        alarm_id = alarm_payload.get("alarm_id", "unknown")
   192	        channels: list[str] = alarm_payload.get("channels", [])
   193	        values: dict[str, float] = alarm_payload.get("values", {})
   194	        channel_history = await self._read_channel_history(channels, lookback_min)
   195	        pressure_trend = await self._read_pressure_trend()
   196	        return DiagnosticSuggestionContext(
   197	            alarm_id=alarm_id,
   198	            channels=channels,
   199	            values=values,
   200	            channel_history=channel_history,
   201	            recent_alarms="нет данных",
   202	            past_cooldowns="нет истории",
   203	            pressure_trend=pressure_trend,
   204	            lookback_min=lookback_min,
   205	        )
   206	
   207	    async def _read_channel_history(self, channels: list[str], lookback_min: int) -> str:
   208	        """Read recent readings for alarm channels from SQLite."""
   209	        if not channels or not hasattr(self._reader, "read_readings_history"):
   210	            return "нет данных"
   211	        try:
   212	            from_ts = _time.time() - lookback_min * 60
   213	            data: dict[str, list[tuple[float, float]]] = (
   214	                await self._reader.read_readings_history(
   215	                    channels=channels,
   216	                    from_ts=from_ts,
   217	                    limit_per_channel=20,
   218	                )
   219	            )
   220	            if not data:
   221	                return "нет данных"
   222	            lines: list[str] = []
   223	            for ch, readings in data.items():
   224	                if readings:
   225	                    vals = [f"{v:.4g}" for _, v in readings[-5:]]
   226	                    lines.append(f"- {ch}: [{', '.join(vals)}]")
   227	            return "\n".join(lines) if lines else "нет данных"
   228	        except Exception:
   229	            logger.debug("ContextBuilder: channel history read failed", exc_info=True)
   230	            return "нет данных"
   231	
   232	    async def _read_pressure_trend(self) -> str:
   233	        """Read recent pressure readings from SQLite."""
   234	        if not hasattr(self._reader, "read_readings_history"):
   235	            return "нет данных"
   236	        try:
   237	            from_ts = _time.time() - 30 * 60
   238	            data: dict[str, list[tuple[float, float]]] = (
   239	                await self._reader.read_readings_history(
   240	                    from_ts=from_ts,
   241	                    limit_per_channel=10,
   242	                )
   243	            )
   244	            pressure = {
   245	                k: v
   246	                for k, v in data.items()
   247	                if "pressure" in k.lower() or "mbar" in k.lower()
   248	            }
   249	            if not pressure:
   250	                return "нет данных"
   251	            lines: list[str] = []
   252	            for ch, readings in pressure.items():
   253	                if len(readings) >= 2:
   254	                    start = readings[0][1]
   255	                    end = readings[-1][1]
   256	                    threshold = 0.01 * max(abs(start), 1e-12)
   257	                    arrow = "→" if abs(end - start) < threshold else ("↑" if end > start else "↓")
   258	                    lines.append(f"- {ch}: {start:.2e} → {end:.2e} {arrow}")
   259	            return "\n".join(lines) if lines else "нет данных"
   260	        except Exception:
   261	            logger.debug("ContextBuilder: pressure trend read failed", exc_info=True)
   262	            return "нет данных"
   263	
   264	
   265	def _compute_experiment_age(em: Any) -> float | None:
   266	    try:
   267	        history = em.get_phase_history()
   268	        if not history:
   269	            return None
   270	        first = history[0].get("started_at")
   271	        if not first:
   272	            return None
   273	        from datetime import UTC, datetime
   274	
   275	        started = datetime.fromisoformat(first)
   276	        return (datetime.now(UTC) - started.astimezone(UTC)).total_seconds()
   277	    except Exception:
   278	        return None
   515	    total_event_count: int = 0
   516	
   517	    def to_template_dict(self) -> dict[str, str]:
   518	        """Format all context fields as prompt-ready strings."""
   519	        if self.active_experiment_id:
   520	            phase_str = (
   521	                f" (фаза: {self.active_experiment_phase})"
   522	                if self.active_experiment_phase else ""
   523	            )
   524	            active_exp = f"{self.active_experiment_id}{phase_str}"
   525	        else:
   526	            active_exp = "нет активного эксперимента"
   527	
   528	        return {
   529	            "active_experiment_summary": active_exp,
   530	            "events_section": _format_log_entries(self.other_entries) or "(нет)",
   531	            "alarms_section": _format_log_entries(self.alarm_entries) or "(нет)",
   532	            "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
   533	            "operator_entries_section": _format_log_entries(self.operator_entries) or "(нет)",
   534	            "calibration_section": _format_log_entries(self.calibration_entries) or "(нет)",
   535	            "total_event_count": str(self.total_event_count),
   536	        }
   537	
   538	
   539	def _format_log_entries(entries: list[Any]) -> str:
   540	    if not entries:
   541	        return ""
   542	    lines = []
   543	    for e in entries[:10]:
   544	        ts = e.timestamp.astimezone().strftime("%H:%M") if hasattr(e, "timestamp") else "?"
   545	        msg = getattr(e, "message", str(e))[:120]
   546	        lines.append(f"- {ts}: {msg}")
   547	    return "\n".join(lines)

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_context.py | nl -ba | sed -n '1,220p' && git show feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py | nl -ba | sed -n '1,270p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Tests for PeriodicReportContext and build_periodic_report_context (F29)."""
     2	
     3	from __future__ import annotations
     4	
     5	from datetime import UTC, datetime
     6	from unittest.mock import AsyncMock, MagicMock
     7	
     8	from cryodaq.agents.assistant.live.context_builder import ContextBuilder
     9	
    10	
    11	def _make_entry(message: str, tags: tuple[str, ...], source: str = "auto") -> MagicMock:
    12	    entry = MagicMock()
    13	    entry.timestamp = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    14	    entry.message = message
    15	    entry.tags = tags
    16	    entry.source = source
    17	    return entry
    18	
    19	
    20	def _make_context_builder(entries: list, experiment_id: str | None = "exp-001") -> ContextBuilder:
    21	    reader = MagicMock()
    22	    reader.get_operator_log = AsyncMock(return_value=entries)
    23	    em = MagicMock()
    24	    em.active_experiment_id = experiment_id
    25	    em.get_current_phase = MagicMock(return_value="COOL")
    26	    return ContextBuilder(reader, em)
    27	
    28	
    29	async def test_periodic_report_context_aggregates_window() -> None:
    30	    entries = [
    31	        _make_entry("Alarm fired", ("auto", "alarm", "alarm_T1")),
    32	        _make_entry("Phase → COOL", ("auto", "phase_transition")),
    33	        _make_entry("Experiment started", ("auto", "experiment")),
    34	    ]
    35	    cb = _make_context_builder(entries)
    36	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    37	
    38	    assert len(ctx.alarm_entries) == 1
    39	    assert len(ctx.phase_entries) == 1
    40	    assert len(ctx.experiment_entries) == 1
    41	    assert ctx.total_event_count == 3
    42	    assert ctx.active_experiment_id == "exp-001"
    43	    assert ctx.active_experiment_phase == "COOL"
    44	
    45	
    46	async def test_periodic_report_context_handles_empty_window() -> None:
    47	    cb = _make_context_builder([])
    48	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    49	
    50	    assert ctx.total_event_count == 0
    51	    assert ctx.alarm_entries == []
    52	    assert ctx.phase_entries == []
    53	    assert ctx.operator_entries == []
    54	
    55	
    56	async def test_periodic_report_context_excludes_machine_log_entries() -> None:
    57	    entries = [
    58	        _make_entry("AI summary", ("auto", "ai", "abc123")),
    59	        _make_entry("Manual note", (), source="operator"),
    60	    ]
    61	    cb = _make_context_builder(entries)
    62	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    63	
    64	    # AI entry must NOT appear in operator_entries
    65	    assert len(ctx.operator_entries) == 1
    66	    assert ctx.operator_entries[0].message == "Manual note"
    67	    assert ctx.total_event_count == 1  # only the operator entry
    68	
    69	
    70	async def test_periodic_report_context_total_count_correct() -> None:
    71	    entries = [
    72	        _make_entry("Alarm 1", ("auto", "alarm")),
    73	        _make_entry("Alarm 2", ("auto", "alarm")),
    74	        _make_entry("Phase", ("auto", "phase_transition")),
    75	        _make_entry("Operator note", (), source="operator"),
    76	        _make_entry("Leak rate", ("auto", "leak_rate")),
    77	    ]
    78	    cb = _make_context_builder(entries)
    79	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    80	
    81	    assert ctx.total_event_count == 5
    82	
    83	
    84	async def test_periodic_report_context_no_experiment() -> None:
    85	    cb = _make_context_builder([], experiment_id=None)
    86	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    87	
    88	    assert ctx.active_experiment_id is None
    89	    tmpl = ctx.to_template_dict()
    90	    assert "нет активного" in tmpl["active_experiment_summary"]
    91	
    92	
    93	async def test_periodic_report_context_to_template_dict_structure() -> None:
    94	    entries = [
    95	        _make_entry("Alarm T1 high", ("auto", "alarm")),
    96	    ]
    97	    cb = _make_context_builder(entries)
    98	    ctx = await cb.build_periodic_report_context(window_minutes=60)
    99	
   100	    tmpl = ctx.to_template_dict()
   101	    assert "active_experiment_summary" in tmpl
   102	    assert "events_section" in tmpl
   103	    assert "alarms_section" in tmpl
   104	    assert "phase_transitions_section" in tmpl
   105	    assert "operator_entries_section" in tmpl
   106	    assert "total_event_count" in tmpl
   107	    assert "Alarm T1 high" in tmpl["alarms_section"]
   108	    assert tmpl["total_event_count"] == "1"
   109	
   110	
   111	async def test_periodic_report_context_formats_calibration_section() -> None:
   112	    entries = [
   113	        _make_entry("T1 offset +0.02 K", ("auto", "calibration")),
   114	    ]
   115	    cb = _make_context_builder(entries)
   116	    ctx = await cb.build_periodic_report_context(window_minutes=60)
   117	
   118	    tmpl = ctx.to_template_dict()
   119	    assert "T1 offset" in tmpl["calibration_section"]
   120	    assert "T1 offset" not in tmpl["events_section"]
   121	    assert ctx.total_event_count == 1
     1	"""Tests for AssistantLiveAgent periodic_report_request handler (F29)."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	from datetime import UTC, datetime
     7	from pathlib import Path
     8	from unittest.mock import AsyncMock, MagicMock
     9	
    10	from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
    11	from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext
    12	from cryodaq.agents.assistant.live.output_router import OutputRouter
    13	from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM, PERIODIC_REPORT_USER
    14	from cryodaq.agents.assistant.shared.audit import AuditLogger
    15	from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
    16	from cryodaq.core.event_bus import EngineEvent, EventBus
    17	
    18	
    19	def _periodic_event(window_minutes: int = 60) -> EngineEvent:
    20	    return EngineEvent(
    21	        event_type="periodic_report_request",
    22	        timestamp=datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC),
    23	        payload={"window_minutes": window_minutes, "trigger": "scheduled"},
    24	        experiment_id="exp-001",
    25	    )
    26	
    27	
    28	def _make_config(**overrides) -> AssistantConfig:
    29	    cfg = AssistantConfig(
    30	        enabled=True,
    31	        max_concurrent_inferences=1,
    32	        max_calls_per_hour=60,
    33	        output_telegram=True,
    34	        output_operator_log=True,
    35	        output_gui_insight=False,
    36	        audit_enabled=False,
    37	        periodic_report_enabled=True,
    38	        periodic_report_min_events=1,
    39	        periodic_report_skip_if_idle=True,
    40	    )
    41	    for k, v in overrides.items():
    42	        setattr(cfg, k, v)
    43	    return cfg
    44	
    45	
    46	def _make_mock_context(total_event_count: int = 3) -> PeriodicReportContext:
    47	    ctx = PeriodicReportContext(
    48	        window_minutes=60,
    49	        active_experiment_id="exp-001",
    50	        active_experiment_phase="COOL",
    51	        total_event_count=total_event_count,
    52	    )
    53	    return ctx
    54	
    55	
    56	def _make_agent(
    57	    *,
    58	    config: AssistantConfig | None = None,
    59	    ollama=None,
    60	    telegram=None,
    61	    event_logger=None,
    62	    context: PeriodicReportContext | None = None,
    63	    tmp_path: Path,
    64	) -> tuple[AssistantLiveAgent, EventBus]:
    65	    bus = EventBus()
    66	    cfg = config or _make_config()
    67	    em = MagicMock()
    68	    em.active_experiment_id = "exp-001"
    69	    em.get_current_phase = MagicMock(return_value="COOL")
    70	    em.get_phase_history = MagicMock(return_value=[])
    71	
    72	    reader = MagicMock()
    73	    reader.get_operator_log = AsyncMock(return_value=[])
    74	    ctx_builder = ContextBuilder(reader, em)
    75	
    76	    if context is not None:
    77	        ctx_builder.build_periodic_report_context = AsyncMock(return_value=context)
    78	
    79	    audit = AuditLogger(tmp_path / "audit", enabled=False)
    80	
    81	    if telegram is None:
    82	        telegram = AsyncMock()
    83	        telegram._send_to_all = AsyncMock()
    84	    if event_logger is None:
    85	        event_logger = AsyncMock()
    86	        event_logger.log_event = AsyncMock()
    87	
    88	    router = OutputRouter(
    89	        telegram_bot=telegram,
    90	        event_logger=event_logger,
    91	        event_bus=bus,
    92	    )
    93	
    94	    if ollama is None:
    95	        ollama = AsyncMock()
    96	        ollama.generate = AsyncMock(
    97	            return_value=GenerationResult(
    98	                text="Всё стабильно. Активный эксперимент в фазе охлаждения.",
    99	                tokens_in=50,
   100	                tokens_out=20,
   101	                latency_s=2.0,
   102	                model="gemma4:e2b",
   103	            )
   104	        )
   105	        ollama.close = AsyncMock()
   106	
   107	    agent = AssistantLiveAgent(
   108	        config=cfg,
   109	        event_bus=bus,
   110	        ollama_client=ollama,
   111	        context_builder=ctx_builder,
   112	        audit_logger=audit,
   113	        output_router=router,
   114	    )
   115	    return agent, bus
   116	
   117	
   118	# ---------------------------------------------------------------------------
   119	# Handler dispatch
   120	# ---------------------------------------------------------------------------
   121	
   122	
   123	async def test_periodic_report_handler_dispatches_when_active(tmp_path: Path) -> None:
   124	    telegram = AsyncMock()
   125	    telegram._send_to_all = AsyncMock()
   126	    ctx = _make_mock_context(total_event_count=3)
   127	    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
   128	    await agent.start()
   129	
   130	    await bus.publish(_periodic_event())
   131	    await asyncio.sleep(0.1)
   132	
   133	    telegram._send_to_all.assert_awaited_once()
   134	    sent = telegram._send_to_all.call_args[0][0]
   135	    assert "🤖 Гемма (отчёт за час):" in sent
   136	    await agent.stop()
   137	
   138	
   139	async def test_periodic_report_handler_skips_when_idle(tmp_path: Path) -> None:
   140	    telegram = AsyncMock()
   141	    telegram._send_to_all = AsyncMock()
   142	    # total_event_count=0 < min_events=1 → idle skip
   143	    ctx = _make_mock_context(total_event_count=0)
   144	    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
   145	    await agent.start()
   146	
   147	    await bus.publish(_periodic_event())
   148	    await asyncio.sleep(0.1)
   149	
   150	    telegram._send_to_all.assert_not_awaited()
   151	    await agent.stop()
   152	
   153	
   154	async def test_periodic_report_skip_if_idle_false_dispatches_always(tmp_path: Path) -> None:
   155	    """skip_if_idle=False → dispatch even when no events."""
   156	    telegram = AsyncMock()
   157	    telegram._send_to_all = AsyncMock()
   158	    ctx = _make_mock_context(total_event_count=0)
   159	    cfg = _make_config(periodic_report_skip_if_idle=False)
   160	    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
   161	    await agent.start()
   162	
   163	    await bus.publish(_periodic_event())
   164	    await asyncio.sleep(0.1)
   165	
   166	    telegram._send_to_all.assert_awaited_once()
   167	    await agent.stop()
   168	
   169	
   170	async def test_periodic_report_handler_handles_empty_response(tmp_path: Path) -> None:
   171	    telegram = AsyncMock()
   172	    telegram._send_to_all = AsyncMock()
   173	    ctx = _make_mock_context(total_event_count=2)
   174	    ollama = AsyncMock()
   175	    ollama.generate = AsyncMock(
   176	        return_value=GenerationResult(
   177	            text="", tokens_in=10, tokens_out=0, latency_s=1.0, model="gemma4:e2b"
   178	        )
   179	    )
   180	    ollama.close = AsyncMock()
   181	    agent, bus = _make_agent(
   182	        ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path
   183	    )
   184	    await agent.start()
   185	
   186	    await bus.publish(_periodic_event())
   187	    await asyncio.sleep(0.1)
   188	
   189	    telegram._send_to_all.assert_not_awaited()
   190	    await agent.stop()
   191	
   192	
   193	async def test_periodic_report_disabled_does_not_handle(tmp_path: Path) -> None:
   194	    telegram = AsyncMock()
   195	    telegram._send_to_all = AsyncMock()
   196	    cfg = _make_config(periodic_report_enabled=False)
   197	    ctx = _make_mock_context(total_event_count=5)
   198	    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
   199	    await agent.start()
   200	
   201	    await bus.publish(_periodic_event())
   202	    await asyncio.sleep(0.05)
   203	
   204	    telegram._send_to_all.assert_not_awaited()
   205	    await agent.stop()
   206	
   207	
   208	# ---------------------------------------------------------------------------
   209	# OutputRouter prefix_suffix
   210	# ---------------------------------------------------------------------------
   211	
   212	
   213	def test_periodic_report_prefix_includes_suffix() -> None:
   214	    router = OutputRouter(
   215	        telegram_bot=None,
   216	        event_logger=MagicMock(),
   217	        event_bus=MagicMock(),
   218	        brand_name="Гемма",
   219	        brand_emoji="🤖",
   220	    )
   221	    # Verify brand_base used for suffix variant
   222	    assert router._brand_base == "🤖 Гемма"
   223	    # Verify standard prefix unchanged
   224	    assert router._prefix == "🤖 Гемма:"
   225	
   226	
   227	def test_periodic_report_prompt_does_not_hardcode_hour_window() -> None:
   228	    """Configured non-hourly windows must not fight a hardcoded system prompt."""
   229	    assert "последний час" not in PERIODIC_REPORT_SYSTEM
   230	    assert "{window_minutes}" in PERIODIC_REPORT_USER

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:tests/agents/assistant/test_engine_periodic_report_tick.py | nl -ba | sed -n '1,180p' && git show feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_config.py | nl -ba | sed -n '1,140p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Tests for engine-owned periodic_report_request timer (F29 Phase D)."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	from datetime import UTC
     7	from unittest.mock import MagicMock
     8	
     9	from cryodaq.agents.assistant.live.agent import AssistantConfig
    10	from cryodaq.core.event_bus import EventBus
    11	from cryodaq.engine import _periodic_report_tick
    12	
    13	
    14	def _make_config(**overrides) -> AssistantConfig:
    15	    cfg = AssistantConfig(
    16	        enabled=True,
    17	        periodic_report_enabled=True,
    18	        periodic_report_interval_minutes=15,
    19	    )
    20	    for key, value in overrides.items():
    21	        setattr(cfg, key, value)
    22	    return cfg
    23	
    24	
    25	def _make_experiment_manager(experiment_id: str | None = "exp-042") -> MagicMock:
    26	    em = MagicMock()
    27	    em.active_experiment_id = experiment_id
    28	    return em
    29	
    30	
    31	async def test_engine_periodic_report_tick_publishes_event() -> None:
    32	    cfg = _make_config(periodic_report_interval_minutes=15)
    33	    bus = EventBus()
    34	    q = await bus.subscribe("test")
    35	    sleep_calls: list[float] = []
    36	
    37	    async def fake_sleep(delay_s: float) -> None:
    38	        sleep_calls.append(delay_s)
    39	        await asyncio.sleep(0)
    40	
    41	    task = asyncio.create_task(
    42	        _periodic_report_tick(
    43	            cfg,
    44	            bus,
    45	            _make_experiment_manager("exp-042"),
    46	            sleep=fake_sleep,
    47	        )
    48	    )
    49	    try:
    50	        event = await asyncio.wait_for(q.get(), timeout=1.0)
    51	    finally:
    52	        task.cancel()
    53	        try:
    54	            await task
    55	        except asyncio.CancelledError:
    56	            pass
    57	
    58	    assert sleep_calls[0] == 15 * 60
    59	    assert event.event_type == "periodic_report_request"
    60	    assert event.timestamp.tzinfo is UTC
    61	    assert event.payload == {"window_minutes": 15, "trigger": "scheduled"}
    62	    assert event.experiment_id == "exp-042"
    63	
    64	
    65	async def test_engine_periodic_report_tick_disabled_when_config_off() -> None:
    66	    cfg = _make_config(periodic_report_enabled=False)
    67	    bus = EventBus()
    68	    q = await bus.subscribe("test")
    69	    sleep_called = False
    70	
    71	    async def fake_sleep(_delay_s: float) -> None:
    72	        nonlocal sleep_called
    73	        sleep_called = True
    74	
    75	    await _periodic_report_tick(
    76	        cfg,
    77	        bus,
    78	        _make_experiment_manager("exp-042"),
    79	        sleep=fake_sleep,
    80	    )
    81	
    82	    assert sleep_called is False
    83	    assert q.empty()
    84	
    85	
    86	async def test_engine_periodic_report_tick_cancelled_on_shutdown() -> None:
    87	    cfg = _make_config(periodic_report_interval_minutes=15)
    88	    bus = EventBus()
    89	
    90	    async def cancelling_sleep(_delay_s: float) -> None:
    91	        raise asyncio.CancelledError
    92	
    93	    task = asyncio.create_task(
    94	        _periodic_report_tick(
    95	            cfg,
    96	            bus,
    97	            _make_experiment_manager(),
    98	            sleep=cancelling_sleep,
    99	        )
   100	    )
   101	
   102	    try:
   103	        await task
   104	    except asyncio.CancelledError:
   105	        pass
   106	
   107	    assert task.cancelled()
     1	"""Tests for F29 periodic report configuration fields in AssistantConfig."""
     2	
     3	from __future__ import annotations
     4	
     5	from cryodaq.agents.assistant.live.agent import AssistantConfig
     6	
     7	
     8	def test_periodic_report_config_defaults() -> None:
     9	    config = AssistantConfig()
    10	    assert config.periodic_report_enabled is True
    11	    assert config.periodic_report_interval_minutes == 60
    12	    assert config.periodic_report_skip_if_idle is True
    13	    assert config.periodic_report_min_events == 1
    14	
    15	
    16	def test_periodic_report_config_disabled() -> None:
    17	    config = AssistantConfig.from_dict(
    18	        {"triggers": {"periodic_report": {"enabled": False}}}
    19	    )
    20	    assert config.periodic_report_enabled is False
    21	
    22	
    23	def test_periodic_report_interval_seconds_calculation() -> None:
    24	    config = AssistantConfig.from_dict(
    25	        {"triggers": {"periodic_report": {"enabled": True, "interval_minutes": 30}}}
    26	    )
    27	    assert config.get_periodic_report_interval_s() == 1800.0
    28	
    29	
    30	def test_periodic_report_interval_zero_when_disabled() -> None:
    31	    config = AssistantConfig.from_dict(
    32	        {"triggers": {"periodic_report": {"enabled": False, "interval_minutes": 60}}}
    33	    )
    34	    assert config.get_periodic_report_interval_s() == 0.0
    35	
    36	
    37	def test_periodic_report_min_events_configurable() -> None:
    38	    config = AssistantConfig.from_dict(
    39	        {"triggers": {"periodic_report": {"min_events_for_dispatch": 5}}}
    40	    )
    41	    assert config.periodic_report_min_events == 5
    42	
    43	
    44	def test_periodic_report_config_from_yaml_string() -> None:
    45	    yaml_content = (
    46	        "agent:\n"
    47	        "  triggers:\n"
    48	        "    periodic_report:\n"
    49	        "      enabled: true\n"
    50	        "      interval_minutes: 120\n"
    51	        "      skip_if_idle: false\n"
    52	        "      min_events_for_dispatch: 3\n"
    53	    )
    54	    config = AssistantConfig.from_yaml_string(yaml_content)
    55	    assert config.periodic_report_enabled is True
    56	    assert config.periodic_report_interval_minutes == 120
    57	    assert config.periodic_report_skip_if_idle is False
    58	    assert config.periodic_report_min_events == 3
    59	    assert config.get_periodic_report_interval_s() == 7200.0

codex
I’ve got one concrete bug candidate around output routing and I’m checking whether there are any second-order issues that are equally real: schema coercion, idle counts, and timestamp formatting.
exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py | nl -ba | sed -n '128,160p;492,518p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   128	                    limit=50,
   129	                )
   130	            except Exception:
   131	                logger.debug("PeriodicReportContext: get_operator_log failed", exc_info=True)
   132	
   133	        alarm_entries = [e for e in entries if "alarm" in e.tags]
   134	        phase_entries = [e for e in entries if "phase_transition" in e.tags]
   135	        experiment_entries = [e for e in entries if "experiment" in e.tags]
   136	        calibration_entries = [e for e in entries if "calibration" in e.tags]
   137	        # Exclude machine-generated and AI-generated entries from operator section
   138	        operator_entries = [
   139	            e for e in entries
   140	            if e.source != "auto" and "ai" not in e.tags and "auto" not in e.tags
   141	        ]
   142	        # Any auto event not classified above (calibration, leak_rate, etc.)
   143	        other_entries = [
   144	            e for e in entries
   145	            if "auto" in e.tags
   146	            and "alarm" not in e.tags
   147	            and "phase_transition" not in e.tags
   148	            and "experiment" not in e.tags
   149	            and "calibration" not in e.tags
   150	            and "ai" not in e.tags
   151	        ]
   152	
   153	        total_event_count = (
   154	            len(alarm_entries) + len(phase_entries) + len(experiment_entries)
   155	            + len(calibration_entries) + len(operator_entries) + len(other_entries)
   156	        )
   157	
   158	        experiment_id: str | None = getattr(self._em, "active_experiment_id", None)
   159	        phase: str | None = None
   160	        if hasattr(self._em, "get_current_phase"):
   492	    if m > 0:
   493	        return f"{m}м {s}с"
   494	    return f"{s}с"
   495	
   496	
   497	# ---------------------------------------------------------------------------
   498	# Periodic report context (F29)
   499	# ---------------------------------------------------------------------------
   500	
   501	
   502	@dataclass
   503	class PeriodicReportContext:
   504	    """Context for periodic narrative report (F29)."""
   505	
   506	    window_minutes: int
   507	    active_experiment_id: str | None
   508	    active_experiment_phase: str | None
   509	    alarm_entries: list[Any] = field(default_factory=list)
   510	    phase_entries: list[Any] = field(default_factory=list)
   511	    experiment_entries: list[Any] = field(default_factory=list)
   512	    calibration_entries: list[Any] = field(default_factory=list)
   513	    operator_entries: list[Any] = field(default_factory=list)
   514	    other_entries: list[Any] = field(default_factory=list)
   515	    total_event_count: int = 0
   516	
   517	    def to_template_dict(self) -> dict[str, str]:
   518	        """Format all context fields as prompt-ready strings."""

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/agents/assistant/shared/ollama_client.py | nl -ba | sed -n '1,210p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Ollama HTTP client for local LLM inference."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	import logging
     7	import time
     8	from dataclasses import dataclass
     9	from typing import Any
    10	
    11	import aiohttp
    12	
    13	logger = logging.getLogger(__name__)
    14	
    15	_GENERATE_PATH = "/api/generate"
    16	
    17	
    18	class OllamaUnavailableError(Exception):
    19	    """Ollama server unreachable (connection refused or network error)."""
    20	
    21	
    22	class OllamaModelMissingError(Exception):
    23	    """Requested model is not pulled on this Ollama instance."""
    24	
    25	    def __init__(self, model: str) -> None:
    26	        self.model = model
    27	        super().__init__(f"Model '{model}' not found. Run: ollama pull {model}")
    28	
    29	
    30	@dataclass
    31	class GenerationResult:
    32	    """Result of a single LLM generate call."""
    33	
    34	    text: str
    35	    tokens_in: int
    36	    tokens_out: int
    37	    latency_s: float
    38	    model: str
    39	    truncated: bool = False
    40	
    41	
    42	class OllamaClient:
    43	    """Async HTTP wrapper around Ollama /api/generate.
    44	
    45	    Manages one aiohttp.ClientSession; call close() on shutdown.
    46	    """
    47	
    48	    def __init__(
    49	        self,
    50	        base_url: str = "http://localhost:11434",
    51	        default_model: str = "gemma4:e4b",
    52	        *,
    53	        timeout_s: float = 30.0,
    54	    ) -> None:
    55	        self._base_url = base_url.rstrip("/")
    56	        self._default_model = default_model
    57	        self._timeout_s = timeout_s
    58	        self._session: aiohttp.ClientSession | None = None
    59	
    60	    async def _get_session(self) -> aiohttp.ClientSession:
    61	        if self._session is None or self._session.closed:
    62	            self._session = aiohttp.ClientSession()
    63	        return self._session
    64	
    65	    async def close(self) -> None:
    66	        """Close the underlying HTTP session."""
    67	        if self._session is not None and not self._session.closed:
    68	            await self._session.close()
    69	            self._session = None
    70	
    71	    async def generate(
    72	        self,
    73	        prompt: str,
    74	        *,
    75	        model: str | None = None,
    76	        max_tokens: int = 2048,
    77	        temperature: float = 0.3,
    78	        system: str | None = None,
    79	        num_ctx: int | None = None,
    80	    ) -> GenerationResult:
    81	        """Call Ollama /api/generate and return a GenerationResult.
    82	
    83	        On timeout: returns truncated=True with empty text (does not raise).
    84	
    85	        Raises:
    86	            OllamaUnavailableError: server not reachable
    87	            OllamaModelMissingError: model not pulled
    88	        """
    89	        effective_model = model or self._default_model
    90	        url = f"{self._base_url}{_GENERATE_PATH}"
    91	        options: dict[str, Any] = {
    92	            "num_predict": max_tokens,
    93	            "temperature": temperature,
    94	        }
    95	        if num_ctx is not None:
    96	            options["num_ctx"] = num_ctx
    97	        payload: dict[str, Any] = {
    98	            "model": effective_model,
    99	            "prompt": prompt,
   100	            "stream": False,
   101	            "options": options,
   102	        }
   103	        if system is not None:
   104	            payload["system"] = system
   105	
   106	        session = await self._get_session()
   107	        t0 = time.monotonic()
   108	
   109	        try:
   110	            async with asyncio.timeout(self._timeout_s):
   111	                async with session.post(url, json=payload) as resp:
   112	                    data: dict[str, Any] = await resp.json(content_type=None)
   113	        except TimeoutError:
   114	            latency_s = time.monotonic() - t0
   115	            logger.warning(
   116	                "OllamaClient: timeout after %.1fs for model %s",
   117	                latency_s,
   118	                effective_model,
   119	            )
   120	            return GenerationResult(
   121	                text="",
   122	                tokens_in=0,
   123	                tokens_out=0,
   124	                latency_s=latency_s,
   125	                model=effective_model,
   126	                truncated=True,
   127	            )
   128	        except aiohttp.ClientConnectorError as exc:
   129	            raise OllamaUnavailableError(
   130	                f"Cannot connect to Ollama at {self._base_url}: {exc}"
   131	            ) from exc
   132	        except aiohttp.ClientError as exc:
   133	            raise OllamaUnavailableError(f"Ollama HTTP error: {exc}") from exc
   134	
   135	        latency_s = time.monotonic() - t0
   136	
   137	        if "error" in data:
   138	            err = str(data["error"])
   139	            if "not found" in err.lower():
   140	                raise OllamaModelMissingError(effective_model)
   141	            raise OllamaUnavailableError(f"Ollama error: {err}")
   142	
   143	        return GenerationResult(
   144	            text=data.get("response", ""),
   145	            tokens_in=data.get("prompt_eval_count", 0),
   146	            tokens_out=data.get("eval_count", 0),
   147	            latency_s=latency_s,
   148	            model=data.get("model", effective_model),
   149	        )

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/core/event_logger.py | nl -ba | sed -n '1,180p' && git show feat/f29-periodic-reports:src/cryodaq/core/event_bus.py | nl -ba | sed -n '1,140p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Automatic event logging for system actions."""
     2	
     3	from __future__ import annotations
     4	
     5	import logging
     6	from datetime import UTC, datetime
     7	from typing import TYPE_CHECKING, Any
     8	
     9	if TYPE_CHECKING:
    10	    from cryodaq.core.event_bus import EventBus
    11	
    12	logger = logging.getLogger(__name__)
    13	
    14	
    15	class EventLogger:
    16	    """Logs system events to the operator journal via SQLiteWriter."""
    17	
    18	    def __init__(
    19	        self,
    20	        writer: Any,
    21	        experiment_manager: Any,
    22	        *,
    23	        event_bus: EventBus | None = None,
    24	    ) -> None:
    25	        self._writer = writer
    26	        self._em = experiment_manager
    27	        self._event_bus = event_bus
    28	
    29	    async def log_event(
    30	        self,
    31	        event_type: str,
    32	        message: str,
    33	        *,
    34	        extra_tags: list[str] | None = None,
    35	    ) -> None:
    36	        """Write an auto-log entry to SQLite and publish to EventBus."""
    37	        experiment_id = self._em.active_experiment_id
    38	        try:
    39	            await self._writer.append_operator_log(
    40	                message=message,
    41	                author="system",
    42	                source="auto",
    43	                experiment_id=experiment_id,
    44	                tags=["auto", event_type, *(extra_tags or [])],
    45	            )
    46	        except Exception:
    47	            logger.warning("Failed to auto-log event: %s", message, exc_info=True)
    48	
    49	        if self._event_bus is not None:
    50	            from cryodaq.core.event_bus import EngineEvent
    51	
    52	            try:
    53	                await self._event_bus.publish(
    54	                    EngineEvent(
    55	                        event_type="event_logged",
    56	                        timestamp=datetime.now(UTC),
    57	                        payload={"event_type": event_type, "message": message},
    58	                        experiment_id=experiment_id,
    59	                    )
    60	                )
    61	            except Exception:
    62	                logger.warning("EventBus publish failed in log_event", exc_info=True)
     1	"""Lightweight pub/sub event bus for engine events (not Reading data)."""
     2	
     3	from __future__ import annotations
     4	
     5	import asyncio
     6	import logging
     7	from dataclasses import dataclass
     8	from datetime import datetime
     9	from typing import Any
    10	
    11	logger = logging.getLogger(__name__)
    12	
    13	
    14	@dataclass
    15	class EngineEvent:
    16	    """An engine-level event published to EventBus subscribers."""
    17	
    18	    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
    19	    timestamp: datetime
    20	    payload: dict[str, Any]
    21	    experiment_id: str | None = None
    22	
    23	
    24	class EventBus:
    25	    """Lightweight pub/sub for engine events (not Reading data).
    26	
    27	    Subscribers receive a dedicated asyncio.Queue. Publish is non-blocking:
    28	    a full queue logs a warning and drops the event rather than blocking
    29	    the engine event loop.
    30	    """
    31	
    32	    def __init__(self) -> None:
    33	        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}
    34	
    35	    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
    36	        """Register a named subscriber and return its dedicated queue."""
    37	        if name in self._subscribers:
    38	            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
    39	        q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
    40	        self._subscribers[name] = q
    41	        return q
    42	
    43	    def unsubscribe(self, name: str) -> None:
    44	        """Remove a subscriber by name. No-op if not registered."""
    45	        self._subscribers.pop(name, None)
    46	
    47	    async def publish(self, event: EngineEvent) -> None:
    48	        """Fan out event to all subscriber queues (non-blocking; drops on full)."""
    49	        for name, q in list(self._subscribers.items()):
    50	            try:
    51	                q.put_nowait(event)
    52	            except asyncio.QueueFull:
    53	                logger.warning(
    54	                    "EventBus: subscriber '%s' queue full, dropping %s",
    55	                    name,
    56	                    event.event_type,
    57	                )
    58	
    59	    @property
    60	    def subscriber_count(self) -> int:
    61	        """Number of currently registered subscribers."""
    62	        return len(self._subscribers)

exec
/opt/homebrew/bin/bash -lc "git grep -n \"log_event(.*phase\\|phase_transition\\|log_event(.*alarm\\|extra_tags=.*alarm\\|extra_tags=.*phase\\|extra_tags=.*calibration\" feat/f29-periodic-reports -- src/cryodaq tests | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py:134:        phase_entries = [e for e in entries if "phase_transition" in e.tags]
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py:147:            and "phase_transition" not in e.tags
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/context_builder.py:532:            "phase_transitions_section": _format_log_entries(self.phase_entries) or "(нет)",
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:260:{phase_transitions_section}
feat/f29-periodic-reports:src/cryodaq/core/event_bus.py:18:    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
feat/f29-periodic-reports:src/cryodaq/engine.py:525:                "phase_transitions": [
feat/f29-periodic-reports:src/cryodaq/engine.py:1724:                    await event_logger.log_event("phase", f"Фаза: → {phase}")
feat/f29-periodic-reports:src/cryodaq/engine.py:1728:                            event_type="phase_transition",
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/dashboard_view.py:86:                self._phase_widget.phase_transition_requested.connect(
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/dashboard_view.py:87:                    self._on_phase_transition_requested
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/dashboard_view.py:208:    def _on_phase_transition_requested(self, phase: str) -> None:
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/phase_aware_widget.py:41:    phase_transition_requested = Signal(str)
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/phase_aware_widget.py:414:                self.phase_transition_requested.emit(PHASE_ORDER[idx - 1])
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/phase_aware_widget.py:424:                self.phase_transition_requested.emit(PHASE_ORDER[idx + 1])
feat/f29-periodic-reports:src/cryodaq/gui/dashboard/phase_aware_widget.py:433:            self.phase_transition_requested.emit(target)
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_context.py:32:        _make_entry("Phase → COOL", ("auto", "phase_transition")),
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_context.py:74:        _make_entry("Phase", ("auto", "phase_transition")),
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_context.py:104:    assert "phase_transitions_section" in tmpl
feat/f29-periodic-reports:tests/core/test_event_bus.py:32:        event_type="phase_transition",
feat/f29-periodic-reports:tests/core/test_event_bus.py:37:    assert ev.event_type == "phase_transition"
feat/f29-periodic-reports:tests/gui/dashboard/test_phase_aware_widget.py:102:    w.phase_transition_requested.connect(lambda p: received.append(p))
feat/f29-periodic-reports:tests/gui/dashboard/test_phase_aware_widget.py:117:    w.phase_transition_requested.connect(lambda p: received.append(p))
feat/f29-periodic-reports:tests/gui/dashboard/test_phase_aware_widget.py:132:    w.phase_transition_requested.connect(lambda p: received.append(p))
feat/f29-periodic-reports:tests/gui/dashboard/test_phase_aware_widget.py:147:    w.phase_transition_requested.connect(lambda p: received.append(p))
feat/f29-periodic-reports:tests/gui/shell/views/test_analytics_widget_cooldown_history.py:58:        "phase_transitions": [
feat/f29-periodic-reports:tests/test_engine_cooldown_history.py:124:    assert any(p["phase"] == "cooldown" for p in c["phase_transitions"])

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/engine.py | nl -ba | sed -n '1990,2025p;2100,2140p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
  1990	    await interlock_engine.start()
  1991	    await plugin_pipeline.start()
  1992	    if cooldown_service is not None:
  1993	        await cooldown_service.start()
  1994	    if periodic_reporter is not None:
  1995	        await periodic_reporter.start()
  1996	    if telegram_bot is not None:
  1997	        await telegram_bot.start()
  1998	    if gemma_agent is not None:
  1999	        try:
  2000	            await gemma_agent.start()
  2001	        except Exception as _gemma_start_exc:
  2002	            logger.warning("AssistantLiveAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
  2003	            gemma_agent = None
  2004	    periodic_report_tick_task: asyncio.Task | None = None
  2005	    if _gemma_config is not None and _gemma_config.periodic_report_enabled:
  2006	        periodic_report_tick_task = asyncio.create_task(
  2007	            _periodic_report_tick(_gemma_config, event_bus, experiment_manager),
  2008	            name="periodic_report_tick",
  2009	        )
  2010	    await scheduler.start()
  2011	    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
  2012	    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
  2013	    alarm_v2_tick_task: asyncio.Task | None = None
  2014	    if _alarm_v2_configs:
  2015	        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
  2016	    sd_feed_task: asyncio.Task | None = None
  2017	    sd_tick_task: asyncio.Task | None = None
  2018	    if sensor_diag is not None:
  2019	        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
  2020	        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
  2021	    vt_feed_task: asyncio.Task | None = None
  2022	    vt_tick_task: asyncio.Task | None = None
  2023	    if vacuum_trend is not None:
  2024	        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
  2025	        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
  2100	        sd_tick_task.cancel()
  2101	        try:
  2102	            await sd_tick_task
  2103	        except asyncio.CancelledError:
  2104	            pass
  2105	
  2106	    if vt_feed_task is not None:
  2107	        vt_feed_task.cancel()
  2108	        try:
  2109	            await vt_feed_task
  2110	        except asyncio.CancelledError:
  2111	            pass
  2112	    if vt_tick_task is not None:
  2113	        vt_tick_task.cancel()
  2114	        try:
  2115	            await vt_tick_task
  2116	        except asyncio.CancelledError:
  2117	            pass
  2118	    if periodic_report_tick_task is not None:
  2119	        periodic_report_tick_task.cancel()
  2120	        try:
  2121	            await periodic_report_tick_task
  2122	        except asyncio.CancelledError:
  2123	            pass
  2124	    leak_rate_feed_task.cancel()
  2125	    try:
  2126	        await leak_rate_feed_task
  2127	    except asyncio.CancelledError:
  2128	        pass
  2129	
  2130	    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
  2131	    await scheduler.stop()
  2132	    logger.info("Планировщик остановлен")
  2133	
  2134	    await plugin_pipeline.stop()
  2135	    logger.info("Пайплайн плагинов остановлен")
  2136	
  2137	    if cooldown_service is not None:
  2138	        await cooldown_service.stop()
  2139	        logger.info("CooldownService остановлен")
  2140	

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:artifacts/scripts/smoke_f29_periodic_report.py | nl -ba | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	#!/usr/bin/env python3
     2	"""F29 periodic report smoke: real Ollama + EventBus + audit/router path."""
     3	
     4	from __future__ import annotations
     5	
     6	import asyncio
     7	import json
     8	import sys
     9	import time
    10	from dataclasses import dataclass
    11	from datetime import UTC, datetime, timedelta
    12	from pathlib import Path
    13	from unittest.mock import AsyncMock, MagicMock
    14	
    15	sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    16	
    17	from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
    18	from cryodaq.agents.assistant.live.context_builder import ContextBuilder
    19	from cryodaq.agents.assistant.live.output_router import OutputRouter
    20	from cryodaq.agents.assistant.shared.audit import AuditLogger
    21	from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
    22	from cryodaq.core.event_bus import EventBus
    23	from cryodaq.engine import _periodic_report_tick
    24	
    25	
    26	AUDIT_DIR = Path("data/agents/assistant/f29-smoke-audit")
    27	TIMEOUT_S = 120.0
    28	
    29	
    30	@dataclass
    31	class SmokeEntry:
    32	    timestamp: datetime
    33	    message: str
    34	    tags: tuple[str, ...]
    35	    source: str = "auto"
    36	
    37	
    38	def _cyrillic_ratio(text: str) -> float:
    39	    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    40	    alpha = sum(1 for c in text if c.isalpha())
    41	    return cyrillic / max(alpha, 1)
    42	
    43	
    44	def _count_audit_files() -> int:
    45	    today = datetime.now(UTC).strftime("%Y-%m-%d")
    46	    date_dir = AUDIT_DIR / today
    47	    if not date_dir.exists():
    48	        return 0
    49	    return len(list(date_dir.glob("*.json")))
    50	
    51	
    52	async def _wait_for_new_audit(files_before: int) -> dict | None:
    53	    today = datetime.now(UTC).strftime("%Y-%m-%d")
    54	    date_dir = AUDIT_DIR / today
    55	    t0 = time.monotonic()
    56	    while time.monotonic() - t0 < TIMEOUT_S:
    57	        await asyncio.sleep(1.0)
    58	        if not date_dir.exists():
    59	            continue
    60	        files = sorted(date_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
    61	        if len(files) > files_before:
    62	            return json.loads(files[-1].read_text(encoding="utf-8"))
    63	    return None
    64	
    65	
    66	async def _run_tick_once(cfg: AssistantConfig, bus: EventBus, em: MagicMock) -> None:
    67	    """Run the engine timer long enough to publish one scheduled request."""
    68	    sleep_count = 0
    69	
    70	    async def fake_sleep(_delay_s: float) -> None:
    71	        nonlocal sleep_count
    72	        sleep_count += 1
    73	        if sleep_count > 1:
    74	            raise asyncio.CancelledError
    75	        await asyncio.sleep(0)
    76	
    77	    task = asyncio.create_task(_periodic_report_tick(cfg, bus, em, sleep=fake_sleep))
    78	    try:
    79	        await asyncio.sleep(0.2)
    80	    finally:
    81	        task.cancel()
    82	        try:
    83	            await task
    84	        except asyncio.CancelledError:
    85	            pass
    86	
    87	
    88	async def run_smoke() -> bool:
    89	    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    90	    now = datetime.now(UTC)
    91	    entries = [
    92	        SmokeEntry(now - timedelta(minutes=14), "Аларм Т1_высокая: T1=8.5 K", ("auto", "alarm")),
    93	        SmokeEntry(now - timedelta(minutes=12), "Переход фазы: подготовка -> охлаждение", ("auto", "phase_transition")),
    94	        SmokeEntry(now - timedelta(minutes=9), "Operator note: проверена стабильность термопары T1", (), "operator"),
    95	        SmokeEntry(now - timedelta(minutes=5), "Калибровка: поправка T1 +0.02 K", ("auto", "calibration")),
    96	    ]
    97	
    98	    reader = MagicMock()
    99	    reader.get_operator_log = AsyncMock(return_value=entries)
   100	
   101	    em = MagicMock()
   102	    em.active_experiment_id = "f29-дымовой-001"
   103	    em.get_current_phase = MagicMock(return_value="охлаждение")
   104	
   105	    telegram = AsyncMock()
   106	    telegram._send_to_all = AsyncMock()
   107	    event_logger = AsyncMock()
   108	    event_logger.log_event = AsyncMock()
   109	
   110	    bus = EventBus()
   111	    gui_q = await bus.subscribe("smoke_gui")
   112	
   113	    cfg = AssistantConfig(
   114	        enabled=True,
   115	        default_model="gemma4:e2b",
   116	        timeout_s=TIMEOUT_S,
   117	        max_tokens=2048,
   118	        max_concurrent_inferences=1,
   119	        max_calls_per_hour=10,
   120	        output_telegram=True,
   121	        output_operator_log=True,
   122	        output_gui_insight=True,
   123	        audit_enabled=True,
   124	        audit_dir=AUDIT_DIR,
   125	        periodic_report_enabled=True,
   126	        periodic_report_interval_minutes=15,
   127	        periodic_report_skip_if_idle=True,
   128	        periodic_report_min_events=1,
   129	    )
   130	    ollama = OllamaClient(
   131	        base_url="http://localhost:11434",
   132	        default_model="gemma4:e2b",
   133	        timeout_s=TIMEOUT_S,
   134	    )
   135	    agent = AssistantLiveAgent(
   136	        config=cfg,
   137	        event_bus=bus,
   138	        ollama_client=ollama,
   139	        context_builder=ContextBuilder(reader, em),
   140	        audit_logger=AuditLogger(AUDIT_DIR, enabled=True),
   141	        output_router=OutputRouter(
   142	            telegram_bot=telegram,
   143	            event_logger=event_logger,
   144	            event_bus=bus,
   145	            brand_name=cfg.brand_name,
   146	            brand_emoji=cfg.brand_emoji,
   147	        ),
   148	    )
   149	
   150	    await agent.start()
   151	    files_before = _count_audit_files()
   152	    t0 = time.monotonic()
   153	    await _run_tick_once(cfg, bus, em)
   154	    record = await _wait_for_new_audit(files_before)
   155	    latency = time.monotonic() - t0
   156	
   157	    if record is None:
   158	        await agent.stop()
   159	        print("FAIL: no audit record produced")
   160	        return False
   161	
   162	    response = record.get("response", "")
   163	    sent = telegram._send_to_all.call_args[0][0] if telegram._send_to_all.await_count else ""
   164	    gui_event = None
   165	    while not gui_q.empty():
   166	        candidate = gui_q.get_nowait()
   167	        if candidate.event_type == "assistant_insight":
   168	            gui_event = candidate
   169	
   170	    ratio = _cyrillic_ratio(response)
   171	    print("ACTIVE WINDOW")
   172	    print(f"latency_wall_s={latency:.1f}")
   173	    print(f"latency_audit_s={record.get('latency_s')}")
   174	    print(f"tokens={record.get('tokens')}")
   175	    print(f"russian_ratio={ratio:.1%}")
   176	    print(f"dispatched={record.get('outputs_dispatched')}")
   177	    print(f"telegram_prefix_ok={sent.startswith('🤖 Гемма (отчёт за час):')}")
   178	    print(f"gui_trigger={gui_event.payload.get('trigger_event_type') if gui_event else None}")
   179	    print("response:")
   180	    print(response)
   181	
   182	    reader.get_operator_log = AsyncMock(return_value=[])
   183	    before_idle_telegram = telegram._send_to_all.await_count
   184	    before_idle_log = event_logger.log_event.await_count
   185	    before_idle_audits = _count_audit_files()
   186	    await _run_tick_once(cfg, bus, em)
   187	    await asyncio.sleep(2.0)
   188	    idle_skipped = (
   189	        telegram._send_to_all.await_count == before_idle_telegram
   190	        and event_logger.log_event.await_count == before_idle_log
   191	        and _count_audit_files() == before_idle_audits
   192	    )
   193	    print("\nIDLE WINDOW")
   194	    print(f"idle_skipped={idle_skipped}")
   195	
   196	    await agent.stop()
   197	
   198	    quality_ok = len(response) > 50 and ratio >= 0.9
   199	    grounded_ok = all(marker in response for marker in ("T1",)) and "охлажд" in response.lower()
   200	    dispatch_ok = (
   201	        sent.startswith("🤖 Гемма (отчёт за час):")
   202	        and "telegram" in record.get("outputs_dispatched", [])
   203	        and "operator_log" in record.get("outputs_dispatched", [])
   204	        and "gui_insight" in record.get("outputs_dispatched", [])
   205	        and gui_event is not None
   206	    )
   207	    return quality_ok and grounded_ok and dispatch_ok and idle_skipped
   208	
   209	
   210	if __name__ == "__main__":
   211	    ok = asyncio.run(run_smoke())
   212	    sys.exit(0 if ok else 1)

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/notifications/telegram.py | nl -ba | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Уведомления о тревогах через Telegram Bot API.
     2	
     3	TelegramNotifier — async-коллбэк для AlarmEngine.  Отправляет
     4	форматированные сообщения в указанный чат при активации/сбросе тревог.
     5	
     6	Конфигурация (config/notifications.yaml):
     7	
     8	    telegram:
     9	      bot_token: "123456:ABC-DEF..."
    10	      chat_id: -1001234567890
    11	      send_cleared: true           # отправлять ли уведомление о сбросе
    12	      timeout_s: 10.0              # таймаут HTTP-запроса
    13	"""
    14	
    15	from __future__ import annotations
    16	
    17	import logging
    18	from datetime import UTC
    19	from pathlib import Path
    20	from typing import Any
    21	
    22	import aiohttp
    23	import yaml
    24	
    25	from cryodaq.notifications._secrets import SecretStr
    26	
    27	logger = logging.getLogger(__name__)
    28	
    29	# Эмодзи по уровню критичности
    30	_SEVERITY_EMOJI: dict[str, str] = {
    31	    "info": "ℹ️",
    32	    "warning": "⚠️",
    33	    "critical": "🚨",
    34	}
    35	
    36	# Эмодзи по типу события
    37	_EVENT_EMOJI: dict[str, str] = {
    38	    "activated": "🔔",
    39	    "cleared": "✅",
    40	    "acknowledged": "👁",
    41	}
    42	
    43	
    44	class TelegramNotifier:
    45	    """Отправка уведомлений о тревогах через Telegram.
    46	
    47	    Используется как notifier-коллбэк для AlarmEngine::
    48	
    49	        notifier = TelegramNotifier.from_config(Path("config/notifications.yaml"))
    50	        alarm_engine = AlarmEngine(broker, notifiers=[notifier])
    51	
    52	    Параметры
    53	    ----------
    54	    bot_token:
    55	        Токен Telegram-бота (от @BotFather).
    56	    chat_id:
    57	        ID чата или группы для отправки уведомлений.
    58	    send_cleared:
    59	        Отправлять ли уведомления при сбросе тревоги.  По умолчанию True.
    60	    timeout_s:
    61	        Таймаут HTTP-запроса к Telegram API.  По умолчанию 10 с.
    62	    """
    63	
    64	    def __init__(
    65	        self,
    66	        bot_token: str | SecretStr,
    67	        chat_id: int | str,
    68	        *,
    69	        send_cleared: bool = True,
    70	        timeout_s: float = 10.0,
    71	    ) -> None:
    72	        # Phase 2b K.1: store the token in a SecretStr wrapper so accidental
    73	        # repr/str/f-string never leaks it. The API URL is computed on demand.
    74	        self._bot_token = bot_token if isinstance(bot_token, SecretStr) else SecretStr(bot_token)
    75	        self._chat_id = chat_id
    76	        self._send_cleared = send_cleared
    77	        self._timeout_s = timeout_s
    78	        self._session: aiohttp.ClientSession | None = None
    79	
    80	    def _build_api_url(self, method: str = "sendMessage") -> str:
    81	        """Compute the Telegram API URL on demand. Never store as attribute."""
    82	        return f"https://api.telegram.org/bot{self._bot_token.get_secret_value()}/{method}"
    83	
    84	    @classmethod
    85	    def from_config(cls, config_path: Path) -> TelegramNotifier:
    86	        """Создать notifier из YAML-файла конфигурации.
    87	
    88	        Ожидаемая структура::
    89	
    90	            telegram:
    91	              bot_token: "..."
    92	              chat_id: ...
    93	              send_cleared: true
    94	              timeout_s: 10.0
    95	
    96	        Параметры
    97	        ----------
    98	        config_path:
    99	            Путь к config/notifications.yaml.
   100	
   101	        Исключения
   102	        ----------
   103	        FileNotFoundError:  Файл не найден.
   104	        KeyError:           Отсутствуют обязательные поля.
   105	        """
   106	        if not config_path.exists():
   107	            raise FileNotFoundError(f"Файл конфигурации уведомлений не найден: {config_path}")
   108	
   109	        with config_path.open(encoding="utf-8") as fh:
   110	            raw: dict[str, Any] = yaml.safe_load(fh)
   111	
   112	        tg = raw["telegram"]
   113	        return cls(
   114	            bot_token=str(tg["bot_token"]),
   115	            chat_id=tg["chat_id"],
   116	            send_cleared=bool(tg.get("send_cleared", True)),
   117	            timeout_s=float(tg.get("timeout_s", 10.0)),
   118	        )
   119	
   120	    async def __call__(self, event: Any) -> None:
   121	        """Async-коллбэк для AlarmEngine.
   122	
   123	        Параметры
   124	        ----------
   125	        event:
   126	            Экземпляр AlarmEvent (из cryodaq.core.alarm).
   127	        """
   128	        # Пропустить cleared, если не настроено
   129	        if event.event_type == "cleared" and not self._send_cleared:
   130	            return
   131	
   132	        # Пропустить acknowledged (внутреннее событие)
   133	        if event.event_type == "acknowledged":
   134	            return
   135	
   136	        text = self._format_message(event)
   137	        await self._send(text)
   138	
   139	    # ------------------------------------------------------------------
   140	    # Форматирование сообщения
   141	    # ------------------------------------------------------------------
   142	
   143	    def _format_message(self, event: Any) -> str:
   144	        """Сформировать текст уведомления."""
   145	        severity_str = (
   146	            event.severity.value if hasattr(event.severity, "value") else str(event.severity)
   147	        )
   148	        severity_emoji = _SEVERITY_EMOJI.get(severity_str, "❓")
   149	        event_emoji = _EVENT_EMOJI.get(event.event_type, "")
   150	
   151	        # Время в московском часовом поясе (UTC+3) — стандарт для ФИАН
   152	        ts = event.timestamp
   153	        if ts.tzinfo is None:
   154	            ts = ts.replace(tzinfo=UTC)
   155	        time_str = ts.strftime("%H:%M:%S %d.%m.%Y")
   156	
   157	        if event.event_type == "activated":
   158	            header = f"{event_emoji} {severity_emoji} ТРЕВОГА"
   159	        elif event.event_type == "cleared":
   160	            header = f"{event_emoji} Тревога снята"
   161	        else:
   162	            header = f"{event_emoji} {event.event_type}"
   163	
   164	        lines = [
   165	            header,
   166	            "",
   167	            f"<b>{event.alarm_name}</b>",
   168	            f"Канал: <code>{event.channel}</code>",
   169	            f"Значение: <b>{event.value:.4g}</b>",
   170	            f"Порог: {event.threshold:.4g}",
   171	            f"Уровень: {severity_str.upper()}",
   172	            f"Время: {time_str}",
   173	        ]
   174	
   175	        return "\n".join(lines)
   176	
   177	    # ------------------------------------------------------------------
   178	    # Отправка HTTP-запроса
   179	    # ------------------------------------------------------------------
   180	
   181	    async def _get_session(self) -> aiohttp.ClientSession:
   182	        if self._session is None or self._session.closed:
   183	            self._session = aiohttp.ClientSession(
   184	                timeout=aiohttp.ClientTimeout(total=self._timeout_s)
   185	            )
   186	        return self._session
   187	
   188	    async def close(self) -> None:
   189	        if self._session and not self._session.closed:
   190	            await self._session.close()
   191	            self._session = None
   192	
   193	    async def send_message(self, chat_id: int | str, text: str) -> None:
   194	        """Отправить произвольное сообщение в указанный chat_id."""
   195	        payload = {
   196	            "chat_id": chat_id,
   197	            "text": text,
   198	            "parse_mode": "HTML",
   199	            "disable_web_page_preview": True,
   200	        }
   201	        try:
   202	            session = await self._get_session()
   203	            async with session.post(self._build_api_url("sendMessage"), json=payload) as resp:
   204	                if resp.status != 200:
   205	                    body = await resp.text()
   206	                    logger.error("Telegram API ответил %d: %s", resp.status, body[:200])
   207	        except Exception as exc:
   208	            logger.error("Ошибка отправки Telegram-уведомления: %s", exc)
   209	
   210	    async def _send(self, text: str) -> None:
   211	        """Отправить сообщение через Telegram Bot API.
   212	
   213	        Использует aiohttp для асинхронной отправки.  При недоступности
   214	        библиотеки или ошибке сети — логирует и продолжает работу.
   215	        """
   216	        payload = {
   217	            "chat_id": self._chat_id,
   218	            "text": text,
   219	            "parse_mode": "HTML",
   220	            "disable_web_page_preview": True,

exec
/opt/homebrew/bin/bash -lc "git grep -n \"sanitize\\|Markdown\\|LaTeX\\|latex\\|\\\\"'$'"\\\\|_send_to_all\\|parse_mode\" feat/f29-periodic-reports -- src/cryodaq/agents src/cryodaq/notifications src/cryodaq/core tests/agents tests/notifications | head -160" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/output_router.py:69:                        await self._telegram._send_to_all(prefixed)
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:28:- 80-150 слов. Telegram-friendly Markdown (жирный, курсив — ok, заголовки — нет).
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:66:- 80-120 слов. Telegram-friendly Markdown.
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:101:- НЕ используй Markdown (жирный, курсив, заголовки). Текст пойдёт в DOCX напрямую.
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:128:Напиши аннотацию к научному отчёту. Только русский язык, формальный стиль, без Markdown.
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:148:- 80-130 слов. Telegram-friendly Markdown (жирный, курсив — ok).
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:187:- 60-100 слов. Telegram-friendly Markdown (жирный, курсив — ok).
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:223:- 120-200 слов. Telegram-friendly Markdown.
feat/f29-periodic-reports:src/cryodaq/agents/assistant/live/prompts.py:247:- 100-200 слов максимум. Telegram-friendly Markdown (жирный, курсив — ok).
feat/f29-periodic-reports:src/cryodaq/agents/assistant/shared/report_intro.py:85:    Returns the generated text (plain Russian, no Markdown), or None if
feat/f29-periodic-reports:src/cryodaq/core/sensor_diagnostics.py:50:    re.compile(r"^Keithley.*/(voltage|current|power|resistance)$"),
feat/f29-periodic-reports:src/cryodaq/core/sensor_diagnostics.py:57:    re.compile(r"^[ТT]\d+(\b|\s|/|$)"),  # T-prefixed cryo channels
feat/f29-periodic-reports:src/cryodaq/core/sensor_diagnostics.py:58:    re.compile(r"/[ТT]\d+(\b|\s|/|$)"),  # …with instrument prefix
feat/f29-periodic-reports:src/cryodaq/notifications/periodic_report.py:493:            form.add_field("parse_mode", "HTML")
feat/f29-periodic-reports:src/cryodaq/notifications/telegram.py:198:            "parse_mode": "HTML",
feat/f29-periodic-reports:src/cryodaq/notifications/telegram.py:219:            "parse_mode": "HTML",
feat/f29-periodic-reports:src/cryodaq/notifications/telegram_commands.py:445:                "parse_mode": "HTML",
feat/f29-periodic-reports:src/cryodaq/notifications/telegram_commands.py:456:    async def _send_to_all(self, text: str) -> None:
feat/f29-periodic-reports:src/cryodaq/notifications/telegram_commands.py:462:            logger.debug("_send_to_all: нет allowed_chat_ids, сообщение не отправлено")
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:88:        telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:200:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:207:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:208:    sent_text = telegram._send_to_all.call_args[0][0]
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:314:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:321:    telegram._send_to_all.assert_not_awaited()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:357:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:390:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:432:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:470:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:514:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_alarm_flow.py:544:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_diagnostic.py:98:        telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_diagnostic.py:194:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_diagnostic.py:210:    assert telegram._send_to_all.await_count == 2
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:83:        telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:125:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:133:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:134:    sent = telegram._send_to_all.call_args[0][0]
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:141:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:150:    telegram._send_to_all.assert_not_awaited()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:157:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:166:    telegram._send_to_all.assert_awaited_once()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:172:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:189:    telegram._send_to_all.assert_not_awaited()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:195:    telegram._send_to_all = AsyncMock()
feat/f29-periodic-reports:tests/agents/assistant/test_periodic_report_handler.py:204:    telegram._send_to_all.assert_not_awaited()

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/notifications/telegram_commands.py | nl -ba | sed -n '430,475p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   430	        )
   431	        if result.get("ok"):
   432	            await self._send(chat_id, f"✅ Фаза: → {phase}")
   433	        else:
   434	            await self._send(chat_id, f"❌ Ошибка: {result.get('error', '?')}")
   435	
   436	    # ------------------------------------------------------------------
   437	    # Send
   438	    # ------------------------------------------------------------------
   439	
   440	    async def _send(self, chat_id: int, text: str) -> None:
   441	        try:
   442	            payload = {
   443	                "chat_id": chat_id,
   444	                "text": text,
   445	                "parse_mode": "HTML",
   446	                "disable_web_page_preview": True,
   447	            }
   448	            session = await self._get_session()
   449	            async with session.post(f"{self._api}/sendMessage", json=payload) as resp:
   450	                if resp.status != 200:
   451	                    body = await resp.text()
   452	                    logger.error("Telegram sendMessage %d: %s", resp.status, body[:200])
   453	        except Exception as exc:
   454	            logger.error("Ошибка отправки Telegram: %s", exc)
   455	
   456	    async def _send_to_all(self, text: str) -> None:
   457	        """Отправить текст всем разрешённым chat_id (или только первому если список пуст)."""
   458	        if self._allowed_ids:
   459	            for chat_id in self._allowed_ids:
   460	                await self._send(chat_id, text)
   461	        else:
   462	            logger.debug("_send_to_all: нет allowed_chat_ids, сообщение не отправлено")

exec
/opt/homebrew/bin/bash -lc "git show feat/f29-periodic-reports:src/cryodaq/gui/shell/views/assistant_insight_panel.py | nl -ba | sed -n '1,180p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""AssistantInsightPanel — operator-facing assistant insight viewer.
     2	
     3	Displays the last 10 LLM-generated insights from AssistantLiveAgent.
     4	Populated via push_insight() by the shell when it receives
     5	assistant_insight events.
     6	
     7	DS compliance: all colors and fonts from theme tokens.
     8	No hardcoded hex/px values.
     9	"""
    10	
    11	from __future__ import annotations
    12	
    13	import logging
    14	from collections import deque
    15	from datetime import UTC, datetime
    16	from typing import NamedTuple
    17	
    18	from PySide6.QtCore import Qt
    19	from PySide6.QtGui import QFont
    20	from PySide6.QtWidgets import (
    21	    QFrame,
    22	    QHBoxLayout,
    23	    QLabel,
    24	    QScrollArea,
    25	    QSizePolicy,
    26	    QVBoxLayout,
    27	    QWidget,
    28	)
    29	
    30	from cryodaq.gui import theme
    31	
    32	logger = logging.getLogger(__name__)
    33	
    34	_MAX_INSIGHTS = 10
    35	
    36	# Trigger type → (short label, status color token)
    37	_TRIGGER_META: dict[str, tuple[str, str]] = {
    38	    "alarm_fired": ("АЛАРМ", theme.STATUS_WARNING),
    39	    "experiment_finalize": ("ЭКСП", theme.STATUS_INFO),
    40	    "experiment_stop": ("ЭКСП", theme.STATUS_INFO),
    41	    "experiment_abort": ("ПРЕРВАН", theme.STATUS_FAULT),
    42	    "sensor_anomaly_critical": ("ДАТЧИК", theme.STATUS_FAULT),
    43	    "shift_handover_request": ("СМЕНА", theme.STATUS_OK),
    44	    "periodic_report_request": ("ОТЧЁТ", theme.STATUS_INFO),
    45	}
    46	_DEFAULT_META = ("СОБЫТИЕ", theme.STATUS_STALE)
    47	
    48	
    49	class _InsightEntry(NamedTuple):
    50	    text: str
    51	    trigger_event_type: str
    52	    timestamp: datetime
    53	
    54	
    55	class _TriggerChip(QLabel):
    56	    """Colored label chip showing trigger type."""
    57	
    58	    def __init__(self, trigger_event_type: str, parent: QWidget | None = None) -> None:
    59	        super().__init__(parent)
    60	        label, color = _TRIGGER_META.get(trigger_event_type, _DEFAULT_META)
    61	        self.setText(label)
    62	        self.setFixedHeight(18)
    63	        font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
    64	        font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    65	        self.setFont(font)
    66	        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
    67	        self.setContentsMargins(6, 0, 6, 0)
    68	        self.setStyleSheet(
    69	            f"background: {color}; color: {theme.BACKGROUND}; border-radius: 3px;"
    70	        )
    71	
    72	
    73	class _InsightCard(QFrame):
    74	    """Single insight card: timestamp chip + trigger chip + LLM text."""
    75	
    76	    def __init__(self, entry: _InsightEntry, parent: QWidget | None = None) -> None:
    77	        super().__init__(parent)
    78	        self.setFrameShape(QFrame.Shape.NoFrame)
    79	        self.setStyleSheet(
    80	            f"background: {theme.SURFACE_CARD}; border-radius: 6px;"
    81	            f" border: 1px solid {theme.BORDER_SUBTLE};"
    82	        )
    83	
    84	        root = QVBoxLayout(self)
    85	        root.setContentsMargins(10, 8, 10, 8)
    86	        root.setSpacing(6)
    87	
    88	        # Header row: timestamp + trigger chip
    89	        header = QHBoxLayout()
    90	        header.setSpacing(8)
    91	
    92	        ts_label = QLabel(entry.timestamp.astimezone().strftime("%H:%M:%S"))
    93	        ts_font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
    94	        ts_label.setFont(ts_font)
    95	        ts_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
    96	        header.addWidget(ts_label)
    97	
    98	        header.addWidget(_TriggerChip(entry.trigger_event_type))
    99	        header.addStretch()
   100	        root.addLayout(header)
   101	
   102	        # LLM text
   103	        text_label = QLabel(entry.text)
   104	        text_label.setWordWrap(True)
   105	        text_label.setTextInteractionFlags(
   106	            Qt.TextInteractionFlag.TextSelectableByMouse
   107	        )
   108	        text_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_SM)
   109	        text_label.setFont(text_font)
   110	        text_label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
   111	        root.addWidget(text_label)
   112	
   113	
   114	class AssistantInsightPanel(QWidget):
   115	    """Panel displaying last N assistant insights.
   116	
   117	    Public API:
   118	      push_insight(text, trigger_event_type, timestamp)  — add one insight
   119	      clear()                                             — remove all insights
   120	    """
   121	
   122	    def __init__(
   123	        self,
   124	        parent: QWidget | None = None,
   125	        *,
   126	        brand_name: str = "Гемма",
   127	        brand_emoji: str = "🤖",
   128	    ) -> None:
   129	        super().__init__(parent)
   130	        self._brand_name = brand_name
   131	        self._brand_emoji = brand_emoji
   132	        self._entries: deque[_InsightEntry] = deque(maxlen=_MAX_INSIGHTS)
   133	        self._setup_ui()
   134	
   135	    def _setup_ui(self) -> None:
   136	        self.setStyleSheet(f"background: {theme.BACKGROUND};")
   137	
   138	        root = QVBoxLayout(self)
   139	        root.setContentsMargins(0, 0, 0, 0)
   140	        root.setSpacing(0)
   141	
   142	        # Panel header
   143	        header_frame = QFrame()
   144	        header_frame.setFixedHeight(40)
   145	        header_frame.setStyleSheet(
   146	            f"background: {theme.SURFACE_PANEL};"
   147	            f" border-bottom: 1px solid {theme.BORDER};"
   148	        )
   149	        header_layout = QHBoxLayout(header_frame)
   150	        header_layout.setContentsMargins(12, 0, 12, 0)
   151	
   152	        title = QLabel(f"{self._brand_emoji} {self._brand_name} — ИИ аналитика")
   153	        title_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
   154	        title_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
   155	        title.setFont(title_font)
   156	        title.setStyleSheet(f"color: {theme.FOREGROUND};")
   157	        header_layout.addWidget(title)
   158	        header_layout.addStretch()
   159	
   160	        self._count_label = QLabel("")
   161	        count_font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
   162	        self._count_label.setFont(count_font)
   163	        self._count_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
   164	        header_layout.addWidget(self._count_label)
   165	
   166	        root.addWidget(header_frame)
   167	
   168	        # Scroll area for insight cards
   169	        scroll = QScrollArea()
   170	        scroll.setWidgetResizable(True)
   171	        scroll.setFrameShape(QFrame.Shape.NoFrame)
   172	        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
   173	        scroll.setStyleSheet(f"background: {theme.BACKGROUND};")
   174	
   175	        self._cards_widget = QWidget()
   176	        self._cards_widget.setStyleSheet(f"background: {theme.BACKGROUND};")
   177	        self._cards_layout = QVBoxLayout(self._cards_widget)
   178	        self._cards_layout.setContentsMargins(12, 12, 12, 12)
   179	        self._cards_layout.setSpacing(8)
   180	        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

codex
The strongest issues are now narrowed to behavior, not style: rate-limit admission is not atomic, phase logs are categorized under “other,” and the Telegram path asks for Markdown while the sender uses HTML with no cleanup. I’m running the focused tests once so I can separate confirmed regressions from coverage-only notes.
exec
/opt/homebrew/bin/bash -lc 'pytest -q tests/agents/assistant/test_engine_periodic_report_tick.py tests/agents/assistant/test_periodic_report_config.py tests/agents/assistant/test_periodic_report_context.py tests/agents/assistant/test_periodic_report_handler.py' in /Users/vladimir/Projects/cryodaq
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: pytest: command not found

codex
`pytest` is not on PATH in this shell, so I’m checking the project runner next rather than treating that as a code failure.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,180p' pyproject.toml" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cryodaq"
version = "0.44.0"
description = "Система сбора данных для криогенной лаборатории (АКЦ ФИАН, Millimetron)"
requires-python = ">=3.12"
license = { file = "LICENSE" }
authors = [
    { name = "Vladimir Fomenko" },
]
dependencies = [
    # Phase 2c M.1: upper bounds added so a future major-version bump
    # cannot silently break the bundle build. Lockfile in
    # requirements-lock.txt pins exact versions for reproducible builds.
    "pyside6>=6.6,<7",
    "pyqtgraph>=0.13,<0.14",
    "pyvisa>=1.14,<2",
    "pyserial-asyncio>=0.6,<1",
    "pyzmq>=25,<27",
    "h5py>=3.10,<4",
    "pyyaml>=6.0,<7",
    "msgpack>=1.0,<2",
    "matplotlib>=3.8,<4",
    "aiohttp>=3.9.5,<4",
    "numpy>=1.26,<3",
    "scipy>=1.12,<2",
    "openpyxl>=3.1,<4",
    "python-docx>=1.1,<2",
    "pyqtdarktheme-fork>=2.3.6,<3",
    # IV.3 Finding 4: ToolRail uses qtawesome to render Phosphor icons
    # at runtime instead of shipping Lucide SVG files. Phosphor has
    # 1200+ icons vs. 10 SVGs previously; theming falls out naturally
    # because qta.icon(color=...) renders fresh on each call.
    "qtawesome>=1.4,<2",
    # IV.4 Finding 1: pyarrow promoted from [archive] extra to base.
    # Backend already exports Parquet best-effort on finalize; optional
    # install meant silent skip with "pyarrow not installed" warning
    # whenever the lab PC missed the extras. UI gains an explicit
    # Parquet export button in the same commit, so the feature must
    # work out of the box. Adds ~60 MB to the install footprint.
    # Upper bound set to <25 so the lockfile's pyarrow 23.x pin
    # resolves cleanly from the declared spec.
    "pyarrow>=15,<25",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4",
    "pytest-timeout>=2.0",
    "ruff>=0.3",
    "pyinstaller>=6.0",
    "pip-tools>=7.4",
]
web = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
]
# IV.4 Finding 1: archive extra retained as a no-op alias so any
# deployment / CI script pinned to `pip install -e ".[archive]"` keeps
# working. pyarrow now ships in base deps (see above); this list is
# intentionally empty.
archive = []

[project.scripts]
cryodaq-engine = "cryodaq.engine:main"
cryodaq-gui = "cryodaq.gui.app:main"
cryodaq = "cryodaq.launcher:main"
cryodaq-cooldown = "cryodaq.tools.cooldown_cli:main"
# Frozen entry points — used by PyInstaller spec. Call freeze_support()
# BEFORE importing PySide6 / cryodaq submodules to avoid Windows fork bomb.
cryodaq-frozen = "cryodaq._frozen_main:main_launcher"
cryodaq-frozen-engine = "cryodaq._frozen_main:main_engine"
cryodaq-frozen-gui = "cryodaq._frozen_main:main_gui"

[tool.hatch.build.targets.wheel]
packages = ["src/cryodaq"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "ASYNC"]

exec
/opt/homebrew/bin/bash -lc 'rg -n "pytest|uv run|poetry|hatch|pdm" README.md Makefile pyproject.toml tox.ini noxfile.py .github 2>/dev/null' in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
pyproject.toml:2:requires = ["hatchling"]
pyproject.toml:3:build-backend = "hatchling.build"
pyproject.toml:51:    "pytest>=8",
pyproject.toml:52:    "pytest-asyncio>=0.23",
pyproject.toml:53:    "pytest-cov>=4",
pyproject.toml:54:    "pytest-timeout>=2.0",
pyproject.toml:80:[tool.hatch.build.targets.wheel]
pyproject.toml:83:[tool.pytest.ini_options]
README.md:139:Запуск `pytest` без `pip install -e ...` не поддерживается.
README.md:227:python -m pytest tests/core -q
README.md:228:python -m pytest tests/storage -q
README.md:229:python -m pytest tests/drivers -q
README.md:230:python -m pytest tests/analytics -q
README.md:231:python -m pytest tests/gui -q
README.md:232:python -m pytest tests/reporting -q
.github/workflows/main.yml:26:        run: pytest tests/ -x --tb=short -q

exec
/opt/homebrew/bin/bash -lc 'python -m pytest -q tests/agents/assistant/test_engine_periodic_report_tick.py tests/agents/assistant/test_periodic_report_config.py tests/agents/assistant/test_periodic_report_context.py tests/agents/assistant/test_periodic_report_handler.py' in /Users/vladimir/Projects/cryodaq
 exited 127 in 0ms:
/opt/homebrew/bin/bash: line 1: python: command not found

exec
/opt/homebrew/bin/bash -lc 'python3 -m pytest -q tests/agents/assistant/test_engine_periodic_report_tick.py tests/agents/assistant/test_periodic_report_config.py tests/agents/assistant/test_periodic_report_context.py tests/agents/assistant/test_periodic_report_handler.py' in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest

exec
/opt/homebrew/bin/bash -lc 'git rev-parse feat/f29-periodic-reports && git log -1 --oneline feat/f29-periodic-reports' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
ef0a1eb00f8b895b6a0ee9cc259d224813d0a5bf
ef0a1eb release: v0.46.0 — F29 periodic reports

codex
Verdict: CONDITIONAL

Finding 1  
Severity: MEDIUM  
File: `src/cryodaq/agents/assistant/live/agent.py:297`  
Description: Rate limiting is checked before waiting for the inference semaphore, but the call is only recorded after the semaphore is acquired at lines 307-308. With `max_concurrent_inferences=1`, a burst of periodic/alarm events can all pass `_check_rate_limit()` while queued, then execute later and exceed `max_calls_per_hour`.  
Why it matters: A busy alarm period plus periodic reports can overload Ollama and delay operator-critical summaries.  
Recommended fix: Reserve the rate-limit slot atomically before queueing behind the semaphore, or move check+append under a shared lock immediately before generation.

Finding 2  
Severity: MEDIUM  
File: `src/cryodaq/agents/assistant/live/context_builder.py:130`  
Description: `get_operator_log()` failures are swallowed at debug level and converted into `entries=[]`; then `_handle_periodic_report` skips as idle at `src/cryodaq/agents/assistant/live/agent.py:704`. This makes SQLite read failures indistinguishable from truly empty windows and produces no audit record.  
Why it matters: Operators can silently miss an hourly report during storage/read faults.  
Recommended fix: Return a context error flag or raise to handler; log at warning, audit the failure, and avoid applying idle-skip to failed context reads.

Finding 3  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/context_builder.py:134`  
Description: Periodic context looks for phase log entries tagged `"phase_transition"`, but engine phase changes are logged via `event_logger.log_event("phase", ...)` at `src/cryodaq/engine.py:1724`. Those entries fall into “События (прочие)” instead of “Переходы фаз”.  
Why it matters: The report’s phase-transition section can show `(нет)` while actual phase changes happened.  
Recommended fix: Either tag phase log entries as `"phase_transition"` or have the context builder classify `"phase"` tags as phase transitions too.

Finding 4  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/output_router.py:87`  
Description: `prefix_suffix` is applied to Telegram/operator-log text, but GUI insight events publish `"text": llm_output` without the same prefix at lines 91-95. The periodic report label is therefore inconsistent across the three requested channels.  
Why it matters: GUI history loses the same explicit “отчёт за час” framing operators see elsewhere.  
Recommended fix: Include the prefixed text in GUI payload, or add a separate `display_prefix`/`report_kind` field and update GUI tests.

Finding 5  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/prompts.py:247`  
Description: The periodic prompt permits “Telegram-friendly Markdown” but does not prohibit LaTeX/math notation, and `OutputRouter` forwards raw model text to Telegram at `src/cryodaq/agents/assistant/live/output_router.py:69`. This does not address the known `$\rightarrow$` sample-output concern.  
Why it matters: Telegram may display raw math markup, degrading operator readability.  
Recommended fix: Add explicit prompt constraints: no LaTeX, no `$...$`, use plain arrows/units. Prefer also adding a small sanitizer/test for `$\\...$` patterns.

Verification note: I reviewed `feat/f29-periodic-reports` at `ef0a1eb`. I could not run the focused pytest suite because this shell has no `pytest` installed (`python3 -m pytest` reports `No module named pytest`).
tokens used
85 251
Verdict: CONDITIONAL

Finding 1  
Severity: MEDIUM  
File: `src/cryodaq/agents/assistant/live/agent.py:297`  
Description: Rate limiting is checked before waiting for the inference semaphore, but the call is only recorded after the semaphore is acquired at lines 307-308. With `max_concurrent_inferences=1`, a burst of periodic/alarm events can all pass `_check_rate_limit()` while queued, then execute later and exceed `max_calls_per_hour`.  
Why it matters: A busy alarm period plus periodic reports can overload Ollama and delay operator-critical summaries.  
Recommended fix: Reserve the rate-limit slot atomically before queueing behind the semaphore, or move check+append under a shared lock immediately before generation.

Finding 2  
Severity: MEDIUM  
File: `src/cryodaq/agents/assistant/live/context_builder.py:130`  
Description: `get_operator_log()` failures are swallowed at debug level and converted into `entries=[]`; then `_handle_periodic_report` skips as idle at `src/cryodaq/agents/assistant/live/agent.py:704`. This makes SQLite read failures indistinguishable from truly empty windows and produces no audit record.  
Why it matters: Operators can silently miss an hourly report during storage/read faults.  
Recommended fix: Return a context error flag or raise to handler; log at warning, audit the failure, and avoid applying idle-skip to failed context reads.

Finding 3  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/context_builder.py:134`  
Description: Periodic context looks for phase log entries tagged `"phase_transition"`, but engine phase changes are logged via `event_logger.log_event("phase", ...)` at `src/cryodaq/engine.py:1724`. Those entries fall into “События (прочие)” instead of “Переходы фаз”.  
Why it matters: The report’s phase-transition section can show `(нет)` while actual phase changes happened.  
Recommended fix: Either tag phase log entries as `"phase_transition"` or have the context builder classify `"phase"` tags as phase transitions too.

Finding 4  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/output_router.py:87`  
Description: `prefix_suffix` is applied to Telegram/operator-log text, but GUI insight events publish `"text": llm_output` without the same prefix at lines 91-95. The periodic report label is therefore inconsistent across the three requested channels.  
Why it matters: GUI history loses the same explicit “отчёт за час” framing operators see elsewhere.  
Recommended fix: Include the prefixed text in GUI payload, or add a separate `display_prefix`/`report_kind` field and update GUI tests.

Finding 5  
Severity: LOW  
File: `src/cryodaq/agents/assistant/live/prompts.py:247`  
Description: The periodic prompt permits “Telegram-friendly Markdown” but does not prohibit LaTeX/math notation, and `OutputRouter` forwards raw model text to Telegram at `src/cryodaq/agents/assistant/live/output_router.py:69`. This does not address the known `$\rightarrow$` sample-output concern.  
Why it matters: Telegram may display raw math markup, degrading operator readability.  
Recommended fix: Add explicit prompt constraints: no LaTeX, no `$...$`, use plain arrows/units. Prefer also adding a small sanitizer/test for `$\\...$` patterns.

Verification note: I reviewed `feat/f29-periodic-reports` at `ef0a1eb`. I could not run the focused pytest suite because this shell has no `pytest` installed (`python3 -m pytest` reports `No module named pytest`).
