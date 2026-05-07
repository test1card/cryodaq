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
        if self._table_name not in self._db.list_tables().tables:
            logger.warning(
                "RAG table '%s' not found in %s",
                self._table_name,
                getattr(self._db, "uri", "?"),
            )
            return []

        table = self._db.open_table(self._table_name)
        query_vec = await self._embeddings.embed(query)

        # Over-fetch so source_kind_filter has room to discard.
        # `.to_list()` keeps us pandas-free; LanceDB returns dict-rows.
        rows = table.search(query_vec).limit(top_k * 3).to_list()

        results: list[SearchResult] = []
        for row in rows:
            kind = row["source_kind"]
            if source_kind_filter and kind not in source_kind_filter:
                continue
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
            if len(results) >= top_k:
                break
        return results
