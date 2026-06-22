"""F32 H9 — searcher must guard against query embedding dim mismatch.

Indexer (cycle 2) has warn+zero-vec fallback for dim mismatch; searcher
previously passed mismatched vectors to LanceDB and crashed with a
schema error. This test verifies the searcher now mirrors indexer
behaviour: warn + return [].

Production _EMBEDDING_DIM is 1024 (qwen3-embedding:0.6b). The mismatch
scenario is a 768-dim query (e.g. nomic-embed-text) against a 1024-dim
table — tests use a real LanceDB index to verify no crash + correct guard.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cryodaq.agents.rag.indexer import _EMBEDDING_DIM, build_index
from cryodaq.agents.rag.searcher import RagSearcher


class _Mock1024:
    """Correct _EMBEDDING_DIM-sized embeddings for building the index."""

    async def embed(self, text: str) -> list[float]:
        seed = (hash(text) % 100) / 100.0
        return [seed] * _EMBEDDING_DIM


class _Mock768:
    """Mismatched 768-dim query embeddings (e.g. nomic-embed-text)."""

    async def embed(self, text: str) -> list[float]:
        return [0.5] * 768


def _seed_experiment(root: Path, exp_id: str = "dim_test") -> None:
    exp_dir = root / "experiments" / exp_id
    (exp_dir / "archive" / "summaries").mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(
        json.dumps({"description": "dim mismatch test", "notes": ""}),
        encoding="utf-8",
    )
    (exp_dir / "archive" / "summaries" / "summary_metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "title": "Dim test",
                "sample": "S-001",
                "operator": "test",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_searcher_dim_mismatch_returns_empty(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 768-dim query against a real 1024-dim LanceDB table returns []
    with a warning and must not crash or call table.search()."""
    db_path = tmp_path / "rag.lancedb"

    # Build a real 1024-dim index.
    _seed_experiment(tmp_path)
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_Mock1024(),
    )

    # Searcher queries with 768-dim embeddings — mismatch against the 1024-dim table.
    searcher = RagSearcher(
        db_path=db_path,
        embeddings_client=_Mock768(),
    )

    with caplog.at_level(logging.WARNING, logger="cryodaq.agents.rag.searcher"):
        results = await searcher.search("test query")

    assert results == [], f"expected [] on dim mismatch; got {results}"
    assert any(
        "embedding dim" in rec.message and "768" in rec.message
        for rec in caplog.records
    ), f"expected dim mismatch warning; got: {[r.message for r in caplog.records]}"
