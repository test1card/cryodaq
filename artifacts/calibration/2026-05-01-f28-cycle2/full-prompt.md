# F28 Cycle 2 audit — GemmaAgent service + alarm summary (Slice A)

## Context

CryoDAQ v0.44.0, Python 3.12+, asyncio, safety-critical cryogenic DAQ.
Branch feat/f28-hermes-agent, commit 535cc95.

Cycle 2 adds GemmaAgent (Гемма): a local LLM agent (Ollama/gemma4:e4b) that
subscribes to EventBus, handles alarm_fired events, generates Russian-language
operator summaries, and dispatches to Telegram + operator log.

CRITICAL CONSTRAINT from spec: GemmaAgent NEVER executes engine commands or
modifies engine state. Text-only output. Fails gracefully if Ollama down.

## Files changed

- src/cryodaq/agents/gemma.py (NEW, 291 LOC) — GemmaAgent main service
- src/cryodaq/agents/output_router.py (NEW, 102 LOC) — output dispatch
- src/cryodaq/agents/prompts.py (NEW, 83 LOC) — Russian prompt templates
- src/cryodaq/engine.py (MODIFIED, +63 LOC) — wiring in startup/shutdown
- config/agent.yaml (NEW) — gemma configuration
- tests/agents/test_gemma_alarm_flow.py (NEW, 307 LOC) — 15 unit tests

All 31 agent tests pass. Smoke test with real gemma4:e4b done in Cycle 1.

## Diff

```
535cc95 feat(f28): Cycle 2 — GemmaAgent service + alarm summary (Slice A) (12 seconds ago) <Vladimir Fomenko>
config/agent.yaml                     |  39 +++++
 src/cryodaq/agents/gemma.py           | 291 ++++++++++++++++++++++++++++++++
 src/cryodaq/agents/output_router.py   | 102 +++++++++++
 src/cryodaq/agents/prompts.py         |  83 +++++++++
 src/cryodaq/engine.py                 |  63 ++++++-
 tests/agents/test_gemma_alarm_flow.py | 307 ++++++++++++++++++++++++++++++++++
 6 files changed, 881 insertions(+), 4 deletions(-)

config/agent.yaml
  @@ -0,0 +1,39 @@
  +gemma:
  +  enabled: true
  +
  +  ollama:
  +    base_url: http://localhost:11434
  +    default_model: gemma4:e4b
  +    timeout_s: 30
  +    temperature: 0.3
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
  +    b_suggestion: false
  +    c_campaign_report: false
  +
  +  audit:
  +    enabled: true
  +    retention_days: 90
  +39 -0

src/cryodaq/agents/gemma.py
  @@ -0,0 +1,291 @@
  +"""GemmaAgent — local LLM agent observing engine events.
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
  +from cryodaq.agents.audit import AuditLogger
  +from cryodaq.agents.context_builder import ContextBuilder
  +from cryodaq.agents.ollama_client import (
  +    OllamaClient,
  +    OllamaModelMissingError,
  +    OllamaUnavailableError,
  +)
  +from cryodaq.agents.output_router import OutputRouter, OutputTarget
  +from cryodaq.agents.prompts import ALARM_SUMMARY_SYSTEM, ALARM_SUMMARY_USER
  +from cryodaq.core.event_bus import EngineEvent, EventBus
  +
  +logger = logging.getLogger(__name__)
  +
  +_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
  +
  +
  +@dataclass
  +class GemmaConfig:
  +    enabled: bool = True
  +    ollama_base_url: str = "http://localhost:11434"
  +    default_model: str = "gemma4:e4b"
  +    timeout_s: float = 30.0
  +    temperature: float = 0.3
  +    max_tokens: int = 1024
  +    max_concurrent_inferences: int = 2
  +    max_calls_per_hour: int = 60
  +    alarm_min_level: str = "WARNING"
  +    slice_a_notification: bool = True
  +    slice_b_suggestion: bool = False
  +    slice_c_campaign_report: bool = False
  +    output_telegram: bool = True
  +    output_operator_log: bool = True
  +    output_gui_insight: bool = True
  +    audit_enabled: bool = True
  +    audit_retention_days: int = 90
  +    audit_dir: Path = field(default_factory=lambda: Path("data/agents/gemma/audit"))
  +
  +    @classmethod
  +    def from_dict(cls, d: dict[str, Any]) -> GemmaConfig:
  +        """Build from agent.yaml gemma section dict."""
  +        cfg = cls()
  +        cfg.enabled = bool(d.get("enabled", True))
  +        ollama = d.get("ollama", {})
  +        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
  +        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
  +        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
  +        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
  +        rl = d.get("rate_limit", {})
  +        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
  +        cfg.max_concurrent_inferences = int(
  +            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
  +        )
  +        triggers = d.get("triggers", {})
  +        alarm_t = triggers.get("alarm_fired", {})
  +        if isinstance(alarm_t, dict):
  +            cfg.alarm_min_level = str(alarm_t.get("min_level", cfg.alarm_min_level))
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
  +        return cfg
  +
  +
  +class GemmaAgent:
  +    """Local LLM agent. Operator-facing brand: Гемма."""
  +
  +    def __init__(
  +        self,
  +        *,
  ... (191 lines truncated)
  +291 -0

src/cryodaq/agents/output_router.py
  @@ -0,0 +1,102 @@
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
  +_GEMMA_PREFIX = "🤖 Гемма:"
  +
  +
  +class OutputTarget(enum.Enum):
  +    TELEGRAM = "telegram"
  +    OPERATOR_LOG = "operator_log"
  +    GUI_INSIGHT = "gui_insight"
  +
  +
  +class OutputRouter:
  +    """Dispatches GemmaAgent LLM output to configured channels."""
  +
  +    def __init__(
  +        self,
  +        *,
  +        telegram_bot: Any | None,
  +        event_logger: EventLogger,
  +        event_bus: EventBus,
  +    ) -> None:
  +        self._telegram = telegram_bot
  +        self._event_logger = event_logger
  +        self._event_bus = event_bus
  +
  +    async def dispatch(
  +        self,
  +        trigger_event: EngineEvent,
  +        llm_output: str,
  +        *,
  +        targets: list[OutputTarget],
  +        audit_id: str,
  +    ) -> list[str]:
  +        """Send llm_output to all configured targets.
  +
  +        Returns list of successfully dispatched target names.
  +        """
  +        dispatched: list[str] = []
  +        prefixed = f"{_GEMMA_PREFIX} {llm_output}"
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
  +                        "gemma",
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
  +                            event_type="gemma_insight",
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
  ... (2 lines truncated)
  +102 -0

src/cryodaq/agents/prompts.py
  @@ -0,0 +1,83 @@
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
  +Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
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
  +Ты — Гемма, ассистент-аналитик в криогенной лаборатории. Твоя задача — \
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
  +83 -0

src/cryodaq/engine.py
  @@ -29,6 +29,11 @@ from typing import Any
  +from cryodaq.agents.audit import AuditLogger
  +from cryodaq.agents.context_builder import ContextBuilder
  +from cryodaq.agents.gemma import GemmaAgent, GemmaConfig
  +from cryodaq.agents.ollama_client import OllamaClient
  +from cryodaq.agents.output_router import OutputRouter
   from cryodaq.analytics.calibration import CalibrationStore
   from cryodaq.analytics.leak_rate import LeakRateEstimator
   from cryodaq.analytics.plugin_loader import PluginPipeline
  @@ -1656,9 +1661,7 @@ async def _run_engine(*, mock: bool = False) -> None:
  -                            event_type="experiment_finalize"
  -                            if action != "experiment_abort"
  -                            else "experiment_abort",
  +                            event_type=action,
                               timestamp=datetime.now(UTC),
                               payload={"action": action, "experiment": _exp_info},
                               experiment_id=_exp_info.get("experiment_id"),
  @@ -1666,7 +1669,6 @@ async def _run_engine(*, mock: bool = False) -> None:
  -                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                       _active = experiment_manager.active_experiment
                       await event_bus.publish(
                           EngineEvent(
  @@ -1676,6 +1678,7 @@ async def _run_engine(*, mock: bool = False) -> None:
  +                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                   return result
               if action == "calibration_acquisition_status":
                   return {"ok": True, **calibration_acquisition.stats}
  @@ -1868,6 +1871,48 @@ async def _run_engine(*, mock: bool = False) -> None:
  +    # --- GemmaAgent (Гемма local LLM agent) ---
  +    _agent_cfg_path = _CONFIG_DIR / "agent.yaml"
  +    gemma_agent: GemmaAgent | None = None
  +    if _agent_cfg_path.exists():
  +        try:
  +            _agent_raw = yaml.safe_load(_agent_cfg_path.read_text(encoding="utf-8")) or {}
  +            _gemma_raw = _agent_raw.get("gemma", {})
  +            _gemma_config = GemmaConfig.from_dict(_gemma_raw)
  +            if _gemma_config.enabled:
  +                _gemma_ollama = OllamaClient(
  +                    base_url=_gemma_config.ollama_base_url,
  +                    default_model=_gemma_config.default_model,
  +                    timeout_s=_gemma_config.timeout_s,
  +                )
  +                _gemma_ctx = ContextBuilder(writer, experiment_manager)
  +                _gemma_audit = AuditLogger(
  +                    _DATA_DIR / "agents" / "gemma" / "audit",
  +                    enabled=_gemma_config.audit_enabled,
  +                    retention_days=_gemma_config.audit_retention_days,
  +                )
  +                _gemma_router = OutputRouter(
  +                    telegram_bot=telegram_bot,
  +                    event_logger=event_logger,
  +                    event_bus=event_bus,
  +                )
  +                gemma_agent = GemmaAgent(
  +                    config=_gemma_config,
  +                    event_bus=event_bus,
  +                    ollama_client=_gemma_ollama,
  +                    context_builder=_gemma_ctx,
  +                    audit_logger=_gemma_audit,
  +                    output_router=_gemma_router,
  +                )
  +                logger.info(
  +                    "GemmaAgent (Гемма): инициализирован, модель=%s",
  +                    _gemma_config.default_model,
  +                )
  +        except Exception as _gemma_exc:
  +            logger.warning("GemmaAgent: ошибка инициализации — %s", _gemma_exc)
  +    else:
  +        logger.info("GemmaAgent: config/agent.yaml не найден, агент отключён")
  +
       # --- Запуск всех подсистем ---
       await safety_manager.start()
       logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
  @@ -1883,6 +1928,12 @@ async def _run_engine(*, mock: bool = False) -> None:
  +    if gemma_agent is not None:
  +        try:
  +            await gemma_agent.start()
  +        except Exception as _gemma_start_exc:
  +            logger.warning("GemmaAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
  +            gemma_agent = None
       await scheduler.start()
       throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
       alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
  @@ -2012,6 +2063,10 @@ async def _run_engine(*, mock: bool = False) -> None:
  +    if gemma_agent is not None:
  +        await gemma_agent.stop()
  +        logger.info("GemmaAgent (Гемма) остановлен")
  +
       if telegram_bot is not None:
           await telegram_bot.stop()
           logger.info("TelegramCommandBot остановлен")
  +59 -4

tests/agents/test_gemma_alarm_flow.py
  @@ -0,0 +1,307 @@
  +"""Tests for GemmaAgent alarm flow — Slice A end-to-end (mock Ollama)."""
  +
  +from __future__ import annotations
  +
  +import asyncio
  +from datetime import UTC, datetime
  +from pathlib import Path
  +from unittest.mock import AsyncMock, MagicMock
  +
  +from cryodaq.agents.audit import AuditLogger
  +from cryodaq.agents.context_builder import ContextBuilder
  +from cryodaq.agents.gemma import GemmaAgent, GemmaConfig, _format_age
  +from cryodaq.agents.ollama_client import GenerationResult, OllamaUnavailableError
  +from cryodaq.agents.output_router import OutputRouter
  +from cryodaq.core.event_bus import EngineEvent, EventBus
  +
  +# ---------------------------------------------------------------------------
  +# Fixtures
  +# ---------------------------------------------------------------------------
  +
  +
  +def _alarm_event(
  +    alarm_id: str = "test_alarm",
  +    level: str = "WARNING",
  +    experiment_id: str | None = "exp-001",
  +) -> EngineEvent:
  +    return EngineEvent(
  +        event_type="alarm_fired",
  +        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
  +        payload={
  +            "alarm_id": alarm_id,
  +            "level": level,
  +            "channels": ["T1", "T2"],
  +            "values": {"T1": 4.5, "T2": 4.8},
  +            "message": "Temperature above threshold",
  +        },
  +        experiment_id=experiment_id,
  +    )
  +
  +
  +def _make_config(**overrides) -> GemmaConfig:
  +    cfg = GemmaConfig(
  +        enabled=True,
  +        max_concurrent_inferences=1,
  +        max_calls_per_hour=60,
  +        alarm_min_level="WARNING",
  +        output_telegram=True,
  +        output_operator_log=True,
  +        output_gui_insight=False,
  +        audit_enabled=False,
  +    )
  +    for k, v in overrides.items():
  +        setattr(cfg, k, v)
  +    return cfg
  +
  +
  +def _make_mock_ollama(text: str = "🤖 Тест: температура T1 4.5K выше порога.") -> MagicMock:
  +    ollama = AsyncMock()
  +    ollama.generate = AsyncMock(
  +        return_value=GenerationResult(
  +            text=text, tokens_in=80, tokens_out=25, latency_s=3.5, model="gemma4:e4b"
  +        )
  +    )
  +    ollama.close = AsyncMock()
  +    return ollama
  +
  +
  +def _make_mock_em() -> MagicMock:
  +    em = MagicMock()

... (more changes truncated)
  +69 -0
[full diff: rtk git diff --no-compact]

```

## Review focus

1. **GemmaAgent lifecycle**: start/stop correct? EventBus subscription/unsubscribe
   clean? Task cancellation safe?
2. **Rate limiting**: asyncio.Semaphore for concurrent + deque for hourly rate.
   Edge cases? Thread safety? (asyncio single-threaded, no lock needed)
3. **Alarm handling**: alarm_fired → context_builder → ollama → audit → dispatch.
   Error isolation correct? Could any path crash engine?
4. **Engine wiring**: GemmaAgent init placed correctly (after telegram_bot)?
   Start after telegram_bot.start()? Stop before telegram_bot.stop()? Config
   loading failure handled?
5. **Output router**: Telegram/log/gui dispatch — error isolation per target?
   "🤖 Гемма:" prefix on all outputs?
6. **Safety constraints**: any path that could trigger engine side-effects?
7. **Test coverage**: 15 tests — gaps in alarm flow coverage?

## Output format

Verdict: PASS / CONDITIONAL / FAIL
Findings: Severity (CRITICAL/HIGH/MEDIUM/LOW), file:line, description, fix.
Under 2000 words.
