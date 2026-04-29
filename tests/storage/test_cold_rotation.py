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

    index_path = archive_dir / "index.json"
    assert index_path.exists(), "index.json must be created"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert "files" in index
    assert len(index["files"]) == 1

    entry = index["files"][0]
    assert entry["original_name"] == old_name
    assert entry["row_count"] == n_rows
    assert entry["size_bytes_original"] > 0
    assert entry["size_bytes_archive"] > 0
    assert "checksum_md5" in entry
    assert len(entry["checksum_md5"]) == 32  # hex MD5
    assert "rotated_at" in entry
    assert "archive_path" in entry

    # Archive path follows year=/month= layout
    archive_rel = entry["archive_path"]
    assert "year=" in archive_rel
    assert "month=" in archive_rel


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
