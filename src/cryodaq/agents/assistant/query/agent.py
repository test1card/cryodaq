"""AssistantQueryAgent — F30 Live Query Agent orchestrator.

Three-step pipeline: classify intent → fetch from adapters → format with LLM.
Never raises from handle_query(); returns Russian error string on all failures.
"""

from __future__ import annotations

import collections
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.live.prompts import format_with_brand
from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier
from cryodaq.agents.assistant.query.prompts import (
    FORMAT_ALARM_STATUS_USER,
    FORMAT_COMPOSITE_STATUS_USER,
    FORMAT_CURRENT_VALUE_USER,
    FORMAT_ETA_COOLDOWN_USER,
    FORMAT_ETA_VACUUM_USER,
    FORMAT_OUT_OF_SCOPE_GENERAL_USER,
    FORMAT_OUT_OF_SCOPE_HISTORICAL_USER,
    FORMAT_PHASE_INFO_USER,
    FORMAT_RANGE_STATS_USER,
    FORMAT_RESPONSE_SYSTEM,
    FORMAT_UNKNOWN_USER,
)
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import QueryAdapters, QueryCategory

if TYPE_CHECKING:
    from cryodaq.agents.assistant.live.agent import AssistantConfig
    from cryodaq.agents.assistant.shared.audit import AuditLogger
    from cryodaq.agents.assistant.shared.ollama_client import (
        GenerationResult,
        OllamaClient,
    )

logger = logging.getLogger(__name__)

_FALLBACK = "Произошла внутренняя ошибка. Попробуй ещё раз или обратись к оператору."


class AssistantQueryAgent:
    """Orchestrates the live query pipeline for operator free-text questions."""

    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        audit_logger: AuditLogger,
        config: AssistantConfig,
        adapters: QueryAdapters,
        intent_model: str | None = None,
        format_model: str | None = None,
        intent_temperature: float = 0.1,
        format_temperature: float = 0.3,
        intent_timeout_s: float = 10.0,
        format_timeout_s: float = 20.0,
        max_queries_per_chat_per_hour: int = 60,
    ) -> None:
        self._ollama = ollama_client
        self._audit = audit_logger
        self._config = config
        self._classifier = IntentClassifier(
            ollama_client,
            model=intent_model,
            temperature=intent_temperature,
            timeout_s=intent_timeout_s,
        )
        self._router = QueryRouter(adapters)
        self._format_model = format_model
        self._format_temperature = format_temperature
        self._format_timeout_s = format_timeout_s
        self._max_per_hour = max_queries_per_chat_per_hour
        self._rate_buckets: dict[int | str, collections.deque[float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_query(
        self,
        query: str,
        *,
        chat_id: int | str | None = None,
    ) -> str:
        """Process free-text operator query. Never raises."""
        if chat_id is not None and not self._check_rate(chat_id):
            return "Слишком много запросов. Подожди немного."

        audit_id = self._audit.make_audit_id()
        t0 = time.monotonic()
        errors: list[str] = []
        intent = None
        data: dict[str, Any] = {}
        user_prompt = ""
        result: GenerationResult | None = None
        response = _FALLBACK

        try:
            intent = await self._classifier.classify(query)
            data = await self._router.fetch(intent, query)
            user_prompt = self._build_format_user_prompt(
                query, intent.category, data
            )
            system_prompt = format_with_brand(
                FORMAT_RESPONSE_SYSTEM, self._config.brand_name
            )
            result = await self._ollama.generate(
                user_prompt,
                model=self._format_model,
                system=system_prompt,
                temperature=self._format_temperature,
                max_tokens=2048,
            )
            if result.truncated or not result.text.strip():
                errors.append("format_llm_truncated_or_empty")
            else:
                response = result.text.strip()
        except Exception as exc:
            logger.warning(
                "AssistantQueryAgent: error handling %r: %s", query[:80], exc
            )
            errors.append(f"unexpected: {exc}")

        latency_s = time.monotonic() - t0
        cat_str = intent.category.value if intent is not None else "error"

        await self._audit.log(
            audit_id=audit_id,
            trigger_event={
                "type": "live_query",
                "query": query,
                "chat_id": chat_id,
                "category": cat_str,
            },
            context_assembled=str(data),
            prompt_template=cat_str,
            model=result.model if result is not None else (
                self._format_model or "unknown"
            ),
            system_prompt=format_with_brand(
                FORMAT_RESPONSE_SYSTEM, self._config.brand_name
            ),
            user_prompt=user_prompt,
            response=response,
            tokens={
                "in": result.tokens_in if result is not None else 0,
                "out": result.tokens_out if result is not None else 0,
            },
            latency_s=latency_s,
            outputs_dispatched=["telegram"] if chat_id is not None else [],
            errors=errors,
        )

        return response

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate(self, chat_id: int | str) -> bool:
        """Return True if within rate limit; record the request."""
        now = time.monotonic()
        bucket = self._rate_buckets.setdefault(chat_id, collections.deque())
        cutoff = now - 3600.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_per_hour:
            return False
        bucket.append(now)
        return True

    # ------------------------------------------------------------------
    # Format prompt building
    # ------------------------------------------------------------------

    def _build_format_user_prompt(
        self,
        query: str,
        category: QueryCategory,
        data: dict[str, Any],
    ) -> str:
        try:
            return self._format_dispatch(query, category, data)
        except Exception as exc:
            logger.warning(
                "_build_format_user_prompt failed for %s: %s", category, exc
            )
            return FORMAT_UNKNOWN_USER.format(query=query)

    def _format_dispatch(
        self,
        query: str,
        category: QueryCategory,
        data: dict[str, Any],
    ) -> str:
        if category == QueryCategory.CURRENT_VALUE:
            return self._fmt_current_value(query, data)
        if category == QueryCategory.ETA_COOLDOWN:
            return self._fmt_eta_cooldown(query, data)
        if category == QueryCategory.ETA_VACUUM:
            return self._fmt_eta_vacuum(query, data)
        if category == QueryCategory.RANGE_STATS:
            return self._fmt_range_stats(query, data)
        if category == QueryCategory.PHASE_INFO:
            return self._fmt_phase_info(query, data)
        if category == QueryCategory.ALARM_STATUS:
            return self._fmt_alarm_status(query, data)
        if category == QueryCategory.COMPOSITE_STATUS:
            return self._fmt_composite(query, data)
        if category == QueryCategory.OUT_OF_SCOPE_HISTORICAL:
            return FORMAT_OUT_OF_SCOPE_HISTORICAL_USER.format(
                query=query, brand_name=self._config.brand_name
            )
        if category == QueryCategory.OUT_OF_SCOPE_GENERAL:
            return FORMAT_OUT_OF_SCOPE_GENERAL_USER.format(
                query=query, brand_name=self._config.brand_name
            )
        return FORMAT_UNKNOWN_USER.format(query=query)

    def _fmt_current_value(self, query: str, data: dict[str, Any]) -> str:
        readings = data.get("readings", {})
        ages = data.get("ages_s", {})
        channels = data.get("channels", [])

        if not readings:
            vals_text = "нет данных"
            stale_text = "—"
        else:
            val_lines = []
            stale_lines = []
            for ch in channels:
                r = readings.get(ch)
                unit = getattr(r, "unit", "") if r is not None else ""
                val_lines.append(
                    f"  {ch}: {r.value:.4g} {unit}" if r else f"  {ch}: нет данных"
                )
                age = ages.get(ch)
                if age is None:
                    stale_lines.append(f"  {ch}: нет данных")
                elif age > 60:
                    stale_lines.append(f"  {ch}: {age:.0f}s (УСТАРЕЛО)")
                else:
                    stale_lines.append(f"  {ch}: {age:.0f}s (свежее)")
            vals_text = "\n".join(val_lines) or "нет данных"
            stale_text = "\n".join(stale_lines) or "—"

        return FORMAT_CURRENT_VALUE_USER.format(
            query=query,
            channel_values_text=vals_text,
            staleness_text=stale_text,
        )

    def _fmt_eta_cooldown(self, query: str, data: dict[str, Any]) -> str:
        eta = data.get("cooldown_eta")
        if eta is None:
            return FORMAT_ETA_COOLDOWN_USER.format(
                query=query,
                t_cold="нет данных",
                progress_pct=0.0,
                phase="нет данных",
                t_remaining_str="нет прогноза",
                ci_low=0.0,
                ci_high=0.0,
                n_references=0,
                cooldown_active=False,
            )
        h = max(eta.t_remaining_hours, 0.0)
        t_str = f"{int(h)}ч {int((h % 1) * 60)}мин"
        t_cold = (
            f"{eta.T_cold:.2f}" if eta.T_cold is not None else "нет данных"
        )
        return FORMAT_ETA_COOLDOWN_USER.format(
            query=query,
            t_cold=t_cold,
            progress_pct=eta.progress * 100,
            phase=eta.phase,
            t_remaining_str=t_str,
            ci_low=eta.t_remaining_low_68,
            ci_high=eta.t_remaining_high_68,
            n_references=eta.n_references,
            cooldown_active=eta.cooldown_active,
        )

    def _fmt_eta_vacuum(self, query: str, data: dict[str, Any]) -> str:
        eta = data.get("vacuum_eta")
        current_p = data.get("current_pressure")

        if eta is None:
            cur_str = f"{current_p:.2e}" if current_p is not None else "нет данных"
            return FORMAT_ETA_VACUUM_USER.format(
                query=query,
                current_mbar=cur_str,
                target_mbar=1e-6,
                eta_str="нет прогноза",
                trend="нет данных",
                confidence=0.0,
            )

        cur = eta.current_mbar if eta.current_mbar is not None else current_p
        cur_str = f"{cur:.2e}" if cur is not None else "нет данных"
        if eta.eta_seconds is None:
            eta_str = "не определено"
        else:
            h = eta.eta_seconds / 3600
            eta_str = f"{int(h)}ч {int((h % 1) * 60)}мин"

        return FORMAT_ETA_VACUUM_USER.format(
            query=query,
            current_mbar=cur_str,
            target_mbar=eta.target_mbar,
            eta_str=eta_str,
            trend=eta.trend,
            confidence=eta.confidence,
        )

    def _fmt_range_stats(self, query: str, data: dict[str, Any]) -> str:
        stats_dict = data.get("range_stats", {})
        window = data.get("window_minutes", 60)
        if not stats_dict:
            return FORMAT_RANGE_STATS_USER.format(
                query=query,
                channel="нет данных",
                window_minutes=window,
                n_samples=0,
                min_value=0.0,
                max_value=0.0,
                mean_value=0.0,
                std_value=0.0,
                unit="",
            )
        channel, stats = next(iter(stats_dict.items()))
        return FORMAT_RANGE_STATS_USER.format(
            query=query,
            channel=channel,
            window_minutes=stats.window_minutes,
            n_samples=stats.n_samples,
            min_value=stats.min_value,
            max_value=stats.max_value,
            mean_value=stats.mean_value,
            std_value=stats.std_value,
            unit=stats.unit,
        )

    def _fmt_phase_info(self, query: str, data: dict[str, Any]) -> str:
        status = data.get("experiment_status")
        if status is None:
            return FORMAT_PHASE_INFO_USER.format(
                query=query,
                experiment_id="нет активного эксперимента",
                phase="нет данных",
                phase_started_text="—",
                experiment_age_text="—",
                target_temp="нет данных",
            )
        age_h = status.experiment_age_s / 3600
        age_text = f"{int(age_h)}ч {int((age_h % 1) * 60)}мин"
        if status.phase_started_at is not None:
            phase_dt = datetime.fromtimestamp(status.phase_started_at, tz=UTC)
            phase_started = phase_dt.strftime("%H:%M UTC")
        else:
            phase_started = "нет данных"
        target = (
            f"{status.target_temp} K"
            if status.target_temp is not None
            else "нет данных"
        )
        return FORMAT_PHASE_INFO_USER.format(
            query=query,
            experiment_id=status.experiment_id,
            phase=status.phase or "нет данных",
            phase_started_text=phase_started,
            experiment_age_text=age_text,
            target_temp=target,
        )

    def _fmt_alarm_status(self, query: str, data: dict[str, Any]) -> str:
        result = data.get("alarm_result")
        if result is None or result.count == 0:
            return FORMAT_ALARM_STATUS_USER.format(
                query=query,
                alarm_count=0,
                alarms_text="тревог нет",
            )
        lines = []
        for a in result.active:
            ts = a.triggered_at.strftime("%H:%M") if a.triggered_at else "—"
            lines.append(f"  [{a.level}] {a.alarm_id} ({ts})")
        return FORMAT_ALARM_STATUS_USER.format(
            query=query,
            alarm_count=result.count,
            alarms_text="\n".join(lines),
        )

    def _fmt_composite(self, query: str, data: dict[str, Any]) -> str:
        cs = data.get("composite_status")
        if cs is None:
            return FORMAT_COMPOSITE_STATUS_USER.format(
                query=query,
                experiment_text="нет данных",
                phase_text="нет данных",
                temps_text="нет данных",
                pressure_text="нет данных",
                cooldown_eta_text="нет данных",
                vacuum_eta_text="нет данных",
                alarms_text="нет данных",
            )

        exp = cs.experiment
        exp_text = exp.experiment_id if exp else "нет активного эксперимента"
        phase_text = exp.phase if exp else "—"

        temps_parts = [
            f"{ch}: {val:.2f} K" if val is not None else f"{ch}: нет"
            for ch, val in cs.key_temperatures.items()
        ]
        temps_text = ", ".join(temps_parts) if temps_parts else "нет данных"

        pressure_text = (
            f"{cs.current_pressure:.2e} mbar"
            if cs.current_pressure is not None
            else "нет данных"
        )

        cd = cs.cooldown_eta
        if cd is None:
            cd_text = "нет прогноза"
        else:
            h = max(cd.t_remaining_hours, 0.0)
            cd_text = f"{int(h)}ч {int((h % 1) * 60)}мин"

        vac = cs.vacuum_eta
        if vac is None:
            vac_text = "нет прогноза"
        elif vac.eta_seconds is None:
            vac_text = "не определено"
        else:
            h = vac.eta_seconds / 3600
            vac_text = f"{int(h)}ч {int((h % 1) * 60)}мин"

        alarms_text = (
            ", ".join(a.alarm_id for a in cs.active_alarms)
            if cs.active_alarms
            else "тревог нет"
        )

        return FORMAT_COMPOSITE_STATUS_USER.format(
            query=query,
            experiment_text=exp_text,
            phase_text=phase_text,
            temps_text=temps_text,
            pressure_text=pressure_text,
            cooldown_eta_text=cd_text,
            vacuum_eta_text=vac_text,
            alarms_text=alarms_text,
        )
