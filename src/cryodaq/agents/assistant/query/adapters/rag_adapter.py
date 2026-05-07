"""RAGAdapter — semantic search over the F32 RAG corpus for the query agent.

Wraps :class:`cryodaq.agents.rag.searcher.RagSearcher` (LanceDB top-K cosine
lookup over experiment metadata, vault notes, and operator log entries) with a
QueryAgent-friendly interface that:

- Returns a typed :class:`KnowledgeQueryResult` (not raw ``SearchResult`` rows).
- Filters out hits whose LanceDB ``_distance`` exceeds a configured cutoff so
  the format LLM does not have to reason about irrelevant matches. Distance is
  used (not similarity) because the underlying searcher exposes only LanceDB's
  raw distance — lower is closer; for normalised multilingual-e5-small
  embeddings a distance ≳1.5 typically means an unrelated chunk.
- Never raises; missing searcher / index / embedding errors all collapse to
  ``None`` so the format prompt can frame "no relevant information" politely.

The F32 Stage 1 modules (indexer/searcher/document_loader/embeddings) are
explicitly out of scope for v0.55.7; this adapter only consumes them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from cryodaq.agents.assistant.query.schemas import (
    KnowledgeQueryHit,
    KnowledgeQueryResult,
)

if TYPE_CHECKING:
    from cryodaq.agents.rag.searcher import RagSearcher

logger = logging.getLogger(__name__)


# Distance cutoff calibrated for ``multilingual-e5-small`` (384-dim, normalised).
# LanceDB defaults to L2 distance; with unit-norm vectors L2² ≈ 2 - 2·cos(θ),
# so a cutoff of ~1.5 keeps roughly cosθ > 0.25 — empirically the boundary
# between "topical" and "noise" for the small CryoDAQ corpus.
_DEFAULT_MAX_DISTANCE = 1.5


def _truncate_snippet(text: str, *, max_chars: int = 280) -> str:
    """Trim chunk text for inclusion in the format-LLM prompt.

    Keeps the prompt budget bounded; full chunk text is still in LanceDB if
    operators want to drill down via the GUI knowledge-base overlay.
    """
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


class RAGAdapter:
    """Read-only semantic-search adapter over the F32 RAG corpus."""

    def __init__(
        self,
        searcher: RagSearcher | None,
        *,
        default_top_k: int = 5,
        max_distance: float = _DEFAULT_MAX_DISTANCE,
    ) -> None:
        self._searcher = searcher
        self._default_top_k = default_top_k
        self._max_distance = max_distance

    @property
    def is_available(self) -> bool:
        """True when an underlying searcher was wired in (engine startup)."""
        return self._searcher is not None

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source_kind: str | None = None,
        max_distance: float | None = None,
    ) -> KnowledgeQueryResult | None:
        """Run a semantic search; returns ``None`` if no searcher is wired.

        ``source_kind`` accepts one of the corpus kinds emitted by
        :mod:`cryodaq.agents.rag.document_loader` (currently
        ``experiment_metadata`` / ``vault`` / ``operator_log``); unknown values
        are passed through unchanged so the LanceDB ``WHERE`` clause simply
        returns no rows rather than a Python error.
        """
        if self._searcher is None:
            return None
        try:
            kinds = [source_kind] if source_kind else None
            results = await self._searcher.search(
                query,
                top_k=top_k or self._default_top_k,
                source_kind_filter=kinds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — adapter must never raise.
            logger.warning("RAGAdapter.search failed for %r: %s", query[:80], exc)
            return None

        cutoff = self._max_distance if max_distance is None else max_distance
        hits: list[KnowledgeQueryHit] = []
        for r in results:
            if r.score > cutoff:
                continue
            hits.append(
                KnowledgeQueryHit(
                    source=r.source_id,
                    source_kind=r.source_kind,
                    snippet=_truncate_snippet(r.text),
                    distance=float(r.score),
                    # v0.55.7.1: forward chunk metadata so the format
                    # prompt can render pretty source labels (page,
                    # title, version etc.) instead of opaque source_id.
                    metadata=dict(r.metadata) if r.metadata else {},
                )
            )

        return KnowledgeQueryResult(
            query=query,
            hits=hits,
            total_hits=len(hits),
            source_kind_filter=source_kind,
        )
