"""F-KnowledgeBaseExpansion (v0.55.7.1) — PDF loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from cryodaq.agents.rag.loaders.pdf_loader import load_pdf_documents
from tests.agents.rag.loaders.conftest import write_pdf


@pytest.fixture
def pdf_dir(tmp_path: Path) -> Path:
    """Knowledge dir с одним 3-page PDF + один пустой PDF + sub-dir."""
    target = tmp_path / "manuals"
    target.mkdir()
    write_pdf(
        target / "etalon_multiline.pdf",
        ["Etalon MultiLine TCP commands", "Page 2 cycle data", "Page 3 burst"],
    )
    return target


# ---------------------------------------------------------------------------
# Basic ingest
# ---------------------------------------------------------------------------


def test_load_pdf_returns_chunks_for_each_page(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir)
    pages_seen = sorted(c.metadata["page_number"] for c in chunks)
    assert pages_seen == [1, 2, 3]


def test_load_pdf_metadata_includes_page_number(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir)
    page2 = next(c for c in chunks if c.metadata["page_number"] == 2)
    assert page2.metadata["total_pages"] == 3
    assert page2.metadata["chunk_index"] == 0
    assert page2.metadata["source_path"] == "etalon_multiline.pdf"


def test_load_pdf_metadata_includes_document_name(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir)
    assert chunks
    # Underscores → spaces in human-readable name.
    assert all(c.metadata["document_name"] == "etalon multiline" for c in chunks)


def test_load_pdf_chunk_id_format(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir)
    expected = [
        "pdf:etalon_multiline.pdf:p1:c0",
        "pdf:etalon_multiline.pdf:p2:c0",
        "pdf:etalon_multiline.pdf:p3:c0",
    ]
    actual = sorted(c.chunk_id for c in chunks)
    assert actual == expected


def test_load_pdf_default_source_kind(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir)
    assert all(c.source_kind == "equipment_manual" for c in chunks)


def test_load_pdf_source_kind_overridable(pdf_dir: Path) -> None:
    chunks = load_pdf_documents(pdf_dir, source_kind="vault_pdf")
    assert all(c.source_kind == "vault_pdf" for c in chunks)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_load_pdf_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    assert load_pdf_documents(tmp_path / "empty") == []


def test_load_pdf_missing_dir_returns_empty_list(tmp_path: Path) -> None:
    assert load_pdf_documents(tmp_path / "does_not_exist") == []


def test_load_pdf_skips_non_pdf_files(tmp_path: Path) -> None:
    write_pdf(tmp_path / "real.pdf", ["only PDF text"])
    (tmp_path / "notes.md").write_text("# not a pdf")
    (tmp_path / "junk.txt").write_text("plain text")
    chunks = load_pdf_documents(tmp_path)
    assert {c.source_id for c in chunks} == {"real.pdf"}


def test_load_pdf_recursive_walk_subdirs(tmp_path: Path) -> None:
    write_pdf(tmp_path / "lakeshore.pdf", ["LakeShore 218S"])
    sub = tmp_path / "vacuum"
    sub.mkdir()
    write_pdf(sub / "thyracont.pdf", ["Thyracont VSP63D"])
    chunks = load_pdf_documents(tmp_path)
    sources = sorted(c.source_id for c in chunks)
    assert sources == ["lakeshore.pdf", "vacuum/thyracont.pdf"]


def test_load_pdf_skips_corrupt_pdf_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A truncated PDF must not crash the batch — only warn + continue."""
    write_pdf(tmp_path / "good.pdf", ["good content"])
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4\nthis is not a real pdf\n")
    with caplog.at_level("WARNING"):
        chunks = load_pdf_documents(tmp_path)
    assert {c.source_id for c in chunks} == {"good.pdf"}
    assert any("PDF load failed" in r.message or "PDF page extract failed" in r.message
               for r in caplog.records)


def test_load_pdf_skips_encrypted_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Encrypted PDFs are skipped (operator must decrypt first)."""
    write_pdf(tmp_path / "good.pdf", ["unencrypted"])
    encrypted_path = tmp_path / "secret.pdf"
    writer = PdfWriter()
    # PdfWriter.append_pages_from_reader needs an existing PDF, so we
    # build a normal one first then re-open + encrypt.
    write_pdf(encrypted_path, ["secret content"])
    reader = PdfReader(str(encrypted_path))
    writer.append_pages_from_reader(reader)
    writer.encrypt(user_password="x", owner_password="x")
    with open(encrypted_path, "wb") as f:
        writer.write(f)
    with caplog.at_level("WARNING"):
        chunks = load_pdf_documents(tmp_path)
    assert {c.source_id for c in chunks} == {"good.pdf"}
    assert any("encrypted" in r.message.lower() for r in caplog.records)


def test_load_pdf_chunk_text_when_page_exceeds_max_chars(tmp_path: Path) -> None:
    """A long page splits into multiple chunks; chunk_index reflects order."""
    long_text = "lorem ipsum dolor sit amet " * 200  # ~5400 chars
    write_pdf(tmp_path / "long.pdf", [long_text])
    chunks = load_pdf_documents(tmp_path, max_chars=400, overlap=50)
    long_chunks = [c for c in chunks if c.metadata["page_number"] == 1]
    assert len(long_chunks) > 1, "long page must produce > 1 chunk"
    indices = [c.metadata["chunk_index"] for c in long_chunks]
    assert indices == sorted(indices)
    assert indices[0] == 0


def test_load_pdf_returns_empty_for_blank_pages(tmp_path: Path) -> None:
    """Pages with no text content yield no chunks."""
    write_pdf(tmp_path / "blank_page.pdf", ["", "actual text", ""])
    chunks = load_pdf_documents(tmp_path)
    pages = sorted(c.metadata["page_number"] for c in chunks)
    assert pages == [2]
