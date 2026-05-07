"""F32 — searcher tests on a freshly built mock index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryodaq.agents.rag.indexer import build_index
from cryodaq.agents.rag.searcher import RagSearcher


class _MockEmbeddings:
    async def embed(self, text: str) -> list[float]:
        seed = (hash(text[:5]) % 100) / 100.0
        return [seed] * 384


def _seed(tmp_path: Path) -> None:
    exp_dir = tmp_path / "experiments" / "abc12345"
    (exp_dir / "archive" / "summaries").mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(json.dumps({"description": "Cooldown test"}))
    (exp_dir / "archive" / "summaries" / "summary_metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "abc12345",
                "title": "T",
                "sample": "S",
                "operator": "V",
                "status": "COMPLETED",
            }
        )
    )


@pytest.mark.asyncio
async def test_searcher_returns_results_after_index(tmp_path):
    _seed(tmp_path)
    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=embeddings,
    )

    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)
    results = await searcher.search("any query", top_k=5)
    assert len(results) >= 1
    assert results[0].source_id == "abc12345"
    assert results[0].source_kind == "experiment_metadata"


@pytest.mark.asyncio
async def test_searcher_empty_db_returns_empty(tmp_path):
    embeddings = _MockEmbeddings()
    searcher = RagSearcher(db_path=tmp_path / "empty_db", embeddings_client=embeddings)
    results = await searcher.search("query", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_searcher_source_kind_filter(tmp_path):
    _seed(tmp_path)
    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=embeddings,
    )

    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)

    matched = await searcher.search(
        "query", top_k=5, source_kind_filter=["experiment_metadata"]
    )
    assert all(r.source_kind == "experiment_metadata" for r in matched)
    assert len(matched) >= 1

    none = await searcher.search("query", top_k=5, source_kind_filter=["nonexistent"])
    assert none == []
