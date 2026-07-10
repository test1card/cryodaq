from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import cryodaq.storage.archive_reader as archive_reader_module
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader, BoundedReadIssueCode


def _hot_db(root: Path, day: str, rows: list[tuple[object, str, str, float, str, str]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"data_{day}.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE readings(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp REAL NOT NULL,
          instrument_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          value REAL NOT NULL,
          unit TEXT NOT NULL,
          status TEXT NOT NULL
        );
        CREATE INDEX idx_readings_ts ON readings(timestamp);
        CREATE INDEX idx_channel_ts ON readings(channel, timestamp);
        """
    )
    connection.executemany(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
        rows,
    )
    connection.commit()
    connection.close()
    return path


def _cold(
    root: Path,
    day: str,
    rows: list[tuple[datetime, str, str, float, str, str]],
    *,
    row_group_size: int = 2,
) -> Path:
    relative = Path(f"year={day[:4]}") / f"data_{day}.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": pa.array([r[0] for r in rows], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([r[1] for r in rows], type=pa.string()),
            "channel": pa.array([r[2] for r in rows], type=pa.string()),
            "value": pa.array([r[3] for r in rows], type=pa.float64()),
            "unit": pa.array([r[4] for r in rows], type=pa.string()),
            "status": pa.array([r[5] for r in rows], type=pa.string()),
        }
    )
    pq.write_table(table, path, row_group_size=row_group_size)
    (root / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": f"data_{day}.db",
                        "archive_path": relative.as_posix(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _query(reader: ArchiveReader, start: datetime, end: datetime, **kwargs: object):
    defaults: dict[str, object] = {
        "channels": ("T",),
        "max_channels": 4,
        "max_points_per_channel": 20,
        "max_total_points": 40,
        "max_retained_bytes": 65_536,
        "deadline_monotonic": time.monotonic() + 10,
        "batch_rows": 64,
        "max_arrow_batch_bytes": 65_536,
    }
    defaults.update(kwargs)
    return reader.query_reading_rows_bounded(start=start, end=end, **defaults)


def test_bounded_rows_preserve_fields_null_and_end_exclusive(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [
            (start.timestamp(), "ls", "T", 1.0, "K", "ok"),
            ((start + timedelta(microseconds=1)).timestamp(), "ls", "T", math.inf, "K", "overrange"),
            ((start + timedelta(seconds=2)).timestamp(), "ls", "T", 3.0, "K", "ok"),
        ],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=2),
    )
    assert result.complete is True
    assert [(row.instrument_id, row.channel, row.unit, row.status) for row in result.rows] == [
        ("ls", "T", "K", "ok"),
        ("ls", "T", "K", "overrange"),
    ]
    assert result.rows[1].value is None


def test_hot_cold_overlap_archive_wins_at_microsecond_precision(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        [(start + timedelta(microseconds=123456), "i", "T", 10.0, "K", "ok")],
    )
    _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [
            ((start + timedelta(microseconds=123456)).timestamp(), "i", "T", 99.0, "K", "ok"),
            ((start + timedelta(seconds=1)).timestamp(), "i", "T", 11.0, "K", "ok"),
        ],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=2),
    )
    assert result.complete is True
    assert [row.value for row in result.rows] == [10.0, 11.0]


def test_caps_are_applied_during_collection(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    rows = [((start + timedelta(seconds=index)).timestamp(), "i", "T", float(index), "K", "ok") for index in range(100)]
    _hot_db(tmp_path / "data", "2026-07-10", rows)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=101),
        max_points_per_channel=2,
        max_total_points=2,
    )
    assert [row.value for row in result.rows] == [98.0, 99.0]
    assert result.truncated is True
    assert result.rows_dropped_by_caps == 98
    assert result.retained_encoded_bytes <= 65_536


def test_none_channels_fails_closed_at_limit(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    rows = [(start.timestamp(), "i", f"C{index}", float(index), "K", "ok") for index in range(5)]
    _hot_db(tmp_path / "data", "2026-07-10", rows)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        channels=None,
        max_channels=4,
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.CHANNEL_LIMIT in {issue.code for issue in result.issues}


def test_cross_source_duplicate_channels_cannot_hide_the_extra_channel(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 9, tzinfo=UTC)
    _hot_db(
        tmp_path / "data",
        "2026-07-09",
        [
            (start.timestamp(), "i", channel, float(index), "K", "ok")
            for index, channel in enumerate(("A", "B", "C", "D"))
        ],
    )
    _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [
            ((start + timedelta(days=1)).timestamp(), "i", channel, float(index), "K", "ok")
            for index, channel in enumerate(("A", "B"))
        ],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(days=2),
        channels=None,
        max_channels=3,
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.CHANNEL_LIMIT in {issue.code for issue in result.issues}


def test_none_channels_fails_closed_when_indexed_source_is_missing(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": "data_2026-07-10.db",
                        "archive_path": "year=2026/missing.parquet",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        channels=None,
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.SOURCE_MISSING in {issue.code for issue in result.issues}


def test_legacy_text_timestamp_is_partial(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    path = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
        ("2026-07-10T00:00:00+00:00", "i", "T", 2.0, "K", "ok"),
    )
    connection.commit()
    connection.close()
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert len(result.rows) == 1
    assert result.complete is False
    assert BoundedReadIssueCode.LEGACY_TIMESTAMP_UNSUPPORTED in {issue.code for issue in result.issues}


def test_midnight_end_excludes_faults_from_the_wholly_excluded_day(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 9, tzinfo=UTC)
    _hot_db(
        tmp_path / "data",
        "2026-07-09",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    excluded = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [((start + timedelta(days=1)).timestamp(), "i", "T", 2.0, "K", "ok")],
    )
    connection = sqlite3.connect(excluded)
    connection.execute(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
        ("2026-07-10T00:00:00+00:00", "i", "T", 3.0, "K", "ok"),
    )
    connection.commit()
    connection.close()
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(days=1),
    )
    assert result.complete is True
    assert [row.value for row in result.rows] == [1.0]


def test_parquet_reader_uses_projected_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        [(start, "i", "T", 1.0, "K", "ok")],
    )
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: pytest.fail("whole table read"))
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert result.complete is True
    assert result.rows[0].value == 1.0


def test_parquet_null_key_is_visible_partial_not_silently_filtered(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        [
            (None, "i", "T", 0.0, "K", "ok"),  # type: ignore[arg-type]
            (start, "i", "T", 1.0, "K", "ok"),
        ],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert result.complete is False
    assert [row.value for row in result.rows] == [1.0]
    assert BoundedReadIssueCode.INVALID_ROW in {issue.code for issue in result.issues}


def test_invalid_parquet_footer_is_rejected_before_table_read(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    target = archive / "year=2026" / "bad.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-parquet!")
    (archive / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": "data_2026-07-10.db",
                        "archive_path": "year=2026/bad.parquet",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
    )
    assert result.complete is False
    assert result.rows == ()
    assert BoundedReadIssueCode.PARQUET_METADATA in {issue.code for issue in result.issues}


def test_parquet_batch_byte_tripwire_stops_before_scalar_conversion(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    rows = [
        (
            start + timedelta(microseconds=index),
            "i" * 256,
            "T",
            float(index),
            "u" * 64,
            "ok",
        )
        for index in range(1_024)
    ]
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        rows,
        row_group_size=1_024,
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        batch_rows=1_024,
        max_arrow_batch_bytes=65_536,
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.PARQUET_BATCH_OVERSIZE in {issue.code for issue in result.issues}


def test_sqlite_length_limit_rejects_large_value_before_normalization(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    path = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
        (start.timestamp(), "x" * 1_048_577, "T", 2.0, "K", "ok"),
    )
    connection.commit()
    connection.close()
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert result.complete is False
    assert BoundedReadIssueCode.SQLITE_VALUE_OVERSIZE in {issue.code for issue in result.issues}


def test_sqlite_keyset_plan_has_no_temp_btree(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    path = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    connection = sqlite3.connect(path)
    plan = connection.execute(
        "EXPLAIN QUERY PLAN SELECT id,timestamp,instrument_id,channel,value,unit,status "
        "FROM readings WHERE typeof(timestamp) IN ('real','integer') "
        "AND timestamp >= ? AND timestamp < ? AND channel = ? "
        "ORDER BY timestamp DESC,id DESC LIMIT ?",
        (start.timestamp(), start.timestamp() + 1, "T", 64),
    ).fetchall()
    connection.execute("DROP INDEX idx_channel_ts")
    discovery_first = connection.execute(
        "EXPLAIN QUERY PLAN SELECT id,channel FROM readings NOT INDEXED "
        "WHERE typeof(timestamp) IN ('real','integer') "
        "AND timestamp >= ? AND timestamp < ? ORDER BY id LIMIT ?",
        (start.timestamp(), start.timestamp() + 1, 64),
    ).fetchall()
    discovery_next = connection.execute(
        "EXPLAIN QUERY PLAN SELECT id,channel FROM readings NOT INDEXED "
        "WHERE typeof(timestamp) IN ('real','integer') "
        "AND timestamp >= ? AND timestamp < ? AND id > ? ORDER BY id LIMIT ?",
        (start.timestamp(), start.timestamp() + 1, 0, 64),
    ).fetchall()
    connection.close()
    assert not any("USE TEMP B-TREE" in str(row).upper() for row in plan)
    assert not any("USE TEMP B-TREE" in str(row).upper() for row in (*discovery_first, *discovery_next))


@pytest.mark.parametrize(
    "change",
    [
        {"max_channels": True},
        {"batch_rows": 1},
        {"channels": ("T", "T")},
        {"deadline_monotonic": math.inf},
    ],
)
def test_invalid_arguments_reject_before_io(tmp_path: Path, change: dict[str, object]) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    reader = ArchiveReader(tmp_path / "missing-data", tmp_path / "missing-archive")
    with pytest.raises((TypeError, ValueError)):
        _query(reader, start, start + timedelta(seconds=1), **change)


def test_index_symlink_and_hardlink_are_rejected_before_read(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    authority = tmp_path / "authority.json"
    authority.write_text('{"files": []}', encoding="utf-8")
    (archive / "index.json").symlink_to(authority)
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert {issue.code for issue in result.issues} == {BoundedReadIssueCode.ARCHIVE_INDEX_INVALID}

    (archive / "index.json").unlink()
    (archive / "index.json").hardlink_to(authority)
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert {issue.code for issue in result.issues} == {BoundedReadIssueCode.ARCHIVE_INDEX_INVALID}


def test_index_same_size_mutation_during_fd_read_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    index = archive / "index.json"
    index.write_text('{"files": []}', encoding="utf-8")
    original_read = archive_reader_module.os.read
    mutated = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if not mutated:
            mutated = True
            index.write_text('{"files": {}}', encoding="utf-8")
        return chunk

    monkeypatch.setattr(archive_reader_module.os, "read", racing_read)
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert {issue.code for issue in result.issues} == {BoundedReadIssueCode.ARCHIVE_INDEX_INVALID}


def test_index_growth_during_fd_read_is_bounded_and_classified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    index = archive / "index.json"
    index.write_text('{"files": []}', encoding="utf-8")
    original_read = archive_reader_module.os.read
    grown = False

    def growing_read(descriptor: int, size: int) -> bytes:
        nonlocal grown
        chunk = original_read(descriptor, size)
        if not grown:
            grown = True
            with index.open("ab") as stream:
                stream.truncate(8 * 1024 * 1024 + 1)
        return chunk

    monkeypatch.setattr(archive_reader_module.os, "read", growing_read)
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert {issue.code for issue in result.issues} == {BoundedReadIssueCode.ARCHIVE_INDEX_OVERSIZE}


def test_rotation_index_publish_then_hot_unlink_cannot_return_false_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    hot = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    archive = tmp_path / "archive"
    _cold(
        archive,
        "2026-07-10",
        [(start, "i", "T", 1.0, "K", "ok")],
    )
    index = archive / "index.json"
    published = index.read_text(encoding="utf-8")
    index.write_text('{"files": []}', encoding="utf-8")
    original = ArchiveReader._read_bounded_index
    calls = 0

    def rotate_after_read(path: Path) -> object:
        nonlocal calls
        calls += 1
        document = original(path)
        if calls == 1:
            replacement = archive / "index.next"
            replacement.write_text(published, encoding="utf-8")
            replacement.replace(index)
            hot.unlink()
        return document

    monkeypatch.setattr(
        ArchiveReader,
        "_read_bounded_index",
        staticmethod(rotate_after_read),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.ARCHIVE_INDEX_INVALID in {issue.code for issue in result.issues}
