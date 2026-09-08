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
    RETRIEVAL_DECISION_SYSTEM,
    RETRIEVAL_DECISION_USER,
)
from cryodaq.agents.assistant.query.router import QueryRouter, QueryUnavailableError
from cryodaq.agents.assistant.query.ru_labels import (
    phase_display_name,
    ru_bool,
)
from cryodaq.agents.assistant.query.schemas import (
    ARCHIVE_DETAIL_INVALID_REQUEST_REASON,
    QueryAdapters,
    QueryCategory,
)
from cryodaq.agents.rag.source_labels import prettify_source_label

if TYPE_CHECKING:
    from cryodaq.agents.assistant.live.agent import AssistantConfig
    from cryodaq.agents.assistant.shared.audit import AuditLogger
    from cryodaq.agents.assistant.shared.ollama_client import (
        GenerationResult,
        OllamaClient,
    )
    from cryodaq.core.channel_manager import ChannelManager

# Fallbacks only — the live values come from config (query.format_max_tokens
# and query.format_num_ctx). They were constants until 2026-09-06, sized
# "against num_ctx (8192)": a context this deployment no longer has, and one
# nobody could change without editing this file. A reasoning model routinely
# spends 2-3k tokens thinking before it writes anything the operator sees, so
# the answer budget has to clear that on top of the prompt and the retrieved
# pages — which is exactly the kind of judgement that belongs in config, next
# to the model it is sized for.
_FORMAT_MAX_TOKENS = 6144
# Sized for a 4 GiB card that is long gone. The interactive path passes this
# explicitly on every call, so it — not ollama.num_ctx — is the window a
# conversation actually gets.
_FORMAT_NUM_CTX = 100_000

logger = logging.getLogger(__name__)

_FALLBACK = "Произошла внутренняя ошибка. Попробуй ещё раз или обратись к оператору."
_RATE_WINDOW_S = 3600.0
_RATE_BUCKET_SWEEP_INTERVAL_S = 60.0
_MAX_RATE_BUCKETS = 4096


def _format_horizons(forecast: dict[str, float] | None) -> str:
    """The horizon forecast as a self-contained block, ordered by hours ahead.

    Carries its own heading and its own instruction so the section simply is
    not there when the engine supplies no forecast. A fixed template that
    always asks for a column, with "нет данных" where the column should be,
    gave a small model contradictory instructions and it answered with two
    bare numbers.

    Dict order is insertion order and a wire round-trip need not preserve the
    intended sequence, so the ordering is re-established here rather than
    trusted — a forecast listing 12 h before 3 h reads as an error.
    """
    if not forecast:
        return "Прогноз по горизонтам недоступен."

    def hours_of(item: tuple[str, float]) -> float:
        try:
            return float(item[0])
        except (TypeError, ValueError):
            return float("inf")

    lines = [f"  +{hours} ч: {pressure:.2e} мбар" for hours, pressure in sorted(forecast.items(), key=hours_of)]
    return "Прогноз давления по горизонтам (выведи их столбиком, как есть):\n" + "\n".join(lines)


#: Categories that fetch documents but no live state. The motivating question —
#: "почему давление растёт, если насос выключен?" — lands here, and until
#: 2026-09-07 it therefore answered about the manuals while the readings it
#: needed sat one adapter away. It does not need a retrieval DECISION (the
#: router already retrieves for it); it needs the stand.
_STATE_HUNGRY_CATEGORIES = frozenset({QueryCategory.KNOWLEDGE_QUERY})

_RETRIEVAL_DECIDING_CATEGORIES = frozenset(
    {
        QueryCategory.COMPOSITE_STATUS,
        QueryCategory.CURRENT_VALUE,
        QueryCategory.ETA_VACUUM,
        QueryCategory.ETA_COOLDOWN,
        QueryCategory.PHASE_INFO,
        QueryCategory.ALARM_STATUS,
        QueryCategory.RANGE_STATS,
        QueryCategory.UNKNOWN,
    }
)
#: The decision is one line. A budget this small also keeps a reasoning model
#: from thinking its way past the answer.
_RETRIEVAL_DECISION_MAX_TOKENS = 120
#: The decision is one line. Giving it the formatting stage's 1500 s — which is
#: what it took until review on 2026-09-07 — meant an enrichment could spend the
#: answer's entire budget before the answer began. Generous enough for a cold
#: model load (measured 23 s) and nothing like generous enough to matter.
_RETRIEVAL_DECISION_TIMEOUT_S = 300.0
#: The search stage. Sized so intent + decision + search + format sits under the
#: handler budget with room to spare; see tests/agents/test_timeout_chain_is_ordered.py,
#: which asserts the sum rather than only the neighbouring pairs.
_RETRIEVAL_SEARCH_TIMEOUT_S = 240.0
#: Beyond this many standard errors the exact number says nothing a person can
#: use. Reported as words instead.
_SIGMA_BEYOND_DOUBT = 10.0
#: Reading or appending one small transcript. Generous for a healthy disk,
#: finite because a stalled read on this loop stops every deadline above it.
_CONVERSATION_IO_TIMEOUT_S = 5.0
#: Bounded so a model that ignores the format cannot turn its whole answer into
#: a search query.
_MAX_RETRIEVAL_QUERY_CHARS = 200


def _format_retrieved_documents(result) -> str:
    """Corpus extracts the model asked for, or nothing at all.

    Empty when it asked for none — an empty "Документы: —" section invites the
    model to comment on their absence, which is noise in an answer about the
    current state.
    """
    if result is None:
        return ""
    hits = getattr(result, "hits", None) or []
    if not hits:
        asked = getattr(result, "query", None)
        if not asked:
            return ""
        return f"Документы: по запросу «{asked}» в корпусе ничего не нашлось."
    rows = []
    for index, hit in enumerate(hits, 1):
        # `KnowledgeQueryHit` carries `source` and `snippet`. The first version
        # read `source_id` and `text`, which do not exist on it, so every
        # retrieved document rendered as "[1] manual.pdf: " with an empty body —
        # the model was handed citations with nothing in them. Found by review
        # 2026-09-07; I had guessed the field names instead of reading the type.
        source = getattr(hit, "source", None) or getattr(hit, "source_id", None) or "?"
        body = getattr(hit, "snippet", None) or getattr(hit, "text", "") or ""
        rows.append(f"[{index}] {source}: {str(body).strip().replace(chr(10), ' ')}")
    return "Документы, которые ты сам запросил (цитируй как [1], [2]):\n" + "\n".join(rows)


def _parse_retrieval_decision(text: str) -> str | None:
    """The search query the model asked for, or None if it asked for nothing.

    Deliberately forgiving about surroundings and strict about the marker: a
    model that answers the question instead of deciding must not have its
    answer mistaken for a search query.
    """
    if not text:
        return None
    for raw in text.splitlines():
        line = raw.strip().strip("`*").strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("НЕТ"):
            return None
        for marker in ("ПОИСК:", "SEARCH:"):
            if upper.startswith(marker):
                query = line[len(marker) :].strip().strip('"').strip()
                return query[:_MAX_RETRIEVAL_QUERY_CHARS] or None
    return None


def _format_trends(trends) -> str:
    """One line per channel that is going somewhere. Empty when nothing is.

    Rendered from the span that ACTUALLY arrived, not the window that was
    asked for: the engine caps a history reply at 10000 samples, and "за 6 ч"
    over a 2.8 h window is a small lie that compounds into a wrong rate in the
    operator's head.
    """
    if not trends:
        return "нет данных о динамике"
    # Said once, where the numbers are, because it qualifies all of them: these
    # are pointwise intervals computed as though the residuals were independent.
    # They are not simultaneous across a monitoring run, and hourly averaging
    # does not itself make slow correlations go away.
    caveat = (
        "погрешности — поточечные, в предположении независимых остатков; "
        "при ежечасном пересмотре они не дают одновременного покрытия"
    )
    rows: list[str] = []
    for name, trend in sorted(trends.items()):
        if not getattr(trend, "available", False):
            rows.append(f"{name}: динамика недоступна ({getattr(trend, 'reason', '?')})")
            continue
        # The number and its uncertainty, not a verdict. `direction` used to
        # collapse this into one of three Russian words and got them wrong on
        # autocorrelated noise and on completed steps; the model reading this
        # has more to work with than the word carried.
        parts = [f"{trend.rate_per_hour:+.3g}/ч за {trend.span_hours:.1f} ч"]
        z = trend.significance
        if z is not None:
            # CAPPED. A clean ramp over thousands of samples produces four-digit
            # sigmas — the assistant told an operator "сигнал 1495σ", which is
            # noise wearing the costume of precision. Past ten sigma the only
            # honest content is "this is not noise".
            if z >= _SIGMA_BEYOND_DOUBT:
                parts.append("наклон уверенный")
            elif z >= 1:
                parts.append(f"наклон {z:.0f}σ")
            else:
                parts.append("в пределах шума")
        # THE SHAPE, NOT JUST THE SLOPE. A leak holds its rate; desorption
        # exhausts its source and decays. One slope cannot tell them apart, and
        # on 2026-09-08 the assistant said exactly that to the operator who
        # asked. Three consecutive rates can.
        # ONE CURVATURE ONLY WHEN THERE IS ONE. `slope_change` fits a single
        # bend to the whole window, so it answers "how much did the rate change"
        # only while the rate moves one way. On 2026-09-09 the thirds ran
        # 0.101, 0.0989, 0.113 — down then up — and the single number came out
        # slightly negative beside three rates whose ends clearly rose. The
        # agent reported the contradiction to the operator and said, correctly,
        # that it could not resolve it. It could not because both numbers were
        # right about different questions, and only one of them was labelled.
        rates = [rate for rate, _ in trend.segments]
        monotonic = len(rates) < 2 or all(
            b >= a for a, b in zip(rates, rates[1:])
        ) or all(b <= a for a, b in zip(rates, rates[1:]))
        agrees = True
        if trend.slope_change is not None and len(rates) >= 2:
            # AND IT MUST POINT THE SAME WAY AS THE RATES BESIDE IT. A single
            # number saying the rate fell, printed next to three rates that
            # rose, is the contradiction the operator was handed. Either
            # estimator can be the right one; neither is right enough to print
            # against the other.
            agrees = (trend.slope_change[0] >= 0) == (rates[-1] >= rates[0])
        if trend.slope_change is not None and monotonic and agrees:
            change, change_err = trend.slope_change
            parts.append(f"изменение темпа по окну {change:+.3g} ± {change_err:.2g}/ч")
        elif trend.slope_change is not None:
            parts.append(
                "темп по окну не монотонен, единого изменения нет"
                if not monotonic
                else "оценки изменения темпа расходятся по знаку, единого изменения нет"
            )
        if trend.segments:
            # WITH THE ERRORS. Bare rates make a noisy segment and a tight one
            # look alike, and the shape of the curve is exactly what the
            # operator reads off this line.
            rates = ", ".join(f"{rate:+.3g} ± {err:.2g}" for rate, err in trend.segments)
            parts.append(f"по третям окна: {rates}")
        # THE SHAPE OF THE RISE, from where the rise began. A window that starts
        # mid-rise cannot separate a constant source from a decaying one; their
        # difference lives in the first hour, where a decaying source is
        # steepest. This is that comparison, as ratios rather than a verdict.
        # ONLY FOR A PRESSURE. The three laws describe a source filling a closed
        # volume; on a temperature they describe nothing, and the reading rule in
        # the prompt would turn a warming sensor's straight line into the
        # signature of a vacuum leak. Same test the router uses.
        # THE CHANNEL, NOT THE LABEL. The key here is whatever the caller chose
        # to display — "давление" as often as the channel id — so testing it
        # silently switched the shape off for the one channel it is for.
        identity = f"{getattr(trend, 'channel', '')} {name}".lower()
        is_pressure = "pressure" in identity or "mbar" in identity
        if trend.shape is not None and is_pressure:
            linear, root, log = trend.shape
            if linear > 0.0:
                since = (
                    f"режим идёт {trend.regime_hours:.1f} ч"
                    if trend.regime_hours is not None
                    else "режим не менялся в окне"
                )
                parts.append(
                    f"{since}, форма подъёма: прямая RMS {linear:.3g}, "
                    f"√t хуже в {root / linear:.1f}, ln t хуже в {log / linear:.1f}"
                )
        rows.append(f"{name}: {', '.join(parts)}")
    return "; ".join(rows) + f". {caveat}"


def _vacuum_forecast_qualifier(vac) -> str:
    """What the vacuum forecast is worth, in the operator's words.

    Empty when the forecast carries no warning of its own — a good forecast
    should not be hedged into uselessness.
    """
    parts: list[str] = []
    trend = (getattr(vac, "trend", "") or "").strip().lower()
    if trend == "anomaly":
        parts.append("модель отмечает аномалию")
    confidence = getattr(vac, "confidence", None)
    if isinstance(confidence, (int, float)):
        if confidence < 0:
            parts.append(f"R²={confidence:.2f}, фит хуже постоянной")
        elif confidence < 0.5:
            parts.append(f"R²={confidence:.2f}")
    current = getattr(vac, "current_mbar", None)
    target = getattr(vac, "target_mbar", None)
    eta = getattr(vac, "eta_seconds", None)
    if (
        isinstance(current, (int, float))
        and isinstance(target, (int, float))
        and isinstance(eta, (int, float))
        and current > target
        and eta <= 0
    ):
        parts.append("цель НЕ достигнута: давление выше неё, а прогноз нулевой")
    return "; ".join(parts)


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
        conversation_store: Any | None = None,
    ) -> None:
        self._ollama = ollama_client
        self._audit = audit_logger
        self._config = config
        # Release the classifier's model only when the answer comes from a
        # different one. Same model for both stages means releasing would
        # unload what the next call immediately reloads.
        self._classifier = IntentClassifier(
            ollama_client,
            model=intent_model,
            temperature=intent_temperature,
            timeout_s=intent_timeout_s,
            channel_manager=channel_manager,
            # What is publishing right now, so the classifier can name the
            # pressure gauge and the source meter — neither is in channels.yaml
            # and until 2026-09-07 neither could be asked about by name.
            # getattr twice on purpose. This runs in the CONSTRUCTOR, so a
            # snapshot object without the method — a stub, an older adapter,
            # anything not the production BrokerSnapshot — would take the whole
            # agent down at construction rather than degrade a hint. Caught by
            # the suite on a StartStop stub before it reached the stand.
            live_channels_provider=getattr(getattr(adapters, "broker_snapshot", None), "latest_with_labels", None),
            release_model_after=intent_model != format_model,
        )
        self._router = QueryRouter(adapters, channel_manager=channel_manager)
        self._format_model = format_model
        self._format_temperature = format_temperature
        self._format_timeout_s = format_timeout_s
        self._max_per_hour = max_queries_per_chat_per_hour
        self._chart_dispatcher = chart_dispatcher
        # Optional: without it every query is a one-shot, which is what it was
        # until 2026-09-07. Prepended to the user prompt rather than threaded
        # through fifteen templates, so every category gets memory at once.
        self._conversation = conversation_store
        self._rate_buckets: dict[int | str, collections.deque[float]] = {}
        self._next_rate_sweep_at = 0.0
        self._closed = False
        self._last_audit_error = False

    @property
    def last_audit_error(self) -> bool:
        return self._last_audit_error

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

    async def close(self) -> None:
        """Drain chart work before the query owner is considered stopped."""
        self._closed = True
        if self._chart_dispatcher is not None:
            await self._chart_dispatcher.close()

    async def _maybe_attach_state(self, intent) -> str:
        """Live readings for the categories that would otherwise answer blind.

        A documentation answer about this stand is better for knowing what the
        stand is doing. Contained like every other enrichment: a failure here
        costs the state block, never the answer.
        """
        if intent is None or getattr(intent, "category", None) not in _STATE_HUNGRY_CATEGORIES:
            return ""
        composite = getattr(getattr(self._router, "_adapters", None), "composite", None)
        if composite is None:
            return ""
        try:
            status = await composite.status()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - enrichment never costs the answer
            logger.debug("state attachment unavailable: %s", exc)
            return ""
        digest = self._state_digest({"composite_status": status})
        return f"Живое состояние стенда прямо сейчас:\n{digest}" if digest else ""

    def _with_documents(self, user_prompt: str, data: dict) -> str:
        """Attach retrieved documents to whatever prompt was built.

        Appended to the assembled prompt rather than threaded through the
        templates: the first version put the block in the composite template
        only, so seven of the eight categories that could ask for documents
        fetched them and then discarded them. Found by review 2026-09-07.
        """
        block = _format_retrieved_documents(data.get("retrieved_documents"))
        if not block:
            return user_prompt
        return f"{user_prompt}\n\n{block}"

    def _conversation_scope(self) -> str | None:
        """Pin the experiment ONCE for a whole question.

        The store consults its provider on every call, so without pinning a long
        question spanning an experiment transition could be classified from one
        run's transcript, formatted from another's, and filed under a third.
        """
        if self._conversation is None:
            return None
        try:
            return self._conversation.current_scope()
        except Exception as exc:  # noqa: BLE001 - memory never costs an answer
            logger.debug("conversation scope unavailable: %s", exc)
            return None

    async def _conversation_transcript(self, chat_id: Any, scope: str | None = None) -> str:
        """What was already said, or "" — never raises, never stalls the handler.

        OFF THE LOOP, WITH A DEADLINE. The transcript is a small file and this
        is microseconds on a healthy disk, but it is unbounded on a hung mount,
        and this loop is carrying a question with a strict budget: a stalled
        read there does not time out, it stops every deadline above it from
        firing. Losing the memory for one turn is a worse answer; losing the
        loop is no answer at all.
        """
        if self._conversation is None:
            return ""
        try:
            return (
                await asyncio.wait_for(
                    asyncio.to_thread(self._conversation.replay, chat_id, scope=scope),
                    timeout=_CONVERSATION_IO_TIMEOUT_S,
                )
                or ""
            )
        except Exception as exc:  # noqa: BLE001 - memory never costs an answer
            logger.debug("conversation replay unavailable: %s", exc)
            return ""

    async def _with_conversation(self, user_prompt: str, chat_id: Any, scope: str | None = None) -> str:
        """Prepend what was already said, if anything was.

        Deliberately a prefix on the assembled prompt rather than a slot in
        each of fifteen templates: the memory belongs to the conversation, not
        to whichever bucket this particular question fell into.
        """
        transcript = await self._conversation_transcript(chat_id, scope)
        if not transcript:
            return user_prompt
        return f"Предыдущий разговор (показания в нём УСТАРЕЛИ — актуальные ниже):\n{transcript}\n\n{user_prompt}"

    async def _maybe_retrieve(self, query: str, intent, data: dict):
        """Let the model decide whether the corpus would help, and with what query.

        The classifier puts a question into one bucket and the router then runs
        one adapter, so a question needing both the live readings and the
        manuals could not have both. On 2026-09-07 "почему давление растёт,
        если насос выключен? натекание или газовыделение MLI?" was bucketed as
        knowledge_query, searched the corpus, found nothing, and asked the
        operator to supply a pressure value the assistant was already holding.

        This is one extra short call on the state-answering paths, and the
        model decides — a fixed rule about which questions "need documents"
        would just be a sixteenth bucket.

        Every failure here is silent by design: retrieval is an enrichment, and
        an enrichment must never cost the operator the answer.
        """
        rag = getattr(self._router, "_adapters", None)
        rag = getattr(rag, "rag", None) if rag is not None else None
        if rag is None or not getattr(rag, "is_available", False):
            return None
        if intent is None or getattr(intent, "category", None) not in _RETRIEVAL_DECIDING_CATEGORIES:
            return None
        try:
            digest = self._state_digest(data)
            decision = await asyncio.wait_for(
                self._ollama.generate(
                    RETRIEVAL_DECISION_USER.format(query=query, state_digest=digest),
                    model=self._format_model,
                    system=RETRIEVAL_DECISION_SYSTEM,
                    temperature=0.0,
                    max_tokens=_RETRIEVAL_DECISION_MAX_TOKENS,
                ),
                timeout=_RETRIEVAL_DECISION_TIMEOUT_S,
            )
            search_query = _parse_retrieval_decision(getattr(decision, "text", "") or "")
            if not search_query:
                return None
            logger.info("AssistantQueryAgent: модель запросила поиск — %r", search_query[:120])
            # BOUNDED. The decision to search was bounded and so is the
            # formatting, but the search itself was not — and it is the stage
            # most able to hang rather than fail: the embedding call is HTTP
            # with its own deadline, but the LanceDB read runs in a thread, and
            # `asyncio.to_thread` cannot be cancelled. An unbounded stage makes
            # the handler's budget unenforceable, so the transport gives up
            # first and the operator is told the outcome is unknown instead of
            # getting a plain answer.
            return await asyncio.wait_for(
                rag.search(search_query), timeout=_RETRIEVAL_SEARCH_TIMEOUT_S
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - enrichment never costs the answer
            logger.debug("retrieval decision unavailable: %s", exc)
            return None

    @staticmethod
    def _state_digest(data: dict) -> str:
        """What the model already holds, in a few lines.

        Short on purpose. This feeds a yes/no decision, not the answer, and a
        digest as long as the answer would just pay the cost twice.
        """
        cs = data.get("composite_status") or data.get("composite")
        parts: list[str] = []
        if cs is not None:
            phase = getattr(getattr(cs, "experiment", None), "current_phase", None)
            if phase:
                parts.append(f"фаза: {phase}")
            temps = getattr(cs, "key_temperatures", None) or {}
            if temps:
                parts.append(f"температур в наличии: {len(temps)}")
            pressure = getattr(cs, "current_pressure", None)
            if pressure is not None:
                parts.append(f"давление: {pressure:.3g} мбар")
            trends = getattr(cs, "trends", None) or {}
            if trends:
                parts.append("динамика: " + _format_trends(trends))
            alarms = getattr(cs, "active_alarms", None)
            parts.append(f"активных тревог: {len(alarms) if alarms else 0}")
        if not parts:
            keys = ", ".join(sorted(k for k in data if not k.startswith("_"))) or "ничего"
            parts.append(f"данные под рукой: {keys}")
        return "\n".join(f"- {line}" for line in parts)

    async def _handle_query_inner(
        self,
        query: str,
        *,
        chat_id: int | str | None = None,
    ) -> str:
        if self._closed:
            return _FALLBACK
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
        # ONE QUESTION IS ONE CONVERSATION. Resolved here and carried through
        # every use below, because the store consults its provider afresh on
        # each call: a long question spanning an experiment transition could
        # otherwise be classified from one run's transcript, formatted from
        # another's, and filed under a third.
        conversation_scope = self._conversation_scope()

        try:
            # The classifier sees the conversation too. It used to get the bare
            # query, so "а сейчас?" or "почему?" carried no subject: the
            # category was decided blind and the ROUTER then fetched data for
            # the wrong one. Injecting the history only into the format prompt
            # could not repair that — by then the wrong numbers were already in
            # hand, and a fluent answer over the wrong numbers is worse than an
            # honest "не знаю".
            intent = await self._classifier.classify(
                query,
                conversation=await self._conversation_transcript(chat_id, conversation_scope),
            )
            data = await self._router.fetch(intent, query)
            retrieved = await self._maybe_retrieve(query, intent, data)
            if retrieved is not None:
                data = {**data, "retrieved_documents": retrieved}
            state_block = await self._maybe_attach_state(intent)
            user_prompt = self._build_format_user_prompt(query, intent.category, data)
            user_prompt = self._with_documents(user_prompt, data)
            if state_block:
                user_prompt = f"{user_prompt}\n\n{state_block}"
            user_prompt = await self._with_conversation(user_prompt, chat_id, conversation_scope)
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
                    # A reasoning model spends most of this budget thinking
                    # before it writes a word the operator sees. At 2048 a
                    # documentation answer over retrieved manual pages ran out
                    # mid-trace and never reached its conclusion.
                    max_tokens=getattr(self._config, "query_format_max_tokens", _FORMAT_MAX_TOKENS),
                    # Must be passed explicitly: without it Ollama applies its
                    # own 4096 default, which cannot hold the retrieved manual
                    # pages plus a reasoning trace plus the answer.
                    num_ctx=getattr(self._config, "query_format_num_ctx", _FORMAT_NUM_CTX),
                ),
                timeout=self._format_timeout_s,
            )
            if result.truncated or not result.text.strip():
                errors.append("format_llm_truncated_or_empty")
            else:
                response = result.text.strip()
        except QueryUnavailableError as exc:
            logger.warning("AssistantQueryAgent: query unavailable for %r: %s", query[:80], exc)
            errors.append(f"query_unavailable: {exc}")
        except Exception as exc:
            logger.warning("AssistantQueryAgent: pipeline error for %r: %s", query[:80], exc)
            errors.append(f"unexpected: {exc}")

        latency_s = time.monotonic() - t0
        cat_str = intent.category.value if intent is not None else "error"

        try:
            self._last_audit_error = False
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
                output_intent=["telegram"] if chat_id is not None else [],
                outputs_dispatched=[],
                errors=errors,
            )
        except Exception:
            self._last_audit_error = True
            logger.warning("AssistantQueryAgent: audit log failed", exc_info=True)
            return response

        # REMEMBERED HERE, NOT WHERE IT WAS WRITTEN. The exchange used to be
        # stored the moment the format call returned — before the audit. An
        # audit failure makes the caller return `delivery_state: not_dispatched`
        # and `commit_state: not_committed`, so the operator never sees that
        # text; the agent nonetheless carried it into the next turn's history
        # and answered follow-ups about a message that, for the operator, was
        # never said. Past the audit is the last point at which this agent still
        # withholds an answer, so it is the honest place to commit the memory.
        #
        # Only what was SAID: the state blocks are rebuilt every turn on
        # purpose, because a remembered reading is a stale reading.
        if self._conversation is not None and response is not _FALLBACK and response.strip():
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._conversation.remember,
                        chat_id,
                        query,
                        response,
                        scope=conversation_scope,
                    ),
                    timeout=_CONVERSATION_IO_TIMEOUT_S,
                )
            except Exception as exc:  # noqa: BLE001 - memory never costs an answer
                logger.debug("conversation not remembered: %s", exc)

        if self._chart_dispatcher is not None and chat_id is not None:
            self._chart_dispatcher.dispatch(intent.category if intent is not None else None, data, chat_id)

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
        if not eta.available:
            return f"Запрос: {query}\n\nПрогноз охлаждения недоступен: {eta.reason}. Не утверждай, что прогноза нет."
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
                target_mbar=float("nan"),
                eta_str="нет прогноза",
                trend="нет данных",
                p_ultimate="неизвестен",
                horizons_block="Прогноз по горизонтам недоступен.",
                confidence=0.0,
            )
        if not eta.available:
            return f"Запрос: {query}\n\nВакуумный прогноз недоступен: {eta.reason}. Не утверждай, что прогноза нет."

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
            p_ultimate=(f"{eta.p_ultimate_mbar:.2e} mbar" if eta.p_ultimate_mbar is not None else "не определён"),
            horizons_block=_format_horizons(eta.horizon_forecast),
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
        unavailable = [stats.reason for stats in stats_dict.values() if not stats.available]
        if unavailable:
            return (
                f"Запрос: {query}\n\nСтатистика диапазона недоступна: {unavailable[0]}. Не подставляй нулевые значения."
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
        if not status.available:
            return (
                f"Запрос: {query}\n\nСтатус эксперимента недоступен: {status.reason}. "
                "Не утверждай, что активного эксперимента нет."
            )
        exp_id_text = status.experiment_id
        if status.experiment_started_human:
            exp_id_text += f" (начат {status.experiment_started_human})"
        if status.experiment_age_s is None:
            age_text = "нет данных"
        else:
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
        if result is None:
            return FORMAT_ALARM_STATUS_USER.format(
                query=query,
                alarm_count="нет данных",
                alarms_text="нет данных о тревогах",
            )
        if not result.available:
            return f"Запрос: {query}\n\nСостояние тревог недоступно: {result.reason}. Не утверждай, что тревог нет."
        if result.count == 0:
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
                trends_text="нет данных о динамике",
                vacuum_eta_text="нет данных",
                alarms_text="нет данных",
            )
        if not cs.available:
            return (
                f"Запрос: {query}\n\nСнимок текущих данных недоступен: {cs.reason}. "
                "Не утверждай, что поток только запускается."
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
        elif not cd.available:
            cd_text = f"недоступен: {cd.reason}"
        else:
            h = max(cd.t_remaining_hours, 0.0)
            cd_text = f"{int(h)}ч {int((h % 1) * 60)}мин"

        vac = cs.vacuum_eta
        if vac is None:
            vac_text = "нет прогноза"
        elif not vac.available:
            vac_text = f"недоступен: {vac.reason}"
        else:
            # The target travels with the forecast. It comes from the engine's
            # configuration and changes with the gauge in use, so naming it
            # here keeps a summary from implying a threshold nobody set.
            target = f"{vac.target_mbar:.0e} мбар"
            if vac.eta_seconds is None:
                vac_text = f"до {target} — не определено"
            else:
                h = vac.eta_seconds / 3600
                vac_text = f"до {target}: {int(h)}ч {int((h % 1) * 60)}мин"
            # The forecast's own quality travels WITH the forecast.
            #
            # Reported 2026-09-07: asked "what is happening", the assistant said
            # "до 1e-01 мбар по прогнозу уже сейчас — 0ч 0мин" while the gauge
            # read 2.02e-01 and RISING with the pump switched off. The engine was
            # honest about it — trend "anomaly", confidence -1.26e-11, two of
            # three fit parameters pinned at their bounds, and an identical
            # forecast at 1, 3, 6, 12, 24 and 48 hours — and this line dropped
            # every one of those and stated the number.
            #
            # The dedicated ETA prompt already carries trend and R² and warns
            # the model not to read R² as confidence. The composite path handed
            # it a flattened string instead. Annotating, not suppressing: the
            # operator gets the number AND what it is worth.
            qualifier = _vacuum_forecast_qualifier(vac)
            if qualifier:
                vac_text = f"{vac_text} [{qualifier}]"

        alarms_text = (
            ", ".join(a.alarm_id for a in cs.active_alarms)
            if cs.active_alarms
            else "тревог нет"
            if cs.alarms_available
            else "нет данных о тревогах"
        )

        return FORMAT_COMPOSITE_STATUS_USER.format(
            query=query,
            experiment_text=exp_text,
            phase_text=phase_text,
            temps_text=temps_text,
            pressure_text=pressure_text,
            cooldown_eta_text=cd_text,
            trends_text=_format_trends(getattr(cs, "trends", {})),
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
        if not result.available:
            return f"Запрос: {query}\n\nАрхив недоступен: {result.reason}. Не утверждай, что записей нет."
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
        if result.reason == ARCHIVE_DETAIL_INVALID_REQUEST_REASON:
            return (
                f"Запрос: {query}\n\n"
                "Не указан идентификатор эксперимента, поэтому архив не запрашивался. "
                "Уточните идентификатор; не утверждай, что запись не найдена."
            )
        if not result.available:
            return (
                f"Запрос: {query}\n\n"
                f"Детали эксперимента {ident} недоступны: {result.reason}.\n"
                "Не утверждай, что запись не найдена."
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
        if not result.available:
            return f"Запрос: {query}\n\nИстория тревог недоступна: {result.reason}. Не подставляй нулевые счётчики."
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
        if not result.available:
            return (
                f"Запрос: {query}\n\nСемантический поиск недоступен: {result.reason}. Не утверждай, что совпадений нет."
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
