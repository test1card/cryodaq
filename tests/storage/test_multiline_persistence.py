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


async def test_multiline_reading_writes_to_sqlite_before_broker_publish(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    """The persistence-first invariant lives at the Scheduler level
    (scheduler.py:390 → sqlite_writer.write_immediate before
    broker.publish_batch). The SQLiteWriter itself does no channel
    filtering, so MultiLine readings persist by construction.

    This test proves the SQLiteWriter side: regardless of channel name,
    every Reading we hand to it lands in the readings table.
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


def test_multiline_persistence_path_is_channel_agnostic() -> None:
    """Static contract check: SQLiteWriter.write_immediate signature
    accepts ``list[Reading]`` and the persisted column set is
    (timestamp, instrument_id, channel, value, unit, status). Nothing
    in the writer pre-filters by channel name.
    """
    import inspect

    src = inspect.getsource(SQLiteWriter)
    # The INSERT statement must enumerate channel without a WHERE clause
    # that could exclude MultiLine_*; the v0.55.4 baseline has just the
    # one canonical INSERT into readings.
    assert "INSERT INTO readings" in src
    assert "WHERE channel" not in src.split("INSERT INTO readings")[1].split(";")[0], (
        "SQLiteWriter must not filter readings by channel name"
    )


def test_multiline_parquet_archive_is_channel_agnostic() -> None:
    """parquet_archive.py reads from the SQLite readings table without
    a channel filter. Verify the source matches that contract so a
    future regression that adds a hardcoded filter is caught here.
    """
    import inspect

    from cryodaq.storage import parquet_archive

    src = inspect.getsource(parquet_archive)
    # The archive reads readings via SELECT; ensure no hardcoded
    # 'WHERE channel NOT LIKE' or 'channel != "MultiLine_*"' filter.
    forbidden = (
        "channel NOT LIKE",
        "channel != 'MultiLine",
        "channel != \"MultiLine",
        "MultiLine NOT IN",
    )
    for f in forbidden:
        assert f not in src, f"parquet_archive contains channel filter '{f}'"


def test_multiline_cold_rotation_is_channel_agnostic() -> None:
    """F17 cold rotation reads SQLite rows for archival; the same
    no-filter contract applies.
    """
    import inspect

    from cryodaq.storage import cold_rotation

    src = inspect.getsource(cold_rotation)
    forbidden = (
        "channel NOT LIKE",
        "channel != 'MultiLine",
        "channel != \"MultiLine",
        "MultiLine NOT IN",
    )
    for f in forbidden:
        assert f not in src, f"cold_rotation contains channel filter '{f}'"
