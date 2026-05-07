"""F32 — Load + chunk corpus documents for embedding."""

from __future__ import annotations

import json
import logging
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
            phase_text = "Фазы: " + "; ".join(
                f"{p.get('phase')} ({p.get('started_at', '?')} → {p.get('ended_at', 'in progress')})"
                for p in phases
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
            text = (msg or "").strip()
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
