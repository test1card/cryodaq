"""Воспроизведение исторических данных из SQLite через DataBroker.

ReplaySource читает записи из daily-файлов SQLite и публикует их
в DataBroker с сохранением оригинальной временной структуры (или
ускоренно).  Позволяет прогонять аналитические плагины на прошлых данных.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import (
    ArchiveReader,
    BoundedReadingQueryResult,
    BoundedReadIssue,
    BoundedReadIssueCode,
    _day_from_db_name,
)
from cryodaq.storage.descriptor_archive import ResolvedStorageDescriptor
from cryodaq.storage.sentinel import decode
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DescriptorReplayReading:
    """One descriptor-qualified historical reading with no live authority.

    This carrier deliberately does not inherit from :class:`Reading`.  The
    current broker contract has only mutable metadata for extension fields,
    which cannot safely own canonical descriptor identity.  A later reviewed
    cutover may translate this value into the descriptor-aware wire contract;
    until then it remains observational and cannot be published accidentally
    through :class:`DataBroker`'s existing ``Reading`` API.
    """

    timestamp: datetime
    instrument_id: str
    channel_id: str
    value: float | None
    unit: str
    status: str
    descriptor: ResolvedStorageDescriptor

    @property
    def descriptor_envelope(self) -> bytes | None:
        """Exact canonical persisted bytes, or ``None`` for explicit legacy."""

        return self.descriptor.envelope_json

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class DescriptorReplayBatch:
    """Bounded replay projection plus its fail-closed evidence ledger."""

    readings: tuple[DescriptorReplayReading, ...]
    complete: bool
    truncated: bool
    issues: tuple[BoundedReadIssue, ...]
    issue_overflow: int
    discovered_channels: tuple[str, ...]
    rows_examined: int
    rows_dropped_by_caps: int
    retained_encoded_bytes: int

    @property
    def grants_control_authority(self) -> bool:
        return False


class DescriptorReplayReader:
    """Read descriptor-qualified hot/cold/overlap history off the event loop.

    The underlying bounded reader verifies canonical descriptor envelopes and
    performs value+descriptor dedup as one retained row.  Descriptor-bearing
    corruption is reported in ``issues`` and omitted; it is never converted to
    a synthetic legacy descriptor.  Genuine pre-descriptor rows remain
    explicit ``legacy_unknown`` values with no canonical envelope.
    """

    def __init__(self, data_dir: Path, archive_dir: Path | None = None) -> None:
        self._reader = ArchiveReader(
            data_dir,
            archive_dir if archive_dir is not None else data_dir / "archive",
        )

    async def read_window(
        self,
        *,
        start: datetime,
        end: datetime,
        channels: Sequence[str] | None = None,
        max_channels: int = 64,
        max_points_per_channel: int = 100_000,
        max_total_points: int = 500_000,
        max_retained_bytes: int = 32 * 1024 * 1024,
        deadline_seconds: float = 30.0,
        batch_rows: int = 2048,
        max_arrow_batch_bytes: int = 4 * 1024 * 1024,
    ) -> DescriptorReplayBatch:
        if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float)):
            raise TypeError("deadline_seconds must be numeric")
        if not 0.0 < float(deadline_seconds) <= 300.0:
            raise ValueError("deadline_seconds must be in (0, 300]")
        query_task = asyncio.create_task(
            asyncio.to_thread(
                self._reader.query_reading_rows_bounded,
                start=start,
                end=end,
                channels=channels,
                max_channels=max_channels,
                max_points_per_channel=max_points_per_channel,
                max_total_points=max_total_points,
                max_retained_bytes=max_retained_bytes,
                deadline_monotonic=time.monotonic() + float(deadline_seconds),
                batch_rows=batch_rows,
                max_arrow_batch_bytes=max_arrow_batch_bytes,
            ),
            name="descriptor-replay-bounded-query",
        )
        try:
            await asyncio.wait({query_task})
        except asyncio.CancelledError as cancellation:
            # asyncio.to_thread cannot stop a running worker.  Keep ownership
            # until its bounded query settles so cancellation cannot detach
            # SQLite/Parquet handles.  Repeated cancel() calls are consumed
            # only for settlement; the first caller cancellation remains the
            # terminal outcome after the worker releases every resource.
            while not query_task.done():
                try:
                    await asyncio.wait({query_task})
                except asyncio.CancelledError:
                    continue
            try:
                query_task.result()
            except BaseException:
                # The caller cancellation is dominant, but the worker outcome
                # must be retrieved so neither Task nor loop handler owns it.
                pass
            raise cancellation
        result = query_task.result()
        return self._from_query_result(result)

    @staticmethod
    def _from_query_result(result: BoundedReadingQueryResult) -> DescriptorReplayBatch:
        missing_descriptor = any(row.descriptor is None for row in result.rows)
        readings = tuple(
            DescriptorReplayReading(
                timestamp=datetime.fromtimestamp(row.timestamp, tz=UTC),
                instrument_id=row.instrument_id,
                channel_id=row.channel,
                value=row.value,
                unit=row.unit,
                status=row.status,
                descriptor=row.descriptor,
            )
            for row in result.rows
            if row.descriptor is not None
        )
        issues = result.issues
        issue_overflow = result.issue_overflow
        if missing_descriptor:
            missing_issue = BoundedReadIssue(
                code=BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING,
                source="replay_adapter",
            )
            if len(issues) < 32:
                issues = (*issues, missing_issue)
            else:
                issue_overflow += 1
        return DescriptorReplayBatch(
            readings=readings,
            complete=result.complete and not missing_descriptor,
            truncated=result.truncated,
            issues=issues,
            issue_overflow=issue_overflow,
            discovered_channels=result.discovered_channels,
            rows_examined=result.rows_examined,
            rows_dropped_by_caps=result.rows_dropped_by_caps,
            retained_encoded_bytes=result.retained_encoded_bytes,
        )


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
        self._stop_generation = 0
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
        _generation: int | None = None,
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
        generation = self._stop_generation if _generation is None else _generation
        if generation != self._stop_generation:
            return 0
        if not db_path.exists():  # noqa: ASYNC240
            raise FileNotFoundError(f"Файл БД не найден: {db_path}")

        encoded = await asyncio.to_thread(
            self._load_rows,
            db_path,
            start=start,
            end=end,
            channels=channels,
        )
        if generation != self._stop_generation:
            logger.info("Replay was stopped while loading %s", db_path.name)
            return 0
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
        count = await self._replay_rows(rows, generation=generation)
        logger.info("Воспроизведение завершено: %d записей", count)
        return count

    async def _replay_rows(
        self,
        rows: list[tuple[float, str, str, float, str, str]],
        *,
        generation: int,
    ) -> int:
        """Publish already-decoded rows to the broker with speed pacing.

        Shared publish path for both the hot SQLite (:meth:`play`) and cold
        archive (:meth:`_play_archived_day`) sources. Each ``row`` is
        ``(ts_posix, instrument_id, channel, value, unit, status_str)`` with
        ``value`` already decoded — the caller must NOT decode twice.
        """
        if generation != self._stop_generation:
            return 0
        self._running = True
        count = 0
        prev_ts: float | None = None

        try:
            for ts_posix, inst_id, channel, value, unit, status_str in rows:
                if not self._running or generation != self._stop_generation:
                    logger.info("Воспроизведение остановлено оператором")
                    break

                # Пауза с учётом скорости
                if prev_ts is not None and self._speed > 0.0:
                    delta = ts_posix - prev_ts
                    if delta > 0:
                        await asyncio.sleep(delta / self._speed)
                    if not self._running or generation != self._stop_generation:
                        logger.info("Воспроизведение остановлено оператором")
                        break
                prev_ts = ts_posix

                try:
                    status = ChannelStatus(status_str)
                except ValueError:
                    logger.warning(
                        "Unknown persisted replay status %r for %s/%s; failing closed",
                        status_str,
                        inst_id,
                        channel,
                    )
                    status = ChannelStatus.SENSOR_ERROR

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
        finally:
            if generation == self._stop_generation:
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
        generation = self._stop_generation
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
                if generation != self._stop_generation:
                    break
                total += await self.play(
                    db_path,
                    start=start,
                    end=end,
                    channels=channels,
                    _generation=generation,
                )
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
            if generation != self._stop_generation:
                break
            if kind == "hot":
                total += await self.play(  # type: ignore[arg-type]
                    ref,
                    start=start,
                    end=end,
                    channels=channels,
                    _generation=generation,
                )
            else:
                total += await self._play_archived_day(
                    reader,
                    ref,
                    start=start,
                    end=end,
                    channels=channels,  # type: ignore[arg-type]
                    generation=generation,
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
        generation: int,
    ) -> int:
        """Replay one cold (Parquet-archived) day through the same publish path."""
        if generation != self._stop_generation:
            return 0
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
        if generation != self._stop_generation:
            logger.info("Replay was stopped while loading archived day %s", day_iso)
            return 0
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
        count = await self._replay_rows(rows, generation=generation)
        logger.info("Воспроизведение архива завершено: %d записей", count)
        return count

    def stop(self) -> None:
        """Запросить остановку воспроизведения."""
        self._stop_generation += 1
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
