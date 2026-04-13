"""Verify disk-full detection and graceful degradation (Phase 2a H.1)."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
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


@pytest.mark.asyncio
async def test_disk_full_sets_flag_on_operational_error(tmp_path):
    """A disk-full OperationalError must set _disk_full and not re-raise."""
    writer = SQLiteWriter(tmp_path)

    poisoned = _poisoned_conn(sqlite3.OperationalError("database or disk is full"))

    # _write_day_batch is sync; it's the path that handles disk-full.
    writer._write_day_batch(poisoned, [_reading()])

    assert writer.is_disk_full is True, "disk_full flag must be set"
    poisoned.executemany.assert_called_once()


@pytest.mark.asyncio
async def test_persistence_failure_callback_invoked(tmp_path):
    """The async callback must be scheduled on the engine event loop."""
    writer = SQLiteWriter(tmp_path)
    writer.set_event_loop(asyncio.get_running_loop())

    callback_invoked = asyncio.Event()
    received_reasons: list[str] = []

    async def callback(reason: str) -> None:
        received_reasons.append(reason)
        callback_invoked.set()

    writer.set_persistence_failure_callback(callback)

    poisoned = _poisoned_conn(sqlite3.OperationalError("database or disk is full"))
    writer._write_day_batch(poisoned, [_reading()])

    # _signal_persistence_failure schedules via run_coroutine_threadsafe
    # from the *current* thread (writer thread in production); here we
    # are already on the loop, so we just need to yield to let it run.
    try:
        await asyncio.wait_for(callback_invoked.wait(), timeout=2.0)
    except TimeoutError:
        pytest.fail(
            "persistence_failure_callback was not invoked within 2s. "
            f"is_disk_full={writer.is_disk_full}"
        )

    assert any("disk full" in r.lower() for r in received_reasons), (
        f"callback received unexpected reasons: {received_reasons}"
    )


def test_other_operational_errors_still_raise(tmp_path):
    """Non-disk OperationalErrors keep the existing raise semantics."""
    writer = SQLiteWriter(tmp_path)

    poisoned = _poisoned_conn(
        sqlite3.OperationalError("table readings has no column foo")
    )

    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned, [_reading()])

    assert writer.is_disk_full is False, (
        "non-disk error must NOT set the disk_full flag"
    )


def test_clear_disk_full_resets_flag(tmp_path):
    writer = SQLiteWriter(tmp_path)
    writer._disk_full = True
    assert writer.is_disk_full is True
    writer.clear_disk_full()
    assert writer.is_disk_full is False
    # Idempotent — calling again is safe.
    writer.clear_disk_full()
    assert writer.is_disk_full is False


@pytest.mark.asyncio
async def test_safety_manager_on_persistence_failure_latches_fault():
    """SafetyManager.on_persistence_failure must transition to FAULT_LATCHED."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager, SafetyState

    safety_broker = SafetyBroker()
    keithley = MagicMock()
    keithley.emergency_off = AsyncMock()

    mgr = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
    await mgr.start()
    try:
        await mgr.on_persistence_failure("disk full: database or disk is full")
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert "Persistence failure" in mgr.fault_reason
        keithley.emergency_off.assert_awaited()
    finally:
        await mgr.stop()


@pytest.mark.asyncio
async def test_disk_monitor_does_NOT_auto_clear_flag(tmp_path, caplog):
    """DiskMonitor logs recovery but does NOT clear the writer flag.

    Operator must acknowledge_fault to actually resume polling — this
    prevents auto-recovery on disk-space flapping (Codex Phase 2a P1-1).
    """
    from cryodaq.core.broker import DataBroker
    from cryodaq.core.disk_monitor import DiskMonitor

    writer = SQLiteWriter(tmp_path)
    writer._disk_full = True

    broker = DataBroker()
    monitor = DiskMonitor(
        data_dir=tmp_path,
        broker=broker,
        warning_gb=0.0,
        critical_gb=0.0,
        sqlite_writer=writer,
    )
    caplog.set_level(logging.WARNING)
    await monitor._check_once()

    # Flag MUST still be set — auto-clear is forbidden.
    assert writer.is_disk_full is True, (
        "DiskMonitor must NOT auto-clear the disk_full flag (Codex P1-1). "
        "Recovery requires explicit operator acknowledge_fault."
    )
    # Recovery WAS logged for the operator.
    assert any(
        "acknowledge_fault" in r.message.lower() for r in caplog.records
    ), "DiskMonitor must log a recovery notice prompting the operator"


@pytest.mark.asyncio
async def test_acknowledge_fault_clears_disk_full_flag():
    """SafetyManager.acknowledge_fault must clear the writer flag via callback."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager, SafetyState

    safety_broker = SafetyBroker()
    keithley = MagicMock()
    keithley.emergency_off = AsyncMock()
    mgr = SafetyManager(safety_broker, keithley_driver=keithley, mock=True)
    mgr._config.cooldown_before_rearm_s = 0.0  # no cooldown for the test
    mgr._config.require_reason = False

    cleared = {"called": False}

    def clear_cb() -> None:
        cleared["called"] = True

    mgr.set_persistence_failure_clear(clear_cb)

    await mgr.start()
    try:
        await mgr.on_persistence_failure("disk full: test")
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert cleared["called"] is False  # not yet

        result = await mgr.acknowledge_fault("ack")
        assert result.get("ok"), f"acknowledge_fault failed: {result}"
        assert cleared["called"] is True, (
            "acknowledge_fault must invoke the persistence_failure_clear callback"
        )
    finally:
        await mgr.stop()


@pytest.mark.asyncio
async def test_disk_full_classifier_rejects_unrelated_disk_messages(tmp_path):
    """The phrase-based classifier must NOT match SQLITE_CORRUPT / SQLITE_IOERR.

    Codex Phase 2a P1-2: matching individual keywords like 'disk' would
    false-positive on 'database disk image is malformed' (corrupt) or
    'disk I/O error' (transient I/O), which are NOT disk-full.
    """
    writer = SQLiteWriter(tmp_path)

    # SQLITE_CORRUPT — must NOT trigger disk-full
    poisoned1 = _poisoned_conn(
        sqlite3.OperationalError("database disk image is malformed")
    )
    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned1, [_reading()])
    assert writer.is_disk_full is False, "SQLITE_CORRUPT must not be classified as disk-full"

    # SQLITE_IOERR — must NOT trigger disk-full
    poisoned2 = _poisoned_conn(sqlite3.OperationalError("disk I/O error"))
    with pytest.raises(sqlite3.OperationalError):
        writer._write_day_batch(poisoned2, [_reading()])
    assert writer.is_disk_full is False, "SQLITE_IOERR must not be classified as disk-full"


@pytest.mark.asyncio
async def test_disk_full_classifier_accepts_real_messages(tmp_path):
    """All real disk-full phrases (Linux, Windows, quota) trigger the flag."""
    real_messages = [
        "database or disk is full",
        "no space left on device",
        "Not enough space on the disk",  # Windows phrasing, mixed case
        "disk quota exceeded",
    ]
    for msg in real_messages:
        writer = SQLiteWriter(tmp_path)
        poisoned = _poisoned_conn(sqlite3.OperationalError(msg))
        writer._write_day_batch(poisoned, [_reading()])
        assert writer.is_disk_full is True, (
            f"Real disk-full message {msg!r} was not classified as disk-full"
        )


@pytest.mark.asyncio
async def test_persistence_failure_callback_from_executor_thread(tmp_path):
    """Verify the cross-thread plumbing works from a real executor thread.

    The previous test exercised callback scheduling from the event-loop
    thread. In production _write_day_batch runs in the SQLiteWriter executor.
    This test runs the same path via run_in_executor to cover the actual
    cross-thread codepath (Codex Phase 2a P2).
    """
    writer = SQLiteWriter(tmp_path)
    writer.set_event_loop(asyncio.get_running_loop())

    callback_invoked = asyncio.Event()
    received: list[str] = []

    async def callback(reason: str) -> None:
        received.append(reason)
        callback_invoked.set()

    writer.set_persistence_failure_callback(callback)

    poisoned = _poisoned_conn(sqlite3.OperationalError("database or disk is full"))

    # Run _write_day_batch on the writer's actual executor thread.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(writer._executor, writer._write_day_batch, poisoned, [_reading()])

    try:
        await asyncio.wait_for(callback_invoked.wait(), timeout=2.0)
    except TimeoutError:
        pytest.fail(
            "callback not invoked from executor thread within 2s. "
            "Cross-thread run_coroutine_threadsafe plumbing is broken."
        )
    assert any("disk full" in r.lower() for r in received)
    assert writer.is_disk_full is True
