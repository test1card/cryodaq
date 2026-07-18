"""AssistantQueryAgent — F30 Live Query Agent orchestrator.

Three-step pipeline: classify intent → fetch from adapters → format with LLM.
Never raises from handle_query(); returns Russian error string on all failures.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cryodaq.agents.assistant.live.prompts import format_with_brand
from cryodaq.agents.assistant.query.chart_dispatcher import ChartDispatcher
from cryodaq.agents.assistant.query.intent_classifier import IntentClassifier
from cryodaq.agents.assistant.query.prompts import (
    FORMAT_ALARM_HISTORY_USER,
    FORMAT_ALARM_STATUS_USER,
    FORMAT_ARCHIVE_DETAIL_USER,
    FORMAT_ARCHIVE_LIST_USER,
    FORMAT_COMPOSITE_STATUS_USER,
    FORMAT_CURRENT_VALUE_USER,
    FORMAT_ETA_COOLDOWN_USER,
    FORMAT_ETA_VACUUM_USER,
    FORMAT_KNOWLEDGE_QUERY_USER,
    FORMAT_OUT_OF_SCOPE_GENERAL_USER,
    FORMAT_OUT_OF_SCOPE_HISTORICAL_USER,
    FORMAT_PHASE_INFO_USER,
    FORMAT_RANGE_STATS_USER,
    FORMAT_RESPONSE_SYSTEM,
    FORMAT_UNKNOWN_USER,
)
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.ru_labels import (
    phase_display_name,
    ru_bool,
)
from cryodaq.agents.assistant.query.schemas import QueryAdapters, QueryCategory
from cryodaq.agents.rag.source_labels import prettify_source_label

if TYPE_CHECKING:
    from cryodaq.agents.assistant.live.agent import AssistantConfig
    from cryodaq.agents.assistant.shared.audit import AuditLogger
    from cryodaq.agents.assistant.shared.ollama_client import (
        GenerationResult,
        OllamaClient,
    )
    from cryodaq.core.channel_manager import ChannelManager

logger = logging.getLogger(__name__)

_FALLBACK = "Произошла внутренняя ошибка. Попробуй ещё раз или обратись к оператору."
_RATE_WINDOW_S = 3600.0
_RATE_BUCKET_SWEEP_INTERVAL_S = 60.0
_MAX_RATE_BUCKETS = 4096


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
        channel_manager: ChannelManager | None = None,
        chart_dispatcher: ChartDispatcher | None = None,
    ) -> None:
        self._ollama = ollama_client
        self._audit = audit_logger
        self._config = config
        self._classifier = IntentClassifier(
            ollama_client,
            model=intent_model,
            temperature=intent_temperature,
            timeout_s=intent_timeout_s,
            channel_manager=channel_manager,
        )
        self._router = QueryRouter(adapters, channel_manager=channel_manager)
        self._format_model = format_model
        self._format_temperature = format_temperature
        self._format_timeout_s = format_timeout_s
        self._max_per_hour = max_queries_per_chat_per_hour
        self._chart_dispatcher = chart_dispatcher
        self._rate_buckets: dict[int | str, collections.deque[float]] = {}
        self._next_rate_sweep_at = 0.0

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
        try:
            return await self._handle_query_inner(query, chat_id=chat_id)
        except Exception:
            logger.warning("AssistantQueryAgent: unexpected error for %r", query[:80], exc_info=True)
            return _FALLBACK

    async def _handle_query_inner(
        self,
        query: str,
        *,
        chat_id: int | str | None = None,
    ) -> str:
        if chat_id is not None and not self._check_rate(chat_id):
            logger.info("AssistantQueryAgent: rate-limited chat_id=%s", chat_id)
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
            user_prompt = self._build_format_user_prompt(query, intent.category, data)
            system_prompt = format_with_brand(FORMAT_RESPONSE_SYSTEM, self._config.brand_name)
            # Bound the format LLM call by _format_timeout_s. Without this
            # wrapper a hung Ollama format call (cold model load that never
            # returns, stalled socket) hangs the whole query agent
            # indefinitely. On timeout asyncio.TimeoutError propagates to the
            # broad ``except Exception`` below → errors logged, response stays
            # _FALLBACK (bounded fallback). _format_timeout_s is stored in
            # __init__ (default 20 s).
            result = await asyncio.wait_for(
                self._ollama.generate(
                    user_prompt,
                    model=self._format_model,
                    system=system_prompt,
                    temperature=self._format_temperature,
                    max_tokens=2048,
                ),
                timeout=self._format_timeout_s,
            )
            if result.truncated or not result.text.strip():
                errors.append("format_llm_truncated_or_empty")
            else:
                response = result.text.strip()
                if self._chart_dispatcher is not None and chat_id is not None:
                    self._chart_dispatcher.dispatch(intent.category, data, chat_id)
        except Exception as exc:
            logger.warning("AssistantQueryAgent: pipeline error for %r: %s", query[:80], exc)
            errors.append(f"unexpected: {exc}")

        latency_s = time.monotonic() - t0
        cat_str = intent.category.value if intent is not None else "error"

        try:
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
                model=result.model if result is not None else (self._format_model or "unknown"),
                system_prompt=format_with_brand(FORMAT_RESPONSE_SYSTEM, self._config.brand_name),
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
        except Exception:
            logger.warning("AssistantQueryAgent: audit log failed", exc_info=True)

        return response

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate(self, chat_id: int | str) -> bool:
        """Return True if within rate limit; record the request."""
        now = time.monotonic()
        cutoff = now - _RATE_WINDOW_S
        if now >= self._next_rate_sweep_at:
            stale = [key for key, candidate in self._rate_buckets.items() if not candidate or candidate[-1] < cutoff]
            for key in stale:
                self._rate_buckets.pop(key, None)
            self._next_rate_sweep_at = now + _RATE_BUCKET_SWEEP_INTERVAL_S

        bucket = self._rate_buckets.get(chat_id)
        if bucket is None:
            if len(self._rate_buckets) >= _MAX_RATE_BUCKETS:
                logger.warning("AssistantQueryAgent: rate registry capacity reached")
                return False
            bucket = collections.deque()
            self._rate_buckets[chat_id] = bucket
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
            logger.warning("_build_format_user_prompt failed for %s: %s", category, exc)
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
        if category == QueryCategory.ARCHIVE_LIST:
            return self._fmt_archive_list(query, data)
        if category == QueryCategory.ARCHIVE_DETAIL:
            return self._fmt_archive_detail(query, data)
        if category == QueryCategory.ALARM_HISTORY:
            return self._fmt_alarm_history(query, data)
        if category == QueryCategory.KNOWLEDGE_QUERY:
            return self._fmt_knowledge_query(query, data)
        if category == QueryCategory.OUT_OF_SCOPE_HISTORICAL:
            return FORMAT_OUT_OF_SCOPE_HISTORICAL_USER.format(query=query, brand_name=self._config.brand_name)
        if category == QueryCategory.OUT_OF_SCOPE_GENERAL:
            return FORMAT_OUT_OF_SCOPE_GENERAL_USER.format(query=query, brand_name=self._config.brand_name)
        return FORMAT_UNKNOWN_USER.format(query=query, brand_name=self._config.brand_name)

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
                val_lines.append(f"  {ch}: {r.value:.4g} {unit}" if r else f"  {ch}: нет данных")
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
                cooldown_active=ru_bool(False),
            )
        h = max(eta.t_remaining_hours, 0.0)
        t_str = f"{int(h)}ч {int((h % 1) * 60)}мин"
        t_cold = f"{eta.T_cold:.2f}" if eta.T_cold is not None else "нет данных"
        return FORMAT_ETA_COOLDOWN_USER.format(
            query=query,
            t_cold=t_cold,
            progress_pct=eta.progress * 100,
            phase=phase_display_name(eta.phase),
            t_remaining_str=t_str,
            ci_low=eta.t_remaining_low_68,
            ci_high=eta.t_remaining_high_68,
            n_references=eta.n_references,
            cooldown_active=ru_bool(eta.cooldown_active),
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
        exp_id_text = status.experiment_id
        if status.experiment_started_human:
            exp_id_text += f" (начат {status.experiment_started_human})"
        age_h = status.experiment_age_s / 3600
        age_text = f"{int(age_h)}ч {int((age_h % 1) * 60)}мин"
        if status.phase_started_at is not None:
            phase_dt = datetime.fromtimestamp(status.phase_started_at, tz=UTC)
            phase_started = phase_dt.strftime("%H:%M UTC")
        else:
            phase_started = "нет данных"
        target = f"{status.target_temp} K" if status.target_temp is not None else "нет данных"
        return FORMAT_PHASE_INFO_USER.format(
            query=query,
            experiment_id=exp_id_text,
            phase=phase_display_name(status.phase),
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

        if getattr(cs, "snapshot_empty", False):
            return (
                f"Запрос: {query}\n\n"
                "Поток данных только запускается — показания датчиков ещё "
                "не поступили (обычно занимает 5–15 секунд после старта). "
                "Скажи оператору по-человечески что система запускается "
                "и предложи повторить запрос через несколько секунд."
            )

        exp = cs.experiment
        exp_text = exp.experiment_id if exp else "нет активного эксперимента"
        phase_text = phase_display_name(exp.phase) if exp else "—"

        temps_parts = [
            f"{ch}: {val:.2f} K" if val is not None else f"{ch}: нет" for ch, val in cs.key_temperatures.items()
        ]
        temps_text = ", ".join(temps_parts) if temps_parts else "нет данных"

        pressure_text = f"{cs.current_pressure:.2e} mbar" if cs.current_pressure is not None else "нет данных"

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

        alarms_text = ", ".join(a.alarm_id for a in cs.active_alarms) if cs.active_alarms else "тревог нет"

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

    # ------------------------------------------------------------------
    # F33 — archive query format prompts
    # ------------------------------------------------------------------

    def _fmt_archive_list(self, query: str, data: dict[str, Any]) -> str:
        result = data.get("archive_list")
        if result is None:
            return FORMAT_ARCHIVE_LIST_USER.format(
                query=query,
                filter_summary="—",
                total_count=0,
                entries_text="(адаптер архива не сконфигурирован)",
            )
        entries = result.entries or []
        if not entries:
            entries_text = "(нет записей за выбранный период)"
        else:
            lines: list[str] = []
            for entry in entries:
                exp_id = entry.get("experiment_id") or "?"
                title = entry.get("title") or ""
                sample = entry.get("sample") or "—"
                operator = entry.get("operator") or "—"
                started = entry.get("start_time") or "—"
                status = entry.get("status") or "—"
                head = f"- {exp_id}"
                if title:
                    head += f" «{title}»"
                lines.append(f"{head}: проба {sample}, оператор {operator}, начало {started}, статус {status}")
            entries_text = "\n".join(lines)
        return FORMAT_ARCHIVE_LIST_USER.format(
            query=query,
            filter_summary=result.filter_summary or "—",
            total_count=result.total_count,
            entries_text=entries_text,
        )

    def _fmt_archive_detail(self, query: str, data: dict[str, Any]) -> str:
        result = data.get("archive_detail")
        ident = data.get("experiment_id") or "—"
        if result is None:
            return FORMAT_ARCHIVE_DETAIL_USER.format(
                query=query,
                experiment_id=ident,
                sample="—",
                operator="—",
                status="—",
                started_at="—",
                ended_at="—",
                duration_str="—",
                phases_text="(нет данных)",
                cooldown_text="(не указано)",
            )
        if result.duration_h is None:
            duration_str = "не зафиксировано"
        else:
            h_int = int(result.duration_h)
            mins = int((result.duration_h - h_int) * 60)
            duration_str = f"{h_int}ч {mins}мин"
        if result.phases:
            phase_lines = []
            for p in result.phases:
                # v0.55.16 (audit SCOPE 3 finding 3.6) — defensive
                # filter against non-dict phase rows (already filtered
                # at the loader, but format prompt should not crash if
                # legacy data slips through) + localise raw English
                # phase identifiers ("cooldown", "warmup", "preparation",
                # "measurement") to operator-facing Russian via the
                # shared `phase_display_name` helper.
                if not isinstance(p, dict):
                    continue
                pname = phase_display_name(p.get("phase"))
                p_started = p.get("started_at", "—")
                p_ended = p.get("ended_at", "—")
                phase_lines.append(f"- {pname}: {p_started} → {p_ended}")
            phases_text = "\n".join(phase_lines) if phase_lines else "(нет данных)"
        else:
            phases_text = "(нет данных)"
        cooldown = result.cooldown_metrics
        if cooldown:
            cooldown_text = f"началось {cooldown.get('started_at', '—')}, закончилось {cooldown.get('ended_at', '—')}"
        else:
            cooldown_text = "(нет фазы захолаживания в архиве этого эксперимента)"
        return FORMAT_ARCHIVE_DETAIL_USER.format(
            query=query,
            experiment_id=result.experiment_id or ident,
            sample=result.sample or "—",
            operator=result.operator or "—",
            status=result.status or "—",
            started_at=result.started_at or "—",
            ended_at=result.ended_at or "не зафиксировано",
            duration_str=duration_str,
            phases_text=phases_text,
            cooldown_text=cooldown_text,
        )

    def _fmt_alarm_history(self, query: str, data: dict[str, Any]) -> str:
        result = data.get("alarm_history")
        if result is None:
            return FORMAT_ALARM_HISTORY_USER.format(
                query=query,
                window_description="—",
                triggered_count=0,
                cleared_count=0,
                by_alarm_id_text="(адаптер архива не сконфигурирован)",
            )
        if result.by_alarm_id:
            top = sorted(result.by_alarm_id.items(), key=lambda kv: kv[1], reverse=True)
            lines = [f"- {aid} ×{count}" for aid, count in top]
            by_alarm_id_text = "\n".join(lines)
        else:
            by_alarm_id_text = "(тревог не было)"
        return FORMAT_ALARM_HISTORY_USER.format(
            query=query,
            window_description=result.window_description or "—",
            triggered_count=result.triggered_count,
            cleared_count=result.cleared_count,
            by_alarm_id_text=by_alarm_id_text,
        )

    # ------------------------------------------------------------------
    # F32 Stage 2 (v0.55.7) — knowledge query format prompt
    # ------------------------------------------------------------------

    def _fmt_knowledge_query(self, query: str, data: dict[str, Any]) -> str:
        result = data.get("knowledge_query")
        if result is None:
            return FORMAT_KNOWLEDGE_QUERY_USER.format(
                query=query,
                total_hits=0,
                filter_note="",
                hits_text="(семантический поиск недоступен — RAG-индекс не сконфигурирован)",
            )
        hits = list(result.hits)
        filter_note = f" (фильтр source_kind={result.source_kind_filter})" if result.source_kind_filter else ""
        if not hits:
            hits_text = "(совпадений не найдено)"
        else:
            lines: list[str] = []
            for idx, hit in enumerate(hits, start=1):
                # v0.55.7.1 PHASE 9: prefer the prettified citation
                # label («Etalon MultiLine — стр. 5», «Процедура: …»)
                # so the LLM cites the document operator can recognise
                # rather than a chunk-id path. Fall back to source_id
                # when prettifier is non-specific (would just echo the
                # kind string).
                pretty = prettify_source_label(hit.source_kind, getattr(hit, "metadata", None) or {})
                if pretty == hit.source_kind:
                    pretty = f"{self._kind_label(hit.source_kind)} — {hit.source}"
                lines.append(f"[Источник {idx}] {pretty} (score={hit.distance:.2f})\n  «{hit.snippet}»")
            hits_text = "\n".join(lines)
        return FORMAT_KNOWLEDGE_QUERY_USER.format(
            query=query,
            total_hits=result.total_hits,
            filter_note=filter_note,
            hits_text=hits_text,
        )

    @staticmethod
    def _kind_label(kind: str) -> str:
        # Localised labels keep the format prompt's "Источники:" block
        # readable without exposing internal corpus-kind identifiers.
        # v0.55.14 (audit SCOPE 6 finding 6.4 follow-up) — keys
        # match the canonical names emitted by document_loader.py
        # (vault_note, not vault); the legacy "vault" alias is kept so
        # an old index does not regress to the raw identifier.
        return {
            "experiment_metadata": "архив",
            "vault_note": "vault",
            "vault": "vault",
            "operator_log": "журнал",
        }.get(kind, kind or "источник")
