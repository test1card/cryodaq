"""Tests for the persistence-first ordering guarantee.

Key invariant: data is written to SQLite BEFORE it is published to subscribers.
If the write fails, subscribers must not receive the reading.

These tests verify:
  - write_immediate() blocks until WAL commit before returning
  - failed writes suppress broker publication
  - if a subscriber sees a reading, it is already on disk
  - write_immediate() tolerates slow writes (no premature timeout)
  - old queue-based start() API still works
  - start_immediate() creates the data directory on demand
  - Scheduler with sqlite_writer=None still publishes (backward compat)
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockDriver(InstrumentDriver):
    """Minimal concrete driver used by persistence-ordering tests."""

    def __init__(self) -> None:
        super().__init__("mock", mock=True)

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return [Reading.now("CH1", 4.2, "K", instrument_id="mock")]


def _make_batch(n: int) -> list[Reading]:
    """Create a batch of n readings with instrument_id set."""
    ts = datetime.now(UTC)
    return [
        Reading(
            timestamp=ts,
            instrument_id="mock",
            channel=f"CH{i + 1}",
            value=4.0 + i * 0.01,
            unit="K",
            status=ChannelStatus.OK,
        )
        for i in range(n)
    ]


def _count_rows(db_path: Path) -> int:
    """Return the number of rows in the readings table of the given DB."""
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    finally:
        conn.close()
    return count


def _db_path_for_writer(writer: SQLiteWriter, ts: datetime) -> Path:
    """Derive the expected DB file path for a given timestamp."""
    return writer._data_dir / f"data_{ts.date().isoformat()}.db"


# ---------------------------------------------------------------------------
# 1. write_immediate blocks until WAL commit — rows visible on return
# ---------------------------------------------------------------------------


async def test_write_immediate_persists_before_return(tmp_path: Path, monkeypatch) -> None:
    """write_immediate() must not return until all rows are committed to disk."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    batch = _make_batch(5)
    await writer.write_immediate(batch)

    # No sleep — if write_immediate truly awaits the commit, rows exist NOW.
    db_path = _db_path_for_writer(writer, batch[0].timestamp)
    assert db_path.exists(), f"DB file not created: {db_path}"
    assert _count_rows(db_path) == 5, (
        f"Expected 5 rows immediately after write_immediate, found {_count_rows(db_path)}"
    )

    await writer.stop()


# ---------------------------------------------------------------------------
# 2. Failed write suppresses broker publication
# ---------------------------------------------------------------------------


async def test_write_immediate_failure_does_not_publish(tmp_path: Path, monkeypatch) -> None:
    """If SQLite write raises, the reading must not reach any subscriber."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    broker = DataBroker()
    test_queue = await broker.subscribe("test_consumer", maxsize=100)

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    driver = MockDriver()
    sched = Scheduler(broker, sqlite_writer=writer)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.05))

    # Patch _write_batch to always raise — simulates a disk error.
    with patch.object(writer, "_write_batch", side_effect=RuntimeError("disk full")):
        await sched.start()
        # Give the scheduler enough time for at least one poll attempt.
        await asyncio.sleep(0.3)
        await sched.stop()

    # The subscriber queue must be empty: no unpersisted data may be published.
    assert test_queue.empty(), (
        f"Expected empty queue after write failure, but got {test_queue.qsize()} items"
    )

    await writer.stop()


# ---------------------------------------------------------------------------
# 3. If broker has a reading, it is already on disk
# ---------------------------------------------------------------------------


async def test_ordering_guarantee_write_before_zmq(tmp_path: Path, monkeypatch) -> None:
    """Persistence-before-publish is deterministically verified.

    Strategy:
    1. Wrap write_immediate so it blocks on a gate Event before completing.
    2. Start the scheduler and wait until _write_batch has been entered
       (write is in progress but not yet committed).
    3. Assert the subscriber queue is STILL EMPTY — no publish has happened yet.
    4. Release the gate so the write completes.
    5. Assert the exact reading now appears in the subscriber queue AND is on disk.

    This proves the ordering guarantee: the scheduler does NOT publish until
    write_immediate returns, regardless of timing.
    Note: we cannot introduce a src/ change, so we wrap at the test level.
    """
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    broker = DataBroker()
    test_queue = await broker.subscribe("test_consumer", maxsize=100)

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    # Gate that blocks write_immediate mid-flight
    write_started = asyncio.Event()
    write_gate = asyncio.Event()

    original_write_immediate = writer.write_immediate

    async def gated_write_immediate(batch: list) -> None:
        write_started.set()           # signal: write has been entered
        await write_gate.wait()       # block until test releases
        await original_write_immediate(batch)

    writer.write_immediate = gated_write_immediate  # type: ignore[method-assign]

    driver = MockDriver()
    sched = Scheduler(broker, sqlite_writer=writer)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.05))

    await sched.start()
    try:
        # Wait until the first write_immediate has been entered
        await asyncio.wait_for(write_started.wait(), timeout=2.0)

        # Write is in progress but NOT yet committed → queue MUST be empty
        assert test_queue.empty(), (
            "Subscriber queue is non-empty while write_immediate is still blocked — "
            "publish happened BEFORE persistence (ordering violated)"
        )

        # Release the gate → write completes → publish proceeds
        write_gate.set()

        # Now a reading must appear in the queue
        reading = await asyncio.wait_for(test_queue.get(), timeout=2.0)
    finally:
        await sched.stop()

    # Restore original to avoid interference with writer.stop()
    writer.write_immediate = original_write_immediate  # type: ignore[method-assign]

    # The reading is in the queue — it must already be on disk
    db_path = _db_path_for_writer(writer, reading.timestamp)
    assert db_path.exists(), "DB file must exist before reading reaches subscriber"

    # Exact channel and value match (not just row count ≥ 1)
    assert reading.channel == "CH1", f"Unexpected channel: {reading.channel}"
    assert abs(reading.value - 4.2) < 1e-9, f"Unexpected value: {reading.value}"

    row_count = _count_rows(db_path)
    assert row_count >= 1, f"Expected at least 1 row in DB, found {row_count}"

    await writer.stop()


# ---------------------------------------------------------------------------
# 4. write_immediate waits for slow writes — no premature timeout
# ---------------------------------------------------------------------------


async def test_write_immediate_timeout_handling(tmp_path: Path, monkeypatch) -> None:
    """write_immediate() must wait for completion even when _write_batch is slow."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    original_write_batch = writer._write_batch

    def slow_write_batch(batch: list[Reading]) -> None:
        import time

        time.sleep(0.1)  # 100 ms — deliberate slow write in the executor thread
        original_write_batch(batch)

    batch = _make_batch(10)

    with patch.object(writer, "_write_batch", side_effect=slow_write_batch):
        # Must complete without raising and without truncating the batch.
        await writer.write_immediate(batch)

    db_path = _db_path_for_writer(writer, batch[0].timestamp)
    assert db_path.exists(), "DB file must exist after slow write_immediate"
    assert _count_rows(db_path) == 10, (
        f"Expected 10 rows after slow write, found {_count_rows(db_path)}"
    )

    await writer.stop()


# ---------------------------------------------------------------------------
# 5. Old queue-based start() API still works (backward compat)
# ---------------------------------------------------------------------------


async def test_backward_compat_queue_mode(tmp_path: Path, monkeypatch) -> None:
    """The queue-based start(queue) path must continue to work unchanged."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path, flush_interval_s=0.1)
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    await writer.start(queue)

    batch = _make_batch(3)
    for reading in batch:
        await queue.put(reading)

    # Wait for the flush interval to expire so the writer drains the queue.
    await asyncio.sleep(0.4)

    await writer.stop()

    db_path = _db_path_for_writer(writer, batch[0].timestamp)
    assert db_path.exists(), "DB file must be created by queue-mode writer"
    assert _count_rows(db_path) == 3, (
        f"Expected 3 rows after queue flush, found {_count_rows(db_path)}"
    )


# ---------------------------------------------------------------------------
# 6. start_immediate creates the data directory if it does not exist
# ---------------------------------------------------------------------------


async def test_start_immediate_creates_data_dir(tmp_path: Path, monkeypatch) -> None:
    """start_immediate() must create the data directory on demand."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    non_existent = tmp_path / "deep" / "nested" / "data"
    assert not non_existent.exists(), "Pre-condition: directory must not exist"

    writer = SQLiteWriter(non_existent)
    await writer.start_immediate()

    assert non_existent.exists(), (
        f"start_immediate() must create data_dir, but {non_existent} was not created"
    )
    assert writer._running is True, "start_immediate() must set _running = True"

    await writer.stop()


# ---------------------------------------------------------------------------
# 7. Scheduler with sqlite_writer=None still publishes (backward compat)
# ---------------------------------------------------------------------------


async def test_scheduler_without_writer_still_publishes(tmp_path: Path) -> None:
    """Scheduler(sqlite_writer=None) must behave exactly like the old Scheduler."""
    broker = DataBroker()
    test_queue = await broker.subscribe("no_writer_consumer", maxsize=100)

    driver = MockDriver()
    # Explicit sqlite_writer=None — should be identical to the old two-arg Scheduler.
    sched = Scheduler(broker, sqlite_writer=None)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=0.05))

    await sched.start()
    try:
        reading = await asyncio.wait_for(test_queue.get(), timeout=2.0)
    finally:
        await sched.stop()

    assert reading.channel == "CH1"
    assert abs(reading.value - 4.2) < 1e-9, f"Unexpected reading value: {reading.value}"
