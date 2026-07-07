"""Regression tests for read/write executor separation in SQLiteWriter.

After the 2026-04 stall bug: read-only operations (get_operator_log,
read_readings_history, ...) must run on the dedicated _read_executor,
not the single-worker _executor that also runs write_immediate().

If they share an executor, any in-flight persistence write blocks the
next read, which pins the engine REP task whenever a log_get arrives
during a scheduler flush.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from cryodaq.storage.sqlite_writer import SQLiteWriter


def test_reads_and_writes_use_separate_executors(tmp_path: Path):
    """Runtime routing check (not source inspection): a read actually runs on
    _read_executor and a write actually runs on _executor. Source-string
    inspection could pass on a comment or a wrapper while the real call misroutes;
    spying run_in_executor records the executor object that is genuinely used."""
    from cryodaq.drivers.base import Reading

    writer = SQLiteWriter(data_dir=tmp_path)

    async def run():
        await writer.start_immediate()
        try:
            loop = asyncio.get_running_loop()
            seen: list = []
            orig = loop.run_in_executor

            def spy(executor, func, *args):
                seen.append(executor)
                return orig(executor, func, *args)

            loop.run_in_executor = spy  # type: ignore[method-assign]
            try:
                seen.clear()
                await writer.get_operator_log(limit=10)
                read_execs = list(seen)

                seen.clear()
                await writer.write_immediate(
                    [Reading.now(channel="T1", value=4.5, unit="K", instrument_id="test")]
                )
                write_execs = list(seen)
            finally:
                loop.run_in_executor = orig
            return read_execs, write_execs, writer._read_executor, writer._executor
        finally:
            await writer.stop()

    read_execs, write_execs, read_pool, write_pool = asyncio.run(run())
    assert read_pool in read_execs, "get_operator_log must run on _read_executor"
    assert write_pool not in read_execs, "get_operator_log must NOT use the write executor"
    assert write_pool in write_execs, "write_immediate must run on the write _executor"
    assert read_pool not in write_execs, "write_immediate must NOT use _read_executor"


def test_get_operator_log_not_blocked_by_slow_write(tmp_path: Path):
    """Integration check: a long-running job on the write executor must
    NOT delay a concurrent get_operator_log() by anywhere near that
    duration. Previously they shared a single-worker executor, so a
    2s write would push the read to ≥2s; after the fix, the read
    should land in well under a second."""
    writer = SQLiteWriter(data_dir=tmp_path)

    async def run():
        await writer.start_immediate()
        try:
            loop = asyncio.get_running_loop()

            # Occupy the write executor for 2 seconds.
            import time as _time

            def _block_write():
                _time.sleep(2.0)

            write_fut = loop.run_in_executor(writer._executor, _block_write)

            # Give the write a moment to actually start.
            await asyncio.sleep(0.1)

            read_start = loop.time()
            await writer.get_operator_log(limit=10)
            read_elapsed = loop.time() - read_start

            # Wait for the blocker to finish so we shut down cleanly.
            await write_fut

            return read_elapsed
        finally:
            await writer.stop()

    read_elapsed = asyncio.run(run())
    assert read_elapsed < 1.0, (
        f"get_operator_log took {read_elapsed:.2f}s while a 2s write was "
        "in flight — read/write executors look shared again."
    )


def test_get_operator_log_includes_rotated_cold_days(tmp_path: Path):
    """F2: the live operator journal (log_get → get_operator_log) must include
    rotated audit days, not just hot data_*.db.

    Reports already union cold operator_log via ArchiveReader.query_operator_log,
    but the live path scanned hot files only — after cold rotation the rotated
    day's audit entry silently vanished from the operator-facing journal. Pin
    that get_operator_log unions the cold archive while preserving the DESC
    ordering + limit + experiment_id contract the GUI panel relies on.
    """
    import pytest

    pytest.importorskip("pyarrow")
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService

    old_day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    recent_day = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)

    async def _seed_and_rotate():
        writer = SQLiteWriter(data_dir=tmp_path)
        writer._write_batch(
            [
                Reading(
                    timestamp=old_day,
                    instrument_id="ls",
                    channel="T",
                    value=1.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
        writer._write_operator_log_entry(
            timestamp=old_day,
            experiment_id="exp-1",
            author="op",
            source="gui",
            message="old rotated note",
            tags=("cooldown",),
        )
        writer._write_operator_log_entry(
            timestamp=recent_day,
            experiment_id="exp-1",
            author="op",
            source="gui",
            message="recent hot note",
            tags=(),
        )
        await writer.stop()
        service = ColdRotationService(
            data_dir=tmp_path, archive_dir=tmp_path / "archive", age_days=30
        )
        results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert results, "old day must rotate to Parquet"

    asyncio.run(_seed_and_rotate())
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    async def _get(**kwargs):
        writer = SQLiteWriter(data_dir=tmp_path)
        await writer.start_immediate()
        try:
            return await writer.get_operator_log(**kwargs)
        finally:
            await writer.stop()

    entries = asyncio.run(_get(limit=100))
    messages = [e.message for e in entries]
    assert "old rotated note" in messages, "rotated cold audit entry missing from live journal"
    # Ordering contract: newest-first (timestamp DESC), hot + cold interleaved.
    assert messages == ["recent hot note", "old rotated note"], f"order wrong: {messages}"

    # Limit contract still applied across the hot+cold union (newest kept).
    limited = asyncio.run(_get(limit=1))
    assert [e.message for e in limited] == ["recent hot note"]

    # experiment_id filter still applied to cold rows.
    filtered = asyncio.run(_get(experiment_id="nope", limit=100))
    assert filtered == []
