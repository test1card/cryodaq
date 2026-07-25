"""Durable global ordering authority for operator snapshots.

The allocator is deliberately isolated from daily acquisition databases and
from descriptor persistence.  It grants only an ordering token and a
non-regressing backend generation timestamp; it has no publication, replay,
GUI, instrument, or control authority.

The synchronous core is intended to run off the engine event loop.  The async
facade does that explicitly and settles the executor operation before
propagating cancellation: a revision committed while its caller is cancelled
is a valid gap and is never reused.
"""

from __future__ import annotations

import asyncio
import functools
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryodaq.storage._sqlite import sqlite3

_APPLICATION_ID = 0x43515352  # ASCII "CQSR"
_SCHEMA_VERSION = 1
_MAX_REVISION = (1 << 63) - 1
_STATE_DIRECTORY = "state"
_DATABASE_NAME = "operator_snapshot_revision.db"

_CREATE_SCHEMA = """CREATE TABLE snapshot_revision (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision INTEGER NOT NULL CHECK (revision >= 0 AND revision <= 9223372036854775807),
    received_at_us INTEGER NOT NULL CHECK (received_at_us >= 0)
)"""

_EXPECTED_COLUMNS = (
    (0, "singleton", "INTEGER", 0, None, 1, 0),
    (1, "revision", "INTEGER", 1, None, 0, 0),
    (2, "received_at_us", "INTEGER", 1, None, 0, 0),
)


class OperatorSnapshotRevisionError(RuntimeError):
    """Base class for fail-closed allocator errors."""


class OperatorSnapshotRevisionBusyError(OperatorSnapshotRevisionError):
    """The allocator could not acquire its bounded SQLite write lock."""


class OperatorSnapshotRevisionCorruptError(OperatorSnapshotRevisionError):
    """The state database or its schema cannot be trusted."""


class OperatorSnapshotRevisionExhaustedError(OperatorSnapshotRevisionError):
    """The signed 63-bit revision space is exhausted."""


@dataclass(frozen=True, slots=True)
class SnapshotRevision:
    """One durably committed snapshot ordering allocation."""

    revision: int
    received_at: datetime

    def __post_init__(self) -> None:
        if type(self.revision) is not int or not 1 <= self.revision <= _MAX_REVISION:
            raise ValueError("revision must be a positive signed 63-bit integer")
        if type(self.received_at) is not datetime or self.received_at.tzinfo is None:
            raise ValueError("received_at must be an exact timezone-aware datetime")
        if self.received_at.utcoffset() != timedelta(0):
            raise ValueError("received_at must be UTC")
        received_at = self.received_at
        object.__setattr__(
            self,
            "received_at",
            datetime(
                received_at.year,
                received_at.month,
                received_at.day,
                received_at.hour,
                received_at.minute,
                received_at.second,
                received_at.microsecond,
                tzinfo=UTC,
                fold=received_at.fold,
            ),
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_epoch_us(value: datetime, *, subject: str = "allocator clock") -> int:
    if type(value) is not datetime or value.tzinfo is None:
        raise OperatorSnapshotRevisionError(f"{subject} must be an exact timezone-aware datetime")
    offset = value.utcoffset()
    if offset is None:
        raise OperatorSnapshotRevisionError(f"{subject} must be an exact timezone-aware datetime")
    if offset != timedelta(0):
        value = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value - epoch
    microseconds = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    if not 0 <= microseconds <= _MAX_REVISION:
        raise OperatorSnapshotRevisionError(f"{subject} is outside the supported UTC range")
    return microseconds


def _from_epoch_us(value: int) -> datetime:
    if type(value) is not int or not 0 <= value <= _MAX_REVISION:
        raise OperatorSnapshotRevisionCorruptError("persisted received_at is outside the supported range")
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)
    except OverflowError as exc:
        raise OperatorSnapshotRevisionCorruptError("persisted received_at is outside datetime range") from exc


async def _settle_executor_future(future: asyncio.Future[Any]) -> Any:
    """Retrieve one executor outcome before honoring caller cancellation."""

    async def wait_once() -> Any:
        if future.done():
            return future.result()
        loop = asyncio.get_running_loop()
        proxy: asyncio.Future[Any] = loop.create_future()

        def copy_result(settled: asyncio.Future[Any]) -> None:
            if proxy.cancelled():
                return
            if settled.cancelled():
                proxy.cancel()
                return
            error = settled.exception()
            if error is not None:
                proxy.set_exception(error)
            else:
                proxy.set_result(settled.result())

        future.add_done_callback(copy_result)
        try:
            return await proxy
        finally:
            future.remove_done_callback(copy_result)

    first_cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await wait_once()
        except asyncio.CancelledError as exc:
            if future.cancelled():
                raise
            if first_cancellation is None:
                first_cancellation = exc
            continue
        if first_cancellation is not None:
            raise first_cancellation
        return result


class OperatorSnapshotRevisionAllocator:
    """SQLite-backed global snapshot revision allocator.

    ``root`` is CryoDAQ's already-resolved data root, not a caller-selected DB
    filename.  The database location is always the fixed
    ``state/operator_snapshot_revision.db`` child.
    """

    def __init__(
        self,
        root: Path,
        *,
        busy_timeout_ms: int = 5_000,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(root, Path):
            raise TypeError("root must be pathlib.Path")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be an integer from 1 to 60000")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._root = root
        self._path = root / _STATE_DIRECTORY / _DATABASE_NAME
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def allocate(self, *, not_before: datetime | None = None) -> SnapshotRevision:
        """Commit and return the next ordering token synchronously."""

        not_before_us = 0 if not_before is None else _to_epoch_us(not_before, subject="not_before")
        with self._lock:
            conn = None
            transaction = False
            try:
                self._prepare_path()
                conn = sqlite3.connect(
                    str(self._path),
                    timeout=self._busy_timeout_ms / 1_000,
                    isolation_level=None,
                )
                conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("BEGIN IMMEDIATE")
                transaction = True
                self._initialize_or_verify(conn)
                row = conn.execute(
                    "SELECT revision, received_at_us FROM snapshot_revision WHERE singleton=1"
                ).fetchone()
                if row is None or len(row) != 2:
                    raise OperatorSnapshotRevisionCorruptError("snapshot revision singleton is missing")
                revision = self._exact_int(row[0], field="revision")
                previous_received_at_us = self._exact_int(row[1], field="received_at_us")
                _from_epoch_us(previous_received_at_us)
                if not 0 <= revision <= _MAX_REVISION:
                    raise OperatorSnapshotRevisionCorruptError("persisted revision is outside signed 63-bit range")
                if revision == _MAX_REVISION:
                    raise OperatorSnapshotRevisionExhaustedError("operator snapshot revision space is exhausted")

                received_at_us = max(
                    _to_epoch_us(self._clock()),
                    previous_received_at_us,
                    not_before_us,
                )
                next_revision = revision + 1
                cursor = conn.execute(
                    "UPDATE snapshot_revision SET revision=?, received_at_us=? "
                    "WHERE singleton=1 AND revision=? AND received_at_us=?",
                    (next_revision, received_at_us, revision, previous_received_at_us),
                )
                if cursor.rowcount != 1:
                    raise OperatorSnapshotRevisionCorruptError("snapshot revision singleton changed unexpectedly")
                conn.commit()
                transaction = False
                return SnapshotRevision(next_revision, _from_epoch_us(received_at_us))
            except OperatorSnapshotRevisionError:
                if conn is not None and transaction:
                    conn.rollback()
                raise
            except sqlite3.OperationalError as exc:
                if conn is not None and transaction:
                    conn.rollback()
                message = str(exc).lower()
                if "locked" in message or "busy" in message:
                    raise OperatorSnapshotRevisionBusyError("snapshot revision database is busy") from exc
                raise OperatorSnapshotRevisionError("cannot durably allocate snapshot revision") from exc
            except (OSError, sqlite3.DatabaseError) as exc:
                if conn is not None and transaction:
                    conn.rollback()
                raise OperatorSnapshotRevisionCorruptError(
                    "snapshot revision database failed integrity or access checks"
                ) from exc
            finally:
                if conn is not None:
                    conn.close()

    async def allocate_async(self, *, not_before: datetime | None = None) -> SnapshotRevision:
        """Run allocation off-loop and settle it before propagating cancellation."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, functools.partial(self.allocate, not_before=not_before))
        return await _settle_executor_future(future)

    def _prepare_path(self) -> None:
        if self._root.exists() and self._root.is_symlink():
            raise OperatorSnapshotRevisionError("CryoDAQ state root must not be a symlink")
        self._root.mkdir(parents=True, exist_ok=True)
        state_dir = self._path.parent
        if state_dir.exists() and state_dir.is_symlink():
            raise OperatorSnapshotRevisionError("CryoDAQ state directory must not be a symlink")
        state_dir.mkdir(mode=0o700, exist_ok=True)
        if self._path.is_symlink():
            raise OperatorSnapshotRevisionError("snapshot revision database must not be a symlink")
        if self._path.exists():
            mode = self._path.stat().st_mode
            if not stat.S_ISREG(mode):
                raise OperatorSnapshotRevisionError("snapshot revision database must be a regular file")

    def _initialize_or_verify(self, conn: Any) -> None:
        check = conn.execute("PRAGMA integrity_check").fetchall()
        if check != [("ok",)]:
            raise OperatorSnapshotRevisionCorruptError("snapshot revision integrity_check failed")

        objects = conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        application_id = self._exact_int(conn.execute("PRAGMA application_id").fetchone()[0], field="application_id")
        user_version = self._exact_int(conn.execute("PRAGMA user_version").fetchone()[0], field="user_version")
        if not objects and application_id == 0 and user_version == 0:
            conn.execute(_CREATE_SCHEMA)
            conn.execute("INSERT INTO snapshot_revision(singleton,revision,received_at_us) VALUES(1,0,0)")
            conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        elif application_id != _APPLICATION_ID or user_version != _SCHEMA_VERSION:
            raise OperatorSnapshotRevisionCorruptError("snapshot revision application/schema identity mismatch")

        objects = conn.execute(
            "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        if objects != [("table", "snapshot_revision")]:
            raise OperatorSnapshotRevisionCorruptError("snapshot revision schema object set mismatch")
        columns = tuple(tuple(row) for row in conn.execute("PRAGMA table_xinfo(snapshot_revision)"))
        if columns != _EXPECTED_COLUMNS:
            raise OperatorSnapshotRevisionCorruptError("snapshot revision table schema mismatch")
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='snapshot_revision'"
        ).fetchone()
        if table_sql != (_CREATE_SCHEMA,):
            raise OperatorSnapshotRevisionCorruptError("snapshot revision table definition mismatch")
        count = conn.execute("SELECT COUNT(*) FROM snapshot_revision").fetchone()
        if count != (1,):
            raise OperatorSnapshotRevisionCorruptError("snapshot revision singleton cardinality mismatch")

    @staticmethod
    def _exact_int(value: Any, *, field: str) -> int:
        if type(value) is not int:
            raise OperatorSnapshotRevisionCorruptError(f"persisted {field} is not an exact integer")
        return value


__all__ = [
    "OperatorSnapshotRevisionAllocator",
    "OperatorSnapshotRevisionBusyError",
    "OperatorSnapshotRevisionCorruptError",
    "OperatorSnapshotRevisionError",
    "OperatorSnapshotRevisionExhaustedError",
    "SnapshotRevision",
]
