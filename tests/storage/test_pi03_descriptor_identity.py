from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from cryodaq.storage.archive_reader import ArchiveReader
from cryodaq.storage.parquet_archive import export_experiment_readings_to_parquet


def _db(path: Path, rows: list[tuple[float, str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE readings (timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT, descriptor_hash TEXT)"
    )
    connection.executemany(
        "INSERT INTO readings VALUES (?, ?, ?, 1.0, 'K', 'ok', ?)", rows
    )
    connection.commit()
    connection.close()


def test_query_rows_keeps_descriptor_identity_when_names_match(tmp_path: Path) -> None:
    day = datetime(2026, 8, 1, tzinfo=UTC)
    _db(
        tmp_path / "data_2026-08-01.db",
        [
            (day.timestamp(), "instrument", "renamed", "sha256:" + "1" * 64),
            (day.timestamp(), "instrument", "renamed", "sha256:" + "2" * 64),
        ],
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "index.json").write_text(json.dumps({"files": []}), encoding="utf-8")

    rows = ArchiveReader(tmp_path, archive).query_rows(day, day + timedelta(seconds=1), None)

    assert len(rows) == 2
    assert {row[6] for row in rows} == {"sha256:" + "1" * 64, "sha256:" + "2" * 64}


def test_export_includes_descriptor_hash_column(tmp_path: Path) -> None:
    day = datetime(2026, 8, 1, tzinfo=UTC)
    descriptor_hash = "sha256:" + "a" * 64
    _db(tmp_path / "data_2026-08-01.db", [(day.timestamp(), "instrument", "T", descriptor_hash)])

    output = tmp_path / "export.parquet"
    export_experiment_readings_to_parquet(
        experiment_id="experiment",
        start_time=day,
        end_time=day + timedelta(seconds=1),
        sqlite_root=tmp_path,
        output_path=output,
    )

    table = pq.read_table(output)
    assert "descriptor_hash" in table.column_names
    assert table.column("descriptor_hash").to_pylist() == [descriptor_hash]