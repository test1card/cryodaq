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
import stat
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote
from weakref import WeakKeyDictionary

from cryodaq.channels.descriptors import ChannelCatalog
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.operator_log import (
    OperatorLogCommitResult,
    OperatorLogEntry,
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
    normalize_operator_log_tags,
)
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

_MAX_COMMIT_REVISION = 2**63 - 1

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
    tags          TEXT    NOT NULL DEFAULT '[]',
    request_id    TEXT,
    request_fingerprint TEXT
);
"""

INDEX_OPERATOR_LOG_TS = """
CREATE INDEX IF NOT EXISTS idx_operator_log_ts ON operator_log (timestamp);
"""

INDEX_OPERATOR_LOG_EXPERIMENT = """
CREATE INDEX IF NOT EXISTS idx_operator_log_experiment ON operator_log (experiment_id, timestamp);
"""

INDEX_OPERATOR_LOG_REQUEST_ID = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_log_request_id
ON operator_log (request_id) WHERE request_id IS NOT NULL;
"""

SCHEMA_ALARM_ACK_OUTBOX = """
CREATE TABLE IF NOT EXISTS alarm_ack_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    alarm_name TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('intent', 'committed', 'published')),
    event_json TEXT,
    receipt_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""
SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX = """
CREATE TABLE IF NOT EXISTS operator_log_publication_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('intent', 'published')),
    event_json TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

_OPERATOR_LOG_LEGACY_COLUMNS = (
    (0, "id", "INTEGER", 0, None, 1),
    (1, "timestamp", "REAL", 1, None, 0),
    (2, "experiment_id", "TEXT", 0, None, 0),
    (3, "author", "TEXT", 1, "''", 0),
    (4, "source", "TEXT", 1, "''", 0),
    (5, "message", "TEXT", 1, None, 0),
    (6, "tags", "TEXT", 1, "'[]'", 0),
)
_OPERATOR_LOG_CURRENT_COLUMNS = (
    *_OPERATOR_LOG_LEGACY_COLUMNS,
    (7, "request_id", "TEXT", 0, None, 0),
    (8, "request_fingerprint", "TEXT", 0, None, 0),
)
_OPERATOR_LOG_REGISTRY_DEADLINE_S = 10.0
_OPERATOR_LOG_MAX_DIRECTORY_ENTRIES = 100_000
_OPERATOR_LOG_MAX_HOT_DATABASES = 10_000
_OPERATOR_LOG_MAX_KEYED_ROWS = 10_000


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
# A no-filter request is one aggregate trust-boundary query, not 64 implicit
# per-channel requests.  Keep one hard cap across every daily file so the
# caller cannot multiply the materialised row count by days on disk.
_HISTORY_MAX_TOTAL_ROWS = 100_000
_HISTORY_COLD_MAX_RETAINED_BYTES = 32 * 1024 * 1024
_HISTORY_COLD_MIN_RETAINED_BYTES = 64 * 1024
_HISTORY_COLD_DEADLINE_S = 10.0
_HISTORY_COLD_CHUNK = timedelta(hours=168)

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
    commit_revision: int
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
        commit_revision: int,
        owner_key: object,
        integrity_token: object,
    ) -> CommittedBatchReceipt:
        issued = object.__new__(cls)
        object.__setattr__(issued, "entries", entries)
        object.__setattr__(issued, "commit_revision", commit_revision)
        object.__setattr__(issued, "_owner_key", owner_key)
        object.__setattr__(issued, "_provenance", _COMMIT_RECEIPT_PROVENANCE)
        object.__setattr__(issued, "_integrity_token", integrity_token)
        return issued

    @property
    def grants_control_authority(self) -> bool:
        return False


class CommittedBatchSettlement:
    """Operation-scoped owner for a descriptor commit and its terminal receipt."""

    __slots__ = ("_owner",)

    def __init__(self) -> None:
        self._owner: asyncio.Task[CommittedBatchReceipt | None] | None = None

    def bind(self, owner: asyncio.Task[CommittedBatchReceipt | None]) -> None:
        if self._owner is not None:
            raise RuntimeError("commit settlement ticket is already bound")
        self._owner = owner

    async def wait(self) -> CommittedBatchReceipt | None:
        owner = self._owner
        if owner is None:
            raise RuntimeError("commit settlement ticket is not bound")
        return await asyncio.shield(owner)


@dataclass(frozen=True, slots=True)
class _CommitReceiptIntegrity:
    entries: tuple[CommittedReadingReceipt, ...]
    entry_values: tuple[tuple[str, str, int, bytes, DescriptorBoundReading], ...]
    commit_revision: int
    token: object


@dataclass(frozen=True, slots=True)
class _PersistedOperatorLogRequest:
    """Persistence-private registry row; never serialized to operator clients."""

    storage_day: date
    entry: OperatorLogEntry
    request_id: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class AlarmAckOutboxRecord:
    request_id: str
    request_fingerprint: str
    alarm_name: str
    activation_id: str
    operator_name: str
    reason: str
    state: str
    event: dict[str, Any] | None
    receipt: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class OperatorLogPublicationOutboxRecord:
    request_id: str
    request_fingerprint: str
    state: str
    event: dict[str, Any]
    receipt: dict[str, Any]


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
        self._descriptor_catalog_installed = False
        self._descriptor_connection_guard: tuple[int, int, int] | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_written: int = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
        # Every executor operation is owned independently of its caller. A REP
        # timeout/cancellation may abandon only the waiter; these retained owners
        # remain authoritative until the worker and its side effects settle.
        self._owned_write_tasks: set[asyncio.Task[Any]] = set()
        self._owned_read_tasks: set[asyncio.Task[Any]] = set()
        self._pending_callback_futures: set[ConcurrentFuture[Any]] = set()
        self._pending_write_futures: set[asyncio.Future[Any]] = set()
        self._pending_read_futures: set[asyncio.Future[Any]] = set()
        self._stopping = False
        self._stop_owner: asyncio.Task[None] | None = None
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
        self._commit_revision = 0
        self._issued_commits: WeakKeyDictionary[CommittedBatchReceipt, _CommitReceiptIntegrity] = WeakKeyDictionary()
        # Durable operator-log idempotency is a retained-data property, not an
        # in-memory receipt cache. Startup explicitly builds this bounded
        # registry before keyed writes are enabled. Slice B extends the same
        # builder with indexed cold-v2 rows; normal appends never rescan cold
        # storage.
        self._operator_log_idempotency_registry: dict[str, _PersistedOperatorLogRequest] | None = None
        # Each abandoned commit has one explicit operation-scoped ticket. The
        # bound is checked before admission; no receipt can be evicted to make
        # room for a later operation.
        self._commit_settlement_capacity = 1024
        self._retained_commit_settlements: set[CommittedBatchSettlement] = set()
        self._settled_commit_receipts: list[CommittedBatchReceipt] = []

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

    def _control_db_path(self) -> Path:
        return self._data_dir / "control.db"

    def _open_control_db(self) -> sqlite3.Connection:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._control_db_path()), timeout=10, check_same_thread=False)
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
            if (mode[0] if mode else "").lower() != "wal":
                raise RuntimeError("alarm ACK outbox requires SQLite WAL")
            conn.execute("PRAGMA synchronous=FULL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute(SCHEMA_ALARM_ACK_OUTBOX)
            conn.execute(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX)
            conn.commit()
            return conn
        except Exception:
            conn.close()
            raise

    @staticmethod
    def _alarm_ack_record(row: tuple[object, ...]) -> AlarmAckOutboxRecord:
        event = None if row[7] is None else json.loads(str(row[7]))
        receipt = None if row[8] is None else json.loads(str(row[8]))
        return AlarmAckOutboxRecord(
            request_id=str(row[0]),
            request_fingerprint=str(row[1]),
            alarm_name=str(row[2]),
            activation_id=str(row[3]),
            operator_name=str(row[4]),
            reason=str(row[5]),
            state=str(row[6]),
            event=event,
            receipt=receipt,
        )

    def _prepare_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        operator_name: str,
        reason: str,
    ) -> AlarmAckOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        values = (request_id, request_fingerprint, alarm_name, activation_id, operator_name, reason)
        conn = self._open_control_db()
        try:
            now = time.time()
            conn.execute(
                "INSERT OR IGNORE INTO alarm_ack_outbox "
                "(request_id, request_fingerprint, alarm_name, activation_id, operator_name, "
                "reason, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'intent', ?, ?)",
                (*values, now, now),
            )
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "operator_name, reason, state, event_json, receipt_json "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("alarm ACK outbox intent disappeared")
            record = self._alarm_ack_record(row)
            if record.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            conn.commit()
            return record
        finally:
            conn.close()

    @staticmethod
    def _operator_log_publication_record(row: tuple[object, ...]) -> OperatorLogPublicationOutboxRecord:
        return OperatorLogPublicationOutboxRecord(
            request_id=str(row[0]),
            request_fingerprint=str(row[1]),
            state=str(row[2]),
            event=dict(json.loads(str(row[3]))),
            receipt=dict(json.loads(str(row[4]))),
        )

    def _prepare_operator_log_publication_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> OperatorLogPublicationOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        event_json = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        conn = self._open_control_db()
        try:
            now = time.time()
            conn.execute(
                "INSERT OR IGNORE INTO operator_log_publication_outbox "
                "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
                "VALUES (?, ?, 'intent', ?, ?, ?, ?)",
                (request_id, request_fingerprint, event_json, receipt_json, now, now),
            )
            row = conn.execute(
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("operator-log publication intent disappeared")
            current = self._operator_log_publication_record(row)
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError(
                    "operator-log publication request_id was reused with different content"
                )
            if current.event != event or current.receipt != receipt:
                raise RuntimeError("operator-log publication payload changed")
            conn.commit()
            return current
        finally:
            conn.close()

    async def prepare_operator_log_publication_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> OperatorLogPublicationOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._prepare_operator_log_publication_outbox_sync,
            request_id,
            request_fingerprint,
            event,
            receipt,
            read=False,
            name="sqlite_operator_log_publication_prepare",
        )
        return await asyncio.shield(owner)

    def _publish_operator_log_publication_outbox_sync(
        self, request_id: str, request_fingerprint: str
    ) -> OperatorLogPublicationOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        conn = self._open_control_db()
        try:
            row = conn.execute(
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("operator-log publication intent is missing")
            current = self._operator_log_publication_record(row)
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError(
                    "operator-log publication request_id was reused with different content"
                )
            if current.state == "published":
                return current
            conn.execute(
                "UPDATE operator_log_publication_outbox SET state = 'published', updated_at = ? "
                "WHERE request_id = ? AND request_fingerprint = ?",
                (time.time(), request_id, request_fingerprint),
            )
            conn.commit()
            row = conn.execute(
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("operator-log publication receipt disappeared")
            return self._operator_log_publication_record(row)
        finally:
            conn.close()

    async def publish_operator_log_publication_outbox(
        self, *, request_id: str, request_fingerprint: str
    ) -> OperatorLogPublicationOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._publish_operator_log_publication_outbox_sync,
            request_id,
            request_fingerprint,
            read=False,
            name="sqlite_operator_log_publication_publish",
        )
        return await asyncio.shield(owner)

    async def prepare_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        operator_name: str,
        reason: str,
    ) -> AlarmAckOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._prepare_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            alarm_name,
            activation_id,
            operator_name,
            reason,
            read=False,
            name="sqlite_alarm_ack_outbox_prepare",
        )
        return await asyncio.shield(owner)

    def _commit_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        event_json = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        conn = self._open_control_db()
        try:
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "operator_name, reason, state, event_json, receipt_json "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("alarm ACK outbox intent is missing")
            current = self._alarm_ack_record(row)
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            if current.state == "published":
                return current
            if current.state == "committed":
                if current.event != event or current.receipt != receipt:
                    raise RuntimeError("alarm ACK outbox committed payload changed")
                return current
            now = time.time()
            conn.execute(
                "UPDATE alarm_ack_outbox SET state = 'committed', event_json = ?, receipt_json = ?, updated_at = ? "
                "WHERE request_id = ? AND request_fingerprint = ? AND state = 'intent'",
                (event_json, receipt_json, now, request_id, request_fingerprint),
            )
            conn.commit()
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "operator_name, reason, state, event_json, receipt_json "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("alarm ACK outbox commit disappeared")
            return self._alarm_ack_record(row)
        finally:
            conn.close()

    async def commit_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._commit_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            event,
            receipt,
            read=False,
            name="sqlite_alarm_ack_outbox_commit",
        )
        return await asyncio.shield(owner)

    def _publish_alarm_ack_outbox_sync(self, request_id: str, request_fingerprint: str) -> AlarmAckOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        conn = self._open_control_db()
        try:
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "operator_name, reason, state, event_json, receipt_json "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("alarm ACK outbox receipt is missing")
            current = self._alarm_ack_record(row)
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            if current.state == "intent":
                raise RuntimeError("alarm ACK event cannot publish before state commit")
            if current.state == "published":
                return current
            conn.execute(
                "UPDATE alarm_ack_outbox SET state = 'published', updated_at = ? "
                "WHERE request_id = ? AND request_fingerprint = ?",
                (time.time(), request_id, request_fingerprint),
            )
            conn.commit()
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "operator_name, reason, state, event_json, receipt_json "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("alarm ACK outbox publication disappeared")
            return self._alarm_ack_record(row)
        finally:
            conn.close()

    async def publish_alarm_ack_outbox(self, *, request_id: str, request_fingerprint: str) -> AlarmAckOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._publish_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            read=False,
            name="sqlite_alarm_ack_outbox_publish",
        )
        return await asyncio.shield(owner)

    def _db_path(self, day: date) -> Path:
        return self._data_dir / f"data_{day.isoformat()}.db"

    @staticmethod
    def _operator_log_columns(conn: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (int(row[0]), str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
            for row in conn.execute("PRAGMA main.table_info(operator_log)")
        )

    @staticmethod
    def _normalized_schema_sql(value: object) -> str:
        if type(value) is not str:
            return ""
        return " ".join(value.strip().rstrip(";").split()).casefold()

    @classmethod
    def _verify_operator_log_storage(cls, conn: sqlite3.Connection) -> None:
        if cls._operator_log_columns(conn) != _OPERATOR_LOG_CURRENT_COLUMNS:
            raise RuntimeError("operator_log schema is not the exact current schema")
        index_rows = conn.execute("PRAGMA main.index_list(operator_log)").fetchall()
        matching = [row for row in index_rows if row[1] == "idx_operator_log_request_id"]
        if len(matching) != 1 or int(matching[0][2]) != 1 or int(matching[0][4]) != 1:
            raise RuntimeError("operator_log request-id index is missing or not unique/partial")
        index_info = conn.execute("PRAGMA main.index_info(idx_operator_log_request_id)").fetchall()
        if [(int(row[0]), int(row[1]), row[2]) for row in index_info] != [(0, 7, "request_id")]:
            raise RuntimeError("operator_log request-id index targets unexpected columns")
        stored = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_operator_log_request_id'"
        ).fetchone()
        actual_sql = cls._normalized_schema_sql(None if stored is None else stored[0])
        expected_sql = cls._normalized_schema_sql(INDEX_OPERATOR_LOG_REQUEST_ID)
        expected_without_guard = expected_sql.replace(" if not exists", "")
        if actual_sql not in {expected_sql, expected_without_guard}:
            raise RuntimeError("operator_log request-id index predicate is not exact")

    @classmethod
    def _ensure_operator_log_storage_in_transaction(cls, conn: sqlite3.Connection) -> None:
        columns = cls._operator_log_columns(conn)
        if not columns:
            conn.execute(SCHEMA_OPERATOR_LOG)
        elif columns == _OPERATOR_LOG_LEGACY_COLUMNS:
            conn.execute("ALTER TABLE operator_log ADD COLUMN request_id TEXT")
            conn.execute("ALTER TABLE operator_log ADD COLUMN request_fingerprint TEXT")
        elif columns != _OPERATOR_LOG_CURRENT_COLUMNS:
            raise RuntimeError("operator_log schema migration refused an unknown or partial schema")
        conn.execute(INDEX_OPERATOR_LOG_TS)
        conn.execute(INDEX_OPERATOR_LOG_EXPERIMENT)
        conn.execute(INDEX_OPERATOR_LOG_REQUEST_ID)
        cls._verify_operator_log_storage(conn)

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

    def _remember_owned_task(self, task: asyncio.Task[Any], collection: set[asyncio.Task[Any]]) -> asyncio.Task[Any]:
        collection.add(task)
        task.add_done_callback(collection.discard)
        return task

    async def _run_owned_executor(
        self,
        executor: ThreadPoolExecutor,
        function: Callable[..., Any],
        *args: Any,
        pending: set[asyncio.Future[Any]],
    ) -> Any:
        if self._stopping:
            raise RuntimeError("SQLiteWriter is stopping; new persistence work is rejected")
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(executor, function, *args)
        pending.add(operation)
        operation.add_done_callback(pending.discard)
        caller_cancelled: asyncio.CancelledError | None = None
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
            except BaseException:
                break
        try:
            result = operation.result()
        except BaseException as operation_error:
            if caller_cancelled is not None:
                raise caller_cancelled from operation_error
            raise
        if caller_cancelled is not None:
            raise caller_cancelled
        return result

    async def _commit_owner(self, readings: list[Reading]) -> CommittedBatchReceipt | None:
        bound = await self._run_owned_executor(
            self._executor,
            self._write_live_batch,
            readings,
            pending=self._pending_write_futures,
        )
        if bound is None:
            return None
        return self._issue_committed_batch(bound)

    def begin_committed(self, readings: list[Reading]) -> CommittedBatchSettlement:
        """Admit one commit only when its settlement proof has capacity."""
        if self._live_channel_catalog is None:
            raise RuntimeError("write_committed() requires a live descriptor catalog owner")
        if self._stopping:
            raise RuntimeError("SQLiteWriter is stopping; new persistence work is rejected")
        if len(self._retained_commit_settlements) >= self._commit_settlement_capacity:
            raise RuntimeError("commit settlement capacity exhausted; admission refused")
        settlement = CommittedBatchSettlement()
        owner = self._remember_owned_task(
            asyncio.create_task(self._commit_owner(readings), name="sqlite_write_committed"),
            self._owned_write_tasks,
        )
        settlement.bind(owner)
        self._retained_commit_settlements.add(settlement)
        return settlement

    async def settle_committed(self, settlement: CommittedBatchSettlement) -> CommittedBatchReceipt | None:
        """Settle and release exactly the admitted operation named by settlement."""
        if settlement not in self._retained_commit_settlements:
            raise RuntimeError("unknown or already settled commit ticket")
        try:
            return await settlement.wait()
        finally:
            self._retained_commit_settlements.discard(settlement)

    def release_committed(self, settlement: CommittedBatchSettlement) -> None:
        """Release a normally completed operation-scoped ticket."""
        if settlement not in self._retained_commit_settlements:
            raise RuntimeError("unknown or already released commit ticket")
        self._retained_commit_settlements.remove(settlement)

    def take_retained_commit_receipts(self) -> tuple[CommittedBatchReceipt, ...]:
        """Compatibility snapshot of terminal receipts; never drains proof."""
        return tuple(self._settled_commit_receipts)

    def _owned_executor_task(
        self,
        executor: ThreadPoolExecutor,
        function: Callable[..., Any],
        *args: Any,
        read: bool,
        name: str,
    ) -> asyncio.Task[Any]:
        collection = self._owned_read_tasks if read else self._owned_write_tasks
        pending = self._pending_read_futures if read else self._pending_write_futures
        task = asyncio.create_task(
            self._run_owned_executor(executor, function, *args, pending=pending),
            name=name,
        )
        return self._remember_owned_task(task, collection)

    async def _settle_owned_tasks(self, collection: set[asyncio.Task[Any]]) -> None:
        while True:
            pending = tuple(task for task in collection if not task.done())
            if not pending:
                return
            drain = asyncio.gather(*pending, return_exceptions=True)
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                continue

    async def _settle_callback_futures(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            pending = tuple(future for future in self._pending_callback_futures if not future.done())
            if not pending:
                return
            drain = asyncio.gather(
                *(asyncio.wrap_future(future, loop=loop) for future in pending),
                return_exceptions=True,
            )
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                continue

    @staticmethod
    def _forget_callback_future(future: ConcurrentFuture[Any], owner: SQLiteWriter) -> None:
        owner._pending_callback_futures.discard(future)

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
            self._pending_callback_futures.add(future)
            future.add_done_callback(partial(self._forget_callback_future, owner=self))
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
            self._descriptor_catalog_installed = False
            self._descriptor_connection_guard = None
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
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(SCHEMA_READINGS)
            conn.execute(SCHEMA_SOURCE_DATA)
            conn.execute(INDEX_READINGS_TS)
            conn.execute(INDEX_SOURCE_DATA_TS)
            conn.execute(INDEX_CHANNEL_TS)
            self._ensure_operator_log_storage_in_transaction(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        try:
            initialize_descriptor_storage(conn)
        except Exception:
            conn.close()
            raise
        self._descriptor_catalog_installed = False
        # Do not trust a baseline sampled outside the receipted write lock.
        # The first batch must run the full descriptor verification after
        # BEGIN IMMEDIATE, then publish its pre-commit guard sample.
        self._descriptor_connection_guard = None
        self._conn = conn
        self._current_date = day
        logger.info("Открыта БД: %s", db_path)
        return conn

    @staticmethod
    def _descriptor_guard_state(conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Return cheap change detectors for one descriptor-authoritative DB."""

        main_schema = conn.execute("PRAGMA main.schema_version").fetchone()
        temp_schema = conn.execute("PRAGMA temp.schema_version").fetchone()
        data_version = conn.execute("PRAGMA main.data_version").fetchone()
        if any(row is None or type(row[0]) is not int for row in (main_schema, temp_schema, data_version)):
            raise RuntimeError("SQLite descriptor guard PRAGMA returned an invalid value")
        return main_schema[0], temp_schema[0], data_version[0]

    def _verify_descriptor_write_boundary(self, conn: sqlite3.Connection) -> None:
        """Escalate to a full verification only after observable DB change.

        Normal acquisition batches pay three constant-time PRAGMA reads. A
        schema/temp-schema change or an external connection commit triggers the
        complete descriptor/FK verification before the next write. This keeps
        the trigger, temporary-shadow and external-tamper defenses without
        scanning the entire descriptor/readings history for every poll.
        """

        if self._channel_catalog is None:
            return
        current = self._descriptor_guard_state(conn)
        if current == self._descriptor_connection_guard:
            return
        verify_descriptor_storage(conn)
        self._descriptor_connection_guard = self._descriptor_guard_state(conn)

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

        Every input is bound and validated before persistence. A batch crossing
        UTC midnight is then split into ordered, single-day transactions. One
        receipt covering the original batch is issued only after every daily
        transaction commits; ``None`` means a disk-full/locked failure left no
        publication authority (even if an earlier day already committed).
        """

        owner = self._live_channel_catalog
        if owner is None:
            raise RuntimeError("descriptor-authoritative commit requires a live catalog owner")
        if not batch:
            raise ValueError("descriptor-authoritative commit requires a non-empty batch")

        bound = tuple(owner.bind(reading) for reading in batch)
        by_day: dict[date, list[Reading]] = {}
        for item in bound:
            reading = item.reading
            nonfinite = not math.isfinite(reading.value)
            if nonfinite and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains non-finite OK reading")
            if not nonfinite and is_sentinel(reading.value) and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains sentinel OK reading")
            stable = replace(reading, channel=item.descriptor.channel_id)
            timestamp = (
                reading.timestamp.astimezone(UTC)
                if reading.timestamp.tzinfo is not None
                else reading.timestamp.replace(tzinfo=UTC)
            )
            by_day.setdefault(timestamp.date(), []).append(stable)

        for day, stable_readings in sorted(by_day.items()):
            if not self._write_day_batch(self._ensure_connection(day), stable_readings):
                return None
        return bound

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
        if self._commit_revision >= _MAX_COMMIT_REVISION:
            raise OverflowError("committed batch receipt revision exhausted after SQLite commit")
        entries = tuple(CommittedReadingReceipt._issue(item) for item in bound)
        commit_revision = self._commit_revision + 1
        token = object()
        receipt = CommittedBatchReceipt._issue(
            entries,
            commit_revision=commit_revision,
            owner_key=self._commit_owner_key,
            integrity_token=token,
        )
        self._issued_commits[receipt] = _CommitReceiptIntegrity(
            entries=entries,
            entry_values=tuple(self._receipt_entry_value(entry) for entry in entries),
            commit_revision=commit_revision,
            token=token,
        )
        self._commit_revision = commit_revision
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
                and candidate.commit_revision == integrity.commit_revision
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

    def entries_from_commit(self, receipt: object) -> tuple[CommittedReadingReceipt, ...]:
        """Return the verified receipt entries (reading + descriptor envelope).

        F35 D4: same ownership/integrity verification as ``readings_from_commit``,
        but keeps ``channel_id``/``descriptor_hash``/``descriptor_revision``/
        ``descriptor_envelope`` alongside each reading instead of discarding them.
        Purely additive — ``readings_from_commit`` is untouched and still used
        wherever bare readings suffice.
        """

        if not self.owns_commit(receipt):
            raise TypeError("commit receipt is foreign, forged, or mutated")
        assert isinstance(receipt, CommittedBatchReceipt)
        return receipt.entries

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
        catalog_was_installed = self._descriptor_catalog_installed
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Verify after acquiring the writer lock. An external connection
            # must not be able to install a trigger or corrupt FK data between
            # this guard and the receipted INSERT below.
            self._verify_descriptor_write_boundary(conn)
            if self._channel_catalog is not None and not catalog_was_installed:
                # Install once per daily connection, in the same transaction as
                # its first readings. A failed first write therefore cannot
                # leave catalog authority behind without any persisted sample.
                install_catalog(conn, self._channel_catalog, within_transaction=True)
            conn.executemany(
                "INSERT INTO main.readings "
                "(timestamp, instrument_id, channel, value, unit, status, descriptor_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                rows,
            )
            descriptor_guard_after_write = (
                self._descriptor_guard_state(conn) if self._channel_catalog is not None else None
            )
            conn.commit()
            if self._channel_catalog is not None:
                self._descriptor_catalog_installed = True
                # Publish only the baseline sampled while BEGIN IMMEDIATE still
                # excluded external writers. A commit landing immediately after
                # ours must remain observable as a change on the next batch.
                assert descriptor_guard_after_write is not None
                self._descriptor_connection_guard = descriptor_guard_after_write
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
        request_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> OperatorLogEntry:
        if (request_id is None) != (request_fingerprint is None):
            raise ValueError("operator-log private request fields must be supplied together")
        if request_id is not None:
            self._validate_operator_log_request(request_id, request_fingerprint)
        day = timestamp.date()
        conn = self._ensure_connection(day)
        if request_id is not None:
            self._verify_operator_log_storage(conn)
        try:
            cursor = conn.execute(
                "INSERT INTO operator_log "
                "(timestamp, experiment_id, author, source, message, tags, request_id, request_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    timestamp.timestamp(),
                    experiment_id,
                    author,
                    source,
                    message,
                    json.dumps(list(tags), ensure_ascii=False),
                    request_id,
                    request_fingerprint,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return OperatorLogEntry(
            id=int(cursor.lastrowid),
            timestamp=timestamp,
            experiment_id=experiment_id,
            author=author,
            source=source,
            message=message,
            tags=tags,
        )

    @staticmethod
    def _validate_operator_log_request(request_id: object, request_fingerprint: object) -> None:
        if (
            type(request_id) is not str
            or len(request_id) != 32
            or any(char not in "0123456789abcdef" for char in request_id)
        ):
            raise ValueError("request_id must be exactly 32 lowercase hexadecimal characters")
        if (
            type(request_fingerprint) is not str
            or len(request_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in request_fingerprint)
        ):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 hexadecimal digest")

    @staticmethod
    def _operator_log_path_identity(path: Path) -> tuple[int, int, int, int]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("operator-log source is not a regular file")
        if getattr(info, "st_nlink", 1) != 1:
            raise OSError("operator-log source has multiple links")
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_nlink)

    def _bounded_operator_log_hot_paths(self, deadline_monotonic: float) -> tuple[tuple[date, Path], ...]:
        if not self._data_dir.exists():
            return ()
        paths: list[tuple[date, Path]] = []
        visited = 0
        try:
            with os.scandir(self._data_dir) as entries:
                for item in entries:
                    visited += 1
                    if visited > _OPERATOR_LOG_MAX_DIRECTORY_ENTRIES:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log hot directory exceeds the bounded entry cap"
                        )
                    if time.monotonic() >= deadline_monotonic:
                        raise OperatorLogIdempotencyUnavailableError("operator-log hot registry deadline expired")
                    name = item.name
                    if len(name) != 18 or not name.startswith("data_") or not name.endswith(".db"):
                        continue
                    try:
                        day = date.fromisoformat(name[5:15])
                    except ValueError:
                        continue
                    if name != f"data_{day.isoformat()}.db":
                        continue
                    path = Path(item.path)
                    self._operator_log_path_identity(path)
                    paths.append((day, path))
                    if len(paths) > _OPERATOR_LOG_MAX_HOT_DATABASES:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log hot database count exceeds the bounded cap"
                        )
        except OperatorLogIdempotencyUnavailableError:
            raise
        except Exception as exc:
            raise OperatorLogIdempotencyUnavailableError("operator-log hot registry enumeration failed") from exc
        return tuple(sorted(paths, key=lambda item: item[0]))

    def _read_hot_operator_log_registry(
        self,
        deadline_monotonic: float,
    ) -> dict[str, _PersistedOperatorLogRequest]:
        registry: dict[str, _PersistedOperatorLogRequest] = {}
        for storage_day, path in self._bounded_operator_log_hot_paths(deadline_monotonic):
            identity = self._operator_log_path_identity(path)
            uri = f"file:{quote(str(path), safe='/')}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.25, isolation_level=None)
            expired = [False]
            try:
                if not hasattr(conn, "setlimit") or not hasattr(sqlite3, "SQLITE_LIMIT_LENGTH"):
                    raise RuntimeError("SQLite allocation limits unavailable")
                conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_048_576)
                conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65_536)

                def interrupt_on_deadline() -> int:
                    if time.monotonic() >= deadline_monotonic:
                        expired[0] = True
                        return 1
                    return 0

                conn.set_progress_handler(interrupt_on_deadline, 2_000)
                conn.execute("PRAGMA query_only=ON").close()
                conn.execute("PRAGMA busy_timeout=250").close()
                columns = self._operator_log_columns(conn)
                if not columns:
                    continue
                if columns == _OPERATOR_LOG_LEGACY_COLUMNS:
                    continue
                self._verify_operator_log_storage(conn)
                cursor = conn.execute(
                    "SELECT id, timestamp, experiment_id, author, source, message, tags, "
                    "request_id, request_fingerprint FROM operator_log "
                    "INDEXED BY idx_operator_log_request_id WHERE request_id IS NOT NULL "
                    "ORDER BY request_id LIMIT ?",
                    (_OPERATOR_LOG_MAX_KEYED_ROWS + 1,),
                )
                try:
                    rows = cursor.fetchall()
                finally:
                    cursor.close()
                if len(rows) > _OPERATOR_LOG_MAX_KEYED_ROWS:
                    raise RuntimeError("operator-log keyed row count exceeds the bounded cap")
                for row in rows:
                    (
                        row_id,
                        raw_timestamp,
                        experiment_id,
                        author,
                        source,
                        message,
                        raw_tags,
                        request_id,
                        fingerprint,
                    ) = row
                    self._validate_operator_log_request(request_id, fingerprint)
                    if type(row_id) is not int or row_id <= 0:
                        raise ValueError("operator-log row id is invalid")
                    if experiment_id is not None and type(experiment_id) is not str:
                        raise ValueError("operator-log experiment id is invalid")
                    if any(type(value) is not str for value in (author, source, message, raw_tags)):
                        raise ValueError("operator-log text field is invalid")
                    decoded_tags = json.loads(raw_tags)
                    if type(decoded_tags) is not list or any(type(value) is not str for value in decoded_tags):
                        raise ValueError("operator-log tags are invalid")
                    entry = OperatorLogEntry(
                        id=row_id,
                        timestamp=_parse_timestamp(raw_timestamp),
                        experiment_id=experiment_id,
                        author=author,
                        source=source,
                        message=message,
                        tags=tuple(decoded_tags),
                    )
                    if request_id in registry:
                        raise RuntimeError("operator-log request id is ambiguous across retained hot databases")
                    registry[request_id] = _PersistedOperatorLogRequest(
                        storage_day=storage_day,
                        entry=entry,
                        request_id=request_id,
                        request_fingerprint=fingerprint,
                    )
                    if len(registry) > _OPERATOR_LOG_MAX_KEYED_ROWS:
                        raise RuntimeError("operator-log keyed row count exceeds the bounded cap")
            except Exception as exc:
                reason = (
                    "operator-log hot registry deadline expired"
                    if expired[0]
                    else "operator-log hot registry is invalid"
                )
                raise OperatorLogIdempotencyUnavailableError(reason) from exc
            finally:
                conn.close()
            if self._operator_log_path_identity(path) != identity:
                raise OperatorLogIdempotencyUnavailableError("operator-log hot source identity changed")
        self._read_cold_operator_log_registry(deadline_monotonic, registry)
        if time.monotonic() >= deadline_monotonic:
            raise OperatorLogIdempotencyUnavailableError("operator-log hot registry deadline expired")
        return registry

    def _read_cold_operator_log_registry(
        self,
        deadline_monotonic: float,
        registry: dict[str, _PersistedOperatorLogRequest],
    ) -> None:
        """Load keyed identity only from verified, contained cold-v2 sidecars."""
        index_path = self._data_dir / "archive" / "index.json"
        if not index_path.is_file():
            return
        try:
            archive_root = index_path.parent.resolve(strict=True)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            entries = index.get("files", [])
            if type(entries) is not list or len(entries) > _OPERATOR_LOG_MAX_HOT_DATABASES:
                raise ValueError("cold operator-log index is invalid or unbounded")
            import pyarrow.parquet as pq  # noqa: PLC0415
        except ImportError as exc:
            raise OperatorLogIdempotencyUnavailableError("cold operator-log identity requires pyarrow") from exc
        except Exception as exc:
            raise OperatorLogIdempotencyUnavailableError("cold operator-log index is invalid") from exc

        for indexed in entries:
            if time.monotonic() >= deadline_monotonic:
                raise OperatorLogIdempotencyUnavailableError("operator-log cold registry deadline expired")
            if indexed.get("operator_log_schema") != "operator_log_v2":
                continue
            relative = indexed.get("operator_log_path")
            if type(relative) is not str or not relative:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path is invalid")
            path = (archive_root / relative).resolve(strict=True)
            try:
                path.relative_to(archive_root)
            except ValueError as exc:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path escapes archive root") from exc
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_nlink", 1) != 1
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log sidecar is not stable")
            if indexed.get("operator_log_size_bytes") != info.st_size:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log size proof mismatch")
            if self._md5_hex(path) != indexed.get("operator_log_checksum_md5"):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log checksum proof mismatch")
            table = pq.read_table(
                str(path),
                columns=[
                    "timestamp",
                    "experiment_id",
                    "author",
                    "source",
                    "message",
                    "tags",
                    "request_id",
                    "request_fingerprint",
                    "row_id",
                ],
            )
            if table.num_rows > _OPERATOR_LOG_MAX_KEYED_ROWS:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log keyed row count exceeds cap")
            for row in table.to_pylist():
                request_id = row["request_id"]
                fingerprint = row["request_fingerprint"]
                self._validate_operator_log_request(request_id, fingerprint)
                row_id = row["row_id"]
                if type(row_id) is not int or row_id <= 0:
                    raise ValueError("cold operator-log row id is invalid")
                tags = json.loads(str(row["tags"]))
                if type(tags) is not list or any(type(value) is not str for value in tags):
                    raise ValueError("cold operator-log tags are invalid")
                values = (row["author"], row["source"], row["message"])
                if any(type(value) is not str for value in values):
                    raise ValueError("cold operator-log text field is invalid")
                original_name = indexed.get("original_name")
                if (
                    type(original_name) is not str
                    or len(original_name) != 18
                    or not original_name.startswith("data_")
                    or not original_name.endswith(".db")
                ):
                    raise ValueError("cold operator-log source day is invalid")
                storage_day = date.fromisoformat(original_name[5:15])
                entry = OperatorLogEntry(
                    id=row_id,
                    timestamp=_parse_timestamp(row["timestamp"]),
                    experiment_id=row["experiment_id"],
                    author=row["author"],
                    source=row["source"],
                    message=row["message"],
                    tags=tuple(tags),
                )
                if request_id in registry:
                    raise OperatorLogIdempotencyUnavailableError(
                        "operator-log request id is ambiguous across retained storage"
                    )
                registry[request_id] = _PersistedOperatorLogRequest(
                    storage_day=storage_day,
                    entry=entry,
                    request_id=request_id,
                    request_fingerprint=fingerprint,
                )
                if len(registry) > _OPERATOR_LOG_MAX_KEYED_ROWS:
                    raise OperatorLogIdempotencyUnavailableError("operator-log keyed row count exceeds the bounded cap")

    def _initialize_operator_log_idempotency_sync(self, deadline_monotonic: float) -> None:
        try:
            registry = self._read_hot_operator_log_registry(deadline_monotonic)
        except Exception:
            self._operator_log_idempotency_registry = None
            raise
        self._operator_log_idempotency_registry = registry

    async def initialize_operator_log_idempotency(self) -> None:
        """Build the bounded retained-data registry before accepting keyed writes."""

        deadline = time.monotonic() + _OPERATOR_LOG_REGISTRY_DEADLINE_S
        owner = self._owned_executor_task(
            self._executor,
            self._initialize_operator_log_idempotency_sync,
            deadline,
            read=False,
            name="sqlite_operator_log_registry_init",
        )
        await asyncio.shield(owner)

    def _resolve_operator_log_request_sync(
        self,
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult | None:
        self._validate_operator_log_request(request_id, request_fingerprint)
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log deduplication registry is not initialized")
        persisted = registry.get(request_id)
        if persisted is None:
            return None
        if persisted.request_fingerprint != request_fingerprint:
            raise OperatorLogIdempotencyConflictError("request_id was already committed with different content")
        return OperatorLogCommitResult(entry=persisted.entry, replayed=True)

    async def find_operator_log_request(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult | None:
        """Resolve one key from the proven registry without touching disk."""

        owner = self._owned_executor_task(
            self._executor,
            self._resolve_operator_log_request_sync,
            request_id,
            request_fingerprint,
            read=False,
            name="sqlite_operator_log_lookup",
        )
        return await asyncio.shield(owner)

    def _append_operator_log_idempotent_sync(
        self,
        *,
        message: str,
        author: str,
        source: str,
        experiment_id: str | None,
        tags: tuple[str, ...],
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult:
        resolved = self._resolve_operator_log_request_sync(request_id, request_fingerprint)
        if resolved is not None:
            return resolved
        entry_time = datetime.now(UTC)
        try:
            entry = self._write_operator_log_entry(
                timestamp=entry_time,
                experiment_id=experiment_id,
                author=author,
                source=source,
                message=message,
                tags=tags,
                request_id=request_id,
                request_fingerprint=request_fingerprint,
            )
        except sqlite3.IntegrityError as exc:
            # A collision not represented in the proven registry means its
            # authority changed underneath us. Do not guess whether it is a
            # replay; disable keyed writes until a fresh bounded rebuild.
            self._operator_log_idempotency_registry = None
            raise OperatorLogIdempotencyUnavailableError("operator-log request registry changed during append") from exc
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log request registry became unavailable")
        registry[request_id] = _PersistedOperatorLogRequest(
            storage_day=entry_time.date(),
            entry=entry,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        return OperatorLogCommitResult(entry=entry, replayed=False)

    async def append_operator_log_idempotent(
        self,
        *,
        message: str,
        request_id: str,
        request_fingerprint: str,
        author: str = "",
        source: str = "command",
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> OperatorLogCommitResult:
        """Append once using server-owned time, or return the original row."""

        text = message.strip()
        if not text:
            raise ValueError("Operator log message must not be empty.")
        self._validate_operator_log_request(request_id, request_fingerprint)
        normalized_tags = normalize_operator_log_tags(tags)
        task = partial(
            self._append_operator_log_idempotent_sync,
            message=text,
            author=author.strip(),
            source=source.strip() or "command",
            experiment_id=experiment_id,
            tags=normalized_tags,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        owner = self._owned_executor_task(
            self._executor,
            task,
            read=False,
            name="sqlite_operator_log_idempotent_append",
        )
        return await asyncio.shield(owner)

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
                # This is a read path over historical databases. Older files
                # legitimately predate operator_log; probing sqlite_master is
                # observational, while CREATE TABLE here would mutate them.
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'operator_log'"
                ).fetchone()
                if exists is None:
                    continue
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
                    await self._run_owned_executor(
                        executor,
                        self._write_batch,
                        batch,
                        pending=self._pending_write_futures,
                    )
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
        owner = self._owned_executor_task(
            self._executor,
            self._write_batch,
            readings,
            read=False,
            name="sqlite_write_immediate",
        )
        try:
            return await asyncio.shield(owner)
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
        settlement = self.begin_committed(readings)
        try:
            bound = await settlement.wait()
        except asyncio.CancelledError:
            # The owner continues through the transaction and post-commit
            # receipt boundary; cancellation never creates a late write after
            # a caller or shutdown waiter has been told it is settled.
            raise
        except Exception:
            self._retained_commit_settlements.discard(settlement)
            logger.critical(
                "CRITICAL: descriptor-authoritative commit failed (%d readings) — no receipt issued",
                len(readings),
            )
            raise
        assert isinstance(bound, CommittedBatchReceipt) or bound is None
        self._retained_commit_settlements.discard(settlement)
        return bound

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
        task = partial(
            self._write_operator_log_entry,
            timestamp=entry_time,
            experiment_id=experiment_id,
            author=author.strip(),
            source=source.strip() or "command",
            message=text,
            tags=normalized_tags,
        )
        owner = self._owned_executor_task(
            self._executor,
            task,
            read=False,
            name="sqlite_append_operator_log",
        )
        return await asyncio.shield(owner)

    async def get_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
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
        owner = self._owned_executor_task(
            self._read_executor,
            task,
            read=True,
            name="sqlite_operator_log_read",
        )
        return await asyncio.shield(owner)

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

    async def _stop_impl(self) -> None:
        """Settle every retained owner before closing SQLite or executors."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Caller cancellation never detaches a write, read, or callback owner.
        # A stopped receipt is impossible until all retained work is terminal.
        for settlement in tuple(self._retained_commit_settlements):
            try:
                receipt = await settlement.wait()
                if receipt is not None:
                    self._settled_commit_receipts.append(receipt)
            except BaseException:
                logger.exception("retained SQLite commit settlement failed during stop")
            finally:
                self._retained_commit_settlements.discard(settlement)
        await self._settle_owned_tasks(self._owned_write_tasks)
        await self._settle_owned_tasks(self._owned_read_tasks)
        await self._settle_callback_futures()
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
        if self._read_executor is not None:
            await asyncio.to_thread(self._read_executor.shutdown, wait=True)
        if self._conn:
            self._conn.close()
            self._conn = None
            self._descriptor_catalog_installed = False
            self._descriptor_connection_guard = None
        logger.info("SQLiteWriter stopped (written: %d)", self._total_written)

    async def stop(self) -> None:
        """Retain one shutdown owner and never report stopped early."""
        if self._stop_owner is None:
            self._stopping = True
            self._stop_owner = asyncio.create_task(self._stop_impl(), name="sqlite_writer_stop")
        owner = self._stop_owner
        caller_cancelled: asyncio.CancelledError | None = None
        while not owner.done():
            try:
                await asyncio.shield(owner)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
        try:
            owner.result()
        except BaseException as error:
            if caller_cancelled is not None:
                raise caller_cancelled from error
            raise
        if caller_cancelled is not None:
            raise caller_cancelled

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
            # One requested channel consumes one bounded query budget. Preserve
            # caller order while preventing duplicate names from multiplying
            # work across every retained daily file.
            channels = list(dict.fromkeys(channels))[:_HISTORY_MAX_CHANNELS]
        hot_deficits = {channel: limit_per_channel for channel in channels} if channels else None
        unfiltered_limit = min(
            limit_per_channel * _HISTORY_MAX_CHANNELS,
            _HISTORY_MAX_TOTAL_ROWS,
        )
        unfiltered_remaining = unfiltered_limit

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

        # Newest files satisfy the retained tail first. Older files are opened
        # only while a requested channel (or the aggregate no-filter budget)
        # still has a deficit.
        for db_path in reversed(selected_dbs):
            if channels:
                assert hot_deficits is not None
                if not any(hot_deficits.values()):
                    break
            elif unfiltered_remaining <= 0:
                break
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

                    def _collect(query: str, params: list[Any]) -> int:
                        pending: list[tuple[str, float, float]] = []
                        for row in conn.execute(query, params):
                            ch = row["channel"]
                            # NaN-доктрина: mask sentinel / error / legacy ±inf at
                            # the read boundary — the GUI-reconnect history feed
                            # must not surface a non-physical number.
                            pending.append(
                                (
                                    ch,
                                    float(row["timestamp"]),
                                    decode(float(row["value"]), row["status"]),
                                )
                            )
                        # Keep each bounded file/channel query atomic. A malformed
                        # later row must not retain a partial prefix without also
                        # consuming its deficit, which could multiply memory by
                        # the number of retained daily files.
                        for ch, timestamp, value in pending:
                            result.setdefault(ch, []).append((timestamp, value))
                        return len(pending)

                    if channels:
                        # Per-channel bounded query: each channel gets its own
                        # newest-first LIMIT, so a fast channel (e.g. thermometry)
                        # can't crowd out a slow one (e.g. vacuum) — mixed sampling
                        # rates are normal. Spend each budget across files rather
                        # than once per file; rows are re-sorted ASC below.
                        assert hot_deficits is not None
                        for ch in channels:
                            remaining = hot_deficits[ch]
                            if remaining <= 0:
                                continue
                            collected = _collect(
                                base + time_clause + " AND channel = ? ORDER BY timestamp DESC LIMIT ?",
                                [*time_params, ch, remaining],
                            )
                            hot_deficits[ch] -= collected
                    else:
                        # No channel filter: spend one aggregate budget across
                        # daily files, newest first. A separate LIMIT per file
                        # would let retained history multiply this bound.
                        collected = _collect(
                            base + time_clause + " ORDER BY timestamp DESC LIMIT ?",
                            [*time_params, unfiltered_remaining],
                        )
                        unfiltered_remaining -= collected
                finally:
                    conn.close()
            except Exception:
                logger.warning("Ошибка чтения истории из %s", db_path)

        # Cold path: a window reaching before the oldest hot day would silently
        # miss days already rotated to Parquet. Union those cold rows through
        # ArchiveReader's hard-bounded API. Process at most seven days per call,
        # newest first, under one row/byte/deadline budget for the whole request.
        # The cold end is strictly before the oldest hot day so an ordinary
        # rotation cannot make the hot and cold paths read the same source.
        archive_index = self._data_dir / "archive" / "index.json"
        cold_needed = any(hot_deficits.values()) if channels and hot_deficits is not None else unfiltered_remaining > 0
        if archive_index.exists() and cold_needed:
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
                cold_deadline = time.monotonic() + _HISTORY_COLD_DEADLINE_S
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
                    try:
                        if time.monotonic() >= cold_deadline:
                            raise TimeoutError("cold history deadline expired before index read")
                        index = reader._read_bounded_index(archive_index)
                        if not isinstance(index, dict) or set(index) != {"files"}:
                            raise ValueError("invalid bounded archive index schema")
                        entries = index["files"]
                        if not isinstance(entries, list) or len(entries) > 100_000:
                            raise ValueError("invalid bounded archive index entries")
                        archived_days: list[date] = []
                        for entry in entries:
                            if not isinstance(entry, dict):
                                raise ValueError("invalid bounded archive index entry")
                            name = entry.get("original_name")
                            if (
                                not isinstance(name, str)
                                or len(name) != 18
                                or not name.startswith("data_")
                                or not name.endswith(".db")
                            ):
                                raise ValueError("invalid bounded archive original_name")
                            archived_day = date.fromisoformat(name[5:15])
                            if name != f"data_{archived_day.isoformat()}.db":
                                raise ValueError("non-canonical bounded archive original_name")
                            archived_days.append(archived_day)
                        if time.monotonic() >= cold_deadline:
                            raise TimeoutError("cold history deadline expired during index read")
                    except Exception:
                        logger.warning("Bounded cold history index read failed", exc_info=True)
                        cold_from = None
                    else:
                        if archived_days:
                            earliest = min(archived_days)
                            cold_from = datetime(
                                earliest.year,
                                earliest.month,
                                earliest.day,
                                tzinfo=UTC,
                            ).timestamp()
                        else:
                            cold_from = None
                if cold_from is not None and cold_to >= cold_from:
                    deficits = (
                        {
                            channel: limit_per_channel - len(result.get(channel, ()))
                            for channel in channels
                            if len(result.get(channel, ())) < limit_per_channel
                        }
                        if channels
                        else None
                    )
                    cold_rows_remaining = min(
                        sum(deficits.values()) if deficits is not None else unfiltered_remaining,
                        _HISTORY_MAX_TOTAL_ROWS,
                    )
                    cold_bytes_remaining = _HISTORY_COLD_MAX_RETAINED_BYTES
                    cold_start = datetime.fromtimestamp(cold_from, tz=UTC)
                    cold_end = datetime.fromtimestamp(cold_to, tz=UTC) + timedelta(microseconds=1)
                    deadline = cold_deadline
                    stop_cold = False
                    while (
                        cold_rows_remaining > 0
                        and cold_bytes_remaining >= _HISTORY_COLD_MIN_RETAINED_BYTES
                        and cold_start < cold_end
                    ):
                        if time.monotonic() >= deadline:
                            logger.warning("Cold history read stopped at its bounded deadline")
                            break
                        chunk_start = max(cold_start, cold_end - _HISTORY_COLD_CHUNK)
                        query_channels = list(deficits) if deficits is not None else [None]
                        for channel in query_channels:
                            if cold_rows_remaining <= 0:
                                break
                            if cold_bytes_remaining < _HISTORY_COLD_MIN_RETAINED_BYTES:
                                stop_cold = True
                                break
                            if deficits is not None:
                                deficit = deficits.get(channel, 0)
                                if deficit <= 0:
                                    continue
                                row_cap = min(deficit, cold_rows_remaining)
                                selected_channels: list[str] | None = [str(channel)]
                            else:
                                deficit = cold_rows_remaining
                                row_cap = cold_rows_remaining
                                selected_channels = None
                            query_total = max(2, row_cap)
                            try:
                                bounded = reader.query_reading_rows_bounded(
                                    start=chunk_start,
                                    end=cold_end,
                                    channels=selected_channels,
                                    max_channels=_HISTORY_MAX_CHANNELS,
                                    max_points_per_channel=query_total,
                                    max_total_points=query_total,
                                    max_retained_bytes=cold_bytes_remaining,
                                    deadline_monotonic=deadline,
                                )
                            except Exception:
                                logger.warning("Bounded cold history read failed", exc_info=True)
                                stop_cold = True
                                break

                            retained_bytes = bounded.retained_encoded_bytes
                            if (
                                type(retained_bytes) is not int
                                or retained_bytes < 0
                                or retained_bytes > cold_bytes_remaining
                            ):
                                logger.warning("Bounded cold history returned an invalid byte count")
                                stop_cold = True
                                break
                            cold_bytes_remaining -= retained_bytes
                            accepted = bounded.rows[-row_cap:]
                            for row in accepted:
                                value = float("nan") if row.value is None else row.value
                                result.setdefault(row.channel, []).append((row.timestamp, value))
                            cold_rows_remaining -= len(accepted)
                            if deficits is not None:
                                assert channel is not None
                                deficits[channel] = max(0, deficit - len(accepted))
                            if not bounded.complete or (bounded.truncated and len(accepted) < row_cap):
                                logger.warning(
                                    "Cold history read returned partial bounded evidence "
                                    "(complete=%s, truncated=%s, issues=%d)",
                                    bounded.complete,
                                    bounded.truncated,
                                    len(bounded.issues) + bounded.issue_overflow,
                                )
                                stop_cold = True
                                break
                        if stop_cold:
                            break
                        cold_end = chunk_start

        if not channels:
            # The cold reader has its own date/source bounds but returns a
            # channel mapping. Re-apply the same absolute newest-row cap to the
            # hot+cold union so the public result cannot exceed the trust
            # boundary even when the archive contributes the remaining rows.
            newest = sorted(
                ((timestamp, channel, value) for channel, points in result.items() for timestamp, value in points),
                key=lambda item: item[0],
                reverse=True,
            )[:unfiltered_limit]
            result = {}
            for timestamp, channel, value in newest:
                result.setdefault(channel, []).append((timestamp, value))

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
        task = partial(
            self._read_readings_history,
            channels=channels,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_per_channel=limit_per_channel,
        )
        owner = self._owned_executor_task(
            self._read_executor,
            task,
            read=True,
            name="sqlite_readings_history",
        )
        return await asyncio.shield(owner)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }
