"""F32 — document loader / chunking tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cryodaq.agents.rag.document_loader import (
    _chunk_text,
    load_experiment_metadata,
    load_operator_log_entries,
    load_vault_notes,
)


def test_chunk_short_text_returns_single_chunk():
    chunks = _chunk_text("short text", max_chars=1000)
    assert chunks == ["short text"]


def test_chunk_long_text_splits():
    text = "abc " * 500  # 2000 chars
    chunks = _chunk_text(text, max_chars=500, overlap=50)
    assert len(chunks) >= 4
    assert all(c for c in chunks)


def test_chunk_empty_returns_empty():
    assert _chunk_text("") == []


def test_chunk_prefers_sentence_boundary_over_arbitrary_split():
    # Pad the first sentence so the boundary lands inside the chunker's
    # back-search window, then verify the split lands at ". " rather than
    # cutting a word in half.
    first = "First sentence with enough body to land near the split point. "
    second = "Second sentence."
    text = first + second + " filler" * 200
    chunks = _chunk_text(text, max_chars=70, overlap=0)
    assert chunks[0].rstrip().endswith(".")


def test_load_experiment_metadata_walks_directory(tmp_path):
    exp_dir = tmp_path / "abc12345"
    (exp_dir / "archive" / "summaries").mkdir(parents=True)
    (exp_dir / "metadata.json").write_text(
        json.dumps(
            {
                "description": "Test description",
                "notes": "Test notes",
                "phases": [
                    {"phase": "preparation", "started_at": "2026-05-07T10:00:00Z"}
                ],
            }
        )
    )
    (exp_dir / "archive" / "summaries" / "summary_metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "abc12345",
                "title": "Тест",
                "sample": "S-001",
                "operator": "Vladimir",
                "status": "COMPLETED",
            }
        )
    )

    chunks = load_experiment_metadata(tmp_path)
    assert len(chunks) >= 1
    assert chunks[0].source_kind == "experiment_metadata"
    assert chunks[0].source_id == "abc12345"
    text = chunks[0].text
    assert "Test description" in text or "Test notes" in text


def test_load_experiment_metadata_returns_empty_when_dir_missing(tmp_path):
    chunks = load_experiment_metadata(tmp_path / "no-such-dir")
    assert chunks == []


def test_load_experiment_metadata_skips_corrupt_json(tmp_path, caplog):
    exp_dir = tmp_path / "broken"
    exp_dir.mkdir()
    (exp_dir / "metadata.json").write_text("{ not json")
    chunks = load_experiment_metadata(tmp_path)
    assert chunks == []


def test_load_vault_notes_parses_frontmatter(tmp_path):
    md = (
        "---\n"
        "experiment_id: abc12345\n"
        "sample: S-001\n"
        "---\n"
        "\n"
        "# Тестовый эксперимент\n"
        "\n"
        "Body content here.\n"
    )
    (tmp_path / "test.md").write_text(md)
    chunks = load_vault_notes(tmp_path)
    assert len(chunks) >= 1
    assert chunks[0].metadata.get("experiment_id") == "abc12345"
    assert chunks[0].source_id == "abc12345"
    assert "Body content here" in chunks[0].text


def test_load_vault_notes_returns_empty_when_dir_missing(tmp_path):
    chunks = load_vault_notes(tmp_path / "no-such-dir")
    assert chunks == []


def test_load_operator_log_entries_returns_empty_when_file_missing(tmp_path):
    chunks = load_operator_log_entries(tmp_path / "no.db")
    assert chunks == []


def test_load_operator_log_entries_reads_rows(tmp_path):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE operator_log (id INTEGER PRIMARY KEY, timestamp TEXT,"
            " message TEXT, author TEXT, experiment_id TEXT, tags TEXT)"
        )
        conn.execute(
            "INSERT INTO operator_log VALUES (1, '2026-05-07T10:00:00Z',"
            " 'beam break detected', 'Vladimir', 'abc', 'alarm')"
        )
        conn.execute(
            "INSERT INTO operator_log VALUES (2, '2026-05-07T11:00:00Z',"
            " '', 'Vladimir', 'abc', '')"  # empty message — should be skipped
        )
        conn.commit()
    finally:
        conn.close()

    chunks = load_operator_log_entries(db_path)
    assert len(chunks) == 1
    assert chunks[0].text == "beam break detected"
    assert chunks[0].metadata["experiment_id"] == "abc"


def test_load_operator_log_entries_handles_missing_table(tmp_path):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE other (x INTEGER)")
        conn.commit()
    finally:
        conn.close()
    chunks = load_operator_log_entries(db_path)
    assert chunks == []
