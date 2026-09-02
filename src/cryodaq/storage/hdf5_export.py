"""Экспорт данных из SQLite/Parquet в HDF5.

Один файл HDF5 на один календарный день.  Экспорт archive-aware: readings
читаются через :class:`~cryodaq.storage.archive_reader.ArchiveReader` (горячий
SQLite + холодный Parquet), поэтому день, вытесненный ротацией в Parquet,
по-прежнему экспортируется — иначе HDF5-экспорт слепнет на вытесненных днях.
``source_data`` и ``experiments`` берутся из горячего daily-файла, когда он ещё
есть (ротация срабатывает только на днях без ``source_data``).

Структура:

    /
    ├── metadata (attrs: experiment_id, start_time, ...)
    ├── <instrument_id>/
    │   ├── <channel>/
    │   │   ├── timestamp  (dataset, float64 — POSIX)
    │   │   ├── value      (dataset, float64 — NaN-доктрина: sentinel → NaN)
    │   │   ├── status     (dataset, str — дискриминатор D-C15)
    │   │   └── unit       (attr, str)
    │   └── ...
    └── source_data/
        ├── timestamp (dataset, float64)
        ├── channel   (dataset, str)
        ├── voltage   (dataset, float64)
        ├── current   (dataset, float64)
        ├── resistance(dataset, float64)
        └── power     (dataset, float64)

Instrument and channel group names in the tree above are sanitized and
uniquified for use as HDF5 paths.  Their exact identities are carried by the
``instrument_id`` and ``channel_id`` attributes on the corresponding groups.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import h5py

from cryodaq.paths import get_archive_dir
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader, FullRow, _day_from_db_name
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


def _archived_days(archive_dir: Path) -> set[str]:
    """Return rotated days, rejecting unavailable or malformed index authority."""
    idx = ArchiveReader(archive_dir.parent, archive_dir)._load_index()
    days: set[str] = set()
    for entry in idx["files"]:
        day = _day_from_db_name(entry["original_name"])
        assert day is not None
        days.add(day)
    return days


def hdf5_export_days(data_dir: Path, archive_dir: Path) -> list[str]:
    """Sorted ``YYYY-MM-DD`` days available for HDF5 export (hot ∪ cold).

    Union of the live daily SQLite files and the days rotated to Parquet, so the
    GUI can produce one ``.h5`` per day across the full retained history.
    """
    days: set[str] = set()
    if data_dir.exists():
        for db_path in data_dir.glob("data_????-??-??.db"):
            day = _day_from_db_name(db_path.name)
            if day is not None:
                days.add(day)
    days |= _archived_days(archive_dir)
    return sorted(days)


class HDF5Exporter:
    """Экспортирует данные одного дня в HDF5 (archive-aware).

    Пример использования::

        exporter = HDF5Exporter(data_dir=Path("data"))
        exporter.export(
            date(2026, 3, 14),
            output_path=Path("export/data_2026-03-14.h5"),
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
        """
        self._data_dir = data_dir
        self._archive_dir = archive_dir if archive_dir is not None else get_archive_dir(data_dir)

    def export(
        self,
        day: date | str,
        output_path: Path,
        *,
        experiment_metadata: dict[str, Any] | None = None,
    ) -> int:
        """Экспортировать данные одного дня в HDF5.

        Параметры
        ----------
        day:
            Экспортируемый день (``date`` или ISO-строка ``YYYY-MM-DD``).
        output_path:
            Путь для создаваемого HDF5-файла.
        experiment_metadata:
            Метаданные эксперимента (записываются как атрибуты корневой группы).

        Возвращает
        ----------
        int:  Общее количество экспортированных записей.
        """
        d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
        start = datetime(d.year, d.month, d.day, tzinfo=UTC)
        end = start + timedelta(days=1)

        # Readings across hot SQLite + cold Parquet. query_rows already decodes
        # the NaN-доктрина sentinel (a masked reading is NaN, status verbatim) and
        # keeps the range end-exclusive, so a rotated day still exports.
        reader = ArchiveReader(self._data_dir, self._archive_dir)
        rows = reader.query_rows(start, end, None, None)
        # Fail closed before writing: a non-null descriptor_hash with no
        # descriptor-catalog row is a dangling reference, not declared identity.
        # The bounded reader refuses it as DESCRIPTOR_CATALOG_MISSING, and the
        # exporter must not publish it as if a descriptor declared it.
        reader.verify_descriptor_references({row[6] for row in rows if row[6] is not None})

        output_path.parent.mkdir(parents=True, exist_ok=True)
        hot_db = self._data_dir / f"data_{d.isoformat()}.db"
        total = 0

        with h5py.File(str(output_path), "w") as hf:
            # --- Метаданные эксперимента ---
            if experiment_metadata:
                for key, val in experiment_metadata.items():
                    if isinstance(val, (str, int, float, bool)):
                        hf.attrs[key] = val

            hf.attrs["source_day"] = d.isoformat()
            hf.attrs["export_time"] = datetime.now(UTC).isoformat()

            # --- Readings (hot + cold) ---
            total += self._write_readings(hf, rows)

            # --- source_data / experiments: hot daily DB only. A rotated day
            #     carries no source_data (rotation skips such days), and its
            #     experiments metadata is not preserved in cold storage. ---
            if hot_db.exists():
                # Read-only: SELECT-only code needs no write authority.
                conn = sqlite3.connect(hot_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    total += self._export_source_data(conn, hf)
                    self._export_experiments(conn, hf)
                finally:
                    conn.close()

        logger.info(
            "HDF5-экспорт завершён: %s → %s (%d записей)",
            d.isoformat(),
            output_path.name,
            total,
        )
        return total

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _write_readings(self, hf: h5py.File, rows: list[FullRow]) -> int:
        """Записать readings (одна группа на instrument, датасет на канал).

        ``rows`` — уже декодированные строки из ``query_rows`` (value = NaN для
        sentinel/error, status verbatim); никакого повторного decode не нужно.
        """
        if not rows:
            return 0

        # Группировка: instrument_id → channel → накопитель
        data: dict[str, dict[str, _ChannelData]] = {}
        for raw_ts, inst_id, channel, value, unit, status, *identity in rows:
            ts = _parse_timestamp(raw_ts).timestamp()
            descriptor_hash = identity[0] if identity else None
            data.setdefault(inst_id, {}).setdefault(channel, _ChannelData(unit=unit)).append(
                ts, value, status, descriptor_hash
            )

        # Запись в HDF5
        str_dt = h5py.string_dtype()
        count = 0
        for inst_id, channels in data.items():
            inst_group = hf.create_group(_unique_child_name(hf, _sanitize_name(inst_id)))
            inst_group.attrs["instrument_id"] = inst_id
            for ch_name, ch_data in channels.items():
                ch_group = inst_group.create_group(_unique_child_name(inst_group, _sanitize_name(ch_name)))
                ch_group.attrs["channel_id"] = ch_name
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
                # Preserve the per-reading status column (D-C15).
                ch_group.create_dataset(
                    "status",
                    data=ch_data.statuses,
                    dtype=str_dt,
                    chunks=True,
                    compression="gzip",
                    compression_opts=4,
                )
                ch_group.create_dataset(
                    "descriptor_hash",
                    data=ch_data.descriptor_hashes,
                    dtype=str_dt,
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
            "SELECT timestamp, channel, voltage, current, resistance, power FROM source_data ORDER BY timestamp;"
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
        grp.create_dataset("timestamp", data=timestamps, chunks=True, compression="gzip", compression_opts=4)
        # h5py не поддерживает list[str] напрямую — используем variable-length
        dt = h5py.string_dtype()
        grp.create_dataset("channel", data=channels, dtype=dt, chunks=True, compression="gzip", compression_opts=4)
        grp.create_dataset("voltage", data=voltages, chunks=True, compression="gzip", compression_opts=4)
        grp.create_dataset("current", data=currents, chunks=True, compression="gzip", compression_opts=4)
        grp.create_dataset("resistance", data=resistances, chunks=True, compression="gzip", compression_opts=4)
        grp.create_dataset("power", data=powers, chunks=True, compression="gzip", compression_opts=4)

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

    __slots__ = ("unit", "timestamps", "values", "statuses", "descriptor_hashes")

    def __init__(self, unit: str) -> None:
        self.unit = unit
        self.timestamps: list[float] = []
        self.values: list[float] = []
        self.statuses: list[str] = []
        self.descriptor_hashes: list[str] = []

    def append(self, ts: float, value: float, status: str = "", descriptor_hash: str | None = None) -> None:
        self.timestamps.append(ts)
        self.values.append(value)
        self.statuses.append(status)
        self.descriptor_hashes.append(descriptor_hash or "")


def _sanitize_name(name: str) -> str:
    """Привести строку к допустимому имени HDF5-группы."""
    # Заменяем пробелы и спецсимволы на подчёркивания
    return name.replace("/", "_").replace(" ", "_").replace(":", "_")


def _unique_child_name(parent: h5py.Group, base: str) -> str:
    """Return a name unique within ``parent`` (append _2, _3 … on collision).

    Distinct source names can sanitize to the same string (e.g. 'A:B' and
    'A B' → 'A_B'); reusing the group then crashes on duplicate datasets.
    """
    if base not in parent:
        return base
    i = 2
    while f"{base}_{i}" in parent:
        i += 1
    return f"{base}_{i}"
