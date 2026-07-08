"""Tests for ArchiveReader — unified SQLite + Parquet query (F17)."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.storage.archive_reader import ArchiveReader  # noqa: E402
from cryodaq.storage.cold_rotation import ColdRotationService  # noqa: E402
from cryodaq.storage.sentinel import SENTINEL  # noqa: E402
from cryodaq.storage.sqlite_writer import SQLiteWriter  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sqlite_db(db_path: Path, readings: list[tuple]) -> None:
    """Create minimal SQLite DB with readings."""
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
        readings,
    )
    conn.commit()
    conn.close()


def _create_parquet(parquet_path: Path, readings: list[tuple]) -> None:
    """Create Parquet with cold-rotation schema (no experiment_id)."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("instrument_id", pa.string()),
            ("channel", pa.string()),
            ("value", pa.float64()),
            ("unit", pa.string()),
            ("status", pa.string()),
        ]
    )
    timestamps, instruments, channels, values, units, statuses = [], [], [], [], [], []
    for ts_epoch, inst, ch, val, unit, status in readings:
        timestamps.append(datetime.fromtimestamp(ts_epoch, tz=UTC))
        instruments.append(inst)
        channels.append(ch)
        values.append(float(val))
        units.append(unit)
        statuses.append(status)

    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(instruments),
            "channel": pa.array(channels),
            "value": pa.array(values, type=pa.float64()),
            "unit": pa.array(units),
            "status": pa.array(statuses),
        },
        schema=schema,
    )
    pq.write_table(table, str(parquet_path), compression="zstd")


def _write_index(archive_dir: Path, entries: list[dict]) -> None:
    """Write archive index.json."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "index.json").write_text(
        json.dumps({"files": entries}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# test_query_archived_uses_parquet
# ---------------------------------------------------------------------------


def test_query_archived_uses_parquet(tmp_path: Path) -> None:
    """When a file is in the archive index, reads come from Parquet."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    day = datetime(2026, 3, 15, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    # Parquet archive for that day
    rel_path = f"year=2026/month=03/{db_name}.parquet"
    parquet_path = archive_dir / rel_path
    readings = [
        (base_ts + i, "ls218s", "Т1", 77.0 + i * 0.1, "K", "ok") for i in range(10)
    ]
    _create_parquet(parquet_path, readings)

    _write_index(
        archive_dir,
        [
            {
                "original_name": db_name,
                "archive_path": rel_path,
                "rotated_at": "2026-04-15T03:00:00+00:00",
                "row_count": 10,
                "size_bytes_original": 1000,
                "size_bytes_archive": 200,
                "checksum_md5": "abc123" + "0" * 26,
            }
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т1"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert len(result["Т1"]) == 10
    # Verify sorted by time
    ts_list = [t for t, _ in result["Т1"]]
    assert ts_list == sorted(ts_list)
    # Verify exact (timestamp, value) pairs — not just count/order.
    expected = [(base_ts + i, 77.0 + i * 0.1) for i in range(10)]
    for i, (ts, val) in enumerate(result["Т1"]):
        assert ts == pytest.approx(expected[i][0], abs=1e-3), f"point {i}: ts mismatch"
        assert val == pytest.approx(expected[i][1], abs=1e-6), f"point {i}: value mismatch"


# ---------------------------------------------------------------------------
# test_query_recent_uses_sqlite
# ---------------------------------------------------------------------------


def test_query_recent_uses_sqlite(tmp_path: Path) -> None:
    """Files not in archive index are read directly from SQLite."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 28, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    readings = [
        (base_ts + i, "ls218s", "Т2", 80.0 + i * 0.05, "K", "ok") for i in range(15)
    ]
    _create_sqlite_db(data_dir / db_name, readings)

    # Empty index — no archived files
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т2"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т2" in result
    assert len(result["Т2"]) == 15
    # Verify exact (timestamp, value) pairs — not just count.
    expected = [(base_ts + i, 80.0 + i * 0.05) for i in range(15)]
    for i, (ts, val) in enumerate(result["Т2"]):
        assert ts == pytest.approx(expected[i][0], abs=1e-3), f"point {i}: ts mismatch"
        assert val == pytest.approx(expected[i][1], abs=1e-6), f"point {i}: value mismatch"


# ---------------------------------------------------------------------------
# test_missing_archive_file_returns_partial
# ---------------------------------------------------------------------------


def test_missing_archive_file_returns_partial(tmp_path: Path) -> None:
    """If indexed Parquet file is missing on disk, gracefully skip it."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    day1 = datetime(2026, 3, 10, tzinfo=UTC)
    day2 = datetime(2026, 3, 11, tzinfo=UTC)

    # day1 in index but Parquet file missing
    rel1 = f"year=2026/month=03/data_{day1.date().isoformat()}.db.parquet"
    # day2 has valid Parquet
    rel2 = f"year=2026/month=03/data_{day2.date().isoformat()}.db.parquet"
    parquet2 = archive_dir / rel2
    readings2 = [
        (day2.timestamp() + i, "ls218s", "Т3", 90.0 + i, "K", "ok") for i in range(5)
    ]
    _create_parquet(parquet2, readings2)

    _write_index(
        archive_dir,
        [
            {
                "original_name": f"data_{day1.date().isoformat()}.db",
                "archive_path": rel1,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 100,
                "size_bytes_original": 5000,
                "size_bytes_archive": 1000,
                "checksum_md5": "aabbcc" + "0" * 26,
            },
            {
                "original_name": f"data_{day2.date().isoformat()}.db",
                "archive_path": rel2,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 5,
                "size_bytes_original": 500,
                "size_bytes_archive": 100,
                "checksum_md5": "ddeeff" + "0" * 26,
            },
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    # Query spanning both days
    result = reader.query(
        channels=["Т3"],
        from_ts=day1,
        to_ts=day2 + timedelta(hours=1),
    )

    # day2 data present; day1 gracefully skipped (no exception)
    assert "Т3" in result
    assert len(result["Т3"]) == 5
    # Verify exact day2 values — no day1 timestamps leaked in.
    day2_ts = day2.timestamp()
    expected_day2 = [(day2_ts + i, 90.0 + i) for i in range(5)]
    for i, (ts, val) in enumerate(result["Т3"]):
        assert ts >= day2_ts, f"point {i}: day1 timestamp leaked (ts={ts} < day2_ts={day2_ts})"
        assert ts < day2_ts + 86400, f"point {i}: timestamp out of expected range"
        assert ts == pytest.approx(expected_day2[i][0], abs=1e-3), f"point {i}: ts mismatch"
        assert val == pytest.approx(expected_day2[i][1], abs=1e-6), f"point {i}: value mismatch"


# ---------------------------------------------------------------------------
# test_query_merges_sqlite_and_parquet
# ---------------------------------------------------------------------------


def test_query_merges_sqlite_and_parquet(tmp_path: Path) -> None:
    """Results from archived Parquet and recent SQLite are merged in time order."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()

    # Old day — archived
    old_day = datetime(2026, 3, 1, tzinfo=UTC)
    old_db_name = f"data_{old_day.date().isoformat()}.db"
    rel_old = f"year=2026/month=03/{old_db_name}.parquet"
    parquet_old = archive_dir / rel_old
    old_readings = [
        (old_day.timestamp() + i, "ls218s", "Т4", 70.0 + i, "K", "ok") for i in range(5)
    ]
    _create_parquet(parquet_old, old_readings)

    # Recent day — SQLite
    recent_day = datetime(2026, 4, 28, tzinfo=UTC)
    recent_db_name = f"data_{recent_day.date().isoformat()}.db"
    recent_readings = [
        (recent_day.timestamp() + i, "ls218s", "Т4", 85.0 + i, "K", "ok") for i in range(3)
    ]
    _create_sqlite_db(data_dir / recent_db_name, recent_readings)

    _write_index(
        archive_dir,
        [
            {
                "original_name": old_db_name,
                "archive_path": rel_old,
                "rotated_at": "2026-04-01T03:00:00+00:00",
                "row_count": 5,
                "size_bytes_original": 500,
                "size_bytes_archive": 100,
                "checksum_md5": "112233" + "0" * 26,
            }
        ],
    )

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т4"],
        from_ts=old_day,
        to_ts=recent_day + timedelta(hours=1),
    )

    assert "Т4" in result
    all_points = result["Т4"]
    assert len(all_points) == 8  # 5 old + 3 recent
    # Verify time-sorted
    ts_list = [t for t, _ in all_points]
    assert ts_list == sorted(ts_list)
    # Verify exact (timestamp, value) for parquet portion (first 5 points).
    old_base = old_day.timestamp()
    for i in range(5):
        ts, val = all_points[i]
        assert ts == pytest.approx(old_base + i, abs=1e-3), f"old[{i}] ts mismatch"
        assert val == pytest.approx(70.0 + i, abs=1e-6), f"old[{i}] value mismatch"
    # Verify exact (timestamp, value) for sqlite portion (last 3 points).
    recent_base = recent_day.timestamp()
    for i in range(3):
        ts, val = all_points[5 + i]
        assert ts == pytest.approx(recent_base + i, abs=1e-3), f"recent[{i}] ts mismatch"
        assert val == pytest.approx(85.0 + i, abs=1e-6), f"recent[{i}] value mismatch"


# ---------------------------------------------------------------------------
# test_query_channel_filter
# ---------------------------------------------------------------------------


def test_query_channel_filter(tmp_path: Path) -> None:
    """channels= filter is respected; other channels excluded from result."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 20, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    # Two channels
    readings = [
        (base_ts + i, "ls218s", "Т1", 77.0, "K", "ok") for i in range(5)
    ] + [
        (base_ts + i, "ls218s", "Т2", 80.0, "K", "ok") for i in range(5)
    ]
    _create_sqlite_db(data_dir / db_name, readings)
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=["Т1"],
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert "Т2" not in result
    assert len(result["Т1"]) == 5


# ---------------------------------------------------------------------------
# test_query_no_channels_filter_returns_all
# ---------------------------------------------------------------------------


def test_query_no_channels_filter_returns_all(tmp_path: Path) -> None:
    """channels=None returns all channels from SQLite."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    data_dir.mkdir()
    archive_dir.mkdir()

    day = datetime(2026, 4, 20, tzinfo=UTC)
    base_ts = day.timestamp()
    db_name = f"data_{day.date().isoformat()}.db"

    readings = [
        (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
        (base_ts + 1, "ls218s", "Т2", 80.0, "K", "ok"),
        (base_ts + 2, "ls218s", "Т3", 85.0, "K", "ok"),
    ]
    _create_sqlite_db(data_dir / db_name, readings)
    _write_index(archive_dir, [])

    reader = ArchiveReader(data_dir=data_dir, archive_dir=archive_dir)
    result = reader.query(
        channels=None,
        from_ts=day,
        to_ts=day + timedelta(hours=1),
    )

    assert "Т1" in result
    assert "Т2" in result
    assert "Т3" in result


# ---------------------------------------------------------------------------
# NaN-доктрина: sentinel / legacy raw-inf rows mask to NaN on read (both sources)
# ---------------------------------------------------------------------------


def test_query_sqlite_masks_nonfinite(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    db_path = tmp_path / f"data_{day.date().isoformat()}.db"
    _create_sqlite_db(
        db_path,
        [
            (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
            (base_ts + 1, "ls218s", "Т1", SENTINEL, "K", "sensor_error"),
            (base_ts + 2, "ls218s", "Т1", float("inf"), "K", "overrange"),  # legacy raw inf
        ],
    )
    reader = ArchiveReader(data_dir=tmp_path, archive_dir=tmp_path / "arch")
    out: dict[str, list[tuple[float, float]]] = {}
    reader._query_sqlite(db_path, base_ts, base_ts + 10, None, out)

    vals = [v for _, v in out["Т1"]]
    assert 77.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"


def test_query_operator_log_reads_rotated_cold_day(tmp_path: Path) -> None:
    """operator_log rows survive cold rotation and reach query_operator_log.

    CR-3 preserves the operator_log audit trail as a companion Parquet when a
    daily SQLite file is rotated and deleted. This pins that query_operator_log
    reads it back — otherwise the archived audit trail is write-only.
    """
    import asyncio
    import json

    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)

    async def _seed_and_rotate() -> ColdRotationService:
        writer = SQLiteWriter(tmp_path)
        writer._write_batch(
            [
                Reading(
                    timestamp=day,
                    instrument_id="ls218s",
                    channel="T_STAGE",
                    value=4.3,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
        writer._write_operator_log_entry(
            timestamp=day,
            experiment_id="exp-1",
            author="operator",
            source="gui",
            message="cooldown start",
            tags=("cooldown", "note"),
        )
        await writer.stop()
        service = ColdRotationService(
            data_dir=tmp_path, archive_dir=tmp_path / "archive", age_days=30
        )
        results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert results, "old day must have rotated to Parquet"
        return service

    asyncio.run(_seed_and_rotate())
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    reader = ArchiveReader(data_dir=tmp_path, archive_dir=tmp_path / "archive")
    rows = reader.query_operator_log(
        day.replace(hour=0, minute=0), day.replace(hour=23, minute=59)
    )
    assert len(rows) == 1, "rotated cold operator_log entry must be readable"
    ts, exp_id, author, source, message, tags = rows[0]
    assert exp_id == "exp-1"
    assert author == "operator"
    assert source == "gui"
    assert message == "cooldown start"
    assert json.loads(tags) == ["cooldown", "note"]


def test_query_operator_log_unions_hot_and_cold(tmp_path: Path) -> None:
    """A hot day and a rotated cold day both surface, time-ordered."""
    import asyncio

    cold_day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    hot_day = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)

    async def _seed() -> None:
        writer = SQLiteWriter(tmp_path)
        writer._write_operator_log_entry(
            timestamp=cold_day,
            experiment_id=None,
            author="op",
            source="gui",
            message="cold entry",
            tags=(),
        )
        writer._write_batch(
            [
                Reading(
                    timestamp=cold_day,
                    instrument_id="ls",
                    channel="T",
                    value=1.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
        writer._write_operator_log_entry(
            timestamp=hot_day,
            experiment_id="exp-2",
            author="op",
            source="gui",
            message="hot entry",
            tags=(),
        )
        await writer.stop()
        service = ColdRotationService(
            data_dir=tmp_path, archive_dir=tmp_path / "archive", age_days=30
        )
        # cold_day is >30d before "now"; hot_day is within 30d → stays hot.
        results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert results

    asyncio.run(_seed())
    assert not (tmp_path / "data_2026-04-14.db").exists()
    assert (tmp_path / "data_2026-05-30.db").exists()

    reader = ArchiveReader(data_dir=tmp_path, archive_dir=tmp_path / "archive")
    rows = reader.query_operator_log(cold_day.replace(hour=0), hot_day.replace(hour=23))
    messages = [r[4] for r in rows]
    assert messages == ["cold entry", "hot entry"], f"union/order wrong: {messages}"


def test_query_operator_log_no_archive_dir(tmp_path: Path) -> None:
    """No archive dir → hot-only, no crash (behaviour parity pin)."""
    import asyncio

    day = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)

    async def _seed() -> None:
        writer = SQLiteWriter(tmp_path)
        writer._write_operator_log_entry(
            timestamp=day,
            experiment_id="exp-3",
            author="op",
            source="gui",
            message="hot only",
            tags=(),
        )
        await writer.stop()

    asyncio.run(_seed())
    reader = ArchiveReader(data_dir=tmp_path, archive_dir=tmp_path / "archive")
    rows = reader.query_operator_log(day.replace(hour=0), day.replace(hour=23))
    assert [r[4] for r in rows] == ["hot only"]


# ---------------------------------------------------------------------------
# F2: query() (archived-wins-else-hot) and query_operator_log() (skips hot for
# rotated days) must, like query_rows(), UNION a restored/backdated hot DB with
# the archive for an overlap day — else the restored rows are silently shadowed
# on the history + journal paths while exports (query_rows) already see them.
# ---------------------------------------------------------------------------


def test_query_and_operator_log_union_restored_hot_over_archived_day(tmp_path: Path) -> None:
    import asyncio

    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    dup_ts = day.replace(hour=12)
    new_ts = day.replace(hour=13)
    db_name = "data_2026-04-14.db"
    archive_dir = tmp_path / "archive"

    async def _seed_rotate() -> None:
        writer = SQLiteWriter(tmp_path)
        writer._write_batch([Reading(dup_ts, "ls", "T", 1.0, "K", ChannelStatus.OK)])
        writer._write_operator_log_entry(
            timestamp=dup_ts, experiment_id=None, author="op", source="gui", message="orig", tags=()
        )
        await writer.stop()
        svc = ColdRotationService(data_dir=tmp_path, archive_dir=archive_dir, age_days=30)
        assert await svc.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))

    asyncio.run(_seed_rotate())
    assert not (tmp_path / db_name).exists(), "rotation must delete the hot DB"

    async def _restore_backdated() -> None:
        writer = SQLiteWriter(tmp_path)
        writer._write_batch(
            [
                Reading(dup_ts, "ls", "T", 1.0, "K", ChannelStatus.OK),  # exact duplicate
                Reading(new_ts, "ls", "T", 2.5, "K", ChannelStatus.OK),  # restored-only
            ]
        )
        writer._write_operator_log_entry(
            timestamp=dup_ts, experiment_id=None, author="op", source="gui", message="orig", tags=()
        )  # duplicate
        writer._write_operator_log_entry(
            timestamp=new_ts, experiment_id=None, author="op", source="gui", message="restored", tags=()
        )  # restored-only
        await writer.stop()

    asyncio.run(_restore_backdated())
    assert (tmp_path / db_name).exists(), "backdated hot DB now overlaps the archive"

    reader = ArchiveReader(data_dir=tmp_path, archive_dir=archive_dir)

    # query(): restored reading must surface; the exact-key duplicate dedups to one.
    res = reader.query(["T"], day.replace(hour=0), day.replace(hour=23))
    vals = sorted(v for _t, v in res["T"])
    assert vals == [1.0, 2.5], f"query() must union restored hot over archive, got {vals}"

    # query_operator_log(): restored journal entry must surface, duplicate deduped.
    ol = reader.query_operator_log(day.replace(hour=0), day.replace(hour=23))
    msgs = sorted(r[4] for r in ol)
    assert msgs == ["orig", "restored"], f"operator_log must union+dedup, got {msgs}"


def test_query_parquet_masks_nonfinite(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    parquet_path = tmp_path / "arch" / "cold.parquet"
    _create_parquet(
        parquet_path,
        [
            (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
            (base_ts + 1, "ls218s", "Т1", SENTINEL, "K", "sensor_error"),
            (base_ts + 2, "ls218s", "Т1", float("inf"), "K", "overrange"),
        ],
    )
    reader = ArchiveReader(data_dir=tmp_path, archive_dir=tmp_path / "arch")
    out: dict[str, list[tuple[float, float]]] = {}
    reader._query_parquet("cold.parquet", base_ts, base_ts + 10, None, out)

    vals = [v for _, v in out["Т1"]]
    assert 77.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"
