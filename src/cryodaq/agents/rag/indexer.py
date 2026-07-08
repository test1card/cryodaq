"""F32 — Indexer: corpus -> embeddings -> LanceDB."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import lancedb
import pyarrow as pa

from cryodaq.agents.rag.document_loader import (
    DocumentChunk,
    load_experiment_metadata,
    load_operator_log_entries,
    load_procedure_documents,
    load_reference_documents,
    load_vault_notes,
)
from cryodaq.agents.rag.loaders.pdf_loader import load_pdf_documents

logger = logging.getLogger(__name__)


# May 2026: switched to qwen3-embedding:0.6b — top of MTEB multilingual
# leaderboard (June 2025 score 70.58), 100+ languages, 32k context, official
# Ollama library entry. Previous: multilingual-e5-small (384d) — qllama/jeffh
# uploads incompatible with Ollama 0.23+ runtime (subprocess EOF crash).
_EMBEDDING_DIM = 1024


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


def _swap_table_atomically(
    db: Any,
    *,
    table_name: str,
    rows: list[dict[str, Any]],
    schema: pa.Schema,
) -> Any:
    """v0.55.14 (audit SCOPE 2 finding 2.3) — crash-safe rebuild.

    Writes the freshly embedded corpus into a staging table first, then
    swaps the canonical name via ``db.rename_table`` (atomic at the
    LanceDB manifest level). The previous index stays readable
    throughout the embedding loop and is only replaced once the staging
    table is fully written and row-count-verified.

    A LanceDB build that lacks ``rename_table`` falls back to the older
    drop+create sequence with a logged warning so operators know the
    rebuild has a small crash window. Returns the canonical table.
    """
    existing = set(db.list_tables().tables)
    staging_name = f"{table_name}__staging"
    if staging_name in existing:
        db.drop_table(staging_name)
    staging_table = db.create_table(staging_name, data=rows, schema=schema)

    # Validate staging row count before exposing the new index.
    staged_count = staging_table.count_rows()
    if staged_count != len(rows):
        raise RuntimeError(
            f"RAG staging row count mismatch: wrote {len(rows)} rows but "
            f"LanceDB reports {staged_count} — refusing to swap canonical."
        )

    existing_after_stage = set(db.list_tables().tables)

    rename_supported = True
    try:
        if table_name in existing_after_stage:
            # The drop-then-rename window is tiny (manifest-only ops),
            # but it is non-zero. Acceptable trade-off: avoiding it
            # would require a 3-name backup dance with no upside given
            # how short the window is on a local LanceDB.
            db.drop_table(table_name)
        db.rename_table(staging_name, table_name)
    except (AttributeError, NotImplementedError) as exc:
        # LanceDB OSS (as of 0.30) raises NotImplementedError on
        # rename_table even though the method exists. Fall back to a
        # drop+create cycle so the rebuild still works; log so the
        # operator knows the rebuild has a small crash window.
        rename_supported = False
        logger.warning(
            "RAG: LanceDB %s rename_table unavailable (%s); falling "
            "back to drop+create — rebuild has a small crash window",
            getattr(lancedb, "__version__", "unknown"),
            exc.__class__.__name__,
        )
    if not rename_supported:
        existing_now = set(db.list_tables().tables)
        if table_name in existing_now:
            db.drop_table(table_name)
        db.create_table(table_name, data=rows, schema=schema)
        if staging_name in db.list_tables().tables:
            db.drop_table(staging_name)

    return db.open_table(table_name)


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
    pdf_dir: Path | None = None,
    procedures_dir: Path | None = None,
    reference_root: Path | None = None,
) -> dict:
    """Build (or rebuild) the RAG index. Returns a stats dict.

    Embedding dimension mismatches are logged and zero-vector-substituted
    so a single bad chunk does not abort the whole build.

    v0.55.14 (audit SCOPE 6 finding 6.6) — synchronous filesystem
    walks and LanceDB writes are offloaded via :func:`asyncio.to_thread`
    so the engine event loop does not stall while ``RAGIndexSink`` runs
    a finalize-time rebuild on a corpus of any size.

    v0.55.7.1 (F-KnowledgeBaseExpansion) — three new optional sources:

    pdf_dir
        Knowledge corpus folder с equipment manual PDFs (e.g.
        ``data/knowledge/equipment_manuals``). Page-aware chunks via
        :func:`cryodaq.agents.rag.loaders.pdf_loader.load_pdf_documents`.
    procedures_dir
        Markdown procedures folder (e.g. ``data/knowledge/procedures``).
        H1 → title; subdir → category.
    reference_root
        Repo root для project reference docs (operator_manual, README,
        CHANGELOG). CHANGELOG is section-aware per version.

    All three are optional; existing callers (CLI, RAGIndexSink before
    v0.55.7.1) keep working without modification. Like the legacy
    loaders, the new loaders run inside :func:`asyncio.to_thread` so
    they do not stall the engine loop.
    """
    chunks: list[DocumentChunk] = []
    chunks.extend(
        await asyncio.to_thread(load_experiment_metadata, experiments_dir)
    )
    if vault_dir is not None:
        chunks.extend(await asyncio.to_thread(load_vault_notes, vault_dir))
    if sqlite_path is not None:
        chunks.extend(
            await asyncio.to_thread(load_operator_log_entries, sqlite_path)
        )
    if pdf_dir is not None:
        chunks.extend(await asyncio.to_thread(load_pdf_documents, pdf_dir))
    if procedures_dir is not None:
        chunks.extend(
            await asyncio.to_thread(load_procedure_documents, procedures_dir)
        )
    if reference_root is not None:
        chunks.extend(
            await asyncio.to_thread(load_reference_documents, reference_root)
        )

    logger.info("RAG: %d chunks loaded", len(chunks))
    if not chunks:
        return {
            "chunks": 0,
            "embedded": 0,
            "failed": 0,
            "indexed": 0,
            "db_path": str(db_path),
            "table": table_name,
        }

    embedded_count = 0
    failed_count = 0
    vectors: list[list[float]] = []
    for idx, chunk in enumerate(chunks):
        vec = await embeddings_client.embed(chunk.text)
        if not vec:
            # Empty vector = the embedding FAILED (e.g. an Ollama timeout makes
            # embed() return []). The zero vector keeps row alignment, but the
            # chunk is effectively unsearchable, so it must NOT count as a
            # successful embed — track it so a degraded corpus is visible, not
            # silently masked as fully embedded.
            logger.warning(
                "RAG embedding FAILED on chunk %s (empty vector — likely a "
                "timeout); substituting zero vector (chunk will not be searchable)",
                chunk.chunk_id,
            )
            vec = [0.0] * embedding_dim
            failed_count += 1
        elif len(vec) != embedding_dim:
            logger.warning(
                "RAG embedding dim mismatch on chunk %s: got %d, expected %d — using zero vector",
                chunk.chunk_id,
                len(vec),
                embedding_dim,
            )
            vec = [0.0] * embedding_dim
            failed_count += 1
        else:
            embedded_count += 1
        vectors.append(vec)
        if progress_cb is not None and idx % 50 == 0:
            progress_cb(idx, len(chunks))

    if failed_count:
        logger.warning(
            "RAG index built with %d/%d chunks that FAILED to embed — corpus is "
            "degraded (those chunks are not searchable). Re-run the rebuild once "
            "the embedding backend is healthy.",
            failed_count,
            len(chunks),
        )

    await asyncio.to_thread(db_path.mkdir, parents=True, exist_ok=True)
    db = await asyncio.to_thread(lancedb.connect, str(db_path))
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

    table = await asyncio.to_thread(
        _swap_table_atomically,
        db,
        table_name=table_name,
        rows=rows,
        schema=schema,
    )
    indexed_count = await asyncio.to_thread(table.count_rows)

    return {
        "chunks": len(chunks),
        "embedded": embedded_count,
        "failed": failed_count,
        "indexed": indexed_count,
        "db_path": str(db_path),
        "table": table_name,
    }
