"""Экспорт данных из SQLite в CSV.

Позволяет экспортировать показания за указанный временной диапазон
из одного или нескольких daily-файлов SQLite.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


class CSVExporter:
    """Экспортирует показания из SQLite в CSV.

    Пример использования::

        exporter = CSVExporter(data_dir=Path("data"))
        count = exporter.export(
            output_path=Path("export/readings.csv"),
            start=datetime(2026, 3, 14, tzinfo=timezone.utc),
            end=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
    """

    def __init__(self, data_dir: Path) -> None:
        """Инициализировать экспортёр.

        Параметры
        ----------
        data_dir:
            Директория с daily-файлами SQLite (data_YYYY-MM-DD.db).
        """
        self._data_dir = data_dir

    def export(
        self,
        output_path: Path,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[str] | None = None,
        instrument_ids: list[str] | None = None,
    ) -> int:
        """Экспортировать показания в CSV.

        Параметры
        ----------
        output_path:
            Путь для создаваемого CSV-файла.
        start:
            Начало временного диапазона (включительно).  None → без ограничения.
        end:
            Конец временного диапазона (исключительно).  None → без ограничения.
        channels:
            Фильтр по именам каналов.  None → все каналы.
        instrument_ids:
            Фильтр по идентификаторам приборов.  None → все приборы.

        Возвращает
        ----------
        int:  Количество экспортированных строк.
        """
        db_files = self._find_db_files(start, end)
        if not db_files:
            logger.warning("Не найдено файлов БД для указанного диапазона")
            return 0

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0

        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp", "instrument_id", "channel", "value", "unit", "status"])

            for db_path in db_files:
                total += self._export_from_db(
                    db_path, writer,
                    start=start, end=end,
                    channels=channels, instrument_ids=instrument_ids,
                )

        logger.info(
            "CSV-экспорт завершён: %s (%d записей из %d файлов БД)",
            output_path, total, len(db_files),
        )
        return total

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _find_db_files(
        self, start: datetime | None, end: datetime | None,
    ) -> list[Path]:
        """Найти daily-файлы SQLite, покрывающие указанный диапазон."""
        if not self._data_dir.exists():
            return []

        all_files = sorted(self._data_dir.glob("data_*.db"))
        if start is None and end is None:
            return all_files

        result: list[Path] = []
        for path in all_files:
            # Извлечь дату из имени файла: data_2026-03-14.db
            stem = path.stem  # data_2026-03-14
            date_str = stem.replace("data_", "")
            try:
                file_date = date.fromisoformat(date_str)
            except ValueError:
                continue

            if start is not None and file_date < start.date():
                continue
            if end is not None and file_date > end.date():
                continue
            result.append(path)

        return result

    def _export_from_db(
        self,
        db_path: Path,
        writer: csv.writer,
        *,
        start: datetime | None,
        end: datetime | None,
        channels: list[str] | None,
        instrument_ids: list[str] | None,
    ) -> int:
        """Экспортировать записи из одного файла БД."""
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row

        try:
            query = "SELECT timestamp, instrument_id, channel, value, unit, status FROM readings"
            conditions: list[str] = []
            params: list[str | float] = []

            if start is not None:
                conditions.append("timestamp >= ?")
                params.append(start.timestamp())
            if end is not None:
                conditions.append("timestamp < ?")
                params.append(end.timestamp())
            if channels:
                placeholders = ",".join("?" * len(channels))
                conditions.append(f"channel IN ({placeholders})")
                params.extend(channels)
            if instrument_ids:
                placeholders = ",".join("?" * len(instrument_ids))
                conditions.append(f"instrument_id IN ({placeholders})")
                params.extend(instrument_ids)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp;"

            cursor = conn.execute(query, params)
            count = 0
            for row in cursor:
                ts = _parse_timestamp(row["timestamp"])
                writer.writerow([
                    ts.isoformat(),
                    row["instrument_id"],
                    row["channel"],
                    row["value"],
                    row["unit"],
                    row["status"],
                ])
                count += 1

            return count
        finally:
            conn.close()
