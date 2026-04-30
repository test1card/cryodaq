"""AssistantLiveAgent — local LLM agent observing engine events.

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

from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter, OutputTarget
from cryodaq.agents.assistant.live.prompts import (
    ALARM_SUMMARY_SYSTEM,
    ALARM_SUMMARY_USER,
    DIAGNOSTIC_SUGGESTION_SYSTEM,
    DIAGNOSTIC_SUGGESTION_USER,
    EXPERIMENT_FINALIZE_SYSTEM,
    EXPERIMENT_FINALIZE_USER,
    PERIODIC_REPORT_SYSTEM,
    PERIODIC_REPORT_USER,
    SENSOR_ANOMALY_SYSTEM,
    SENSOR_ANOMALY_USER,
    SHIFT_HANDOVER_SYSTEM,
    SHIFT_HANDOVER_USER,
    format_with_brand,
)
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaClient,
    OllamaModelMissingError,
    OllamaUnavailableError,
)
from cryodaq.core.event_bus import EngineEvent, EventBus

logger = logging.getLogger(__name__)

_MIN_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class AssistantConfig:
    enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "gemma4:e4b"
    timeout_s: float = 30.0
    temperature: float = 0.3
    max_tokens: int = 2048  # gemma4:e4b is thinking-first; needs 2048+ for thought + response
    max_concurrent_inferences: int = 2
    max_calls_per_hour: int = 60
    alarm_fired_enabled: bool = True
    alarm_min_level: str = "WARNING"
    experiment_finalize_enabled: bool = True
    sensor_anomaly_critical_enabled: bool = True
    shift_handover_request_enabled: bool = True
    slice_a_notification: bool = True
    slice_b_suggestion: bool = False
    slice_c_campaign_report: bool = False
    output_telegram: bool = True
    output_operator_log: bool = True
    output_gui_insight: bool = True
    audit_enabled: bool = True
    audit_retention_days: int = 90
    num_ctx: int | None = None  # Ollama context window override; None = use model default
    audit_dir: Path = field(default_factory=lambda: Path("data/agents/assistant/audit"))
    brand_name: str = "Гемма"
    brand_emoji: str = "🤖"
    periodic_report_enabled: bool = True
    periodic_report_interval_minutes: int = 60
    periodic_report_skip_if_idle: bool = True
    periodic_report_min_events: int = 1

    def get_periodic_report_interval_s(self) -> float:
        """Return interval in seconds, or 0 if periodic reports are disabled."""
        if not self.periodic_report_enabled:
            return 0.0
        return float(self.periodic_report_interval_minutes * 60)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssistantConfig:
        """Build from agent.yaml agent section dict."""
        cfg = cls()
        cfg.enabled = bool(d.get("enabled", True))
        ollama = d.get("ollama", {})
        cfg.ollama_base_url = str(ollama.get("base_url", cfg.ollama_base_url))
        cfg.default_model = str(ollama.get("default_model", cfg.default_model))
        cfg.timeout_s = float(ollama.get("timeout_s", cfg.timeout_s))
        cfg.temperature = float(ollama.get("temperature", cfg.temperature))
        _num_ctx = ollama.get("num_ctx")
        cfg.num_ctx = int(_num_ctx) if _num_ctx is not None else None
        rl = d.get("rate_limit", {})
        cfg.max_calls_per_hour = int(rl.get("max_calls_per_hour", cfg.max_calls_per_hour))
        cfg.max_concurrent_inferences = int(
            rl.get("max_concurrent_inferences", cfg.max_concurrent_inferences)
        )
        triggers = d.get("triggers", {})
        alarm_t = triggers.get("alarm_fired", {})
        if isinstance(alarm_t, dict):
            cfg.alarm_fired_enabled = bool(alarm_t.get("enabled", cfg.alarm_fired_enabled))
            raw_level = str(alarm_t.get("min_level", cfg.alarm_min_level)).upper()
            if raw_level not in _MIN_LEVELS:
                raise ValueError(
                    f"alarm_min_level must be one of {list(_MIN_LEVELS)}, got {raw_level!r}"
                )
            cfg.alarm_min_level = raw_level
        exp_t = triggers.get("experiment_finalize", {})
        if isinstance(exp_t, dict):
            cfg.experiment_finalize_enabled = bool(
                exp_t.get("enabled", cfg.experiment_finalize_enabled)
            )
        sa_t = triggers.get("sensor_anomaly_critical", {})
        if isinstance(sa_t, dict):
            cfg.sensor_anomaly_critical_enabled = bool(
                sa_t.get("enabled", cfg.sensor_anomaly_critical_enabled)
            )
        sh_t = triggers.get("shift_handover_request", {})
        if isinstance(sh_t, dict):
            cfg.shift_handover_request_enabled = bool(
                sh_t.get("enabled", cfg.shift_handover_request_enabled)
            )
        pr_t = triggers.get("periodic_report", {})
        if isinstance(pr_t, dict):
            cfg.periodic_report_enabled = bool(pr_t.get("enabled", cfg.periodic_report_enabled))
            cfg.periodic_report_interval_minutes = int(
                pr_t.get("interval_minutes", cfg.periodic_report_interval_minutes)
            )
            cfg.periodic_report_skip_if_idle = bool(
                pr_t.get("skip_if_idle", cfg.periodic_report_skip_if_idle)
            )
            cfg.periodic_report_min_events = int(
                pr_t.get("min_events_for_dispatch", cfg.periodic_report_min_events)
            )
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
        cfg.brand_name = str(d.get("brand_name", cfg.brand_name))
        cfg.brand_emoji = str(d.get("brand_emoji", cfg.brand_emoji))
        return cfg

    @classmethod
    def from_yaml_string(cls, content: str) -> AssistantConfig:
        """Load from YAML string; handles agent.* and legacy gemma.* namespaces."""
        import yaml  # noqa: PLC0415
        raw = yaml.safe_load(content) or {}
        return cls._from_raw(raw)

    @classmethod
    def from_yaml_path(cls, path: Path) -> AssistantConfig:
        """Load from agent.yaml file; handles agent.* and legacy gemma.* namespaces."""
        import yaml  # noqa: PLC0415
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict) -> AssistantConfig:
        if "agent" in raw:
            return cls.from_dict(raw["agent"])
        if "gemma" in raw:
            logger.warning(
                "AssistantConfig: legacy gemma.* config namespace detected; "
                "please migrate to agent.*. Backward compatibility removed in v0.46.0."
            )
            return cls.from_dict(raw["gemma"])
        return cls()


class AssistantLiveAgent:
    """Local LLM agent. Operator-facing brand: Гемма."""

    def __init__(
        self,
        *,
        config: AssistantConfig,
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
        self._handler_tasks: set[asyncio.Task] = set()
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[EngineEvent] | None = None

    async def start(self) -> None:
        """Subscribe to EventBus and begin event processing."""
        if not self._config.enabled:
            logger.info("AssistantLiveAgent (Гемма): отключён в конфигурации")
            return
        self._queue = await self._bus.subscribe("gemma_agent", maxsize=1000)
        self._task = asyncio.create_task(self._event_loop(), name="gemma_agent")
        logger.info(
            "AssistantLiveAgent (Гемма): запущен. Модель=%s, timeout=%.0fs",
            self._config.default_model,
            self._config.timeout_s,
        )

    async def stop(self) -> None:
        """Cancel the event loop and in-flight handlers, release resources."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Cancel in-flight inference tasks to avoid racing with shutdown
        for t in list(self._handler_tasks):
            t.cancel()
        for t in list(self._handler_tasks):
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self._queue is not None:
            self._bus.unsubscribe("gemma_agent")
            self._queue = None
        await self._ollama.close()
        logger.info("AssistantLiveAgent (Гемма): остановлен")

    async def _event_loop(self) -> None:
        """Drain the EventBus queue and dispatch handlers."""
        assert self._queue is not None
        while True:
            try:
                event = await self._queue.get()
                if self._should_handle(event):
                    t = asyncio.create_task(
                        self._safe_handle(event),
                        name=f"gemma_{event.event_type}",
                    )
                    self._handler_tasks.add(t)
                    t.add_done_callback(self._handler_tasks.discard)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("AssistantLiveAgent: event loop error", exc_info=True)

    def _should_handle(self, event: EngineEvent) -> bool:
        if not self._config.slice_a_notification:
            return False
        if event.event_type == "alarm_fired":
            if not self._config.alarm_fired_enabled:
                return False
            level = event.payload.get("level", "INFO")
            return _MIN_LEVELS.get(level, 0) >= _MIN_LEVELS.get(
                self._config.alarm_min_level, 1
            )
        if event.event_type in {"experiment_finalize", "experiment_stop", "experiment_abort"}:
            return self._config.experiment_finalize_enabled
        if event.event_type == "sensor_anomaly_critical":
            return self._config.sensor_anomaly_critical_enabled
        if event.event_type == "shift_handover_request":
            return self._config.shift_handover_request_enabled
        if event.event_type == "periodic_report_request":
            return self._config.periodic_report_enabled
        return False

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
                "AssistantLiveAgent: rate limit reached (%d/hr), dropping %s",
                self._config.max_calls_per_hour,
                event.event_type,
            )
            return

        async with self._semaphore:
            self._call_timestamps.append(time.monotonic())
            try:
                if event.event_type in {
                    "experiment_finalize",
                    "experiment_stop",
                    "experiment_abort",
                }:
                    await self._handle_experiment_finalize(event)
                elif event.event_type == "sensor_anomaly_critical":
                    await self._handle_sensor_anomaly(event)
                elif event.event_type == "shift_handover_request":
                    await self._handle_shift_handover(event)
                elif event.event_type == "periodic_report_request":
                    await self._handle_periodic_report(event)
                else:
                    await self._handle_alarm_fired(event)
            except (OllamaUnavailableError, OllamaModelMissingError) as exc:
                logger.warning("AssistantLiveAgent: Ollama недоступен — %s", exc)
            except Exception:
                logger.warning(
                    "AssistantLiveAgent: ошибка обработки %s", event.event_type, exc_info=True
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

        system_prompt = format_with_brand(ALARM_SUMMARY_SYSTEM, self._config.brand_name)
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
            logger.warning("AssistantLiveAgent: ответ обрезан по таймауту (audit_id=%s)", audit_id)

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning(
                "AssistantLiveAgent: пустой ответ, dispatch пропущен (truncated=%s, audit_id=%s)",
                result.truncated,
                audit_id,
            )
            dispatched: list[str] = []
        else:
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
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            outputs_dispatched=dispatched,
            errors=errors,
        )

        logger.info(
            "AssistantLiveAgent: alarm_fired обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
            audit_id,
            result.latency_s,
            dispatched,
        )
        if self._config.slice_b_suggestion and not result.truncated and result.text.strip():
            await self._generate_diagnostic_suggestion(event, payload)


    async def _generate_diagnostic_suggestion(
        self, event: EngineEvent, alarm_payload: dict[str, Any]
    ) -> None:
        """Generate and dispatch Slice B diagnostic suggestion (second LLM call).

        Records a separate rate-limit timestamp so each Ollama call counts
        toward the hourly budget (Slice B makes 2 calls per alarm event).
        """
        # Count diagnostic as a separate call toward the hourly rate limit
        self._call_timestamps.append(time.monotonic())
        audit_id = self._audit.make_audit_id()
        ctx = await self._ctx_builder.build_diagnostic_suggestion_context(alarm_payload)
        channels_str = ", ".join(ctx.channels) if ctx.channels else "—"
        values_str = ", ".join(f"{k}={v}" for k, v in ctx.values.items()) if ctx.values else "—"

        user_prompt = DIAGNOSTIC_SUGGESTION_USER.format(
            alarm_id=ctx.alarm_id,
            channels=channels_str,
            values=values_str,
            lookback_min=ctx.lookback_min,
            channel_history=ctx.channel_history,
            recent_alarms=ctx.recent_alarms,
            past_cooldowns=ctx.past_cooldowns,
            pressure_trend=ctx.pressure_trend,
        )

        system_prompt = format_with_brand(DIAGNOSTIC_SUGGESTION_SYSTEM, self._config.brand_name)
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
                "AssistantLiveAgent: diagnostic ответ обрезан (audit_id=%s)", audit_id
            )

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning("AssistantLiveAgent: пустой diagnostic ответ (audit_id=%s)", audit_id)
            dispatched_diag: list[str] = []
        else:
            dispatched_diag = await self._router.dispatch(
                event, result.text, targets=targets, audit_id=audit_id
            )

        await self._audit.log(
            audit_id=audit_id,
            trigger_event={
                "event_type": event.event_type,
                "payload": alarm_payload,
                "experiment_id": event.experiment_id,
            },
            context_assembled=user_prompt,
            prompt_template="diagnostic_suggestion",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            outputs_dispatched=dispatched_diag,
            errors=errors,
        )
        logger.info(
            "AssistantLiveAgent: diagnostic_suggestion dispatched (audit_id=%s, latency=%.1fs)",
            audit_id,
            result.latency_s,
        )

    async def _handle_experiment_finalize(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_experiment_finalize_context(payload)
        _action_labels = {
            "experiment_finalize": "Завершён штатно",
            "experiment_stop": "Остановлен",
            "experiment_abort": "Прерван аварийно",
        }
        user_prompt = EXPERIMENT_FINALIZE_USER.format(
            experiment_id=ctx.experiment_id or "—",
            name=ctx.name,
            duration=ctx.duration_str,
            status=_action_labels.get(ctx.action, ctx.action),
            phases=ctx.phases_text,
            alarms_summary=ctx.alarms_summary_text,
        )

        system_prompt = format_with_brand(EXPERIMENT_FINALIZE_SYSTEM, self._config.brand_name)
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
                "AssistantLiveAgent: ответ обрезан (experiment_finalize, audit_id=%s)", audit_id
            )

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning(
                "AssistantLiveAgent: пустой ответ experiment_finalize (audit_id=%s)", audit_id
            )
            dispatched: list[str] = []
        else:
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
            prompt_template="experiment_finalize",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            outputs_dispatched=dispatched,
            errors=errors,
        )
        logger.info(
            "AssistantLiveAgent: %s обработан (audit_id=%s, latency=%.1fs, dispatched=%s)",
            event.event_type,
            audit_id,
            result.latency_s,
            dispatched,
        )

    async def _handle_sensor_anomaly(self, event: EngineEvent) -> None:
        audit_id = self._audit.make_audit_id()
        payload = event.payload

        ctx = await self._ctx_builder.build_sensor_anomaly_context(payload)
        user_prompt = SENSOR_ANOMALY_USER.format(
            channel=ctx.channel,
            alarm_id=ctx.alarm_id,
            level=ctx.level,
            message=ctx.message,
            health_score=ctx.health_score,
            fault_flags=ctx.fault_flags,
            current_value=ctx.current_value,
            experiment_id=ctx.experiment_id or "—",
            phase=ctx.phase or "—",
        )

        system_prompt = format_with_brand(SENSOR_ANOMALY_SYSTEM, self._config.brand_name)
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
                "AssistantLiveAgent: ответ обрезан (sensor_anomaly, audit_id=%s)", audit_id
            )

        targets = _build_targets(self._config)
        if result.truncated or not result.text.strip():
            logger.warning(
                "AssistantLiveAgent: пустой ответ sensor_anomaly (audit_id=%s)", audit_id
            )
            dispatched_sa: list[str] = []
        else:
            dispatched_sa = await self._router.dispatch(
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
            prompt_template="sensor_anomaly",
            model=result.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result.text,
            tokens={"in": result.tokens_in, "out": result.tokens_out},
            latency_s=result.latency_s,
            outputs_dispatched=dispatched_sa,
            errors=errors,
        )
        logger.info(
            "AssistantLiveAgent: sensor_anomaly_critical обработан "
            "(audit_id=%s, latency=%.1fs, channel=%s)",
            audit_id,
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

        if ctx.context_read_failed:
            logger.warning(
                "AssistantLiveAgent: periodic report context read failed "
                "(audit_id=%s) — proceeding with empty context",
                audit_id,
            )
        elif (
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
