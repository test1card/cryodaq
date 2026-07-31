from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import cryodaq.storage.archive_reader as archive_reader_module  # noqa: E402
from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.storage.archive_reader import (  # noqa: E402
    ArchiveReader,
    ArchiveUnavailableError,
    BoundedReadIssueCode,
)
from cryodaq.storage.cold_rotation import ColdRotationService  # noqa: E402
from cryodaq.storage.sqlite_writer import SQLiteWriter  # noqa: E402


def _write_index(archive_dir: Path, entries: list[dict[str, object]]) -> None:
    (archive_dir / "index.json").write_text(
        json.dumps({"files": entries}, separators=(",", ":")),
        encoding="utf-8",
    )


def _rotate_days(
    data_dir: Path,
    rows: list[tuple[datetime, float]],
) -> tuple[Path, list[dict[str, object]]]:
    archive_dir = data_dir / "archive"

    async def rotate() -> None:
        writer = SQLiteWriter(data_dir)
        for at, value in rows:
            writer._write_batch([Reading(at, "ls", "T", value, "K", ChannelStatus.OK)])
            writer._write_operator_log_entry(
                timestamp=at,
                experiment_id="exp",
                author="operator",
                source="gui",
                message=f"entry-{value:g}",
                tags=(),
            )
        await writer.stop()
        service = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
        results = await service.run_once(now=max(at for at, _value in rows) + timedelta(days=60))
        assert len(results) == len(rows)

    asyncio.run(rotate())
    document = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    entries = document["files"]
    assert isinstance(entries, list)
    assert all(isinstance(entry, dict) for entry in entries)
    return archive_dir, entries


def _artifact(archive_dir: Path, entry: dict[str, object], field: str = "archive_path") -> Path:
    relative = entry[field]
    assert isinstance(relative, str)
    return archive_dir / relative


def _refresh_reading_receipt(entry: dict[str, object], path: Path) -> None:
    entry["row_count"] = pq.read_metadata(path).num_rows
    entry["size_bytes_archive"] = path.stat().st_size
    entry["checksum_md5"] = hashlib.md5(
        path.read_bytes(),
        usedforsecurity=False,
    ).hexdigest()


def _replace_reading_values(path: Path, value: float) -> None:
    parquet = pq.ParquetFile(path)
    table = parquet.read()
    replacement = pa.array([value] * table.num_rows, type=pa.float64())
    pq.write_table(
        table.set_column(table.schema.get_field_index("value"), "value", replacement),
        path,
    )


def _bounded(reader: ArchiveReader, start: datetime, end: datetime):
    return reader.query_reading_rows_bounded(
        start=start,
        end=end,
        channels=("T",),
        max_channels=1,
        max_points_per_channel=20,
        max_total_points=20,
        max_retained_bytes=65_536,
        deadline_monotonic=time.monotonic() + 10,
        batch_rows=64,
        max_arrow_batch_bytes=65_536,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "persistent_replacement",
        "checksum",
        "size",
        "row_count",
        "schema",
        "canonical_path",
        "missing_receipt",
        "partial_receipt",
    ],
)
def test_archive_receipt_mismatch_matrix_rejects_every_production_reader(
    tmp_path: Path,
    fault: str,
) -> None:
    day = datetime(2026, 4, 14, 12, tzinfo=UTC)
    archive_dir, entries = _rotate_days(tmp_path, [(day, 1.0)])
    entry = entries[0]
    path = _artifact(archive_dir, entry)

    if fault == "persistent_replacement":
        _replace_reading_values(path, 99.0)
    elif fault == "checksum":
        entry["checksum_md5"] = "0" * 32
    elif fault == "size":
        entry["size_bytes_archive"] = path.stat().st_size + 1
    elif fault == "row_count":
        entry["row_count"] = int(entry["row_count"]) + 1
    elif fault == "schema":
        table = pq.ParquetFile(path).read()
        pq.write_table(
            table.append_column("unexpected", pa.array([1] * table.num_rows, type=pa.int8())),
            path,
        )
        _refresh_reading_receipt(entry, path)
    elif fault == "canonical_path":
        relative = str(entry["archive_path"])
        entry["archive_path"] = f"{Path(relative).parent.as_posix()}/../{Path(relative).name}"
    elif fault == "missing_receipt":
        for field in ("row_count", "size_bytes_archive", "checksum_md5"):
            entry.pop(field, None)
    else:
        entry.pop("checksum_md5")
    _write_index(archive_dir, entries)

    reader = ArchiveReader(tmp_path, archive_dir)
    with pytest.raises(ArchiveUnavailableError):
        reader.query_rows(None, None, None)
    with pytest.raises(ArchiveUnavailableError):
        reader.query(["T"], day.replace(hour=0), day.replace(hour=23))
    bounded = _bounded(reader, day.replace(hour=0), day.replace(hour=0) + timedelta(days=1))
    assert bounded.complete is False
    assert bounded.rows == ()


def test_failed_cold_source_rows_are_quarantined_after_postread_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = datetime(2026, 4, 14, 12, tzinfo=UTC)
    new = old + timedelta(days=1)
    archive_dir, entries = _rotate_days(tmp_path, [(old, 1.0), (new, 2.0)])
    old_entry = next(entry for entry in entries if entry["original_name"] == "data_2026-04-14.db")
    old_path = _artifact(archive_dir, old_entry)
    real_next = ArchiveReader._next_bounded_parquet_batch
    mutated = False

    def mutate_after_materialization(iterator: object) -> object:
        nonlocal mutated
        batch = real_next(iterator)
        if not mutated and batch.num_rows and batch["value"][0].as_py() == 1.0:
            mutated = True
            with old_path.open("r+b") as stream:
                stream.seek(4)
                original = stream.read(1)
                assert original
                stream.seek(4)
                stream.write(bytes([original[0] ^ 1]))
                stream.flush()
                os.fsync(stream.fileno())
        return batch

    monkeypatch.setattr(
        ArchiveReader,
        "_next_bounded_parquet_batch",
        staticmethod(mutate_after_materialization),
    )
    result = _bounded(ArchiveReader(tmp_path, archive_dir), old.replace(hour=0), new + timedelta(days=1))

    assert mutated is True
    assert result.complete is False
    assert [row.value for row in result.rows] == [2.0]
    assert BoundedReadIssueCode.PARQUET_READ in {issue.code for issue in result.issues}


def test_history_raises_unavailable_before_returning_partial_cold_rows(tmp_path: Path) -> None:
    old = datetime(2026, 4, 14, 12, tzinfo=UTC)
    new = old + timedelta(days=1)
    archive_dir, entries = _rotate_days(tmp_path, [(old, 1.0), (new, 2.0)])
    old_entry = next(entry for entry in entries if entry["original_name"] == "data_2026-04-14.db")
    _replace_reading_values(_artifact(archive_dir, old_entry), 99.0)

    writer = SQLiteWriter(tmp_path)
    try:
        with pytest.raises(ArchiveUnavailableError):
            writer._read_readings_history(
                channels=["T"],
                from_ts=old.replace(hour=0).timestamp(),
                to_ts=(new + timedelta(days=1)).timestamp(),
                limit_per_channel=20,
            )
    finally:
        asyncio.run(writer.stop())


def test_missing_index_with_cold_artifact_is_unavailable_to_bounded_history(
    tmp_path: Path,
) -> None:
    day = datetime(2026, 4, 14, tzinfo=UTC)
    archive_dir = tmp_path / "archive"
    relative = "year=2026/month=04/orphan.readings.parquet"
    path = archive_dir / relative
    path.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "timestamp": pa.array([day], type=pa.timestamp("us", tz="UTC")),
                "instrument_id": pa.array(["ls"], type=pa.string()),
                "channel": pa.array(["T"], type=pa.string()),
                "value": pa.array([1.0], type=pa.float64()),
                "unit": pa.array(["K"], type=pa.string()),
                "status": pa.array(["ok"], type=pa.string()),
            }
        ),
        path,
    )

    reader = ArchiveReader(tmp_path, archive_dir)
    bounded = _bounded(reader, day, day + timedelta(days=1))
    assert bounded.complete is False
    assert bounded.rows == ()
    assert {issue.code for issue in bounded.issues} == {
        BoundedReadIssueCode.ARCHIVE_INDEX_INVALID,
    }

    writer = SQLiteWriter(tmp_path)
    try:
        with pytest.raises(ArchiveUnavailableError) as caught:
            writer._read_readings_history(
                channels=["T"],
                from_ts=day.timestamp(),
                to_ts=(day + timedelta(days=1)).timestamp(),
            )
        assert caught.value.issue.code is BoundedReadIssueCode.ARCHIVE_INDEX_INVALID
    finally:
        asyncio.run(writer.stop())

    empty_root = tmp_path / "legitimate-empty"
    (empty_root / "archive").mkdir(parents=True)
    empty_writer = SQLiteWriter(empty_root)
    try:
        assert (
            empty_writer._read_readings_history(
                channels=["T"],
                from_ts=day.timestamp(),
                to_ts=(day + timedelta(days=1)).timestamp(),
            )
            == {}
        )
    finally:
        asyncio.run(empty_writer.stop())


def _operator_table(schema: str, message: str | None) -> pa.Table:
    count = 0 if message is None else 1
    columns: dict[str, pa.Array] = {
        "timestamp": pa.array([] if message is None else [1_776_124_800.0], type=pa.float64()),
        "experiment_id": pa.array([] if message is None else ["exp"], type=pa.string()),
        "author": pa.array([] if message is None else ["operator"], type=pa.string()),
        "source": pa.array([] if message is None else ["gui"], type=pa.string()),
        "message": pa.array([] if message is None else [message], type=pa.string()),
        "tags": pa.array([] if message is None else ["[]"], type=pa.string()),
    }
    if schema == "operator_log_v2":
        columns.update(
            {
                "request_id": pa.array([None] * count, type=pa.string()),
                "request_fingerprint": pa.array([None] * count, type=pa.string()),
                "row_id": pa.array(list(range(1, count + 1)), type=pa.int64()),
            }
        )
    return pa.table(columns)


def test_receipted_operator_log_v1_v2_and_exact_zero_rows_remain_compatible(
    tmp_path: Path,
) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    entries: list[dict[str, object]] = []
    shapes = (
        ("2026-04-14", "operator_log_v1", "v1"),
        ("2026-04-15", "operator_log_v2", "v2"),
        ("2026-04-16", "operator_log_v1", None),
        ("2026-04-17", "operator_log_v2", None),
    )
    for day, schema, message in shapes:
        relative = f"year=2026/month=04/data_{day}.{schema}.parquet"
        path = archive_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        table = _operator_table(schema, message)
        pq.write_table(table, path)
        assert path.stat().st_size > 0
        entries.append(
            {
                "original_name": f"data_{day}.db",
                "archive_path": f"year=2026/month=04/data_{day}.readings.parquet",
                "operator_log_path": relative,
                "operator_log_rows": table.num_rows,
                "operator_log_size_bytes": path.stat().st_size,
                "operator_log_checksum_md5": hashlib.md5(
                    path.read_bytes(),
                    usedforsecurity=False,
                ).hexdigest(),
                "operator_log_schema": schema,
            }
        )
    _write_index(archive_dir, entries)

    rows = ArchiveReader(tmp_path, archive_dir).query_operator_log(None, None)
    assert [row[4] for row in rows] == ["v1", "v2"]


def test_receiptless_v1_replacement_is_explicitly_unavailable(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    relative = "year=2026/month=04/data_2026-04-14.operator_log_v1.parquet"
    path = archive_dir / relative
    path.parent.mkdir(parents=True)
    pq.write_table(_operator_table("operator_log_v1", "original"), path)
    entry: dict[str, object] = {
        "original_name": "data_2026-04-14.db",
        "archive_path": "year=2026/month=04/data_2026-04-14.readings.parquet",
        "operator_log_path": relative,
        "operator_log_rows": 1,
    }
    _write_index(archive_dir, [entry])
    pq.write_table(_operator_table("operator_log_v1", "replacement"), path)

    with pytest.raises(ArchiveUnavailableError):
        ArchiveReader(tmp_path, archive_dir).query_operator_log(None, None)


def test_exact_zero_row_readings_receipt_preserves_empty_history(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, tzinfo=UTC)
    archive_dir = tmp_path / "archive"
    relative = "year=2026/month=04/data_2026-04-14.readings.parquet"
    path = archive_dir / relative
    path.parent.mkdir(parents=True)
    table = pa.table(
        {
            "timestamp": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([], type=pa.string()),
            "channel": pa.array([], type=pa.string()),
            "value": pa.array([], type=pa.float64()),
            "unit": pa.array([], type=pa.string()),
            "status": pa.array([], type=pa.string()),
        }
    )
    pq.write_table(table, path)
    assert path.stat().st_size > 0
    _write_index(
        archive_dir,
        [
            {
                "original_name": "data_2026-04-14.db",
                "archive_path": relative,
                "row_count": 0,
                "size_bytes_archive": path.stat().st_size,
                "checksum_md5": hashlib.md5(
                    path.read_bytes(),
                    usedforsecurity=False,
                ).hexdigest(),
            }
        ],
    )

    reader = ArchiveReader(tmp_path / "no-hot-data", archive_dir)
    assert reader.query_rows(day, day + timedelta(days=1), None) == []
    bounded = _bounded(reader, day, day + timedelta(days=1))
    assert bounded.complete is True
    assert bounded.rows == ()
    writer = SQLiteWriter(tmp_path)
    try:
        assert (
            writer._read_readings_history(
                from_ts=day.timestamp(),
                to_ts=(day + timedelta(days=1)).timestamp(),
            )
            == {}
        )
    finally:
        asyncio.run(writer.stop())


def test_main_reading_in_place_mutation_during_materialization_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = datetime(2026, 4, 14, 12, tzinfo=UTC)
    archive_dir, entries = _rotate_days(tmp_path, [(day, 1.0)])
    path = _artifact(archive_dir, entries[0])
    real_read = pq.ParquetFile.read
    mutated = False

    def mutate_after_read(parquet: pq.ParquetFile, *args: object, **kwargs: object) -> pa.Table:
        nonlocal mutated
        table = real_read(parquet, *args, **kwargs)
        if not mutated:
            mutated = True
            with path.open("r+b") as stream:
                stream.seek(4)
                original = stream.read(1)
                assert original
                stream.seek(4)
                stream.write(bytes([original[0] ^ 1]))
                stream.flush()
                os.fsync(stream.fileno())
        return table

    monkeypatch.setattr(pq.ParquetFile, "read", mutate_after_read)
    with pytest.raises(ArchiveUnavailableError):
        ArchiveReader(tmp_path, archive_dir).query_rows(None, None, None)
    assert mutated is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX opened inode survives pathname replacement")
def test_posix_pathname_replacement_of_opened_reading_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = datetime(2026, 4, 14, 12, tzinfo=UTC)
    archive_dir, entries = _rotate_days(tmp_path, [(day, 1.0)])
    path = _artifact(archive_dir, entries[0])
    saved = path.with_suffix(".opened")
    real_read = pq.ParquetFile.read

    def replace_after_read(parquet: pq.ParquetFile, *args: object, **kwargs: object) -> pa.Table:
        table = real_read(parquet, *args, **kwargs)
        path.replace(saved)
        shutil.copyfile(saved, path)
        return table

    monkeypatch.setattr(pq.ParquetFile, "read", replace_after_read)
    with pytest.raises(ArchiveUnavailableError):
        ArchiveReader(tmp_path, archive_dir).query_rows(None, None, None)
    assert saved.is_file()
    assert path.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows open-handle sharing semantics")
def test_windows_open_reading_handle_blocks_pathname_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = datetime(2026, 4, 14, 12, tzinfo=UTC)
    archive_dir, entries = _rotate_days(tmp_path, [(day, 1.0)])
    path = _artifact(archive_dir, entries[0])
    saved = path.with_suffix(".opened")
    real_read = pq.ParquetFile.read
    blocked: list[int | None] = []

    def attempt_replace(parquet: pq.ParquetFile, *args: object, **kwargs: object) -> pa.Table:
        table = real_read(parquet, *args, **kwargs)
        try:
            path.replace(saved)
        except PermissionError as exc:
            blocked.append(exc.winerror)
        else:
            pytest.fail("Windows replaced a live receipted Parquet handle")
        return table

    monkeypatch.setattr(pq.ParquetFile, "read", attempt_replace)
    rows = ArchiveReader(tmp_path, archive_dir).query_rows(None, None, None)
    assert [row[3] for row in rows] == [1.0]
    assert blocked == [32]
    assert path.is_file()
    assert saved.exists() is False


def test_pure_cold_and_overlap_public_query_share_receipted_path(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, 12, tzinfo=UTC)
    archive_dir, _entries = _rotate_days(tmp_path, [(day, 1.0)])
    cold_only = ArchiveReader(tmp_path / "no-hot-data", archive_dir)
    assert [
        value
        for _at, value in cold_only.query(
            ["T"],
            day.replace(hour=0),
            day.replace(hour=23),
        )["T"]
    ] == [1.0]

    writer = SQLiteWriter(tmp_path)
    writer._write_batch([Reading(day + timedelta(hours=1), "ls", "T", 2.0, "K", ChannelStatus.OK)])
    asyncio.run(writer.stop())
    overlap = ArchiveReader(tmp_path, archive_dir).query(
        ["T"],
        day.replace(hour=0),
        day.replace(hour=23),
    )
    assert sorted(value for _at, value in overlap["T"]) == [1.0, 2.0]


def test_receipt_hashing_uses_constant_blocks_and_honors_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "representative.bin"
    path.write_bytes(b"x" * (2 * 1024 * 1024 + 17))
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    real_read = os.read
    requests: list[int] = []

    def record_reads(fd: int, count: int) -> bytes:
        requests.append(count)
        return real_read(fd, count)

    monkeypatch.setattr(archive_reader_module.os, "read", record_reads)
    try:
        digest = ArchiveReader._hash_open_file(
            descriptor,
            deadline_monotonic=time.monotonic() + 10,
        )
    finally:
        os.close(descriptor)
    assert (
        digest
        == hashlib.md5(
            path.read_bytes(),
            usedforsecurity=False,
        ).hexdigest()
    )
    assert requests and max(requests) == 65_536

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    clock = [0.0]

    def expire_after_one_read(fd: int, count: int) -> bytes:
        block = real_read(fd, count)
        clock[0] = 2.0
        return block

    monkeypatch.setattr(archive_reader_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(archive_reader_module.os, "read", expire_after_one_read)
    try:
        with pytest.raises(RuntimeError, match="deadline"):
            ArchiveReader._hash_open_file(descriptor, deadline_monotonic=1.0)
    finally:
        os.close(descriptor)
