"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.

Один файл на день: data_YYYY-MM-DD.db.
Батчевая вставка каждую секунду (или при накоплении batch_size).
Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
from cryodaq.drivers.base import Reading

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
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")

    def _db_path(self, day: date) -> Path:
        return self._data_dir / f"data_{day.isoformat()}.db"

    def _ensure_connection(self, day: date) -> sqlite3.Connection:
        """Открыть/переоткрыть БД если сменился день."""
        if self._conn is not None and self._current_date == day:
            return self._conn
        if self._conn is not None:
            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
            self._conn.close()
        db_path = self._db_path(day)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
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
        """Вставить пакет в таблицу readings (вызывается в потоке)."""
        if not batch:
            return
        day = batch[0].timestamp.date()
        conn = self._ensure_connection(day)
        rows = [
            (
                r.timestamp.timestamp(),
                r.instrument_id or "unknown",
                r.channel,
                r.value,
                r.unit,
                r.status.value,
            )
            for r in batch
        ]
        conn.executemany(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            rows,
        )
        conn.commit()
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
        if self._conn:
            self._conn.close()
            self._conn = None
        self._executor.shutdown(wait=False)
        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }
