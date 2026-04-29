"""GemmaAgent — local LLM agent observing engine events.

Service named Гемма (after the underlying Gemma 4 model via Ollama).
Subscribes to EventBus, generates Russian-language operator insights,
dispatches to Telegram + operator log + GUI insight panel.

Constraints (ORCHESTRATION v1.3 §13):
- NEVER executes engine commands or modifies engine state.
- Text-only output channels (Telegram, log, GUI).
- Fails gracefully if Ollama is unavailable — engine continues.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryodaq.agents.audit import AuditLogger
from cryodaq.agents.context_builder import ContextBuilder
from cryodaq.agents.ollama_client import (
    OllamaClient,
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.agents.output_router import OutputRouter, OutputTarget
from cryodaq.agents.prompts import ALARM_SUMMARY_SYSTEM, ALARM_SUMMARY_USER
from cryodaq.core.event_bus import EngineEvent, EventBus

logger = logging.getLogger(__name__)

_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class GemmaConfig:
    enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "gemma4:e4b"
    timeout_s: float = 30.0
    temperature: float = 0.3
    max_tokens: int = 1024
    max_concurrent_inferences: int = 2
    max_calls_per_hour: int = 60
    alarm_min_level: str = "WARNING"
    slice_a_notification: bool = True
    slice_b_suggestion: bool = False
    slice_c_campaign_report: bool = False
    output_telegram: bool = True
    output_operator_log: bool = True
    output_gui_insight: bool = True
    audit_enabled: bool = True
    audit_retention_days: int = 90
    audit_dir: Path = field(default_factory=lambda: Path("data/agents/gemma/audit"))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GemmaConfig:
        """Build from agent.yaml gemma section dict."""
        cfg = cls()
        cfg.enabled = bool(d.get("enabled", True))
        ollama = d.get("ollama", {})
        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
        rl = d.get("rate_limit", {})
        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
        cfg.max_concurrent_inferences = int(
            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
        )
        triggers = d.get("triggers", {})
        alarm_t = triggers.get("alarm_fired", {})
        if isinstance(alarm_t, dict):
            cfg.alarm_min_level = str(alarm_t.get("min_level", cfg.alarm_min_level))
        outputs = d.get("outputs", {})
        cfg.output_telegram = bool(outputs.get("telegram", cfg.output_telegram))
        cfg.output_operator_log = bool(outputs.get("operator_log", cfg.output_operator_log))
        cfg.output_gui_insight = bool(outputs.get("gui_insight_panel", cfg.output_gui_insight))
        slices = d.get("slices", {})
        cfg.slice_a_notification = bool(slices.get("a_notification", cfg.slice_a_notification))
        cfg.slice_b_suggestion = bool(slices.get("b_suggestion", cfg.slice_b_suggestion))
        cfg.slice_c_campaign_report = bool(
            slices.get("c_campaign_report", cfg.slice_c_campaign_report)
        )
        audit = d.get("audit", {})
        cfg.audit_enabled = bool(audit.get("enabled", cfg.audit_enabled))
        cfg.audit_retention_days = int(audit.get("retention_days", cfg.audit_retention_days))
        return cfg


class GemmaAgent:
    """Local LLM agent. Operator-facing brand: Гемма."""

    def __init__(
        self,
        *,
        config: GemmaConfig,
        event_bus: EventBus,
        ollama_client: OllamaClient,
        context_builder: ContextBuilder,
        audit_logger: AuditLogger,
        output_router: OutputRouter,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._ollama = ollama_client
        self._ctx_builder = context_builder
        self._audit = audit_logger
        self._router = output_router

        self._semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
        self._call_timestamps: deque[float] = deque()
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[EngineEvent] | None = None

    async def start(self) -> None:
        """Subscribe to EventBus and begin event processing."""
        if not self._config.enabled:
            logger.info("GemmaAgent (Гемма): отключён в конфигурации")
            return
        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
        logger.info(
            "GemmaAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
            self._config.default_model,
            self._config.timeout_s,
        )

    async def stop(self) -> None:
        """Cancel the event loop and release resources."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue is not None:
            self._bus.unsubscribe("gemma_agent")
            self._queue = None
        await self._ollama.close()
        logger.info("GemmaAgent (Гемма): остановлен")

    async def _event_loop(self) -> None:
        """Drain the EventBus queue and dispatch handlers."""
        assert self._queue is not None
        while True:
            try:
                event = await self._queue.get()
                if self._should_handle(event):
                    asyncio.create_task(
                        self._safe_handle(event),
                        name=f"gemma_{event.event_type}",
                    )
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("GemmaAgent: event loop error", exc_info=True)

    def _should_handle(self, event: EngineEvent) -> bool:
        if not self._config.slice_a_notification:
            return False
        if event.event_type == "alarm_fired":
            level = event.payload.get("level", "INFO")
            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
                self._config.alarm_min_level, 1
            )
        return False  # experiment_finalize and phase_transition handled in Cycle 3

    def _check_rate_limit(self) -> bool:
        """True if we can make a call now (hourly bucket)."""
        now = time.monotonic()
        cutoff = now - 3600.0
        while self._call_timestamps and self._call_timestamps[0] < cutoff:
            self._call_timestamps.popleft()
        return len(self._call_timestamps) < self._config.max_calls_per_hour

    async def _safe_handle(self, event: EngineEvent) -> None:
        """Handle one event with rate-limit + semaphore + error isolation."""
        if not self._check_rate_limit():
            logger.warning(
                "GemmaAgent: rate limit reached (%d/hr), dropping %s",
                self._config.max_calls_per_hour,
                event.event_type,
            )
            return

        async with self._semaphore:
            self._call_timestamps.append(time.monotonic())
            try:
                await self._handle_alarm_fired(event)
            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
                logger.warning("GemmaAgent: Ollama недоступен — %s", exc)
            except Exception:
                logger.warning(
                    "GemmaAgent: ошибка обработки %s", event.event_type, exc_info=True
                )

    async def _handle_alarm_fired(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_alarm_context(payload)
        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"
        age_str = _format_age(ctx.experiment_age_s)

        user_prompt = ALARM_SUMMARY_USER.format(
            alarm_id=ctx.alarm_id,
            level=ctx.level,
            channels=channels_str,
            values=values_str,
            phase=ctx.phase or "—",
            experiment_id=ctx.experiment_id or "—",
            experiment_age=age_str,
            target_temp=ctx.target_temp if ctx.target_temp is not None else "—",
            interlocks=", ".join(ctx.active_interlocks) if ctx.active_interlocks else "нет",
            lookback_s=60,
            recent_readings=ctx.recent_readings_text,
            recent_alarms=ctx.recent_alarms_text,
        )

        result = await self._ollama.generate(
            user_prompt,
            system=ALARM_SUMMARY_SYSTEM,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )

        errors: list[str] = []
        if result.truncated:
            errors.append("timeout_truncated")
            logger.warning("GemmaAgent: ответ обрезан по таймауту (audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        dispatched = await self._router.dispatch(
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
            prompt_template="alarm_summary",
            model=result.model,
            system_prompt=ALARM_SUMMARY_SYSTEM,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            outputs_dispatched=dispatched,
            errors=errors,
        )

        logger.info(
            "GemmaAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
            audit_id,
            result.latency_s,
            dispatched,
        )


def _build_targets(config: GemmaConfig) -> list[OutputTarget]:
    targets = []
    if config.output_telegram:
        targets.append(OutputTarget.TELEGRAM)
    if config.output_operator_log:
        targets.append(OutputTarget.OPERATOR_LOG)
    if config.output_gui_insight:
        targets.append(OutputTarget.GUI_INSIGHT)
    return targets


def _format_age(age_s: float | None) -> str:
    if age_s is None:
        return "неизвестно"
    h, rem = divmod(int(age_s), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"
