"""Durable FIFO acceptance spool for persistence-first reading batches.

This module owns only the local acceptance journal.  It deliberately has no
destination-database or broker dependency: later integration must keep
``SQLiteWriter`` as the single authority that appends here, materializes daily
SQLite rows, and acknowledges envelopes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryodaq.storage._sqlite import sqlite3

_APPLICATION_ID = 0x43515350  # ASCII "CQSP"
_SCHEMA_VERSION = 2
_ENVELOPE_SCHEMA = "cryodaq.persistence-envelope"
_MAX_TEXT_BYTES = 4096
_MAX_RECENT_REJECTIONS = 128
_RECEIPT_TOKEN = object()


class PersistenceSpoolError(RuntimeError):
    """Base class for spool integrity and contract failures."""


class PersistenceSpoolCorruptError(PersistenceSpoolError):
    """The spool cannot be trusted or does not match the supported schema."""


class PersistenceSpoolCollisionError(PersistenceSpoolError):
    """A stable UUID was reused for non-equivalent data."""


class PersistenceOutcome(Enum):
    """Typed persistence result; accidental boolean authorization is forbidden."""

    MATERIALIZED = "materialized"
    DURABLY_QUEUED = "durably_queued"
    REJECTED = "rejected"

    def __bool__(self) -> bool:
        raise TypeError("PersistenceOutcome must be compared explicitly")


def _canonical_digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """Opaque proof used for cooperative in-process capability confinement.

    This resists accidental misuse and cross-wiring.  It is not a security
    boundary against code with arbitrary introspection in the same interpreter.
    """

    batch_uuid: str
    envelope_hash: str
    issuer_id: str
    proof: bytes

    def __post_init__(self) -> None:
        _canonical_uuid(self.batch_uuid)
        _canonical_digest(self.envelope_hash, field="receipt envelope_hash")
        _canonical_uuid(self.issuer_id)
        if not isinstance(self.proof, bytes) or len(self.proof) != hashlib.sha256().digest_size:
            raise ValueError("receipt proof must be one SHA-256 digest")


class MaterializationReceiptIssuer:
    """Narrow capability retained by the future single destination writer."""

    __slots__ = ("__issuer_id", "__secret")

    def __init__(self, token: object, *, issuer_id: str, secret: bytes) -> None:
        if token is not _RECEIPT_TOKEN:
            raise TypeError("receipt issuers are created only as a bound channel")
        self.__issuer_id = issuer_id
        self.__secret = secret

    def issue(self, envelope: NormalizedBatchEnvelope) -> MaterializationReceipt:
        """Issue proof after the destination atomically materializes this envelope."""

        if not isinstance(envelope, NormalizedBatchEnvelope):
            raise TypeError("receipt requires NormalizedBatchEnvelope")
        message = _receipt_message(self.__issuer_id, envelope.batch_uuid, envelope.payload_hash)
        return MaterializationReceipt(
            batch_uuid=envelope.batch_uuid,
            envelope_hash=envelope.payload_hash,
            issuer_id=self.__issuer_id,
            proof=hmac.digest(self.__secret, message, "sha256"),
        )


class MaterializationReceiptVerifier:
    """Spool-side half of one destination receipt capability."""

    __slots__ = ("__issuer_id", "__secret")

    def __init__(self, token: object, *, issuer_id: str, secret: bytes) -> None:
        if token is not _RECEIPT_TOKEN:
            raise TypeError("receipt verifiers are created only as a bound channel")
        self.__issuer_id = issuer_id
        self.__secret = secret

    def verify(self, receipt: MaterializationReceipt, *, batch_uuid: str, envelope_hash: str) -> None:
        if not isinstance(receipt, MaterializationReceipt):
            raise PersistenceSpoolError("acknowledgement requires a materialization receipt")
        if receipt.batch_uuid != batch_uuid or receipt.envelope_hash != envelope_hash:
            raise PersistenceSpoolError("materialization receipt does not match oldest pending envelope")
        if receipt.issuer_id != self.__issuer_id:
            raise PersistenceSpoolError("materialization receipt issuer is not bound to this spool")
        expected = hmac.digest(
            self.__secret,
            _receipt_message(receipt.issuer_id, receipt.batch_uuid, receipt.envelope_hash),
            "sha256",
        )
        if not hmac.compare_digest(receipt.proof, expected):
            raise PersistenceSpoolError("materialization receipt proof is invalid")


def create_materialization_receipt_channel() -> tuple[
    MaterializationReceiptIssuer,
    MaterializationReceiptVerifier,
]:
    """Create one cooperative issuer/verifier pair for future integration wiring.

    The future single ``SQLiteWriter`` owner retains the issuer privately.  This
    narrows normal call paths but is not a hostile-code security boundary inside
    one Python interpreter.
    """

    issuer_id = str(uuid4())
    secret = secrets.token_bytes(32)
    return (
        MaterializationReceiptIssuer(_RECEIPT_TOKEN, issuer_id=issuer_id, secret=secret),
        MaterializationReceiptVerifier(_RECEIPT_TOKEN, issuer_id=issuer_id, secret=secret),
    )


def _receipt_message(issuer_id: str, batch_uuid: str, envelope_hash: str) -> bytes:
    return f"{issuer_id}\0{batch_uuid}\0{envelope_hash}".encode("ascii")


async def _await_executor_settlement(future: asyncio.Future[Any]) -> Any:
    """Settle one executor future before honoring cooperative task cancellation.

    A cancellable proxy prevents task cancellation from reaching the executor
    future.  Durable lifecycle methods remember every caller cancellation, keep
    awaiting the same future, retrieve its result or exception, let worker
    failure dominate, and only then propagate the first cancellation.
    """

    def retrieve_exception(settled: asyncio.Future[Any]) -> None:
        if settled.cancelled():
            return
        try:
            settled.exception()
        except BaseException:
            pass

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
            exception = settled.exception()
            if exception is not None:
                proxy.set_exception(exception)
            else:
                proxy.set_result(settled.result())

        future.add_done_callback(copy_result)
        try:
            return await proxy
        finally:
            future.remove_done_callback(copy_result)

    # Explicit retrieval prevents a worker exception from becoming an
    # unobserved event-loop exception while cancellation settlement is pending.
    future.add_done_callback(retrieve_exception)
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


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("UUID must be canonical lowercase text") from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("UUID must be canonical lowercase text")
    return canonical


def _bounded_text(value: str, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if not allow_empty and not value:
        raise ValueError(f"{field} must not be empty")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} exceeds {_MAX_TEXT_BYTES} UTF-8 bytes")
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("envelope contains non-canonical data") from exc
    return text.encode("ascii")


@dataclass(frozen=True, slots=True)
class CalibrationGrouping:
    """Non-executable metadata preserving one KRDG/SRDG acquisition group."""

    group_id: str
    krdg_rows: int
    srdg_rows: int
    acquisition_id: str | None = None
    pending_t_min: float | None = None
    pending_t_max: float | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.group_id, field="calibration group_id")
        if self.acquisition_id is not None:
            _bounded_text(self.acquisition_id, field="calibration acquisition_id")
        if type(self.krdg_rows) is not int or self.krdg_rows < 0:
            raise ValueError("krdg_rows must be a non-negative integer")
        if type(self.srdg_rows) is not int or self.srdg_rows < 0:
            raise ValueError("srdg_rows must be a non-negative integer")
        for name in ("pending_t_min", "pending_t_max"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
            ):
                raise ValueError(f"{name} must be finite when present")
        if (
            self.pending_t_min is not None
            and self.pending_t_max is not None
            and self.pending_t_min > self.pending_t_max
        ):
            raise ValueError("pending_t_min must not exceed pending_t_max")

    def canonical_value(self) -> dict[str, str | int | float | None]:
        return {
            "acquisition_id": self.acquisition_id,
            "group_id": self.group_id,
            "krdg_rows": self.krdg_rows,
            "pending_t_max": self.pending_t_max,
            "pending_t_min": self.pending_t_min,
            "srdg_rows": self.srdg_rows,
        }


@dataclass(frozen=True, slots=True)
class NormalizedSpoolRow:
    """One immutable, destination-ready reading row with stable identity."""

    ingest_uuid: str
    timestamp: float
    utc_day: date
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: str

    def __post_init__(self) -> None:
        _canonical_uuid(self.ingest_uuid)
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, (int, float)):
            raise TypeError("timestamp must be a finite Unix timestamp")
        if not math.isfinite(float(self.timestamp)):
            raise ValueError("timestamp must be finite")
        expected_day = datetime.fromtimestamp(float(self.timestamp), tz=UTC).date()
        if self.utc_day != expected_day:
            raise ValueError("utc_day must match timestamp in UTC")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be a finite stored number")
        if not math.isfinite(float(self.value)):
            raise ValueError("value must already be normalized to a finite stored number")
        _bounded_text(self.instrument_id, field="instrument_id")
        _bounded_text(self.channel, field="channel")
        _bounded_text(self.unit, field="unit", allow_empty=True)
        _bounded_text(self.status, field="status")

    @classmethod
    def create(
        cls,
        *,
        timestamp: datetime,
        instrument_id: str,
        channel: str,
        value: float,
        unit: str,
        status: str,
        ingest_uuid: str | None = None,
    ) -> NormalizedSpoolRow:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        normalized = timestamp.astimezone(UTC)
        return cls(
            ingest_uuid=ingest_uuid or str(uuid4()),
            timestamp=normalized.timestamp(),
            utc_day=normalized.date(),
            instrument_id=instrument_id,
            channel=channel,
            value=value,
            unit=unit,
            status=status,
        )

    def canonical_value(self) -> dict[str, str | float]:
        return {
            "channel": self.channel,
            "ingest_uuid": self.ingest_uuid,
            "instrument_id": self.instrument_id,
            "status": self.status,
            "timestamp": float(self.timestamp),
            "unit": self.unit,
            "utc_day": self.utc_day.isoformat(),
            "value": float(self.value),
        }

    @property
    def payload_bytes(self) -> bytes:
        return _canonical_json(self.canonical_value())

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(self.payload_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedBatchEnvelope:
    """Immutable ordered batch accepted by the durable spool."""

    batch_uuid: str
    created_at: float
    rows: tuple[NormalizedSpoolRow, ...]
    calibration: CalibrationGrouping | None = None
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        _canonical_uuid(self.batch_uuid)
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"unsupported envelope schema version: {self.schema_version}")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise TypeError("created_at must be a finite Unix timestamp")
        if not math.isfinite(float(self.created_at)):
            raise ValueError("created_at must be finite")
        if not self.rows:
            raise ValueError("envelope must contain at least one row")
        if not isinstance(self.rows, tuple):
            raise TypeError("rows must be an immutable tuple")
        if any(not isinstance(row, NormalizedSpoolRow) for row in self.rows):
            raise TypeError("rows must contain only NormalizedSpoolRow values")
        row_ids = [row.ingest_uuid for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("envelope contains duplicate ingest UUIDs")
        if self.calibration is not None:
            grouped = self.calibration.krdg_rows + self.calibration.srdg_rows
            if grouped != len(self.rows):
                raise ValueError("calibration row counts must cover the exact envelope")

    @classmethod
    def create(
        cls,
        rows: Iterable[NormalizedSpoolRow],
        *,
        batch_uuid: str | None = None,
        created_at: datetime | None = None,
        calibration: CalibrationGrouping | None = None,
    ) -> NormalizedBatchEnvelope:
        instant = created_at or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return cls(
            batch_uuid=batch_uuid or str(uuid4()),
            created_at=instant.astimezone(UTC).timestamp(),
            rows=tuple(rows),
            calibration=calibration,
        )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "batch_uuid": self.batch_uuid,
            "calibration": self.calibration.canonical_value() if self.calibration else None,
            "created_at": float(self.created_at),
            "rows": [row.canonical_value() for row in self.rows],
            "schema": _ENVELOPE_SCHEMA,
            "schema_version": self.schema_version,
        }

    @property
    def payload_bytes(self) -> bytes:
        return _canonical_json(self.canonical_value())

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(self.payload_bytes).hexdigest()

    @property
    def utc_days(self) -> frozenset[date]:
        return frozenset(row.utc_day for row in self.rows)


@dataclass(frozen=True, slots=True)
class SpoolLimits:
    """Independent logical and physical capacity policy."""

    max_bytes: int = 64 * 1024 * 1024
    max_rows: int = 250_000
    max_batches: int = 10_000
    max_database_bytes: int = 128 * 1024 * 1024
    transaction_reserve_bytes: int = 256 * 1024
    max_oldest_age_s: float = 24 * 60 * 60
    high_water_fraction: float = 0.8

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_rows",
            "max_batches",
            "max_database_bytes",
            "transaction_reserve_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_database_bytes <= self.transaction_reserve_bytes:
            raise ValueError("max_database_bytes must exceed transaction_reserve_bytes")
        if not math.isfinite(self.max_oldest_age_s) or self.max_oldest_age_s <= 0:
            raise ValueError("max_oldest_age_s must be positive and finite")
        if not math.isfinite(self.high_water_fraction) or not 0 < self.high_water_fraction < 1:
            raise ValueError("high_water_fraction must be between zero and one")


@dataclass(frozen=True, slots=True)
class SpoolHealth:
    pending_batches: int
    pending_rows: int
    pending_bytes: int
    oldest_age_s: float
    high_water: bool
    rejected_batches: int
    rejected_rows: int
    retry_count: int
    last_error: str | None
    database_bytes: int
    database_limit_bytes: int
    database_headroom_bytes: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS spool_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    rejected_batches INTEGER NOT NULL DEFAULT 0 CHECK (rejected_batches >= 0),
    rejected_rows INTEGER NOT NULL DEFAULT 0 CHECK (rejected_rows >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS spool_batches (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_uuid TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    state TEXT NOT NULL CHECK (state = 'pending'),
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    payload_size INTEGER NOT NULL CHECK (payload_size > 0),
    envelope_hash TEXT NOT NULL,
    calibration_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS spool_rejections (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_uuid TEXT NOT NULL UNIQUE,
    envelope_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spool_rows (
    batch_uuid TEXT NOT NULL REFERENCES spool_batches(batch_uuid) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    ingest_uuid TEXT NOT NULL UNIQUE,
    utc_day TEXT NOT NULL,
    timestamp REAL NOT NULL,
    instrument_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (batch_uuid, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_spool_batches_fifo ON spool_batches(state, sequence);
CREATE INDEX IF NOT EXISTS idx_spool_rows_day ON spool_rows(utc_day, batch_uuid);
INSERT OR IGNORE INTO spool_meta(singleton) VALUES (1);
"""

_EXPECTED_TABLES = frozenset({"spool_meta", "spool_batches", "spool_rejections", "spool_rows"})
_EXPECTED_INDEXES = frozenset({"idx_spool_batches_fifo", "idx_spool_rows_day"})
_EXPECTED_COLUMNS = {
    "spool_meta": (
        "singleton",
        "rejected_batches",
        "rejected_rows",
        "retry_count",
        "last_error",
    ),
    "spool_batches": (
        "sequence",
        "batch_uuid",
        "schema_version",
        "created_at",
        "state",
        "row_count",
        "payload_size",
        "envelope_hash",
        "calibration_json",
        "error",
    ),
    "spool_rows": (
        "batch_uuid",
        "ordinal",
        "ingest_uuid",
        "utc_day",
        "timestamp",
        "instrument_id",
        "channel",
        "value",
        "unit",
        "status",
        "payload_json",
        "payload_hash",
    ),
    "spool_rejections": (
        "sequence",
        "batch_uuid",
        "envelope_hash",
        "row_count",
        "reason",
    ),
}


class PersistenceSpool:
    """Thread-safe durable FIFO for immutable normalized envelopes."""

    def __init__(
        self,
        path: Path,
        *,
        limits: SpoolLimits | None = None,
        receipt_verifier: MaterializationReceiptVerifier | None = None,
    ) -> None:
        self._path = Path(path)
        self._limits = limits or SpoolLimits()
        if receipt_verifier is not None and not isinstance(
            receipt_verifier,
            MaterializationReceiptVerifier,
        ):
            raise TypeError("receipt_verifier must be MaterializationReceiptVerifier")
        self.__receipt_verifier = receipt_verifier
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._before_commit_hook: Callable[[], None] | None = None
        probe = sqlite3.connect(":memory:")
        try:
            self._validate_preopen_physical_limits(int(probe.execute("PRAGMA page_size").fetchone()[0]))
        finally:
            probe.close()
        self.open()

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> PersistenceSpool:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            existed = self._path.exists() and self._path.stat().st_size > 0
            try:
                conn = sqlite3.connect(str(self._path), timeout=10, check_same_thread=False)
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("PRAGMA foreign_keys=ON")
                check = conn.execute("PRAGMA quick_check").fetchall()
                if check != [("ok",)]:
                    raise PersistenceSpoolCorruptError(f"spool quick_check failed: {check!r}")
                application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
                user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if existed and (application_id != _APPLICATION_ID or user_version != _SCHEMA_VERSION):
                    raise PersistenceSpoolCorruptError("spool application/schema identity mismatch")
                if not existed:
                    conn.executescript(_SCHEMA)
                    conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                    conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                    conn.commit()
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if tables != _EXPECTED_TABLES:
                    raise PersistenceSpoolCorruptError(
                        f"spool table set mismatch: expected {sorted(_EXPECTED_TABLES)!r}, got {sorted(tables)!r}"
                    )
                for table, expected_columns in _EXPECTED_COLUMNS.items():
                    actual_columns = tuple(str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})"))
                    if actual_columns != expected_columns:
                        raise PersistenceSpoolCorruptError(
                            f"spool schema mismatch for {table}: expected {expected_columns!r}, got {actual_columns!r}"
                        )
                indexes = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if indexes != _EXPECTED_INDEXES:
                    raise PersistenceSpoolCorruptError(
                        f"spool index set mismatch: expected {sorted(_EXPECTED_INDEXES)!r}, got {sorted(indexes)!r}"
                    )
                unexpected_objects = conn.execute(
                    "SELECT type,name FROM sqlite_master WHERE type IN ('trigger','view') ORDER BY type,name"
                ).fetchall()
                if unexpected_objects:
                    raise PersistenceSpoolCorruptError(
                        f"spool contains unexpected schema objects: {unexpected_objects!r}"
                    )
                self._verify_semantic_schema(conn)
                self._validate_open_physical_limits(conn, include_wal_headroom=True)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA wal_autocheckpoint=1")
                self._validate_open_physical_limits(conn)
                self._verify_all_integrity(conn)
                self._conn = conn
            except PersistenceSpoolError:
                if "conn" in locals():
                    conn.close()
                raise
            except Exception as exc:
                if "conn" in locals():
                    conn.close()
                raise PersistenceSpoolCorruptError(f"cannot open persistence spool: {exc}") from exc

    def close(self) -> None:
        """Close synchronously after all durable executor calls have settled."""

        with self._lock:
            if self._conn is None:
                return
            self._conn.close()
            self._conn = None

    async def close_durable(self) -> None:
        """Close off-loop, safely waiting for any operation that owns the lock."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self.close)
        await _await_executor_settlement(future)

    def verify_integrity(self) -> None:
        with self._lock:
            conn = self._connection()
            check = conn.execute("PRAGMA quick_check").fetchall()
            if check != [("ok",)]:
                raise PersistenceSpoolCorruptError(f"spool quick_check failed: {check!r}")
            try:
                self._verify_semantic_schema(conn)
                self._verify_all_integrity(conn)
            except PersistenceSpoolCorruptError:
                raise
            except Exception as exc:
                raise PersistenceSpoolCorruptError(f"spool semantic integrity failed: {exc}") from exc

    def append(self, envelope: NormalizedBatchEnvelope) -> PersistenceOutcome:
        """Durably append one exact envelope or reject it without eviction."""

        if not isinstance(envelope, NormalizedBatchEnvelope):
            raise TypeError("append requires NormalizedBatchEnvelope")
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT state, envelope_hash FROM spool_batches WHERE batch_uuid=?",
                    (envelope.batch_uuid,),
                ).fetchone()
                if existing is not None:
                    if str(existing[1]) != envelope.payload_hash:
                        raise PersistenceSpoolCollisionError(f"batch UUID collision: {envelope.batch_uuid}")
                    outcome = self._outcome_for_state(str(existing[0]))
                    conn.commit()
                    return outcome

                rejection = conn.execute(
                    "SELECT envelope_hash FROM spool_rejections WHERE batch_uuid=?",
                    (envelope.batch_uuid,),
                ).fetchone()
                if rejection is not None:
                    if str(rejection[0]) != envelope.payload_hash:
                        raise PersistenceSpoolCollisionError(f"rejected batch UUID collision: {envelope.batch_uuid}")
                    conn.commit()
                    return PersistenceOutcome.REJECTED

                self._reject_ingest_collisions(conn, envelope)
                reason = self._hard_limit_reason(conn, envelope)
                if reason is not None:
                    self._record_rejection(conn, envelope, reason)
                    self._commit(conn)
                    self._checkpoint_reuse(conn)
                    actual_bytes = self._database_bytes()
                    if actual_bytes > self._limits.max_database_bytes:
                        raise PersistenceSpoolError(
                            "spool physical cap invariant failed after bounded rejection: "
                            f"{actual_bytes} > {self._limits.max_database_bytes}"
                        )
                    return PersistenceOutcome.REJECTED

                calibration_json = (
                    _canonical_json(envelope.calibration.canonical_value()).decode("ascii")
                    if envelope.calibration
                    else None
                )
                conn.execute(
                    "INSERT INTO spool_batches(batch_uuid,schema_version,created_at,state,row_count,"
                    "payload_size,envelope_hash,calibration_json,error) VALUES (?,?,?,?,?,?,?,?,NULL)",
                    (
                        envelope.batch_uuid,
                        envelope.schema_version,
                        envelope.created_at,
                        "pending",
                        len(envelope.rows),
                        len(envelope.payload_bytes),
                        envelope.payload_hash,
                        calibration_json,
                    ),
                )
                for ordinal, row in enumerate(envelope.rows):
                    conn.execute(
                        "INSERT INTO spool_rows(batch_uuid,ordinal,ingest_uuid,utc_day,timestamp,"
                        "instrument_id,channel,value,unit,status,payload_json,payload_hash) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            envelope.batch_uuid,
                            ordinal,
                            row.ingest_uuid,
                            row.utc_day.isoformat(),
                            row.timestamp,
                            row.instrument_id,
                            row.channel,
                            row.value,
                            row.unit,
                            row.status,
                            row.payload_bytes.decode("ascii"),
                            row.payload_hash,
                        ),
                    )
                self._commit(conn)
                self._checkpoint_reuse(conn)
                actual_bytes = self._database_bytes()
                if actual_bytes > self._limits.max_database_bytes:
                    raise PersistenceSpoolError(
                        "spool physical cap invariant failed after durable append: "
                        f"{actual_bytes} > {self._limits.max_database_bytes}"
                    )
                return PersistenceOutcome.DURABLY_QUEUED
            except BaseException:
                conn.rollback()
                raise

    async def append_durable(self, envelope: NormalizedBatchEnvelope) -> PersistenceOutcome:
        """Submit append off-loop; cancellation cannot interrupt its transaction."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self.append, envelope)
        return await _await_executor_settlement(future)

    def oldest_pending(self) -> NormalizedBatchEnvelope | None:
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                "SELECT batch_uuid FROM spool_batches WHERE state='pending' ORDER BY sequence LIMIT 1"
            ).fetchone()
            return None if row is None else self._load_envelope(conn, str(row[0]))

    def pending_batches(self) -> tuple[NormalizedBatchEnvelope, ...]:
        with self._lock:
            conn = self._connection()
            identifiers = conn.execute(
                "SELECT batch_uuid FROM spool_batches WHERE state='pending' ORDER BY sequence"
            ).fetchall()
            return tuple(self._load_envelope(conn, str(row[0])) for row in identifiers)

    def acknowledge(self, receipt: MaterializationReceipt) -> None:
        """Remove one oldest envelope only after destination materialization proof.

        The destination remains the idempotency authority.  The spool deliberately
        keeps no unbounded acknowledged copy or tombstone.
        """

        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                oldest = conn.execute(
                    "SELECT batch_uuid,envelope_hash FROM spool_batches WHERE state='pending' ORDER BY sequence LIMIT 1"
                ).fetchone()
                if oldest is None:
                    raise PersistenceSpoolError("no pending envelope may be acknowledged")
                if self.__receipt_verifier is None:
                    raise PersistenceSpoolError("no destination receipt verifier is bound to this spool")
                batch_uuid, envelope_hash = str(oldest[0]), str(oldest[1])
                self.__receipt_verifier.verify(
                    receipt,
                    batch_uuid=batch_uuid,
                    envelope_hash=envelope_hash,
                )
                conn.execute("DELETE FROM spool_batches WHERE batch_uuid=?", (batch_uuid,))
                self._commit(conn)
            except BaseException:
                conn.rollback()
                raise
            self._checkpoint_reuse(conn)

    async def acknowledge_durable(self, receipt: MaterializationReceipt) -> None:
        """Acknowledge off-loop; cancellation cannot split delete and compaction."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self.acknowledge, receipt)
        await _await_executor_settlement(future)

    def latch_pending_error(self, batch_uuid: str, reason: str) -> None:
        """Latch a terminal materialization error without releasing accepted data.

        This intentionally leaves the exact envelope at the head of FIFO and keeps
        all of its UTC days protected.  Integration must pause/retry or obtain
        destination materialization proof and call :meth:`acknowledge`.
        """

        batch_uuid = _canonical_uuid(batch_uuid)
        reason = _bounded_text(reason, field="rejection reason")
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                oldest = conn.execute(
                    "SELECT batch_uuid FROM spool_batches WHERE state='pending' ORDER BY sequence LIMIT 1"
                ).fetchone()
                if oldest is None or str(oldest[0]) != batch_uuid:
                    raise PersistenceSpoolError("only the oldest pending envelope may latch an error")
                conn.execute(
                    "UPDATE spool_batches SET error=? WHERE batch_uuid=?",
                    (reason, batch_uuid),
                )
                conn.execute(
                    "UPDATE spool_meta SET last_error=? WHERE singleton=1",
                    (reason,),
                )
                self._commit(conn)
            except BaseException:
                conn.rollback()
                raise

    def note_retry(self, error: str) -> None:
        error = _bounded_text(error, field="retry error")
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "UPDATE spool_meta SET retry_count=retry_count+1,last_error=? WHERE singleton=1",
                    (error,),
                )
                self._commit(conn)
            except BaseException:
                conn.rollback()
                raise

    def pending_days(self) -> frozenset[date]:
        with self._lock:
            rows = (
                self._connection()
                .execute(
                    "SELECT DISTINCT r.utc_day FROM spool_rows r "
                    "JOIN spool_batches b ON b.batch_uuid=r.batch_uuid WHERE b.state='pending'"
                )
                .fetchall()
            )
            return frozenset(date.fromisoformat(str(row[0])) for row in rows)

    def health(self, *, now: datetime | None = None) -> SpoolHealth:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("health timestamp must be timezone-aware")
        now_ts = instant.astimezone(UTC).timestamp()
        with self._lock:
            conn = self._connection()
            pending = conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(row_count),0),COALESCE(SUM(payload_size),0),"
                "MIN(created_at) FROM spool_batches WHERE state='pending'"
            ).fetchone()
            meta = conn.execute(
                "SELECT rejected_batches,rejected_rows,retry_count,last_error FROM spool_meta WHERE singleton=1"
            ).fetchone()
            batches, rows, payload_bytes = int(pending[0]), int(pending[1]), int(pending[2])
            oldest_age = max(0.0, now_ts - float(pending[3])) if pending[3] is not None else 0.0
            database_bytes = self._database_bytes()
            high_water = self._is_high_water(
                batches,
                rows,
                payload_bytes,
                oldest_age,
                database_bytes,
            )
            return SpoolHealth(
                pending_batches=batches,
                pending_rows=rows,
                pending_bytes=payload_bytes,
                oldest_age_s=oldest_age,
                high_water=high_water,
                rejected_batches=int(meta[0]),
                rejected_rows=int(meta[1]),
                retry_count=int(meta[2]),
                last_error=None if meta[3] is None else str(meta[3]),
                database_bytes=database_bytes,
                database_limit_bytes=self._limits.max_database_bytes,
                database_headroom_bytes=max(0, self._limits.max_database_bytes - database_bytes),
            )

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise PersistenceSpoolError("persistence spool is closed")
        return self._conn

    def _validate_preopen_physical_limits(self, page_size: int) -> None:
        minimum_reserve = page_size * 8
        conservative_base = page_size * 20
        rejection_headroom = page_size * 8
        if self._limits.transaction_reserve_bytes < minimum_reserve:
            raise ValueError(
                "transaction_reserve_bytes is below the page-size-aware minimum: "
                f"{self._limits.transaction_reserve_bytes} < {minimum_reserve}"
            )
        minimum_cap = conservative_base + self._limits.transaction_reserve_bytes + rejection_headroom
        if self._limits.max_database_bytes < minimum_cap:
            raise ValueError(
                "max_database_bytes cannot safely contain the spool schema, WAL transaction reserve, "
                f"and rejection headroom: {self._limits.max_database_bytes} < {minimum_cap}"
            )

    def _validate_open_physical_limits(
        self,
        conn: sqlite3.Connection,
        *,
        include_wal_headroom: bool = False,
    ) -> None:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        minimum_reserve = page_size * 8
        actual = self._database_bytes()
        wal_headroom = minimum_reserve if include_wal_headroom else 0
        minimum_cap = actual + self._limits.transaction_reserve_bytes + minimum_reserve + wal_headroom
        if self._limits.transaction_reserve_bytes < minimum_reserve:
            raise PersistenceSpoolError("configured transaction reserve is unsafe for spool page size")
        if self._limits.max_database_bytes < minimum_cap:
            raise PersistenceSpoolError(
                "configured physical cap cannot contain the open spool plus transaction headroom: "
                f"{self._limits.max_database_bytes} < {minimum_cap}"
            )

    @staticmethod
    def _verify_semantic_schema(conn: sqlite3.Connection) -> None:
        reference = sqlite3.connect(":memory:")
        try:
            reference.execute("PRAGMA foreign_keys=ON")
            reference.executescript(_SCHEMA)

            def normalized_master(database: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
                records = database.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "WHERE type IN ('table','index','trigger','view') "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
                ).fetchall()
                return tuple(
                    (str(kind), str(name), str(table), "".join(str(sql).split()).lower())
                    for kind, name, table, sql in records
                )

            if normalized_master(conn) != normalized_master(reference):
                raise PersistenceSpoolCorruptError("spool normalized schema SQL mismatch")

            for table in sorted(_EXPECTED_TABLES):
                if (
                    conn.execute(f"PRAGMA table_xinfo({table})").fetchall()
                    != reference.execute(f"PRAGMA table_xinfo({table})").fetchall()
                ):
                    raise PersistenceSpoolCorruptError(f"spool table_xinfo mismatch: {table}")
                if (
                    conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                    != reference.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                ):
                    raise PersistenceSpoolCorruptError(f"spool foreign key mismatch: {table}")
                actual_indexes = conn.execute(f"PRAGMA index_list({table})").fetchall()
                expected_indexes = reference.execute(f"PRAGMA index_list({table})").fetchall()
                if actual_indexes != expected_indexes:
                    raise PersistenceSpoolCorruptError(f"spool index_list mismatch: {table}")
                for index_record in expected_indexes:
                    index_name = str(index_record[1])
                    if (
                        conn.execute(f"PRAGMA index_xinfo({index_name})").fetchall()
                        != reference.execute(f"PRAGMA index_xinfo({index_name})").fetchall()
                    ):
                        raise PersistenceSpoolCorruptError(f"spool index_xinfo mismatch: {index_name}")
        finally:
            reference.close()

    def _commit(self, conn: sqlite3.Connection) -> None:
        if self._before_commit_hook is not None:
            self._before_commit_hook()
        conn.commit()

    def _hard_limit_reason(
        self,
        conn: sqlite3.Connection,
        envelope: NormalizedBatchEnvelope,
    ) -> str | None:
        pending = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(row_count),0),COALESCE(SUM(payload_size),0),"
            "MIN(created_at) FROM spool_batches WHERE state='pending'"
        ).fetchone()
        next_batches = int(pending[0]) + 1
        next_rows = int(pending[1]) + len(envelope.rows)
        next_bytes = int(pending[2]) + len(envelope.payload_bytes)
        now_ts = datetime.now(UTC).timestamp()
        oldest = min(
            float(pending[3]) if pending[3] is not None else envelope.created_at,
            envelope.created_at,
        )
        if self._projected_database_bytes(conn, envelope) > self._limits.max_database_bytes:
            return "spool physical database hard cap exceeded"
        if next_batches > self._limits.max_batches:
            return "spool batch hard cap exceeded"
        if next_rows > self._limits.max_rows:
            return "spool row hard cap exceeded"
        if next_bytes > self._limits.max_bytes:
            return "spool byte hard cap exceeded"
        if now_ts - oldest >= self._limits.max_oldest_age_s:
            return "spool oldest-age hard cap exceeded"
        return None

    def _record_rejection(
        self,
        conn: sqlite3.Connection,
        envelope: NormalizedBatchEnvelope,
        reason: str,
    ) -> None:
        conn.execute(
            "INSERT INTO spool_rejections(batch_uuid,envelope_hash,row_count,reason) VALUES (?,?,?,?)",
            (
                envelope.batch_uuid,
                envelope.payload_hash,
                len(envelope.rows),
                reason,
            ),
        )
        conn.execute(
            "DELETE FROM spool_rejections WHERE sequence NOT IN "
            "(SELECT sequence FROM spool_rejections ORDER BY sequence DESC LIMIT ?)",
            (_MAX_RECENT_REJECTIONS,),
        )
        conn.execute(
            "UPDATE spool_meta SET rejected_batches=rejected_batches+1,rejected_rows=rejected_rows+?,"
            "last_error=? WHERE singleton=1",
            (len(envelope.rows), reason),
        )

    def _reject_ingest_collisions(
        self,
        conn: sqlite3.Connection,
        envelope: NormalizedBatchEnvelope,
    ) -> None:
        for row in envelope.rows:
            existing = conn.execute(
                "SELECT batch_uuid,payload_json FROM spool_rows WHERE ingest_uuid=?",
                (row.ingest_uuid,),
            ).fetchone()
            if existing is not None:
                equivalent = str(existing[1]).encode("ascii") == row.payload_bytes
                detail = "equivalent duplicate in another batch" if equivalent else "payload mismatch"
                raise PersistenceSpoolCollisionError(
                    f"ingest UUID collision ({detail}) in batch {existing[0]}: {row.ingest_uuid}"
                )

    def _load_envelope(
        self,
        conn: sqlite3.Connection,
        batch_uuid: str,
    ) -> NormalizedBatchEnvelope:
        header = conn.execute(
            "SELECT schema_version,created_at,calibration_json,envelope_hash,state,"
            "row_count,payload_size,error "
            "FROM spool_batches WHERE batch_uuid=?",
            (batch_uuid,),
        ).fetchone()
        if header is None or str(header[4]) != "pending":
            raise PersistenceSpoolCorruptError(f"pending envelope header unavailable: {batch_uuid}")
        row_records = conn.execute(
            "SELECT ordinal,ingest_uuid,utc_day,timestamp,instrument_id,channel,value,unit,status,"
            "payload_json,payload_hash FROM spool_rows WHERE batch_uuid=? ORDER BY ordinal",
            (batch_uuid,),
        ).fetchall()
        actual_ordinals = [int(record[0]) for record in row_records]
        if actual_ordinals != list(range(len(row_records))):
            raise PersistenceSpoolCorruptError(f"row ordinal gap: {batch_uuid}")
        rows: list[NormalizedSpoolRow] = []
        for record in row_records:
            row = NormalizedSpoolRow(
                ingest_uuid=str(record[1]),
                utc_day=date.fromisoformat(str(record[2])),
                timestamp=float(record[3]),
                instrument_id=str(record[4]),
                channel=str(record[5]),
                value=float(record[6]),
                unit=str(record[7]),
                status=str(record[8]),
            )
            if row.payload_bytes != str(record[9]).encode("ascii") or row.payload_hash != str(record[10]):
                raise PersistenceSpoolCorruptError(f"row payload mismatch: {row.ingest_uuid}")
            rows.append(row)
        if int(header[5]) != len(rows):
            raise PersistenceSpoolCorruptError(f"row count mismatch: {batch_uuid}")
        calibration_text = None if header[2] is None else str(header[2])
        calibration_raw = None if calibration_text is None else json.loads(calibration_text)
        calibration = (
            None
            if calibration_raw is None
            else CalibrationGrouping(
                group_id=calibration_raw["group_id"],
                krdg_rows=calibration_raw["krdg_rows"],
                srdg_rows=calibration_raw["srdg_rows"],
                acquisition_id=calibration_raw["acquisition_id"],
                pending_t_min=calibration_raw["pending_t_min"],
                pending_t_max=calibration_raw["pending_t_max"],
            )
        )
        expected_calibration = (
            None if calibration is None else _canonical_json(calibration.canonical_value()).decode("ascii")
        )
        if calibration_text != expected_calibration:
            raise PersistenceSpoolCorruptError(f"calibration payload mismatch: {batch_uuid}")
        envelope = NormalizedBatchEnvelope(
            batch_uuid=batch_uuid,
            created_at=float(header[1]),
            rows=tuple(rows),
            calibration=calibration,
            schema_version=int(header[0]),
        )
        if envelope.payload_hash != str(header[3]):
            raise PersistenceSpoolCorruptError(f"envelope payload mismatch: {batch_uuid}")
        if int(header[6]) != len(envelope.payload_bytes):
            raise PersistenceSpoolCorruptError(f"payload size mismatch: {batch_uuid}")
        if header[7] is not None:
            _bounded_text(str(header[7]), field="pending error")
        return envelope

    def _verify_all_integrity(self, conn: sqlite3.Connection) -> None:
        meta_rows = conn.execute(
            "SELECT singleton,rejected_batches,rejected_rows,retry_count,last_error FROM spool_meta"
        ).fetchall()
        if len(meta_rows) != 1 or int(meta_rows[0][0]) != 1:
            raise PersistenceSpoolCorruptError("spool meta singleton is missing or duplicated")
        for value in meta_rows[0][1:4]:
            if type(value) is not int or value < 0:
                raise PersistenceSpoolCorruptError("spool meta counter is invalid")
        if meta_rows[0][4] is not None:
            _bounded_text(str(meta_rows[0][4]), field="spool last_error")

        identifiers = conn.execute("SELECT batch_uuid FROM spool_batches ORDER BY sequence").fetchall()
        for row in identifiers:
            self._load_envelope(conn, str(row[0]))

        rejections = conn.execute(
            "SELECT batch_uuid,envelope_hash,row_count,reason FROM spool_rejections ORDER BY sequence"
        ).fetchall()
        if len(rejections) > _MAX_RECENT_REJECTIONS:
            raise PersistenceSpoolCorruptError("rejection ring exceeds configured bound")
        ring_rows = 0
        for batch_uuid, envelope_hash, row_count, reason in rejections:
            _canonical_uuid(str(batch_uuid))
            digest = str(envelope_hash)
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise PersistenceSpoolCorruptError("rejection envelope hash is invalid")
            if type(row_count) is not int or row_count <= 0:
                raise PersistenceSpoolCorruptError("rejection row count is invalid")
            ring_rows += row_count
            _bounded_text(str(reason), field="rejection reason")
        if int(meta_rows[0][1]) < len(rejections) or int(meta_rows[0][2]) < ring_rows:
            raise PersistenceSpoolCorruptError("rejection counters understate retained rejection evidence")
        overlap = conn.execute(
            "SELECT 1 FROM spool_batches b JOIN spool_rejections r USING(batch_uuid) LIMIT 1"
        ).fetchone()
        if overlap is not None:
            raise PersistenceSpoolCorruptError("batch exists in pending FIFO and rejection ring")

    @staticmethod
    def _outcome_for_state(state: str) -> PersistenceOutcome:
        if state == "pending":
            return PersistenceOutcome.DURABLY_QUEUED
        raise PersistenceSpoolCorruptError(f"unknown spool state: {state}")

    def _is_high_water(
        self,
        batches: int,
        rows: int,
        payload_bytes: int,
        oldest_age_s: float,
        database_bytes: int,
    ) -> bool:
        fraction = self._limits.high_water_fraction
        return (
            batches >= self._limits.max_batches * fraction
            or rows >= self._limits.max_rows * fraction
            or payload_bytes >= self._limits.max_bytes * fraction
            or oldest_age_s >= self._limits.max_oldest_age_s * fraction
            or database_bytes >= self._limits.max_database_bytes * fraction
        )

    def _projected_database_bytes(
        self,
        conn: sqlite3.Connection,
        envelope: NormalizedBatchEnvelope,
    ) -> int:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        free_bytes = int(conn.execute("PRAGMA freelist_count").fetchone()[0]) * page_size
        content_bytes = len(envelope.payload_bytes) + sum(len(row.payload_bytes) for row in envelope.rows)
        page_size_overhead = page_size * (8 + 3 * len(envelope.rows))
        conservative_overhead = 16 * 1024 + len(envelope.rows) * 2048 + page_size_overhead
        required_bytes = content_bytes + conservative_overhead
        allocated_growth = max(0, required_bytes - free_bytes)
        return self._database_bytes() + allocated_growth + self._limits.transaction_reserve_bytes

    @staticmethod
    def _checkpoint_reuse(conn: sqlite3.Connection) -> bool:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return result is not None and int(result[0]) == 0

    def _database_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(f"{self._path}{suffix}")
            except OSError:
                pass
        return total


__all__ = [
    "CalibrationGrouping",
    "MaterializationReceipt",
    "MaterializationReceiptIssuer",
    "MaterializationReceiptVerifier",
    "NormalizedBatchEnvelope",
    "NormalizedSpoolRow",
    "PersistenceOutcome",
    "PersistenceSpool",
    "PersistenceSpoolCollisionError",
    "PersistenceSpoolCorruptError",
    "PersistenceSpoolError",
    "SpoolHealth",
    "SpoolLimits",
    "create_materialization_receipt_channel",
]
