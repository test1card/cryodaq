from __future__ import annotations

import asyncio
import math
import sqlite3
from pathlib import Path

import pytest

from cryodaq.replay_engine.sources import CurveReplay, DirectoryReplay, SQLiteReplay


def _db(path: Path, rows: list[tuple[float, str, float, str, str, str | None]]) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, "
            "unit TEXT, status TEXT, instrument_id TEXT)"
        )
        conn.executemany("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.commit()


@pytest.mark.parametrize(
    "curve",
    [
        {"t_hours": [0.0, 1.0], "T_cold": [4.0], "T_warm": [5.0, 6.0]},
        {"t_hours": [0.0, 1.0], "T_cold": [4.0, math.nan], "T_warm": [5.0, 6.0]},
        {"t_hours": [0.0, 0.0], "T_cold": [4.0, 4.1], "T_warm": [5.0, 5.1]},
    ],
)
async def test_curve_validation_fails_before_first_publication(curve: dict) -> None:
    published = []
    replay = CurveReplay(curve, speed=0.0)

    with pytest.raises(ValueError):
        await replay.run(published.append)

    assert published == []


async def test_unknown_sqlite_status_is_never_promoted_to_ok(tmp_path: Path) -> None:
    path = tmp_path / "data_2026-07-18.db"
    _db(path, [(1.0, "temperature", 4.2, "K", "mystery", "instrument-1")])
    published = []

    with pytest.raises(ValueError, match="Unknown replay status"):
        await SQLiteReplay(path, speed=0.0).run(published.append)

    assert published == []


@pytest.mark.parametrize(
    "value,instrument_id",
    [(math.inf, "instrument-1"), (4.2, None)],
)
async def test_nonfinite_or_unproven_sqlite_evidence_is_rejected_before_publish(
    tmp_path: Path,
    value: float,
    instrument_id: str | None,
) -> None:
    path = tmp_path / "data_2026-07-18.db"
    _db(path, [(1.0, "temperature", value, "K", "ok", instrument_id)])
    published = []

    with pytest.raises(ValueError):
        await SQLiteReplay(path, speed=0.0).run(published.append)

    assert published == []


async def test_curve_loop_timestamps_never_rewind() -> None:
    replay = CurveReplay(
        {"t_hours": [0.0, 1.0], "T_cold": [4.0, 4.1], "T_warm": [5.0, 5.1]},
        speed=0.0,
        loop=True,
    )
    published = []

    async def collect(reading) -> None:
        published.append(reading)
        if len(published) == 6:
            replay.stop()

    await replay.run(collect)
    timestamps = [item.timestamp.timestamp() for item in published]
    assert timestamps == sorted(timestamps)
    assert timestamps[4] > timestamps[3]


async def test_directory_pacing_and_loop_use_one_global_monotonic_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _db(
        tmp_path / "data_2026-07-17.db",
        [
            (1.0, "temperature", 4.0, "K", "ok", "instrument-1"),
            (2.0, "temperature", 4.1, "K", "ok", "instrument-1"),
        ],
    )
    _db(
        tmp_path / "data_2026-07-18.db",
        [
            (10.0, "temperature", 4.2, "K", "ok", "instrument-1"),
            (11.0, "temperature", 4.3, "K", "ok", "instrument-1"),
        ],
    )
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    replay = DirectoryReplay(tmp_path, speed=1.0, loop=True)
    published = []

    async def collect(reading) -> None:
        published.append(reading)
        if len(published) == 6:
            replay.stop()

    await replay.run(collect)
    timestamps = [item.timestamp.timestamp() for item in published]
    assert timestamps == sorted(timestamps)
    assert timestamps[4] > timestamps[3]
    assert sleeps[:3] == [1.0, 8.0, 1.0]
