"""v0.55.6 — engine ``rag.search`` command dispatch helper.

Mirrors the test pattern of ``test_engine_assistant_query_command.py`` —
we exercise the module-level helper :func:`_handle_rag_search_command`
directly because the closure in ``_run_engine`` simply delegates to it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryodaq.agents.assistant_main import _handle_rag_search_command


def _run(coro):
    return asyncio.run(coro)


def _result(**fields):
    return SimpleNamespace(
        chunk_id=fields.get("chunk_id", "c1"),
        source_kind=fields.get("source_kind", "vault"),
        source_id=fields.get("source_id", "doc1"),
        text=fields.get("text", "fragment"),
        metadata=fields.get("metadata", {"page": 1}),
        score=fields.get("score", 0.42),
    )


def test_rag_search_returns_results() -> None:
    searcher = AsyncMock()
    searcher.search.return_value = [_result(), _result(chunk_id="c2", source_id="doc2")]
    out = _run(
        _handle_rag_search_command(
            searcher,
            {"query": "охлаждение", "limit": 5},
        )
    )
    assert out["ok"] is True
    assert len(out["results"]) == 2
    first = out["results"][0]
    assert first["chunk_id"] == "c1"
    assert first["source_kind"] == "vault"
    assert first["score"] == 0.42
    searcher.search.assert_awaited_once_with(
        "охлаждение", top_k=5, source_kind_filter=None
    )


def test_rag_search_when_searcher_unavailable_returns_error() -> None:
    out = _run(_handle_rag_search_command(None, {"query": "test"}))
    assert out["ok"] is False
    assert "RAG индекс не построен" in out["error"]


def test_rag_search_empty_query_short_circuits() -> None:
    searcher = AsyncMock()
    out = _run(_handle_rag_search_command(searcher, {"query": "   "}))
    assert out == {"ok": False, "error": "Пустой запрос."}
    searcher.search.assert_not_called()


def test_rag_search_default_limit_is_ten() -> None:
    searcher = AsyncMock()
    searcher.search.return_value = []
    _run(_handle_rag_search_command(searcher, {"query": "manual"}))
    searcher.search.assert_awaited_once_with(
        "manual", top_k=10, source_kind_filter=None
    )


def test_rag_search_top_k_alias_accepted() -> None:
    searcher = AsyncMock()
    searcher.search.return_value = []
    _run(_handle_rag_search_command(searcher, {"query": "manual", "top_k": 3}))
    searcher.search.assert_awaited_once_with(
        "manual", top_k=3, source_kind_filter=None
    )


def test_rag_search_source_kind_filter_listified() -> None:
    searcher = AsyncMock()
    searcher.search.return_value = []
    _run(
        _handle_rag_search_command(
            searcher,
            {"query": "x", "source_kind_filter": "vault"},
        )
    )
    searcher.search.assert_awaited_once_with(
        "x", top_k=10, source_kind_filter=["vault"]
    )


def test_rag_search_source_kind_filter_list_passthrough() -> None:
    searcher = AsyncMock()
    searcher.search.return_value = []
    _run(
        _handle_rag_search_command(
            searcher,
            {"query": "x", "source_kind_filter": ["vault", "operator_log"]},
        )
    )
    searcher.search.assert_awaited_once_with(
        "x", top_k=10, source_kind_filter=["vault", "operator_log"]
    )


def test_rag_search_timeout_returns_russian_error() -> None:
    async def _slow(query, *, top_k, source_kind_filter):
        await asyncio.sleep(2.0)
        return []

    searcher = AsyncMock()
    searcher.search.side_effect = _slow
    out = _run(
        _handle_rag_search_command(
            searcher,
            {"query": "x"},
            timeout_s=0.05,
        )
    )
    assert out["ok"] is False
    assert "RAG-поиск" in out["error"]


def test_rag_search_exception_caught() -> None:
    searcher = AsyncMock()
    searcher.search.side_effect = RuntimeError("lance corruption")
    out = _run(_handle_rag_search_command(searcher, {"query": "x"}))
    assert out["ok"] is False
    assert "lance corruption" in out["error"]
