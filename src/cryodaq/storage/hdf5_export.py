"""Экспорт данных из SQLite в HDF5.

Один файл HDF5 на один daily-файл SQLite.  Структура:

    /
    ├── metadata (attrs: experiment_id, start_time, ...)
    ├── <instrument_id>/
    │   ├── <channel>/
    │   │   ├── timestamp  (dataset, float64 — POSIX)
    │   │   ├── value      (dataset, float64)
    │   │   └── unit       (attr, str)
    │   └── ...
    └── source_data/
        ├── timestamp (dataset, float64)
        ├── channel   (dataset, str)
        ├── voltage   (dataset, float64)
        ├── current   (dataset, float64)
        ├── resistance(dataset, float64)
        └── power     (dataset, float64)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py

from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


class HDF5Exporter:
    """Экспортирует daily-файл SQLite в HDF5.

    Пример использования::

        exporter = HDF5Exporter()
        exporter.export(
            db_path=Path("data/data_2026-03-14.db"),
            output_path=Path("export/data_2026-03-14.h5"),
        )
    """

    def export(
        self,
        db_path: Path,
        output_path: Path,
        *,
        experiment_metadata: dict[str, Any] | None = None,
    ) -> int:
        """Экспортировать данные из SQLite в HDF5.

        Параметры
        ----------
        db_path:
            Путь к SQLite-файлу (data_YYYY-MM-DD.db).
        output_path:
            Путь для создаваемого HDF5-файла.
        experiment_metadata:
            Метаданные эксперимента (записываются как атрибуты корневой группы).

        Возвращает
        ----------
        int:  Общее количество экспортированных записей.
        """
        if not db_path.exists():
            raise FileNotFoundError(f"Файл БД не найден: {db_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        total = 0

        try:
            with h5py.File(str(output_path), "w") as hf:
                # --- Метаданные эксперимента ---
                if experiment_metadata:
                    for key, val in experiment_metadata.items():
                        if isinstance(val, (str, int, float, bool)):
                            hf.attrs[key] = val

                hf.attrs["source_db"] = str(db_path)
                hf.attrs["export_time"] = datetime.now(UTC).isoformat()

                # --- Readings ---
                total += self._export_readings(conn, hf)

                # --- Source data ---
                total += self._export_source_data(conn, hf)

                # --- Experiment records ---
                self._export_experiments(conn, hf)

        finally:
            conn.close()

        logger.info(
            "HDF5-экспорт завершён: %s → %s (%d записей)",
            db_path.name,
            output_path.name,
            total,
        )
        return total

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _export_readings(self, conn: sqlite3.Connection, hf: h5py.File) -> int:
        """Экспортировать таблицу readings (одна группа на instrument, датасет на канал)."""
        cursor = conn.execute(
            "SELECT timestamp, instrument_id, channel, value, unit, status "
            "FROM readings ORDER BY timestamp;"
        )
        rows = cursor.fetchall()
        if not rows:
            return 0

        # Группировка: instrument_id → channel → [(ts, value, unit)]
        data: dict[str, dict[str, _ChannelData]] = {}
        for row in rows:
            ts_str, inst_id, channel, value, unit, _status = (
                row["timestamp"],
                row["instrument_id"],
                row["channel"],
                row["value"],
                row["unit"],
                row["status"],
            )
            ts = _parse_timestamp(ts_str).timestamp()
            data.setdefault(inst_id, {}).setdefault(channel, _ChannelData(unit=unit)).append(
                ts, value
            )

        # Запись в HDF5
        count = 0
        for inst_id, channels in data.items():
            inst_group = hf.require_group(_sanitize_name(inst_id))
            for ch_name, ch_data in channels.items():
                ch_group = inst_group.require_group(_sanitize_name(ch_name))
                ch_group.create_dataset(
                    "timestamp",
                    data=ch_data.timestamps,
                    chunks=True,
                    compression="gzip",
                    compression_opts=4,
                )
                ch_group.create_dataset(
                    "value",
                    data=ch_data.values,
                    chunks=True,
                    compression="gzip",
                    compression_opts=4,
                )
                ch_group.attrs["unit"] = ch_data.unit
                ch_group.attrs["count"] = len(ch_data.timestamps)
                count += len(ch_data.timestamps)

        return count

    def _export_source_data(self, conn: sqlite3.Connection, hf: h5py.File) -> int:
        """Экспортировать таблицу source_data (Keithley raw)."""
        cursor = conn.execute(
            "SELECT timestamp, channel, voltage, current, resistance, power "
            "FROM source_data ORDER BY timestamp;"
        )
        rows = cursor.fetchall()
        if not rows:
            return 0

        timestamps: list[float] = []
        channels: list[str] = []
        voltages: list[float] = []
        currents: list[float] = []
        resistances: list[float] = []
        powers: list[float] = []

        for row in rows:
            timestamps.append(_parse_timestamp(row["timestamp"]).timestamp())
            channels.append(row["channel"] or "")
            voltages.append(row["voltage"] if row["voltage"] is not None else float("nan"))
            currents.append(row["current"] if row["current"] is not None else float("nan"))
            resistances.append(row["resistance"] if row["resistance"] is not None else float("nan"))
            powers.append(row["power"] if row["power"] is not None else float("nan"))

        grp = hf.require_group("source_data")
        grp.create_dataset(
            "timestamp", data=timestamps, chunks=True, compression="gzip", compression_opts=4
        )
        # h5py не поддерживает list[str] напрямую — используем variable-length
        dt = h5py.string_dtype()
        grp.create_dataset(
            "channel", data=channels, dtype=dt, chunks=True, compression="gzip", compression_opts=4
        )
        grp.create_dataset(
            "voltage", data=voltages, chunks=True, compression="gzip", compression_opts=4
        )
        grp.create_dataset(
            "current", data=currents, chunks=True, compression="gzip", compression_opts=4
        )
        grp.create_dataset(
            "resistance", data=resistances, chunks=True, compression="gzip", compression_opts=4
        )
        grp.create_dataset(
            "power", data=powers, chunks=True, compression="gzip", compression_opts=4
        )

        return len(rows)

    def _export_experiments(self, conn: sqlite3.Connection, hf: h5py.File) -> None:
        """Экспортировать таблицу experiments как атрибуты группы."""
        try:
            cursor = conn.execute(
                "SELECT experiment_id, name, operator, cryostat, sample, "
                "description, start_time, end_time, status "
                "FROM experiments;"
            )
        except sqlite3.OperationalError:
            # Таблица не существует — ничего страшного
            return

        rows = cursor.fetchall()
        if not rows:
            return

        grp = hf.require_group("experiments")
        for i, row in enumerate(rows):
            exp_grp = grp.require_group(row["experiment_id"] or f"exp_{i}")
            for key in (
                "name",
                "operator",
                "cryostat",
                "sample",
                "description",
                "start_time",
                "end_time",
                "status",
            ):
                val = row[key]
                if val is not None:
                    exp_grp.attrs[key] = str(val)


# ---------------------------------------------------------------------------
# Вспомогательные классы и функции
# ---------------------------------------------------------------------------


class _ChannelData:
    """Накопитель данных одного канала для экспорта."""

    __slots__ = ("unit", "timestamps", "values")

    def __init__(self, unit: str) -> None:
        self.unit = unit
        self.timestamps: list[float] = []
        self.values: list[float] = []

    def append(self, ts: float, value: float) -> None:
        self.timestamps.append(ts)
        self.values.append(value)


def _sanitize_name(name: str) -> str:
    """Привести строку к допустимому имени HDF5-группы."""
    # Заменяем пробелы и спецсимволы на подчёркивания
    return name.replace("/", "_").replace(" ", "_").replace(":", "_")
