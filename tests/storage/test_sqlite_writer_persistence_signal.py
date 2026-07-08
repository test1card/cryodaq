"""A4: _signal_persistence_failure must not silently drop the scheduled Future.

run_coroutine_threadsafe returns a Future the writer thread never awaits.
If the persistence-failure safety callback (which latches the disk-full
fault) raises, that exception previously vanished. A done-callback now logs
CRITICAL so the lost latch failure is at least visible.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from cryodaq.storage.sqlite_writer import SQLiteWriter


def test_done_callback_logs_critical_on_exception(caplog) -> None:
    fut: concurrent.futures.Future = concurrent.futures.Future()
    fut.set_exception(RuntimeError("latch failed"))
    with caplog.at_level(logging.CRITICAL):
        SQLiteWriter._log_persistence_callback_result(fut)
    assert any("latch may NOT have fired" in rec.message for rec in caplog.records)


def test_done_callback_silent_on_success(caplog) -> None:
    fut: concurrent.futures.Future = concurrent.futures.Future()
    fut.set_result(None)
    with caplog.at_level(logging.CRITICAL):
        SQLiteWriter._log_persistence_callback_result(fut)
    assert not caplog.records


async def test_signal_persistence_failure_wires_done_callback(tmp_path, caplog) -> None:
    """End-to-end: a raising safety callback surfaces as CRITICAL, not silence."""
    writer = SQLiteWriter(tmp_path)
    writer.set_event_loop(asyncio.get_running_loop())

    async def boom(reason: str) -> None:
        raise RuntimeError(f"boom: {reason}")

    writer.set_persistence_failure_callback(boom)

    with caplog.at_level(logging.CRITICAL):
        # run_coroutine_threadsafe must be called off the loop thread.
        await asyncio.to_thread(writer._signal_persistence_failure, "disk full: x")
        await asyncio.sleep(0.05)  # let the scheduled coro + done-callback run

    assert any("latch may NOT have fired" in rec.message for rec in caplog.records)
