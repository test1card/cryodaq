"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.

Один файл на день: data_YYYY-MM-DD.db.
Батчевая вставка каждую секунду (или при накоплении batch_size).
Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)

SCHEMA_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
);
"""

SCHEMA_SOURCE_DATA = """
-- Reserved for future Keithley raw SMU buffer recording.
-- Currently unused — Keithley data goes through standard Reading path.
CREATE TABLE IF NOT EXISTS source_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    channel     TEXT    NOT NULL,
    voltage     REAL,
    current     REAL,
    resistance  REAL,
    power       REAL
);
"""

INDEX_READINGS_TS = """
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp);
"""

INDEX_SOURCE_DATA_TS = """
CREATE INDEX IF NOT EXISTS idx_source_data_ts ON source_data (timestamp);
"""

INDEX_CHANNEL_TS = """
CREATE INDEX IF NOT EXISTS idx_channel_ts ON readings (channel, timestamp);
"""

SCHEMA_OPERATOR_LOG = """
CREATE TABLE IF NOT EXISTS operator_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    experiment_id TEXT,
    author        TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    message       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]'
);
"""

INDEX_OPERATOR_LOG_TS = """
CREATE INDEX IF NOT EXISTS idx_operator_log_ts ON operator_log (timestamp);
"""

INDEX_OPERATOR_LOG_EXPERIMENT = """
CREATE INDEX IF NOT EXISTS idx_operator_log_experiment ON operator_log (experiment_id, timestamp);
"""


def _parse_timestamp(raw) -> datetime:
    """Parse timestamp from REAL (float) or legacy TEXT (isoformat)."""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    return datetime.fromisoformat(str(raw))


_SQLITE_VERSION_CHECKED = False


def _check_sqlite_version() -> None:
    """Warn if running on a SQLite version affected by the March 2026 WAL-reset bug.

    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
    connections across threads/processes write or checkpoint "at the same
    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
    history reader, web dashboard, reporting); upgrade to >= 3.51.3 in
    production. See: https://www.sqlite.org/wal.html
    """
    global _SQLITE_VERSION_CHECKED
    if _SQLITE_VERSION_CHECKED:
        return
    _SQLITE_VERSION_CHECKED = True
    version = sqlite3.sqlite_version_info  # tuple, e.g. (3, 37, 2)
    if (3, 7, 0) <= version < (3, 51, 3):
        logger.warning(
            "SQLite %d.%d.%d is affected by the March 2026 WAL-reset corruption "
            "bug (range 3.7.0 – 3.51.2). CryoDAQ uses WAL with multiple "
            "connections; upgrade to SQLite >= 3.51.3 in production. On Ubuntu "
            "22.04 this means building libsqlite3 from source or bundling a "
            "custom libsqlite3 in the PyInstaller build. "
            "See https://www.sqlite.org/wal.html",
            version[0], version[1], version[2],
        )


class SQLiteWriter:
    """Асинхронный писатель показаний в SQLite.

    Использование::

        writer = SQLiteWriter(data_dir=Path("./data"))
        await writer.start(queue)   # queue: asyncio.Queue[Reading]
        ...
        await writer.stop()
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        flush_interval_s: float = 1.0,
        batch_size: int = 500,
    ) -> None:
        self._data_dir = data_dir
        self._flush_interval_s = flush_interval_s
        self._batch_size = batch_size
        self._conn: sqlite3.Connection | None = None
        self._current_date: date | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_written: int = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
        self._checkpoint_counter = 0

        # Disk-full graceful degradation (Phase 2a H.1).
        # When the writer thread detects disk-full from sqlite3.OperationalError,
        # it sets _disk_full=True and (optionally) schedules a callback on the
        # engine event loop via run_coroutine_threadsafe so the SafetyManager
        # can latch a fault. The flag is cleared by DiskMonitor when free
        # space recovers, BUT the operator still has to acknowledge_fault to
        # actually resume polling.
        self._disk_full = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persistence_failure_callback: (
            Callable[[str], Awaitable[None]] | None
        ) = None

        _check_sqlite_version()

    def _db_path(self, day: date) -> Path:
        return self._data_dir / f"data_{day.isoformat()}.db"

    # ------------------------------------------------------------------
    # Disk-full graceful degradation (Phase 2a H.1)
    # ------------------------------------------------------------------
    @property
    def is_disk_full(self) -> bool:
        """True when the most recent write hit a disk-full / out-of-space error."""
        return self._disk_full

    def clear_disk_full(self) -> None:
        """Clear the disk-full flag.

        Called by DiskMonitor when free space recovers above the threshold.
        Note: this does NOT auto-resume polling — the SafetyManager has
        already latched a fault, and the operator must acknowledge_fault
        explicitly. This is a deliberate guard against disk-space flapping.
        """
        if self._disk_full:
            logger.warning(
                "Disk space recovered — clearing _disk_full flag. "
                "SafetyManager fault remains latched until operator acknowledge."
            )
            self._disk_full = False

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the writer to an event loop so the executor thread can
        schedule the persistence-failure callback on it."""
        self._loop = loop

    def set_persistence_failure_callback(
        self, callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """Register an async callback for persistence failures (disk full etc).

        The callback is awaited via :func:`asyncio.run_coroutine_threadsafe`
        from the writer thread, so it lands on the engine event loop where
        SafetyManager.on_persistence_failure can latch a fault.
        """
        self._persistence_failure_callback = callback

    def _signal_persistence_failure(self, reason: str) -> None:
        """Schedule persistence-failure callback on the engine event loop.

        Runs in the writer thread (called from _write_day_batch) — must NOT
        block. We use run_coroutine_threadsafe and intentionally do NOT await
        the resulting Future, because the writer thread does not have an
        event loop of its own.
        """
        if self._persistence_failure_callback is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._persistence_failure_callback(reason),
                self._loop,
            )
        except Exception as exc:
            logger.error("Failed to schedule persistence_failure callback: %s", exc)

    def _ensure_connection(self, day: date) -> sqlite3.Connection:
        """Открыть/переоткрыть БД если сменился день."""
        if self._conn is not None and self._current_date == day:
            return self._conn
        if self._conn is not None:
            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
            self._conn.close()
        db_path = self._db_path(day)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
        # Default autocheckpoint (1000 pages) can starve under concurrent
        # readers. See https://www.sqlite.org/wal.html
        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
        actual_mode = (result[0] if result else "").lower()
        if actual_mode != "wal":
            raise RuntimeError(
                f"SQLite WAL mode could not be enabled at {db_path}. "
                f"PRAGMA journal_mode returned {actual_mode!r}. "
                f"This may indicate an unsupported filesystem (network share, "
                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
                f"for cross-process read concurrency. Refusing to start."
            )
        # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
        # throughput. Production deployments must be on a UPS. If no UPS,
        # set CRYODAQ_SQLITE_SYNC=FULL.
        sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
        if sync_mode not in ("NORMAL", "FULL"):
            sync_mode = "NORMAL"
        conn.execute(f"PRAGMA synchronous={sync_mode};")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")  # ~4 MB
        conn.execute("PRAGMA cache_size=-16384;")  # 16 MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute(SCHEMA_READINGS)
        conn.execute(SCHEMA_SOURCE_DATA)
        conn.execute(SCHEMA_OPERATOR_LOG)
        conn.execute(INDEX_READINGS_TS)
        conn.execute(INDEX_SOURCE_DATA_TS)
        conn.execute(INDEX_CHANNEL_TS)
        conn.execute(INDEX_OPERATOR_LOG_TS)
        conn.execute(INDEX_OPERATOR_LOG_EXPERIMENT)
        conn.commit()
        self._conn = conn
        self._current_date = day
        logger.info("Открыта БД: %s", db_path)
        return conn

    def _write_batch(self, batch: list[Reading]) -> None:
        """Вставить пакет в таблицу readings (вызывается в потоке).

        Readings с value=None или value=NaN пропускаются (sqlite3 maps NaN
        to NULL, which violates the NOT NULL constraint on readings.value).

        Readings are grouped by day before writing so that a batch spanning
        midnight is correctly split across daily DB files.
        """
        if not batch:
            return
        # Group readings by day to handle midnight crossing
        by_day: dict[date, list[Reading]] = {}
        for r in batch:
            day = r.timestamp.date()
            by_day.setdefault(day, []).append(r)
        for day, day_readings in sorted(by_day.items()):
            conn = self._ensure_connection(day)
            self._write_day_batch(conn, day_readings)

    # Status values where a non-finite value IS the sensor state (not garbage).
    # Persist these so post-mortem analysis has evidence of OVL/fault events.
    _STATE_CARRYING_STATUSES = {
        ChannelStatus.OVERRANGE,
        ChannelStatus.UNDERRANGE,
        ChannelStatus.SENSOR_ERROR,
        ChannelStatus.TIMEOUT,
    }

    def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> None:
        """Write a single day's readings to the given connection."""
        rows = []
        skipped = 0
        for r in batch:
            if r.value is None:
                skipped += 1
                continue
            if isinstance(r.value, float) and not math.isfinite(r.value):
                # Non-finite value: persist if status says this IS the sensor state
                if r.status not in self._STATE_CARRYING_STATUSES:
                    skipped += 1
                    continue
            rows.append(
                (
                    r.timestamp.timestamp(),
                    r.instrument_id or "unknown",
                    r.channel,
                    r.value,
                    r.unit,
                    r.status.value,
                )
            )
        if skipped:
            logger.warning(
                "Пропущено %d readings с value=None/NaN (из батча %d)", skipped, len(batch),
            )
        if not rows:
            return
        try:
            conn.executemany(
                "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
                "VALUES (?, ?, ?, ?, ?, ?);",
                rows,
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            # Disk-full graceful degradation (Phase 2a H.1).
            # Detect by exact PHRASES to avoid false positives like
            # "database disk image is malformed" (SQLITE_CORRUPT) or
            # "disk I/O error" (SQLITE_IOERR), which are NOT disk-full.
            # Phrases cover SQLITE_FULL on Linux/macOS/Windows + quota.
            msg = str(exc).lower()
            disk_full_phrases = (
                "database or disk is full",
                "database is full",
                "no space left on device",
                "not enough space on the disk",
                "disk quota exceeded",
            )
            if any(phrase in msg for phrase in disk_full_phrases):
                if not self._disk_full:
                    logger.critical(
                        "DISK FULL detected in SQLite write: %s. "
                        "Pausing polling, triggering safety fault.",
                        exc,
                    )
                self._disk_full = True
                self._signal_persistence_failure(f"disk full: {exc}")
                # Do NOT re-raise. Re-raising would propagate up to
                # write_immediate / scheduler and cause the historic tight
                # CRITICAL-log loop. The flag + signalled callback are the
                # signalling mechanism now.
                return
            # Any other OperationalError keeps the existing semantics.
            raise

        # Periodic explicit PASSIVE checkpoint (~once per minute at 1 Hz batch
        # cadence). Prevents WAL file growth under concurrent reader pressure.
        # See DEEP_AUDIT_CC.md D.1.
        self._checkpoint_counter += 1
        if self._checkpoint_counter >= 60:
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.OperationalError as exc:
                logger.warning("Periodic WAL checkpoint failed: %s", exc)
            self._checkpoint_counter = 0
        self._total_written += len(rows)

    def _write_source_row(
        self,
        timestamp: datetime,
        channel: str,
        *,
        voltage: float | None = None,
        current: float | None = None,
        resistance: float | None = None,
        power: float | None = None,
    ) -> None:
        """Reserved for future Keithley raw data recording.

        Currently unused — Keithley data goes through standard Reading path.
        Kept for future direct SMU buffer recording.
        """
        day = timestamp.date()
        conn = self._ensure_connection(day)
        conn.execute(
            "INSERT INTO source_data (timestamp, channel, voltage, current, resistance, power) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (timestamp.isoformat(), channel, voltage, current, resistance, power),
        )
        conn.commit()

    def _write_operator_log_entry(
        self,
        *,
        timestamp: datetime,
        experiment_id: str | None,
        author: str,
        source: str,
        message: str,
        tags: tuple[str, ...],
    ) -> OperatorLogEntry:
        day = timestamp.date()
        conn = self._ensure_connection(day)
        cursor = conn.execute(
            "INSERT INTO operator_log (timestamp, experiment_id, author, source, message, tags) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (
                timestamp.timestamp(),
                experiment_id,
                author,
                source,
                message,
                json.dumps(list(tags), ensure_ascii=False),
            ),
        )
        conn.commit()
        return OperatorLogEntry(
            id=int(cursor.lastrowid),
            timestamp=timestamp,
            experiment_id=experiment_id,
            author=author,
            source=source,
            message=message,
            tags=tags,
        )

    def _operator_log_db_paths(
        self,
        *,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[Path]:
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
        if not db_files:
            return []

        if start_time is None and end_time is None:
            return db_files

        selected: list[Path] = []
        start_day = start_time.date() if start_time is not None else None
        end_day = end_time.date() if end_time is not None else None
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if start_day is not None and day < start_day:
                continue
            if end_day is not None and day > end_day:
                continue
            selected.append(db_path)
        return selected

    def _read_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
        rows: list[OperatorLogEntry] = []
        for db_path in self._operator_log_db_paths(start_time=start_time, end_time=end_time):
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(SCHEMA_OPERATOR_LOG)
                query = (
                    "SELECT id, timestamp, experiment_id, author, source, message, tags "
                    "FROM operator_log WHERE 1 = 1"
                )
                params: list[Any] = []
                if experiment_id is not None:
                    query += " AND experiment_id = ?"
                    params.append(experiment_id)
                if start_time is not None:
                    query += " AND timestamp >= ?"
                    params.append(start_time.timestamp())
                if end_time is not None:
                    query += " AND timestamp <= ?"
                    params.append(end_time.timestamp())
                query += " ORDER BY timestamp DESC"
                for row in conn.execute(query, params).fetchall():
                    tags = tuple(json.loads(row["tags"] or "[]"))
                    rows.append(
                        OperatorLogEntry(
                            id=int(row["id"]),
                            timestamp=_parse_timestamp(row["timestamp"]),
                            experiment_id=row["experiment_id"],
                            author=str(row["author"] or ""),
                            source=str(row["source"] or ""),
                            message=str(row["message"] or ""),
                            tags=tags,
                        )
                    )
            finally:
                conn.close()

        rows.sort(key=lambda item: item.timestamp, reverse=True)
        return rows[: max(limit, 0)]

    async def _consume_loop(self, queue: asyncio.Queue[Reading]) -> None:
        """Основной цикл: собирает батч из очереди, пишет в БД."""
        loop = asyncio.get_running_loop()
        executor = self._executor
        while self._running:
            batch: list[Reading] = []
            deadline = asyncio.get_event_loop().time() + self._flush_interval_s
            while len(batch) < self._batch_size:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    reading = await asyncio.wait_for(queue.get(), timeout=remaining)
                    batch.append(reading)
                except TimeoutError:
                    break
            if batch:
                try:
                    await loop.run_in_executor(executor, self._write_batch, batch)
                except Exception:
                    logger.exception("Ошибка записи батча (%d записей)", len(batch))

    async def write_immediate(self, readings: list[Reading]) -> None:
        """Записать пакет синхронно (await до WAL commit).

        Используется Scheduler для гарантии persistence-first:
        данные попадают в DataBroker ТОЛЬКО после записи на диск.
        При ошибке — логирует CRITICAL и пробрасывает исключение.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._write_batch, readings)
        except Exception:
            logger.critical(
                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
                len(readings),
            )
            raise

    async def append_operator_log(
        self,
        *,
        message: str,
        author: str = "",
        source: str = "command",
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
        timestamp: datetime | None = None,
    ) -> OperatorLogEntry:
        text = message.strip()
        if not text:
            raise ValueError("Operator log message must not be empty.")

        normalized_tags = normalize_operator_log_tags(tags)
        entry_time = timestamp or datetime.now(timezone.utc)
        loop = asyncio.get_running_loop()
        task = partial(
            self._write_operator_log_entry,
            timestamp=entry_time,
            experiment_id=experiment_id,
            author=author.strip(),
            source=source.strip() or "command",
            message=text,
            tags=normalized_tags,
        )
        return await loop.run_in_executor(self._executor, task)

    async def get_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
        loop = asyncio.get_running_loop()
        task = partial(
            self._read_operator_log,
            experiment_id=experiment_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        return await loop.run_in_executor(self._executor, task)

    async def start_immediate(self) -> None:
        """Инициализировать writer без очереди (persistence-first режим).

        Создаёт директорию данных и помечает writer как работающий.
        Запись происходит через write_immediate(), вызываемый из Scheduler.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info("SQLiteWriter запущен (immediate mode)")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        """Запустить цикл записи (legacy, обратная совместимость)."""
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(queue), name="sqlite_writer")
        logger.info("SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size)

    async def stop(self) -> None:
        """Остановить цикл, дождаться завершения, закрыть БД."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Shutdown executor FIRST — waits for any in-flight write_batch to finish.
        # Then close connection — no race with executor thread.
        if self._executor is not None:
            self._executor.shutdown(wait=True)
        if self._read_executor is not None:
            self._read_executor.shutdown(wait=True)
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)

    # ------------------------------------------------------------------
    # Readings history query (for GUI reconnect / full-range view)
    # ------------------------------------------------------------------

    def _read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Read historical readings from SQLite.

        Returns {channel: [(unix_ts, value), ...]} sorted by time ASC.
        Scans all daily DB files that overlap [from_ts, to_ts].
        """
        result: dict[str, list[tuple[float, float]]] = {}
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
        if not db_files:
            return result

        # Filter DB files by date range if possible
        if from_ts is not None:
            from_day = datetime.fromtimestamp(from_ts, tz=timezone.utc).date()
        else:
            from_day = None
        if to_ts is not None:
            to_day = datetime.fromtimestamp(to_ts, tz=timezone.utc).date()
        else:
            to_day = None

        selected_dbs: list[Path] = []
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            selected_dbs.append(db_path)

        for db_path in selected_dbs:
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    query = "SELECT timestamp, channel, value FROM readings WHERE 1=1"
                    params: list[Any] = []
                    if from_ts is not None:
                        query += " AND timestamp >= ?"
                        params.append(from_ts)
                    if to_ts is not None:
                        query += " AND timestamp <= ?"
                        params.append(to_ts)
                    if channels:
                        placeholders = ",".join("?" for _ in channels)
                        query += f" AND channel IN ({placeholders})"
                        params.extend(channels)
                    query += " ORDER BY timestamp ASC"
                    for row in conn.execute(query, params).fetchall():
                        ch = row["channel"]
                        if ch not in result:
                            result[ch] = []
                        result[ch].append((float(row["timestamp"]), float(row["value"])))
                finally:
                    conn.close()
            except Exception:
                logger.warning("Ошибка чтения истории из %s", db_path)

        # Truncate to limit_per_channel (keep latest)
        for ch in result:
            if len(result[ch]) > limit_per_channel:
                result[ch] = result[ch][-limit_per_channel:]

        return result

    async def read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Async wrapper for _read_readings_history."""
        loop = asyncio.get_running_loop()
        task = partial(
            self._read_readings_history,
            channels=channels,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_per_channel=limit_per_channel,
        )
        return await loop.run_in_executor(self._read_executor, task)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }
