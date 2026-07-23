from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cryodaq.core.operator_log import (
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
)
from cryodaq.storage import sqlite_writer as sqlite_writer_module
from cryodaq.storage.cold_rotation import ColdRotationService
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


async def _rotate_mixed_operator_log_v2(
    root: Path,
    *,
    request_id: str = "5" * 32,
    fingerprint: str = "f" * 64,
) -> tuple[Path, Path, dict[str, object]]:
    pytest.importorskip("pyarrow")
    data_dir = root / "data"
    archive_dir = data_dir / "archive"
    old = datetime(2026, 5, 1, tzinfo=UTC)
    writer = SQLiteWriter(data_dir)
    writer._write_operator_log_entry(
        timestamp=old,
        experiment_id="exp-cold",
        author="operator",
        source="gui",
        message="keyed cold row",
        tags=("cold",),
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    writer._write_operator_log_entry(
        timestamp=old,
        experiment_id=None,
        author="system",
        source="legacy",
        message="unkeyed cold row",
        tags=(),
    )
    hot_path = data_dir / "data_2026-05-01.db"
    conn = writer._ensure_connection(old.date())
    conn.execute(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) VALUES (?, ?, ?, ?, ?, ?)",
        (old.timestamp(), "mock", "T1", 4.2, "K", "ok"),
    )
    conn.commit()
    await writer.stop()
    hot_bytes = hot_path.read_bytes()

    service = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    results = await service.run_once(now=datetime(2026, 7, 23, tzinfo=UTC))
    assert len(results) == 1
    assert not hot_path.exists()
    index_path = archive_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["files"]) == 1
    assert index["files"][0]["operator_log_schema"] == "operator_log_v2"
    sidecar = archive_dir / index["files"][0]["operator_log_path"]
    assert sidecar.is_file()
    return (
        index_path,
        hot_path,
        {
            "hot_bytes": hot_bytes,
            "index": index,
            "sidecar": sidecar,
        },
    )


def _write_index(index_path: Path, index: dict[str, object]) -> None:
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_operator_sidecar(
    index_path: Path,
    evidence: dict[str, object],
    table,
    *,
    row_group_size: int | None = None,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    pyarrow_parquet.write_table(table, sidecar, compression="zstd", row_group_size=row_group_size)
    raw = sidecar.read_bytes()
    entry = index["files"][0]
    entry["operator_log_size_bytes"] = len(raw)
    entry["operator_log_checksum_md5"] = hashlib.md5(raw, usedforsecurity=False).hexdigest()
    entry["operator_log_rows"] = table.num_rows
    _write_index(index_path, index)


def _durable_operator_log_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in sorted(root.glob("data_*.db*")):
        if path.is_file():
            payload = path.read_bytes()
            manifest[path.name] = (len(payload), hashlib.sha256(payload).hexdigest())
    return manifest


def _durable_tree_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        payload = path.read_bytes()
        manifest[path.relative_to(root).as_posix()] = (len(payload), hashlib.sha256(payload).hexdigest())
    return manifest


def _install_parquet_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metadata_byte_size: int | None = None,
    on_row_group=None,
    on_batch=None,
) -> dict[str, list[object]]:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    real_parquet_file = pyarrow_parquet.ParquetFile
    observed: dict[str, list[object]] = {"constructor": [], "batches": [], "row_groups": []}

    class ColumnProxy:
        def __init__(self, inner) -> None:
            self._inner = inner

        @property
        def total_compressed_size(self) -> int:
            if metadata_byte_size is not None:
                return metadata_byte_size
            return self._inner.total_compressed_size

    class RowGroupProxy:
        def __init__(self, inner, index: int) -> None:
            self._inner = inner
            self._index = index

        @property
        def total_byte_size(self) -> int:
            return metadata_byte_size if metadata_byte_size is not None else self._inner.total_byte_size

        @property
        def num_columns(self) -> int:
            return self._inner.num_columns

        def column(self, index: int):
            return ColumnProxy(self._inner.column(index))

    class MetadataProxy:
        def __init__(self, inner) -> None:
            self._inner = inner

        @property
        def num_rows(self) -> int:
            return self._inner.num_rows

        @property
        def num_row_groups(self) -> int:
            return self._inner.num_row_groups

        def row_group(self, index: int):
            observed["row_groups"].append(index)
            if on_row_group is not None:
                on_row_group(index)
            return RowGroupProxy(self._inner.row_group(index), index)

    class ParquetFileProbe:
        def __init__(self, *args, **kwargs) -> None:
            observed["constructor"].append(dict(kwargs))
            self._inner = real_parquet_file(*args, **kwargs)

        @property
        def schema_arrow(self):
            return self._inner.schema_arrow

        @property
        def metadata(self):
            return MetadataProxy(self._inner.metadata)

        def iter_batches(self, *args, **kwargs):
            observed["batches"].append(dict(kwargs))
            for index, batch in enumerate(self._inner.iter_batches(*args, **kwargs)):
                if on_batch is not None:
                    on_batch(index, batch)
                yield batch

    monkeypatch.setattr(pyarrow_parquet, "ParquetFile", ParquetFileProbe)
    return observed


async def _assert_cold_registry_unavailable(
    data_dir: Path,
    *,
    match: str | None = None,
    request_id: str = "7" * 32,
    request_fingerprint: str = "b" * 64,
) -> None:
    before_manifest = _durable_operator_log_manifest(data_dir)
    writer = SQLiteWriter(data_dir)
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match=match):
        await writer.initialize_operator_log_idempotency()
    assert writer._operator_log_idempotency_registry is None
    assert _durable_operator_log_manifest(data_dir) == before_manifest
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await writer.append_operator_log_idempotent(
            message="must not be appended",
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
    assert _durable_operator_log_manifest(data_dir) == before_manifest
    await writer.stop()


async def test_rotation_restart_returns_original_request_receipt(tmp_path: Path) -> None:
    request_id = "5" * 32
    fingerprint = "f" * 64
    _index_path, _hot_path, _evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()
    found = await writer.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await writer.append_operator_log_idempotent(
        message="must return the cold durable row",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert found is not None and found.replayed is True
    assert found.entry.message == "keyed cold row"
    assert found.entry.experiment_id == "exp-cold"
    assert replay == found
    assert await asyncio.to_thread(lambda: list((tmp_path / "data").glob("data_*.db"))) == []
    await writer.stop()


@pytest.mark.parametrize(
    "malformed_index",
    [
        {},
        {"files": {}},
        {"files": None},
    ],
    ids=["missing-files", "mapping-files", "null-files"],
)
async def test_present_archive_index_requires_exact_files_list_before_retained_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformed_index: dict[str, object],
) -> None:
    request_id = "d" * 32
    fingerprint = "e" * 64
    index_path, _hot_path, _evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    _write_index(index_path, malformed_index)
    observed = _install_parquet_probe(monkeypatch)
    before_manifest = _durable_tree_manifest(tmp_path / "data")

    await _assert_cold_registry_unavailable(
        tmp_path / "data",
        match="index is invalid",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert observed["constructor"] == []
    assert _durable_tree_manifest(tmp_path / "data") == before_manifest


@pytest.mark.parametrize("schema_kind", ["v1", "v2_all_null"])
@pytest.mark.parametrize("alias_separator", ["//", "/./"], ids=["double-slash", "dot-segment"])
async def test_noncanonical_relative_alias_cannot_bypass_duplicate_authority_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_kind: str,
    alias_separator: str,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    if schema_kind == "v1":
        table = table.select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
        index["files"][0]["operator_log_schema"] = "operator_log_v1"
    else:
        table = table.set_column(
            table.schema.get_field_index("request_id"),
            "request_id",
            pyarrow.array([None] * table.num_rows, type=pyarrow.string()),
        )
        table = table.set_column(
            table.schema.get_field_index("request_fingerprint"),
            "request_fingerprint",
            pyarrow.array([None] * table.num_rows, type=pyarrow.string()),
        )
    _rewrite_operator_sidecar(index_path, evidence, table)
    duplicate = json.loads(json.dumps(index["files"][0]))
    for field_name in ("archive_path", "operator_log_path"):
        value = duplicate[field_name]
        assert isinstance(value, str) and "/" in value
        duplicate[field_name] = value.replace("/", alias_separator, 1)
    index["files"].append(duplicate)
    _write_index(index_path, index)
    observed = _install_parquet_probe(monkeypatch)
    before_manifest = _durable_tree_manifest(tmp_path / "data")

    await _assert_cold_registry_unavailable(
        tmp_path / "data",
        match="invalid or non-canonical",
    )

    assert observed["constructor"] == []
    assert _durable_tree_manifest(tmp_path / "data") == before_manifest


async def test_half_null_cold_identity_disables_registry(tmp_path: Path) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    request_ids = table["request_id"].to_pylist()
    request_ids[1] = "a" * 32
    table = table.set_column(
        table.schema.get_field_index("request_id"),
        "request_id",
        pyarrow.array(request_ids, type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)

    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize(
    "mutation",
    [
        "v2_tagged_v1",
        "timestamp_string",
        "timestamp_nonfinite",
        "experiment_integer",
        "extra_column",
        "missing_column",
        "row_id_zero",
        "row_id_duplicate",
    ],
)
async def test_exact_cold_schema_and_tag_are_mandatory(tmp_path: Path, mutation: str) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    if mutation == "v2_tagged_v1":
        index["files"][0]["operator_log_schema"] = "operator_log_v1"
        _write_index(index_path, index)
    elif mutation == "timestamp_string":
        table = table.set_column(
            table.schema.get_field_index("timestamp"),
            "timestamp",
            pyarrow.array(
                ["2026-05-01T00:00:00+00:00"] * table.num_rows,
                type=pyarrow.string(),
            ),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "timestamp_nonfinite":
        table = table.set_column(
            table.schema.get_field_index("timestamp"),
            "timestamp",
            pyarrow.array([float("inf"), float("nan")], type=pyarrow.float64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "experiment_integer":
        table = table.set_column(
            table.schema.get_field_index("experiment_id"),
            "experiment_id",
            pyarrow.array([17, None], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "extra_column":
        table = table.append_column(
            "optimistic_ready",
            pyarrow.array([True] * table.num_rows, type=pyarrow.bool_()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "missing_column":
        table = table.drop(["source"])
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "row_id_zero":
        table = table.set_column(
            table.schema.get_field_index("row_id"),
            "row_id",
            pyarrow.array([0, 2], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    else:
        table = table.set_column(
            table.schema.get_field_index("row_id"),
            "row_id",
            pyarrow.array([1, 1], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)

    await _assert_cold_registry_unavailable(tmp_path / "data")


async def test_exact_v1_sidecar_is_verified_then_excluded_from_keyed_registry(tmp_path: Path) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
    )
    index["files"][0]["operator_log_schema"] = "operator_log_v1"
    _rewrite_operator_sidecar(index_path, evidence, table)
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()

    assert writer._operator_log_idempotency_registry == {}
    await writer.stop()


async def test_fully_absent_operator_metadata_is_irrelevant_to_keyed_registry(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    entry = index["files"][0]
    for field in (
        "operator_log_path",
        "operator_log_rows",
        "operator_log_checksum_md5",
        "operator_log_size_bytes",
        "operator_log_schema",
    ):
        entry.pop(field)
    _write_index(index_path, index)
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()

    assert writer._operator_log_idempotency_registry == {}
    await writer.stop()


@pytest.mark.parametrize(
    "fault",
    [
        "checksum",
        "size",
        "zero_rows",
        "row_count",
        "partial",
        "all_null",
        "unknown_schema",
        "path",
    ],
)
async def test_corrupt_or_ambiguous_cold_identity_disables_writes(tmp_path: Path, fault: str) -> None:
    request_id = "6" * 32
    fingerprint = "a" * 64
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    index = evidence["index"]
    assert isinstance(index, dict)
    entries = index["files"]
    assert isinstance(entries, list)
    entry = entries[0]
    if fault == "checksum":
        entry["operator_log_checksum_md5"] = "0" * 32
    elif fault == "size":
        entry["operator_log_size_bytes"] += 1
    elif fault == "zero_rows":
        entry["operator_log_rows"] = 0
    elif fault == "row_count":
        entry["operator_log_rows"] += 1
    elif fault == "partial":
        entry.pop("operator_log_checksum_md5")
    elif fault == "all_null":
        for field in (
            "operator_log_path",
            "operator_log_rows",
            "operator_log_checksum_md5",
            "operator_log_size_bytes",
            "operator_log_schema",
        ):
            entry[field] = None
    elif fault == "unknown_schema":
        entry["operator_log_schema"] = "operator_log_v3"
    else:
        entry["operator_log_path"] = "other.operator_log.parquet"
    _write_index(index_path, index)
    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize("duplicate_kind", ["exact_proof", "same_path"])
async def test_duplicate_unkeyed_cold_proof_disables_registry(
    tmp_path: Path,
    duplicate_kind: str,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
    )
    index["files"][0]["operator_log_schema"] = "operator_log_v1"
    _rewrite_operator_sidecar(index_path, evidence, table)
    duplicate = json.loads(json.dumps(index["files"][0]))
    if duplicate_kind == "same_path":
        duplicate["operator_log_rows"] = 1
    index["files"].append(duplicate)
    _write_index(index_path, index)

    expected = "proof is duplicated" if duplicate_kind == "exact_proof" else "path authority is ambiguous"
    await _assert_cold_registry_unavailable(tmp_path / "data", match=expected)


async def test_duplicate_json_index_key_is_ambiguous_and_disables_registry(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    encoded = json.dumps(index, ensure_ascii=False)
    index_path.write_text(
        '{"files":[],"files":' + encoded.removeprefix('{"files":').removesuffix("}") + "}",
        encoding="utf-8",
    )

    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize("bound", ["index", "sidecar", "field", "decoded"])
async def test_cold_registry_bounds_fail_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    if bound == "index":
        monkeypatch.setattr(
            sqlite_writer_module,
            "_OPERATOR_LOG_INDEX_MAX_BYTES",
            len(index_path.read_bytes()) - 1,
        )
    elif bound == "sidecar":
        monkeypatch.setattr(
            sqlite_writer_module,
            "_OPERATOR_LOG_SIDECAR_MAX_BYTES",
            sidecar.stat().st_size - 1,
        )
    elif bound == "field":
        table = pyarrow_parquet.ParquetFile(sidecar).read()
        table = table.set_column(
            table.schema.get_field_index("message"),
            "message",
            pyarrow.array(["x" * 128, "unkeyed"], type=pyarrow.string()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_TEXT_FIELD_BYTES", 64)
    else:
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data")


async def test_identity_field_bound_is_independent_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .set_column(
            2,
            "author",
            pyarrow.array(["a" * 128, "system"], type=pyarrow.string()),
        )
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="author field exceeds cap")


async def test_expected_row_cap_is_checked_before_decoder_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _rotate_mixed_operator_log_v2(tmp_path)
    observed = _install_parquet_probe(monkeypatch)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_KEYED_ROWS", 1)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="row-count proof is invalid")

    assert observed["constructor"] == []


async def test_row_group_cap_has_its_own_rejection_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    _rewrite_operator_sidecar(index_path, evidence, table, row_group_size=1)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_ROW_GROUPS", 1)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="row-group count exceeds cap")


async def test_parquet_decoder_receives_exact_resource_and_batch_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    request_ids = table["request_id"].to_pylist()
    request_ids[1] = "a" * 32
    table = table.set_column(
        table.schema.get_field_index("request_id"),
        "request_id",
        pyarrow.array(request_ids, type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    observed = _install_parquet_probe(monkeypatch)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="partially populated")

    assert observed["constructor"] == [
        {
            "pre_buffer": False,
            "thrift_string_size_limit": sqlite_writer_module._OPERATOR_LOG_PARQUET_THRIFT_STRING_MAX_BYTES,
            "thrift_container_size_limit": sqlite_writer_module._OPERATOR_LOG_MAX_KEYED_ROWS * 9,
        }
    ]
    assert observed["batches"] == [{"batch_size": sqlite_writer_module._OPERATOR_LOG_BATCH_ROWS, "use_threads": False}]


async def test_post_batch_arrow_byte_bound_is_not_masked_by_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _rotate_mixed_operator_log_v2(tmp_path)
    batch_sizes: list[int] = []
    observed = _install_parquet_probe(
        monkeypatch,
        metadata_byte_size=1,
        on_batch=lambda _index, batch: batch_sizes.append(batch.nbytes),
    )
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="decoded size exceeds cap")

    assert observed["row_groups"] == [0]
    assert len(batch_sizes) == 1 and batch_sizes[0] > 64


async def test_decoded_content_bound_is_not_masked_by_arrow_batch_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    escaped_tags = '["' + "\\u0061" * 512 + '"]'
    table = table.set_column(
        table.schema.get_field_index("tags"),
        "tags",
        pyarrow.array([escaped_tags, "[]"], type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    rows = table.to_pylist()
    decoded_content_bytes = 0
    for row in rows:
        for value in (row["experiment_id"], row["author"], row["source"], row["message"], row["tags"]):
            if value is not None:
                decoded_content_bytes += len(value.encode("utf-8"))
        decoded_content_bytes += sum(len(value.encode("utf-8")) for value in json.loads(row["tags"]))
        if row["request_id"] is not None:
            decoded_content_bytes += len(row["request_id"]) + len(row["request_fingerprint"])
    arrow_bytes = table.to_batches(max_chunksize=sqlite_writer_module._OPERATOR_LOG_BATCH_ROWS)[0].nbytes
    assert decoded_content_bytes > arrow_bytes
    limit = arrow_bytes + 1
    assert decoded_content_bytes > limit
    observed_batch_sizes: list[int] = []
    _install_parquet_probe(
        monkeypatch,
        metadata_byte_size=1,
        on_batch=lambda _index, batch: observed_batch_sizes.append(batch.nbytes),
    )
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", limit)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="decoded content exceeds cap")

    assert observed_batch_sizes == [arrow_bytes]


async def test_deadline_expiry_immediately_after_secure_read_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    sidecar_relative = index["files"][0]["operator_log_path"]
    expired = False
    reads: list[str] = []
    real_read = sqlite_writer_module._read_secure_operator_log_bytes

    def read_then_expire(root: Path, relative: str, **kwargs) -> bytes:
        nonlocal expired
        raw = real_read(root, relative, **kwargs)
        reads.append(relative)
        if relative == sidecar_relative:
            expired = True
        return raw

    monkeypatch.setattr(sqlite_writer_module, "_read_secure_operator_log_bytes", read_then_expire)
    monkeypatch.setattr(sqlite_writer_module, "_operator_log_monotonic", lambda: 111.0 if expired else 100.0)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="deadline expired after read")

    assert reads == ["archive/index.json", sidecar_relative]


@pytest.mark.parametrize("boundary", ["row_group", "batch"])
async def test_deadline_expiry_inside_parquet_iteration_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    expired = False
    observed_batch_indices: list[int] = []

    def on_row_group(index: int) -> None:
        nonlocal expired
        if boundary == "row_group" and index == 0:
            expired = True

    def on_batch(index: int, _batch) -> None:
        nonlocal expired
        observed_batch_indices.append(index)
        if boundary == "batch" and index == 1:
            expired = True

    if boundary == "row_group":
        sidecar = evidence["sidecar"]
        assert isinstance(sidecar, Path)
        _rewrite_operator_sidecar(
            index_path,
            evidence,
            pyarrow_parquet.ParquetFile(sidecar).read(),
            row_group_size=1,
        )
    else:
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_BATCH_ROWS", 1)
    observed = _install_parquet_probe(
        monkeypatch,
        on_row_group=on_row_group,
        on_batch=on_batch,
    )
    monkeypatch.setattr(sqlite_writer_module, "_operator_log_monotonic", lambda: 111.0 if expired else 100.0)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="cold registry deadline expired")

    if boundary == "row_group":
        assert observed["row_groups"] == [0]
        assert observed_batch_indices == []
    else:
        assert observed["row_groups"] == [0]
        assert observed_batch_indices == [0, 1]


async def test_cold_sidecar_symlink_or_reparse_is_rejected(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    target = sidecar.with_name(sidecar.name + ".target")
    sidecar.replace(target)
    try:
        os.symlink(target.name, sidecar)
    except OSError as exc:
        target.replace(sidecar)
        pytest.skip(f"symlink/reparse creation is unavailable: {exc}")

    try:
        await _assert_cold_registry_unavailable(tmp_path / "data")
    finally:
        if sidecar.is_symlink():
            sidecar.unlink()
        if target.exists():
            target.replace(sidecar)
        assert index_path.exists()


async def test_sidecar_swap_after_stable_read_cannot_change_decoded_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    request_id = "b" * 32
    fingerprint = "c" * 64
    _index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    malicious = sidecar.with_name(sidecar.name + ".malicious")
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    table = table.set_column(
        table.schema.get_field_index("message"),
        "message",
        pyarrow.array(["swapped content", "swapped content"], type=pyarrow.string()),
    )
    pyarrow_parquet.write_table(table, malicious, compression="zstd")
    original = sqlite_writer_module._read_secure_operator_log_bytes
    swapped = False

    def read_then_swap(root: Path, relative: str, **kwargs) -> bytes:
        nonlocal swapped
        raw = original(root, relative, **kwargs)
        if not swapped and relative == index["files"][0]["operator_log_path"]:
            backup = sidecar.with_name(sidecar.name + ".original")
            sidecar.replace(backup)
            malicious.replace(sidecar)
            swapped = True
        return raw

    monkeypatch.setattr(sqlite_writer_module, "_read_secure_operator_log_bytes", read_then_swap)
    writer = SQLiteWriter(tmp_path / "data")
    await writer.initialize_operator_log_idempotency()
    found = await writer.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert swapped is True
    assert found is not None
    assert found.entry.message == "keyed cold row"
    await writer.stop()


async def test_keyed_registry_capacity_rejects_before_append_without_eviction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_KEYED_ROWS", 1)
    writer = SQLiteWriter(tmp_path)
    await writer.initialize_operator_log_idempotency()
    first = await writer.append_operator_log_idempotent(
        message="retained identity",
        request_id="8" * 32,
        request_fingerprint="c" * 64,
    )
    before_manifest = _durable_operator_log_manifest(tmp_path)
    assert any(name.endswith(".db") for name in before_manifest)

    class ForbiddenDatetime:
        @classmethod
        def now(cls, _timezone):
            raise AssertionError("capacity rejection must happen before server time is observed")

    def forbidden_write(**_kwargs):
        raise AssertionError("capacity rejection must happen before any durable append")

    monkeypatch.setattr(sqlite_writer_module, "datetime", ForbiddenDatetime)
    monkeypatch.setattr(writer, "_write_operator_log_entry", forbidden_write)

    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="capacity"):
        await writer.append_operator_log_idempotent(
            message="must not displace retained identity",
            request_id="9" * 32,
            request_fingerprint="d" * 64,
        )

    registry = writer._operator_log_idempotency_registry
    assert registry is not None
    assert tuple(registry) == ("8" * 32,)
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    replay = await writer.append_operator_log_idempotent(
        message="payload is ignored only for the exact retained fingerprint",
        request_id="8" * 32,
        request_fingerprint="c" * 64,
    )
    assert replay.replayed is True
    assert replay.entry == first.entry
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.append_operator_log_idempotent(
            message="conflict must outrank capacity",
            request_id="8" * 32,
            request_fingerprint="d" * 64,
        )
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    await writer.stop()


async def test_legacy_stranded_index_cannot_delete_unproven_operator_log_rows(tmp_path: Path) -> None:
    index_path, hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    entry = index["files"][0]
    for field in (
        "operator_log_path",
        "operator_log_rows",
        "operator_log_checksum_md5",
        "operator_log_size_bytes",
        "operator_log_schema",
    ):
        entry.pop(field)
    assert entry.get("source_md5")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    hot_bytes = evidence["hot_bytes"]
    assert isinstance(hot_bytes, bytes)
    hot_path.write_bytes(hot_bytes)
    service = ColdRotationService(data_dir=hot_path.parent, archive_dir=index_path.parent, age_days=30)
    proof_conn = sqlite3.connect(hot_path)
    try:
        proof_conn.execute("BEGIN IMMEDIATE")
        assert service._logical_source_md5(proof_conn) == entry["source_md5"]
    finally:
        if proof_conn.in_transaction:
            proof_conn.rollback()
        proof_conn.close()
    sidecars_before = {
        path.name: path.read_bytes()
        for path in (hot_path.with_name(hot_path.name + "-wal"), hot_path.with_name(hot_path.name + "-shm"))
        if path.exists()
    }
    assert sidecars_before == {}, "the operator-log proof, not a live WAL sidecar, must block deletion"

    await service.run_once(now=datetime(2026, 7, 23, tzinfo=UTC))

    assert hot_path.read_bytes() == hot_bytes
    assert {
        path.name: path.read_bytes()
        for path in (hot_path.with_name(hot_path.name + "-wal"), hot_path.with_name(hot_path.name + "-shm"))
        if path.exists()
    } == sidecars_before
    conn = sqlite3.connect(hot_path)
    try:
        assert conn.execute("SELECT message FROM operator_log ORDER BY id").fetchall() == [
            ("keyed cold row",),
            ("unkeyed cold row",),
        ]
    finally:
        conn.close()
