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
async def test_searcher_reconnects_after_external_rebuild(tmp_path, monkeypatch):
    """Cached connection misses the table; reconnect surfaces it.

    Stubs lancedb.connect so the *first* connection returns a DB that
    claims the table is absent, while the *second* connection (the
    reconnect) returns a real DB that has the table.  This directly
    exercises the two-step guard in RagSearcher.search() and proves the
    reconnect branch ran, not merely that search returned something.
    """
    import lancedb as _lancedb

    embeddings = _MockEmbeddings()
    db_path = tmp_path / "rag_db"

    # Build the real index first so disk state is populated.
    _seed(tmp_path)
    await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=embeddings,
    )

    real_db = _lancedb.connect(str(db_path))

    connect_calls: list[str] = []

    class _FakeEmptyDB:
        """Mimics a stale cached connection that does not see the table."""

        uri = str(db_path)

        class _Tables:
            tables: list[str] = []

        def list_tables(self):  # noqa: ANN201
            return self._Tables()

    def _patched_connect(uri: str):  # noqa: ANN201
        connect_calls.append(uri)
        if len(connect_calls) == 1:
            # First connect (at RagSearcher.__init__) — stale, no tables.
            return _FakeEmptyDB()
        # Second connect (reconnect branch) — real DB with the table.
        return real_db

    monkeypatch.setattr("cryodaq.agents.rag.searcher.lancedb.connect", _patched_connect)

    searcher = RagSearcher(db_path=db_path, embeddings_client=embeddings)

    # At this point the cached _db has no tables.  search() must reconnect.
    results = await searcher.search("any query", top_k=3)

    # The reconnect branch fired (connect was called twice).
    assert len(connect_calls) == 2, (
        f"expected 2 connect() calls (init + reconnect), got {len(connect_calls)}"
    )
    assert len(results) >= 1, "reconnect path must surface the rebuilt index"


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
