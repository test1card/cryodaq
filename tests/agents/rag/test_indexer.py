"""F32 — indexer integration tests with deterministic mock embeddings."""

from __future__ import annotations

import json

import pytest

from cryodaq.agents.rag.indexer import build_index


class _MockEmbeddings:
    """Returns a deterministic 384-dim vector keyed off the input text."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        seed = (hash(text) % 100) / 100.0
        return [seed] * self.dim


class _ShortVectorEmbeddings:
    """Returns a shorter-than-expected vector to exercise the warn+zero fallback."""

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002
        return [0.5] * 10  # not 384


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
async def test_indexer_with_single_experiment_creates_table(tmp_path):
    _seed_experiment(tmp_path)
    stats = await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "rag_db",
        embeddings_client=_MockEmbeddings(),
    )
    assert stats["chunks"] >= 1
    assert stats["embedded"] >= 1
    assert stats["indexed"] >= 1
    assert stats["table"] == "cryodaq_corpus"


@pytest.mark.asyncio
async def test_indexer_dim_mismatch_falls_back_to_zero_vector(tmp_path, caplog):
    _seed_experiment(tmp_path)
    stats = await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "rag_db",
        embeddings_client=_ShortVectorEmbeddings(),
    )
    assert stats["chunks"] == stats["indexed"]
    assert stats["chunks"] >= 1
