from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cryodaq.core.operator_log import (
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
)
from cryodaq.storage.sqlite_writer import SQLiteWriter

_LEGACY_OPERATOR_LOG = """
CREATE TABLE operator_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    experiment_id TEXT,
    author        TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    message       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]'
)
"""


def _legacy_database(path: Path, *, message: str = "legacy") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_OPERATOR_LOG)
        conn.execute(
            "INSERT INTO operator_log "
            "(timestamp, experiment_id, author, source, message, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime(2026, 7, 1, tzinfo=UTC).timestamp(), "exp-old", "operator", "gui", message, '["old"]'),
        )
        conn.commit()
    finally:
        conn.close()


async def test_legacy_schema_migrates_exactly_and_preserves_public_row(tmp_path: Path) -> None:
    db_path = tmp_path / "data_2026-07-01.db"
    _legacy_database(db_path)
    writer = SQLiteWriter(tmp_path)

    conn = writer._ensure_connection(date(2026, 7, 1))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(operator_log)")]
    index = next(
        row for row in conn.execute("PRAGMA index_list(operator_log)") if row[1] == "idx_operator_log_request_id"
    )
    row = conn.execute("SELECT message, tags, request_id, request_fingerprint FROM operator_log WHERE id=1").fetchone()
    await writer.stop()

    assert columns == [
        "id",
        "timestamp",
        "experiment_id",
        "author",
        "source",
        "message",
        "tags",
        "request_id",
        "request_fingerprint",
    ]
    assert int(index[2]) == 1
    assert int(index[4]) == 1
    assert row == ("legacy", '["old"]', None, None)


async def test_partial_private_schema_is_rejected_without_becoming_live(tmp_path: Path) -> None:
    db_path = tmp_path / "data_2026-07-01.db"
    _legacy_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE operator_log ADD COLUMN request_id TEXT")
    conn.commit()
    conn.close()
    writer = SQLiteWriter(tmp_path)

    with pytest.raises(RuntimeError, match="unknown or partial schema"):
        writer._ensure_connection(date(2026, 7, 1))

    assert writer._conn is None
    await writer.stop()


async def test_keyed_append_replays_original_and_conflict_is_fail_closed(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "1" * 32
    fingerprint = "a" * 64
    await writer.initialize_operator_log_idempotency()

    first = await writer.append_operator_log_idempotent(
        message="Reached stable pressure",
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["pressure"],
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await writer.append_operator_log_idempotent(
        message="This payload is deliberately not trusted by storage on replay",
        author="different",
        source="command",
        experiment_id="exp-other",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.append_operator_log_idempotent(
            message="conflict",
            request_id=request_id,
            request_fingerprint="b" * 64,
        )

    conn = sqlite3.connect(tmp_path / f"data_{first.entry.timestamp.date().isoformat()}.db")
    count = conn.execute("SELECT COUNT(*) FROM operator_log").fetchone()[0]
    stored_private = conn.execute(
        "SELECT request_id, request_fingerprint FROM operator_log WHERE id=?",
        (first.entry.id,),
    ).fetchone()
    conn.close()
    await writer.stop()

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.entry == first.entry
    assert count == 1
    assert stored_private == (request_id, fingerprint)
    assert set(first.entry.to_payload()) == {
        "id",
        "timestamp",
        "experiment_id",
        "author",
        "source",
        "message",
        "tags",
    }


async def test_restart_registry_returns_original_row_without_new_insert(tmp_path: Path) -> None:
    request_id = "2" * 32
    fingerprint = "c" * 64
    first_writer = SQLiteWriter(tmp_path)
    await first_writer.initialize_operator_log_idempotency()
    committed = await first_writer.append_operator_log_idempotent(
        message="restart-safe",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    await first_writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.initialize_operator_log_idempotency()
    found = await restarted.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await restarted.append_operator_log_idempotent(
        message="ignored-on-replay",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    conn = sqlite3.connect(tmp_path / f"data_{committed.entry.timestamp.date().isoformat()}.db")
    count = conn.execute("SELECT COUNT(*) FROM operator_log").fetchone()[0]
    conn.close()
    await restarted.stop()

    assert found is not None and found.replayed is True
    assert found.entry == committed.entry
    assert replay.entry == committed.entry
    assert replay.replayed is True
    assert count == 1


async def test_registry_refuses_ambiguous_request_ids_across_hot_days(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "3" * 32
    fingerprint = "d" * 64
    for day in (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC)):
        writer._write_operator_log_entry(
            timestamp=day,
            experiment_id=None,
            author="",
            source="test",
            message="duplicate",
            tags=(),
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="registry is invalid"):
        await restarted.initialize_operator_log_idempotency()
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await restarted.find_operator_log_request(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
    await restarted.stop()


async def test_keyed_append_is_disabled_until_bounded_registry_is_ready(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await writer.append_operator_log_idempotent(
            message="must not persist",
            request_id="4" * 32,
            request_fingerprint="e" * 64,
        )

    assert await asyncio.to_thread(lambda: list(tmp_path.glob("data_*.db"))) == []
    await writer.stop()
