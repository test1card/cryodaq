"""F32 — indexer integration tests with deterministic mock embeddings."""

from __future__ import annotations

import hashlib
import json
import logging

import lancedb
import pytest

from cryodaq.agents.rag.indexer import _EMBEDDING_DIM, build_index


class _MockEmbeddings:
    """Returns a deterministic _EMBEDDING_DIM-sized vector keyed off the input text.

    Uses hashlib.md5 so the seed is stable across Python processes regardless of
    PYTHONHASHSEED.  The +1 in the numerator guarantees the seed is strictly
    positive (> 0), so the resulting vector is never all-zero.
    """

    def __init__(self, dim: int = _EMBEDDING_DIM) -> None:
        self.dim = dim
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        seed = (hashlib.md5(text.encode("utf-8")).digest()[0] + 1) / 256.0  # always > 0
        return [seed] * self.dim


class _ShortVectorEmbeddings:
    """Returns a shorter-than-expected vector to exercise the warn+zero fallback."""

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.5] * 10  # intentionally mismatched dim


@pytest.mark.asyncio
async def test_indexer_empty_corpus_returns_zero_stats(tmp_path):
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "rag_db",
        embeddings_client=_MockEmbeddings(),
    )
    assert stats["chunks"] == 0
    assert stats["embedded"] == 0
    assert stats["indexed"] == 0


def _seed_experiment(tmp_path, exp_id: str = "abc12345") -> None:
    exp_dir = tmp_path / "experiments" / exp_id
    (exp_dir / "archive" / "summaries").mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(
        json.dumps(
            {"description": "Тестовая проба охлаждения 4К", "notes": "no incidents"}
        )
    )
    (exp_dir / "archive" / "summaries" / "summary_metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "title": "Cooldown test",
                "sample": "S-001",
                "operator": "Vladimir",
                "status": "COMPLETED",
            }
        )
    )


@pytest.mark.asyncio
async def test_indexer_with_single_experiment_creates_table(tmp_path, caplog):
    _seed_experiment(tmp_path)
    db_path = tmp_path / "rag_db"
    with caplog.at_level(logging.WARNING, logger="cryodaq.agents.rag.indexer"):
        stats = await build_index(
            experiments_dir=tmp_path / "experiments",
            vault_dir=None,
            sqlite_path=None,
            db_path=db_path,
            embeddings_client=_MockEmbeddings(),
        )
    assert stats["chunks"] >= 1
    assert stats["embedded"] >= 1
    assert stats["indexed"] >= 1
    assert stats["table"] == "cryodaq_corpus"

    # No dim-mismatch fallback must fire when mock returns _EMBEDDING_DIM vectors.
    dim_mismatch_logs = [
        r for r in caplog.records if "dim mismatch" in r.message.lower()
    ]
    assert dim_mismatch_logs == [], (
        f"unexpected dim-mismatch warnings: {[r.message for r in dim_mismatch_logs]}"
    )

    # Open the LanceDB table and verify the persisted row.
    db = lancedb.connect(str(db_path))
    arrow_table = db.open_table("cryodaq_corpus").to_arrow()
    assert arrow_table.num_rows >= 1, "expected at least one indexed row"
    source_kinds = arrow_table.column("source_kind").to_pylist()
    source_ids = arrow_table.column("source_id").to_pylist()
    texts = arrow_table.column("text").to_pylist()
    vectors = arrow_table.column("vector").to_pylist()
    # source_kind and source_id must be populated (not empty strings).
    assert all(k != "" for k in source_kinds), "source_kind must be non-empty"
    assert all(s != "" for s in source_ids), "source_id must be non-empty"
    # text must be non-empty.
    assert all(len(t) > 0 for t in texts), "text must be non-empty"
    # vectors must be non-zero (correct dim mock, no fallback applied).
    for vec in vectors:
        assert len(vec) == _EMBEDDING_DIM, f"vector dim {len(vec)} != {_EMBEDDING_DIM}"
        assert any(v != 0.0 for v in vec), "vector must be non-zero for correct-dim mock"


@pytest.mark.asyncio
async def test_indexer_dim_mismatch_falls_back_to_zero_vector(tmp_path, caplog):
    _seed_experiment(tmp_path)
    db_path = tmp_path / "rag_db"
    with caplog.at_level(logging.WARNING, logger="cryodaq.agents.rag.indexer"):
        stats = await build_index(
            experiments_dir=tmp_path / "experiments",
            vault_dir=None,
            sqlite_path=None,
            db_path=db_path,
            embeddings_client=_ShortVectorEmbeddings(),
        )
    assert stats["chunks"] == stats["indexed"]
    assert stats["chunks"] >= 1

    # The dim-mismatch warning must have fired.
    mismatch_warnings = [r for r in caplog.records if "dim mismatch" in r.message.lower()]
    assert mismatch_warnings, (
        f"expected dim-mismatch warning; got: {[r.message for r in caplog.records]}"
    )

    # The persisted vector must be all-zeros of length _EMBEDDING_DIM.
    db = lancedb.connect(str(db_path))
    arrow_table = db.open_table("cryodaq_corpus").to_arrow()
    assert arrow_table.num_rows >= 1
    vectors = arrow_table.column("vector").to_pylist()
    for vec in vectors:
        assert len(vec) == _EMBEDDING_DIM, (
            f"zero-fallback vector dim {len(vec)} != {_EMBEDDING_DIM}"
        )
        assert all(v == 0.0 for v in vec), (
            "zero-fallback vector must be all-zeros; got non-zero values"
        )
