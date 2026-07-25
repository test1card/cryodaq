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
