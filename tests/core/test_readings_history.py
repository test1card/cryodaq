"""Tests for readings_history engine command and SQLiteWriter.read_readings_history."""

from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sentinel import SENTINEL
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture()
def writer_with_data(tmp_path: Path):
    """Create a SQLiteWriter with sample readings already written."""
    # SQLiteWriter checks SQLite version at construction; bypass on known-broken
    # dev SQLite versions (same pattern as test_audit_fixes.py, test_experiment.py).
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())

    # Anchor to a whole second: row timestamps round-trip losslessly through
    # datetime.fromtimestamp (microsecond precision), so the inclusive-boundary
    # filter (timestamp >= base_ts + 50*30) lands deterministically on row 50.
    # A sub-second base_ts (raw time.time()) makes row 50's stored microsecond
    # value jitter above/below from_ts by its fractional part → flaky 49/50.
    base_ts = float(int(time.time()) - 7200)  # 2 hours ago, whole-second anchor
    readings: list[Reading] = []
    for i in range(100):
        ts = base_ts + i * 30  # every 30 seconds
        for ch_name in ["Т1 Камера", "Т2 Экран"]:
            r = Reading(
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
                instrument_id="LS218_1",
                channel=ch_name,
                value=4.2 + i * 0.01,
                unit="K",
                status=ChannelStatus.OK,
            )
            readings.append(r)
        # Pressure channel
        readings.append(
            Reading(
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
                instrument_id="VSP63D",
                channel="P Камера",
                value=1e-3 + i * 1e-5,
                unit="mbar",
                status=ChannelStatus.OK,
            )
        )

    loop.run_until_complete(writer.write_immediate(readings))
    yield writer, base_ts
    loop.run_until_complete(writer.stop())
    loop.close()


def test_read_readings_history_all(writer_with_data) -> None:
    """Read all history without filters — verify exact row count and value correctness."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    assert "Т1 Камера" in data
    assert "Т2 Экран" in data
    assert "P Камера" in data
    assert len(data["Т1 Камера"]) == 100
    # Verify exact values: row i should have value 4.2 + i * 0.01 (ASC order)
    points = data["Т1 Камера"]
    assert abs(points[0][1] - 4.2) < 1e-6, (
        f"First point value must be 4.2, got {points[0][1]}"
    )
    assert abs(points[-1][1] - (4.2 + 99 * 0.01)) < 1e-6, (
        f"Last point value must be {4.2 + 99 * 0.01:.4f}, got {points[-1][1]}"
    )
    # Verify timestamps: first point must be at base_ts (±1s for float precision)
    assert abs(points[0][0] - base_ts) < 1.0, (
        f"First timestamp must be near base_ts={base_ts}, got {points[0][0]}"
    )
    # Oldest point must be first, newest last
    assert points[0][0] < points[-1][0], "Points must be sorted oldest-first"


def test_read_readings_history_time_filter(writer_with_data) -> None:
    """Filter by from_ts returns exactly the rows at the inclusive boundary.

    base_ts is a float (time.time() - 7200) and each row is spaced exactly
    30 s apart, so from_ts = base_ts + 50*30 lands precisely on row index 50.
    SQLiteWriter uses timestamp >= ? (inclusive), so the result must be exactly
    50 rows: indices 50..99.  Allowing 49 would let a regression to
    timestamp > ? (exclusive) go undetected.
    """
    writer, base_ts = writer_with_data
    # Row i has timestamp base_ts + i * 30.  Row 50 is the exact boundary.
    from_ts = base_ts + 50 * 30
    data = writer._read_readings_history(from_ts=from_ts)
    points = data["Т1 Камера"]

    # Exactly 50 rows: indices 50..99 (inclusive lower bound).
    assert len(points) == 50, (
        f"Expected exactly 50 points after midpoint filter (timestamp >= boundary), "
        f"got {len(points)}"
    )
    # All returned timestamps must be >= from_ts (timestamps are exact multiples).
    for ts, _ in points:
        assert ts >= from_ts, f"Timestamp {ts} is before from_ts {from_ts}"
    # First returned point must be row 50: value = 4.2 + 50 * 0.01
    expected_first_value = 4.2 + 50 * 0.01
    assert abs(points[0][1] - expected_first_value) < 1e-6, (
        f"First filtered point must be row 50 (value={expected_first_value:.4f}), "
        f"got {points[0][1]}"
    )
    # Last returned point must be row 99: value = 4.2 + 99 * 0.01
    expected_last_value = 4.2 + 99 * 0.01
    assert abs(points[-1][1] - expected_last_value) < 1e-6, (
        f"Last filtered point must be row 99 (value={expected_last_value:.4f}), "
        f"got {points[-1][1]}"
    )


def test_read_readings_history_channel_filter(writer_with_data) -> None:
    """Filter by specific channels."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(channels=["Т1 Камера"])
    assert "Т1 Камера" in data
    assert "Т2 Экран" not in data
    assert "P Камера" not in data


def test_read_readings_history_limit(writer_with_data) -> None:
    """limit_per_channel truncates to latest N points with correct values."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(limit_per_channel=10)
    assert len(data["Т1 Камера"]) == 10, (
        f"Expected exactly 10 points with limit_per_channel=10, got {len(data['Т1 Камера'])}"
    )
    points = data["Т1 Камера"]
    # Must be the LATEST 10 points (rows 90..99)
    # Latest point value = 4.2 + 99 * 0.01
    expected_last = 4.2 + 99 * 0.01
    assert abs(points[-1][1] - expected_last) < 1e-5, (
        f"Last point must be the newest value {expected_last:.4f}, got {points[-1][1]}"
    )
    expected_first = 4.2 + 90 * 0.01
    assert abs(points[0][1] - expected_first) < 1e-5, (
        f"First of the 10 latest must be row 90 value {expected_first:.4f}, got {points[0][1]}"
    )
    # Sorted oldest-first within the returned window
    assert points[-1][1] > points[0][1], "Returned points must be sorted ascending by value/time"


def test_read_readings_history_sorted_asc(writer_with_data) -> None:
    """Points must be sorted by timestamp ASC."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    for ch, points in data.items():
        timestamps = [ts for ts, _ in points]
        assert timestamps == sorted(timestamps), f"Channel {ch} not sorted ASC"


def test_history_limit_floored_to_one(writer_with_data) -> None:
    """limit_per_channel <= 0 must floor to 1, not fall through to the full set.

    Regression guard for the ``result[-0:]`` Python quirk: a zero limit used to
    slice to the whole list and return every row (unbounded), the opposite of a
    limit. Fail-closed: a non-positive limit returns the single latest point.
    """
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(limit_per_channel=0)
    assert len(data["Т1 Камера"]) == 1, (
        f"limit_per_channel=0 must floor to 1 latest point, got {len(data['Т1 Камера'])}"
    )
    # The one returned point must be the newest (row 99).
    assert abs(data["Т1 Камера"][0][1] - (4.2 + 99 * 0.01)) < 1e-5


def test_history_channel_list_capped(writer_with_data) -> None:
    """A channel list longer than the cap is truncated; channels past the cap drop.

    Trust-boundary clamp: readings_history is reachable from unauthenticated
    loopback ZMQ, so an over-long channel list must be bounded. A real channel
    placed past the 64-channel cap must NOT come back.
    """
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_CHANNELS

    writer, base_ts = writer_with_data
    # 64 filler names, then a real channel at index 64 (just past the cap).
    channels = [f"fake_{i}" for i in range(_HISTORY_MAX_CHANNELS)] + ["Т1 Камера"]
    data = writer._read_readings_history(channels=channels)
    assert "Т1 Камера" not in data, (
        "channel past the cap must be dropped by the channel-list clamp"
    )


def test_history_clamps_hostile_request(writer_with_data) -> None:
    """limit=10_000_000 + 500 channels returns clamped, bounded counts, no error."""
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_ROWS

    writer, base_ts = writer_with_data
    channels = ["Т1 Камера", "Т2 Экран", "P Камера"] + [f"fake_{i}" for i in range(497)]
    data = writer._read_readings_history(channels=channels, limit_per_channel=10_000_000)
    # Real channels within the first 64 entries still return their (small) data.
    assert len(data["Т1 Камера"]) == 100
    # No channel exceeds the row cap.
    for ch, points in data.items():
        assert len(points) <= _HISTORY_MAX_ROWS


def test_mixed_rate_channels_each_get_their_limit(tmp_path: Path) -> None:
    """A fast channel must not crowd out a slow one's rows (mixed rates are
    normal: vacuum vs thermometry). 10 old rows on "quiet" + 100 newer rows
    on "noisy", limit_per_channel=10 -> BOTH channels return their latest 10.
    """
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        base_ts = float(int(time.time()) - 7200)
        readings: list[Reading] = []
        # 10 OLD rows on "quiet" (earliest timestamps).
        for i in range(10):
            readings.append(
                Reading(
                    timestamp=datetime.fromtimestamp(base_ts + i, tz=UTC),
                    instrument_id="VSP63D",
                    channel="quiet",
                    value=float(i),
                    unit="mbar",
                    status=ChannelStatus.OK,
                )
            )
        # 100 NEWER rows on "noisy" (all after the quiet rows).
        for i in range(100):
            readings.append(
                Reading(
                    timestamp=datetime.fromtimestamp(base_ts + 100 + i, tz=UTC),
                    instrument_id="LS218_1",
                    channel="noisy",
                    value=float(i),
                    unit="K",
                    status=ChannelStatus.OK,
                )
            )
        loop.run_until_complete(writer.write_immediate(readings))

        data = writer._read_readings_history(channels=["quiet", "noisy"], limit_per_channel=10)
        assert len(data.get("quiet", [])) == 10, (
            f"quiet channel crowded out: got {len(data.get('quiet', []))} rows"
        )
        assert len(data.get("noisy", [])) == 10, (
            f"noisy channel wrong count: got {len(data.get('noisy', []))} rows"
        )
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_read_readings_history_masks_sentinel(tmp_path: Path) -> None:
    """NaN-доктрина: a persisted sentinel/error row reads back as NaN, never as
    the raw sentinel — the GUI-reconnect history feed must not show a number."""
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        base_ts = float(int(time.time()) - 60)
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(base_ts, tz=UTC),
                        instrument_id="ls218s",
                        channel="CH1",
                        value=4.5,
                        unit="K",
                        status=ChannelStatus.OK,
                    ),
                    Reading(
                        timestamp=datetime.fromtimestamp(base_ts + 1, tz=UTC),
                        instrument_id="ls218s",
                        channel="CH1",
                        value=float("nan"),
                        unit="K",
                        status=ChannelStatus.SENSOR_ERROR,
                    ),
                ]
            )
        )
        data = writer._read_readings_history(channels=["CH1"])
        vals = [v for _, v in data["CH1"]]
        assert 4.5 in vals, "usable reading must survive"
        assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
        assert any(math.isnan(v) for v in vals), "sentinel row must read back as NaN"
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_read_readings_history_no_archive_unchanged(writer_with_data) -> None:
    """No archive → a from_ts far before any hot data is hot-only, unchanged.

    Pins the archive-aware branch to a strict no-op when no archive index
    exists (the default for every deployment with cold rotation OFF).
    """
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(from_ts=base_ts - 86400 * 5)
    assert len(data["Т1 Камера"]) == 100, "no-archive path must stay hot-only"


def test_read_readings_history_unions_cold_archive(tmp_path: Path) -> None:
    """A window reaching before the oldest hot day unions in rotated Parquet rows.

    Cold (archived) rows must appear alongside hot rows, sorted ASC, without
    double-reading hot days.
    """
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        now = datetime.now(UTC)
        # HOT: a row for today lands in data_<today>.db.
        hot_ts = now.timestamp() - 60
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(hot_ts, tz=UTC),
                        instrument_id="LS218_1",
                        channel="Т1",
                        value=10.0,
                        unit="K",
                        status=ChannelStatus.OK,
                    )
                ]
            )
        )
        # COLD: a row 3 days ago, only in the Parquet archive.
        cold_day = now - timedelta(days=3)
        cold_ts = cold_day.timestamp()
        archive_dir = tmp_path / "archive"
        rel = (
            f"year={cold_day:%Y}/month={cold_day:%m}/"
            f"data_{cold_day.date().isoformat()}.db.parquet"
        )
        ppath = archive_dir / rel
        ppath.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "timestamp": pa.array(
                    [datetime.fromtimestamp(cold_ts, tz=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array(["LS218_1"]),
                "channel": pa.array(["Т1"]),
                "value": pa.array([5.0], type=pa.float64()),
                "unit": pa.array(["K"]),
                "status": pa.array(["ok"]),
            }
        )
        pq.write_table(table, str(ppath))
        (archive_dir / "index.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "original_name": f"data_{cold_day.date().isoformat()}.db",
                            "archive_path": rel,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        data = writer._read_readings_history(
            from_ts=cold_ts - 10, to_ts=now.timestamp()
        )
        vals = [v for _, v in data["Т1"]]
        assert 5.0 in vals, "cold archived row must be unioned in"
        assert 10.0 in vals, "hot row must remain"
        # ASC order → cold (older) first, hot (newer) last.
        assert data["Т1"][0][1] == 5.0
        assert data["Т1"][-1][1] == 10.0
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_read_readings_history_unbounded_unions_cold_archive(tmp_path: Path) -> None:
    """F3: an unbounded (from_ts=None) request must also union cold archive rows.

    The cold branch was gated on ``from_ts is not None``, so a full-range /
    unbounded-past request read hot-only and silently dropped rotated days.
    from_ts=None means unbounded past → it ALWAYS reaches archived days.
    """
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        now = datetime.now(UTC)
        hot_ts = now.timestamp() - 60
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(hot_ts, tz=UTC),
                        instrument_id="LS218_1",
                        channel="Т1",
                        value=10.0,
                        unit="K",
                        status=ChannelStatus.OK,
                    )
                ]
            )
        )
        cold_day = now - timedelta(days=3)
        cold_ts = cold_day.timestamp()
        archive_dir = tmp_path / "archive"
        rel = (
            f"year={cold_day:%Y}/month={cold_day:%m}/"
            f"data_{cold_day.date().isoformat()}.db.parquet"
        )
        ppath = archive_dir / rel
        ppath.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "timestamp": pa.array(
                    [datetime.fromtimestamp(cold_ts, tz=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array(["LS218_1"]),
                "channel": pa.array(["Т1"]),
                "value": pa.array([5.0], type=pa.float64()),
                "unit": pa.array(["K"]),
                "status": pa.array(["ok"]),
            }
        )
        pq.write_table(table, str(ppath))
        (archive_dir / "index.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "original_name": f"data_{cold_day.date().isoformat()}.db",
                            "archive_path": rel,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        # from_ts unset (None) → unbounded past. Must still union the cold row.
        data = writer._read_readings_history(to_ts=now.timestamp())
        vals = [v for _, v in data["Т1"]]
        assert 5.0 in vals, "unbounded request must union the cold archived row"
        assert 10.0 in vals, "hot row must remain"
        assert data["Т1"][0][1] == 5.0, "ASC order: cold (older) first"
        assert data["Т1"][-1][1] == 10.0
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


@pytest.mark.asyncio
async def test_async_read_readings_history(writer_with_data) -> None:
    """Async wrapper must return the same data as the sync implementation."""
    writer, base_ts = writer_with_data
    # Get sync result for comparison
    sync_data = writer._read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
    # Get async result
    async_data = await writer.read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
    assert len(async_data["Т1 Камера"]) == 5, (
        f"Async wrapper must return 5 points, got {len(async_data['Т1 Камера'])}"
    )
    # Async and sync must return identical data
    assert async_data["Т1 Камера"] == sync_data["Т1 Камера"], (
        "Async wrapper must return identical data to sync implementation"
    )
