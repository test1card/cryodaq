"""F32 — Searcher: query embedding -> top-K LanceDB lookup."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import lancedb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """One row returned from RagSearcher.search()."""

    chunk_id: str
    source_kind: str
    source_id: str
    text: str
    metadata: dict
    score: float  # LanceDB `_distance` — lower is closer.


class _EmbeddingsLike(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class RagSearcher:
    """Embeds a query and returns the top-K matching chunks from LanceDB."""

    def __init__(
        self,
        *,
        db_path: Path,
        embeddings_client: _EmbeddingsLike,
        table_name: str = "cryodaq_corpus",
    ) -> None:
        self._db_path = Path(db_path)
        self._db = lancedb.connect(str(db_path))
        self._table_name = table_name
        self._embeddings = embeddings_client

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        source_kind_filter: list[str] | None = None,
    ) -> list[SearchResult]:
        # v0.56.0 — when the CLI / engine rebuild_index drops and
        # recreates the table, the cached LanceDB connection's
        # list_tables() view can lag the on-disk manifest. Reconnect
        # once before reporting the index as missing so a freshly built
        # index becomes visible without an engine restart.
        if self._table_name not in self._db.list_tables().tables:
            self._db = lancedb.connect(str(self._db_path))
            if self._table_name not in self._db.list_tables().tables:
                logger.warning(
                    "RAG table '%s' not found in %s",
                    self._table_name,
                    getattr(self._db, "uri", "?"),
                )
                return []

        table = self._db.open_table(self._table_name)
        query_vec = await self._embeddings.embed(query)

        # H9: guard query embedding dim. Indexer has warn+zero-vec
        # fallback for dim mismatch; searcher mirrors that pattern.
        # May 2026: switched to qwen3-embedding:0.6b (1024-dim) from
        # multilingual-e5-small (384-dim).
        expected_dim = 1024  # qwen3-embedding:0.6b canonical dim
        if len(query_vec) != expected_dim:
            logger.warning(
                "RAG search: query embedding dim %d != expected %d; "
                "Ollama embedding model likely misconfigured",
                len(query_vec),
                expected_dim,
            )
            return []

        # Push source_kind_filter into LanceDB's WHERE clause so the
        # vector search itself respects the filter — applying it after
        # `.limit(top_k)` would silently drop valid matches when other
        # kinds happened to be closer in vector space.
        query_builder = table.search(query_vec)
        if source_kind_filter:
            quoted = ", ".join(
                "'" + str(k).replace("'", "''") + "'" for k in source_kind_filter
            )
            query_builder = query_builder.where(f"source_kind IN ({quoted})")
        rows = query_builder.limit(top_k).to_list()

        results: list[SearchResult] = []
        for row in rows:
            kind = row["source_kind"]
            metadata_raw = row.get("metadata_json") or "{}"
            try:
                metadata = json.loads(metadata_raw)
            except (TypeError, ValueError):
                metadata = {}
            results.append(
                SearchResult(
                    chunk_id=row["chunk_id"],
                    source_kind=kind,
                    source_id=row["source_id"],
                    text=row["text"],
                    metadata=metadata,
                    score=float(row.get("_distance", 0.0)),
                )
            )
        return results
