"""Tests for ReplaySource — historical SQLite data → DataBroker replay."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.replay import ReplaySource
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime,
    instrument_id: str = "ls218s",
) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _make_db(tmp_path: Path, readings: list[Reading]) -> Path:
    """Write readings to a SQLite daily file, return the db path."""
    writer = SQLiteWriter(tmp_path)
    writer._write_batch(readings)
    day = readings[0].timestamp.date()
    db_path = tmp_path / f"data_{day.isoformat()}.db"
    writer._conn = None  # release connection
    return db_path


def _fixed_ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 3, 14, hour, minute, second, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 1. replay publishes all readings to broker
# ---------------------------------------------------------------------------


async def test_replay_publishes_readings(tmp_path: Path) -> None:
    readings = [
        _reading("CH1", 4.1, ts=_fixed_ts(10, 0, 0)),
        _reading("CH2", 4.2, ts=_fixed_ts(10, 0, 1)),
        _reading("CH3", 4.3, ts=_fixed_ts(10, 0, 2)),
    ]
    db_path = _make_db(tmp_path, readings)

    broker = DataBroker()
    queue = await broker.subscribe("test_sub", maxsize=100)

    replay = ReplaySource(broker, speed=0.0)
    count = await replay.play(db_path)

    assert count == 3, f"Expected 3 replayed readings, got {count}"
    assert queue.qsize() == 3, f"Expected 3 items in queue, got {queue.qsize()}"

    # Verify the values are intact
    received = [queue.get_nowait() for _ in range(3)]
    values = {r.channel: r.value for r in received}
    assert abs(values["CH1"] - 4.1) < 1e-9
    assert abs(values["CH2"] - 4.2) < 1e-9
    assert abs(values["CH3"] - 4.3) < 1e-9


# ---------------------------------------------------------------------------
# 2. speed=0 replays without sleeping (completes essentially instantly)
# ---------------------------------------------------------------------------


async def test_replay_speed_zero(tmp_path: Path) -> None:
    import time

    # Use timestamps far apart — if speed > 0 this would take a long time
    readings = [
        _reading("CH1", ts=_fixed_ts(0, 0, 0)),
        _reading("CH2", ts=_fixed_ts(6, 0, 0)),  # 6 hours later
        _reading("CH3", ts=_fixed_ts(12, 0, 0)),  # 12 hours later
    ]
    db_path = _make_db(tmp_path, readings)

    broker = DataBroker()
    await broker.subscribe("test_sub", maxsize=100)

    replay = ReplaySource(broker, speed=0.0)

    t0 = time.monotonic()
    await replay.play(db_path)
    elapsed = time.monotonic() - t0

    # With speed=0 there are no asyncio.sleep() calls; should complete in << 1s
    assert elapsed < 2.0, f"speed=0 replay took {elapsed:.2f}s (expected < 2s)"


# ---------------------------------------------------------------------------
# 3. Replayed count matches the number of rows written to the DB
# ---------------------------------------------------------------------------


async def test_replay_count(tmp_path: Path) -> None:
    n = 20
    _fixed_ts(10)
    readings = [
        _reading(f"CH{i % 8 + 1}", float(i), ts=datetime(2026, 3, 14, 10, 0, i, tzinfo=UTC))
        for i in range(n)
    ]
    db_path = _make_db(tmp_path, readings)

    broker = DataBroker()
    await broker.subscribe("test_sub", maxsize=200)

    replay = ReplaySource(broker, speed=0.0)
    count = await replay.play(db_path)

    assert count == n, f"Expected {n} replayed rows, got {count}"
    assert replay.total_replayed == n


# ---------------------------------------------------------------------------
# 4. FileNotFoundError on nonexistent file
# ---------------------------------------------------------------------------


async def test_replay_missing_file(tmp_path: Path) -> None:
    broker = DataBroker()
    replay = ReplaySource(broker, speed=0.0)

    with pytest.raises(FileNotFoundError):
        await replay.play(tmp_path / "nonexistent.db")


# ---------------------------------------------------------------------------
# 5. stop() mid-replay halts publishing
# ---------------------------------------------------------------------------


async def test_replay_stop(tmp_path: Path) -> None:
    # Use a small number of readings and a non-zero speed so the loop contains
    # real asyncio.sleep() calls — giving stop() a guaranteed opportunity to run.
    # Timestamps are 1 second apart; speed=100 means each sleep is 10 ms.
    n = 10
    readings = [
        _reading("CH1", float(i), ts=datetime(2026, 3, 14, 10, 0, i, tzinfo=UTC)) for i in range(n)
    ]
    db_path = _make_db(tmp_path, readings)

    broker = DataBroker()
    await broker.subscribe("test_sub", maxsize=n + 10)

    replay = ReplaySource(broker, speed=100.0)  # 1 s apart → 10 ms sleep each

    # Launch play() as a background task
    play_task = asyncio.create_task(replay.play(db_path))

    # Wait long enough for at least one row to be published, then stop
    await asyncio.sleep(0.05)  # 50 ms — enough for a few 10 ms sleeps
    replay.stop()

    count = await play_task

    # At least one row was published but not all n
    assert 0 < count < n, (
        f"Expected stop() to halt replay between 1 and {n - 1} rows; got count={count}"
    )
    assert not replay._running, "replay._running should be False after stop()"
