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
    # Stale row (chunk_99) must not appear; new rows present
    ids = set(table.to_arrow().column("chunk_id").to_pylist())
    assert "chunk_99" not in ids, "Stale row from pre-existing table survived the swap"
    assert {"chunk_0", "chunk_1", "chunk_2"} == ids


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
    # Orphaned staging row (chunk_99) must not bleed into canonical table
    ids = set(table.to_arrow().column("chunk_id").to_pylist())
    assert "chunk_99" not in ids, "Orphaned staging row leaked into canonical table"
    assert ids == {"chunk_0"}


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
    # Loader must produce at least one chunk and the description text survives.
    assert chunks, "Expected at least one chunk even when phases field is not a list"
    text = "\n".join(c.text for c in chunks)
    assert "valid" in text, f"Expected 'valid' in chunk text, got: {text!r}"


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
    """build_index must offload sync loaders via asyncio.to_thread so the event
    loop stays responsive while a loader blocks in its worker thread.

    Proof of genuine event-loop responsiveness:
    1. Monkeypatch load_vault_notes to block on a threading.Event (not yet set).
    2. Run build_index as an asyncio Task.
    3. Concurrently run a heartbeat coroutine that ticks every 5 ms.
    4. Wait (bounded, 3 s) until load_vault_notes is confirmed blocked (a second
       threading.Event set at loader entry).
    5. Assert heartbeat has advanced ≥ 3 ticks while the loader is blocked
       — proves the event loop was NOT blocked.
    6. Set the release Event so the loader (and build_index) can complete.
    7. Await build_index completion with a 10 s timeout.
    """
    import threading

    from cryodaq.agents.rag import document_loader as _dl_mod
    from cryodaq.agents.rag import indexer

    # Two threading events for loader coordination.
    _loader_entered = threading.Event()   # set inside the blocked loader
    _loader_release = threading.Event()   # set by the test to unblock the loader

    original_load_vault_notes = _dl_mod.load_vault_notes

    seen: list[str] = []

    def _blocking_load_vault_notes(vault_dir):
        """Replacement that blocks until released — runs in worker thread."""
        seen.append("load_vault_notes")
        _loader_entered.set()                         # signal: we are now blocked
        _loader_release.wait(timeout=10.0)            # block until test releases us
        return original_load_vault_notes(vault_dir)

    monkeypatch.setattr(_dl_mod, "load_vault_notes", _blocking_load_vault_notes)
    # Also patch the name as imported inside indexer
    monkeypatch.setattr(indexer, "load_vault_notes", _blocking_load_vault_notes, raising=False)

    # Verify build_index uses asyncio.to_thread for loaders; if not, this test
    # would deadlock (loader blocks event loop) — detect early via a short timeout.

    # Prepare minimal vault dir
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    # Prepare minimal sqlite DB
    sqlite_path = tmp_path / "data_2026.db"
    conn = sqlite3.connect(str(sqlite_path))
    conn.execute(
        "CREATE TABLE operator_log ("
        "id INTEGER PRIMARY KEY, timestamp TEXT, message TEXT, "
        "author TEXT, experiment_id TEXT, tags TEXT)"
    )
    conn.commit()
    conn.close()

    embeddings = MagicMock()
    embeddings.embed = AsyncMock(return_value=[0.0] * 384)

    async def _run() -> None:
        heartbeat_ticks: list[int] = [0]
        heartbeat_done = asyncio.Event()

        async def _heartbeat() -> None:
            try:
                while not heartbeat_done.is_set():
                    await asyncio.sleep(0.005)   # 5 ms
                    heartbeat_ticks[0] += 1
            except asyncio.CancelledError:
                pass

        hb_task = asyncio.create_task(_heartbeat())
        build_task = asyncio.create_task(
            build_index(
                experiments_dir=tmp_path / "experiments",
                vault_dir=vault_dir,
                sqlite_path=sqlite_path,
                db_path=tmp_path / "lance",
                embeddings_client=embeddings,
            )
        )

        # Wait until the loader is confirmed blocked in its worker thread (bounded 3 s).
        # We poll with asyncio.sleep so the event loop keeps running during the wait.
        deadline = asyncio.get_event_loop().time() + 3.0
        while not _loader_entered.is_set():
            if asyncio.get_event_loop().time() > deadline:
                _loader_release.set()    # prevent deadlock before failing
                hb_task.cancel()
                pytest.fail(
                    "load_vault_notes was not called within 3 s — "
                    "build_index may not be offloading loaders via asyncio.to_thread"
                )
            await asyncio.sleep(0.005)

        # Loader is confirmed blocked in worker thread.
        # Give the heartbeat coroutine several scheduling rounds to accumulate ticks.
        for _ in range(10):
            await asyncio.sleep(0.010)   # 10 ms per iteration → at least 2 ticks each

        # Loader is blocked in worker thread; assert heartbeat has advanced.
        ticks_while_blocked = heartbeat_ticks[0]
        assert ticks_while_blocked >= 3, (
            f"Event loop did not tick while loader was blocked "
            f"(heartbeat_ticks={ticks_while_blocked}); "
            "loader may be running on the event loop thread instead of to_thread"
        )

        # Release the blocked loader so build_index can finish.
        _loader_release.set()

        # Await build_index with a generous timeout.
        await asyncio.wait_for(build_task, timeout=10.0)

        heartbeat_done.set()
        await hb_task

    asyncio.run(_run())

    # Confirm load_vault_notes was indeed called.
    assert "load_vault_notes" in seen, f"load_vault_notes was not called; seen={seen}"


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
        "failed": 0,
        "indexed": 0,
        "db_path": str(tmp_path / "lance"),
        "table": "cryodaq_corpus",
    }
    embeddings.embed.assert_not_awaited()
