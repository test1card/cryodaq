"""F32 — Indexer: corpus -> embeddings -> LanceDB."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

import lancedb
import pyarrow as pa

from cryodaq.agents.rag.document_loader import (
    DocumentChunk,
    load_experiment_metadata,
    load_operator_log_entries,
    load_vault_notes,
)

logger = logging.getLogger(__name__)


_EMBEDDING_DIM = 384  # multilingual-e5-small dimension


class _EmbeddingsLike(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def _make_schema(embedding_dim: int) -> pa.Schema:
    return pa.schema(
        [
            ("chunk_id", pa.string()),
            ("source_kind", pa.string()),
            ("source_id", pa.string()),
            ("text", pa.string()),
            ("vector", pa.list_(pa.float32(), embedding_dim)),
            ("metadata_json", pa.string()),
        ]
    )


async def build_index(
    *,
    experiments_dir: Path,
    vault_dir: Path | None,
    sqlite_path: Path | None,
    db_path: Path,
    embeddings_client: _EmbeddingsLike,
    embedding_dim: int = _EMBEDDING_DIM,
    table_name: str = "cryodaq_corpus",
    progress_cb: Callable[[int, int], Any] | None = None,
) -> dict:
    """Build (or rebuild) the RAG index. Returns a stats dict.

    Embedding dimension mismatches are logged and zero-vector-substituted
    so a single bad chunk does not abort the whole build.
    """
    chunks: list[DocumentChunk] = []
    chunks.extend(load_experiment_metadata(experiments_dir))
    if vault_dir is not None:
        chunks.extend(load_vault_notes(vault_dir))
    if sqlite_path is not None:
        chunks.extend(load_operator_log_entries(sqlite_path))

    logger.info("RAG: %d chunks loaded", len(chunks))
    if not chunks:
        return {"chunks": 0, "embedded": 0, "indexed": 0, "db_path": str(db_path), "table": table_name}

    embedded_count = 0
    vectors: list[list[float]] = []
    for idx, chunk in enumerate(chunks):
        vec = await embeddings_client.embed(chunk.text)
        if len(vec) != embedding_dim:
            logger.warning(
                "RAG embedding dim mismatch on chunk %s: got %d, expected %d — using zero vector",
                chunk.chunk_id,
                len(vec),
                embedding_dim,
            )
            vec = [0.0] * embedding_dim
        vectors.append(vec)
        embedded_count += 1
        if progress_cb is not None and idx % 50 == 0:
            progress_cb(idx, len(chunks))

    db_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_path))
    rows: list[dict[str, Any]] = [
        {
            "chunk_id": c.chunk_id,
            "source_kind": c.source_kind,
            "source_id": c.source_id,
            "text": c.text,
            "vector": vectors[i],
            "metadata_json": json.dumps(c.metadata, ensure_ascii=False),
        }
        for i, c in enumerate(chunks)
    ]
    schema = _make_schema(embedding_dim)

    if table_name in db.list_tables():
        db.drop_table(table_name)
    table = db.create_table(table_name, data=rows, schema=schema)

    return {
        "chunks": len(chunks),
        "embedded": embedded_count,
        "indexed": table.count_rows(),
        "db_path": str(db_path),
        "table": table_name,
    }
