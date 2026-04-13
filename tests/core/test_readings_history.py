"""Tests for readings_history engine command and SQLiteWriter.read_readings_history."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture()
def writer_with_data(tmp_path: Path):
    """Create a SQLiteWriter with sample readings already written."""
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
    """Read all history without filters."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    assert "Т1 Камера" in data
    assert "Т2 Экран" in data
    assert "P Камера" in data
    assert len(data["Т1 Камера"]) == 100


def test_read_readings_history_time_filter(writer_with_data) -> None:
    """Filter by from_ts should return only recent points."""
    writer, base_ts = writer_with_data
    from_ts = base_ts + 50 * 30  # midpoint
    data = writer._read_readings_history(from_ts=from_ts)
    # 50 points from midpoint onward (±1 for float precision)
    assert 49 <= len(data["Т1 Камера"]) <= 51


def test_read_readings_history_channel_filter(writer_with_data) -> None:
    """Filter by specific channels."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(channels=["Т1 Камера"])
    assert "Т1 Камера" in data
    assert "Т2 Экран" not in data
    assert "P Камера" not in data


def test_read_readings_history_limit(writer_with_data) -> None:
    """limit_per_channel truncates to latest N points."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(limit_per_channel=10)
    assert len(data["Т1 Камера"]) == 10
    # Should be the latest 10 points
    assert data["Т1 Камера"][-1][1] > data["Т1 Камера"][0][1]


def test_read_readings_history_sorted_asc(writer_with_data) -> None:
    """Points must be sorted by timestamp ASC."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    for ch, points in data.items():
        timestamps = [ts for ts, _ in points]
        assert timestamps == sorted(timestamps), f"Channel {ch} not sorted ASC"


@pytest.mark.asyncio
async def test_async_read_readings_history(writer_with_data) -> None:
    """Async wrapper must return the same data."""
    writer, base_ts = writer_with_data
    data = await writer.read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
    assert len(data["Т1 Камера"]) == 5
