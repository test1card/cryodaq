"""Tests for ArchiveReader — unified SQLite + Parquet query (F17)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.storage.archive_reader import ArchiveReader  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sqlite_db(db_path: Path, readings: list[tuple]) -> None:
    """Create minimal SQLite DB with readings."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS readings ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp REAL NOT NULL,"
        "  instrument_id TEXT NOT NULL,"
        "  channel TEXT NOT NULL,"
        "  value REAL NOT NULL,"
        "  unit TEXT NOT NULL,"
        "  status TEXT NOT NULL"
        ")"
    )
    conn.executemany(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        readings,
    )
    conn.commit()
    conn.close()


def _create_parquet(parquet_path: Path, readings: list[tuple]) -> None:
    """Create Parquet with cold-rotation schema (no experiment_id)."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("instrument_id", pa.string()),
            ("channel", pa.string()),
            ("value", pa.float64()),
            ("unit", pa.string()),
            ("status", pa.string()),
        ]
    )
    timestamps, instruments, channels, values, units, statuses = [], [], [], [], [], []
    for ts_epoch, inst, ch, val, unit, status in readings:
        timestamps.append(datetime.fromtimestamp(ts_epoch, tz=UTC))
        instruments.append(inst)
        channels.append(ch)
        values.append(float(val))
        units.append(unit)
        statuses.append(status)

    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(instruments),
            "channel": pa.array(channels),
            "value": pa.array(values, type=pa.float64()),
            "unit": pa.array(units),
            "status": pa.array(statuses),
        },
        schema=schema,
    )
    pq.write_table(table, str(parquet_path), compression="zstd")


def _write_index(archive_dir: Path, entries: list[dict]) -> None:
    """Write archive index.json."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "index.json").write_text(
        json.dumps({"files": entries}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# test_query_archived_uses_parquet
# ---------------------------------------------------------------------------


def test_query_archived_uses_parquet(tmp_path: Path) -> None:
    """When a file is in the archive index, reads come from Parquet."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    day = datetime(2026, 3, 15, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    # Parquet archive for that day
    rel_path = f"year=2026/month=03/{db_name}.parquet"
    parquet_path = archive_dir / rel_path
    readings = [
        (base_ts + i, "ls218s", "Т1", 77.0 + i * 0.1, "K", "ok") for i in range(10)
    ]
    _create_parquet(parquet_path, readings)

    _write_index(
        archive_dir,
        [
            {
                "original_name": db_name,
                "archive_path": rel_path,
                "rotated_at": "2026-04-15T03:00:00+00:00",
                "row_count": 10,
                "size_bytes_original": 1000,
                "size_bytes_archive": 200,
                "checksum_md5": "abc123" + "0" * 26,
            }
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т1"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert len(result["Т1"]) == 10
    # Verify sorted by time
    ts_list = [t for t, _ in result["Т1"]]
    assert ts_list == sorted(ts_list)


# ---------------------------------------------------------------------------
# test_query_recent_uses_sqlite
# ---------------------------------------------------------------------------


def test_query_recent_uses_sqlite(tmp_path: Path) -> None:
    """Files not in archive index are read directly from SQLite."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 28, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    readings = [
        (base_ts + i, "ls218s", "Т2", 80.0 + i * 0.05, "K", "ok") for i in range(15)
    ]
    _create_sqlite_db(data_dir / db_name, readings)

    # Empty index — no archived files
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т2"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т2" in result
    assert len(result["Т2"]) == 15


# ---------------------------------------------------------------------------
# test_missing_archive_file_returns_partial
# ---------------------------------------------------------------------------


def test_missing_archive_file_returns_partial(tmp_path: Path) -> None:
    """If indexed Parquet file is missing on disk, gracefully skip it."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    day1 = datetime(2026, 3, 10, tzinfo=UTC)
    day2 = datetime(2026, 3, 11, tzinfo=UTC)

    # day1 in index but Parquet file missing
    rel1 = f"year=2026/month=03/data_{day1.date().isoformat()}.db.parquet"
    # day2 has valid Parquet
    rel2 = f"year=2026/month=03/data_{day2.date().isoformat()}.db.parquet"
    parquet2 = archive_dir / rel2
    readings2 = [
        (day2.timestamp() + i, "ls218s", "Т3", 90.0 + i, "K", "ok") for i in range(5)
    ]
    _create_parquet(parquet2, readings2)

    _write_index(
        archive_dir,
        [
            {
                "original_name": f"data_{day1.date().isoformat()}.db",
                "archive_path": rel1,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 100,
                "size_bytes_original": 5000,
                "size_bytes_archive": 1000,
                "checksum_md5": "aabbcc" + "0" * 26,
            },
            {
                "original_name": f"data_{day2.date().isoformat()}.db",
                "archive_path": rel2,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 5,
                "size_bytes_original": 500,
                "size_bytes_archive": 100,
                "checksum_md5": "ddeeff" + "0" * 26,
            },
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    # Query spanning both days
    result = reader.query(
        channels=["Т3"],
        from_ts=day1,
        to_ts=day2 + timedelta(hours=1),
    )

    # day2 data present; day1 gracefully skipped (no exception)
    assert "Т3" in result
    assert len(result["Т3"]) == 5


# ---------------------------------------------------------------------------
# test_query_merges_sqlite_and_parquet
# ---------------------------------------------------------------------------


def test_query_merges_sqlite_and_parquet(tmp_path: Path) -> None:
    """Results from archived Parquet and recent SQLite are merged in time order."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    # Old day — archived
    old_day = datetime(2026, 3, 1, tzinfo=UTC)
    old_db_name = f"data_{old_day.date().isoformat()}.db"
    rel_old = f"year=2026/month=03/{old_db_name}.parquet"
    parquet_old = archive_dir / rel_old
    old_readings = [
        (old_day.timestamp() + i, "ls218s", "Т4", 70.0 + i, "K", "ok") for i in range(5)
    ]
    _create_parquet(parquet_old, old_readings)

    # Recent day — SQLite
    recent_day = datetime(2026, 4, 28, tzinfo=UTC)
    recent_db_name = f"data_{recent_day.date().isoformat()}.db"
    recent_readings = [
        (recent_day.timestamp() + i, "ls218s", "Т4", 85.0 + i, "K", "ok") for i in range(3)
    ]
    _create_sqlite_db(data_dir / recent_db_name, recent_readings)

    _write_index(
        archive_dir,
        [
            {
                "original_name": old_db_name,
                "archive_path": rel_old,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 5,
                "size_bytes_original": 500,
                "size_bytes_archive": 100,
                "checksum_md5": "112233" + "0" * 26,
            }
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т4"],
        from_ts=old_day,
        to_ts=recent_day + timedelta(hours=1),
    )

    assert "Т4" in result
    all_points = result["Т4"]
    assert len(all_points) == 8  # 5 old + 3 recent
    # Verify time-sorted
    ts_list = [t for t, _ in all_points]
    assert ts_list == sorted(ts_list)


# ---------------------------------------------------------------------------
# test_query_channel_filter
# ---------------------------------------------------------------------------


def test_query_channel_filter(tmp_path: Path) -> None:
    """channels= filter is respected; other channels excluded from result."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 20, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    # Two channels
    readings = [
        (base_ts + i, "ls218s", "Т1", 77.0, "K", "ok") for i in range(5)
    ] + [
        (base_ts + i, "ls218s", "Т2", 80.0, "K", "ok") for i in range(5)
    ]
    _create_sqlite_db(data_dir / db_name, readings)
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т1"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert "Т2" not in result
    assert len(result["Т1"]) == 5


# ---------------------------------------------------------------------------
# test_query_no_channels_filter_returns_all
# ---------------------------------------------------------------------------


def test_query_no_channels_filter_returns_all(tmp_path: Path) -> None:
    """channels=None returns all channels from SQLite."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 20, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    readings = [
        (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
        (base_ts + 1, "ls218s", "Т2", 80.0, "K", "ok"),
        (base_ts + 2, "ls218s", "Т3", 85.0, "K", "ok"),
    ]
    _create_sqlite_db(data_dir / db_name, readings)
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=None,
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert "Т2" in result
    assert "Т3" in result
