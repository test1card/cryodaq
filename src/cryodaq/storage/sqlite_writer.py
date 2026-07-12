"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.

Один файл на день: data_YYYY-MM-DD.db.
Батчевая вставка каждую секунду (или при накоплении batch_size).
Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

from cryodaq.channels.descriptors import ChannelCatalog
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.operator_log import OperatorLogEntry, normalize_operator_log_tags
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import (
    SQLITE_BACKPORT_SAFE,
    SQLITE_BROKEN_RANGE,
    sqlite3,
    sqlite_version_info,
)
from cryodaq.storage.channel_descriptors import (
    DescriptorBoundReading,
    LiveChannelDescriptorCatalog,
    descriptor_hash_for_reading,
    initialize_descriptor_storage,
    install_catalog,
    snapshot_catalog,
    verify_descriptor_storage,
)
from cryodaq.storage.sentinel import decode, encode, is_sentinel

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
        return datetime.fromtimestamp(raw, tz=UTC)
    return datetime.fromisoformat(str(raw))


_SQLITE_VERSION_CHECKED = False

# readings_history trust-boundary clamps. The command is reachable from
# unauthenticated loopback ZMQ, so a hostile/buggy client can request an
# unbounded channel list + limit and starve the engine (semantic-DoS). Fail
# closed: cap rows-per-channel and channel-list length, and push LIMIT into
# SQL so the query never materialises more than can survive truncation.
_HISTORY_MAX_ROWS = 100_000
_HISTORY_MAX_CHANNELS = 64

# Range and backport-safe set live in cryodaq.storage._sqlite (single source,
# also used to pick the sqlite3 implementation). Imported above.


def _check_sqlite_version() -> None:
    """Hard-fail if running on a SQLite version affected by the March 2026 WAL-reset bug.

    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
    connections across threads/processes write or checkpoint "at the same
    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
    history reader, web dashboard, reporting); upgrade to >= 3.51.3.

    Versions in SQLITE_BACKPORT_SAFE (3.44.6, 3.50.7) carry a backport of the
    fix and are allowed through without requiring CRYODAQ_ALLOW_BROKEN_SQLITE=1.

    Set CRYODAQ_ALLOW_BROKEN_SQLITE=1 to bypass with explicit operator acknowledgment.
    """
    global _SQLITE_VERSION_CHECKED
    if _SQLITE_VERSION_CHECKED:
        return
    _SQLITE_VERSION_CHECKED = True
    version = sqlite_version_info()  # chosen impl, e.g. (3, 37, 2)
    lo, hi = SQLITE_BROKEN_RANGE
    if lo <= version < hi:
        if version in SQLITE_BACKPORT_SAFE:
            return
        bypass = os.environ.get("CRYODAQ_ALLOW_BROKEN_SQLITE", "").strip()
        if bypass == "1":
            logger.warning(
                "CRYODAQ_ALLOW_BROKEN_SQLITE=1: bypassing SQLite WAL gate. "
                "SQLite %d.%d.%d is affected by the March 2026 WAL-reset "
                "corruption bug. Data integrity risk accepted by operator.",
                version[0],
                version[1],
                version[2],
            )
            return
        raise RuntimeError(
            f"SQLite {version[0]}.{version[1]}.{version[2]} is affected by the "
            "March 2026 WAL-reset corruption bug (range 3.7.0 – 3.51.2). "
            "CryoDAQ refuses to start with a known-broken SQLite version. "
            "Upgrade to SQLite >= 3.51.3, or use a backport-safe build "
            "(3.44.6 or 3.50.7), or set CRYODAQ_ALLOW_BROKEN_SQLITE=1 "
            "to bypass with explicit operator acknowledgment."
        )


# Locked-DB persistence-failure parity (roadmap A6). See _write_day_batch:
# a sustained lock (not a few transient blips) must route into
# _signal_persistence_failure like disk-full does.
_LOCKED_FAILURE_THRESHOLD = 3
_LOCKED_FAILURE_SPAN_S = 15.0


_COMMIT_RECEIPT_PROVENANCE = object()


@dataclass(frozen=True, slots=True, init=False, eq=False)
class CommittedReadingReceipt:
    """One persistence-owner-issued, wire-ready committed reading value.

    The canonical descriptor envelope and its derived identity fields are
    carried beside a fresh reading snapshot.  This is observational evidence,
    never driver, credential, callback, or control authority.
    """

    _bound: DescriptorBoundReading
    channel_id: str
    descriptor_hash: str
    descriptor_revision: int
    descriptor_envelope: bytes

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("committed reading receipts are issued only by SQLiteWriter")

    @classmethod
    def _issue(cls, bound: DescriptorBoundReading) -> CommittedReadingReceipt:
        descriptor = bound.descriptor
        issued = object.__new__(cls)
        object.__setattr__(issued, "_bound", bound)
        object.__setattr__(issued, "channel_id", descriptor.channel_id)
        object.__setattr__(issued, "descriptor_hash", descriptor.descriptor_hash)
        object.__setattr__(issued, "descriptor_revision", descriptor.descriptor_revision)
        object.__setattr__(
            issued,
            "descriptor_envelope",
            PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json,
        )
        return issued

    @property
    def reading(self) -> Reading:
        """Return a fresh owned Reading, including exact ``raw`` and metadata."""

        return self._bound.reading

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True, init=False, eq=False, weakref_slot=True)
class CommittedBatchReceipt:
    """Atomic post-commit carrier issued by one exact SQLiteWriter owner."""

    entries: tuple[CommittedReadingReceipt, ...]
    _owner_key: object
    _provenance: object
    _integrity_token: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("committed batch receipts are issued only by SQLiteWriter")

    @classmethod
    def _issue(
        cls,
        entries: tuple[CommittedReadingReceipt, ...],
        *,
        owner_key: object,
        integrity_token: object,
    ) -> CommittedBatchReceipt:
        issued = object.__new__(cls)
        object.__setattr__(issued, "entries", entries)
        object.__setattr__(issued, "_owner_key", owner_key)
        object.__setattr__(issued, "_provenance", _COMMIT_RECEIPT_PROVENANCE)
        object.__setattr__(issued, "_integrity_token", integrity_token)
        return issued

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class _CommitReceiptIntegrity:
    entries: tuple[CommittedReadingReceipt, ...]
    entry_values: tuple[tuple[str, str, int, bytes, DescriptorBoundReading], ...]
    token: object


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
        channel_catalog: ChannelCatalog | LiveChannelDescriptorCatalog | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._flush_interval_s = flush_interval_s
        self._batch_size = batch_size
        self._conn: sqlite3.Connection | None = None
        self._current_date: date | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_written: int = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
        self._checkpoint_counter = 0
        # Optional F35 descriptor authority.  A plain ChannelCatalog retains
        # the explicit legacy bool API for tools/tests.  Production supplies a
        # LiveChannelDescriptorCatalog and must use post-commit receipts.
        self._live_channel_catalog = channel_catalog if type(channel_catalog) is LiveChannelDescriptorCatalog else None
        if self._live_channel_catalog is not None:
            self._channel_catalog = self._live_channel_catalog.storage_catalog_snapshot()
        else:
            self._channel_catalog = None if channel_catalog is None else snapshot_catalog(channel_catalog)
        self._commit_owner_key = object()
        self._issued_commits: WeakKeyDictionary[CommittedBatchReceipt, _CommitReceiptIntegrity] = WeakKeyDictionary()

        # Disk-full graceful degradation (Phase 2a H.1).
        # When the writer thread detects disk-full from sqlite3.OperationalError,
        # it sets _disk_full=True and (optionally) schedules a callback on the
        # engine event loop via run_coroutine_threadsafe so the SafetyManager
        # can latch a fault. The flag is cleared by DiskMonitor when free
        # space recovers, BUT the operator still has to acknowledge_fault to
        # actually resume polling.
        self._disk_full = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None

        # Locked-DB persistence-failure parity (roadmap A6). Consecutive
        # "database is locked"/"database is busy" write_immediate failures
        # are usually transient (WAL writer contention) and clear on retry —
        # only a sustained lock (>= _LOCKED_FAILURE_THRESHOLD consecutive
        # failures spanning >= _LOCKED_FAILURE_SPAN_S) routes into
        # _signal_persistence_failure, same as disk-full. Any successful
        # write resets the streak.
        self._locked_failure_count = 0
        self._locked_failure_first_ts: float | None = None

        _check_sqlite_version()

    def _db_path(self, day: date) -> Path:
        return self._data_dir / f"data_{day.isoformat()}.db"

    # ------------------------------------------------------------------
    # Disk-full graceful degradation (Phase 2a H.1)
    # ------------------------------------------------------------------
    @property
    def is_disk_full(self) -> bool:
        """True when the most recent write hit a disk-full / out-of-space error."""
        return self._disk_full

    @property
    def descriptor_authoritative(self) -> bool:
        """Whether callers must use post-commit receipt publication."""

        return self._live_channel_catalog is not None

    def clear_disk_full(self) -> None:
        """Clear the disk-full flag.

        Called by DiskMonitor when free space recovers above the threshold.
        Note: this does NOT auto-resume polling — the SafetyManager has
        already latched a fault, and the operator must acknowledge_fault
        explicitly. This is a deliberate guard against disk-space flapping.
        """
        if self._disk_full:
            logger.warning(
                "Disk space recovered — clearing _disk_full flag. "
                "SafetyManager fault remains latched until operator acknowledge."
            )
            self._disk_full = False

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the writer to an event loop so the executor thread can
        schedule the persistence-failure callback on it."""
        self._loop = loop

    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Register an async callback for persistence failures (disk full etc).

        The callback is awaited via :func:`asyncio.run_coroutine_threadsafe`
        from the writer thread, so it lands on the engine event loop where
        SafetyManager.on_persistence_failure can latch a fault.
        """
        self._persistence_failure_callback = callback

    def _signal_persistence_failure(self, reason: str) -> None:
        """Schedule persistence-failure callback on the engine event loop.

        Runs in the writer thread (called from _write_day_batch) — must NOT
        block. We use run_coroutine_threadsafe and intentionally do NOT await
        the resulting Future, because the writer thread does not have an
        event loop of its own.
        """
        if self._persistence_failure_callback is None or self._loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._persistence_failure_callback(reason),
                self._loop,
            )
        except Exception as exc:
            logger.error("Failed to schedule persistence_failure callback: %s", exc)
            return
        # The writer thread does not await this Future. Without a done-callback
        # an exception raised inside the safety callback (e.g. the disk-full
        # latch itself failing) would be swallowed silently. Log CRITICAL so
        # the lost latch failure is at least visible in the record.
        future.add_done_callback(self._log_persistence_callback_result)

    @staticmethod
    def _log_persistence_callback_result(future: Any) -> None:
        """Surface an exception from the persistence-failure safety callback.

        Runs on the engine event loop when the scheduled coroutine finishes.
        Success is silent; a raised exception is logged CRITICAL because it
        means the disk-full fault latch may not have fired.
        """
        try:
            exc = future.exception()
        except CancelledError:
            return
        if exc is not None:
            logger.critical(
                "Persistence-failure safety callback raised — disk-full fault latch may NOT have fired: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _ensure_connection(self, day: date) -> sqlite3.Connection:
        """Открыть/переоткрыть БД если сменился день."""
        if self._conn is not None and self._current_date == day:
            return self._conn
        if self._conn is not None:
            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
            self._conn.close()
            self._conn = None
            self._current_date = None
        db_path = self._db_path(day)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
        # Default autocheckpoint (1000 pages) can starve under concurrent
        # readers. See https://www.sqlite.org/wal.html
        result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
        actual_mode = (result[0] if result else "").lower()
        if actual_mode != "wal":
            raise RuntimeError(
                f"SQLite WAL mode could not be enabled at {db_path}. "
                f"PRAGMA journal_mode returned {actual_mode!r}. "
                f"This may indicate an unsupported filesystem (network share, "
                f"WSL with DrvFs, or read-only mount). CryoDAQ requires WAL "
                f"for cross-process read concurrency. Refusing to start."
            )
        # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
        # throughput. Production deployments must be on a UPS. If no UPS,
        # set CRYODAQ_SQLITE_SYNC=FULL.
        sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
        if sync_mode not in ("NORMAL", "FULL"):
            sync_mode = "NORMAL"
        conn.execute(f"PRAGMA synchronous={sync_mode};")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")  # ~4 MB
        conn.execute("PRAGMA cache_size=-16384;")  # 16 MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(SCHEMA_READINGS)
        conn.execute(SCHEMA_SOURCE_DATA)
        conn.execute(SCHEMA_OPERATOR_LOG)
        conn.execute(INDEX_READINGS_TS)
        conn.execute(INDEX_SOURCE_DATA_TS)
        conn.execute(INDEX_CHANNEL_TS)
        conn.execute(INDEX_OPERATOR_LOG_TS)
        conn.execute(INDEX_OPERATOR_LOG_EXPERIMENT)
        conn.commit()
        try:
            initialize_descriptor_storage(conn)
        except Exception:
            conn.close()
            raise
        self._conn = conn
        self._current_date = day
        logger.info("Открыта БД: %s", db_path)
        return conn

    def _write_batch(self, batch: list[Reading]) -> bool:
        """Вставить пакет в таблицу readings (вызывается в потоке).

        Readings с value=None или value=NaN пропускаются (sqlite3 maps NaN
        to NULL, which violates the NOT NULL constraint on readings.value).

        Readings are grouped by day before writing so that a batch spanning
        midnight is correctly split across daily DB files.

        Returns True iff every day's sub-batch was durably persisted; False
        if any sub-batch was swallowed (disk-full / locked-DB — see
        _write_day_batch). This is a LOCAL result of this one call, not
        shared writer state (R1, Phase A recheck) — concurrent
        write_immediate() calls on the same writer can otherwise interleave
        on the single-worker executor and clobber a shared drop flag before
        the dropping caller ever checks it.
        """
        if not batch:
            return True
        persisted = True
        # Group readings by day to handle midnight crossing
        by_day: dict[date, list[Reading]] = {}
        for r in batch:
            day = r.timestamp.date()
            by_day.setdefault(day, []).append(r)
        for day, day_readings in sorted(by_day.items()):
            conn = self._ensure_connection(day)
            if not self._write_day_batch(conn, day_readings):
                persisted = False
        return persisted

    def _write_live_batch(
        self,
        batch: list[Reading],
    ) -> tuple[DescriptorBoundReading, ...] | None:
        """Bind and commit one descriptor-authoritative batch in the writer thread.

        A descriptor-mode poll is one SQLite transaction and therefore cannot
        span daily files.  Midnight-crossing input is refused before either
        file is opened; a later scheduler poll may retry each coherent batch.
        ``None`` means SQLite explicitly swallowed a disk-full/locked failure.
        """

        owner = self._live_channel_catalog
        if owner is None:
            raise RuntimeError("descriptor-authoritative commit requires a live catalog owner")
        if not batch:
            raise ValueError("descriptor-authoritative commit requires a non-empty batch")

        bound = tuple(owner.bind(reading) for reading in batch)
        days = {item.reading.timestamp.date() for item in bound}
        if len(days) != 1:
            raise ValueError("descriptor-authoritative batch cannot span daily SQLite files")

        stable_readings: list[Reading] = []
        for item in bound:
            reading = item.reading
            nonfinite = not math.isfinite(reading.value)
            if nonfinite and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains non-finite OK reading")
            if not nonfinite and is_sentinel(reading.value) and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains sentinel OK reading")
            stable_readings.append(replace(reading, channel=item.descriptor.channel_id))

        persisted = self._write_day_batch(
            self._ensure_connection(next(iter(days))),
            stable_readings,
        )
        return bound if persisted else None

    @staticmethod
    def _receipt_entry_value(
        entry: CommittedReadingReceipt,
    ) -> tuple[str, str, int, bytes, DescriptorBoundReading]:
        return (
            entry.channel_id,
            entry.descriptor_hash,
            entry.descriptor_revision,
            entry.descriptor_envelope,
            entry._bound,
        )

    def _issue_committed_batch(
        self,
        bound: tuple[DescriptorBoundReading, ...],
    ) -> CommittedBatchReceipt:
        owner = self._live_channel_catalog
        if owner is None or not bound or any(not owner.owns(item) for item in bound):
            raise RuntimeError("cannot issue a commit receipt for foreign descriptor bindings")
        entries = tuple(CommittedReadingReceipt._issue(item) for item in bound)
        token = object()
        receipt = CommittedBatchReceipt._issue(
            entries,
            owner_key=self._commit_owner_key,
            integrity_token=token,
        )
        self._issued_commits[receipt] = _CommitReceiptIntegrity(
            entries=entries,
            entry_values=tuple(self._receipt_entry_value(entry) for entry in entries),
            token=token,
        )
        return receipt

    def owns_commit(self, candidate: object) -> bool:
        """Whether this exact writer issued this still-intact commit evidence."""

        if type(candidate) is not CommittedBatchReceipt:
            return False
        integrity = self._issued_commits.get(candidate)
        owner = self._live_channel_catalog
        if integrity is None or owner is None:
            return False
        try:
            return (
                candidate._provenance is _COMMIT_RECEIPT_PROVENANCE
                and candidate._owner_key is self._commit_owner_key
                and candidate._integrity_token is integrity.token
                and candidate.entries is integrity.entries
                and candidate.entries
                and tuple(self._receipt_entry_value(entry) for entry in candidate.entries) == integrity.entry_values
                and all(owner.owns(entry._bound) for entry in candidate.entries)
                and all(
                    entry.descriptor_envelope
                    == PersistedChannelEnvelopeV1.from_descriptor(entry._bound.descriptor).canonical_json
                    and entry.descriptor_hash == entry._bound.descriptor.descriptor_hash
                    and entry.descriptor_revision == entry._bound.descriptor.descriptor_revision
                    and entry.channel_id == entry._bound.descriptor.channel_id
                    for entry in candidate.entries
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def readings_from_commit(self, receipt: object) -> list[Reading]:
        """Return fresh post-commit readings without descriptor re-resolution."""

        if not self.owns_commit(receipt):
            raise TypeError("commit receipt is foreign, forged, or mutated")
        assert isinstance(receipt, CommittedBatchReceipt)
        return [entry.reading for entry in receipt.entries]

    def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> bool:
        """Write a single day's readings to the given connection.

        Returns True if the batch was durably committed (or there was
        nothing to write), False if it was swallowed (disk-full / locked-DB
        below the A6 signalling threshold — see below). The caller
        (_write_batch) folds this per-day result into the per-call return
        of write_immediate().

        NaN-доктрина (P2-2): a non-finite value paired with a non-OK status is
        persisted as the finite ``sentinel.SENTINEL`` value carrying that status,
        so the invariant «if the DataBroker has a reading, SQLite has it» holds
        even for error states (SQLite cannot store NaN — it maps NaN to NULL,
        violating NOT NULL). The status column, not the float value, is the
        discriminator; readers reconstruct NaN via :func:`sentinel.decode`.

        Two rows are refused (never persisted):
        - value=None                                → dropped (no value at all).
        - non-finite value WITH status OK           → garbage (value/status
          disagree — impossible under the doctrine).
        - sentinel value WITH a non-error status    → contract (a): a sentinel
          must never masquerade as a real measurement. Fail-closed: CRITICAL log
          + drop.
        """
        rows = []
        skipped = 0
        for r in batch:
            if r.value is None:
                skipped += 1
                continue
            nonfinite = isinstance(r.value, float) and not math.isfinite(r.value)
            if not nonfinite and is_sentinel(r.value) and r.status is ChannelStatus.OK:
                # Contract (a): sentinel value + non-error status can never be a
                # real measurement — refuse it fail-closed.
                logger.critical(
                    "Отвергнута строка readings: sentinel-значение (%r) со статусом OK "
                    "на канале %s (%s) — sentinel не может выдавать себя за измерение",
                    r.value,
                    r.channel,
                    r.instrument_id or "unknown",
                )
                skipped += 1
                continue
            if nonfinite and r.status is ChannelStatus.OK:
                # Non-finite value with an OK status: value/status disagree
                # (garbage). Drop — the doctrine never produces this pairing.
                skipped += 1
                continue
            stored_value, stored_status = encode(r.value, r.status)
            descriptor_hash = (
                None
                if self._channel_catalog is None
                else descriptor_hash_for_reading(
                    self._channel_catalog,
                    instrument_id=r.instrument_id,
                    channel=r.channel,
                    unit=r.unit,
                )
            )
            rows.append(
                (
                    r.timestamp.timestamp(),
                    r.instrument_id or "unknown",
                    r.channel,
                    stored_value,
                    r.unit,
                    stored_status,
                    descriptor_hash,
                )
            )
        if skipped:
            logger.warning(
                "Пропущено %d readings (value=None / non-finite+OK / sentinel+OK) из батча %d",
                skipped,
                len(batch),
            )
        if not rows:
            return True
        try:
            conn.execute("BEGIN IMMEDIATE")
            if self._channel_catalog is not None:
                install_catalog(conn, self._channel_catalog, within_transaction=True)
            conn.executemany(
                "INSERT INTO main.readings "
                "(timestamp, instrument_id, channel, value, unit, status, descriptor_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                rows,
            )
            if self._channel_catalog is not None:
                verify_descriptor_storage(conn)
            conn.commit()
            # A successful write resets the locked-DB streak (roadmap A6).
            self._locked_failure_count = 0
            self._locked_failure_first_ts = None
        except sqlite3.OperationalError as exc:
            conn.rollback()
            # Disk-full graceful degradation (Phase 2a H.1).
            # Detect by exact PHRASES to avoid false positives like
            # "database disk image is malformed" (SQLITE_CORRUPT) or
            # "disk I/O error" (SQLITE_IOERR), which are NOT disk-full.
            # Phrases cover SQLITE_FULL on Linux/macOS/Windows + quota.
            msg = str(exc).lower()
            disk_full_phrases = (
                "database or disk is full",
                "database is full",
                "no space left on device",
                "not enough space on the disk",
                "disk quota exceeded",
            )
            if any(phrase in msg for phrase in disk_full_phrases):
                if not self._disk_full:
                    logger.critical(
                        "DISK FULL detected in SQLite write: %s. Pausing polling, triggering safety fault.",
                        exc,
                    )
                self._disk_full = True
                self._signal_persistence_failure(f"disk full: {exc}")
                # Do NOT re-raise. Re-raising would propagate up to
                # write_immediate / scheduler and cause the historic tight
                # CRITICAL-log loop. The flag + signalled callback are the
                # signalling mechanism now.
                return False

            # Locked-DB parity (roadmap A6): "database is locked"/"database
            # is busy" is usually transient (WAL writer contention) and
            # clears on retry. Only a sustained lock — >= _LOCKED_FAILURE_THRESHOLD
            # CONSECUTIVE failures spanning >= _LOCKED_FAILURE_SPAN_S — is
            # treated like disk-full. Both conditions must hold: a burst of
            # quick failures or sporadic non-consecutive ones must not signal.
            locked_phrases = ("database is locked", "database is busy")
            if any(phrase in msg for phrase in locked_phrases):
                now = time.monotonic()
                if self._locked_failure_count == 0:
                    self._locked_failure_first_ts = now
                self._locked_failure_count += 1
                span = now - self._locked_failure_first_ts
                if self._locked_failure_count >= _LOCKED_FAILURE_THRESHOLD and span >= _LOCKED_FAILURE_SPAN_S:
                    logger.critical(
                        "LOCKED DB: %d consecutive database is locked/busy "
                        "failures spanning %.1fs. Triggering safety fault.",
                        self._locked_failure_count,
                        span,
                    )
                    self._signal_persistence_failure(f"database locked: {exc}")
                else:
                    # Below threshold: swallowed (no raise) but never silent —
                    # the batch was lost and the log must say so.
                    logger.warning(
                        "Batch write failed, database locked/busy (%d/%d, %.1fs): %s",
                        self._locked_failure_count,
                        _LOCKED_FAILURE_THRESHOLD,
                        span,
                        exc,
                    )
                # F1/R1 (Phase A gate + recheck, CRITICAL): the batch was
                # swallowed, not persisted — report it via the return value
                # (not shared writer state) so the caller (_write_batch) can
                # fold it into write_immediate()'s own per-call result and
                # the scheduler can skip publishing to any broker,
                # regardless of whether the A6 signalling threshold was hit.
                # Do NOT re-raise — same graceful-degradation rationale as
                # disk-full above (avoid the historic tight CRITICAL-log loop).
                return False
            # Any other OperationalError keeps the existing semantics.
            raise
        except Exception:
            conn.rollback()
            raise

        # Periodic explicit PASSIVE checkpoint (~once per minute at 1 Hz batch
        # cadence). Prevents WAL file growth under concurrent reader pressure.
        # See DEEP_AUDIT_CC.md D.1.
        self._checkpoint_counter += 1
        if self._checkpoint_counter >= 60:
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.OperationalError as exc:
                logger.warning("Periodic WAL checkpoint failed: %s", exc)
            self._checkpoint_counter = 0
        self._total_written += len(rows)
        return True

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

        # Daily files are named by UTC day; normalize the caller-supplied range
        # to UTC before deriving the day (mirrors ArchiveReader.query), else an
        # early-hours local start selects the wrong day file and drops rows.
        selected: list[Path] = []
        start_day = (
            (start_time.astimezone(UTC) if start_time.tzinfo else start_time.replace(tzinfo=UTC)).date()
            if start_time is not None
            else None
        )
        end_day = (
            (end_time.astimezone(UTC) if end_time.tzinfo else end_time.replace(tzinfo=UTC)).date()
            if end_time is not None
            else None
        )
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
                    "SELECT id, timestamp, experiment_id, author, source, message, tags FROM operator_log WHERE 1 = 1"
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

        # Cold union (F2): a rotated day's operator_log lives only in the archive
        # Parquet — its hot .db was deleted. The hot scan above therefore drops
        # every rotated audit entry from the live operator journal, even though
        # reports already union the same rows via ArchiveReader.query_operator_log.
        # Thread the live path through the same reader. No archive index → skip
        # entirely so hot-only deployments stay byte-identical.
        archive_index = self._data_dir / "archive" / "index.json"
        if archive_index.exists():
            from cryodaq.storage.archive_reader import ArchiveReader

            # query_operator_log unions hot+cold; a hot day is scanned above, so
            # keep only cold-archived days (no hot .db) to avoid double-counting.
            hot_days = {p.stem.removeprefix("data_") for p in self._data_dir.glob("data_????-??-??.db")}
            reader = ArchiveReader(self._data_dir, archive_index.parent)
            for raw_ts, raw_exp, author, source, message, raw_tags in reader.query_operator_log(start_time, end_time):
                entry_ts = _parse_timestamp(raw_ts)
                utc_day = (
                    (entry_ts if entry_ts.tzinfo else entry_ts.replace(tzinfo=UTC)).astimezone(UTC).date().isoformat()
                )
                if utc_day in hot_days:
                    continue
                if experiment_id is not None and raw_exp != experiment_id:
                    continue
                rows.append(
                    OperatorLogEntry(
                        # Archived rows carry no rowid; the GUI panel keys on
                        # timestamp, not id (see operator_log_panel._sort_entries).
                        id=0,
                        timestamp=entry_ts,
                        experiment_id=raw_exp,
                        author=str(author or ""),
                        source=str(source or ""),
                        message=str(message or ""),
                        tags=tuple(json.loads(raw_tags or "[]")),
                    )
                )

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

    async def write_immediate(self, readings: list[Reading]) -> bool:
        """Записать пакет синхронно (await до WAL commit).

        Используется Scheduler для гарантии persistence-first:
        данные попадают в DataBroker ТОЛЬКО после записи на диск.
        При ошибке — логирует CRITICAL и пробрасывает исключение.

        Returns True iff the batch was durably persisted, False if it was
        swallowed (disk-full / locked-DB — see _write_batch). This result is
        per-call (R1, Phase A recheck): callers must not rely on any shared
        writer state, since concurrent write_immediate() calls on the same
        writer share one executor and could otherwise clobber each other's
        outcome.
        """
        if self._live_channel_catalog is not None:
            raise RuntimeError(
                "descriptor-authoritative writer requires write_committed(); "
                "the legacy bool API cannot carry persistence authority"
            )
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self._executor, self._write_batch, readings)
        except Exception:
            logger.critical(
                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
                len(readings),
            )
            raise

    async def write_committed(
        self,
        readings: list[Reading],
    ) -> CommittedBatchReceipt | None:
        """Commit a live descriptor batch and issue evidence only afterward.

        Binding, canonical descriptor validation, catalog installation and row
        insertion all run on the writer executor.  Cancellation never creates
        evidence: if the awaiting task is cancelled while SQLite settles, the
        result is deliberately ambiguous and no receipt is issued.
        """

        if self._live_channel_catalog is None:
            raise RuntimeError("write_committed() requires a live descriptor catalog owner")
        loop = asyncio.get_running_loop()
        try:
            bound = await loop.run_in_executor(self._executor, self._write_live_batch, readings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.critical(
                "CRITICAL: descriptor-authoritative commit failed (%d readings) — no receipt issued",
                len(readings),
            )
            raise
        if bound is None:
            return None
        return self._issue_committed_batch(bound)

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
        entry_time = timestamp or datetime.now(UTC)
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
        # Read-only operations use _read_executor to avoid blocking behind
        # persistence-first writes on _executor. The engine REP task awaits
        # this call for every `log_get` command (~0.1 Hz from the dashboard),
        # and was previously serialised against scheduler.write_immediate()
        # on the single-worker write executor.
        return await loop.run_in_executor(self._read_executor, task)

    async def start_immediate(self) -> None:
        """Инициализировать writer без очереди (persistence-first режим).

        Создаёт директорию данных и помечает writer как работающий.
        Legacy writers use ``write_immediate``; descriptor-authoritative
        production uses ``write_committed`` and its post-commit receipt.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info("SQLiteWriter запущен (immediate mode)")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        """Запустить цикл записи (legacy, обратная совместимость)."""
        if self._live_channel_catalog is not None:
            raise RuntimeError(
                "descriptor-authoritative writer cannot use the legacy queue; "
                "it would discard post-commit receipt authority"
            )
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
        # Shutdown executor FIRST — waits for any in-flight write_batch to finish.
        # Then close connection — no race with executor thread.
        # shutdown(wait=True) blocks until the in-flight sqlite op returns; run it
        # off the event loop via asyncio.to_thread so a busy write doesn't freeze
        # the engine loop during shutdown. All callers await stop() (or drive it
        # via run_until_complete), so a running loop is always present here.
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
        if self._read_executor is not None:
            await asyncio.to_thread(self._read_executor.shutdown, wait=True)
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("SQLiteWriter остановлен (записано: %d)", self._total_written)

    # ------------------------------------------------------------------
    # Readings history query (for GUI reconnect / full-range view)
    # ------------------------------------------------------------------

    def _read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Read historical readings from SQLite.

        Returns {channel: [(unix_ts, value), ...]} sorted by time ASC.
        Scans all daily DB files that overlap [from_ts, to_ts].
        """
        # Trust-boundary clamp (see module constants): bound rows-per-channel
        # and channel-list length before touching the DB. Non-positive limits
        # floor to 1 (a zero limit would otherwise slice result[-0:] = the whole
        # list, i.e. unbounded — the opposite of a limit).
        limit_per_channel = min(max(int(limit_per_channel), 1), _HISTORY_MAX_ROWS)
        if channels:
            channels = list(channels)[:_HISTORY_MAX_CHANNELS]

        result: dict[str, list[tuple[float, float]]] = {}
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))

        # Filter DB files by date range if possible
        if from_ts is not None:
            from_day = datetime.fromtimestamp(from_ts, tz=UTC).date()
        else:
            from_day = None
        if to_ts is not None:
            to_day = datetime.fromtimestamp(to_ts, tz=UTC).date()
        else:
            to_day = None

        selected_dbs: list[Path] = []
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            selected_dbs.append(db_path)

        for db_path in selected_dbs:
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    base = "SELECT timestamp, channel, value, status FROM readings WHERE 1=1"
                    time_clause = ""
                    time_params: list[Any] = []
                    if from_ts is not None:
                        time_clause += " AND timestamp >= ?"
                        time_params.append(from_ts)
                    if to_ts is not None:
                        time_clause += " AND timestamp <= ?"
                        time_params.append(to_ts)

                    def _collect(query: str, params: list[Any]) -> None:
                        for row in conn.execute(query, params).fetchall():
                            ch = row["channel"]
                            if ch not in result:
                                result[ch] = []
                            # NaN-доктрина: mask sentinel / error / legacy ±inf at
                            # the read boundary — the GUI-reconnect history feed
                            # must not surface a non-physical number.
                            result[ch].append((float(row["timestamp"]), decode(float(row["value"]), row["status"])))

                    if channels:
                        # Per-channel bounded query: each channel gets its own
                        # newest-first LIMIT, so a fast channel (e.g. thermometry)
                        # can't crowd out a slow one (e.g. vacuum) — mixed sampling
                        # rates are normal. Rows are re-sorted ASC and merged below.
                        for ch in channels:
                            _collect(
                                base + time_clause + " AND channel = ? ORDER BY timestamp DESC LIMIT ?",
                                [*time_params, ch, limit_per_channel],
                            )
                    else:
                        # No channel filter: bound the total fetch as before so we
                        # never fetchall() the whole file.
                        _collect(
                            base + time_clause + " ORDER BY timestamp DESC LIMIT ?",
                            [*time_params, limit_per_channel * _HISTORY_MAX_CHANNELS],
                        )
                finally:
                    conn.close()
            except Exception:
                logger.warning("Ошибка чтения истории из %s", db_path)

        # Cold path: a window reaching before the oldest hot day would silently
        # miss days already rotated to Parquet. Union those cold rows in from the
        # archive. ArchiveReader.query already decodes (NaN-доктрина) and returns
        # the same {ch: [(ts, value)]} shape → no double-decode; the per-channel
        # limit clamp below then applies to the union (newest-first), preserving
        # the readings_history contract. Bound the cold read strictly before the
        # oldest hot day so hot days are never read twice (rotation deletes a
        # day's .db, so the archive holds only pre-oldest-hot days).
        # ponytail: cold read is unbounded per request (query has no LIMIT) —
        # bounded only by the date window; add a cold LIMIT only if a deep-history
        # request is ever shown to strain memory.
        archive_index = self._data_dir / "archive" / "index.json"
        if archive_index.exists():
            # Local import breaks the archive_reader → sqlite_writer cycle.
            from cryodaq.storage.archive_reader import ArchiveReader

            reader = ArchiveReader(self._data_dir, archive_index.parent)
            hot_days: list[date] = []
            for db_path in db_files:
                try:
                    hot_days.append(date.fromisoformat(db_path.stem.removeprefix("data_")))
                except ValueError:
                    continue
            oldest_hot = min(hot_days) if hot_days else None
            # from_ts=None means unbounded past → the request ALWAYS reaches
            # archived days, so ALWAYS union when the index exists (a bounded
            # start only reaches cold days when it predates the oldest hot day).
            from_day_req = datetime.fromtimestamp(from_ts, tz=UTC).date() if from_ts is not None else None
            if from_day_req is None or oldest_hot is None or from_day_req < oldest_hot:
                if oldest_hot is not None:
                    boundary = datetime(oldest_hot.year, oldest_hot.month, oldest_hot.day, tzinfo=UTC).timestamp()
                    cold_to = boundary - 1e-6
                    if to_ts is not None and to_ts < cold_to:
                        cold_to = to_ts
                else:
                    cold_to = to_ts if to_ts is not None else datetime.now(UTC).timestamp()
                # Lower bound: from_ts when bounded; else the earliest archived
                # day, so an unbounded request does not sweep years of empty days.
                if from_ts is not None:
                    cold_from = from_ts
                else:
                    index = reader._load_index()
                    archived_days: list[date] = []
                    for entry in index.get("files", []):
                        name = str(entry.get("original_name", ""))
                        try:
                            archived_days.append(date.fromisoformat(name.removeprefix("data_")[:10]))
                        except ValueError:
                            continue
                    if archived_days:
                        earliest = min(archived_days)
                        cold_from = datetime(earliest.year, earliest.month, earliest.day, tzinfo=UTC).timestamp()
                    else:
                        cold_from = None
                if cold_from is not None and cold_to >= cold_from:
                    cold = reader.query(
                        channels,
                        datetime.fromtimestamp(cold_from, tz=UTC),
                        datetime.fromtimestamp(cold_to, tz=UTC),
                    )
                    for ch, pts in cold.items():
                        result.setdefault(ch, []).extend(pts)

        # Sort ASC and truncate to limit_per_channel (keep latest). Rows arrive
        # newest-first and possibly interleaved across daily DB files.
        for ch in result:
            result[ch].sort(key=lambda p: p[0])
            if len(result[ch]) > limit_per_channel:
                result[ch] = result[ch][-limit_per_channel:]

        return result

    async def read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
    ) -> dict[str, list[tuple[float, float]]]:
        """Async wrapper for _read_readings_history."""
        loop = asyncio.get_running_loop()
        task = partial(
            self._read_readings_history,
            channels=channels,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_per_channel=limit_per_channel,
        )
        return await loop.run_in_executor(self._read_executor, task)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }
