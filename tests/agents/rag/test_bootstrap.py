"""F-KnowledgeBaseExpansion (v0.55.7.1) — engine RAG bootstrap tests.

PHASE 6: ``_bootstrap_rag_index_if_empty`` is fire-and-forget.
- Skips when index already populated.
- Builds when probe returns empty / fails.
- Failures are logged, never propagated (engine ready signal must
  not block on bootstrap).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cryodaq.agents.rag.indexer import _EMBEDDING_DIM
from cryodaq.engine import _bootstrap_rag_index_if_empty
from tests.agents.rag.loaders.conftest import write_pdf


class _MockEmbeddings:
    """Deterministic 1024d vector."""

    def __init__(self) -> None:
        self.dim = _EMBEDDING_DIM
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        seed = (hash(text) % 100) / 100.0
        return [seed] * self.dim


def _seed_minimal_corpus(root: Path) -> Path:
    """One markdown procedure under data/knowledge/procedures/."""
    knowledge = root / "knowledge"
    procedures = knowledge / "procedures"
    procedures.mkdir(parents=True)
    (procedures / "p.md").write_text("# Test procedure\nbody", encoding="utf-8")
    return knowledge


def _seed_pdf_corpus(root: Path) -> Path:
    knowledge = root / "knowledge"
    pdf_dir = knowledge / "equipment_manuals"
    pdf_dir.mkdir(parents=True)
    write_pdf(pdf_dir / "manual.pdf", ["Sample manual content"])
    return knowledge


# ---------------------------------------------------------------------------
# Bootstrap behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_runs_when_index_empty(tmp_path: Path) -> None:
    """Empty db_path → build_index runs and produces chunks."""
    knowledge = _seed_minimal_corpus(tmp_path)
    db_path = tmp_path / "rag_db"
    embeddings = _MockEmbeddings()

    await _bootstrap_rag_index_if_empty(
        db_path=db_path,
        embeddings_client=embeddings,
        knowledge_dir=knowledge,
        experiments_dir=tmp_path / "experiments",
        sqlite_path=None,
        repo_root=tmp_path,
    )

    # build_index ran → at least the procedure chunk got embedded.
    assert any("Test procedure" in c for c in embeddings.calls), (
        "Embeddings client should have been called for procedure chunk"
    )


@pytest.mark.asyncio
async def test_bootstrap_skips_when_index_populated(tmp_path: Path) -> None:
    """Probe returns ≥1 hit → bootstrap exits early without indexing."""
    knowledge = _seed_minimal_corpus(tmp_path)
    db_path = tmp_path / "rag_db"
    embeddings = _MockEmbeddings()

    # Patch RagSearcher.search to return a fake hit на the probe.
    from cryodaq.agents.rag import searcher as searcher_mod

    class _PopulatedSearcher:
        def __init__(self, *args, **kwargs):
            pass

        async def search(self, *args, **kwargs):
            return [object()]  # truthy single result

    with patch.object(searcher_mod, "RagSearcher", _PopulatedSearcher):
        await _bootstrap_rag_index_if_empty(
            db_path=db_path,
            embeddings_client=embeddings,
            knowledge_dir=knowledge,
            experiments_dir=tmp_path / "experiments",
            sqlite_path=None,
            repo_root=tmp_path,
        )

    # build_index NOT invoked → embeddings client untouched.
    assert embeddings.calls == [], (
        "Bootstrap must skip when index already populated"
    )


@pytest.mark.asyncio
async def test_bootstrap_failure_does_not_propagate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """build_index raising must NOT crash the engine startup.

    Engine fires this as asyncio.create_task; if it raised, asyncio
    would log the unhandled exception but the engine ready signal would
    still go through (the task is detached). The test asserts the
    helper itself swallows the exception so the failure is contained
    к a single ERROR log line.
    """
    knowledge = _seed_minimal_corpus(tmp_path)
    db_path = tmp_path / "rag_db"

    class _BoomEmbeddings:
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("ollama unreachable")

    with caplog.at_level("ERROR"):
        await _bootstrap_rag_index_if_empty(
            db_path=db_path,
            embeddings_client=_BoomEmbeddings(),
            knowledge_dir=knowledge,
            experiments_dir=tmp_path / "experiments",
            sqlite_path=None,
            repo_root=tmp_path,
        )

    assert any(
        "RAG bootstrap failed" in r.message for r in caplog.records
    ), "Bootstrap must log ERROR on failure but not raise"


@pytest.mark.asyncio
async def test_bootstrap_handles_pdf_corpus(tmp_path: Path) -> None:
    """End-to-end: PDF dropped under equipment_manuals/ gets indexed."""
    knowledge = _seed_pdf_corpus(tmp_path)
    db_path = tmp_path / "rag_db"
    embeddings = _MockEmbeddings()

    await _bootstrap_rag_index_if_empty(
        db_path=db_path,
        embeddings_client=embeddings,
        knowledge_dir=knowledge,
        experiments_dir=tmp_path / "experiments",
        sqlite_path=None,
        repo_root=tmp_path,
    )

    assert any("Sample manual content" in c for c in embeddings.calls)


@pytest.mark.asyncio
async def test_bootstrap_idempotent_after_population(tmp_path: Path) -> None:
    """Running bootstrap twice — second call must observe non-empty index."""
    knowledge = _seed_minimal_corpus(tmp_path)
    db_path = tmp_path / "rag_db"
    embeddings1 = _MockEmbeddings()

    # First call populates index.
    await _bootstrap_rag_index_if_empty(
        db_path=db_path,
        embeddings_client=embeddings1,
        knowledge_dir=knowledge,
        experiments_dir=tmp_path / "experiments",
        sqlite_path=None,
        repo_root=tmp_path,
    )
    first_call_count = len(embeddings1.calls)
    assert first_call_count > 0

    # Second call detects populated index → skips.
    embeddings2 = _MockEmbeddings()
    await _bootstrap_rag_index_if_empty(
        db_path=db_path,
        embeddings_client=embeddings2,
        knowledge_dir=knowledge,
        experiments_dir=tmp_path / "experiments",
        sqlite_path=None,
        repo_root=tmp_path,
    )
    # Probe call only — no rebuild.
    assert len(embeddings2.calls) <= 1, (
        f"Second bootstrap must skip indexing, got {len(embeddings2.calls)} embed calls"
    )


@pytest.mark.asyncio
async def test_bootstrap_with_no_corpus_at_all(tmp_path: Path) -> None:
    """Bootstrap on a clean checkout с no corpus must not crash —
    build_index returns zero stats and the engine continues."""
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()  # empty
    db_path = tmp_path / "rag_db"
    embeddings = _MockEmbeddings()

    await _bootstrap_rag_index_if_empty(
        db_path=db_path,
        embeddings_client=embeddings,
        knowledge_dir=knowledge,
        experiments_dir=tmp_path / "experiments",
        sqlite_path=None,
        repo_root=tmp_path,
    )
    # Zero embed calls — build_index sees empty corpus and returns early.
    assert embeddings.calls == []
