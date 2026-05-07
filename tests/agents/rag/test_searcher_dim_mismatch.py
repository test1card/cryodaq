"""F32 H9 — searcher must guard against query embedding dim mismatch.

Indexer (cycle 2) has warn+zero-vec fallback for dim mismatch; searcher
previously passed mismatched vectors to LanceDB and crashed with a
schema error. This test verifies the searcher now mirrors indexer
behaviour: warn + return [].
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryodaq.agents.rag.searcher import RagSearcher


class _Mock768:
    """Mismatched 768-dim (e.g. nomic-embed-text)."""

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 768


@pytest.mark.asyncio
async def test_searcher_dim_mismatch_returns_empty(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 768-dim query against a 384-dim table returns [] with a warning."""
    fake_db = MagicMock()
    fake_db.list_tables.return_value.tables = ["cryodaq_corpus"]
    fake_db.uri = str(tmp_path)
    fake_table = MagicMock()
    fake_db.open_table.return_value = fake_table

    def _fake_connect(_uri):
        return fake_db

    monkeypatch.setattr("cryodaq.agents.rag.searcher.lancedb.connect", _fake_connect)

    searcher = RagSearcher(
        db_path=tmp_path / "rag.lancedb",
        embeddings_client=_Mock768(),
    )

    with caplog.at_level(logging.WARNING, logger="cryodaq.agents.rag.searcher"):
        results = await searcher.search("test query")

    assert results == []
    assert any(
        "embedding dim" in rec.message and "768" in rec.message
        for rec in caplog.records
    ), f"expected dim mismatch warning; got: {[r.message for r in caplog.records]}"
    fake_table.search.assert_not_called()
