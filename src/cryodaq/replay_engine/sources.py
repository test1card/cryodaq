"""Source dispatch for the replay engine.

resolve_source() inspects the path and returns the appropriate replay source:
  *.db        → SQLiteReplay
  *.json      → CurveReplay (cooldown_v5 schema required)
  directory   → DirectoryReplay (iterates data_*.db files)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)

PublishCallback = Callable[[Reading], Awaitable[None]]


class SQLiteReplay:
    """Replay a single SQLite daily file, publishing readings at replay speed."""

    def __init__(
        self,
        db_path: Path,
        *,
        speed: float = 10.0,
        loop: bool = False,
        channel_map: dict[str, str] | None = None,
    ) -> None:
        self._db_path = db_path
        self._speed = max(speed, 0.0)
        self._loop = loop
        self._channel_map = channel_map or None
        self._running = False

    def _apply_channel_map(self, channel: str) -> str:
        if self._channel_map is None:
            return channel
        return self._channel_map.get(channel, channel)

    def stop(self) -> None:
        self._running = False

    async def run(
        self, publish_cb: PublishCallback, *, base_offset: float | None = None
    ) -> None:
        self._running = True
        while self._running:
            # H6: offload SQLite load to a thread — large historical files
            # (~1 GB for 17 h cooldown) block the asyncio loop otherwise.
            rows = await asyncio.to_thread(_load_db_rows, self._db_path)
            if not rows:
                logger.warning("SQLiteReplay: no rows in %s", self._db_path.name)
                break
            _base_offset = (
                base_offset
                if base_offset is not None
                else datetime.now(tz=UTC).timestamp() - rows[0][0]
            )
            prev_ts: float | None = None
            for row in rows:
                if not self._running:
                    return
                ts_posix, channel, value, unit, status_str, inst_id = row
                if prev_ts is not None and self._speed > 0.0:
                    delta = ts_posix - prev_ts
                    if delta > 0:
                        await asyncio.sleep(delta / self._speed)
                prev_ts = ts_posix
                try:
                    status = ChannelStatus(status_str)
                except ValueError:
                    status = ChannelStatus.OK
                reading = Reading(
                    timestamp=datetime.fromtimestamp(ts_posix + _base_offset, tz=UTC),
                    instrument_id=inst_id,
                    channel=self._apply_channel_map(channel),
                    value=value,
                    unit=unit,
                    status=status,
                    metadata={"source": "replay"},
                )
                await publish_cb(reading)
            if not self._loop:
                break
        self._running = False


class CurveReplay:
    """Replay a cooldown_v5 curve JSON as a live PUB stream.

    Converts t_hours/T_cold/T_warm arrays into Reading objects without
    creating an intermediate SQLite file.  T_cold → cold_channel (Т12),
    T_warm → warm_channel (Т11).
    """

    def __init__(
        self,
        curve: dict,
        *,
        speed: float = 10.0,
        loop: bool = False,
        cold_channel: str = "Т12",
        warm_channel: str = "Т11",
    ) -> None:
        self._curve = curve
        self._speed = max(speed, 0.0)
        self._loop = loop
        self._cold_channel = cold_channel
        self._warm_channel = warm_channel
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def run(self, publish_cb: PublishCallback) -> None:
        import numpy as np

        t_hours = np.asarray(self._curve["t_hours"], dtype=float)
        T_cold = np.asarray(self._curve["T_cold"], dtype=float)
        T_warm = np.asarray(self._curve["T_warm"], dtype=float)
        n = len(t_hours)
        base_ts = datetime.now(tz=UTC).timestamp()

        self._running = True
        while self._running:
            prev_t: float | None = None
            for i in range(n):
                if not self._running:
                    return
                t_h = float(t_hours[i])
                if prev_t is not None and self._speed > 0.0:
                    delta_s = (t_h - prev_t) * 3600.0
                    if delta_s > 0:
                        await asyncio.sleep(delta_s / self._speed)
                prev_t = t_h

                ts = base_ts + t_h * 3600.0
                dt = datetime.fromtimestamp(ts, tz=UTC)
                for channel, value in (
                    (self._cold_channel, float(T_cold[i])),
                    (self._warm_channel, float(T_warm[i])),
                ):
                    reading = Reading(
                        timestamp=dt,
                        instrument_id="replay",
                        channel=channel,
                        value=value,
                        unit="K",
                        status=ChannelStatus.OK,
                        metadata={"source": "curve_replay"},
                    )
                    await publish_cb(reading)
            if not self._loop:
                break
        self._running = False


class DirectoryReplay:
    """Replay all data_*.db files in a directory in chronological order."""

    def __init__(
        self,
        data_dir: Path,
        *,
        speed: float = 10.0,
        loop: bool = False,
        channel_map: dict[str, str] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._speed = speed
        self._loop = loop
        self._channel_map = channel_map or None
        self._running = False
        self._current: SQLiteReplay | None = None

    def stop(self) -> None:
        self._running = False
        if self._current is not None:
            self._current.stop()

    async def run(self, publish_cb: PublishCallback) -> None:
        db_files = sorted(self._data_dir.glob("data_*.db"))
        if not db_files:
            logger.warning("DirectoryReplay: no data_*.db files in %s", self._data_dir)
            return
        # Compute one time origin from the first row of the first non-empty
        # file so timestamps stay monotonic across all files. Walking past
        # empty files defends against half-rotated empty .db at the start
        # of the sort order, which would otherwise leave the offset at 0.0
        # and emit raw historical timestamps for every file (Defect-1
        # regression for multi-file sessions).
        first_rows: list = []
        for _db in db_files:
            # H6: offload SQLite load to a thread.
            first_rows = await asyncio.to_thread(_load_db_rows, _db)
            if first_rows:
                break
        if not first_rows:
            logger.warning(
                "DirectoryReplay: all data_*.db files in %s are empty",
                self._data_dir,
            )
            return
        global_base_offset = datetime.now(tz=UTC).timestamp() - first_rows[0][0]
        self._running = True
        while self._running:
            for db_path in db_files:
                if not self._running:
                    return
                self._current = SQLiteReplay(
                    db_path,
                    speed=self._speed,
                    channel_map=self._channel_map,
                )
                await self._current.run(publish_cb, base_offset=global_base_offset)
            if not self._loop:
                break
        self._running = False


def resolve_source(
    path: Path,
    *,
    speed: float = 10.0,
    loop: bool = False,
    cold_channel: str = "Т12",
    warm_channel: str = "Т11",
    channel_map: dict[str, str] | None = None,
) -> SQLiteReplay | CurveReplay | DirectoryReplay:
    """Dispatch by path type and return the appropriate replay source.

    *.db        → SQLiteReplay
    *.json      → CurveReplay (must contain t_hours/T_cold/T_warm)
    directory   → DirectoryReplay

    `channel_map`, when provided, applies on the SQLite paths only —
    CurveReplay is post-thermal-bridge era and ignores it (per
    F-LegacyChannelMap).
    """
    if path.is_dir():
        return DirectoryReplay(path, speed=speed, loop=loop, channel_map=channel_map)
    if path.suffix == ".db":
        return SQLiteReplay(path, speed=speed, loop=loop, channel_map=channel_map)
    if path.suffix == ".json":
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        missing = [k for k in ("t_hours", "T_cold", "T_warm") if k not in data]
        if missing:
            raise ValueError(
                f"{path.name} is not a cooldown_v5 curve: missing fields {missing}"
            )
        return CurveReplay(
            data,
            speed=speed,
            loop=loop,
            cold_channel=cold_channel,
            warm_channel=warm_channel,
        )
    raise ValueError(f"Unsupported source path: {path} (expected .db, .json, or directory)")


def _load_db_rows(
    db_path: Path,
) -> list[tuple[float, str, float, str, str, str]]:
    """Load all rows from a SQLite readings table, ordered by timestamp."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        cursor = conn.execute(
            "SELECT timestamp, channel, value, unit, status, instrument_id"
            " FROM readings ORDER BY timestamp;"
        )
        rows: list[tuple[float, str, float, str, str, str]] = []
        for row in cursor:
            ts_raw, channel, value, unit, status, inst_id = row
            try:
                dt = _parse_timestamp(ts_raw)
                ts_posix = dt.timestamp()
            except (ValueError, TypeError, OSError):
                continue
            rows.append((ts_posix, channel, float(value), unit, status, inst_id or "unknown"))
        return rows
    finally:
        conn.close()
