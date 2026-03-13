"""Воспроизведение исторических данных из SQLite через DataBroker.

ReplaySource читает записи из daily-файлов SQLite и публикует их
в DataBroker с сохранением оригинальной временной структуры (или
ускоренно).  Позволяет прогонять аналитические плагины на прошлых данных.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)


class ReplaySource:
    """Источник воспроизведения исторических данных.

    Пример использования::

        replay = ReplaySource(broker, speed=10.0)
        count = await replay.play(Path("data/data_2026-03-14.db"))

    Параметры
    ----------
    broker:
        DataBroker, в который публикуются воспроизводимые данные.
    speed:
        Множитель скорости: 1.0 — реальное время, 10.0 — в 10 раз быстрее,
        0.0 — без пауз (максимальная скорость).
    """

    def __init__(self, broker: DataBroker, *, speed: float = 1.0) -> None:
        self._broker = broker
        self._speed = max(speed, 0.0)
        self._running = False
        self._total_replayed: int = 0

    @property
    def total_replayed(self) -> int:
        """Общее количество воспроизведённых записей."""
        return self._total_replayed

    async def play(
        self,
        db_path: Path,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[str] | None = None,
    ) -> int:
        """Воспроизвести данные из SQLite-файла.

        Параметры
        ----------
        db_path:
            Путь к daily-файлу SQLite.
        start:
            Начало диапазона (включительно).  None → с начала файла.
        end:
            Конец диапазона (исключительно).  None → до конца файла.
        channels:
            Фильтр по каналам.  None → все каналы.

        Возвращает
        ----------
        int:  Количество воспроизведённых записей.
        """
        if not db_path.exists():
            raise FileNotFoundError(f"Файл БД не найден: {db_path}")

        rows = self._load_rows(db_path, start=start, end=end, channels=channels)
        if not rows:
            logger.info("Нет данных для воспроизведения в %s", db_path.name)
            return 0

        logger.info(
            "Начало воспроизведения: %s, записей=%d, скорость=%.1fx",
            db_path.name, len(rows), self._speed,
        )

        self._running = True
        count = 0
        prev_ts: float | None = None

        for row in rows:
            if not self._running:
                logger.info("Воспроизведение остановлено оператором")
                break

            ts_posix, channel, value, unit, status_str, inst_id = row

            # Пауза с учётом скорости
            if prev_ts is not None and self._speed > 0.0:
                delta = ts_posix - prev_ts
                if delta > 0:
                    await asyncio.sleep(delta / self._speed)
            prev_ts = ts_posix

            # Восстановить Reading
            try:
                status = ChannelStatus(status_str)
            except ValueError:
                status = ChannelStatus.OK

            reading = Reading(
                timestamp=datetime.fromtimestamp(ts_posix, tz=timezone.utc),
                channel=channel,
                value=value,
                unit=unit,
                status=status,
                metadata={"instrument_id": inst_id, "source": "replay"},
            )

            await self._broker.publish(reading)
            count += 1
            self._total_replayed += 1

        self._running = False
        logger.info("Воспроизведение завершено: %d записей", count)
        return count

    async def play_directory(
        self,
        data_dir: Path,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[str] | None = None,
    ) -> int:
        """Воспроизвести все daily-файлы из директории (в хронологическом порядке).

        Параметры идентичны :meth:`play`, но обрабатываются все файлы.

        Возвращает
        ----------
        int:  Суммарное количество воспроизведённых записей.
        """
        if not data_dir.exists():
            raise FileNotFoundError(f"Директория не найдена: {data_dir}")

        db_files = sorted(data_dir.glob("data_*.db"))
        total = 0
        for db_path in db_files:
            total += await self.play(db_path, start=start, end=end, channels=channels)
        return total

    def stop(self) -> None:
        """Запросить остановку воспроизведения."""
        self._running = False

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _load_rows(
        self,
        db_path: Path,
        *,
        start: datetime | None,
        end: datetime | None,
        channels: list[str] | None,
    ) -> list[tuple[float, str, float, str, str, str]]:
        """Загрузить строки из readings, отсортированные по timestamp."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            query = (
                "SELECT timestamp, channel, value, unit, status, instrument_id "
                "FROM readings"
            )
            conditions: list[str] = []
            params: list[Any] = []

            if start is not None:
                conditions.append("timestamp >= ?")
                params.append(start.isoformat())
            if end is not None:
                conditions.append("timestamp < ?")
                params.append(end.isoformat())
            if channels:
                placeholders = ",".join("?" * len(channels))
                conditions.append(f"channel IN ({placeholders})")
                params.extend(channels)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp;"

            cursor = conn.execute(query, params)
            result: list[tuple[float, str, float, str, str, str]] = []

            for row in cursor:
                ts_str, channel, value, unit, status, inst_id = row
                try:
                    dt = datetime.fromisoformat(ts_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts_posix = dt.timestamp()
                except (ValueError, TypeError):
                    continue
                result.append((ts_posix, channel, value, unit, status, inst_id or "unknown"))

            return result
        finally:
            conn.close()
