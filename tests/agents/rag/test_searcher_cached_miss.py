"""v0.56.0 — RagSearcher reopen-on-cached-miss regression tests.

When the CLI / engine rebuild_index drops and recreates the LanceDB
table, the cached connection's `list_tables()` view can lag the on-disk
manifest. The searcher reconnects once before reporting the table as
missing so a freshly built index becomes visible without an engine
restart.

These tests exercise:
1. cached miss → reconnect → table found  (the live operator path)
2. genuinely empty db → reconnect → still missing → return [] (idempotence)
3. populated db (no rebuild) → normal path unchanged                (regression)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cryodaq.agents.rag.indexer import build_index
from cryodaq.agents.rag.searcher import RagSearcher


class _MockEmbeddings:
    async def embed(self, text: str) -> list[float]:
        digest = hashlib.md5(text[:32].encode("utf-8")).digest()
        seed = digest[0] / 255.0
        return [seed] * 1024


def _seed(tmp_path: Path) -> None:
    exp_dir = tmp_path / "experiments" / "abc12345"
    (exp_dir / "archive" / "summaries").mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(
        json.dumps({"description": "Cooldown test"})
    )
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
async def test_searcher_reconnects_after_external_rebuild(tmp_path):
    """Searcher constructed before index exists; build_index runs;
    searcher.search() must observe the table even though the cached
    connection saw an empty db_path at construction time."""
    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"
    db_path.mkdir(parents=True, exist_ok=True)

    # Searcher created on an empty (but existing) db_path — its cached
    # _db.list_tables() returns no tables.
    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)

    # External rebuild populates the table on disk; searcher's cached
    # connection still believes the table is missing.
    _seed(tmp_path)
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=embeddings,
    )

    # The reopen path must materialise the table so the operator gets
    # results without restarting the engine.
    results = await searcher.search("any query", top_k=3)
    assert len(results) >= 1, "reopen path failed to surface rebuilt index"


@pytest.mark.asyncio
async def test_searcher_truly_empty_db_still_returns_empty(tmp_path):
    """Reconnect path is idempotent: when the table is genuinely
    missing on disk, the second list_tables() also reports it absent
    and the searcher returns [] (no infinite loop, no crash)."""
    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"
    db_path.mkdir(parents=True, exist_ok=True)

    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)
    results = await searcher.search("anything", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_searcher_normal_path_after_construct_with_populated_db(tmp_path):
    """Regression: when the table already exists at construct time,
    the cached connection sees it; reconnect path is not exercised
    and the normal LanceDB query path returns results as before."""
    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"
    _seed(tmp_path)
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=embeddings,
    )

    # Construct AFTER the table exists — the cached connection's
    # initial list_tables() already shows it.
    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)
    results = await searcher.search("any query", top_k=3)
    assert len(results) >= 1
    assert results[0].source_id == "abc12345"
