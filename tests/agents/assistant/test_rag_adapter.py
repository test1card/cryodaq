"""F32 Stage 2 (v0.55.7) — RAGAdapter tests.

Stubs out :class:`cryodaq.agents.rag.searcher.RagSearcher` so the adapter
is exercised in isolation. Asserts on:

- ``search`` returns ``KnowledgeQueryResult`` preserving the searcher's hit order.
- Hits past the distance cutoff are dropped.
- ``source_kind`` is forwarded as a single-element ``source_kind_filter`` list.
- Adapter never raises when the underlying searcher does.
- ``is_available`` reflects whether a searcher was wired in.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.adapters.rag_adapter import (
    RAGAdapter,
    _truncate_snippet,
)
from cryodaq.agents.assistant.query.schemas import (
    KnowledgeQueryHit,
    KnowledgeQueryResult,
)


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _StubSearchResult:
    """Mimics cryodaq.agents.rag.searcher.SearchResult."""

    chunk_id: str
    source_kind: str
    source_id: str
    text: str
    score: float
    metadata: dict | None = None


def _make_searcher(results):
    s = MagicMock()
    s.search = AsyncMock(return_value=results)
    return s


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true_when_searcher_present() -> None:
    adapter = RAGAdapter(MagicMock())
    assert adapter.is_available is True


def test_is_available_false_when_searcher_none() -> None:
    adapter = RAGAdapter(None)
    assert adapter.is_available is False


# ---------------------------------------------------------------------------
# search — happy path
# ---------------------------------------------------------------------------


def test_search_returns_knowledge_query_result_with_hits() -> None:
    # Feed rows in reverse distance order (worse match first) to verify the
    # adapter does NOT re-sort — order is preserved from the searcher.
    rows = [
        _StubSearchResult(
            chunk_id="c2",
            source_kind="experiment_metadata",
            source_id="exp-2025-12-01",
            text="Cooldown стартовал в 09:00, длительность 8 часов.",
            score=0.7,
        ),
        _StubSearchResult(
            chunk_id="c1",
            source_kind="vault",
            source_id="procedure-cooldown.md",
            text="Чтобы запустить cooldown, нажмите Ctrl+E…",
            score=0.4,
        ),
    ]
    adapter = RAGAdapter(_make_searcher(rows))

    result = _run(adapter.search("как делать cooldown?"))

    assert isinstance(result, KnowledgeQueryResult)
    assert result.query == "как делать cooldown?"
    assert result.total_hits == 2
    assert result.source_kind_filter is None
    assert all(isinstance(h, KnowledgeQueryHit) for h in result.hits)
    # Adapter preserves searcher order: 0.7 first, 0.4 second (no re-sort).
    assert result.hits[0].source == "exp-2025-12-01"
    assert result.hits[0].distance == pytest.approx(0.7)
    assert result.hits[1].source == "procedure-cooldown.md"
    assert result.hits[1].source_kind == "vault"
    assert result.hits[1].distance == pytest.approx(0.4)


def test_search_returns_none_when_searcher_unavailable() -> None:
    adapter = RAGAdapter(None)
    assert _run(adapter.search("anything")) is None


# ---------------------------------------------------------------------------
# distance cutoff
# ---------------------------------------------------------------------------


def test_search_drops_hits_above_max_distance() -> None:
    rows = [
        _StubSearchResult("c1", "vault", "doc1", "near match", score=0.4),
        _StubSearchResult("c2", "vault", "doc2", "far away", score=2.5),
    ]
    adapter = RAGAdapter(_make_searcher(rows), max_distance=1.5)

    result = _run(adapter.search("query"))

    assert result is not None
    assert result.total_hits == 1
    assert result.hits[0].source == "doc1"


def test_search_per_call_max_distance_overrides_default() -> None:
    rows = [
        _StubSearchResult("c1", "vault", "doc1", "marginal", score=1.6),
    ]
    adapter = RAGAdapter(_make_searcher(rows), max_distance=1.5)

    # Default would drop this; per-call override keeps it.
    result = _run(adapter.search("query", max_distance=2.0))

    assert result is not None
    assert result.total_hits == 1


# ---------------------------------------------------------------------------
# source_kind filter
# ---------------------------------------------------------------------------


def test_search_passes_source_kind_as_single_element_filter_list() -> None:
    searcher = _make_searcher([])
    adapter = RAGAdapter(searcher)

    _run(adapter.search("какая процедура?", source_kind="vault"))

    searcher.search.assert_awaited_once()
    _, kwargs = searcher.search.call_args
    assert kwargs["source_kind_filter"] == ["vault"]


def test_search_omits_filter_when_source_kind_none() -> None:
    searcher = _make_searcher([])
    adapter = RAGAdapter(searcher)

    _run(adapter.search("anything"))

    _, kwargs = searcher.search.call_args
    assert kwargs["source_kind_filter"] is None


def test_search_records_source_kind_filter_in_result() -> None:
    rows = [
        _StubSearchResult("c1", "vault", "doc1", "snippet", score=0.5),
    ]
    adapter = RAGAdapter(_make_searcher(rows))

    result = _run(adapter.search("query", source_kind="vault"))

    assert result is not None
    assert result.source_kind_filter == "vault"


# ---------------------------------------------------------------------------
# top_k
# ---------------------------------------------------------------------------


def test_search_uses_default_top_k_when_unspecified() -> None:
    searcher = _make_searcher([])
    adapter = RAGAdapter(searcher, default_top_k=7)

    _run(adapter.search("query"))

    _, kwargs = searcher.search.call_args
    assert kwargs["top_k"] == 7


def test_search_per_call_top_k_overrides_default() -> None:
    searcher = _make_searcher([])
    adapter = RAGAdapter(searcher, default_top_k=5)

    _run(adapter.search("query", top_k=3))

    _, kwargs = searcher.search.call_args
    assert kwargs["top_k"] == 3


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


def test_search_handles_searcher_exception_gracefully() -> None:
    searcher = MagicMock()
    searcher.search = AsyncMock(side_effect=RuntimeError("LanceDB locked"))
    adapter = RAGAdapter(searcher)

    result = _run(adapter.search("anything"))

    assert result is not None
    assert result.available is False
    assert result.stale is True
    assert result.reason


def test_search_propagates_cancelled_error() -> None:
    """asyncio.CancelledError must not be silenced — it has to propagate so
    the surrounding task can shut down cleanly."""
    searcher = MagicMock()
    searcher.search = AsyncMock(side_effect=asyncio.CancelledError())
    adapter = RAGAdapter(searcher)

    with pytest.raises(asyncio.CancelledError):
        _run(adapter.search("anything"))


# ---------------------------------------------------------------------------
# snippet truncation
# ---------------------------------------------------------------------------


def test_truncate_snippet_keeps_short_text_intact() -> None:
    assert _truncate_snippet("привет") == "привет"


def test_truncate_snippet_collapses_whitespace_and_caps_length() -> None:
    long = "слово " * 200
    out = _truncate_snippet(long, max_chars=50)
    assert len(out) <= 50
    assert out.endswith("…")
    assert "  " not in out  # whitespace collapsed


def test_truncate_snippet_handles_empty_string() -> None:
    assert _truncate_snippet("") == ""


def test_search_truncates_long_chunk_text_in_snippet() -> None:
    # Input contains tabs, newlines, and consecutive spaces to verify that
    # _truncate_snippet collapses all whitespace before capping length.
    dirty = "Описание\tпроцедуры.\n\nДетали:  подробности  here. " * 30  # ~1500 chars with dirty whitespace
    rows = [_StubSearchResult("c1", "vault", "doc1", dirty, score=0.5)]
    adapter = RAGAdapter(_make_searcher(rows))

    result = _run(adapter.search("query"))

    assert result is not None
    snippet = result.hits[0].snippet
    assert len(snippet) <= 280  # exact cap from _truncate_snippet(max_chars=280)
    assert snippet.endswith("…")  # truncated with ellipsis
    assert snippet.startswith("Описание")  # prefix preserved after collapse
    assert "\n" not in snippet  # newlines collapsed
    assert "\t" not in snippet  # tabs collapsed
    assert "  " not in snippet  # consecutive spaces collapsed


def test_the_configured_embed_timeout_reaches_the_client() -> None:
    """Reported by review, 2026-09-07: it did not, on the path that answers questions.

    A single embed call against this stand's server was MEASURED at 20-34 s,
    straddling the client's 30 s default. `embed_timeout_s: 180.0` went into
    rag.yaml for that reason, and the INDEXING path passed it. The RETRIEVAL
    path built its client with base_url, model and keep_alive and left the
    timeout out, so a cold model could fail an operator's question while every
    log line reported the configuration rather than the object built from it.

    Both paths now go through one builder.
    """
    from cryodaq.agents.rag.embeddings import DEFAULT_EMBED_TIMEOUT_S, make_embeddings_client

    client = make_embeddings_client(
        {
            "ollama_base_url": "http://127.0.0.1:11437",
            "embedding_model": "qwen3-embedding:8b",
            "embed_timeout_s": 180.0,
        }
    )

    assert client.timeout_s == 180.0, "the retrieval client ignored its configured timeout"
    assert client.model == "qwen3-embedding:8b"
    assert client.base_url == "http://127.0.0.1:11437"

    assert DEFAULT_EMBED_TIMEOUT_S >= 180.0, (
        "the fallback must clear the measured 20-34 s embed, not the old 30 s default"
    )


def test_a_malformed_timeout_falls_back_instead_of_raising() -> None:
    """A one-character config error must not stop the assistant from starting."""
    from cryodaq.agents.rag.embeddings import DEFAULT_EMBED_TIMEOUT_S, make_embeddings_client

    for bad in ("", "сто восемьдесят", [], None, 0, -5, float("inf"), float("nan")):
        client = make_embeddings_client({"embed_timeout_s": bad})
        assert client.timeout_s == DEFAULT_EMBED_TIMEOUT_S, f"{bad!r} did not fall back"


def test_there_is_exactly_one_place_that_constructs_the_embeddings_client() -> None:
    """The defect was a SECOND construction site, so the invariant is "one".

    This is a source check, and deliberately so. The builder test above pins
    what the client gets from configuration, but it cannot see a caller that
    bypasses the builder — and bypassing it is precisely what happened: the
    indexing path passed the measured timeout, the retrieval path constructed
    its own client and did not, and no behavioural test could reach the second
    one without booting the assistant.

    A second construction site is the drift itself, not a proxy for it. If a
    caller ever genuinely needs its own client, this test should be changed
    deliberately rather than by accident.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "src" / "cryodaq"
    sites = [
        f"{path.relative_to(src)}:{number}"
        for path in sorted(src.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "EmbeddingsClient(" in line and "make_embeddings_client" not in line
    ]

    assert len(sites) == 1, f"expected one construction site, found {len(sites)}: {sites}"
    assert sites[0].startswith("agents/rag/embeddings.py:"), (
        f"the only construction site must be the shared builder, not {sites[0]}"
    )
