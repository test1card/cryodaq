"""F32 Stage 2 (v0.55.7) — KNOWLEDGE_QUERY end-to-end through QueryRouter.

The router only adds a thin dispatch branch; these tests pin the contract
between QueryRouter and RAGAdapter:

- KNOWLEDGE_QUERY routes to ``adapters.rag.search`` with the original
  operator query string and the optional ``target_source_kind`` filter.
- Missing / unavailable RAGAdapter collapses to ``{"knowledge_query": None}``
  so the format prompt can frame the failure politely.
- Adapter exceptions never surface to the agent (already covered in
  the router's blanket try/except).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import (
    AlarmStatusResult,
    CompositeStatus,
    KnowledgeQueryHit,
    KnowledgeQueryResult,
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)


def _make_adapters(*, rag=None) -> QueryAdapters:
    snap = MagicMock()
    snap.latest = AsyncMock(return_value=None)
    snap.latest_age_s = AsyncMock(return_value=None)
    snap.latest_all = AsyncMock(return_value={})

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    sqlite = MagicMock()
    sqlite.range_stats = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=AlarmStatusResult())
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)
    composite = MagicMock()
    composite.status = AsyncMock(
        return_value=CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=None,
            cooldown_eta=None,
            vacuum_eta=None,
            active_alarms=[],
            key_temperatures={},
            current_pressure=None,
        )
    )
    return QueryAdapters(
        broker_snapshot=snap,
        cooldown=cooldown,
        vacuum=vacuum,
        sqlite=sqlite,
        alarms=alarms,
        experiment=experiment,
        composite=composite,
        rag=rag,
    )


# ---------------------------------------------------------------------------
# Router dispatch
# ---------------------------------------------------------------------------


async def test_router_dispatches_knowledge_query_with_raw_query_text() -> None:
    """The original phrasing — not intent.quantity — is sent to RAG: it has
    far stronger semantic signal than the classifier's terse paraphrase."""
    rag = MagicMock()
    rag.is_available = True
    expected = KnowledgeQueryResult(query="raw", hits=[], total_hits=0)
    rag.search = AsyncMock(return_value=expected)

    adapters = _make_adapters(rag=rag)
    router = QueryRouter(adapters)

    intent = QueryIntent(
        category=QueryCategory.KNOWLEDGE_QUERY,
        quantity="процедура",
    )
    out = await router.fetch(intent, "как делать калибровку датчика?")

    assert "knowledge_query" in out
    assert out["knowledge_query"] is expected
    assert out["query"] == "как делать калибровку датчика?"
    rag.search.assert_awaited_once()
    args, kwargs = rag.search.call_args
    assert args[0] == "как делать калибровку датчика?"


async def test_router_forwards_target_source_kind_to_adapter() -> None:
    rag = MagicMock()
    rag.is_available = True
    rag.search = AsyncMock(
        return_value=KnowledgeQueryResult(query="q", hits=[], total_hits=0)
    )

    adapters = _make_adapters(rag=rag)
    router = QueryRouter(adapters)

    intent = QueryIntent(
        category=QueryCategory.KNOWLEDGE_QUERY,
        target_source_kind="vault",
    )
    await router.fetch(intent, "процедура")

    _, kwargs = rag.search.call_args
    assert kwargs["source_kind"] == "vault"


async def test_router_returns_none_when_rag_adapter_missing() -> None:
    adapters = _make_adapters(rag=None)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.KNOWLEDGE_QUERY)

    out = await router.fetch(intent, "anything")

    assert out["knowledge_query"] is None
    assert out["query"] == "anything"


async def test_router_returns_none_when_rag_adapter_not_available() -> None:
    """Adapter wired in but underlying searcher missing (is_available=False)."""
    rag = MagicMock()
    rag.is_available = False
    rag.search = AsyncMock(return_value=None)

    adapters = _make_adapters(rag=rag)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.KNOWLEDGE_QUERY)

    out = await router.fetch(intent, "anything")

    assert out["knowledge_query"] is None
    rag.search.assert_not_awaited()


async def test_router_swallows_rag_adapter_exception() -> None:
    rag = MagicMock()
    rag.is_available = True
    rag.search = AsyncMock(side_effect=RuntimeError("boom"))

    adapters = _make_adapters(rag=rag)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.KNOWLEDGE_QUERY)

    out = await router.fetch(intent, "anything")

    # Router-level try/except converts to {} on adapter raise.
    assert out == {}


# ---------------------------------------------------------------------------
# Format prompt — exercised through AssistantQueryAgent._build_format_user_prompt
# ---------------------------------------------------------------------------


def test_format_prompt_lists_hits_and_filter_note() -> None:
    """Construct the format-prompt user message directly via the agent's
    private dispatch — verifies citation-friendly numbering and source-kind
    localisation."""
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    hits = [
        KnowledgeQueryHit(
            source="procedure-cooldown.md",
            source_kind="vault",
            snippet="Запуск cooldown через Ctrl+E.",
            distance=0.4,
        ),
        KnowledgeQueryHit(
            source="exp-2025-12-01",
            source_kind="experiment_metadata",
            snippet="Длительность 8 часов.",
            distance=0.7,
        ),
    ]
    result = KnowledgeQueryResult(
        query="как делать cooldown?",
        hits=hits,
        total_hits=2,
        source_kind_filter="vault",
    )
    data = {"knowledge_query": result, "query": "как делать cooldown?"}

    prompt = AssistantQueryAgent._fmt_knowledge_query(
        MagicMock(),  # type: ignore[arg-type]  # method is self-agnostic
        "как делать cooldown?",
        data,
    )

    assert "[Источник 1]" in prompt
    assert "[Источник 2]" in prompt
    assert "vault" in prompt
    assert "архив" in prompt  # localised label for experiment_metadata
    assert "source_kind=vault" in prompt
    assert "procedure-cooldown.md" in prompt


def test_format_prompt_handles_empty_hits() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    result = KnowledgeQueryResult(query="что-то", hits=[], total_hits=0)
    data = {"knowledge_query": result, "query": "что-то"}

    prompt = AssistantQueryAgent._fmt_knowledge_query(
        MagicMock(),  # type: ignore[arg-type]  # method is self-agnostic
        "что-то",
        data,
    )

    assert "(совпадений не найдено)" in prompt


def test_format_prompt_handles_missing_adapter() -> None:
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent

    data = {"knowledge_query": None, "query": "anything"}

    prompt = AssistantQueryAgent._fmt_knowledge_query(
        MagicMock(),  # type: ignore[arg-type]  # method is self-agnostic
        "anything",
        data,
    )

    assert "RAG-индекс не сконфигурирован" in prompt
