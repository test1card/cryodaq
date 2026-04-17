"""Tests for Parquet experiment archive export (Phase 2e stage 1)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.storage.parquet_archive import (  # noqa: E402
    ParquetExportResult,
    export_experiment_readings_to_parquet,
)


def _create_test_db(db_path: Path, readings: list[tuple]) -> None:
    """Create a minimal SQLite DB with readings table."""
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


def _make_readings(
    n: int,
    base_ts: float,
    channel: str = "Т1 Криостат верх",
) -> list[tuple]:
    return [(base_ts + i, "ls218s", channel, 77.0 + i * 0.01, "K", "ok") for i in range(n)]


def test_export_basic_success(tmp_path: Path) -> None:
    """Basic: 100 readings → parquet file with 100 rows."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(db_path, _make_readings(100, base_ts))

    output = tmp_path / "out" / "readings.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="exp-001",
        start_time=day,
        end_time=day + timedelta(hours=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert isinstance(result, ParquetExportResult)
    assert result.rows_written == 100
    assert result.output_path == output
    assert output.exists()
    assert result.file_size_bytes > 0


def test_export_preserves_timestamps(tmp_path: Path) -> None:
    """Timestamps round-trip through parquet with microsecond precision."""
    day = datetime(2026, 4, 14, 10, 30, 15, 123456, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(db_path, [(base_ts, "ls218s", "Т1", 77.0, "K", "ok")])

    output = tmp_path / "readings.parquet"
    export_experiment_readings_to_parquet(
        experiment_id="exp-ts",
        start_time=day - timedelta(seconds=1),
        end_time=day + timedelta(seconds=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    table = pq.read_table(str(output))
    ts_val = table.column("timestamp")[0].as_py()
    assert abs(ts_val.timestamp() - base_ts) < 0.001


def test_export_handles_overrange_inf(tmp_path: Path) -> None:
    """±inf from OVERRANGE/UNDERRANGE persists through parquet."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(
        db_path,
        [
            (base_ts, "ls218s", "Т7", float("inf"), "K", "overrange"),
            (base_ts + 1, "ls218s", "Т8", float("-inf"), "K", "underrange"),
        ],
    )

    output = tmp_path / "readings.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="exp-inf",
        start_time=day,
        end_time=day + timedelta(hours=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert result.rows_written == 2
    table = pq.read_table(str(output))
    values = table.column("value").to_pylist()
    assert values[0] == float("inf")
    assert values[1] == float("-inf")


def test_export_respects_time_range(tmp_path: Path) -> None:
    """Only readings within [start, end] are exported."""
    day1 = datetime(2026, 4, 13, tzinfo=UTC)
    day2 = datetime(2026, 4, 14, tzinfo=UTC)
    day3 = datetime(2026, 4, 15, tzinfo=UTC)

    for d, n in [(day1, 10), (day2, 20), (day3, 10)]:
        db = tmp_path / f"data_{d.date().isoformat()}.db"
        _create_test_db(db, _make_readings(n, d.timestamp()))

    output = tmp_path / "readings.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="exp-range",
        start_time=day2,
        end_time=day2 + timedelta(hours=23, minutes=59, seconds=59),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert result.rows_written == 20


def test_export_chunking(tmp_path: Path) -> None:
    """More rows than chunk_size → all still exported."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(db_path, _make_readings(500, base_ts))

    output = tmp_path / "readings.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="exp-chunk",
        start_time=day,
        end_time=day + timedelta(hours=1),
        sqlite_root=tmp_path,
        output_path=output,
        chunk_size=100,
    )

    assert result.rows_written == 500


def test_export_missing_day_handled(tmp_path: Path) -> None:
    """Missing day file → skipped_days, no exception."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    output = tmp_path / "readings.parquet"

    result = export_experiment_readings_to_parquet(
        experiment_id="exp-missing",
        start_time=day,
        end_time=day + timedelta(hours=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert result.rows_written == 0
    assert "2026-04-14" in result.skipped_days


def test_export_experiment_id_column(tmp_path: Path) -> None:
    """Every row has experiment_id column populated."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(db_path, _make_readings(5, day.timestamp()))

    output = tmp_path / "readings.parquet"
    export_experiment_readings_to_parquet(
        experiment_id="my-exp-42",
        start_time=day,
        end_time=day + timedelta(hours=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    table = pq.read_table(str(output))
    exp_ids = table.column("experiment_id").to_pylist()
    assert all(eid == "my-exp-42" for eid in exp_ids)
