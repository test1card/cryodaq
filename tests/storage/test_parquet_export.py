"""Tests for Parquet experiment archive export (Phase 2e stage 1)."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.storage.parquet_archive import (  # noqa: E402
    ParquetExportResult,
    export_experiment_readings_to_parquet,
    read_experiment_parquet,
)
from cryodaq.storage.sentinel import SENTINEL  # noqa: E402


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


def test_export_masks_nonfinite(tmp_path: Path) -> None:
    """NaN-доктрина: non-finite values (legacy ±inf / sentinel) are masked to NaN
    in the exported parquet — the row survives (status discriminates) but the
    value column never carries a non-physical number downstream."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_test_db(
        db_path,
        [
            (base_ts, "ls218s", "Т7", float("inf"), "K", "overrange"),
            (base_ts + 1, "ls218s", "Т8", float("-inf"), "K", "underrange"),
            (base_ts + 2, "ls218s", "Т9", SENTINEL, "K", "sensor_error"),
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

    assert result.rows_written == 3, "rows persist — status is the discriminator"
    table = pq.read_table(str(output))
    values = table.column("value").to_pylist()
    assert all(math.isnan(v) for v in values), f"non-finite leaked into parquet: {values}"
    # status column still distinguishes the error kinds
    assert table.column("status").to_pylist() == ["overrange", "underrange", "sensor_error"]


def test_read_experiment_parquet_masks_legacy_inf(tmp_path: Path) -> None:
    """The reader masks legacy raw-inf parquet rows (files written pre-doctrine)."""
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    schema = pa.schema(
        [
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("instrument_id", pa.string()),
            ("channel", pa.string()),
            ("value", pa.float64()),
            ("unit", pa.string()),
            ("status", pa.string()),
            ("experiment_id", pa.string()),
        ]
    )
    table = pa.table(
        {
            "timestamp": pa.array(
                [datetime.fromtimestamp(base_ts + i, tz=UTC) for i in range(2)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "instrument_id": pa.array(["ls218s", "ls218s"]),
            "channel": pa.array(["Т1", "Т1"]),
            "value": pa.array([77.0, float("inf")], type=pa.float64()),
            "unit": pa.array(["K", "K"]),
            "status": pa.array(["ok", "overrange"]),
            "experiment_id": pa.array(["e", "e"]),
        },
        schema=schema,
    )
    parquet_path = tmp_path / "legacy.parquet"
    pq.write_table(table, str(parquet_path))

    result = read_experiment_parquet(parquet_path)
    vals = [v for _, v in result["Т1"]]
    assert 77.0 in vals
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals)
    assert any(math.isnan(v) for v in vals), "legacy inf must mask to NaN on read"


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


def test_export_reads_rotated_cold_day(tmp_path: Path) -> None:
    """A rotated day's data lives in cold Parquet, not a daily DB. The bulk
    exporter must read it from the archive instead of dropping the day into
    skipped_days. Cold rows carry no experiment_id → null, reported separately.
    """
    import asyncio

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)

    async def _seed_and_rotate() -> None:
        writer = SQLiteWriter(tmp_path)
        writer._write_batch(
            [
                Reading(
                    timestamp=day + timedelta(seconds=i),
                    instrument_id="ls218s",
                    channel="Т1",
                    value=77.0 + i,
                    unit="K",
                    status=ChannelStatus.OK,
                )
                for i in range(5)
            ]
        )
        await writer.stop()
        service = ColdRotationService(
            data_dir=tmp_path, archive_dir=tmp_path / "archive", age_days=30
        )
        results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert results, "old day must have rotated to Parquet"

    asyncio.run(_seed_and_rotate())
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    output = tmp_path / "out" / "readings.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="exp-cold",
        start_time=day.replace(hour=0, minute=0, second=0),
        end_time=day.replace(hour=23, minute=59, second=59),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert result.rows_written == 5, "rotated cold-day rows must be exported, not skipped"
    assert "2026-04-14" not in result.skipped_days, "day has data in cold archive"
    assert "2026-04-14" in result.archived_days, "cold-sourced day must be reported"

    table = pq.read_table(str(output))
    assert table.num_rows == 5
    exp_ids = table.column("experiment_id").to_pylist()
    assert exp_ids == [None] * 5, f"cold rows carry no experiment_id: {exp_ids}"
    channels = table.column("channel").to_pylist()
    assert channels == ["Т1"] * 5


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
    assert len(exp_ids) == 5, f"Expected 5 rows, got {len(exp_ids)}"
    assert exp_ids == ["my-exp-42"] * 5, f"experiment_id column mismatch: {exp_ids}"
