"""v0.55.14 — regression guards for the RAG-fixes hotfix release.

Covers Codex audit SCOPE 2 + SCOPE 6 follow-ups:
- 2.3 — LanceDB rebuild crash-safety via staging+swap
- 2.4 — document_loader defensive parsing of malformed metadata
- 2.7 — chunker handles a large document with embedded code blocks
- 6.6 — build_index offloads sync filesystem walk to asyncio.to_thread
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.rag.document_loader import (
    _chunk_text,
    load_experiment_metadata,
    load_operator_log_entries,
)
from cryodaq.agents.rag.indexer import _swap_table_atomically, build_index


# ---------------------------------------------------------------------------
# 2.3 — crash-safe rebuild
# ---------------------------------------------------------------------------


def _make_schema_for_test():
    import pyarrow as pa

    return pa.schema(
        [
            ("chunk_id", pa.string()),
            ("source_kind", pa.string()),
            ("source_id", pa.string()),
            ("text", pa.string()),
            ("vector", pa.list_(pa.float32(), 4)),
            ("metadata_json", pa.string()),
        ]
    )


def _make_row(idx: int = 0) -> dict:
    return {
        "chunk_id": f"chunk_{idx}",
        "source_kind": "experiment_metadata",
        "source_id": f"exp_{idx}",
        "text": f"sample text {idx}",
        "vector": [0.1, 0.2, 0.3, 0.4],
        "metadata_json": "{}",
    }


def test_swap_creates_canonical_table_when_absent(tmp_path: Path) -> None:
    import lancedb

    db = lancedb.connect(str(tmp_path / "lance"))
    rows = [_make_row(0), _make_row(1)]

    table = _swap_table_atomically(
        db, table_name="test_corpus", rows=rows, schema=_make_schema_for_test()
    )

    assert table.count_rows() == 2
    assert "test_corpus" in db.list_tables().tables
    # Staging table cleaned up after the swap
    assert "test_corpus__staging" not in db.list_tables().tables


def test_swap_replaces_existing_canonical_table(tmp_path: Path) -> None:
    import lancedb

    db = lancedb.connect(str(tmp_path / "lance"))
    schema = _make_schema_for_test()

    # Pre-populate the canonical table with stale data.
    db.create_table("test_corpus", data=[_make_row(99)], schema=schema)

    new_rows = [_make_row(0), _make_row(1), _make_row(2)]
    table = _swap_table_atomically(
        db, table_name="test_corpus", rows=new_rows, schema=schema
    )

    assert table.count_rows() == 3
    # Staging slot is cleaned up
    assert "test_corpus__staging" not in db.list_tables().tables


def test_swap_cleans_up_orphaned_staging(tmp_path: Path) -> None:
    """If a previous rebuild crashed leaving a staging table, the next
    swap should drop and recreate it cleanly."""
    import lancedb

    db = lancedb.connect(str(tmp_path / "lance"))
    schema = _make_schema_for_test()

    # Simulate orphaned staging from a prior crashed run.
    db.create_table("test_corpus__staging", data=[_make_row(99)], schema=schema)

    table = _swap_table_atomically(
        db, table_name="test_corpus", rows=[_make_row(0)], schema=schema
    )

    assert table.count_rows() == 1
    assert "test_corpus__staging" not in db.list_tables().tables


# ---------------------------------------------------------------------------
# 2.4 — defensive parsing in loader
# ---------------------------------------------------------------------------


def test_load_experiment_metadata_skips_non_dict_phase_entries(tmp_path: Path) -> None:
    """If a malformed metadata.json has a phase entry that isn't a dict
    (e.g. a string from a corrupted write), the loader must skip it
    rather than crashing on `.get()`."""
    exp_dir = tmp_path / "exp-1"
    exp_dir.mkdir()
    (exp_dir / "metadata.json").write_text(
        json.dumps(
            {
                "phases": [
                    {"phase": "preparation", "started_at": "T0"},
                    "this string is not a phase dict",
                    None,
                    {"phase": "cooldown", "started_at": "T1"},
                ]
            }
        ),
        encoding="utf-8",
    )

    chunks = load_experiment_metadata(tmp_path)
    # Should produce a chunk and not crash; the phase summary should
    # mention the two valid dicts.
    assert chunks, "Expected at least one chunk"
    text = "\n".join(c.text for c in chunks)
    assert "preparation" in text
    assert "cooldown" in text


def test_load_experiment_metadata_handles_string_phases_field(tmp_path: Path) -> None:
    """If the entire `phases` field isn't a list, the loader still
    proceeds (but emits no phase summary)."""
    exp_dir = tmp_path / "exp-2"
    exp_dir.mkdir()
    (exp_dir / "metadata.json").write_text(
        json.dumps({"phases": "not a list", "description": "valid"}),
        encoding="utf-8",
    )

    chunks = load_experiment_metadata(tmp_path)
    # Loader should yield no fatal error; if a chunk is produced,
    # the description text survives.
    if chunks:
        assert "valid" in chunks[0].text


def test_load_operator_log_entries_coerces_non_string_message(tmp_path: Path) -> None:
    """Operator-log SQLite may have BLOB messages from legacy writers;
    str() coercion before strip() prevents an AttributeError."""
    db_path = tmp_path / "data_2025.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE operator_log ("
        "  id INTEGER PRIMARY KEY,"
        "  timestamp TEXT,"
        "  message TEXT,"
        "  author TEXT,"
        "  experiment_id TEXT,"
        "  tags TEXT"
        ")"
    )
    # Real string row + a NULL row + a numeric row that SQLite returns as int
    conn.execute(
        "INSERT INTO operator_log VALUES (?, ?, ?, ?, ?, ?)",
        (1, "2025-12-01T00:00", "valid message", "operator", "", ""),
    )
    conn.execute(
        "INSERT INTO operator_log VALUES (?, ?, ?, ?, ?, ?)",
        (2, "2025-12-01T00:00", None, "operator", "", ""),
    )
    conn.execute(
        "INSERT INTO operator_log VALUES (?, ?, ?, ?, ?, ?)",
        (3, "2025-12-01T00:00", 12345, "operator", "", ""),
    )
    conn.commit()
    conn.close()

    chunks = load_operator_log_entries(db_path)
    # Two chunks: the valid string + the int (coerced to "12345"). The
    # NULL row drops to "" after strip and is filtered.
    texts = [c.text for c in chunks]
    assert "valid message" in texts
    assert "12345" in texts


# ---------------------------------------------------------------------------
# 2.7 — chunker handles large doc with code blocks
# ---------------------------------------------------------------------------


def test_chunk_text_handles_large_doc_with_embedded_code_blocks() -> None:
    """A 10x-max-chars Markdown doc with embedded triple-backtick code
    blocks must produce non-empty chunks and not get stuck in an
    infinite loop on boundary search."""
    chunk_max = 1000
    code = "\n".join(f"def func_{i}(): return {i}" for i in range(50))
    doc_parts = []
    for section in range(8):
        doc_parts.append(f"## Section {section}\n")
        doc_parts.append(
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 20
        )
        doc_parts.append(f"\n\n```python\n{code}\n```\n\n")
    text = "".join(doc_parts)
    assert len(text) > chunk_max * 5  # fixture sanity

    chunks = _chunk_text(text, max_chars=chunk_max, overlap=100)

    assert len(chunks) >= 5
    # All chunks non-empty after strip
    assert all(c.strip() for c in chunks)
    # No chunk wildly exceeds the budget (allow some slack for boundary
    # walk + overlap accounting)
    assert all(len(c) <= chunk_max + 200 for c in chunks)


def test_chunk_text_handles_single_oversized_token() -> None:
    """A single line longer than max_chars must NOT loop forever."""
    text = "x" * 5000
    chunks = _chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) >= 4
    # Each chunk fits roughly within budget
    assert all(len(c) <= 1100 for c in chunks)


def test_chunk_text_empty_returns_empty() -> None:
    assert _chunk_text("") == []


def test_chunk_text_single_short_chunk() -> None:
    assert _chunk_text("hello world") == ["hello world"]


# ---------------------------------------------------------------------------
# 6.6 — build_index offloads sync work to to_thread
# ---------------------------------------------------------------------------


def test_build_index_offloads_loaders_via_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The synchronous filesystem-walking loaders must run via
    asyncio.to_thread so the event loop stays responsive during a
    finalize-time rebuild."""
    from cryodaq.agents.rag import indexer

    seen: list[str] = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        seen.append(getattr(func, "__name__", repr(func)))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(indexer.asyncio, "to_thread", spy_to_thread)

    embeddings = MagicMock()
    embeddings.embed = AsyncMock(return_value=[0.0] * 384)

    asyncio.run(
        build_index(
            experiments_dir=tmp_path / "experiments",  # empty
            vault_dir=None,
            sqlite_path=None,
            db_path=tmp_path / "lance",
            embeddings_client=embeddings,
        )
    )

    assert "load_experiment_metadata" in seen


def test_build_index_returns_zero_stats_on_empty_corpus(tmp_path: Path) -> None:
    """Empty corpus must terminate cleanly without invoking the
    LanceDB swap path (no staging table left over)."""
    embeddings = MagicMock()
    embeddings.embed = AsyncMock(return_value=[0.0] * 384)

    stats = asyncio.run(
        build_index(
            experiments_dir=tmp_path / "no-experiments",
            vault_dir=None,
            sqlite_path=None,
            db_path=tmp_path / "lance",
            embeddings_client=embeddings,
        )
    )

    assert stats == {
        "chunks": 0,
        "embedded": 0,
        "indexed": 0,
        "db_path": str(tmp_path / "lance"),
        "table": "cryodaq_corpus",
    }
    embeddings.embed.assert_not_awaited()
