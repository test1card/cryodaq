"""Экспорт данных из SQLite в CSV.

Позволяет экспортировать показания за указанный временной диапазон
из одного или нескольких daily-файлов SQLite.
"""

from __future__ import annotations

import csv
import logging
import math
from datetime import datetime
from pathlib import Path

from cryodaq.storage.archive_reader import ArchiveReader
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

    def __init__(self, data_dir: Path, archive_dir: Path | None = None) -> None:
        """Инициализировать экспортёр.

        Параметры
        ----------
        data_dir:
            Директория с daily-файлами SQLite (data_YYYY-MM-DD.db).
        archive_dir:
            Директория холодного хранилища (Parquet + index.json). None →
            ``data_dir / "archive"`` (совпадает с cold_rotation.archive_dir).
            Дни, вытесненные ротацией в Parquet, читаются оттуда — иначе экспорт
            слепнет на вытесненных днях.
        """
        self._data_dir = data_dir
        self._archive_dir = archive_dir if archive_dir is not None else data_dir / "archive"

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
        # Read across hot SQLite + cold Parquet: rotated days live only in the
        # archive, so a plain SQLite scan would silently drop them. query_rows
        # already decodes the NaN-доктрина sentinel and keeps end exclusive.
        rows = ArchiveReader(self._data_dir, self._archive_dir).query_rows(start, end, channels, instrument_ids)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0

        with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp", "instrument_id", "channel", "value", "unit", "status"])

            for raw_ts, instrument_id, channel, value, unit, status in rows:
                ts = _parse_timestamp(raw_ts)
                # The value is already decoded; a non-finite (masked) reading is
                # left blank — the status column carries the discriminator.
                writer.writerow(
                    [
                        ts.isoformat(),
                        instrument_id,
                        channel,
                        value if math.isfinite(value) else "",
                        unit,
                        status,
                    ]
                )
                total += 1

        logger.info("CSV-экспорт завершён: %s (%d записей)", output_path, total)
        return total
