"""Tests for readings_history engine command and SQLiteWriter.read_readings_history."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
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

    base_ts = time.time() - 7200  # 2 hours ago
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
    """Filter by from_ts should return only recent points with correct values."""
    writer, base_ts = writer_with_data
    from_ts = base_ts + 50 * 30  # midpoint — rows 50..99
    data = writer._read_readings_history(from_ts=from_ts)
    # 50 points from midpoint onward (±1 for float precision)
    assert 49 <= len(data["Т1 Камера"]) <= 51, (
        f"Expected ~50 points after midpoint filter, got {len(data['Т1 Камера'])}"
    )
    points = data["Т1 Камера"]
    # All returned timestamps must be >= from_ts
    for ts, _ in points:
        assert ts >= from_ts - 1.0, f"Timestamp {ts} before from_ts {from_ts}"
    # Values must correspond to rows 50+ (value = 4.2 + i * 0.01, i >= 50)
    assert points[0][1] >= 4.2 + 50 * 0.01 - 1e-6, (
        f"First filtered value must be >= {4.2 + 50 * 0.01:.4f}, got {points[0][1]}"
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
