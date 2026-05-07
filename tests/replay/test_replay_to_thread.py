"""H6 — replay engine offloads SQLite load to thread."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from cryodaq.replay_engine.sources import SQLiteReplay


@pytest.mark.asyncio
async def test_sqlite_replay_loads_in_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLiteReplay.run must call _load_db_rows from a non-loop thread."""
    main_thread = threading.get_ident()
    seen_threads: list[int] = []

    def _fake_load(db_path: Path):
        seen_threads.append(threading.get_ident())
        return []

    monkeypatch.setattr(
        "cryodaq.replay_engine.sources._load_db_rows", _fake_load
    )

    replay = SQLiteReplay(tmp_path / "data.db", speed=1.0, loop=False)

    async def _publish(_reading) -> None:  # pragma: no cover
        pass

    await asyncio.wait_for(replay.run(_publish), timeout=2.0)

    assert seen_threads, "_load_db_rows was not called"
    assert seen_threads[0] != main_thread, (
        "SQLite load ran on the asyncio loop thread"
    )
