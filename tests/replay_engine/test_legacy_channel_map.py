"""F-LegacyChannelMap — channel rename mapping tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import Reading
from cryodaq.replay_engine.legacy_channel_maps import (
    ERA_PRE_2025_02,
    LEGACY_CHANNEL_MAPS,
    get_legacy_map,
)
from cryodaq.replay_engine.sources import SQLiteReplay


def test_get_legacy_map_returns_pre_2025_02_dict():
    m = get_legacy_map("pre-2025-02")
    assert m["Т10"] == "Т12"
    assert m["Т9"] == "Т10"
    assert m["Т8"] == "Т9"


def test_get_legacy_map_unknown_era_returns_empty():
    assert get_legacy_map("unknown-era") == {}


def test_pre_2025_02_does_not_remap_t11():
    """Т11 was already canonical pre-bridge — must not be touched."""
    assert "Т11" not in ERA_PRE_2025_02


def test_legacy_maps_registry_contains_pre_2025_02():
    assert "pre-2025-02" in LEGACY_CHANNEL_MAPS


def _make_db(tmp_path: Path, channel: str) -> Path:
    """Build a minimal SQLite readings file with one row using `channel`."""
    db_path = tmp_path / "data_legacy.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE readings (timestamp TEXT, channel TEXT, value REAL,"
            " unit TEXT, status TEXT, instrument_id TEXT)"
        )
        conn.execute(
            "INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(tz=UTC).isoformat(),
                channel,
                42.0,
                "K",
                "OK",
                "lakeshore_1",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.mark.asyncio
async def test_sqlite_replay_applies_channel_map(tmp_path):
    """Reading published from SQLiteReplay через map имеет new canonical channel."""
    db_path = _make_db(tmp_path, channel="Т10")
    published: list[Reading] = []

    async def cb(r: Reading) -> None:
        published.append(r)

    replay = SQLiteReplay(
        db_path,
        speed=0.0,
        channel_map=ERA_PRE_2025_02,
    )
    await asyncio.wait_for(replay.run(cb), timeout=2.0)

    assert published, "no readings published"
    assert all(r.channel == "Т12" for r in published), [r.channel for r in published]


@pytest.mark.asyncio
async def test_sqlite_replay_no_map_passes_channel_unchanged(tmp_path):
    """Without channel_map, readings published as-is."""
    db_path = _make_db(tmp_path, channel="Т10")
    published: list[Reading] = []

    async def cb(r: Reading) -> None:
        published.append(r)

    replay = SQLiteReplay(db_path, speed=0.0)
    await asyncio.wait_for(replay.run(cb), timeout=2.0)

    assert published
    assert all(r.channel == "Т10" for r in published), [r.channel for r in published]


@pytest.mark.asyncio
async def test_sqlite_replay_unmapped_channel_passes_through(tmp_path):
    """Channels not in the map fall through unchanged."""
    db_path = _make_db(tmp_path, channel="Т11")
    published: list[Reading] = []

    async def cb(r: Reading) -> None:
        published.append(r)

    replay = SQLiteReplay(
        db_path,
        speed=0.0,
        channel_map=ERA_PRE_2025_02,
    )
    await asyncio.wait_for(replay.run(cb), timeout=2.0)

    assert published
    assert all(r.channel == "Т11" for r in published), [r.channel for r in published]
