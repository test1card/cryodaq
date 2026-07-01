"""v0.55.6.1 PART B3 — MultiLine readings persistence verification.

Architect explicit: «значения важны, должны храниться как зеница ока».
This file proves the persistence path is channel-agnostic — MultiLine
readings flow through the standard SQLite writer + Parquet archive
exactly like LakeShore / Keithley / Thyracont readings, without any
filter or special-case path that could cause silent data loss.

If any of these tests fail, the v0.55.6.1 spec mandates STOP — the
fix becomes a separate scope, not a UI tweak.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter


def _ml_reading(channel: str, value: float, *, ts: datetime | None = None) -> Reading:
    return Reading(
        timestamp=ts or datetime.now(UTC),
        instrument_id="MultiLine_1",
        channel=channel,
        value=value,
        unit="мм",
        status=ChannelStatus.OK,
    )


def _all_channels(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT DISTINCT channel FROM readings").fetchall()
    conn.close()
    return sorted(r[0] for r in rows)


async def test_multiline_reading_writes_to_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    """Proves the SQLiteWriter side of persistence: regardless of channel name,
    every Reading handed to write_immediate lands in the readings table.

    Note: the persistence-before-publish ordering invariant (scheduler.py:390
    sqlite_writer.write_immediate → broker.publish_batch) is tested at the
    Scheduler level in tests/core/test_persistence_ordering.py, not here.
    This test proves SQLiteWriter accepts MultiLine channel names without
    filtering — the writer treats channel as an opaque string.
    """
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    readings = [
        _ml_reading("MultiLine_1/length_ch1", 12.345678),
        _ml_reading("MultiLine_1/length_ch4", 12.345555),
        _ml_reading("MultiLine_1/env_temperature", 22.4),
        _ml_reading("MultiLine_1/env_pressure", 1013.25),
        _ml_reading("MultiLine_1/env_humidity", 45.0),
    ]
    await writer.write_immediate(readings)

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files, "No DB file created"
    channels = _all_channels(db_files[0])
    assert "MultiLine_1/length_ch1" in channels
    assert "MultiLine_1/length_ch4" in channels
    assert "MultiLine_1/env_temperature" in channels
    assert "MultiLine_1/env_pressure" in channels
    assert "MultiLine_1/env_humidity" in channels


async def test_multiline_reading_round_trip_value_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    """Picometre-level precision must survive the SQLite round-trip
    (FLOAT column → REAL). Operator-facing display rounds to 4 dp,
    but storage keeps the full float64 representation.
    """
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    original = 12.34567812345678  # 14 significant digits
    await writer.write_immediate([_ml_reading("MultiLine_1/length_ch1", original)])

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    conn = sqlite3.connect(str(db_files[0]))
    row = conn.execute(
        "SELECT value FROM readings WHERE channel = ?",
        ("MultiLine_1/length_ch1",),
    ).fetchone()
    conn.close()
    assert row is not None
    # IEEE 754 double round-trip — exact match is overkill; allow 1 ULP.
    assert abs(row[0] - original) < 1e-12


async def test_multiline_persistence_path_is_channel_agnostic(
    tmp_path: Path, monkeypatch
) -> None:
    """Runtime proof (was a source grep): the writer treats `channel` as an
    opaque string. A single batch mixing a plain temperature channel with
    MultiLine_* channels must persist ALL of them — no channel-name filtering."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    mixed = [
        _ml_reading("T12 Теплообменник 2", 4.2),  # plain (non-MultiLine) channel
        _ml_reading("MultiLine_1/length_ch1", 12.345),
        _ml_reading("MultiLine_1/env_humidity", 45.0),
    ]
    await writer.write_immediate(mixed)

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files, "No DB file created"
    channels = _all_channels(db_files[0])
    assert channels == sorted(r.channel for r in mixed), (
        "every channel in the batch must persist; the writer must not filter by name"
    )


def test_multiline_parquet_archive_runtime_channel_agnostic(
    tmp_path: Path, monkeypatch
) -> None:
    """Runtime proof for :func:`export_experiment_readings_to_parquet`.

    Writes a mixed-channel batch (plain temperature + MultiLine channels)
    into a daily SQLite file, runs the real Parquet export, then reads the
    archive and asserts that every channel and its value appear in the output.
    """
    import pyarrow.parquet as pq

    from cryodaq.storage.parquet_archive import export_experiment_readings_to_parquet

    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")

    day = datetime(2026, 3, 14, tzinfo=UTC)
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"

    # Write mixed-channel readings directly via SQLiteWriter
    writer = SQLiteWriter(tmp_path)
    mixed = [
        _ml_reading("T12 Теплообменник 2", 4.2, ts=day.replace(second=0)),
        _ml_reading("MultiLine_1/length_ch1", 12.345, ts=day.replace(second=1)),
        _ml_reading("MultiLine_1/env_humidity", 45.0, ts=day.replace(second=2)),
    ]
    writer._write_batch(mixed)
    # Close (not just drop) the connection so Windows can clean up the temp DB
    # without a WinError 32 on the still-open file handle.
    if writer._conn is not None:
        writer._conn.close()
    writer._conn = None

    assert db_path.exists(), "SQLiteWriter must create the daily DB file"

    output = tmp_path / "archive.parquet"
    result = export_experiment_readings_to_parquet(
        experiment_id="ml-test-exp",
        start_time=day,
        end_time=day.replace(hour=23, minute=59, second=59),
        sqlite_root=tmp_path,
        output_path=output,
    )

    assert result.rows_written == len(mixed), (
        f"Expected {len(mixed)} rows in Parquet, got {result.rows_written}"
    )

    table = pq.read_table(str(output))
    archived_channels = set(table.column("channel").to_pylist())
    for r in mixed:
        assert r.channel in archived_channels, (
            f"Channel '{r.channel}' missing from Parquet archive — "
            "export_experiment_readings_to_parquet must not filter by channel name"
        )

    # Verify values survive the round-trip
    ch_to_value = {
        ch: val
        for ch, val in zip(
            table.column("channel").to_pylist(),
            table.column("value").to_pylist(),
        )
    }
    for r in mixed:
        assert abs(ch_to_value[r.channel] - r.value) < 1e-9, (
            f"Value for channel '{r.channel}' changed in Parquet archive: "
            f"expected {r.value}, got {ch_to_value[r.channel]}"
        )


def test_multiline_cold_rotation_runtime_channel_agnostic(
    tmp_path: Path,
) -> None:
    """Runtime proof for :class:`ColdRotationService`.

    Writes a mixed-channel batch into an old-enough daily DB, runs cold
    rotation, reads the resulting Parquet archive, and asserts every channel
    and its value appear in the output.
    """
    import asyncio

    import pyarrow.parquet as pq

    from cryodaq.storage.cold_rotation import ColdRotationService

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    today = datetime(2026, 4, 29, tzinfo=UTC)
    # 40 days old — well past the 30-day rotation threshold
    old_day = today.replace(day=today.day) - __import__("datetime").timedelta(days=40)
    old_name = f"data_{old_day.date().isoformat()}.db"
    db_path = data_dir / old_name

    # Populate with mixed-channel data
    mixed = [
        _ml_reading("T12 Теплообменник 2", 4.2, ts=old_day.replace(second=0)),
        _ml_reading("MultiLine_1/length_ch1", 12.345, ts=old_day.replace(second=1)),
        _ml_reading("MultiLine_1/env_humidity", 45.0, ts=old_day.replace(second=2)),
    ]
    writer = SQLiteWriter(data_dir)
    writer._write_batch(mixed)
    # Close (not just drop) the connection: cold rotation renames/deletes the
    # source .db, and Windows refuses that while a file handle is still open
    # (WinError 32). Dropping the ref relies on GC, which Windows doesn't
    # release in time.
    if writer._conn is not None:
        writer._conn.close()
    writer._conn = None

    # Rename to the correct old-day filename (SQLiteWriter uses today's date)
    today_db = data_dir / f"data_{datetime.now(UTC).date().isoformat()}.db"
    if today_db.exists() and today_db != db_path:
        today_db.rename(db_path)

    service = ColdRotationService(
        data_dir=data_dir,
        archive_dir=archive_dir,
        age_days=30,
        enabled=True,
    )
    results = asyncio.run(service.run_once(now=today))

    assert len(results) == 1, f"Expected 1 rotation result, got {len(results)}"
    result = results[0]

    assert result.rows == len(mixed), (
        f"Expected {len(mixed)} rows rotated, got {result.rows}"
    )

    table = pq.read_table(str(result.archive_path))
    archived_channels = set(table.column("channel").to_pylist())
    for r in mixed:
        assert r.channel in archived_channels, (
            f"Channel '{r.channel}' missing from cold-rotation Parquet — "
            "ColdRotationService must not filter by channel name"
        )

    ch_to_value = {
        ch: val
        for ch, val in zip(
            table.column("channel").to_pylist(),
            table.column("value").to_pylist(),
        )
    }
    for r in mixed:
        assert abs(ch_to_value[r.channel] - r.value) < 1e-9, (
            f"Value for channel '{r.channel}' changed in cold-rotation archive: "
            f"expected {r.value}, got {ch_to_value[r.channel]}"
        )
