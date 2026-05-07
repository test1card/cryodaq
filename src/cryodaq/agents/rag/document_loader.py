"""F32 — Load + chunk corpus documents for embedding.

v0.55.7.1 (F-KnowledgeBaseExpansion) extends the original three loaders
(experiment metadata, vault notes, operator log) with two more:
``load_procedure_documents`` for markdown procedures dropped under
``data/knowledge/procedures/`` and ``load_reference_documents`` for the
project's first-class reference docs (operator manual, README,
CHANGELOG). PDF ingest lives in :mod:`cryodaq.agents.rag.loaders.pdf_loader`.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentChunk:
    """Single chunk for embedding."""

    chunk_id: str
    source_kind: str
    source_id: str
    text: str
    metadata: dict


def _chunk_text(
    text: str,
    *,
    max_chars: int = 1000,
    overlap: int = 100,
) -> list[str]:
    """Sliding-window chunker. Tries to break on paragraph/sentence boundaries.

    Empty input -> []. Text shorter than `max_chars` returns a single chunk.
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + max_chars, n)
        if end < n:
            window_start = max(pos + max_chars - 200, pos + 1)
            for sep in ("\n\n", ". ", "\n", " "):
                idx = text.rfind(sep, window_start, end)
                if idx > pos:
                    end = idx + len(sep)
                    break
        chunks.append(text[pos:end].strip())
        next_pos = end - overlap if end - overlap > pos else end
        if next_pos == pos:
            next_pos = end
        pos = next_pos
    return [c for c in chunks if c]


def load_experiment_metadata(experiments_dir: Path) -> list[DocumentChunk]:
    """Walk `data/experiments/<id>/` -> chunks combining summary + metadata."""
    chunks: list[DocumentChunk] = []
    if not experiments_dir.exists():
        return chunks

    for exp_dir in sorted(experiments_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        exp_id = exp_dir.name
        metadata_path = exp_dir / "metadata.json"
        summary_path = exp_dir / "archive" / "summaries" / "summary_metadata.json"

        metadata: dict = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("Skipping %s metadata.json: %s", exp_id, exc)
                continue

        summary: dict = {}
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

        text_parts: list[str] = []
        if summary:
            text_parts.append(f"Эксперимент: {summary.get('title', exp_id)}")
            text_parts.append(f"Проба: {summary.get('sample', '—')}")
            text_parts.append(f"Оператор: {summary.get('operator', '—')}")
            text_parts.append(f"Статус: {summary.get('status', '—')}")

        description = metadata.get("description", "") or ""
        notes = metadata.get("notes", "") or ""
        if description:
            text_parts.append(f"Описание: {description}")
        if notes:
            text_parts.append(f"Заметки оператора: {notes}")

        phases = metadata.get("phases", []) or []
        if phases:
            # v0.55.14 (Codex audit SCOPE 2 finding 2.4) — defensive
            # parsing: silently drop non-dict phase entries instead of
            # crashing on `.get()` against a string / list / None.
            valid_phases = [p for p in phases if isinstance(p, dict)]
            if valid_phases:
                phase_text = "Фазы: " + "; ".join(
                    f"{p.get('phase', '?')} "
                    f"({p.get('started_at', '?')} → "
                    f"{p.get('ended_at', 'in progress')})"
                    for p in valid_phases
                )
                text_parts.append(phase_text)

        narrative = "\n".join(text_parts).strip()
        if not narrative:
            continue

        for idx, chunk_text in enumerate(_chunk_text(narrative)):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"experiment_metadata:{exp_id}:{idx}",
                    source_kind="experiment_metadata",
                    source_id=exp_id,
                    text=chunk_text,
                    metadata={
                        "experiment_id": exp_id,
                        "title": summary.get("title", ""),
                        "sample": summary.get("sample", ""),
                        "operator": summary.get("operator", ""),
                        "status": summary.get("status", ""),
                        "started_at": metadata.get("start_time", ""),
                    },
                )
            )
    return chunks


def load_vault_notes(vault_dir: Path) -> list[DocumentChunk]:
    """Walk an F31 vault directory -> Markdown body chunks + frontmatter metadata."""
    chunks: list[DocumentChunk] = []
    if not vault_dir.exists():
        return chunks

    for md_path in sorted(vault_dir.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping %s: %s", md_path, exc)
            continue

        body = text
        front: dict = {}
        if text.startswith("---"):
            end_idx = text.find("---", 3)
            if end_idx > 0:
                front_text = text[3:end_idx].strip()
                body = text[end_idx + 3 :].strip()
                for line in front_text.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        front[k.strip()] = v.strip()

        if not body:
            continue

        source_id = front.get("experiment_id") or md_path.stem
        for idx, chunk_text in enumerate(_chunk_text(body)):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"vault_note:{source_id}:{idx}",
                    source_kind="vault_note",
                    source_id=source_id,
                    text=chunk_text,
                    metadata=dict(front),
                )
            )
    return chunks


def load_operator_log_entries(sqlite_path: Path) -> list[DocumentChunk]:
    """Load operator_log entries from SQLite. One row -> one chunk."""
    chunks: list[DocumentChunk] = []
    if not sqlite_path.exists():
        return chunks

    try:
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        logger.warning("Cannot open %s read-only: %s", sqlite_path, exc)
        return chunks

    try:
        cursor = conn.execute(
            "SELECT id, timestamp, message, author, experiment_id, tags"
            " FROM operator_log"
        )
    except sqlite3.OperationalError as exc:
        logger.warning("operator_log table not present in %s: %s", sqlite_path, exc)
        conn.close()
        return chunks

    try:
        for row in cursor:
            log_id, ts, msg, author, exp_id, tags = row
            # v0.55.14 (Codex audit SCOPE 2 finding 2.4) — coerce msg
            # to str before strip(); a non-text BLOB or None passed
            # through the SQLite read would otherwise crash the loader.
            text = str(msg or "").strip()
            if not text:
                continue
            chunks.append(
                DocumentChunk(
                    chunk_id=f"operator_log:{log_id}:0",
                    source_kind="operator_log",
                    source_id=str(log_id),
                    text=text,
                    metadata={
                        "timestamp": ts,
                        "author": author or "",
                        "experiment_id": exp_id or "",
                        "tags": tags or "",
                    },
                )
            )
    finally:
        conn.close()
    return chunks


# ---------------------------------------------------------------------------
# v0.55.7.1 — F-KnowledgeBaseExpansion: procedures + reference docs.
# ---------------------------------------------------------------------------


def load_procedure_documents(
    procedures_dir: Path,
    *,
    max_chars: int = 1000,
    overlap: int = 100,
) -> list[DocumentChunk]:
    """Walk ``procedures_dir`` recursively for markdown procedure files.

    The first H1 (``# Title``) becomes the human-readable title used for
    citations; if absent, the filename (with underscores → spaces) is
    the fallback. Subdirectories define the procedure category — a file
    at ``troubleshooting/gpib_disconnect.md`` carries
    ``category=troubleshooting``; a top-level file lands in ``general``.
    ``README.md`` is treated as folder description and skipped so the
    operator can document the corpus without polluting the index.
    """
    chunks: list[DocumentChunk] = []
    if not procedures_dir.exists():
        return chunks

    md_files = [
        p
        for p in sorted(procedures_dir.rglob("*.md"))
        if p.is_file() and p.name != "README.md"
    ]
    logger.info(
        "Procedure loader: scanning %s, found %d files",
        procedures_dir,
        len(md_files),
    )

    for md_path in md_files:
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Procedure load failed %s: %s", md_path.name, exc)
            continue
        if not text.strip():
            continue

        title = md_path.stem.replace("_", " ").replace("-", " ")
        for line in text.splitlines():
            stripped = line.strip()
            # Match a single-hash heading; the negative-lookahead "## "
            # check guards against matching H2/H3 levels.
            if stripped.startswith("# ") and not stripped.startswith("## "):
                candidate = stripped[2:].strip()
                if candidate:
                    title = candidate
                break

        relative = md_path.relative_to(procedures_dir)
        category = relative.parts[0] if len(relative.parts) > 1 else "general"

        text_chunks = _chunk_text(text, max_chars=max_chars, overlap=overlap)
        for idx, chunk_text in enumerate(text_chunks):
            chunk_id = f"procedure:{relative}:c{idx}"
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    source_kind="procedure",
                    source_id=str(relative),
                    text=chunk_text,
                    metadata={
                        "title": title,
                        "category": category,
                        "chunk_index": idx,
                        "source_path": str(relative),
                    },
                )
            )

    logger.info("Procedure loader: %d chunks", len(chunks))
    return chunks


# Reference docs we always pull into the corpus so operator queries
# about CryoDAQ itself ("how do I read the cooldown predictor?") hit
# first-party documentation. Each entry is (filename, source_kind,
# document_name). The loader looks for the file at the repo root first,
# then under ``docs/``, before giving up.
_REFERENCE_DOCS: dict[str, tuple[str, str]] = {
    "operator_manual.md": ("operator_manual", "Operator Manual"),
    "README.md": ("readme", "Project README"),
    "README.en.md": ("readme_en", "Project README (EN)"),
    "CHANGELOG.md": ("changelog", "Changelog"),
}


def load_reference_documents(
    repo_root: Path,
    *,
    max_chars: int = 1500,
    overlap: int = 100,
) -> list[DocumentChunk]:
    """Index project reference docs (operator manual, README, CHANGELOG).

    operator_manual / README go through the standard sliding-window
    chunker. CHANGELOG.md is section-aware: each ``## [version]`` block
    becomes its own chunk so a query about a specific release returns
    that release's notes intact rather than a half-cut window.
    """
    chunks: list[DocumentChunk] = []

    for filename, (source_kind, document_name) in _REFERENCE_DOCS.items():
        candidates = [repo_root / filename, repo_root / "docs" / filename]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Reference load failed %s: %s", filename, exc)
            continue
        if not text.strip():
            continue

        if filename == "CHANGELOG.md":
            chunks.extend(_chunk_changelog(text, source_kind, document_name))
            continue

        text_chunks = _chunk_text(text, max_chars=max_chars, overlap=overlap)
        for idx, chunk_text in enumerate(text_chunks):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"reference:{filename}:c{idx}",
                    source_kind=source_kind,
                    source_id=filename,
                    text=chunk_text,
                    metadata={
                        "document_name": document_name,
                        "chunk_index": idx,
                    },
                )
            )

    logger.info("Reference loader: %d chunks", len(chunks))
    return chunks


def _chunk_changelog(
    text: str, source_kind: str, document_name: str
) -> list[DocumentChunk]:
    """Split CHANGELOG by ``## [version]`` so each release is its own chunk."""
    chunks: list[DocumentChunk] = []
    sections = re.split(r"^## \[", text, flags=re.MULTILINE)
    for idx, section in enumerate(sections):
        if not section.strip():
            continue
        section_text = ("## [" + section) if idx > 0 else section
        match = re.match(r"^## \[([^\]]+)\]", section_text)
        version = match.group(1) if match else f"section_{idx}"
        if len(section_text) > 3000:
            section_text = section_text[:3000] + "\n[truncated]"
        chunks.append(
            DocumentChunk(
                chunk_id=f"changelog:{version}",
                source_kind=source_kind,
                source_id=f"CHANGELOG.md#{version}",
                text=section_text,
                metadata={
                    "document_name": document_name,
                    "version": version,
                    "chunk_index": idx,
                },
            )
        )
    return chunks
