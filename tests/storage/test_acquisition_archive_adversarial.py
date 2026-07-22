from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.parquet_archive import export_experiment_readings_to_parquet


def _write_day(root: Path, day: str, timestamp: float, value: float) -> None:
    db_path = root / f"data_{day}.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE readings ("
            "timestamp REAL NOT NULL, instrument_id TEXT NOT NULL, channel TEXT NOT NULL, "
            "value REAL NOT NULL, unit TEXT NOT NULL, status TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, "instrument-1", "temperature", value, "K", "ok"),
        )
        conn.commit()


def test_parquet_export_failure_preserves_previous_file_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = datetime(2026, 7, 17, 12, tzinfo=UTC)
    second = datetime(2026, 7, 18, 12, tzinfo=UTC)
    _write_day(tmp_path, "2026-07-17", first.timestamp(), 4.2)
    _write_day(tmp_path, "2026-07-18", second.timestamp(), 4.3)
    output = tmp_path / "experiment" / "readings.parquet"
    output.parent.mkdir()
    output.write_bytes(b"previous trusted artifact")
    real_writer = pq.ParquetWriter

    class FailingWriter:
        def __init__(self, *args, **kwargs) -> None:
            self._inner = real_writer(*args, **kwargs)
            self._writes = 0

        def write_table(self, table) -> None:
            self._writes += 1
            if self._writes == 2:
                raise OSError("injected second-day failure")
            self._inner.write_table(table)

        def close(self) -> None:
            self._inner.close()

    monkeypatch.setattr(pq, "ParquetWriter", FailingWriter)
    with pytest.raises(OSError, match="second-day failure"):
        export_experiment_readings_to_parquet(
            "exp-1",
            first,
            second,
            tmp_path,
            output,
        )

    assert output.read_bytes() == b"previous trusted artifact"
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_parquet_export_publishes_only_verified_complete_metadata(tmp_path: Path) -> None:
    first = datetime(2026, 7, 17, 12, tzinfo=UTC)
    second = datetime(2026, 7, 18, 12, tzinfo=UTC)
    _write_day(tmp_path, "2026-07-17", first.timestamp(), 4.2)
    _write_day(tmp_path, "2026-07-18", second.timestamp(), 4.3)
    output = tmp_path / "experiment" / "readings.parquet"

    result = export_experiment_readings_to_parquet(
        "exp-1",
        first,
        second,
        tmp_path,
        output,
    )

    assert result.rows_written == 2
    assert pq.read_metadata(str(output)).num_rows == 2
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []
