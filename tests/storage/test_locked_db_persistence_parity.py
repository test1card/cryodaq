"""A6: locked-DB parity — sustained `database is locked`/`busy` write_immediate
failures must route into _signal_persistence_failure, like disk-full does.

Threshold: >= 3 CONSECUTIVE failures spanning >= 15s. Both conditions must
hold — a burst of quick transient failures or sporadic non-consecutive
failures must NOT signal. A successful write resets the tracking.
"""

from __future__ import annotations

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


def test_three_consecutive_locked_failures_spanning_15s_signals(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    _fake_clock(monkeypatch, [0.0, 8.0, 15.0])

    for _ in range(3):
        poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
        writer._write_day_batch(poisoned, [_reading()])

    signal.assert_called_once()
    assert "database locked" in signal.call_args[0][0].lower()


def test_three_consecutive_locked_failures_within_15s_does_not_signal(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    _fake_clock(monkeypatch, [0.0, 5.0, 10.0])

    for _ in range(3):
        poisoned = _poisoned_conn(sqlite3.OperationalError("database is busy"))
        writer._write_day_batch(poisoned, [_reading()])

    signal.assert_not_called()


def test_two_failures_success_two_failures_does_not_signal(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    signal = MagicMock()
    monkeypatch.setattr(writer, "_signal_persistence_failure", signal)
    # Two failures spanning 8s, a success, then two more failures spanning
    # 8s. Total elapsed since the first failure is well over 15s, but the
    # success must break the streak — neither half reaches 3 consecutive.
    _fake_clock(monkeypatch, [0.0, 8.0, 20.0, 28.0])

    for _ in range(2):
        poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
        writer._write_day_batch(poisoned, [_reading()])

    writer._write_day_batch(_healthy_conn(), [_reading()])

    for _ in range(2):
        poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
        writer._write_day_batch(poisoned, [_reading()])

    signal.assert_not_called()


def test_successful_write_resets_tracking(tmp_path, monkeypatch):
    writer = SQLiteWriter(tmp_path)
    _fake_clock(monkeypatch, [0.0])

    poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
    writer._write_day_batch(poisoned, [_reading()])
    assert writer._locked_failure_count == 1
    assert writer._locked_failure_first_ts == 0.0

    writer._write_day_batch(_healthy_conn(), [_reading()])
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


def test_single_locked_failure_below_threshold_returns_not_persisted(tmp_path, monkeypatch):
    """Even a single (non-signalling) locked failure must report the batch
    as NOT persisted via the return value — the scheduler must not publish
    it regardless of whether the A6 threshold was crossed."""
    writer = SQLiteWriter(tmp_path)
    monkeypatch.setattr(writer, "_signal_persistence_failure", MagicMock())
    _fake_clock(monkeypatch, [0.0])

    poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
    persisted = writer._write_day_batch(poisoned, [_reading()])

    assert persisted is False, (
        "A swallowed locked-DB failure must report not-persisted via the "
        "return value, even below the signalling threshold (F1)"
    )


def test_write_batch_returns_true_on_healthy_write(tmp_path):
    """_write_batch() reports persistence per call via its return value — a
    real, healthy write against tmp_path must return True."""
    writer = SQLiteWriter(tmp_path)

    persisted = writer._write_batch([_reading()])

    assert persisted is True


def test_other_operational_error_raise_path_propagates(tmp_path):
    """The existing raise-through path for unrelated OperationalErrors is
    unaffected — the caller sees the exception directly, no return value."""
    writer = SQLiteWriter(tmp_path)

    poisoned = _poisoned_conn(sqlite3.OperationalError("table readings has no column foo"))
    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned, [_reading()])


async def test_interleaved_write_immediate_first_drop_not_masked_by_second_success(tmp_path):
    """R1 residual (Phase A recheck, CRITICAL): concurrent scheduler poll
    tasks share one SQLiteWriter and its single-worker executor. Call A's
    write_immediate() drops its batch (locked/busy, swallowed); call B's
    write_immediate() succeeds right after, on the same writer. A's return
    value must still be False — a shared `_last_batch_dropped` flag would
    let B's success reset it before A's caller ever checked it. Sequential
    direct calls are enough: no real thread race is needed to show the
    result is bound per-call, not shared mutable writer state.
    """
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    real_write_batch = writer._write_batch
    calls = 0

    def fake_write_batch(batch):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Call A: simulate the swallowed locked/busy failure directly
            # against a poisoned connection, bypassing real disk I/O.
            poisoned = _poisoned_conn(sqlite3.OperationalError("database is locked"))
            return writer._write_day_batch(poisoned, batch)
        # Call B: real, healthy write.
        return real_write_batch(batch)

    with patch.object(writer, "_write_batch", side_effect=fake_write_batch):
        persisted_a = await writer.write_immediate([_reading()])
        persisted_b = await writer.write_immediate([_reading()])

    assert persisted_a is False, "call A must report its own drop"
    assert persisted_b is True, "call B's success must not affect A's result"

    await writer.stop()
