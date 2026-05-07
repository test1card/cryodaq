"""F-KnowledgeBaseExpansion (v0.55.7.1) — procedure + reference loader tests.

PHASE 3 + PHASE 4 of the spec — procedure markdown ingest with H1
title detection + subdir categorisation, and reference docs ingest
with CHANGELOG section-aware chunking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.agents.rag.document_loader import (
    load_procedure_documents,
    load_reference_documents,
)


# ---------------------------------------------------------------------------
# Procedure loader
# ---------------------------------------------------------------------------


def test_load_procedure_extracts_title_from_h1(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "cooldown.md").write_text(
        "# Протокол захолаживания\n\nDetails go here.",
        encoding="utf-8",
    )
    chunks = load_procedure_documents(proc_dir)
    assert chunks
    assert chunks[0].metadata["title"] == "Протокол захолаживания"


def test_load_procedure_falls_back_to_filename(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "no_title_here.md").write_text(
        "Just some content without a heading.\nLine two.",
        encoding="utf-8",
    )
    chunks = load_procedure_documents(proc_dir)
    assert chunks[0].metadata["title"] == "no title here"


def test_load_procedure_categorizes_by_subdir(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    sub = proc_dir / "troubleshooting"
    sub.mkdir(parents=True)
    (proc_dir / "top_level.md").write_text("# Top\nbody", encoding="utf-8")
    (sub / "gpib.md").write_text("# GPIB issue\nbody", encoding="utf-8")
    chunks = load_procedure_documents(proc_dir)
    by_id = {c.source_id: c for c in chunks}
    assert by_id["top_level.md"].metadata["category"] == "general"
    assert by_id["troubleshooting/gpib.md"].metadata["category"] == "troubleshooting"


def test_load_procedure_skips_readme_md(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "README.md").write_text("# Folder Description\nignored", encoding="utf-8")
    (proc_dir / "real_procedure.md").write_text("# Real\nindexed", encoding="utf-8")
    chunks = load_procedure_documents(proc_dir)
    assert {c.source_id for c in chunks} == {"real_procedure.md"}


def test_load_procedure_recursive_walk(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    (proc_dir / "a" / "b").mkdir(parents=True)
    (proc_dir / "top.md").write_text("# top", encoding="utf-8")
    (proc_dir / "a" / "mid.md").write_text("# mid", encoding="utf-8")
    (proc_dir / "a" / "b" / "deep.md").write_text("# deep", encoding="utf-8")
    chunks = load_procedure_documents(proc_dir)
    sources = sorted(c.source_id for c in chunks)
    assert sources == ["a/b/deep.md", "a/mid.md", "top.md"]


def test_load_procedure_handles_empty_file(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "empty.md").write_text("", encoding="utf-8")
    (proc_dir / "blank.md").write_text("   \n\n  \n", encoding="utf-8")
    chunks = load_procedure_documents(proc_dir)
    assert chunks == []


def test_load_procedure_handles_invalid_utf8(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "bad.md").write_bytes(b"# title\n\xff\xfe invalid utf8")
    (proc_dir / "good.md").write_text("# good\nfine", encoding="utf-8")
    with caplog.at_level("WARNING"):
        chunks = load_procedure_documents(proc_dir)
    assert {c.source_id for c in chunks} == {"good.md"}
    assert any("Procedure load failed" in r.message for r in caplog.records)


def test_load_procedure_h1_extraction_ignores_h2(tmp_path: Path) -> None:
    """Make sure ## doesn't accidentally win."""
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "p.md").write_text(
        "## Subheading first\n# Real Title\nbody", encoding="utf-8"
    )
    chunks = load_procedure_documents(proc_dir)
    assert chunks[0].metadata["title"] == "Real Title"


def test_load_procedure_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert load_procedure_documents(tmp_path / "nope") == []


def test_load_procedure_chunk_id_format(tmp_path: Path) -> None:
    proc_dir = tmp_path / "procedures"
    proc_dir.mkdir()
    (proc_dir / "p.md").write_text("# T\nbody", encoding="utf-8")
    chunks = load_procedure_documents(proc_dir)
    assert chunks[0].chunk_id == "procedure:p.md:c0"
    assert chunks[0].source_kind == "procedure"


# ---------------------------------------------------------------------------
# Reference loader
# ---------------------------------------------------------------------------


def test_load_reference_includes_operator_manual(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "operator_manual.md").write_text("# Manual\nbody", encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    assert any(c.source_kind == "operator_manual" for c in chunks)


def test_load_reference_includes_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# README\nbody", encoding="utf-8")
    (tmp_path / "README.en.md").write_text("# README EN\nbody", encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    kinds = {c.source_kind for c in chunks}
    assert "readme" in kinds
    assert "readme_en" in kinds


def test_load_reference_changelog_sectioned_by_version(tmp_path: Path) -> None:
    changelog = (
        "# CHANGELOG\n\n"
        "## [Unreleased]\n\nUpcoming work.\n\n"
        "## [0.55.7]\n\nv0.55.7 release notes.\n\n"
        "## [0.55.6]\n\nOlder entry.\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    versions = {c.metadata["version"] for c in chunks if c.source_kind == "changelog"}
    assert {"Unreleased", "0.55.7", "0.55.6"}.issubset(versions)
    # Each version chunk's source_id encodes the version anchor.
    chunk_055 = next(
        c for c in chunks if c.source_kind == "changelog"
        and c.metadata["version"] == "0.55.7"
    )
    assert chunk_055.source_id == "CHANGELOG.md#0.55.7"


def test_load_reference_changelog_truncates_huge_sections(tmp_path: Path) -> None:
    huge = "## [v0.55.7]\n" + ("body line\n" * 1000)
    (tmp_path / "CHANGELOG.md").write_text(huge, encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    target = next(c for c in chunks if c.metadata["version"] == "v0.55.7")
    assert "[truncated]" in target.text
    assert len(target.text) < 3500  # cap + epilogue tag


def test_load_reference_handles_missing_files_silently(tmp_path: Path) -> None:
    """No reference files at all → empty list, no exception."""
    chunks = load_reference_documents(tmp_path)
    assert chunks == []


def test_load_reference_searches_docs_subdir(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "operator_manual.md").write_text("# Manual\nbody", encoding="utf-8")
    # README at repo root, manual under docs/ — both must be picked up.
    (tmp_path / "README.md").write_text("# README\nbody", encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    kinds = {c.source_kind for c in chunks}
    assert kinds == {"operator_manual", "readme"}


def test_load_reference_handles_unreadable_files(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "README.md").write_bytes(b"\xff\xfe invalid utf8")
    (tmp_path / "README.en.md").write_text("# OK\nbody", encoding="utf-8")
    with caplog.at_level("WARNING"):
        chunks = load_reference_documents(tmp_path)
    kinds = {c.source_kind for c in chunks}
    assert kinds == {"readme_en"}
    assert any("Reference load failed" in r.message for r in caplog.records)


def test_load_reference_chunk_id_format(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# R\nbody", encoding="utf-8")
    chunks = load_reference_documents(tmp_path)
    readme = next(c for c in chunks if c.source_kind == "readme")
    assert readme.chunk_id == "reference:README.md:c0"
    assert readme.source_id == "README.md"
