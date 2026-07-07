"""Tests for ReplaySource — historical SQLite data → DataBroker replay."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.replay import ReplaySource
from cryodaq.storage.sentinel import SENTINEL
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
    if writer._conn is not None:
        writer._conn.close()  # close, don't just drop the ref — Windows locks open DB files
    writer._conn = None
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


async def test_replay_stop(tmp_path: Path, monkeypatch) -> None:
    """stop() halts replay deterministically while it is parked inside asyncio.sleep.

    Strategy: monkeypatch cryodaq.storage.replay.asyncio.sleep so the FIRST
    call sets a ``sleep_started`` event and then blocks on a ``release`` event.
    We await ``sleep_started``, call ``replay.stop()``, then release — verifying
    that fewer than all rows were emitted.
    """
    import cryodaq.storage.replay as replay_module

    n = 10
    readings = [
        _reading("CH1", float(i), ts=datetime(2026, 3, 14, 10, 0, i, tzinfo=UTC)) for i in range(n)
    ]
    db_path = _make_db(tmp_path, readings)

    sleep_started = asyncio.Event()
    release = asyncio.Event()
    original_sleep = asyncio.sleep

    async def _controlled_sleep(delay, *args, **kwargs):
        if not sleep_started.is_set():
            sleep_started.set()
            await asyncio.wait_for(release.wait(), timeout=5.0)
        else:
            # Subsequent sleeps: honour them normally (replay already stopped,
            # this path is only reached if stop() didn't work — let it time out).
            await original_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(replay_module.asyncio, "sleep", _controlled_sleep)

    broker = DataBroker()
    await broker.subscribe("test_sub", maxsize=n + 10)

    replay = ReplaySource(broker, speed=1.0)  # speed>0 → sleep is called between rows
    play_task = asyncio.create_task(replay.play(db_path))

    # Wait for replay to park inside the first sleep
    await asyncio.wait_for(sleep_started.wait(), timeout=5.0)

    # First row was published before sleep; call stop while parked
    replay.stop()

    # Release the blocked sleep so replay can observe _running=False and break
    release.set()

    count = await asyncio.wait_for(play_task, timeout=5.0)

    # Replay emitted the first row (before sleeping), then stopped — count < n
    assert 0 < count < n, (
        f"stop() while parked in sleep must limit emitted count; got count={count} (n={n})"
    )


# ---------------------------------------------------------------------------
# NaN-доктрина: a replayed sentinel/error row publishes NaN, never the sentinel
# ---------------------------------------------------------------------------


async def test_replay_masks_sentinel_value(tmp_path: Path) -> None:
    readings = [
        _reading("CH1", 4.5, ts=_fixed_ts(10, 0, 0)),
        Reading(
            timestamp=_fixed_ts(10, 0, 1),
            instrument_id="ls218s",
            channel="CH1",
            value=float("nan"),
            unit="K",
            status=ChannelStatus.SENSOR_ERROR,
        ),
    ]
    db_path = _make_db(tmp_path, readings)

    broker = DataBroker()
    queue = await broker.subscribe("test_sub", maxsize=100)
    replay = ReplaySource(broker, speed=0.0)
    count = await replay.play(db_path)

    received = [queue.get_nowait() for _ in range(count)]
    values = [r.value for r in received]
    assert SENTINEL not in values, "sentinel republished to broker"
    assert not any(math.isinf(v) for v in values), "inf republished to broker"
    bad = [r.value for r in received if r.status is ChannelStatus.SENSOR_ERROR]
    assert bad and all(math.isnan(v) for v in bad), "error row must republish as NaN"
