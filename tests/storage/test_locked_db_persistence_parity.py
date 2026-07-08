"""A6: locked-DB parity — sustained `database is locked`/`busy` write_immediate
failures must route into _signal_persistence_failure, like disk-full does.

Threshold: >= 3 CONSECUTIVE failures spanning >= 15s. Both conditions must
hold — a burst of quick transient failures or sporadic non-consecutive
failures must NOT signal. A successful write resets the tracking.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock

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
