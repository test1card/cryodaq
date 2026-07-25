"""Regression test: start_immediate() must not block the event loop.

_prepare_control_data_directory() performs blocking filesystem work
(directory walks, os.open, os.mkdir, handle settlement) on slow storage
or under antivirus/reparse-point inspection. The engine awaits
start_immediate() during startup, before SafetyManager.start() and before
signal-handler/readiness installation — if the call runs inline on the
event loop thread, no other coroutine (not even an already-scheduled
heartbeat) can run until it returns, and the launcher can time out and
force-reap the child.

Reviewer's probe: replace the helper with a blocking call and confirm an
already-scheduled fast ticker does NOT advance while start_immediate() is
in flight. Must fail before the executor-offload fix (ticks == 0) and pass
after (ticks > 0).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from pathlib import Path

import cryodaq.storage.sqlite_writer as sqlite_writer_module
from cryodaq.storage.sqlite_writer import SQLiteWriter


def test_start_immediate_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    def blocking_prepare(path, *, retained_on_failure):
        time.sleep(0.25)
        return path

    monkeypatch.setattr(sqlite_writer_module, "_prepare_control_data_directory", blocking_prepare)

    writer = SQLiteWriter(data_dir=tmp_path)

    async def run() -> int:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticker_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)  # let the ticker get its first scheduling in
        try:
            await writer.start_immediate()
        finally:
            ticker_task.cancel()
            try:
                await ticker_task
            except asyncio.CancelledError:
                pass
            await writer.stop()
        return ticks

    ticks = asyncio.run(run())
    assert ticks > 0, (
        "start_immediate() blocked the event loop: an already-scheduled "
        "10ms ticker did not advance while a 250ms directory-prep call "
        "was in flight."
    )


def test_start_immediate_cancellation_propagates_as_cancelled(tmp_path: Path, monkeypatch) -> None:
    """Regression: cancelling start_immediate() mid-prep must end CANCELLED.

    Commit 58ef25d3 offloaded _prepare_control_data_directory onto an
    executor and wrapped the await in ``except BaseException``. A caller
    cancellation lands at that await as asyncio.CancelledError (it is a
    BaseException), so the handler converted a REQUESTED shutdown into a
    phantom "SQLiteWriter data directory authority is unavailable"
    RuntimeError, hid it as a boot failure, and skipped every outer
    ``except asyncio.CancelledError`` shutdown path. The fix lets
    CancelledError propagate unchanged; genuine directory failures still
    raise RuntimeError (covered by
    test_start_immediate_genuine_directory_failure_remains_runtime_error).
    """
    prep_started = threading.Event()

    def slow_prepare(path, *, retained_on_failure):
        prep_started.set()
        time.sleep(0.5)
        return path

    monkeypatch.setattr(sqlite_writer_module, "_prepare_control_data_directory", slow_prepare)
    writer = SQLiteWriter(data_dir=tmp_path)

    async def run() -> bool:
        task = asyncio.create_task(writer.start_immediate())
        try:
            # Wait until the offloaded directory prep is actually in flight
            # in the executor thread, so cancellation lands at the await
            # boundary the bug lives at rather than before the task starts.
            for _ in range(200):
                if prep_started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert prep_started.is_set(), "directory prep never started"
            task.cancel()
            # Swallow whatever the task raises so we can inspect its terminal
            # state directly; cancelled() is the property under test.
            with contextlib.suppress(BaseException):
                await task
            return task.cancelled()
        finally:
            with contextlib.suppress(BaseException):
                await writer.stop()

    cancelled = asyncio.run(run())
    assert cancelled is True, (
        "start_immediate() swallowed a requested cancellation: the task ended "
        "with cancelled()=False (likely the phantom 'data directory authority "
        "is unavailable' RuntimeError) instead of propagating CancelledError."
    )


def test_start_immediate_genuine_directory_failure_remains_runtime_error(tmp_path: Path, monkeypatch) -> None:
    """Fail-closed parity: a real directory failure must still raise RuntimeError.

    Letting cancellation propagate must not weaken the authority-unavailable
    fail-closed direction. When the offloaded directory prep raises a genuine
    exception, start_immediate() must convert it to RuntimeError and leave
    _running False, exactly as before the cancellation fix.
    """

    def failing_prepare(path, *, retained_on_failure):
        raise OSError("simulated directory authority failure")

    monkeypatch.setattr(sqlite_writer_module, "_prepare_control_data_directory", failing_prepare)
    writer = SQLiteWriter(data_dir=tmp_path)

    async def run() -> tuple[type[BaseException], str, bool]:
        try:
            try:
                await writer.start_immediate()
            except BaseException as exc:
                return type(exc), str(exc), writer._running
            return RuntimeError, "no exception raised", writer._running
        finally:
            with contextlib.suppress(BaseException):
                await writer.stop()

    exc_type, message, running = asyncio.run(run())
    assert exc_type is RuntimeError, f"genuine directory failure must surface as RuntimeError, got {exc_type.__name__}"
    assert "data directory authority is unavailable" in message
    assert running is False, "start_immediate() must not mark itself running on directory failure"
