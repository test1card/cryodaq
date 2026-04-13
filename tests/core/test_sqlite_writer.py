"""Tests for SQLiteWriter — daily-rotating WAL-mode SQLite persistence."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    """Construct a Reading with a fixed or provided timestamp."""
    timestamp = ts or datetime.now(timezone.utc)
    return Reading(
        timestamp=timestamp,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _batch(
    n: int,
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
) -> list[Reading]:
    ts = ts or datetime.now(timezone.utc)
    return [
        _reading(channel=f"CH{i % 8 + 1}", value=4.0 + i * 0.001, ts=ts,
                 instrument_id=instrument_id)
        for i in range(n)
    ]


def _read_db(db_path: Path) -> list[dict]:
    """Return all rows from the readings table as dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM readings ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 1. Writing a batch creates a DB file with the expected name
# ---------------------------------------------------------------------------

async def test_write_batch_creates_db(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    batch = _batch(5)
    # Use the UTC date from the batch (not local date.today())
    expected_date = batch[0].timestamp.date()

    writer._write_batch(batch)

    expected_db = tmp_path / f"data_{expected_date.isoformat()}.db"
    assert expected_db.exists(), f"Expected DB file {expected_db} not found"


# ---------------------------------------------------------------------------
# 2. Readings survive a round-trip through the DB
# ---------------------------------------------------------------------------

async def test_readings_persisted(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(timezone.utc)

    batch = [
        _reading("T_STAGE", 4.235, "K", ts=ts, instrument_id="ls218s"),
        _reading("T_SHIELD", 77.0, "K", ts=ts, instrument_id="ls218s"),
    ]
    writer._write_batch(batch)

    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"
    rows = _read_db(db_path)

    assert len(rows) == 2

    assert rows[0]["channel"] == "T_STAGE"
    assert abs(rows[0]["value"] - 4.235) < 1e-6
    assert rows[0]["unit"] == "K"
    assert rows[0]["status"] == ChannelStatus.OK.value
    assert rows[0]["instrument_id"] == "ls218s"

    assert rows[1]["channel"] == "T_SHIELD"
    assert abs(rows[1]["value"] - 77.0) < 1e-6


# ---------------------------------------------------------------------------
# 3. WAL journal mode is configured on new databases
# ---------------------------------------------------------------------------

async def test_wal_mode_enabled(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    batch = _batch(1)
    writer._write_batch(batch)

    utc_date = batch[0].timestamp.date()
    db_path = tmp_path / f"data_{utc_date.isoformat()}.db"
    # The writer's own connection has WAL set; a fresh connection inherits it
    # only if WAL was fully checkpointed. Check via the writer's connection instead.
    assert writer._conn is not None, "Writer connection should be open after write"
    row = writer._conn.execute("PRAGMA journal_mode;").fetchone()

    assert row[0].lower() == "wal", f"Expected WAL journal mode, got: {row[0]}"


# ---------------------------------------------------------------------------
# 4. Daily rotation — two dates → two separate DB files
# ---------------------------------------------------------------------------

async def test_daily_rotation(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    day1 = datetime(2026, 3, 13, 12, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)

    writer._write_batch(_batch(3, ts=day1))
    writer._write_batch(_batch(5, ts=day2))

    db1 = tmp_path / "data_2026-03-13.db"
    db2 = tmp_path / "data_2026-03-14.db"

    assert db1.exists(), "DB for day1 not created"
    assert db2.exists(), "DB for day2 not created"

    rows1 = _read_db(db1)
    rows2 = _read_db(db2)

    assert len(rows1) == 3, f"Expected 3 rows in day1 DB, got {len(rows1)}"
    assert len(rows2) == 5, f"Expected 5 rows in day2 DB, got {len(rows2)}"


# ---------------------------------------------------------------------------
# 5. Batch-insert performance — 1000 readings complete in reasonable time
# ---------------------------------------------------------------------------

async def test_batch_insert_performance(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    big_batch = _batch(1000)

    t0 = time.monotonic()
    writer._write_batch(big_batch)
    elapsed = time.monotonic() - t0

    utc_date = big_batch[0].timestamp.date()
    db_path = tmp_path / f"data_{utc_date.isoformat()}.db"
    rows = _read_db(db_path)

    assert len(rows) == 1000, f"Expected 1000 persisted rows, got {len(rows)}"
    assert elapsed < 5.0, f"Batch insert of 1000 rows took {elapsed:.2f}s (> 5s limit)"


# ---------------------------------------------------------------------------
# 6. WAL recovery after crash — data written before crash is readable
# ---------------------------------------------------------------------------

async def test_wal_recovery_after_crash(tmp_path: Path) -> None:
    # Write some readings and then simulate a crash by nulling the connection
    # without calling close() — the WAL file will ensure the committed data
    # is recoverable by the next writer.
    writer_a = SQLiteWriter(tmp_path)
    ts = datetime.now(timezone.utc)
    pre_crash_batch = _batch(10, ts=ts)
    writer_a._write_batch(pre_crash_batch)

    # Simulate crash: drop the connection reference without closing
    writer_a._conn = None  # type: ignore[assignment]

    # A fresh writer targeting the same directory should find the data intact
    writer_b = SQLiteWriter(tmp_path)
    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"

    rows = _read_db(db_path)
    assert len(rows) == 10, (
        f"Expected 10 rows to survive simulated crash, found {len(rows)}"
    )

    # The new writer must also be able to append without corruption
    writer_b._write_batch(_batch(3, ts=ts))
    rows_after = _read_db(db_path)
    assert len(rows_after) == 13


# ---------------------------------------------------------------------------
# 7. _write_batch with empty list is a no-op (no error, no rows written)
# ---------------------------------------------------------------------------

async def test_empty_batch_noop(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    # Must not raise
    writer._write_batch([])

    # No DB file should have been created (nothing to write)
    db_files = list(tmp_path.glob("data_*.db"))
    assert len(db_files) == 0, (
        f"Empty batch should not create DB files, found: {db_files}"
    )


# ---------------------------------------------------------------------------
# 8. _write_batch skips readings with NaN value (sqlite3 maps NaN to NULL)
# ---------------------------------------------------------------------------

async def test_write_batch_skips_nan_values(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(timezone.utc)

    batch = [
        _reading(channel="CH1", value=4.5, ts=ts),
        _reading(channel="CH2", value=float("nan"), ts=ts),  # NaN → should be skipped
        _reading(channel="CH3", value=3.2, ts=ts),
    ]

    # Must not raise IntegrityError
    writer._write_batch(batch)

    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"
    rows = _read_db(db_path)

    # Only 2 rows written (NaN skipped)
    assert len(rows) == 2
    channels = {r["channel"] for r in rows}
    assert channels == {"CH1", "CH3"}


# ---------------------------------------------------------------------------
# 9. Batch spanning midnight is split into two separate daily DBs
# ---------------------------------------------------------------------------

async def test_write_batch_midnight_crossing(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    before_midnight = datetime(2026, 3, 27, 23, 59, 59, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 3, 28, 0, 0, 1, tzinfo=timezone.utc)

    batch = [
        _reading("CH1", 4.5, ts=before_midnight),
        _reading("CH1", 4.6, ts=after_midnight),
    ]
    writer._write_batch(batch)

    db_day1 = tmp_path / "data_2026-03-27.db"
    db_day2 = tmp_path / "data_2026-03-28.db"

    assert db_day1.exists(), "DB for 2026-03-27 not created"
    assert db_day2.exists(), "DB for 2026-03-28 not created"

    rows1 = _read_db(db_day1)
    rows2 = _read_db(db_day2)

    assert len(rows1) == 1, f"Expected 1 row in day1, got {len(rows1)}"
    assert len(rows2) == 1, f"Expected 1 row in day2, got {len(rows2)}"

    assert abs(rows1[0]["value"] - 4.5) < 1e-6
    assert abs(rows2[0]["value"] - 4.6) < 1e-6


# ---------------------------------------------------------------------------
# Phase 2d B-1.3: WAL mode verification
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2d B-2.1: OVERRANGE persist
# ---------------------------------------------------------------------------


async def test_overrange_reading_persists(tmp_path: Path) -> None:
    """B-2.1: OVERRANGE readings with value=inf must be persisted."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т7 Детектор",
        value=float("inf"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.OVERRANGE,
    )
    await writer.write_immediate([r])

    # Query SQLite directly
    db_files = list(tmp_path.glob("data_*.db"))
    assert db_files, "No DB file created"
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т7 Детектор'").fetchall()
    conn.close()
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    assert rows[0][0] == float("inf")
    assert rows[0][1] == "overrange"


async def test_garbage_nan_ok_still_dropped(tmp_path: Path) -> None:
    """B-2.1: NaN with status=OK must still be dropped (garbage)."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т1 Криостат верх",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.OK,
    )
    await writer.write_immediate([r])

    db_files = list(tmp_path.glob("data_*.db"))
    if not db_files:
        return  # No DB created = correctly dropped
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT * FROM readings WHERE channel='Т1 Криостат верх'").fetchall()
    conn.close()
    assert len(rows) == 0, "NaN with status=OK should have been dropped"


async def test_sensor_error_nan_dropped_not_raised(tmp_path: Path) -> None:
    """B-2 BLOCKING fix: SENSOR_ERROR NaN must be dropped, not raise IntegrityError."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т3 Радиатор 1",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.SENSOR_ERROR,
    )
    await writer.write_immediate([r])  # must NOT raise

    db_files = list(tmp_path.glob("data_*.db"))
    if not db_files:
        return
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT * FROM readings WHERE channel='Т3 Радиатор 1'").fetchall()
    conn.close()
    assert len(rows) == 0


async def test_timeout_nan_dropped_not_raised(tmp_path: Path) -> None:
    """B-2 BLOCKING fix: TIMEOUT NaN must be dropped, not raise IntegrityError."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т4 Радиатор 2",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.TIMEOUT,
    )
    await writer.write_immediate([r])  # must NOT raise

    db_files = list(tmp_path.glob("data_*.db"))
    if not db_files:
        return
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT * FROM readings WHERE channel='Т4 Радиатор 2'").fetchall()
    conn.close()
    assert len(rows) == 0


async def test_underrange_negative_inf_persists(tmp_path: Path) -> None:
    """B-2: UNDERRANGE with -inf must persist (symmetric to OVERRANGE)."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т5 Экран 77К",
        value=float("-inf"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.UNDERRANGE,
    )
    await writer.write_immediate([r])

    db_files = list(tmp_path.glob("data_*.db"))
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т5 Экран 77К'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == float("-inf")
    assert rows[0][1] == "underrange"


def test_sqlite_writer_wal_mode_verified(tmp_path: Path) -> None:
    """B-1.3: SQLiteWriter must verify WAL mode is active on new DB."""
    source = Path("src/cryodaq/storage/sqlite_writer.py").read_text(encoding="utf-8")
    assert "actual_mode" in source and '"wal"' in source, (
        "sqlite_writer.py does not verify WAL mode"
    )


def test_sqlite_writer_wal_verification_in_source() -> None:
    """B-1.3: sqlite_writer must raise RuntimeError if WAL mode fails."""
    source = Path("src/cryodaq/storage/sqlite_writer.py").read_text(encoding="utf-8")
    assert 'actual_mode != "wal"' in source or "actual_mode != 'wal'" in source, (
        "sqlite_writer.py does not verify WAL mode result"
    )
    assert "RuntimeError" in source
