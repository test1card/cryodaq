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
import inspect
from pathlib import Path

from cryodaq.storage.sqlite_writer import SQLiteWriter


def test_get_operator_log_uses_read_executor():
    """Source of get_operator_log must route to self._read_executor."""
    source = inspect.getsource(SQLiteWriter.get_operator_log)
    assert "_read_executor" in source, (
        "get_operator_log must use _read_executor (separated from "
        "persistence writes on _executor)."
    )
    # Make sure we didn't accidentally leave a run_in_executor(self._executor, ...)
    # call in the method. The test must fail loudly if a future edit reverts it.
    stripped = source.replace("_read_executor", "")
    assert "run_in_executor(self._executor" not in stripped, (
        "get_operator_log must NOT schedule the read on self._executor."
    )


def test_read_readings_history_uses_read_executor():
    """read_readings_history has been on _read_executor for a while;
    keep it pinned to prevent accidental regression."""
    source = inspect.getsource(SQLiteWriter.read_readings_history)
    assert "_read_executor" in source


def test_write_immediate_still_uses_write_executor():
    """Persistence-first writes MUST stay on _executor to preserve
    ordering with the scheduler batch flush."""
    source = inspect.getsource(SQLiteWriter.write_immediate)
    assert "run_in_executor(self._executor" in source, (
        "write_immediate must stay on _executor (write pool)."
    )
    assert "_read_executor" not in source


def test_append_operator_log_still_uses_write_executor():
    """append_operator_log is a WRITE (INSERT INTO operator_log);
    it must stay on the write executor to serialise with other writes."""
    source = inspect.getsource(SQLiteWriter.append_operator_log)
    assert "run_in_executor(self._executor" in source
    assert "_read_executor" not in source


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
