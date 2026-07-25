"""Unified read layer across SQLite (recent) and Parquet (archived) data.

ArchiveReader queries both sources transparently, using the archive index
to determine which daily files have been rotated to Parquet cold storage.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import os
import stat
import struct
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import quote

from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    verify_descriptor_storage,
)
from cryodaq.storage.descriptor_archive import (
    MAX_ARCHIVE_DESCRIPTOR_BYTES,
    MAX_ARCHIVE_DESCRIPTORS,
    ArchivedDescriptor,
    DescriptorArchiveError,
    ResolvedStorageDescriptor,
    load_referenced_descriptors,
    resolve_archived_descriptors,
    resolve_legacy_descriptor,
)
from cryodaq.storage.sentinel import decode
from cryodaq.storage.sqlite_writer import _parse_timestamp

logger = logging.getLogger(__name__)

_MAX_DESCRIPTOR_REFERENCE_ROWS = 10_000_000


def _identity_change_time_ns(info: os.stat_result) -> int:
    if os.name == "nt":
        return getattr(info, "st_birthtime_ns", info.st_ctime_ns)
    return info.st_ctime_ns


def _ts_sort_key(raw: object) -> float:
    """Epoch-float sort key for mixed REAL/legacy-ISO timestamp values."""
    try:
        return _parse_timestamp(raw).timestamp()
    except (ValueError, TypeError, OSError):
        return float("inf")


def _day_from_db_name(name: str) -> str | None:
    """Extract the ``YYYY-MM-DD`` day from a ``data_YYYY-MM-DD.db`` filename."""
    day_part = name.removeprefix("data_")[:10]
    try:
        date.fromisoformat(day_part)
    except ValueError:
        return None
    return day_part


# Full row emitted by :meth:`ArchiveReader.query_rows` — value is already
# decoded (NaN-доктрина); status is the raw discriminator string.
FullRow = tuple[object, str, str, float, str, str]

# Raw operator_log row: (timestamp, experiment_id, author, source, message, tags).
# timestamp is a raw epoch float, tags a raw JSON string; the caller applies the
# experiment_id filter and decodes tags (CR-3 cold-read boundary).
OperatorLogRow = tuple[object, str | None, str, str, str, str]


class BoundedReadIssueCode(StrEnum):
    """Stable, redacted failure codes for bounded history hydration."""

    DEADLINE = "deadline"
    ARCHIVE_INDEX_INVALID = "archive_index_invalid"
    ARCHIVE_INDEX_OVERSIZE = "archive_index_oversize"
    CHANNEL_LIMIT = "channel_limit"
    SOURCE_MISSING = "source_missing"
    SQLITE_BUSY = "sqlite_busy"
    SQLITE_INTERRUPTED = "sqlite_interrupted"
    SQLITE_VALUE_OVERSIZE = "sqlite_value_oversize"
    SQLITE_READ = "sqlite_read"
    LEGACY_TIMESTAMP_UNSUPPORTED = "legacy_timestamp_unsupported"
    PARQUET_METADATA = "parquet_metadata"
    PARQUET_SCHEMA = "parquet_schema"
    PARQUET_BATCH_OVERSIZE = "parquet_batch_oversize"
    PARQUET_READ = "parquet_read"
    INVALID_ROW = "invalid_row"
    DESCRIPTOR_CATALOG_MISSING = "descriptor_catalog_missing"
    DESCRIPTOR_INDEX_MISMATCH = "descriptor_index_mismatch"
    DESCRIPTOR_SCHEMA_MISMATCH = "descriptor_schema_mismatch"
    DESCRIPTOR_OVERSIZED = "descriptor_oversized"
    DESCRIPTOR_ENVELOPE_CORRUPT = "descriptor_envelope_corrupt"
    DESCRIPTOR_HASH_MISSING = "descriptor_hash_missing"
    DESCRIPTOR_READING_MISMATCH = "descriptor_reading_mismatch"


@dataclass(frozen=True, slots=True)
class BoundedReadIssue:
    code: BoundedReadIssueCode
    source: str


@dataclass(frozen=True, slots=True)
class BoundedReadingRow:
    timestamp: float
    instrument_id: str
    channel: str
    value: float | None
    unit: str
    status: str
    descriptor: ResolvedStorageDescriptor | None = None


@dataclass(frozen=True, slots=True)
class BoundedReadingQueryResult:
    rows: tuple[BoundedReadingRow, ...]
    complete: bool
    truncated: bool
    issues: tuple[BoundedReadIssue, ...]
    issue_overflow: int
    discovered_channels: tuple[str, ...]
    rows_examined: int
    rows_dropped_by_caps: int
    retained_encoded_bytes: int


@dataclass(frozen=True, slots=True)
class _BoundedSource:
    day: date
    kind: str
    path: Path
    token: str
    index_entry: dict[str, object] | None = None


@dataclass(slots=True)
class _CollectedRow:
    timestamp_us: int
    instrument_id: str
    channel: str
    value: float | None
    unit: str
    status: str
    authority: tuple[int, int]
    token: int
    encoded_size: int
    descriptor: ResolvedStorageDescriptor

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.timestamp_us, self.instrument_id, self.channel)

    @property
    def rank(self) -> tuple[int, str, str]:
        return self.key


def _canonical_row_size(row: BoundedReadingRow) -> int:
    return len(
        json.dumps(
            [
                row.timestamp,
                row.instrument_id,
                row.channel,
                row.value,
                row.unit,
                row.status,
                None if row.descriptor is None else row.descriptor.descriptor_hash,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ) + (0 if row.descriptor is None or row.descriptor.envelope_json is None else len(row.descriptor.envelope_json))


class _BoundedReadingCollector:
    """Newest-row collector whose maps, heaps and encoded bytes are hard-capped."""

    def __init__(
        self,
        *,
        max_points_per_channel: int,
        max_total_points: int,
        max_retained_bytes: int,
    ) -> None:
        self._per_channel_cap = max_points_per_channel
        self._total_cap = max_total_points
        self._byte_cap = max_retained_bytes
        self._by_key: dict[tuple[int, str, str], _CollectedRow] = {}
        self._global_heap: list[tuple[tuple[int, str, str], int, tuple[int, str, str]]] = []
        self._channel_heaps: dict[str, list[tuple[tuple[int, str, str], int, tuple[int, str, str]]]] = defaultdict(list)
        self._channel_counts: dict[str, int] = defaultdict(int)
        self._next_token = 0
        self.retained_encoded_bytes = 0
        self.rows_examined = 0
        self.rows_dropped_by_caps = 0
        self.truncated = False

    def _entry(self, row: _CollectedRow) -> tuple[tuple[int, str, str], int, tuple[int, str, str]]:
        return (row.rank, row.token, row.key)

    def _is_live(self, entry: tuple[tuple[int, str, str], int, tuple[int, str, str]]) -> bool:
        row = self._by_key.get(entry[2])
        return row is not None and row.token == entry[1]

    def _pop_live(self, heap: list[tuple[tuple[int, str, str], int, tuple[int, str, str]]]) -> _CollectedRow | None:
        while heap:
            entry = heapq.heappop(heap)
            if self._is_live(entry):
                return self._by_key[entry[2]]
        return None

    def _evict(self, row: _CollectedRow) -> None:
        current = self._by_key.get(row.key)
        if current is None or current.token != row.token:
            return
        del self._by_key[row.key]
        self._channel_counts[row.channel] -= 1
        if self._channel_counts[row.channel] == 0:
            del self._channel_counts[row.channel]
        self.retained_encoded_bytes -= row.encoded_size
        self.rows_dropped_by_caps += 1
        self.truncated = True

    def _compact_heaps(self) -> None:
        threshold = 2 * len(self._by_key) + 64
        if len(self._global_heap) > threshold:
            self._global_heap = [self._entry(row) for row in self._by_key.values()]
            heapq.heapify(self._global_heap)
        for channel in tuple(self._channel_heaps):
            heap = self._channel_heaps[channel]
            count = self._channel_counts.get(channel, 0)
            if len(heap) > 2 * count + 64:
                heap = [self._entry(row) for row in self._by_key.values() if row.channel == channel]
                if heap:
                    heapq.heapify(heap)
                    self._channel_heaps[channel] = heap
                else:
                    del self._channel_heaps[channel]

    def offer(
        self,
        *,
        timestamp_us: int,
        instrument_id: str,
        channel: str,
        value: float | None,
        unit: str,
        status: str,
        authority: tuple[int, int],
        descriptor: ResolvedStorageDescriptor,
    ) -> None:
        public = BoundedReadingRow(
            timestamp=timestamp_us / 1_000_000.0,
            instrument_id=instrument_id,
            channel=channel,
            value=value,
            unit=unit,
            status=status,
            descriptor=descriptor,
        )
        encoded_size = _canonical_row_size(public)
        if encoded_size > self._byte_cap:
            self.rows_dropped_by_caps += 1
            self.truncated = True
            return
        key = (timestamp_us, instrument_id, channel)
        prior = self._by_key.get(key)
        if prior is not None and authority <= prior.authority:
            return
        if prior is not None:
            self.retained_encoded_bytes -= prior.encoded_size
        else:
            self._channel_counts[channel] += 1
        self._next_token += 1
        row = _CollectedRow(
            timestamp_us=timestamp_us,
            instrument_id=instrument_id,
            channel=channel,
            value=value,
            unit=unit,
            status=status,
            authority=authority,
            token=self._next_token,
            encoded_size=encoded_size,
            descriptor=descriptor,
        )
        self._by_key[key] = row
        self.retained_encoded_bytes += encoded_size
        entry = self._entry(row)
        heapq.heappush(self._global_heap, entry)
        heapq.heappush(self._channel_heaps[channel], entry)

        channel_heap = self._channel_heaps[channel]
        while self._channel_counts.get(channel, 0) > self._per_channel_cap:
            victim = self._pop_live(channel_heap)
            if victim is not None:
                self._evict(victim)
        while len(self._by_key) > self._total_cap:
            victim = self._pop_live(self._global_heap)
            if victim is not None:
                self._evict(victim)
        while self.retained_encoded_bytes > self._byte_cap:
            victim = self._pop_live(self._global_heap)
            if victim is not None:
                self._evict(victim)
        self._compact_heaps()

    def note_examined(self) -> None:
        self.rows_examined += 1

    def discard_if_current(
        self,
        *,
        timestamp_us: int,
        instrument_id: str,
        channel: str,
        authority: tuple[int, int],
    ) -> None:
        """Remove one just-offered row if it crossed an external deadline."""
        key = (timestamp_us, instrument_id, channel)
        row = self._by_key.get(key)
        if row is None or row.authority != authority:
            return
        del self._by_key[key]
        self._channel_counts[channel] -= 1
        if self._channel_counts[channel] == 0:
            del self._channel_counts[channel]
        self.retained_encoded_bytes -= row.encoded_size

    def finish(self) -> tuple[BoundedReadingRow, ...]:
        ordered = sorted(self._by_key.values(), key=lambda row: row.rank)
        return tuple(
            BoundedReadingRow(
                timestamp=row.timestamp_us / 1_000_000.0,
                instrument_id=row.instrument_id,
                channel=row.channel,
                value=row.value,
                unit=row.unit,
                status=row.status,
                descriptor=row.descriptor,
            )
            for row in ordered
        )


class _IssueLedger:
    def __init__(self) -> None:
        self.items: list[BoundedReadIssue] = []
        self.overflow = 0

    def add(self, code: BoundedReadIssueCode, source: str) -> None:
        safe_source = source[:96]
        if len(self.items) < 32:
            self.items.append(BoundedReadIssue(code=code, source=safe_source))
        else:
            self.overflow += 1


class _ParquetMetadataError(ValueError):
    pass


class _ParquetSchemaError(TypeError):
    pass


class _IndexOversizeError(ValueError):
    pass


class _DescriptorReadError(RuntimeError):
    def __init__(self, code: BoundedReadIssueCode) -> None:
        super().__init__(code.value)
        self.code = code


def _epoch_microseconds(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return ((delta.days * 86_400) + delta.seconds) * 1_000_000 + delta.microseconds


def _sqlite_epoch_microseconds(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("timestamp is not numeric")
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("timestamp is not finite")
    dt = datetime.fromtimestamp(number, UTC)
    return _epoch_microseconds(dt)


def _bounded_text(raw: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(raw, str):
        raise ValueError("field is not text")
    size = len(raw.encode("utf-8"))
    if not minimum <= size <= maximum:
        raise ValueError("field is outside encoded bounds")
    return raw


def _bounded_value(raw: object, status: str) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("value is not numeric")
    decoded = decode(float(raw), status)
    return float(decoded) if math.isfinite(decoded) else None


class ArchiveReader:
    """Read channel data spanning SQLite (recent) + Parquet (cold archive).

    Parameters
    ----------
    data_dir:
        Directory containing daily ``data_YYYY-MM-DD.db`` SQLite files.
    archive_dir:
        Directory containing ``index.json`` and Parquet files.
    """

    def __init__(self, data_dir: Path, archive_dir: Path) -> None:
        self._data_dir = data_dir
        self._archive_dir = archive_dir

    def query_reading_rows_bounded(
        self,
        *,
        start: datetime,
        end: datetime,
        channels: Sequence[str] | None,
        max_channels: int,
        max_points_per_channel: int,
        max_total_points: int,
        max_retained_bytes: int,
        deadline_monotonic: float,
        batch_rows: int = 2048,
        max_arrow_batch_bytes: int = 4 * 1024 * 1024,
    ) -> BoundedReadingQueryResult:
        """Return a hard-bounded newest-row projection across hot and cold data.

        The method is synchronous by design. Async callers must run it in a
        worker thread; it never borrows the live writer connection.
        """

        normalized = self._validate_bounded_query(
            start=start,
            end=end,
            channels=channels,
            max_channels=max_channels,
            max_points_per_channel=max_points_per_channel,
            max_total_points=max_total_points,
            max_retained_bytes=max_retained_bytes,
            deadline_monotonic=deadline_monotonic,
            batch_rows=batch_rows,
            max_arrow_batch_bytes=max_arrow_batch_bytes,
        )
        start_utc, end_utc, explicit_channels = normalized
        start_us = _epoch_microseconds(start_utc)
        end_us = _epoch_microseconds(end_utc)
        issues = _IssueLedger()
        last_eligible_day = (end_utc - timedelta(microseconds=1)).date()
        sources = self._bounded_sources(start_utc.date(), last_eligible_day, deadline_monotonic, issues)
        if sources is None:
            return BoundedReadingQueryResult(
                rows=(),
                complete=False,
                truncated=False,
                issues=tuple(issues.items),
                issue_overflow=issues.overflow,
                discovered_channels=(),
                rows_examined=0,
                rows_dropped_by_caps=0,
                retained_encoded_bytes=0,
            )

        if explicit_channels is None and (issues.items or issues.overflow):
            return BoundedReadingQueryResult(
                rows=(),
                complete=False,
                truncated=False,
                issues=tuple(issues.items),
                issue_overflow=issues.overflow,
                discovered_channels=(),
                rows_examined=0,
                rows_dropped_by_caps=0,
                retained_encoded_bytes=0,
            )

        selected = explicit_channels
        if selected is None:
            discovered: set[str] = set()
            discovery_ok = True
            for source in sources:
                if time.monotonic() >= deadline_monotonic:
                    issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                    discovery_ok = False
                    break
                if source.kind == "sqlite":
                    ok = self._discover_sqlite_channels(
                        source,
                        start_us=start_us,
                        end_us=end_us,
                        max_channels=max_channels,
                        channels=discovered,
                        deadline_monotonic=deadline_monotonic,
                        batch_rows=batch_rows,
                        issues=issues,
                    )
                else:
                    ok = self._discover_parquet_channels(
                        source,
                        start_us=start_us,
                        end_us=end_us,
                        max_channels=max_channels,
                        channels=discovered,
                        deadline_monotonic=deadline_monotonic,
                        batch_rows=batch_rows,
                        max_arrow_batch_bytes=max_arrow_batch_bytes,
                        issues=issues,
                    )
                if not ok:
                    discovery_ok = False
                    break
                if len(discovered) > max_channels:
                    issues.add(BoundedReadIssueCode.CHANNEL_LIMIT, source.token)
                    discovery_ok = False
                    break
            if not discovery_ok:
                return BoundedReadingQueryResult(
                    rows=(),
                    complete=False,
                    truncated=False,
                    issues=tuple(issues.items),
                    issue_overflow=issues.overflow,
                    discovered_channels=tuple(sorted(discovered)[:max_channels]),
                    rows_examined=0,
                    rows_dropped_by_caps=0,
                    retained_encoded_bytes=0,
                )
            selected = tuple(sorted(discovered))
        discovered_channels = tuple(selected)
        collector = _BoundedReadingCollector(
            max_points_per_channel=max_points_per_channel,
            max_total_points=max_total_points,
            max_retained_bytes=max_retained_bytes,
        )
        complete = True
        for source in sources:
            if time.monotonic() >= deadline_monotonic:
                issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                complete = False
                break
            if source.kind == "sqlite":
                ok = self._read_sqlite_bounded(
                    source,
                    start_us=start_us,
                    end_us=end_us,
                    channels=selected,
                    deadline_monotonic=deadline_monotonic,
                    batch_rows=batch_rows,
                    collector=collector,
                    issues=issues,
                )
            else:
                ok = self._read_parquet_bounded(
                    source,
                    start_us=start_us,
                    end_us=end_us,
                    channels=selected,
                    deadline_monotonic=deadline_monotonic,
                    batch_rows=batch_rows,
                    max_arrow_batch_bytes=max_arrow_batch_bytes,
                    collector=collector,
                    issues=issues,
                )
            complete = ok and complete
        return BoundedReadingQueryResult(
            rows=collector.finish(),
            complete=complete and not issues.items and issues.overflow == 0,
            truncated=collector.truncated,
            issues=tuple(issues.items),
            issue_overflow=issues.overflow,
            discovered_channels=discovered_channels,
            rows_examined=collector.rows_examined,
            rows_dropped_by_caps=collector.rows_dropped_by_caps,
            retained_encoded_bytes=collector.retained_encoded_bytes,
        )

    @staticmethod
    def _validate_bounded_query(
        *,
        start: datetime,
        end: datetime,
        channels: Sequence[str] | None,
        max_channels: int,
        max_points_per_channel: int,
        max_total_points: int,
        max_retained_bytes: int,
        deadline_monotonic: float,
        batch_rows: int,
        max_arrow_batch_bytes: int,
    ) -> tuple[datetime, datetime, tuple[str, ...] | None]:
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise TypeError("start and end must be datetime")
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("end must be timezone-aware")
        start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
        if not start_utc < end_utc:
            raise ValueError("start must be before end")
        if end_utc - start_utc > timedelta(hours=168):
            raise ValueError("bounded query interval exceeds 168 hours")

        def exact_int(name: str, value: object, minimum: int, maximum: int) -> int:
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} outside {minimum}..{maximum}")
            return value

        exact_int("max_channels", max_channels, 1, 64)
        exact_int("max_points_per_channel", max_points_per_channel, 2, 100_000)
        exact_int("max_total_points", max_total_points, 2, 500_000)
        if max_total_points < max_points_per_channel:
            raise ValueError("max_total_points must cover one channel cap")
        exact_int("max_retained_bytes", max_retained_bytes, 65_536, 33_554_432)
        exact_int("batch_rows", batch_rows, 64, 8_192)
        exact_int("max_arrow_batch_bytes", max_arrow_batch_bytes, 65_536, 33_554_432)
        if isinstance(deadline_monotonic, bool) or not isinstance(deadline_monotonic, (int, float)):
            raise ValueError("deadline_monotonic must be finite")
        deadline = float(deadline_monotonic)
        if not math.isfinite(deadline) or deadline <= time.monotonic():
            raise ValueError("deadline_monotonic must be in the future")
        if channels is None:
            return start_utc, end_utc, None
        if isinstance(channels, (str, bytes)) or not isinstance(channels, Sequence):
            raise TypeError("channels must be a sequence of strings")
        if not 1 <= len(channels) <= max_channels:
            raise ValueError("channels count outside configured cap")
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in channels:
            channel = _bounded_text(raw, minimum=1, maximum=256)
            if channel in seen:
                raise ValueError("channels must be unique")
            seen.add(channel)
            normalized.append(channel)
        return start_utc, end_utc, tuple(normalized)

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("source is not a regular file")
        if getattr(info, "st_nlink", 1) != 1:
            raise OSError("source has multiple links")
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_nlink)

    @classmethod
    def _contained_regular(cls, root: Path, relative: str) -> Path:
        if not relative or "\\" in relative or "\x00" in relative:
            raise OSError("invalid relative path")
        if any(part in {"", ".", ".."} for part in relative.split("/")):
            raise OSError("invalid relative path")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise OSError("invalid relative path")
        if len(pure.parts[0]) >= 2 and pure.parts[0][1] == ":":
            raise OSError("drive path is forbidden")
        resolved_root = root.resolve(strict=True)
        current = resolved_root
        for part in pure.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise OSError("symlink source component")
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            raise OSError("source escaped root")
        cls._identity(resolved)
        return resolved

    @staticmethod
    def _read_bounded_index(index_path: Path) -> object:
        maximum = 8 * 1024 * 1024
        before = index_path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or getattr(before, "st_nlink", 1) != 1:
            raise OSError("invalid index authority")
        if before.st_size > maximum:
            raise _IndexOversizeError("index exceeds bound")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(index_path, flags)
        try:
            opened = os.fstat(descriptor)
            before_identity = (
                before.st_dev,
                before.st_ino,
                stat.S_IFMT(before.st_mode),
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                _identity_change_time_ns(before),
            )
            opened_identity = (
                opened.st_dev,
                opened.st_ino,
                stat.S_IFMT(opened.st_mode),
                opened.st_nlink,
                opened.st_size,
                opened.st_mtime_ns,
                _identity_change_time_ns(opened),
            )
            if opened_identity != before_identity:
                raise OSError("index identity changed before read")
            payload = bytearray()
            while len(payload) <= maximum:
                chunk = os.read(descriptor, min(65_536, maximum + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if len(payload) > maximum or after.st_size > maximum:
            raise _IndexOversizeError("index grew beyond bound")
        after_path = index_path.lstat()
        after_identity = (
            after.st_dev,
            after.st_ino,
            stat.S_IFMT(after.st_mode),
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            _identity_change_time_ns(after),
        )
        after_path_identity = (
            after_path.st_dev,
            after_path.st_ino,
            stat.S_IFMT(after_path.st_mode),
            after_path.st_nlink,
            after_path.st_size,
            after_path.st_mtime_ns,
            _identity_change_time_ns(after_path),
        )
        if (
            after_identity != opened_identity
            or after_path_identity != opened_identity
            or after.st_ctime_ns != opened.st_ctime_ns
            or len(payload) != opened.st_size
        ):
            raise OSError("index changed while reading")
        return json.loads(bytes(payload).decode("utf-8", errors="strict"))

    def _bounded_sources(
        self,
        first_day: date,
        last_day: date,
        deadline_monotonic: float,
        issues: _IssueLedger,
    ) -> tuple[_BoundedSource, ...] | None:
        indexed: dict[str, dict[str, object]] = {}
        index_path = self._archive_dir / "index.json"
        index_was_present = index_path.exists() or index_path.is_symlink()
        index_document: object | None = None
        if index_was_present:
            try:
                if time.monotonic() >= deadline_monotonic:
                    issues.add(BoundedReadIssueCode.DEADLINE, "index")
                    return None
                doc = self._read_bounded_index(index_path)
                index_document = doc
                if not isinstance(doc, dict) or set(doc) != {"files"}:
                    raise ValueError("invalid index schema")
                entries = doc["files"]
                if not isinstance(entries, list) or len(entries) > 100_000:
                    raise ValueError("invalid index entries")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("invalid index entry")
                    name = entry.get("original_name")
                    archive_path = entry.get("archive_path")
                    if not isinstance(name, str) or not isinstance(archive_path, str):
                        raise ValueError("invalid index entry fields")
                    day_text = _day_from_db_name(name)
                    if day_text is None or name != f"data_{day_text}.db":
                        continue
                    day = date.fromisoformat(day_text)
                    if not first_day <= day <= last_day:
                        continue
                    if name in indexed:
                        raise ValueError("duplicate day authority")
                    indexed[name] = entry
            except _IndexOversizeError:
                issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_OVERSIZE, "index")
                return None
            except Exception:
                issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_INVALID, "index")
                return None

        planned: list[_BoundedSource] = []
        current = last_day
        while current >= first_day:
            if time.monotonic() >= deadline_monotonic:
                issues.add(BoundedReadIssueCode.DEADLINE, current.isoformat())
                return None
            name = f"data_{current.isoformat()}.db"
            index_entry = indexed.get(name)
            if index_entry is not None:
                archive_rel = index_entry["archive_path"]
                assert isinstance(archive_rel, str)
                token = f"{current.isoformat()}:parquet:0"
                try:
                    archive = self._contained_regular(self._archive_dir, archive_rel)
                except FileNotFoundError:
                    issues.add(BoundedReadIssueCode.SOURCE_MISSING, token)
                except OSError:
                    issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_INVALID, token)
                else:
                    planned.append(_BoundedSource(current, "parquet", archive, token, index_entry))
            hot = self._data_dir / name
            if hot.exists() or hot.is_symlink():
                token = f"{current.isoformat()}:sqlite"
                try:
                    relative = hot.relative_to(self._data_dir).as_posix()
                    validated = self._contained_regular(self._data_dir, relative)
                except (OSError, ValueError):
                    issues.add(BoundedReadIssueCode.SQLITE_READ, token)
                else:
                    planned.append(_BoundedSource(current, "sqlite", validated, token))
            current -= timedelta(days=1)
        if time.monotonic() >= deadline_monotonic:
            issues.add(BoundedReadIssueCode.DEADLINE, "index:post-plan")
            return None
        index_is_present = index_path.exists() or index_path.is_symlink()
        if index_is_present != index_was_present:
            issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_INVALID, "index:changed")
            return None
        if index_is_present:
            try:
                post_plan_document = self._read_bounded_index(index_path)
            except _IndexOversizeError:
                issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_OVERSIZE, "index")
                return None
            except Exception:
                issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_INVALID, "index")
                return None
            if post_plan_document != index_document:
                issues.add(BoundedReadIssueCode.ARCHIVE_INDEX_INVALID, "index:changed")
                return None
        return tuple(planned)

    @staticmethod
    def _sqlite_issue_for(exc: BaseException) -> BoundedReadIssueCode:
        code = getattr(exc, "sqlite_errorcode", None)
        primary_code = code & 0xFF if isinstance(code, int) else code
        if primary_code == getattr(sqlite3, "SQLITE_TOOBIG", -1) or isinstance(exc, getattr(sqlite3, "DataError", ())):
            return BoundedReadIssueCode.SQLITE_VALUE_OVERSIZE
        if primary_code in {
            getattr(sqlite3, "SQLITE_BUSY", -2),
            getattr(sqlite3, "SQLITE_LOCKED", -3),
        }:
            return BoundedReadIssueCode.SQLITE_BUSY
        if primary_code == getattr(sqlite3, "SQLITE_INTERRUPT", -4):
            return BoundedReadIssueCode.SQLITE_INTERRUPTED
        return BoundedReadIssueCode.SQLITE_READ

    @staticmethod
    def _descriptor_adapter_issue(exc: DescriptorArchiveError) -> BoundedReadIssueCode:
        message = str(exc)
        if "no descriptor catalog" in message:
            return BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING
        if "missing descriptor" in message or "match referenced" in message:
            return BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING
        if "bound" in message or "exceeds" in message:
            return BoundedReadIssueCode.DESCRIPTOR_OVERSIZED
        return BoundedReadIssueCode.DESCRIPTOR_ENVELOPE_CORRUPT

    def _open_bounded_sqlite(
        self,
        source: _BoundedSource,
        *,
        deadline_monotonic: float,
    ) -> tuple[object, tuple[int, int, int, int], list[bool]]:
        before = self._identity(source.path)
        uri = f"file:{quote(str(source.path), safe='/')}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=0.25,
            isolation_level=None,
        )
        try:
            if not hasattr(conn, "setlimit") or not hasattr(sqlite3, "SQLITE_LIMIT_LENGTH"):
                raise RuntimeError("SQLite allocation limits unavailable")
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_048_576)
            conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65_536)
            expired = [False]

            def interrupt_on_deadline() -> int:
                if time.monotonic() >= deadline_monotonic:
                    expired[0] = True
                    return 1
                return 0

            conn.set_progress_handler(interrupt_on_deadline, 2_000)
            conn.execute("PRAGMA query_only=ON").close()
            conn.execute("PRAGMA busy_timeout=250").close()
            if self._identity(source.path) != before:
                raise OSError("SQLite source identity changed")
            return conn, before, expired
        except Exception:
            conn.close()
            raise

    def _close_bounded_sqlite(
        self,
        conn: object,
        source: _BoundedSource,
        identity: tuple[int, int, int, int],
    ) -> bool:
        same = False
        try:
            same = self._identity(source.path) == identity
        except OSError:
            pass
        try:
            conn.close()
        except Exception:
            same = False
        return same

    def _discover_sqlite_channels(
        self,
        source: _BoundedSource,
        *,
        start_us: int,
        end_us: int,
        max_channels: int,
        channels: set[str],
        deadline_monotonic: float,
        batch_rows: int,
        issues: _IssueLedger,
    ) -> bool:
        conn = None
        identity = None
        expired = [False]
        ok = True
        try:
            conn, identity, expired = self._open_bounded_sqlite(source, deadline_monotonic=deadline_monotonic)
            legacy = conn.execute("SELECT 1 FROM readings WHERE typeof(timestamp) = 'text' LIMIT 1")
            try:
                if next(iter(legacy), None) is not None:
                    issues.add(BoundedReadIssueCode.LEGACY_TIMESTAMP_UNSUPPORTED, source.token)
                    return False
            finally:
                legacy.close()
            last_id: int | None = None
            while True:
                if time.monotonic() >= deadline_monotonic:
                    issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                    return False
                sql = (
                    "SELECT id, channel FROM readings NOT INDEXED "
                    "WHERE typeof(timestamp) IN ('real','integer') "
                    "AND timestamp >= ? AND timestamp < ?"
                )
                params: list[object] = [
                    start_us / 1_000_000.0,
                    end_us / 1_000_000.0,
                ]
                if last_id is not None:
                    sql += " AND id > ?"
                    params.append(last_id)
                sql += " ORDER BY id LIMIT ?"
                params.append(batch_rows)
                cursor = conn.execute(sql, params)
                count = 0
                try:
                    for row_id, raw_channel in cursor:
                        if type(row_id) is not int or (last_id is not None and row_id <= last_id):
                            raise ValueError("invalid discovery keyset id")
                        last_id = row_id
                        count += 1
                        channels.add(_bounded_text(raw_channel, minimum=1, maximum=256))
                        if len(channels) > max_channels:
                            issues.add(BoundedReadIssueCode.CHANNEL_LIMIT, source.token)
                            return False
                finally:
                    cursor.close()
                if count < batch_rows:
                    break
        except Exception as exc:
            if expired[0]:
                issues.add(BoundedReadIssueCode.SQLITE_INTERRUPTED, source.token)
                issues.add(BoundedReadIssueCode.DEADLINE, source.token)
            elif isinstance(exc, (ValueError, UnicodeError)):
                issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
            else:
                issues.add(self._sqlite_issue_for(exc), source.token)
            ok = False
        finally:
            if conn is not None and identity is not None:
                if not self._close_bounded_sqlite(conn, source, identity):
                    issues.add(BoundedReadIssueCode.SQLITE_READ, source.token)
                    ok = False
        return ok

    def _read_sqlite_bounded(
        self,
        source: _BoundedSource,
        *,
        start_us: int,
        end_us: int,
        channels: Sequence[str],
        deadline_monotonic: float,
        batch_rows: int,
        collector: _BoundedReadingCollector,
        issues: _IssueLedger,
    ) -> bool:
        conn = None
        identity = None
        expired = [False]
        ok = True
        try:
            conn, identity, expired = self._open_bounded_sqlite(source, deadline_monotonic=deadline_monotonic)
            placeholders = ",".join("?" for _ in channels)
            reading_columns = {str(row[1]) for row in conn.execute("PRAGMA main.table_info(readings)")}
            has_descriptor_hash = "descriptor_hash" in reading_columns
            descriptor_map: dict[str, ResolvedStorageDescriptor] = {}
            if has_descriptor_hash:
                if (
                    conn.execute(
                        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='channel_descriptors'"
                    ).fetchone()
                    is None
                ):
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING)
                try:
                    verify_descriptor_storage(conn)
                except ChannelDescriptorStorageError as exc:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH) from exc
                descriptor_rows = conn.execute(
                    "SELECT DISTINCT descriptor_hash FROM readings WHERE descriptor_hash IS NOT NULL LIMIT ?",
                    (MAX_ARCHIVE_DESCRIPTORS + 1,),
                ).fetchall()
                if len(descriptor_rows) > MAX_ARCHIVE_DESCRIPTORS:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                referenced = {row[0] for row in descriptor_rows}
                if any(type(value) is not str for value in referenced):
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_SCHEMA_MISMATCH)
                if referenced:
                    try:
                        raw_descriptors = load_referenced_descriptors(conn, referenced)
                        descriptor_map = resolve_archived_descriptors(raw_descriptors, referenced)
                    except DescriptorArchiveError as exc:
                        raise _DescriptorReadError(self._descriptor_adapter_issue(exc)) from exc
            legacy_sql = "SELECT 1 FROM readings WHERE typeof(timestamp) = 'text'"
            legacy_params: tuple[object, ...] = ()
            if channels:
                legacy_sql += f" AND channel IN ({placeholders})"
                legacy_params = tuple(channels)
            legacy_sql += " LIMIT 1"
            legacy = conn.execute(legacy_sql, legacy_params)
            try:
                if next(iter(legacy), None) is not None:
                    issues.add(BoundedReadIssueCode.LEGACY_TIMESTAMP_UNSUPPORTED, source.token)
                    ok = False
            finally:
                legacy.close()

            for channel in channels:
                last: tuple[float, int] | None = None
                while True:
                    if time.monotonic() >= deadline_monotonic:
                        issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                        return False
                    sql = (
                        "SELECT id, timestamp, instrument_id, channel, value, unit, status, "
                        + ("descriptor_hash " if has_descriptor_hash else "NULL AS descriptor_hash ")
                        + "FROM readings WHERE typeof(timestamp) IN ('real','integer') "
                        "AND timestamp >= ? AND timestamp < ? AND channel = ?"
                    )
                    params: list[object] = [
                        start_us / 1_000_000.0,
                        end_us / 1_000_000.0,
                        channel,
                    ]
                    if last is not None:
                        sql += " AND (timestamp < ? OR (timestamp = ? AND id < ?))"
                        params.extend((last[0], last[0], last[1]))
                    sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
                    params.append(batch_rows)
                    cursor = conn.execute(sql, params)
                    count = 0
                    try:
                        for raw in cursor:
                            count += 1
                            collector.note_examined()
                            (
                                row_id,
                                timestamp,
                                instrument,
                                raw_channel,
                                value,
                                unit,
                                status_value,
                                descriptor_hash,
                            ) = raw
                            last = (float(timestamp), int(row_id))
                            try:
                                timestamp_us = _sqlite_epoch_microseconds(timestamp)
                                if not start_us <= timestamp_us < end_us:
                                    raise ValueError("timestamp outside normalized interval")
                                instrument_text = _bounded_text(instrument, minimum=1, maximum=256)
                                channel_text = _bounded_text(raw_channel, minimum=1, maximum=256)
                                unit_text = _bounded_text(unit, minimum=0, maximum=64)
                                status_text = _bounded_text(status_value, minimum=0, maximum=64)
                                decoded = _bounded_value(value, status_text)
                                if descriptor_hash is None:
                                    descriptor = resolve_legacy_descriptor(
                                        instrument_text,
                                        channel_text,
                                        unit_text,
                                    )
                                else:
                                    descriptor = descriptor_map.get(descriptor_hash)
                                    if descriptor is None:
                                        raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING)
                                    if (
                                        descriptor.instrument_id != instrument_text
                                        or descriptor.channel_id != channel_text
                                        or descriptor.unit != unit_text
                                    ):
                                        raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_READING_MISMATCH)
                            except _DescriptorReadError as exc:
                                issues.add(exc.code, source.token)
                                ok = False
                                continue
                            except (ValueError, TypeError, OSError, OverflowError):
                                issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
                                ok = False
                                continue
                            collector.offer(
                                timestamp_us=timestamp_us,
                                instrument_id=instrument_text,
                                channel=channel_text,
                                value=decoded,
                                unit=unit_text,
                                status=status_text,
                                authority=(1, int(row_id)),
                                descriptor=descriptor,
                            )
                    finally:
                        cursor.close()
                    if count < batch_rows:
                        break
        except _DescriptorReadError as exc:
            issues.add(exc.code, source.token)
            ok = False
        except Exception as exc:
            if expired[0]:
                issues.add(BoundedReadIssueCode.SQLITE_INTERRUPTED, source.token)
                issues.add(BoundedReadIssueCode.DEADLINE, source.token)
            else:
                issues.add(self._sqlite_issue_for(exc), source.token)
            ok = False
        finally:
            if conn is not None and identity is not None:
                if not self._close_bounded_sqlite(conn, source, identity):
                    issues.add(BoundedReadIssueCode.SQLITE_READ, source.token)
                    ok = False
        return ok

    def _prepare_bounded_parquet(
        self,
        source: _BoundedSource,
        *,
        start_us: int,
        end_us: int,
        deadline_monotonic: float,
    ) -> tuple[
        BinaryIO,
        object,
        object,
        object,
        list[int],
        list[int],
        tuple[int, int, int, int],
        bool,
    ]:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        if time.monotonic() >= deadline_monotonic:
            raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
        path_identity = self._identity(source.path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source.path, flags)
        handle: BinaryIO | None = None
        try:
            info = os.fstat(descriptor)
            handle_identity = (
                info.st_dev,
                info.st_ino,
                stat.S_IFMT(info.st_mode),
                info.st_nlink,
            )
            if handle_identity != path_identity or not stat.S_ISREG(info.st_mode) or getattr(info, "st_nlink", 1) != 1:
                raise OSError("Parquet source identity mismatch")
            if info.st_size < 12:
                raise _ParquetMetadataError("Parquet file too small")
            handle = os.fdopen(descriptor, "rb", closefd=True)
            descriptor = -1
            handle.seek(-8, os.SEEK_END)
            trailer = handle.read(8)
            if len(trailer) != 8 or trailer[4:] != b"PAR1":
                raise _ParquetMetadataError("invalid Parquet trailer")
            footer_length = struct.unpack("<I", trailer[:4])[0]
            if footer_length > 8 * 1024 * 1024 or footer_length + 8 > info.st_size:
                raise _ParquetMetadataError("invalid Parquet footer length")
            handle.seek(0)
            parquet = pq.ParquetFile(
                handle,
                pre_buffer=False,
                thrift_string_size_limit=1_048_576,
                thrift_container_size_limit=1_000_000,
            )
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            expected = pa.schema(
                [
                    ("timestamp", pa.timestamp("us", tz="UTC")),
                    ("instrument_id", pa.string()),
                    ("channel", pa.string()),
                    ("value", pa.float64()),
                    ("unit", pa.string()),
                    ("status", pa.string()),
                ]
            )
            schema = parquet.schema_arrow
            allowed_names = (expected.names, [*expected.names, "descriptor_hash"])
            if schema.names not in allowed_names or any(
                schema.field(name).type != expected.field(name).type for name in expected.names
            ):
                raise _ParquetSchemaError("unexpected Parquet schema")
            if "descriptor_hash" in schema.names and schema.field("descriptor_hash").type != pa.string():
                raise _ParquetSchemaError("unexpected descriptor_hash type")
            metadata = parquet.metadata
            if metadata.num_row_groups > 1_024:
                raise _ParquetMetadataError("too many Parquet row groups")
            starts: list[int] = []
            cursor = 0
            ranges: list[tuple[int | None, int | None]] = []
            eligible: list[int] = []
            metadata_partial = False
            timestamp_column = schema.names.index("timestamp")
            for group_index in range(metadata.num_row_groups):
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                starts.append(cursor)
                group = metadata.row_group(group_index)
                cursor += group.num_rows
                minimum: int | None = None
                maximum: int | None = None
                stats = group.column(timestamp_column).statistics
                if stats is not None and stats.has_min_max:
                    try:
                        minimum = _epoch_microseconds(stats.min)
                        maximum = _epoch_microseconds(stats.max)
                    except (AttributeError, TypeError, ValueError, OSError, OverflowError):
                        minimum = maximum = None
                        metadata_partial = True
                    if minimum is not None and maximum is not None and minimum > maximum:
                        minimum = maximum = None
                        metadata_partial = True
                ranges.append((minimum, maximum))
                if minimum is not None and maximum is not None:
                    if maximum < start_us or minimum >= end_us:
                        continue
                eligible.append(group_index)
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            chronological = all(
                ranges[index][0] is not None
                and ranges[index][1] is not None
                and ranges[index + 1][0] is not None
                and ranges[index][1] <= ranges[index + 1][0]
                for index in range(max(0, len(ranges) - 1))
            )
            if chronological:
                eligible.reverse()
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            return (
                handle,
                parquet,
                pa,
                pc,
                eligible,
                starts,
                path_identity,
                metadata_partial,
            )
        except Exception:
            if handle is not None:
                handle.close()
            elif descriptor >= 0:
                os.close(descriptor)
            raise

    @staticmethod
    def _hash_open_file(descriptor: int, *, deadline_monotonic: float) -> str:
        digest = hashlib.md5()
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            block = os.read(descriptor, 65_536)
            if not block:
                break
            digest.update(block)
        if time.monotonic() >= deadline_monotonic:
            raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
        return digest.hexdigest()

    @staticmethod
    def _read_descriptor_row_group(parquet: object, group_index: int) -> object:
        return parquet.read_row_group(group_index, use_threads=False)

    @staticmethod
    def _next_descriptor_reference_batch(iterator: object) -> object:
        return next(iterator)

    @staticmethod
    def _descriptor_reference_value(scalar: object) -> object:
        return scalar.as_py()

    @staticmethod
    def _open_descriptor_file(path: Path, flags: int) -> int:
        return os.open(path, flags)

    @staticmethod
    def _descriptor_metadata_group(metadata: object, group_index: int) -> object:
        return metadata.row_group(group_index)

    @staticmethod
    def _next_bounded_parquet_batch(iterator: object) -> object:
        return next(iterator)

    @staticmethod
    def _offer_bounded_collector(
        collector: _BoundedReadingCollector,
        **values: object,
    ) -> None:
        collector.offer(**values)

    def _resolve_cold_descriptors(
        self,
        source: _BoundedSource,
        parquet: object,
        *,
        batch_rows: int,
        max_arrow_batch_bytes: int,
        deadline_monotonic: float,
    ) -> dict[str, ResolvedStorageDescriptor]:
        """Verify an indexed sidecar against every non-null reading reference."""
        schema = parquet.schema_arrow
        has_hash = "descriptor_hash" in schema.names
        fields = source.index_entry or {}
        sidecar_keys = (
            "channel_descriptors_path",
            "channel_descriptors_rows",
            "channel_descriptors_checksum",
            "channel_descriptors_size_bytes",
        )
        sidecar_values = tuple(fields.get(key) for key in sidecar_keys)
        if not has_hash:
            if any(value is not None for value in sidecar_values):
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH)
            return {}

        referenced: set[str] = set()
        rows_scanned = 0
        try:
            iterator = iter(
                parquet.iter_batches(
                    batch_size=batch_rows,
                    columns=["descriptor_hash"],
                    use_threads=False,
                )
            )
            while True:
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                try:
                    batch = self._next_descriptor_reference_batch(iterator)
                except StopIteration:
                    if time.monotonic() >= deadline_monotonic:
                        raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                    break
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                if batch.num_rows > batch_rows:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                rows_scanned += batch.num_rows
                if rows_scanned > _MAX_DESCRIPTOR_REFERENCE_ROWS:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                if batch.nbytes > max_arrow_batch_bytes:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                for scalar in batch["descriptor_hash"]:
                    if time.monotonic() >= deadline_monotonic:
                        raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                    value = self._descriptor_reference_value(scalar)
                    if time.monotonic() >= deadline_monotonic:
                        raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                    if value is None:
                        continue
                    if type(value) is not str:
                        raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_SCHEMA_MISMATCH)
                    referenced.add(value)
                    if len(referenced) > MAX_ARCHIVE_DESCRIPTORS:
                        raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
        except _DescriptorReadError:
            raise
        except Exception as exc:
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_SCHEMA_MISMATCH) from exc
        if not referenced:
            if any(value is not None for value in sidecar_values):
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH)
            return {}
        if any(value is None for value in sidecar_values):
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING)

        sidecar_rel, indexed_rows, indexed_checksum, indexed_size = sidecar_values
        archive_rel = fields.get("archive_path")
        expected_rel = (
            archive_rel.removesuffix(".parquet") + ".channel_descriptors.parquet" if type(archive_rel) is str else None
        )
        if (
            type(sidecar_rel) is not str
            or sidecar_rel != expected_rel
            or type(indexed_rows) is not int
            or not 0 < indexed_rows <= MAX_ARCHIVE_DESCRIPTORS
            or type(indexed_checksum) is not str
            or type(indexed_size) is not int
            or indexed_size <= 0
            or indexed_size > MAX_ARCHIVE_DESCRIPTOR_BYTES + 8 * 1024 * 1024
        ):
            code = (
                BoundedReadIssueCode.DESCRIPTOR_OVERSIZED
                if type(indexed_size) is int and indexed_size > MAX_ARCHIVE_DESCRIPTOR_BYTES + 8 * 1024 * 1024
                else BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH
            )
            raise _DescriptorReadError(code)
        try:
            sidecar = self._contained_regular(self._archive_dir, sidecar_rel)
        except FileNotFoundError as exc:
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_CATALOG_MISSING) from exc
        except OSError as exc:
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH) from exc
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        handle: BinaryIO | None = None
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            descriptor = self._open_descriptor_file(sidecar, flags)
            opened = os.fstat(descriptor)
            opened_identity = (
                opened.st_dev,
                opened.st_ino,
                stat.S_IFMT(opened.st_mode),
                opened.st_nlink,
            )
            if (
                opened_identity != self._identity(sidecar)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_size != indexed_size
                or self._hash_open_file(descriptor, deadline_monotonic=deadline_monotonic) != indexed_checksum
            ):
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH)
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            handle = os.fdopen(os.dup(descriptor), "rb", closefd=True)
            descriptor_parquet = pq.ParquetFile(
                handle,
                pre_buffer=False,
                thrift_string_size_limit=1_048_576,
                thrift_container_size_limit=100_000,
            )
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            expected_schema = pa.schema(
                [
                    ("descriptor_hash", pa.string()),
                    ("channel_id", pa.string()),
                    ("instrument_id", pa.string()),
                    ("source_key", pa.string()),
                    ("descriptor_revision", pa.int32()),
                    ("envelope_json", pa.binary()),
                ]
            )
            if descriptor_parquet.schema_arrow != expected_schema:
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_SCHEMA_MISMATCH)
            if descriptor_parquet.metadata.num_rows != indexed_rows:
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH)
            metadata = descriptor_parquet.metadata
            if metadata.num_row_groups > 1_024:
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
            arrow_cap = MAX_ARCHIVE_DESCRIPTOR_BYTES + 2 * 1024 * 1024
            total_uncompressed = 0
            total_compressed = 0
            for group_index in range(metadata.num_row_groups):
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                group = self._descriptor_metadata_group(metadata, group_index)
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                total_uncompressed += group.total_byte_size
                for column_index in range(group.num_columns):
                    if time.monotonic() >= deadline_monotonic:
                        raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                    column = group.column(column_index)
                    if time.monotonic() >= deadline_monotonic:
                        raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                    total_compressed += column.total_compressed_size
                if total_uncompressed > arrow_cap or total_compressed > indexed_size:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
            if time.monotonic() >= deadline_monotonic:
                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            rows: list[ArchivedDescriptor] = []
            decoded_bytes = 0
            for group_index in range(metadata.num_row_groups):
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                table = self._read_descriptor_row_group(descriptor_parquet, group_index)
                decoded_bytes += table.nbytes
                if decoded_bytes > arrow_cap or len(rows) + table.num_rows > MAX_ARCHIVE_DESCRIPTORS:
                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_OVERSIZED)
                rows.extend(
                    ArchivedDescriptor(
                        descriptor_hash=row["descriptor_hash"],
                        channel_id=row["channel_id"],
                        instrument_id=row["instrument_id"],
                        source_key=row["source_key"],
                        descriptor_revision=row["descriptor_revision"],
                        envelope_json=row["envelope_json"],
                    )
                    for row in table.to_pylist()
                )
                if time.monotonic() >= deadline_monotonic:
                    raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
            resolved = resolve_archived_descriptors(rows, referenced)
            after = os.fstat(descriptor)
            if (
                (
                    after.st_dev,
                    after.st_ino,
                    stat.S_IFMT(after.st_mode),
                    after.st_nlink,
                )
                != opened_identity
                or after.st_size != indexed_size
                or self._hash_open_file(descriptor, deadline_monotonic=deadline_monotonic) != indexed_checksum
                or self._identity(sidecar) != opened_identity
            ):
                raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH)
            return resolved
        except _DescriptorReadError:
            raise
        except DescriptorArchiveError as exc:
            message = str(exc)
            if "missing" in message or "match referenced" in message:
                code = BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING
            elif "bound" in message or "exceeds" in message:
                code = BoundedReadIssueCode.DESCRIPTOR_OVERSIZED
            else:
                code = BoundedReadIssueCode.DESCRIPTOR_ENVELOPE_CORRUPT
            raise _DescriptorReadError(code) from exc
        except OSError as exc:
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH) from exc
        except Exception as exc:
            raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_ENVELOPE_CORRUPT) from exc
        finally:
            if handle is not None:
                handle.close()
            if descriptor >= 0:
                os.close(descriptor)

    def _discover_parquet_channels(
        self,
        source: _BoundedSource,
        *,
        start_us: int,
        end_us: int,
        max_channels: int,
        channels: set[str],
        deadline_monotonic: float,
        batch_rows: int,
        max_arrow_batch_bytes: int,
        issues: _IssueLedger,
    ) -> bool:
        handle = None
        identity = None
        ok = True
        try:
            (
                handle,
                parquet,
                pa,
                pc,
                groups,
                _starts,
                identity,
                metadata_partial,
            ) = self._prepare_bounded_parquet(
                source,
                start_us=start_us,
                end_us=end_us,
                deadline_monotonic=deadline_monotonic,
            )
            if metadata_partial:
                issues.add(BoundedReadIssueCode.PARQUET_METADATA, source.token)
                ok = False
            self._resolve_cold_descriptors(
                source,
                parquet,
                batch_rows=batch_rows,
                max_arrow_batch_bytes=max_arrow_batch_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            start_scalar = pa.scalar(
                datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=start_us),
                type=pa.timestamp("us", tz="UTC"),
            )
            end_scalar = pa.scalar(
                datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=end_us),
                type=pa.timestamp("us", tz="UTC"),
            )
            for group in groups:
                iterator = iter(
                    parquet.iter_batches(
                        batch_size=batch_rows,
                        row_groups=[group],
                        columns=["timestamp", "channel"],
                        use_threads=False,
                    )
                )
                while True:
                    if time.monotonic() >= deadline_monotonic:
                        issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                        return False
                    try:
                        batch = self._next_bounded_parquet_batch(iterator)
                    except StopIteration:
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        break
                    if time.monotonic() >= deadline_monotonic:
                        issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                        return False
                    if batch.num_rows > batch_rows:
                        issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                        return False
                    if batch.nbytes > max_arrow_batch_bytes:
                        issues.add(BoundedReadIssueCode.PARQUET_BATCH_OVERSIZE, source.token)
                        return False
                    if bool(pc.any(pc.is_null(batch["timestamp"])).as_py()) or bool(
                        pc.any(pc.is_null(batch["channel"])).as_py()
                    ):
                        issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
                        ok = False
                    mask = pc.and_(
                        pc.greater_equal(batch["timestamp"], start_scalar),
                        pc.less(batch["timestamp"], end_scalar),
                    )
                    mask = pc.fill_null(mask, False)
                    filtered = batch.filter(mask)
                    for index in range(filtered.num_rows):
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        channel = _bounded_text(filtered["channel"][index].as_py(), minimum=1, maximum=256)
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        channels.add(channel)
                        if len(channels) > max_channels:
                            issues.add(BoundedReadIssueCode.CHANNEL_LIMIT, source.token)
                            return False
        except _DescriptorReadError as exc:
            issues.add(exc.code, source.token)
            ok = False
        except _ParquetSchemaError:
            issues.add(BoundedReadIssueCode.PARQUET_SCHEMA, source.token)
            ok = False
        except (_ParquetMetadataError, struct.error):
            issues.add(BoundedReadIssueCode.PARQUET_METADATA, source.token)
            ok = False
        except (ValueError, UnicodeError):
            issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
            ok = False
        except Exception:
            issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
            ok = False
        finally:
            if handle is not None:
                handle.close()
            if identity is not None:
                try:
                    if self._identity(source.path) != identity:
                        issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                        ok = False
                except OSError:
                    issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                    ok = False
        return ok

    def _read_parquet_bounded(
        self,
        source: _BoundedSource,
        *,
        start_us: int,
        end_us: int,
        channels: Sequence[str],
        deadline_monotonic: float,
        batch_rows: int,
        max_arrow_batch_bytes: int,
        collector: _BoundedReadingCollector,
        issues: _IssueLedger,
    ) -> bool:
        handle = None
        identity = None
        ok = True
        try:
            (
                handle,
                parquet,
                pa,
                pc,
                groups,
                starts,
                identity,
                metadata_partial,
            ) = self._prepare_bounded_parquet(
                source,
                start_us=start_us,
                end_us=end_us,
                deadline_monotonic=deadline_monotonic,
            )
            if metadata_partial:
                issues.add(BoundedReadIssueCode.PARQUET_METADATA, source.token)
                ok = False
            descriptor_map = self._resolve_cold_descriptors(
                source,
                parquet,
                batch_rows=batch_rows,
                max_arrow_batch_bytes=max_arrow_batch_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            has_descriptor_hash = "descriptor_hash" in parquet.schema_arrow.names
            start_scalar = pa.scalar(
                datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=start_us),
                type=pa.timestamp("us", tz="UTC"),
            )
            end_scalar = pa.scalar(
                datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=end_us),
                type=pa.timestamp("us", tz="UTC"),
            )
            channel_array = pa.array(channels, type=pa.string())
            columns = [
                "timestamp",
                "instrument_id",
                "channel",
                "value",
                "unit",
                "status",
            ]
            if has_descriptor_hash:
                columns.append("descriptor_hash")
            for group in groups:
                batch_start = 0
                iterator = iter(
                    parquet.iter_batches(
                        batch_size=batch_rows,
                        row_groups=[group],
                        columns=columns,
                        use_threads=False,
                    )
                )
                while True:
                    if time.monotonic() >= deadline_monotonic:
                        issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                        return False
                    try:
                        batch = self._next_bounded_parquet_batch(iterator)
                    except StopIteration:
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        break
                    if time.monotonic() >= deadline_monotonic:
                        issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                        return False
                    if batch.num_rows > batch_rows:
                        issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                        return False
                    if batch.nbytes > max_arrow_batch_bytes:
                        issues.add(BoundedReadIssueCode.PARQUET_BATCH_OVERSIZE, source.token)
                        return False
                    if bool(pc.any(pc.is_null(batch["timestamp"])).as_py()) or bool(
                        pc.any(pc.is_null(batch["channel"])).as_py()
                    ):
                        issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
                        ok = False
                    ordinals = pa.array(
                        range(
                            starts[group] + batch_start,
                            starts[group] + batch_start + batch.num_rows,
                        ),
                        type=pa.int64(),
                    )
                    batch_start += batch.num_rows
                    mask = pc.and_(
                        pc.greater_equal(batch["timestamp"], start_scalar),
                        pc.less(batch["timestamp"], end_scalar),
                    )
                    mask = pc.and_(
                        mask,
                        pc.is_in(batch["channel"], value_set=channel_array),
                    )
                    mask = pc.fill_null(mask, False)
                    filtered = batch.filter(mask)
                    filtered_ordinals = ordinals.filter(mask)
                    for index in range(filtered.num_rows):
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        collector.note_examined()
                        try:
                            timestamp = filtered["timestamp"][index].as_py()
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            timestamp_us = _epoch_microseconds(timestamp)
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            if not start_us <= timestamp_us < end_us:
                                raise ValueError("timestamp outside normalized interval")
                            instrument = _bounded_text(
                                filtered["instrument_id"][index].as_py(),
                                minimum=1,
                                maximum=256,
                            )
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            channel = _bounded_text(
                                filtered["channel"][index].as_py(),
                                minimum=1,
                                maximum=256,
                            )
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            unit = _bounded_text(filtered["unit"][index].as_py(), minimum=0, maximum=64)
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            status_value = _bounded_text(filtered["status"][index].as_py(), minimum=0, maximum=64)
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            value = _bounded_value(filtered["value"][index].as_py(), status_value)
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            descriptor_hash = (
                                filtered["descriptor_hash"][index].as_py() if has_descriptor_hash else None
                            )
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            if descriptor_hash is None:
                                descriptor = resolve_legacy_descriptor(instrument, channel, unit)
                            else:
                                descriptor = descriptor_map.get(descriptor_hash)
                                if descriptor is None:
                                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING)
                                if (
                                    descriptor.instrument_id != instrument
                                    or descriptor.channel_id != channel
                                    or descriptor.unit != unit
                                ):
                                    raise _DescriptorReadError(BoundedReadIssueCode.DESCRIPTOR_READING_MISMATCH)
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            ordinal = filtered_ordinals[index].as_py()
                            if time.monotonic() >= deadline_monotonic:
                                raise _DescriptorReadError(BoundedReadIssueCode.DEADLINE)
                            if isinstance(ordinal, bool) or not isinstance(ordinal, int):
                                raise ValueError("invalid physical ordinal")
                        except _DescriptorReadError as exc:
                            issues.add(exc.code, source.token)
                            ok = False
                            if exc.code is BoundedReadIssueCode.DEADLINE:
                                return False
                            continue
                        except (ValueError, TypeError, OSError, OverflowError):
                            issues.add(BoundedReadIssueCode.INVALID_ROW, source.token)
                            ok = False
                            continue
                        # Cold rotation preserves SQLite ``ORDER BY timestamp,
                        # id`` physical order. The greatest physical ordinal is
                        # therefore the same last-writer authority as the
                        # greatest hot SQLite row id. Source rank 2 still makes
                        # an archived cut authoritative over a later reappeared
                        # hot copy on an overlap day.
                        authority = (2, ordinal)
                        if time.monotonic() >= deadline_monotonic:
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
                        self._offer_bounded_collector(
                            collector,
                            timestamp_us=timestamp_us,
                            instrument_id=instrument,
                            channel=channel,
                            value=value,
                            unit=unit,
                            status=status_value,
                            authority=authority,
                            descriptor=descriptor,
                        )
                        if time.monotonic() >= deadline_monotonic:
                            collector.discard_if_current(
                                timestamp_us=timestamp_us,
                                instrument_id=instrument,
                                channel=channel,
                                authority=authority,
                            )
                            issues.add(BoundedReadIssueCode.DEADLINE, source.token)
                            return False
        except _DescriptorReadError as exc:
            issues.add(exc.code, source.token)
            ok = False
        except _ParquetSchemaError:
            issues.add(BoundedReadIssueCode.PARQUET_SCHEMA, source.token)
            ok = False
        except (_ParquetMetadataError, struct.error):
            issues.add(BoundedReadIssueCode.PARQUET_METADATA, source.token)
            ok = False
        except Exception:
            issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
            ok = False
        finally:
            if handle is not None:
                handle.close()
            if identity is not None:
                try:
                    if self._identity(source.path) != identity:
                        issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                        ok = False
                except OSError:
                    issues.add(BoundedReadIssueCode.PARQUET_READ, source.token)
                    ok = False
        return ok

    def query(
        self,
        channels: list[str] | None,
        from_ts: datetime,
        to_ts: datetime,
    ) -> dict[str, list[tuple[float, float]]]:
        """Return readings in [from_ts, to_ts] from both SQLite and Parquet.

        Returns
        -------
        dict[str, list[tuple[float, float]]]
            ``{channel: [(unix_ts, value), ...]}`` sorted by timestamp ascending.
        """
        channel_set = set(channels) if channels is not None else None
        index = self._load_index()
        archived_names: dict[str, str] = {
            entry["original_name"]: entry["archive_path"] for entry in index.get("files", [])
        }

        result: dict[str, list[tuple[float, float]]] = {}

        # Normalize to UTC first so epoch values and day boundaries are consistent.
        from_utc = from_ts.astimezone(UTC) if from_ts.tzinfo else from_ts.replace(tzinfo=UTC)
        to_utc = to_ts.astimezone(UTC) if to_ts.tzinfo else to_ts.replace(tzinfo=UTC)

        from_epoch = from_utc.timestamp()
        to_epoch = to_utc.timestamp()

        # Iterate day by day across the query range
        current_day = from_utc.date()
        last_day = to_utc.date()
        while current_day <= last_day:
            db_name = f"data_{current_day.isoformat()}.db"
            db_path = self._data_dir / db_name
            is_archived = db_name in archived_names
            hot_exists = db_path.exists()
            if is_archived and hot_exists:
                # Overlap day: a restored/backdated (or stranded pre-sweep) hot
                # DB reappeared for an already-archived day. Union both, archived
                # wins on an exact (channel, ts) clash — mirrors query_rows (F2)
                # so history/journal reads no longer shadow rows exports see.
                self._merge_overlap_day(archived_names[db_name], db_path, from_epoch, to_epoch, channel_set, result)
            elif is_archived:
                self._query_parquet(archived_names[db_name], from_epoch, to_epoch, channel_set, result)
            elif hot_exists:
                self._query_sqlite(db_path, from_epoch, to_epoch, channel_set, result)
            current_day += timedelta(days=1)

        # Sort each channel's data by timestamp
        for ch in result:
            result[ch].sort(key=lambda x: x[0])

        return result

    def query_rows(
        self,
        start: datetime | None,
        end: datetime | None,
        channels: list[str] | None,
        instrument_ids: list[str] | None = None,
    ) -> list[FullRow]:
        """Full readings rows across hot SQLite + cold Parquet for export.

        This is the read boundary for the CSV/XLSX date-range exporters: unlike
        :meth:`query` (which returns only ``{channel: [(ts, value)]}``), it
        preserves every export column ``(timestamp, instrument_id, channel,
        value, unit, status)``. Once a day is rotated to Parquet its SQLite file
        is gone, so exports MUST come here or they go blind over rotated days.

        Semantics mirror the SQLite exporters they replace: ``start`` inclusive,
        ``end`` **exclusive**; ``None`` bounds mean unbounded. ``value`` is
        decoded (a sentinel / error / legacy ±inf row surfaces as ``NaN``);
        ``status`` is returned verbatim. Rows are sorted by timestamp ascending.
        """
        channel_set = set(channels) if channels else None
        instrument_set = set(instrument_ids) if instrument_ids else None

        from_epoch = from_day = None
        to_epoch = to_day = None
        if start is not None:
            s = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            from_epoch, from_day = s.timestamp(), s.date()
        if end is not None:
            e = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            to_epoch, to_day = e.timestamp(), e.date()

        index = self._load_index()
        # day → [("parquet", archive_rel), ...] | [("sqlite", db_path)]. Normally
        # a rotated day has only its Parquet (the hot .db was deleted). But if a
        # hot daily DB reappears for an already-archived day (manual restore /
        # backdated import), BOTH exist — union them so no on-disk data an
        # operator can see is silently shadowed. Exact (ts, instrument, channel)
        # duplicates are deduped below; genuinely new restored rows survive.
        sources: dict[str, list[tuple[str, str]]] = {}
        for entry in index.get("files", []):
            day = _day_from_db_name(entry["original_name"])
            if day is not None:
                sources.setdefault(day, []).append(("parquet", entry["archive_path"]))
        if self._data_dir.exists():
            for db_path in self._data_dir.glob("data_????-??-??.db"):
                day = _day_from_db_name(db_path.name)
                if day is not None:
                    sources.setdefault(day, []).append(("sqlite", str(db_path)))

        out: list[FullRow] = []
        for day_iso in sorted(sources):
            day = date.fromisoformat(day_iso)
            # end exclusive → a row on to_day may still precede to_epoch, so keep
            # the whole [from_day, to_day] day span; the row-level epoch filter
            # inside each reader makes the precise cut.
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            day_rows: dict[tuple[object, str, str], FullRow] = {}
            # Parquet source(s) read first → archived wins across sources.
            # Within every source, the last physical row wins so the same hot
            # SQLite duplicate resolves identically after cold rotation.
            ordered_sources = sorted(sources[day_iso], key=lambda item: 0 if item[0] == "parquet" else 1)
            for kind, ref in ordered_sources:
                source_rows: list[FullRow] = []
                if kind == "parquet":
                    self._read_parquet_rows(ref, from_epoch, to_epoch, channel_set, instrument_set, source_rows)
                else:
                    self._read_sqlite_rows(Path(ref), from_epoch, to_epoch, channel_set, instrument_set, source_rows)
                source_latest: dict[tuple[object, str, str], FullRow] = {}
                for row in source_rows:
                    source_latest[(row[0], row[1], row[2])] = row
                for key, row in source_latest.items():
                    day_rows.setdefault(key, row)
            out.extend(day_rows.values())

        out.sort(key=lambda r: _ts_sort_key(r[0]))
        return out

    def query_operator_log(
        self,
        start: datetime | None,
        end: datetime | None,
    ) -> list[OperatorLogRow]:
        """operator_log rows across hot SQLite + cold Parquet (CR-3 audit trail).

        Cold rotation (F17) archives the per-day ``operator_log`` table to a
        companion Parquet before deleting the daily SQLite file. Nothing read it
        back until now — an old report would show a blank operator journal. This
        unions hot ``operator_log`` with those archived Parquets.

        Returns raw ``(timestamp, experiment_id, author, source, message, tags)``
        tuples sorted by timestamp: ``timestamp`` is the lossless raw epoch float
        (both sources store it that way), ``tags`` is the raw JSON string. The
        caller applies experiment_id filtering / tags decoding so hot and cold
        rows behave identically. Time range is inclusive on both ends.
        """
        from_epoch = from_day = None
        to_epoch = to_day = None
        if start is not None:
            s = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            from_epoch, from_day = s.timestamp(), s.date()
        if end is not None:
            e = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            to_epoch, to_day = e.timestamp(), e.date()

        index = self._load_index()
        # day → [("parquet", operator_log_rel), ...] | [("sqlite", db_path)]. A
        # rotated day's SQLite is normally gone, so its operator_log lives only
        # in the companion Parquet — and only if that day carried operator_log
        # rows at all (entries without operator_log_path simply had none). But if
        # a hot daily DB reappears for an already-rotated day (restore / backdate
        # / stranded pre-sweep), BOTH exist — union them (F2) so a restored
        # journal entry is not shadowed on the audit path while exports see it.
        # Parquet source(s) read first → archived wins on an exact-row clash.
        sources: dict[str, list[tuple[str, str]]] = {}
        for entry in index.get("files", []):
            day = _day_from_db_name(entry["original_name"])
            if day is None:
                continue
            ol_rel = entry.get("operator_log_path")
            if ol_rel:
                sources.setdefault(day, []).append(("parquet", ol_rel))
        if self._data_dir.exists():
            for db_path in self._data_dir.glob("data_????-??-??.db"):
                day = _day_from_db_name(db_path.name)
                if day is not None:
                    sources.setdefault(day, []).append(("sqlite", str(db_path)))

        overlap = any(len(srcs) > 1 for srcs in sources.values())
        out: list[OperatorLogRow] = []
        for day_iso in sorted(sources):
            day = date.fromisoformat(day_iso)
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            for kind, ref in sources[day_iso]:
                if kind == "parquet":
                    self._read_parquet_operator_log(ref, from_epoch, to_epoch, out)
                else:
                    self._read_sqlite_operator_log(Path(ref), from_epoch, to_epoch, out)

        if overlap:
            # Only pay dedup cost when a day had >1 source. Exact-row duplicate
            # (same ts/exp/author/source/message/tags) collapses to one; a
            # restored-only entry differs and survives. Keep first occurrence.
            seen: set[OperatorLogRow] = set()
            deduped: list[OperatorLogRow] = []
            for row in out:
                if row in seen:
                    continue
                seen.add(row)
                deduped.append(row)
            out = deduped

        out.sort(key=lambda r: _ts_sort_key(r[0]))
        return out

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    def _read_sqlite_operator_log(
        self,
        db_path: Path,
        from_epoch: float | None,
        to_epoch: float | None,
        out: list[OperatorLogRow],
    ) -> None:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='operator_log'"
                ).fetchone()
                if exists is None:
                    return
                query = "SELECT timestamp, experiment_id, author, source, message, tags FROM operator_log"
                cond: list[str] = []
                params: list[object] = []
                if from_epoch is not None:
                    cond.append("timestamp >= ?")
                    params.append(from_epoch)
                if to_epoch is not None:
                    cond.append("timestamp <= ?")  # inclusive: mirrors reporting's old SQL
                    params.append(to_epoch)
                if cond:
                    query += " WHERE " + " AND ".join(cond)
                query += " ORDER BY timestamp, rowid"
                for row in conn.execute(query, params):
                    out.append(
                        (
                            row["timestamp"],
                            row["experiment_id"],
                            str(row["author"] or ""),
                            str(row["source"] or ""),
                            str(row["message"] or ""),
                            str(row["tags"] or "[]"),
                        )
                    )
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to read operator_log from SQLite %s — partial result", db_path.name)

    def _read_parquet_operator_log(
        self,
        archive_rel: str,
        from_epoch: float | None,
        to_epoch: float | None,
        out: list[OperatorLogRow],
    ) -> None:
        parquet_path = self._archive_dir / archive_rel
        if not parquet_path.exists():
            logger.warning("Archived operator_log Parquet missing: %s — skipping", archive_rel)
            return
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(
                str(parquet_path),
                columns=["timestamp", "experiment_id", "author", "source", "message", "tags"],
            )
            # CR-3 schema keeps timestamp as a raw epoch float (lossless audit).
            ts_list = table.column("timestamp").to_pylist()
            exp_list = table.column("experiment_id").to_pylist()
            author_list = table.column("author").to_pylist()
            source_list = table.column("source").to_pylist()
            message_list = table.column("message").to_pylist()
            tags_list = table.column("tags").to_pylist()
            for ts, exp, author, source, message, tags in zip(
                ts_list, exp_list, author_list, source_list, message_list, tags_list
            ):
                if from_epoch is not None and ts < from_epoch:
                    continue
                if to_epoch is not None and ts > to_epoch:  # inclusive both ends
                    continue
                out.append(
                    (
                        ts,
                        exp,
                        str(author or ""),
                        str(source or ""),
                        str(message or ""),
                        str(tags if tags is not None else "[]"),
                    )
                )
        except Exception:
            logger.exception("Failed to read operator_log Parquet %s — partial result", archive_rel)

    def _read_sqlite_rows(
        self,
        db_path: Path,
        from_epoch: float | None,
        to_epoch: float | None,
        channels: set[str] | None,
        instruments: set[str] | None,
        out: list[FullRow],
    ) -> None:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                query = "SELECT timestamp, instrument_id, channel, value, unit, status FROM readings"
                cond: list[str] = []
                params: list[object] = []
                # Only bound the range when asked — a numeric bound would drop
                # legacy TEXT-ISO timestamps (SQLite orders TEXT above REAL).
                if from_epoch is not None:
                    cond.append("timestamp >= ?")
                    params.append(from_epoch)
                if to_epoch is not None:
                    cond.append("timestamp < ?")
                    params.append(to_epoch)
                if channels is not None:
                    ph = ",".join("?" * len(channels))
                    cond.append(f"channel IN ({ph})")
                    params.extend(channels)
                if instruments is not None:
                    ph = ",".join("?" * len(instruments))
                    cond.append(f"instrument_id IN ({ph})")
                    params.extend(instruments)
                if cond:
                    query += " WHERE " + " AND ".join(cond)
                query += " ORDER BY timestamp"
                for row in conn.execute(query, params):
                    out.append(
                        (
                            row["timestamp"],
                            str(row["instrument_id"]),
                            str(row["channel"]),
                            decode(float(row["value"]), row["status"]),
                            str(row["unit"]),
                            str(row["status"]),
                        )
                    )
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to read SQLite %s — partial result", db_path.name)

    def _read_parquet_rows(
        self,
        archive_rel: str,
        from_epoch: float | None,
        to_epoch: float | None,
        channels: set[str] | None,
        instruments: set[str] | None,
        out: list[FullRow],
    ) -> None:
        parquet_path = self._archive_dir / archive_rel
        if not parquet_path.exists():
            logger.warning("Archived Parquet file missing: %s — skipping", archive_rel)
            return
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(
                str(parquet_path),
                columns=["timestamp", "instrument_id", "channel", "value", "unit", "status"],
            )
            ts_us = table.column("timestamp").cast("int64").to_pylist()
            inst_list = table.column("instrument_id").to_pylist()
            ch_list = table.column("channel").to_pylist()
            val_list = table.column("value").to_pylist()
            unit_list = table.column("unit").to_pylist()
            status_list = table.column("status").to_pylist()
            for ts_int, inst, ch, val, unit, status in zip(ts_us, inst_list, ch_list, val_list, unit_list, status_list):
                epoch = ts_int / 1_000_000.0
                if from_epoch is not None and epoch < from_epoch:
                    continue
                if to_epoch is not None and epoch >= to_epoch:
                    continue
                if channels is not None and ch not in channels:
                    continue
                if instruments is not None and inst not in instruments:
                    continue
                out.append((epoch, str(inst), str(ch), decode(float(val), status), str(unit), str(status)))
        except Exception:
            logger.exception("Failed to read Parquet %s — partial result", archive_rel)

    def _merge_overlap_day(
        self,
        archive_rel: str,
        db_path: Path,
        from_epoch: float,
        to_epoch: float,
        channels: set[str] | None,
        out: dict[str, list[tuple[float, float]]],
    ) -> None:
        """Union one archived Parquet day with a reappeared hot DB, deduped.

        Archived rows read first and win on an exact (channel, ts) clash; a hot
        row whose ts is not already present for that channel is appended, so a
        restored/backdated reading surfaces instead of being shadowed. Called
        only for a day that genuinely has both sources — pure-hot and pure-cold
        days keep their byte-identical single-source fast path.
        """
        archived: dict[str, list[tuple[float, float]]] = {}
        self._query_parquet(archive_rel, from_epoch, to_epoch, channels, archived)
        hot: dict[str, list[tuple[float, float]]] = {}
        self._query_sqlite(db_path, from_epoch, to_epoch, channels, hot)
        for ch in archived.keys() | hot.keys():
            merged = {ts: value for ts, value in hot.get(ch, ())}
            # Archived cut wins across sources, while each source reader has
            # already applied the same last-physical-row duplicate rule.
            merged.update({ts: value for ts, value in archived.get(ch, ())})
            out.setdefault(ch, []).extend(merged.items())

    def _query_sqlite(
        self,
        db_path: Path,
        from_epoch: float,
        to_epoch: float,
        channels: set[str] | None,
        out: dict[str, list[tuple[float, float]]],
    ) -> None:
        latest: dict[tuple[float, str], tuple[float, float]] = {}
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                if channels is not None:
                    placeholders = ",".join("?" * len(channels))
                    cursor = conn.execute(
                        f"SELECT timestamp, channel, value, status FROM readings "
                        f"WHERE timestamp >= ? AND timestamp <= ? "
                        f"AND channel IN ({placeholders}) ORDER BY timestamp, rowid",
                        (from_epoch, to_epoch, *channels),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT timestamp, channel, value, status FROM readings "
                        "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp, rowid",
                        (from_epoch, to_epoch),
                    )
                for row in cursor:
                    ch = str(row["channel"])
                    timestamp = float(row["timestamp"])
                    # NaN-доктрина: mask sentinel / error / legacy ±inf at the read boundary.
                    latest[(timestamp, ch)] = (timestamp, decode(float(row["value"]), row["status"]))
            finally:
                conn.close()
            for (_timestamp, ch), row in latest.items():
                out.setdefault(ch, []).append(row)
        except Exception:
            logger.exception("Failed to read SQLite %s — partial result", db_path.name)

    def _query_parquet(
        self,
        archive_rel: str,
        from_epoch: float,
        to_epoch: float,
        channels: set[str] | None,
        out: dict[str, list[tuple[float, float]]],
    ) -> None:
        parquet_path = self._archive_dir / archive_rel
        if not parquet_path.exists():
            logger.warning("Archived Parquet file missing: %s — skipping", archive_rel)
            return
        try:
            import pyarrow.parquet as pq

            latest: dict[tuple[float, str], tuple[float, float]] = {}

            table = pq.read_table(
                str(parquet_path),
                columns=["timestamp", "channel", "value", "status"],
            )
            ts_us = table.column("timestamp").cast("int64").to_pylist()
            ch_list = table.column("channel").to_pylist()
            val_list = table.column("value").to_pylist()
            status_list = table.column("status").to_pylist()

            for ts_int, ch, val, status in zip(ts_us, ch_list, val_list, status_list):
                epoch = ts_int / 1_000_000.0
                if epoch < from_epoch or epoch > to_epoch:
                    continue
                channel = str(ch)
                if channels is not None and channel not in channels:
                    continue
                # NaN-доктрина: mask sentinel / error / legacy ±inf at the read boundary.
                latest[(epoch, channel)] = (epoch, decode(float(val), status))
            for (_timestamp, channel), row in latest.items():
                out.setdefault(channel, []).append(row)
        except Exception:
            logger.exception("Failed to read Parquet %s — partial result", archive_rel)

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def _load_index(self) -> dict:
        index_path = self._archive_dir / "index.json"
        if not index_path.exists():
            return {"files": []}
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            logger.error(
                "Archive index.json at %s is corrupt — query cannot determine which days "
                "have been rotated to Parquet. Inspect and repair or delete the file manually.",
                index_path,
            )
            raise RuntimeError(f"Archive index.json corrupt: {index_path}")
