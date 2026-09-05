"""Literature PDFs are a distinct source kind, and they live in subfolders.

The literature corpus is organised by topic — ``literature/cryocoolers/``,
``literature/vacuum/``, ``literature/outgassing/`` — so a loader that globbed
only the top level would silently index nothing at all while reporting
success. That is the failure this file exists to prevent.

The second thing pinned here is the ``source_kind``. A claim drawn from a NIST
monograph and a claim drawn from a vendor manual carry different weight, and
the operator decides which to trust — but only if the citation says which one
it came from. CryoDAQ informs; it does not decide that for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.agents.rag.indexer import _EMBEDDING_DIM, build_index
from cryodaq.agents.rag.loaders.pdf_loader import load_pdf_documents
from tests.agents.rag.loaders.conftest import write_pdf


class _MockEmbeddings:
    def __init__(self) -> None:
        self.dim = _EMBEDDING_DIM

    async def embed(self, text: str) -> list[float]:
        return [0.5] * self.dim


def _seed_literature(root: Path) -> Path:
    """Topic subfolders, exactly as the fetched corpus is laid out on disk."""
    lit = root / "literature"
    (lit / "cryocoolers").mkdir(parents=True)
    (lit / "vacuum").mkdir(parents=True)
    write_pdf(
        lit / "cryocoolers" / "radebaugh-2009-state-of-the-art.pdf",
        ["Regenerator losses scale steeply below 10 K"],
    )
    write_pdf(
        lit / "vacuum" / "chiggiato-outgassing.pdf",
        ["Water outgassing from metals decays as t to the minus one"],
    )
    return lit


def test_literature_in_subfolders_is_found_not_silently_skipped(tmp_path: Path):
    """A non-recursive glob would return zero chunks here and look fine."""
    lit_dir = _seed_literature(tmp_path)

    chunks = load_pdf_documents(lit_dir, source_kind="literature")

    assert chunks, "topic subfolders were not walked — the corpus indexed as empty"
    found = {chunk.source_id for chunk in chunks}
    assert "cryocoolers/radebaugh-2009-state-of-the-art.pdf" in found
    assert "vacuum/chiggiato-outgassing.pdf" in found


def test_literature_is_not_labelled_as_an_equipment_manual(tmp_path: Path):
    lit_dir = _seed_literature(tmp_path)

    chunks = load_pdf_documents(lit_dir, source_kind="literature")

    kinds = {chunk.source_kind for chunk in chunks}
    assert kinds == {"literature"}


@pytest.mark.asyncio
async def test_build_index_indexes_literature_alongside_manuals(tmp_path: Path):
    """Both corpora land in one index, still telling the operator them apart."""
    lit_dir = _seed_literature(tmp_path)
    manuals = tmp_path / "equipment_manuals"
    manuals.mkdir()
    write_pdf(manuals / "ls218.pdf", ["Input excitation is ten microamps"])

    stats = await build_index(
        experiments_dir=tmp_path / "no_experiments",
        vault_dir=None,
        sqlite_path=None,
        db_path=tmp_path / "db",
        embeddings_client=_MockEmbeddings(),
        pdf_dir=manuals,
        literature_dir=lit_dir,
    )

    # Two literature PDFs plus one manual — none of them dropped.
    assert stats["chunks"] >= 3
