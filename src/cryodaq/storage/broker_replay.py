"""Воспроизведение исторических данных из SQLite через DataBroker.

ReplaySource читает записи из daily-файлов SQLite и публикует их
в DataBroker с сохранением оригинальной временной структуры (или
ускоренно).  Позволяет прогонять аналитические плагины на прошлых данных.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader, _day_from_db_name
from cryodaq.storage.sentinel import decode
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    """Normalize to UTC-aware so day boundaries and user bounds are comparable."""
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


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
        if not db_path.exists():  # noqa: ASYNC240
            raise FileNotFoundError(f"Файл БД не найден: {db_path}")

        encoded = self._load_rows(db_path, start=start, end=end, channels=channels)
        if not encoded:
            logger.info("Нет данных для воспроизведения в %s", db_path.name)
            return 0

        logger.info(
            "Начало воспроизведения: %s, записей=%d, скорость=%.1fx",
            db_path.name,
            len(encoded),
            self._speed,
        )

        # NaN-доктрина: decode sentinel / error / legacy ±inf back to NaN here so
        # the republished Reading reproduces the original non-finite value, never
        # the stored sentinel, on the broker / GUI plots.
        rows = [
            (ts_posix, inst_id, channel, decode(value, status_str), unit, status_str)
            for ts_posix, channel, value, unit, status_str, inst_id in encoded
        ]
        count = await self._replay_rows(rows)
        logger.info("Воспроизведение завершено: %d записей", count)
        return count

    async def _replay_rows(
        self,
        rows: list[tuple[float, str, str, float, str, str]],
    ) -> int:
        """Publish already-decoded rows to the broker with speed pacing.

        Shared publish path for both the hot SQLite (:meth:`play`) and cold
        archive (:meth:`_play_archived_day`) sources. Each ``row`` is
        ``(ts_posix, instrument_id, channel, value, unit, status_str)`` with
        ``value`` already decoded — the caller must NOT decode twice.
        """
        self._running = True
        count = 0
        prev_ts: float | None = None

        for ts_posix, inst_id, channel, value, unit, status_str in rows:
            if not self._running:
                logger.info("Воспроизведение остановлено оператором")
                break

            # Пауза с учётом скорости
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
                timestamp=datetime.fromtimestamp(ts_posix, tz=UTC),
                instrument_id=inst_id,
                channel=channel,
                value=value,
                unit=unit,
                status=status,
                metadata={"source": "replay"},
            )

            await self._broker.publish(reading)
            count += 1
            self._total_replayed += 1

        self._running = False
        return count

    async def play_directory(
        self,
        data_dir: Path,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: list[str] | None = None,
        archive_dir: Path | None = None,
    ) -> int:
        """Воспроизвести все daily-файлы из директории (в хронологическом порядке).

        Параметры идентичны :meth:`play`, но обрабатываются все дни: и живые
        SQLite-файлы, и дни, вытесненные cold-rotation в Parquet-архив (их
        `data_*.db` уже удалён, поэтому glob их не видит). `archive_dir` по
        умолчанию — ``<data_dir>/archive`` (как в config/housekeeping.yaml);
        когда архив отсутствует/пуст, поведение байт-в-байт совпадает с
        hot-only оригиналом.

        Возвращает
        ----------
        int:  Суммарное количество воспроизведённых записей.
        """
        if not data_dir.exists():  # noqa: ASYNC240
            raise FileNotFoundError(f"Директория не найдена: {data_dir}")

        db_files = sorted(data_dir.glob("data_*.db"))  # noqa: ASYNC240
        adir = archive_dir if archive_dir is not None else data_dir / "archive"
        reader = ArchiveReader(data_dir, adir)
        archived = self._archived_days(reader)
        hot_days = {_day_from_db_name(p.name) for p in db_files}
        cold_days = archived - hot_days  # pure-cold: only in the Parquet archive
        # Overlap: a day present in BOTH a hot .db and the archive (restored /
        # backdated import). Routing it through the hot-only `play` would drop
        # the archived rows — query_rows already unions+dedups both sources, so
        # replay must go through the cold path to match that contract (F4).
        overlap_days = archived & hot_days

        if not cold_days and not overlap_days:
            # Hot-only fast path — byte-identical to the pre-archive behavior.
            total = 0
            for db_path in db_files:
                total += await self.play(db_path, start=start, end=end, channels=channels)
            return total

        # Merge hot files and cold days, replay in chronological day order.
        # ISO day keys and `data_YYYY-MM-DD.db` filenames sort identically, so a
        # plain lexical sort keeps both in true chronological order.
        items: list[tuple[str, str, object]] = []
        for p in db_files:
            day = _day_from_db_name(p.name)
            if day in overlap_days:
                # query_rows unions this day's hot .db + Parquet and dedups.
                items.append((day, "cold", day))
            else:
                items.append((day or p.name, "hot", p))
        for day_iso in cold_days:
            items.append((day_iso, "cold", day_iso))
        items.sort(key=lambda it: it[0])

        total = 0
        for _key, kind, ref in items:
            if kind == "hot":
                total += await self.play(ref, start=start, end=end, channels=channels)  # type: ignore[arg-type]
            else:
                total += await self._play_archived_day(
                    reader, ref, start=start, end=end, channels=channels  # type: ignore[arg-type]
                )
        return total

    @staticmethod
    def _archived_days(reader: ArchiveReader) -> set[str]:
        """Set of ``YYYY-MM-DD`` days present in the Parquet archive index.

        Reuses ArchiveReader's own index loader rather than re-parsing
        index.json. Returns an empty set when no archive/index exists.
        """
        index = reader._load_index()
        days = {_day_from_db_name(entry["original_name"]) for entry in index.get("files", [])}
        days.discard(None)
        return days  # type: ignore[return-value]

    async def _play_archived_day(
        self,
        reader: ArchiveReader,
        day_iso: str,
        *,
        start: datetime | None,
        end: datetime | None,
        channels: list[str] | None,
    ) -> int:
        """Replay one cold (Parquet-archived) day through the same publish path."""
        day = date.fromisoformat(day_iso)
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        # Intersect the day span with the user's [start, end) filter (end-exclusive,
        # matching query_rows and _load_rows).
        q_start = day_start if start is None else max(day_start, _as_utc(start))
        q_end = day_end if end is None else min(day_end, _as_utc(end))
        if q_start >= q_end:
            return 0

        full = await asyncio.to_thread(reader.query_rows, q_start, q_end, channels, None)
        if not full:
            return 0

        logger.info(
            "Начало воспроизведения архива: %s, записей=%d, скорость=%.1fx",
            day_iso,
            len(full),
            self._speed,
        )
        # query_rows already decoded value per NaN-доктрина — do NOT decode again.
        rows = [
            (_parse_timestamp(ts).timestamp(), inst, channel, value, unit, status)
            for ts, inst, channel, value, unit, status in full
        ]
        count = await self._replay_rows(rows)
        logger.info("Воспроизведение архива завершено: %d записей", count)
        return count

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
            query = "SELECT timestamp, channel, value, unit, status, instrument_id FROM readings"
            conditions: list[str] = []
            params: list[Any] = []

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

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp;"

            cursor = conn.execute(query, params)
            result: list[tuple[float, str, float, str, str, str]] = []

            for row in cursor:
                ts_raw, channel, value, unit, status, inst_id = row
                try:
                    dt = _parse_timestamp(ts_raw)
                    ts_posix = dt.timestamp()
                except (ValueError, TypeError, OSError):
                    continue
                result.append((ts_posix, channel, value, unit, status, inst_id or "unknown"))

            return result
        finally:
            conn.close()
