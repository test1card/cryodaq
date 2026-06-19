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
