"""F32 — Searcher: query embedding -> top-K LanceDB lookup."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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


def _index_vector_dim(table: Any) -> int | None:
    """Width the stored index was built at, read from its own schema.

    ``None`` when the schema cannot be read or the vector column is not a
    fixed-width list — in that case the caller does not guess, it simply
    does not enforce, and LanceDB reports any genuine mismatch itself.
    """
    try:
        field = table.schema.field("vector")
    except (KeyError, AttributeError, ValueError):
        return None
    return getattr(field.type, "list_size", None)


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

        # Guard the query embedding dim against THE INDEX, not against a
        # constant. This was a hardcoded 1024 until 2026-09-05, when the
        # corpus moved to a 4096-dim model: config and indexer agreed on
        # 4096, the index built correctly, and every search returned
        # nothing because the searcher still measured against 1024. A
        # constant here can only ever restate what someone believed on the
        # day they typed it, so read the width the index was actually
        # built at and compare with that.
        expected_dim = _index_vector_dim(table)
        if expected_dim is not None and len(query_vec) != expected_dim:
            logger.warning(
                "RAG search: query embedding dim %d != index dim %d — the "
                "embedding model and the stored index disagree, so the corpus "
                "must be rebuilt with the current model (or rag.embedding_model "
                "pointed back at the one that built it)",
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
            quoted = ", ".join("'" + str(k).replace("'", "''") + "'" for k in source_kind_filter)
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
