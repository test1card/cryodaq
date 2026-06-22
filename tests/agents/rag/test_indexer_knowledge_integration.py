"""F-KnowledgeBaseExpansion (v0.55.7.1) — indexer integration tests.

PHASE 5: build_index gains pdf_dir / procedures_dir / reference_root
optional kwargs. Existing callers (CLI signature, RAGIndexSink) work
unchanged when those kwargs are omitted.
"""

from __future__ import annotations

import json
from pathlib import Path

import lancedb
import pytest

from cryodaq.agents.rag.indexer import _EMBEDDING_DIM, build_index
from tests.agents.rag.loaders.conftest import write_pdf


class _MockEmbeddings:
    """Deterministic _EMBEDDING_DIM-sized vector keyed on the input text."""

    def __init__(self) -> None:
        self.dim = _EMBEDDING_DIM
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        seed = (hash(text) % 100) / 100.0
        return [seed] * self.dim


def _seed_procedures(root: Path) -> Path:
    proc_dir = root / "procedures"
    proc_dir.mkdir()
    (proc_dir / "cooldown.md").write_text(
        "# Cooldown protocol\n\nDetails here.", encoding="utf-8"
    )
    return proc_dir


def _seed_pdfs(root: Path) -> Path:
    pdf_dir = root / "equipment_manuals"
    pdf_dir.mkdir()
    write_pdf(pdf_dir / "manual.pdf", ["MultiLine TCP commands"])
    return pdf_dir


def _seed_reference(root: Path) -> Path:
    (root / "README.md").write_text("# README\nbody", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "operator_manual.md").write_text(
        "# Operator Manual\nbody", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Optional knowledge dirs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_index_skips_loaders_when_dirs_absent(tmp_path: Path):
    """All three new kwargs default к None — backward-compat with v0.55.7."""
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "db",
        embeddings_client=_MockEmbeddings(),
    )
    assert stats["chunks"] == 0


@pytest.mark.asyncio
async def test_build_index_includes_pdf_when_dir_set(tmp_path: Path):
    pdf_dir = _seed_pdfs(tmp_path)
    db_path = tmp_path / "db"
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_MockEmbeddings(),
        pdf_dir=pdf_dir,
    )
    assert stats["chunks"] >= 1
    assert stats["indexed"] >= 1

    # Verify persisted rows have correct source_kind and representative content.
    arrow_tbl = lancedb.connect(str(db_path)).open_table("cryodaq_corpus").to_arrow()
    kinds = set(arrow_tbl.column("source_kind").to_pylist())
    source_ids = arrow_tbl.column("source_id").to_pylist()
    texts = arrow_tbl.column("text").to_pylist()
    assert "equipment_manual" in kinds, f"expected equipment_manual in source_kind; got {kinds}"
    assert all(s != "" for s in source_ids), "source_id must be non-empty"
    assert all(len(t) > 0 for t in texts), "text must be non-empty"
    assert any(
        "MultiLine TCP" in t or "multiline" in t.lower() for t in texts
    ), "expected PDF content 'MultiLine TCP commands' in indexed text"


@pytest.mark.asyncio
async def test_build_index_includes_procedures_when_dir_set(tmp_path: Path):
    proc_dir = _seed_procedures(tmp_path)
    db_path = tmp_path / "db"
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_MockEmbeddings(),
        procedures_dir=proc_dir,
    )
    assert stats["chunks"] >= 1

    # Verify persisted rows have correct source_kind and representative content.
    arrow_tbl = lancedb.connect(str(db_path)).open_table("cryodaq_corpus").to_arrow()
    kinds = set(arrow_tbl.column("source_kind").to_pylist())
    source_ids = arrow_tbl.column("source_id").to_pylist()
    texts = arrow_tbl.column("text").to_pylist()
    assert "procedure" in kinds, f"expected procedure in source_kind; got {kinds}"
    assert all(s != "" for s in source_ids), "source_id must be non-empty"
    assert any(
        "cooldown" in t.lower() for t in texts
    ), "expected procedure content 'cooldown' in indexed text"


@pytest.mark.asyncio
async def test_build_index_includes_reference_when_root_set(tmp_path: Path):
    _seed_reference(tmp_path)
    db_path = tmp_path / "db"
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_MockEmbeddings(),
        reference_root=tmp_path,
    )
    assert stats["chunks"] >= 2  # README + operator_manual

    # Verify persisted rows contain both reference source_kinds.
    arrow_tbl = lancedb.connect(str(db_path)).open_table("cryodaq_corpus").to_arrow()
    kinds = set(arrow_tbl.column("source_kind").to_pylist())
    source_ids = arrow_tbl.column("source_id").to_pylist()
    texts = [t.lower() for t in arrow_tbl.column("text").to_pylist()]
    assert "readme" in kinds, f"expected readme in source_kind; got {kinds}"
    assert "operator_manual" in kinds, f"expected operator_manual in source_kind; got {kinds}"
    assert all(s != "" for s in source_ids), "source_id must be non-empty"
    assert any("readme" in t for t in texts), "expected README content in indexed text"
    assert any("operator" in t for t in texts), "expected operator_manual content in indexed text"


@pytest.mark.asyncio
async def test_build_index_combines_all_loaders(tmp_path: Path):
    pdf_dir = _seed_pdfs(tmp_path)
    proc_dir = _seed_procedures(tmp_path)
    _seed_reference(tmp_path)
    db_path = tmp_path / "db"
    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=db_path,
        embeddings_client=_MockEmbeddings(),
        pdf_dir=pdf_dir,
        procedures_dir=proc_dir,
        reference_root=tmp_path,
    )
    assert stats["chunks"] >= 4  # 1 pdf + 1 proc + 2 reference

    # Verify all four source_kinds are present.
    arrow_tbl = lancedb.connect(str(db_path)).open_table("cryodaq_corpus").to_arrow()
    kinds = set(arrow_tbl.column("source_kind").to_pylist())
    source_ids = arrow_tbl.column("source_id").to_pylist()
    texts = arrow_tbl.column("text").to_pylist()
    expected_kinds = {"equipment_manual", "procedure", "readme", "operator_manual"}
    assert expected_kinds <= kinds, (
        f"expected source_kinds {expected_kinds}; got {kinds}"
    )
    assert all(s != "" for s in source_ids), "source_id must be non-empty"
    assert all(len(t) > 0 for t in texts), "text must be non-empty"


@pytest.mark.asyncio
async def test_build_index_existing_call_signature_works(tmp_path: Path):
    """Verify existing signature (no new kwargs) still works — RAGIndexSink
    and CLI before v0.55.7.1 must not break.
    """
    exp_dir = tmp_path / "experiments" / "exp001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(
        json.dumps({"description": "test", "notes": ""}), encoding="utf-8"
    )
    archive = exp_dir / "archive" / "summaries"
    archive.mkdir(parents=True)
    (archive / "summary_metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp001",
                "title": "test",
                "sample": "s",
                "operator": "v",
                "started_at": "2026-04-01T00:00:00",
                "ended_at": "2026-04-01T01:00:00",
            }
        ),
        encoding="utf-8",
    )
    stats = await build_index(
        experiments_dir=tmp_path / "experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "db",
        embeddings_client=_MockEmbeddings(),
    )
    assert stats["chunks"] >= 1
