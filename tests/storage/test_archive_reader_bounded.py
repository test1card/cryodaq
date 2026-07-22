from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import cryodaq.storage.archive_reader as archive_reader_module
from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader, BoundedReadIssueCode
from cryodaq.storage.channel_descriptors import initialize_descriptor_storage, install_catalog
from cryodaq.storage.descriptor_archive import (
    ArchivedDescriptor,
    DescriptorArchiveError,
    resolve_archived_descriptors,
)
from cryodaq.storage.sqlite_writer import SCHEMA_READINGS


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


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "T",
        "instrument_id": "i",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Cryostat",
        "display_name": "T",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 1,
    }
    values.update(changes)
    return ChannelDescriptorV1(**values)  # type: ignore[arg-type]


def _descriptor_cold(
    root: Path,
    day: str,
    start: datetime,
    descriptor: ChannelDescriptorV1 | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    descriptor = descriptor or _descriptor()
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
    relative = Path(f"year={day[:4]}") / f"data_{day}.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": pa.array([start], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([descriptor.instrument_id], type=pa.string()),
            "channel": pa.array([descriptor.channel_id], type=pa.string()),
            "value": pa.array([10.0], type=pa.float64()),
            "unit": pa.array([descriptor.unit], type=pa.string()),
            "status": pa.array(["ok"], type=pa.string()),
            "descriptor_hash": pa.array([descriptor.descriptor_hash], type=pa.string()),
        }
    )
    pq.write_table(table, path)
    sidecar_rel = relative.with_name(relative.stem + ".channel_descriptors.parquet")
    sidecar = root / sidecar_rel
    descriptor_table = pa.table(
        {
            "descriptor_hash": pa.array([descriptor.descriptor_hash], type=pa.string()),
            "channel_id": pa.array([descriptor.channel_id], type=pa.string()),
            "instrument_id": pa.array([descriptor.instrument_id], type=pa.string()),
            "source_key": pa.array([descriptor.source_key], type=pa.string()),
            "descriptor_revision": pa.array([descriptor.descriptor_revision], type=pa.int32()),
            "envelope_json": pa.array([envelope.canonical_json], type=pa.binary()),
        }
    )
    pq.write_table(descriptor_table, sidecar)
    entry: dict[str, object] = {
        "original_name": f"data_{day}.db",
        "archive_path": relative.as_posix(),
        "channel_descriptors_path": sidecar_rel.as_posix(),
        "channel_descriptors_rows": 1,
        "channel_descriptors_checksum": hashlib.md5(sidecar.read_bytes()).hexdigest(),
        "channel_descriptors_size_bytes": sidecar.stat().st_size,
    }
    (root / "index.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")
    return path, sidecar, entry


def _descriptor_hot(root: Path, day: str, start: datetime, descriptor: ChannelDescriptorV1) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"data_{day}.db"
    connection = sqlite3.connect(path)
    connection.execute(SCHEMA_READINGS)
    initialize_descriptor_storage(connection)
    install_catalog(connection, ChannelCatalog([descriptor]))
    connection.execute(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status,descriptor_hash) VALUES(?,?,?,?,?,?,?)",
        (
            start.timestamp(),
            descriptor.instrument_id,
            descriptor.channel_id,
            10.0,
            descriptor.unit,
            "ok",
            descriptor.descriptor_hash,
        ),
    )
    connection.commit()
    connection.close()
    return path


def _repeat_descriptor_readings(path: Path, start: datetime, count: int) -> None:
    parquet = pq.ParquetFile(path)
    original = parquet.read().to_pylist()[0]
    rows = []
    for index in range(count):
        row = dict(original)
        row["timestamp"] = start + timedelta(microseconds=index)
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows, schema=parquet.schema_arrow), path, row_group_size=1)


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


def test_duplicate_last_writer_authority_survives_hot_to_cold_rotation(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    hot_data = tmp_path / "hot" / "data"
    _hot_db(
        hot_data,
        "2026-07-10",
        [
            (start.timestamp(), "i", "T", 1.0, "K", "ok"),
            (start.timestamp(), "i", "T", 2.0, "K", "ok"),
        ],
    )
    hot = _query(
        ArchiveReader(hot_data, tmp_path / "hot" / "archive"),
        start,
        start + timedelta(seconds=1),
    )

    cold_archive = tmp_path / "cold" / "archive"
    _cold(
        cold_archive,
        "2026-07-10",
        [
            (start, "i", "T", 1.0, "K", "ok"),
            (start, "i", "T", 2.0, "K", "ok"),
        ],
    )
    cold = _query(
        ArchiveReader(tmp_path / "cold" / "data", cold_archive),
        start,
        start + timedelta(seconds=1),
    )

    assert hot.complete is True
    assert cold.complete is True
    assert [row.value for row in hot.rows] == [2.0]
    assert [row.value for row in cold.rows] == [2.0]


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


def test_index_symlink_is_rejected_before_read(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    authority = tmp_path / "authority.json"
    authority.write_text('{"files": []}', encoding="utf-8")
    try:
        (archive / "index.json").symlink_to(authority)
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip("Windows token cannot create symlinks")
        raise
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert {issue.code for issue in result.issues} == {BoundedReadIssueCode.ARCHIVE_INDEX_INVALID}


def test_index_hardlink_is_rejected_before_read(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    archive.mkdir()
    authority = tmp_path / "authority.json"
    authority.write_text('{"files": []}', encoding="utf-8")
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


@pytest.mark.skipif(archive_reader_module.os.name != "nt", reason="Windows stat contract")
def test_index_accepts_stable_windows_handle_ctime_distinct_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    index = archive / "index.json"
    index.write_text('{"files": []}', encoding="utf-8")
    path_ctime_ns = index.lstat().st_ctime_ns
    original_fstat = archive_reader_module.os.fstat

    class HandleStat:
        def __init__(self, source: os.stat_result) -> None:
            self._source = source
            self.st_ctime_ns = path_ctime_ns + 1

        def __getattr__(self, name: str) -> object:
            return getattr(self._source, name)

    def windows_fstat(descriptor: int) -> HandleStat:
        return HandleStat(original_fstat(descriptor))

    monkeypatch.setattr(archive_reader_module.os, "fstat", windows_fstat)

    assert ArchiveReader._read_bounded_index(index) == {"files": []}


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


def test_hot_and_cold_descriptor_resolution_are_value_equivalent(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor()
    _descriptor_hot(tmp_path / "hot", "2026-07-10", start, descriptor)
    _descriptor_cold(tmp_path / "cold", "2026-07-10", start, descriptor)
    hot = _query(ArchiveReader(tmp_path / "hot", tmp_path / "none"), start, start + timedelta(seconds=1))
    cold = _query(ArchiveReader(tmp_path / "none", tmp_path / "cold"), start, start + timedelta(seconds=1))
    assert hot.complete is True
    assert cold.complete is True
    assert hot.rows[0].descriptor == cold.rows[0].descriptor
    assert cold.rows[0].descriptor is not None
    assert (
        cold.rows[0].descriptor.envelope_json == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    )
    assert cold.rows[0].descriptor.grants_control_authority is False


def test_legacy_hot_and_cold_resolve_same_deterministic_unknown(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _hot_db(tmp_path / "hot", "2026-07-10", [(start.timestamp(), "i", "T", 1.0, "K", "ok")])
    _cold(tmp_path / "cold", "2026-07-10", [(start, "i", "T", 1.0, "K", "ok")])
    hot = _query(ArchiveReader(tmp_path / "hot", tmp_path / "none"), start, start + timedelta(seconds=1))
    cold = _query(ArchiveReader(tmp_path / "none", tmp_path / "cold"), start, start + timedelta(seconds=1))
    assert hot.rows[0].descriptor == cold.rows[0].descriptor
    assert hot.rows[0].descriptor is not None
    assert hot.rows[0].descriptor.legacy is True
    assert hot.rows[0].descriptor.quantity == "legacy_unknown"


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("missing", BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING),
        ("index", BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH),
        ("schema", BoundedReadIssueCode.DESCRIPTOR_SCHEMA_MISMATCH),
        ("oversized", BoundedReadIssueCode.DESCRIPTOR_OVERSIZED),
        ("envelope", BoundedReadIssueCode.DESCRIPTOR_ENVELOPE_CORRUPT),
        ("hash", BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING),
        ("reading", BoundedReadIssueCode.DESCRIPTOR_READING_MISMATCH),
    ],
)
def test_descriptor_corruption_matrix_never_downgrades_to_legacy(
    tmp_path: Path,
    fault: str,
    expected: BoundedReadIssueCode,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    readings, sidecar, entry = _descriptor_cold(archive, "2026-07-10", start)
    if fault == "missing":
        for key in tuple(entry):
            if key.startswith("channel_descriptors_"):
                del entry[key]
    elif fault == "index":
        entry["channel_descriptors_checksum"] = "0" * 32
    elif fault == "schema":
        table = pq.ParquetFile(sidecar).read().drop(["source_key"])
        pq.write_table(table, sidecar)
        entry["channel_descriptors_checksum"] = hashlib.md5(sidecar.read_bytes()).hexdigest()
        entry["channel_descriptors_size_bytes"] = sidecar.stat().st_size
    elif fault == "oversized":
        entry["channel_descriptors_size_bytes"] = 99 * 1024 * 1024
    elif fault == "envelope":
        table = pq.ParquetFile(sidecar).read()
        table = table.set_column(
            table.schema.get_field_index("envelope_json"),
            "envelope_json",
            pa.array([b"{}"], type=pa.binary()),
        )
        pq.write_table(table, sidecar)
        entry["channel_descriptors_checksum"] = hashlib.md5(sidecar.read_bytes()).hexdigest()
        entry["channel_descriptors_size_bytes"] = sidecar.stat().st_size
    elif fault == "hash":
        other = _descriptor(channel_id="U", source_key="input.2.temperature", display_name="U")
        envelope = PersistedChannelEnvelopeV1.from_descriptor(other)
        table = pa.table(
            {
                "descriptor_hash": pa.array([other.descriptor_hash], type=pa.string()),
                "channel_id": pa.array([other.channel_id], type=pa.string()),
                "instrument_id": pa.array([other.instrument_id], type=pa.string()),
                "source_key": pa.array([other.source_key], type=pa.string()),
                "descriptor_revision": pa.array([1], type=pa.int32()),
                "envelope_json": pa.array([envelope.canonical_json], type=pa.binary()),
            }
        )
        pq.write_table(table, sidecar)
        entry["channel_descriptors_checksum"] = hashlib.md5(sidecar.read_bytes()).hexdigest()
        entry["channel_descriptors_size_bytes"] = sidecar.stat().st_size
    else:
        table = pq.ParquetFile(readings).read()
        table = table.set_column(
            table.schema.get_field_index("unit"),
            "unit",
            pa.array(["°C"], type=pa.string()),
        )
        pq.write_table(table, readings)
    (archive / "index.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert result.rows == ()
    assert result.complete is False
    assert expected in {issue.code for issue in result.issues}


def test_hot_cold_dedup_never_splices_descriptor_from_losing_row(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor()
    _descriptor_cold(tmp_path / "archive", "2026-07-10", start, descriptor)
    _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 99.0, "K", "ok")],
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert len(result.rows) == 1
    assert result.rows[0].value == 10.0
    assert result.rows[0].descriptor is not None
    assert result.rows[0].descriptor.descriptor_hash == descriptor.descriptor_hash
    assert result.rows[0].descriptor.legacy is False


def test_descriptor_envelope_bytes_count_toward_retained_cap(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    readings, _sidecar, _entry = _descriptor_cold(tmp_path / "archive", "2026-07-10", start)
    original = pq.ParquetFile(readings).read().to_pylist()[0]
    rows = []
    for index in range(120):
        row = dict(original)
        row["timestamp"] = start + timedelta(microseconds=index)
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows, schema=pq.ParquetFile(readings).schema_arrow), readings)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        max_points_per_channel=200,
        max_total_points=200,
        max_retained_bytes=65_536,
    )
    assert result.truncated is True
    assert 0 < len(result.rows) < 120
    assert result.retained_encoded_bytes <= 65_536


def test_descriptor_reference_cardinality_is_bounded_before_sidecar_read(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    relative = Path("year=2026/data_2026-07-10.parquet")
    path = archive / relative
    path.parent.mkdir(parents=True)
    count = 4097
    table = pa.table(
        {
            "timestamp": pa.array([start] * count, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["i"] * count),
            "channel": pa.array(["T"] * count),
            "value": pa.array([1.0] * count),
            "unit": pa.array(["K"] * count),
            "status": pa.array(["ok"] * count),
            "descriptor_hash": pa.array([f"sha256:{index:064x}" for index in range(count)]),
        }
    )
    pq.write_table(table, path)
    (archive / "index.json").write_text(
        json.dumps({"files": [{"original_name": "data_2026-07-10.db", "archive_path": relative.as_posix()}]}),
        encoding="utf-8",
    )
    result = _query(ArchiveReader(tmp_path / "data", archive), start, start + timedelta(seconds=1))
    assert result.rows == ()
    assert BoundedReadIssueCode.DESCRIPTOR_OVERSIZED in {issue.code for issue in result.issues}


def test_hot_descriptor_hash_without_catalog_reports_catalog_missing(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    path = _hot_db(
        tmp_path / "data",
        "2026-07-10",
        [(start.timestamp(), "i", "T", 1.0, "K", "ok")],
    )
    connection = sqlite3.connect(path)
    connection.execute("ALTER TABLE readings ADD COLUMN descriptor_hash TEXT")
    connection.execute("UPDATE readings SET descriptor_hash=?", ("sha256:" + "0" * 64,))
    connection.commit()
    connection.close()
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
    )
    assert result.rows == ()
    assert BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING in {issue.code for issue in result.issues}


def test_compressed_sidecar_bomb_is_rejected_from_metadata_before_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _readings, sidecar, entry = _descriptor_cold(archive, "2026-07-10", start)
    descriptor = _descriptor()
    huge = b"0" * (36 * 1024 * 1024)
    table = pa.table(
        {
            "descriptor_hash": pa.array([descriptor.descriptor_hash], type=pa.string()),
            "channel_id": pa.array([descriptor.channel_id], type=pa.string()),
            "instrument_id": pa.array([descriptor.instrument_id], type=pa.string()),
            "source_key": pa.array([descriptor.source_key], type=pa.string()),
            "descriptor_revision": pa.array([1], type=pa.int32()),
            "envelope_json": pa.array([huge], type=pa.binary()),
        }
    )
    pq.write_table(table, sidecar, compression="zstd")
    entry["channel_descriptors_checksum"] = hashlib.md5(sidecar.read_bytes()).hexdigest()
    entry["channel_descriptors_size_bytes"] = sidecar.stat().st_size
    (archive / "index.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")
    monkeypatch.setattr(
        ArchiveReader,
        "_read_descriptor_row_group",
        staticmethod(lambda *_: pytest.fail("oversized sidecar decoded before metadata rejection")),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
    )
    assert result.rows == ()
    assert BoundedReadIssueCode.DESCRIPTOR_OVERSIZED in {issue.code for issue in result.issues}


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits renaming an open inode")
def test_sidecar_replace_read_restore_cannot_change_opened_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _readings, sidecar, _entry = _descriptor_cold(archive, "2026-07-10", start)
    saved = sidecar.with_suffix(".saved")
    real_hash = ArchiveReader._hash_open_file
    calls = 0

    def replace_around_hash(descriptor: int, *, deadline_monotonic: float) -> str:
        nonlocal calls
        calls += 1
        result = real_hash(descriptor, deadline_monotonic=deadline_monotonic)
        if calls == 1:
            sidecar.replace(saved)
            sidecar.write_bytes(b"attacker replacement")
        elif calls == 2:
            sidecar.unlink()
            saved.replace(sidecar)
        return result

    monkeypatch.setattr(ArchiveReader, "_hash_open_file", staticmethod(replace_around_hash))
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
    )
    assert result.complete is True
    assert len(result.rows) == 1
    assert calls == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows denies replacing an open file")
def test_sidecar_open_handle_blocks_replacement_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _readings, sidecar, _entry = _descriptor_cold(archive, "2026-07-10", start)
    saved = sidecar.with_suffix(".saved")
    real_hash = ArchiveReader._hash_open_file
    calls = 0
    blocked: list[int | None] = []

    def attempt_replace_during_hash(descriptor: int, *, deadline_monotonic: float) -> str:
        nonlocal calls
        calls += 1
        result = real_hash(descriptor, deadline_monotonic=deadline_monotonic)
        if calls == 1:
            try:
                sidecar.replace(saved)
            except PermissionError as exc:
                blocked.append(exc.winerror)
            else:
                pytest.fail("Windows replaced an open descriptor authority")
        return result

    monkeypatch.setattr(ArchiveReader, "_hash_open_file", staticmethod(attempt_replace_during_hash))
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
    )

    assert result.complete is True
    assert len(result.rows) == 1
    assert result.issues == ()
    assert calls == 2
    assert blocked == [32]
    assert sidecar.is_file()
    assert saved.exists() is False


def test_slow_sidecar_hash_observes_bounded_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _descriptor_cold(archive, "2026-07-10", start)
    real_hash = ArchiveReader._hash_open_file
    calls = 0

    def slow_hash(descriptor: int, *, deadline_monotonic: float) -> str:
        nonlocal calls
        calls += 1
        result = real_hash(descriptor, deadline_monotonic=deadline_monotonic)
        if calls == 1:
            time.sleep(0.02)
        return result

    monkeypatch.setattr(ArchiveReader, "_hash_open_file", staticmethod(slow_hash))
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=time.monotonic() + 0.01,
    )
    assert result.rows == ()
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_slow_sidecar_decode_observes_bounded_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _descriptor_cold(archive, "2026-07-10", start)
    real_read = ArchiveReader._read_descriptor_row_group

    def slow_read(parquet: object, group_index: int) -> object:
        table = real_read(parquet, group_index)
        time.sleep(0.02)
        return table

    monkeypatch.setattr(
        ArchiveReader,
        "_read_descriptor_row_group",
        staticmethod(slow_read),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=time.monotonic() + 0.01,
    )
    assert result.rows == ()
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_slow_multibatch_readings_reference_scan_stops_at_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    readings, _sidecar, _entry = _descriptor_cold(archive, "2026-07-10", start)
    _repeat_descriptor_readings(readings, start, 128)
    real_next = ArchiveReader._next_descriptor_reference_batch
    calls = 0
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])

    def slow_second_pull(iterator: object) -> object:
        nonlocal calls
        calls += 1
        batch = real_next(iterator)
        if calls == 2:
            clock[0] = 2.0
        return batch

    monkeypatch.setattr(
        ArchiveReader,
        "_next_descriptor_reference_batch",
        staticmethod(slow_second_pull),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        batch_rows=64,
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert calls == 2
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_slow_readings_reference_scalar_decode_stops_at_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    readings, _sidecar, _entry = _descriptor_cold(archive, "2026-07-10", start)
    _repeat_descriptor_readings(readings, start, 64)
    real_value = ArchiveReader._descriptor_reference_value
    calls = 0
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])

    def slow_second_value(scalar: object) -> object:
        nonlocal calls
        calls += 1
        value = real_value(scalar)
        if calls == 2:
            clock[0] = 2.0
        return value

    monkeypatch.setattr(
        ArchiveReader,
        "_descriptor_reference_value",
        staticmethod(slow_second_value),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        batch_rows=64,
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert calls == 2
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_reference_scan_exhaustion_deadline_blocks_sidecar_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _descriptor_cold(archive, "2026-07-10", start)
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_next = ArchiveReader._next_descriptor_reference_batch

    def expire_on_exhaustion(iterator: object) -> object:
        try:
            return real_next(iterator)
        except StopIteration:
            clock[0] = 2.0
            raise

    opens: list[float] = []
    real_open = ArchiveReader._open_descriptor_file

    def record_open(path: Path, flags: int) -> int:
        opens.append(clock[0])
        return real_open(path, flags)

    monkeypatch.setattr(
        ArchiveReader,
        "_next_descriptor_reference_batch",
        staticmethod(expire_on_exhaustion),
    )
    monkeypatch.setattr(ArchiveReader, "_open_descriptor_file", staticmethod(record_open))
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert opens == []
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_sidecar_metadata_group_deadline_stops_before_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    archive = tmp_path / "archive"
    _descriptor_cold(archive, "2026-07-10", start)
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_group = ArchiveReader._descriptor_metadata_group
    calls = 0

    def expire_after_group(metadata: object, group_index: int) -> object:
        nonlocal calls
        calls += 1
        group = real_group(metadata, group_index)
        clock[0] = 2.0
        return group

    monkeypatch.setattr(
        ArchiveReader,
        "_descriptor_metadata_group",
        staticmethod(expire_after_group),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", archive),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert calls == 1
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_deadline_crossed_during_first_row_text_decode_emits_no_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(tmp_path / "archive", "2026-07-10", [(start, "i", "T", 1.0, "K", "ok")])
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_text = archive_reader_module._bounded_text
    calls = 0

    def expire_during_text(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        value = real_text(*args, **kwargs)
        if calls == 1:
            clock[0] = 2.0
        return value

    monkeypatch.setattr(archive_reader_module, "_bounded_text", expire_during_text)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert result.complete is False
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_deadline_crossed_by_collector_discards_only_post_deadline_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        [
            (start, "i", "T", 1.0, "K", "ok"),
            (start + timedelta(microseconds=1), "i", "T", 2.0, "K", "ok"),
        ],
    )
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_offer = ArchiveReader._offer_bounded_collector
    calls = 0

    def expire_on_second(collector: object, **values: object) -> None:
        nonlocal calls
        calls += 1
        real_offer(collector, **values)
        if calls == 2:
            clock[0] = 2.0

    monkeypatch.setattr(
        ArchiveReader,
        "_offer_bounded_collector",
        staticmethod(expire_on_second),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert [row.value for row in result.rows] == [1.0]
    assert result.complete is False
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_deadline_crossed_during_descriptor_resolution_keeps_prior_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(
        tmp_path / "archive",
        "2026-07-10",
        [
            (start, "i", "T", 1.0, "K", "ok"),
            (start + timedelta(microseconds=1), "i", "T", 2.0, "K", "ok"),
        ],
    )
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_resolve = archive_reader_module.resolve_legacy_descriptor
    calls = 0

    def expire_on_second(*args: object) -> object:
        nonlocal calls
        calls += 1
        value = real_resolve(*args)
        if calls == 2:
            clock[0] = 2.0
        return value

    monkeypatch.setattr(archive_reader_module, "resolve_legacy_descriptor", expire_on_second)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert [row.value for row in result.rows] == [1.0]
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_final_batch_exhaustion_and_metadata_observe_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(tmp_path / "archive", "2026-07-10", [(start, "i", "T", 1.0, "K", "ok")])
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_next = ArchiveReader._next_bounded_parquet_batch

    def expire_on_exhaustion(iterator: object) -> object:
        try:
            return real_next(iterator)
        except StopIteration:
            clock[0] = 2.0
            raise

    monkeypatch.setattr(
        ArchiveReader,
        "_next_bounded_parquet_batch",
        staticmethod(expire_on_exhaustion),
    )
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert [row.value for row in result.rows] == [1.0]
    assert result.complete is False
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_parquet_row_group_metadata_iteration_observes_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _cold(tmp_path / "archive", "2026-07-10", [(start, "i", "T", 1.0, "K", "ok")])
    clock = [0.0]
    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    real_epoch = archive_reader_module._epoch_microseconds
    calls = 0

    def expire_in_metadata(value: datetime) -> int:
        nonlocal calls
        calls += 1
        result = real_epoch(value)
        if calls == 1:
            clock[0] = 2.0
        return result

    monkeypatch.setattr(archive_reader_module, "_epoch_microseconds", expire_in_metadata)
    result = _query(
        ArchiveReader(tmp_path / "data", tmp_path / "archive"),
        start,
        start + timedelta(seconds=1),
        deadline_monotonic=1.0,
    )
    assert result.rows == ()
    assert BoundedReadIssueCode.DEADLINE in {issue.code for issue in result.issues}


def test_descriptor_adapter_stops_generator_at_row_and_byte_caps() -> None:
    row = ArchivedDescriptor("h", "c", "i", "input.1", 1, b"{}")
    consumed = 0

    def too_many():
        nonlocal consumed
        for _ in range(100_000):
            consumed += 1
            yield row

    with pytest.raises(DescriptorArchiveError, match="row count"):
        resolve_archived_descriptors(too_many(), {"h"})
    assert consumed == 4097

    consumed = 0

    def too_large():
        nonlocal consumed
        consumed += 1
        yield ArchivedDescriptor("h", "c", "i", "input.1", 1, b"0" * 8193)
        consumed += 1
        yield row

    with pytest.raises(DescriptorArchiveError, match="byte bound"):
        resolve_archived_descriptors(too_large(), {"h"})
    assert consumed == 1
