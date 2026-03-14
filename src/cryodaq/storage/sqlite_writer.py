"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.

Один файл на день: data_YYYY-MM-DD.db.
Батчевая вставка каждую секунду (или при накоплении batch_size).
Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

SCHEMA_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
);
"""

SCHEMA_SOURCE_DATA = """
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
        conn.execute(INDEX_READINGS_TS)
        conn.execute(INDEX_SOURCE_DATA_TS)
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
                r.timestamp.isoformat(),
                r.metadata.get("instrument_id", "unknown"),
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
        """Записать строку в source_data (для Keithley raw-данных)."""
        day = timestamp.date()
        conn = self._ensure_connection(day)
        conn.execute(
            "INSERT INTO source_data (timestamp, channel, voltage, current, resistance, power) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (timestamp.isoformat(), channel, voltage, current, resistance, power),
        )
        conn.commit()

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

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        """Запустить цикл записи."""
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
