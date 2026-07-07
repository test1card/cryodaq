"""Tests for ColdRotationService — SQLite → Parquet cold-storage rotation (F17)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.storage.cold_rotation import ColdRotationService, RotationResult  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_db(db_path: Path, rows: int, base_ts: float | None = None) -> None:
    """Create a minimal SQLite DB with a readings table and *rows* entries."""
    if base_ts is None:
        base_ts = datetime(2026, 1, 15, tzinfo=UTC).timestamp()
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
        [
            (base_ts + i, "ls218s", f"Т{(i % 8) + 1}", 77.0 + i * 0.01, "K", "ok")
            for i in range(rows)
        ],
    )
    conn.commit()
    conn.close()


def _old_db_name(days_ago: int, today: datetime | None = None) -> str:
    ref = today or datetime(2026, 4, 29, tzinfo=UTC)
    day = (ref - timedelta(days=days_ago)).date()
    return f"data_{day.isoformat()}.db"


def _today_db_name(today: datetime | None = None) -> str:
    ref = today or datetime(2026, 4, 29, tzinfo=UTC)
    return f"data_{ref.date().isoformat()}.db"


# ---------------------------------------------------------------------------
# test_rotation_identifies_old_files
# ---------------------------------------------------------------------------


def test_rotation_identifies_old_files(tmp_path: Path) -> None:
    """Files older than age_days are found; newer files are ignored."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)

    # Create files: 35-day-old (should rotate), 10-day-old (should not)
    old_name = _old_db_name(35, today)
    recent_name = _old_db_name(10, today)

    _create_db(data_dir / old_name, rows=50)
    _create_db(data_dir / recent_name, rows=20)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    assert results[0].db_path.name == old_name
    # Recent file stays
    assert (data_dir / recent_name).exists()


# ---------------------------------------------------------------------------
# test_rotation_produces_valid_parquet
# ---------------------------------------------------------------------------


def test_rotation_produces_valid_parquet(tmp_path: Path) -> None:
    """Rotated SQLite rows match Parquet row count exactly."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    n_rows = 300
    _create_db(data_dir / old_name, rows=n_rows)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    result = results[0]
    assert result.rows == n_rows

    # Parquet file exists and has correct row count
    assert result.archive_path.exists()
    table = pq.read_table(str(result.archive_path))
    assert table.num_rows == n_rows

    # Parquet schema columns are correct (no experiment_id for cold rotation)
    expected_cols = {"timestamp", "instrument_id", "channel", "value", "unit", "status"}
    assert expected_cols.issubset(set(table.schema.names))
    assert "experiment_id" not in table.schema.names


# ---------------------------------------------------------------------------
# test_original_deleted_only_after_verification
# ---------------------------------------------------------------------------


def test_original_deleted_only_after_verification(tmp_path: Path) -> None:
    """SQLite is deleted only after Parquet row count verified; stays on write failure."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(35, today)
    _create_db(data_dir / old_name, rows=100)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    # Patch the Parquet writer to raise an exception mid-write
    import pyarrow.parquet as pq_mod

    class _FailingWriter:
        def __init__(self, *args, **kwargs):
            # Instantiate but blow up on write
            pass

        def write_table(self, *args, **kwargs):
            raise OSError("disk full simulation")

        def close(self):
            pass

    with patch.object(pq_mod, "ParquetWriter", _FailingWriter):
        results = asyncio.run(service.run_once(now=today))

    # No successful rotations
    assert results == []
    # Original SQLite MUST still exist
    assert (data_dir / old_name).exists()


# ---------------------------------------------------------------------------
# test_rotation_atomicity_on_crash
# ---------------------------------------------------------------------------


def test_rotation_atomicity_on_crash(tmp_path: Path) -> None:
    """Simulated crash mid-write leaves SQLite intact; partial Parquet removed."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(35, today)
    _create_db(data_dir / old_name, rows=50)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    import pyarrow.parquet as pq_mod

    class _CrashingWriter:
        def __init__(self, path, schema, **kwargs):
            self._path = Path(path)
            # Create the file to simulate partial write
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch()

        def write_table(self, *args, **kwargs):
            raise RuntimeError("simulated crash during write")

        def close(self):
            pass

    with patch.object(pq_mod, "ParquetWriter", _CrashingWriter):
        results = asyncio.run(service.run_once(now=today))

    assert results == []
    # Original SQLite intact
    assert (data_dir / old_name).exists()
    # No stray Parquet files should remain
    parquet_files = list(archive_dir.rglob("*.parquet"))
    assert parquet_files == [], f"Partial parquet files left behind: {parquet_files}"


# ---------------------------------------------------------------------------
# test_disabled_state_no_rotation
# ---------------------------------------------------------------------------


def test_disabled_state_no_rotation(tmp_path: Path) -> None:
    """enabled=False → run_once returns [] without touching any files."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    _create_db(data_dir / old_name, rows=100)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=False,
    )

    results = asyncio.run(service.run_once(now=today))

    assert results == []
    assert (data_dir / old_name).exists()
    assert not archive_dir.exists() or not list(archive_dir.rglob("*.parquet"))


# ---------------------------------------------------------------------------
# test_active_db_not_rotated
# ---------------------------------------------------------------------------


def test_active_db_not_rotated(tmp_path: Path) -> None:
    """Today's active DB is never rotated even if age_days=0."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    today_name = _today_db_name(today)
    _create_db(data_dir / today_name, rows=10)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=0,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert results == []
    assert (data_dir / today_name).exists()


# ---------------------------------------------------------------------------
# test_index_updated_on_rotation
# ---------------------------------------------------------------------------


def test_index_updated_on_rotation(tmp_path: Path) -> None:
    """archive_dir/index.json updated with correct metadata after rotation."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    n_rows = 75
    _create_db(data_dir / old_name, rows=n_rows)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    result = results[0]

    index_path = archive_dir / "index.json"
    assert index_path.exists(), "index.json must be created"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert "files" in index
    assert len(index["files"]) == 1

    entry = index["files"][0]
    assert entry["original_name"] == old_name
    assert entry["row_count"] == n_rows

    # Sizes must match actual files on disk, not just be > 0.
    assert entry["size_bytes_original"] == result.size_original, (
        f"size_bytes_original {entry['size_bytes_original']} != "
        f"RotationResult.size_original {result.size_original}"
    )
    assert entry["size_bytes_archive"] == result.size_archive, (
        f"size_bytes_archive {entry['size_bytes_archive']} != "
        f"RotationResult.size_archive {result.size_archive}"
    )
    assert result.size_original > 0
    assert result.size_archive > 0

    # Checksum must match actual MD5 of the produced archive file.
    import hashlib as _hashlib

    def _md5(path: Path) -> str:
        h = _hashlib.md5()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(65_536), b""):
                h.update(block)
        return h.hexdigest()

    expected_md5 = _md5(result.archive_path)
    assert entry["checksum_md5"] == expected_md5, (
        f"Index checksum {entry['checksum_md5']} != actual file MD5 {expected_md5}"
    )
    assert len(entry["checksum_md5"]) == 32  # hex MD5

    assert "rotated_at" in entry

    # Archive path in index resolves to the actual archive file.
    archive_rel = entry["archive_path"]
    assert "year=" in archive_rel
    assert "month=" in archive_rel
    resolved = archive_dir / archive_rel
    assert resolved.exists(), f"archive_path in index does not exist: {resolved}"
    assert resolved == result.archive_path


# ---------------------------------------------------------------------------
# test_rotation_result_dataclass_fields
# ---------------------------------------------------------------------------


def test_rotation_result_dataclass_fields(tmp_path: Path) -> None:
    """RotationResult has all required fields with correct types."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    _create_db(data_dir / old_name, rows=20)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, RotationResult)
    assert isinstance(r.db_path, Path)
    assert isinstance(r.archive_path, Path)
    assert isinstance(r.rows, int)
    assert r.rows == 20
    assert isinstance(r.size_original, int)
    assert isinstance(r.size_archive, int)
    assert isinstance(r.rotated_at, datetime)
    assert r.size_original > 0
    assert r.size_archive > 0


# ---------------------------------------------------------------------------
# test_wal_shm_sidecar_deleted
# ---------------------------------------------------------------------------


def test_wal_shm_sidecar_deleted(tmp_path: Path) -> None:
    """After successful rotation, WAL and SHM sidecar files are removed."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    _create_db(data_dir / old_name, rows=10)

    # Create fake sidecar files
    (data_dir / (old_name + "-wal")).write_bytes(b"wal content")
    (data_dir / (old_name + "-shm")).write_bytes(b"shm content")

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    # Main DB and sidecars removed
    assert not (data_dir / old_name).exists()
    assert not (data_dir / (old_name + "-wal")).exists()
    assert not (data_dir / (old_name + "-shm")).exists()


# ---------------------------------------------------------------------------
# test_daemon_start_stop
# ---------------------------------------------------------------------------


def _add_operator_log(db_path: Path, rows: int, base_ts: float | None = None) -> None:
    """Add an operator_log table with *rows* audit entries to an existing DB."""
    if base_ts is None:
        base_ts = datetime(2026, 3, 20, tzinfo=UTC).timestamp()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS operator_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp REAL NOT NULL,"
        "  experiment_id TEXT,"
        "  author TEXT NOT NULL DEFAULT '',"
        "  source TEXT NOT NULL DEFAULT '',"
        "  message TEXT NOT NULL,"
        "  tags TEXT NOT NULL DEFAULT '[]'"
        ")"
    )
    conn.executemany(
        "INSERT INTO operator_log (timestamp, experiment_id, author, source, message, tags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (base_ts + i, "EXP-1", "operator", "gui", f"note {i}", "[]")
            for i in range(rows)
        ],
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# test_operator_log_preserved_on_rotation  (CR-3: audit trail must survive)
# ---------------------------------------------------------------------------


def test_operator_log_preserved_on_rotation(tmp_path: Path) -> None:
    """Rotating a daily DB must NOT destroy its operator_log audit trail.

    Before the fix, rotation exported only the ``readings`` table then deleted
    the whole SQLite file — permanently losing operator_log rows. After the
    fix the operator_log rows must remain retrievable post-rotation.
    """
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    db_path = data_dir / old_name
    _create_db(db_path, rows=20)
    _add_operator_log(db_path, rows=5)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1

    # operator_log rows MUST still be retrievable after rotation (not lost).
    ol_files = list(archive_dir.rglob("*.operator_log.parquet"))
    assert len(ol_files) == 1, f"operator_log not preserved: {ol_files}"
    ol_table = pq.read_table(str(ol_files[0]))
    assert ol_table.num_rows == 5
    messages = ol_table.column("message").to_pylist()
    assert "note 0" in messages
    assert "note 4" in messages


# ---------------------------------------------------------------------------
# test_source_data_rows_block_deletion  (CR-3: reserved table not destroyed)
# ---------------------------------------------------------------------------


def test_source_data_rows_block_deletion(tmp_path: Path) -> None:
    """CR-3 follow-up: a day with unexported source_data rows is NOT rotated at
    all — SQLite kept, no Parquet written, and the file is left out of the index
    so it stays a future candidate and cannot be double-counted."""
    import asyncio
    import json as _json

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    db_path = data_dir / old_name
    _create_db(db_path, rows=10)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS source_data ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT NOT NULL,"
        "  channel TEXT NOT NULL,"
        "  voltage REAL, current REAL, resistance REAL, power REAL"
        ")"
    )
    conn.execute(
        "INSERT INTO source_data (timestamp, channel, voltage) VALUES (?, ?, ?)",
        ("2026-03-20T00:00:00+00:00", "smua", 1.5),
    )
    conn.commit()
    conn.close()

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    results = asyncio.run(service.run_once(now=today))

    # Rotation is skipped entirely for this file.
    assert results == [], "day with unexported source_data must not be rotated"
    assert db_path.exists(), "SQLite with unexported source_data rows must be kept"
    # Nothing written to cold storage...
    assert list(archive_dir.rglob("*.parquet")) == []
    # ...and the file is not recorded in the index (stays a future candidate).
    index_file = archive_dir / "index.json"
    if index_file.exists():
        idx = _json.loads(index_file.read_text(encoding="utf-8"))
        assert all(f["original_name"] != old_name for f in idx.get("files", []))


# ---------------------------------------------------------------------------
# test_index_written_atomically  (ME-11 / D-C10: crash-safe index write)
# ---------------------------------------------------------------------------


def test_index_written_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """index.json must be written via atomic_write_text (temp + os.replace)."""
    import asyncio
    from unittest.mock import MagicMock

    from cryodaq.storage import cold_rotation as cr

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_name = _old_db_name(40, today)
    _create_db(data_dir / old_name, rows=15)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    # Spy that wraps the real atomic writer. setattr fails outright if the fix
    # (import + use of atomic_write_text) is not present — right-reason failure.
    real_atomic = cr.atomic_write_text
    spy = MagicMock(side_effect=real_atomic)
    monkeypatch.setattr(cr, "atomic_write_text", spy)

    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1
    assert spy.called, "index.json write must go through atomic_write_text"
    written_paths = [call.args[0] for call in spy.call_args_list]
    assert (archive_dir / "index.json") in written_paths
    # No stray temp file left behind by the atomic write.
    assert list(archive_dir.glob(".index.json.*")) == []
    # And the index is valid, complete JSON.
    index = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index["files"]) == 1


def test_daemon_start_stop(tmp_path: Path) -> None:
    """start() creates a task; stop() cancels it cleanly."""
    import asyncio

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )

    async def _run():
        await service.start()
        assert service._task is not None
        await service.stop()
        assert service._task is None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# F5: a failed Step-5 unlink must not strand the hot DB forever
# ---------------------------------------------------------------------------


def test_failed_unlink_strands_then_swept_next_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: index-before-unlink is the correct fail-safe, but a failed unlink
    (e.g. a Windows file lock) must not abort the pass or strand the hot DB.

    While the hot DB lingers next to its Parquet, query_rows unions+dedups both
    (F4) so no row is lost or doubled. The next pass sweeps the stray and deletes
    it — the day is already indexed, so _find_candidates alone never would.
    """
    pytest.importorskip("pyarrow")
    import asyncio
    import pathlib

    from cryodaq.storage.archive_reader import ArchiveReader

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)
    old_name = f"data_{old_day.date().isoformat()}.db"
    old_ts = datetime(old_day.year, old_day.month, old_day.day, tzinfo=UTC).timestamp()
    _create_db(data_dir / old_name, rows=5, base_ts=old_ts)

    service = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)

    # Simulate a lock held on the hot DB (and its sidecars) during pass 1.
    real_unlink = pathlib.Path.unlink
    lock = {"active": True}

    def flaky_unlink(self, *args, **kwargs):
        if lock["active"] and self.name.startswith(old_name):
            raise PermissionError("simulated Windows file lock")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", flaky_unlink)

    reader = ArchiveReader(data_dir, archive_dir)

    # Pass 1: rotation archives + indexes, but the unlink fails and is caught.
    results = asyncio.run(service.run_once(now=today))
    assert results, "rotation must still report success despite the failed unlink"
    assert (data_dir / old_name).exists(), "locked hot DB must survive, not vanish"
    idx = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    assert any(e["original_name"] == old_name for e in idx["files"]), "day must be indexed"
    # Both copies exist → union+dedup yields exactly the original 5 rows.
    assert len(reader.query_rows(None, None, None)) == 5, "interim union must be 5 rows (no loss/dup)"

    # Pass 2: lock released → sweep deletes the stranded hot DB. _find_candidates
    # skips the already-indexed day, so only the sweep can reclaim it.
    lock["active"] = False
    asyncio.run(service.run_once(now=today))
    assert not (data_dir / old_name).exists(), "sweep must delete the stranded hot DB next pass"
    assert len(reader.query_rows(None, None, None)) == 5, "post-sweep must still be 5 rows"
