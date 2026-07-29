"""A6: locked-DB parity and retained retry for live reading batches.

Transient `database is locked`/`busy` failures retry the same batch. A sustained
lock routes into _signal_persistence_failure like disk-full does at >= 3
consecutive failures spanning >= 15s. Both threshold conditions must hold.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage import sqlite_writer as sqlite_writer_module
from cryodaq.storage.sqlite_writer import SQLiteWriter


def _reading(channel: str = "Т1", value: float = 4.5) -> Reading:
    return Reading(
        channel=channel,
        value=value,
        unit="K",
        instrument_id="ls218",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        raw=value,
        metadata={},
    )


def _poisoned_conn(side_effect: Exception) -> MagicMock:
    """Build a fake sqlite3.Connection whose executemany raises *side_effect*."""
    conn = MagicMock(spec=sqlite3.Connection)
    conn.executemany = MagicMock(side_effect=side_effect)
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


def _healthy_conn() -> MagicMock:
    """Build a fake sqlite3.Connection whose write succeeds."""
    conn = MagicMock(spec=sqlite3.Connection)
    conn.executemany = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


def _fake_clock(monkeypatch: pytest.MonkeyPatch, times: list[float]) -> None:
    """Feed successive time.monotonic() values from *times*, in order."""
    it = iter(times)
    monkeypatch.setattr(sqlite_writer_module.time, "monotonic", lambda: next(it))


def test_sustained_locked_batch_spanning_15s_signals_fault(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", lambda _seconds: None)
    _fake_clock(monkeypatch, [0.0, 8.0, 15.0])

    poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
    persisted = writer._write_day_batch(poisoned, [_reading()])

    assert persisted is False
    signal.assert_called_once()
    assert "database locked; batch not persisted" in signal.call_args[0][0].lower()


def test_three_locked_failures_within_15s_retry_to_success(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", lambda _seconds: None)
    _fake_clock(monkeypatch, [0.0, 5.0, 10.0])

    transient = _healthy_conn()
    transient.executemany.side_effect = [
        sqlite3.OperationalError("database is busy"),
        sqlite3.OperationalError("database is busy"),
        sqlite3.OperationalError("database is busy"),
        None,
    ]
    persisted = writer._write_day_batch(transient, [_reading()])

    assert persisted is True
    signal.assert_not_called()


def test_two_failures_success_two_failures_does_not_signal(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", lambda _seconds: None)
    # Two failures spanning 8s, a success, then two more failures spanning
    # 8s. Total elapsed since the first failure is well over 15s, but the
    # success must break the streak — neither half reaches 3 consecutive.
    _fake_clock(monkeypatch, [0.0, 8.0, 20.0, 28.0])

    first = _healthy_conn()
    first.executemany.side_effect = [
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database is locked"),
        None,
    ]
    second = _healthy_conn()
    second.executemany.side_effect = [
        sqlite3.OperationalError("database is locked"),
        sqlite3.OperationalError("database is locked"),
        None,
    ]
    assert writer._write_day_batch(first, [_reading()]) is True
    assert writer._write_day_batch(second, [_reading()]) is True

    signal.assert_not_called()


def test_successful_write_resets_tracking(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", lambda _seconds: None)
    _fake_clock(monkeypatch, [0.0])

    transient = _healthy_conn()
    transient.executemany.side_effect = [
        sqlite3.OperationalError("database is locked"),
        None,
    ]
    assert writer._write_day_batch(transient, [_reading()]) is True
    assert writer._locked_failure_count == 0
    assert writer._locked_failure_first_ts is None


def test_other_operational_errors_still_raise_and_do_not_track(tmp_path):
    """Non-locked, non-disk OperationalErrors keep existing raise semantics
    and must not perturb the locked-DB streak."""
    writer = SQLiteWriter(tmp_path)

    poisoned = _poisoned_conn(sqlite3.OperationalError("table readings has no column foo"))
    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned, [_reading()])

    assert writer._locked_failure_count == 0
    assert writer._locked_failure_first_ts is None


# ---------------------------------------------------------------------------
# F1 (Phase A gate, CRITICAL): persistence-first violation on locked-DB.
#
# A locked/busy write_immediate failure is swallowed WITHOUT re-raising (see
# above) even a single time, below the A6 signalling threshold. The writer
# must report that the batch was NOT durably persisted so the scheduler can
# skip publishing it to any broker — publishing an unwritten batch breaks the
# "if a broker has a reading, it was already written to SQLite" invariant.
#
# R1 (Phase A recheck, CRITICAL): that result must be the return value of
# write_immediate()/_write_batch()/_write_day_batch(), local to each call —
# NOT shared writer state. Multiple scheduler poll tasks can share one
# SQLiteWriter and its single-worker executor; a shared flag lets a later
# call's success reset an earlier call's drop before that caller checks it.
# ---------------------------------------------------------------------------


def test_single_locked_failure_is_retried_not_dropped(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", lambda _seconds: None)
    _fake_clock(monkeypatch, [0.0])

    transient = _healthy_conn()
    transient.executemany.side_effect = [
        sqlite3.OperationalError("database is locked"),
        None,
    ]
    persisted = writer._write_day_batch(transient, [_reading()])

    assert persisted is True
    signal.assert_not_called()


def test_healthy_write_succeeds_without_retry_delay(tmp_path, monkeypatch):
    """A normal real write commits without entering the lock retry delay."""
    writer = SQLiteWriter(tmp_path)
    retry_delay = MagicMock(side_effect=AssertionError("healthy write entered locked retry delay"))
    monkeypatch.setattr(sqlite_writer_module.time, "sleep", retry_delay)

    persisted = writer._write_batch([_reading()])

    assert persisted is True
    retry_delay.assert_not_called()


async def test_locked_write_retries_same_batch_until_durable(tmp_path):
    """A transient real SQLite writer lock must delay, not discard, the batch."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    reading = _reading()
    owned = writer._ensure_connection(reading.timestamp.date())
    owned.execute("PRAGMA busy_timeout=25")
    database = tmp_path / f"data_{reading.timestamp.date().isoformat()}.db"
    lock = sqlite3.connect(database)
    lock.execute("BEGIN IMMEDIATE")

    write = asyncio.create_task(writer.write_immediate([reading]))
    await asyncio.sleep(0.1)
    lock.rollback()
    lock.close()

    assert await write is True
    row = owned.execute(
        "SELECT instrument_id, channel, value FROM readings WHERE timestamp=?",
        (reading.timestamp.timestamp(),),
    ).fetchone()
    assert row == (reading.instrument_id, reading.channel, reading.value)
    await writer.stop()


async def test_sustained_real_lock_faults_without_claiming_persistence(tmp_path, monkeypatch):
    """A real lock held past the policy boundary returns False and signals."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    reading = _reading()
    owned = writer._ensure_connection(reading.timestamp.date())
    owned.execute("PRAGMA busy_timeout=10")
    database = tmp_path / f"data_{reading.timestamp.date().isoformat()}.db"
    lock = sqlite3.connect(database)
    lock.execute("BEGIN IMMEDIATE")
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    monkeypatch.setattr(sqlite_writer_module, "_LOCKED_FAILURE_SPAN_S", 0.05)
    monkeypatch.setattr(sqlite_writer_module, "_LOCKED_RETRY_DELAY_S", 0.01)

    persisted = await writer.write_immediate([reading])

    assert persisted is False
    signal.assert_called_once()
    assert "database locked; batch not persisted" in signal.call_args.args[0]
    lock.rollback()
    lock.close()
    await writer.stop()


def test_other_operational_error_raise_path_propagates(tmp_path):
    """The existing raise-through path for unrelated OperationalErrors is
    unaffected — the caller sees the exception directly, no return value."""
    writer = SQLiteWriter(tmp_path)

    poisoned = _poisoned_conn(sqlite3.OperationalError("table readings has no column foo"))
    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned, [_reading()])


async def test_interleaved_write_immediate_first_retry_not_masked_by_second_success(tmp_path):
    """Each queued call returns only after its own retained batch commits."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    real_write_batch = writer._write_batch
    calls = 0

    def fake_write_batch(batch):
        nonlocal calls
        calls += 1
        if calls == 1:
            transient = _healthy_conn()
            transient.executemany.side_effect = [
                sqlite3.OperationalError("database is locked"),
                None,
            ]
            return writer._write_day_batch(transient, batch)
        # Call B: real, healthy write.
        return real_write_batch(batch)

    with patch.object(writer, "_write_batch", side_effect=fake_write_batch):
        persisted_a = await writer.write_immediate([_reading()])
        persisted_b = await writer.write_immediate([_reading()])

    assert persisted_a is True, "call A must report its own retained retry"
    assert persisted_b is True, "call B must report its own success"

    await writer.stop()
