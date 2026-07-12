"""Verified append-only channel descriptor storage for daily SQLite files.

This module owns metadata persistence only.  It does not activate drivers,
publish readings, infer vendor semantics, or grant source/control authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    validate_catalog_update,
)
from cryodaq.channels.persistence import (
    MAX_PERSISTED_ENVELOPE_BYTES,
    PersistedChannelEnvelopeError,
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
    resolve_persisted_channel,
)
from cryodaq.storage._sqlite import sqlite3

CATALOG_SCHEMA_VERSION: Final = 1
MAX_CATALOG_ENVELOPE_BYTES: Final = MAX_CATALOG_DESCRIPTORS * MAX_PERSISTED_ENVELOPE_BYTES

SCHEMA_DESCRIPTOR_META: Final = """
CREATE TABLE IF NOT EXISTS channel_descriptor_meta (
    singleton      INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1)
);
"""

SCHEMA_DESCRIPTORS: Final = """
CREATE TABLE IF NOT EXISTS channel_descriptors (
    descriptor_hash     TEXT    PRIMARY KEY,
    channel_id          TEXT    NOT NULL,
    instrument_id       TEXT    NOT NULL,
    source_key          TEXT    NOT NULL,
    descriptor_revision INTEGER NOT NULL CHECK (descriptor_revision >= 1),
    envelope_json       BLOB    NOT NULL,
    UNIQUE (channel_id, descriptor_revision),
    UNIQUE (instrument_id, source_key, descriptor_revision)
);
"""

INDEX_DESCRIPTORS_CHANNEL_REVISION: Final = """
CREATE INDEX IF NOT EXISTS idx_channel_descriptors_channel_revision
ON channel_descriptors (channel_id, descriptor_revision);
"""

INDEX_READINGS_DESCRIPTOR_HASH: Final = """
CREATE INDEX IF NOT EXISTS idx_readings_descriptor_hash
ON readings (descriptor_hash);
"""

_TRIGGERS: Final[dict[str, str]] = {
    "channel_descriptors_no_update": """
        CREATE TRIGGER channel_descriptors_no_update
        BEFORE UPDATE ON channel_descriptors
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor catalog is append-only');
        END;
    """,
    "channel_descriptors_no_delete": """
        CREATE TRIGGER channel_descriptors_no_delete
        BEFORE DELETE ON channel_descriptors
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor catalog is append-only');
        END;
    """,
    "channel_descriptor_meta_no_update": """
        CREATE TRIGGER channel_descriptor_meta_no_update
        BEFORE UPDATE ON channel_descriptor_meta
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor metadata is immutable');
        END;
    """,
    "channel_descriptor_meta_no_delete": """
        CREATE TRIGGER channel_descriptor_meta_no_delete
        BEFORE DELETE ON channel_descriptor_meta
        BEGIN
            SELECT RAISE(ABORT, 'channel descriptor metadata is immutable');
        END;
    """,
}

_META_COLUMNS: Final = (
    ("singleton", "INTEGER", 0, None, 1),
    ("schema_version", "INTEGER", 1, None, 0),
)
_DESCRIPTOR_COLUMNS: Final = (
    ("descriptor_hash", "TEXT", 0, None, 1),
    ("channel_id", "TEXT", 1, None, 0),
    ("instrument_id", "TEXT", 1, None, 0),
    ("source_key", "TEXT", 1, None, 0),
    ("descriptor_revision", "INTEGER", 1, None, 0),
    ("envelope_json", "BLOB", 1, None, 0),
)
_LEGACY_READING_COLUMNS: Final = (
    ("id", "INTEGER", 0, None, 1),
    ("timestamp", "REAL", 1, None, 0),
    ("instrument_id", "TEXT", 1, None, 0),
    ("channel", "TEXT", 1, None, 0),
    ("value", "REAL", 1, None, 0),
    ("unit", "TEXT", 1, None, 0),
    ("status", "TEXT", 1, None, 0),
)
_V1_READING_COLUMNS: Final = (*_LEGACY_READING_COLUMNS, ("descriptor_hash", "TEXT", 0, None, 0))
_PROTECTED_TEMP_NAMES: Final = {
    "channel_descriptor_meta",
    "channel_descriptors",
    "readings",
    "idx_channel_descriptors_channel_revision",
    "idx_readings_descriptor_hash",
    *_TRIGGERS,
}
_MIGRATED_READINGS_SQL: Final = """
CREATE TABLE readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
, descriptor_hash TEXT REFERENCES channel_descriptors(descriptor_hash))
"""


class ChannelDescriptorStorageError(RuntimeError):
    """The SQLite descriptor authority is malformed, corrupt, or ambiguous."""


@dataclass(frozen=True, slots=True)
class ResolvedSQLiteReading:
    """One immutable hot reading row paired with its resolved descriptor."""

    id: int
    timestamp: float
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: str
    descriptor: ChannelDescriptorV1 | None


def _enable_foreign_keys(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    if conn.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise ChannelDescriptorStorageError("SQLite foreign keys could not be enabled")


def _columns(conn: sqlite3.Connection, table: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (row[1], str(row[2]).upper(), row[3], row[4], row[5])
        for row in conn.execute(f"PRAGMA main.table_info({table})")
    )


def _reject_temp_shadowing(conn: sqlite3.Connection) -> None:
    placeholders = ", ".join("?" for _ in _PROTECTED_TEMP_NAMES)
    protected = tuple(sorted(_PROTECTED_TEMP_NAMES))
    row = conn.execute(
        "SELECT type, name, tbl_name FROM sqlite_temp_master "
        f"WHERE name IN ({placeholders}) OR tbl_name IN ({placeholders}) LIMIT 1",
        (*protected, *protected),
    ).fetchone()
    if row is not None:
        raise ChannelDescriptorStorageError("temporary SQLite object shadows descriptor authority")


def _normalize_sql(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().rstrip(";")).casefold()
    return re.sub(r"\bif not exists ", "", normalized)


def _verify_object_sql(conn: sqlite3.Connection, object_type: str, name: str, expected_sql: str) -> None:
    row = conn.execute(
        "SELECT sql FROM main.sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    if row is None or type(row[0]) is not str or _normalize_sql(row[0]) != _normalize_sql(expected_sql):
        raise ChannelDescriptorStorageError(f"descriptor storage {object_type} {name!r} integrity mismatch")


def _verify_index(
    conn: sqlite3.Connection,
    name: str,
    columns: tuple[str, ...],
    expected_sql: str,
) -> None:
    row = conn.execute(
        "SELECT type FROM main.sqlite_master WHERE name = ?",
        (name,),
    ).fetchone()
    actual = tuple(item[2] for item in conn.execute(f"PRAGMA main.index_info({name})"))
    if row != ("index",) or actual != columns:
        raise ChannelDescriptorStorageError(f"descriptor storage index {name!r} integrity mismatch")
    _verify_object_sql(conn, "index", name, expected_sql)


def _verify_schema(conn: sqlite3.Connection) -> None:
    _reject_temp_shadowing(conn)
    if _columns(conn, "channel_descriptor_meta") != _META_COLUMNS:
        raise ChannelDescriptorStorageError("channel_descriptor_meta schema integrity mismatch")
    if _columns(conn, "channel_descriptors") != _DESCRIPTOR_COLUMNS:
        raise ChannelDescriptorStorageError("channel_descriptors schema integrity mismatch")
    if _columns(conn, "readings") != _V1_READING_COLUMNS:
        raise ChannelDescriptorStorageError("readings descriptor migration integrity mismatch")
    _verify_object_sql(conn, "table", "channel_descriptor_meta", SCHEMA_DESCRIPTOR_META)
    _verify_object_sql(conn, "table", "channel_descriptors", SCHEMA_DESCRIPTORS)
    _verify_object_sql(conn, "table", "readings", _MIGRATED_READINGS_SQL)

    meta = conn.execute("SELECT singleton, schema_version FROM main.channel_descriptor_meta").fetchall()
    if meta != [(1, CATALOG_SCHEMA_VERSION)]:
        raise ChannelDescriptorStorageError("channel descriptor metadata singleton integrity mismatch")

    for name, expected_sql in _TRIGGERS.items():
        row = conn.execute(
            "SELECT sql FROM main.sqlite_master WHERE type = 'trigger' AND name = ?",
            (name,),
        ).fetchone()
        if row is None or not isinstance(row[0], str) or _normalize_sql(row[0]) != _normalize_sql(expected_sql):
            raise ChannelDescriptorStorageError(f"descriptor storage trigger {name!r} integrity mismatch")

    actual_triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'trigger' "
            "AND tbl_name IN ('channel_descriptor_meta', 'channel_descriptors', 'readings')"
        )
    }
    if actual_triggers != set(_TRIGGERS):
        raise ChannelDescriptorStorageError("descriptor storage trigger set integrity mismatch")

    _verify_index(
        conn,
        "idx_channel_descriptors_channel_revision",
        ("channel_id", "descriptor_revision"),
        INDEX_DESCRIPTORS_CHANNEL_REVISION,
    )
    _verify_index(
        conn,
        "idx_readings_descriptor_hash",
        ("descriptor_hash",),
        INDEX_READINGS_DESCRIPTOR_HASH,
    )
    foreign_keys = [(row[2], row[3], row[4]) for row in conn.execute("PRAGMA main.foreign_key_list(readings)")]
    if foreign_keys != [("channel_descriptors", "descriptor_hash", "descriptor_hash")]:
        raise ChannelDescriptorStorageError("readings descriptor foreign-key integrity mismatch")


def initialize_descriptor_storage(conn: sqlite3.Connection) -> None:
    """Idempotently migrate one exact legacy readings schema to descriptor v1."""

    if conn.in_transaction:
        raise ChannelDescriptorStorageError("descriptor migration requires a clean transaction boundary")
    _enable_foreign_keys(conn)
    _reject_temp_shadowing(conn)

    reading_columns = _columns(conn, "readings")
    if reading_columns not in (_LEGACY_READING_COLUMNS, _V1_READING_COLUMNS):
        raise ChannelDescriptorStorageError("readings schema is neither exact legacy nor descriptor v1")
    if reading_columns == _V1_READING_COLUMNS:
        _verify_schema(conn)
        _load_envelopes(conn)
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")
        return

    try:
        conn.execute("BEGIN IMMEDIATE")
        # Another process may have completed the migration while this
        # connection waited for the write lock.  Re-read the authoritative
        # schema under the lock before issuing ALTER TABLE.
        reading_columns = _columns(conn, "readings")
        if reading_columns == _V1_READING_COLUMNS:
            _verify_schema(conn)
            _load_envelopes(conn)
            if conn.execute("PRAGMA main.foreign_key_check").fetchall():
                raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")
            conn.commit()
            return
        if reading_columns != _LEGACY_READING_COLUMNS:
            raise ChannelDescriptorStorageError("readings schema changed during descriptor migration")
        conn.execute(SCHEMA_DESCRIPTOR_META)
        conn.execute(SCHEMA_DESCRIPTORS)
        conn.execute(INDEX_DESCRIPTORS_CHANNEL_REVISION)
        for statement in _TRIGGERS.values():
            conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO main.channel_descriptor_meta (singleton, schema_version) VALUES (1, ?)",
            (CATALOG_SCHEMA_VERSION,),
        )
        conn.execute(
            "ALTER TABLE main.readings ADD COLUMN descriptor_hash TEXT REFERENCES channel_descriptors(descriptor_hash)"
        )
        conn.execute(INDEX_READINGS_DESCRIPTOR_HASH)
        _verify_schema(conn)
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor migration foreign-key check failed")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def snapshot_catalog(catalog: object) -> ChannelCatalog:
    """Copy and revalidate an exact catalog without retaining caller objects."""

    if type(catalog) is not ChannelCatalog:
        raise TypeError("channel_catalog must be exactly ChannelCatalog")
    envelopes = tuple(PersistedChannelEnvelopeV1.from_descriptor(item) for item in catalog.descriptors)
    descriptors = tuple(decode_persisted_channel_envelope(item.canonical_json).descriptor for item in envelopes)
    return ChannelCatalog(descriptors)


def _load_envelopes(conn: sqlite3.Connection) -> tuple[PersistedChannelEnvelopeV1, ...]:
    count, total_bytes, largest = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(length(envelope_json)), 0), "
        "COALESCE(MAX(length(envelope_json)), 0) FROM main.channel_descriptors"
    ).fetchone()
    if type(count) is not int or type(total_bytes) is not int or type(largest) is not int:
        raise ChannelDescriptorStorageError("descriptor catalog bounds are not integral")
    if (
        count > MAX_CATALOG_DESCRIPTORS
        or largest > MAX_PERSISTED_ENVELOPE_BYTES
        or total_bytes > MAX_CATALOG_ENVELOPE_BYTES
    ):
        raise ChannelDescriptorStorageError("descriptor catalog exceeds bounded storage limits")

    result: list[PersistedChannelEnvelopeV1] = []
    rows = conn.execute(
        "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
        "descriptor_revision, envelope_json FROM main.channel_descriptors "
        "ORDER BY channel_id, descriptor_revision"
    )
    for sql_hash, channel_id, instrument_id, source_key, revision, payload in rows:
        if type(payload) is not bytes:
            raise ChannelDescriptorStorageError("descriptor envelope is not stored as exact bytes")
        try:
            envelope = decode_persisted_channel_envelope(payload)
        except (TypeError, PersistedChannelEnvelopeError) as exc:
            raise ChannelDescriptorStorageError("persisted descriptor envelope is corrupt") from exc
        if payload != envelope.canonical_json:
            raise ChannelDescriptorStorageError("persisted descriptor envelope is not exact canonical bytes")
        repeated = (sql_hash, channel_id, instrument_id, source_key, revision)
        expected = (
            envelope.descriptor_hash,
            envelope.channel_id,
            envelope.instrument_id,
            envelope.source_key,
            envelope.descriptor_revision,
        )
        if repeated != expected:
            raise ChannelDescriptorStorageError("descriptor SQL indexes disagree with envelope authority")
        result.append(envelope)
    try:
        validate_catalog_update((), tuple(item.descriptor for item in result))
    except ChannelDescriptorError as exc:
        raise ChannelDescriptorStorageError("persisted descriptor history is invalid") from exc
    return tuple(result)


def install_catalog(
    conn: sqlite3.Connection,
    catalog: ChannelCatalog,
    *,
    within_transaction: bool = False,
) -> None:
    """Verify history and append an idempotent current catalog transactionally."""

    _enable_foreign_keys(conn)
    _verify_schema(conn)
    configured = snapshot_catalog(catalog)
    if type(within_transaction) is not bool:
        raise TypeError("within_transaction must be exactly bool")
    if within_transaction != conn.in_transaction:
        raise ChannelDescriptorStorageError("catalog transaction ownership mismatch")
    try:
        if not within_transaction:
            conn.execute("BEGIN IMMEDIATE")
        existing = _load_envelopes(conn)
        history = tuple(item.descriptor for item in existing)
        try:
            validate_catalog_update(history, configured.descriptors)
            ChannelCatalog(configured.descriptors, historical=history)
        except ChannelDescriptorError as exc:
            raise ChannelDescriptorStorageError(
                "configured descriptor catalog conflicts with persisted history"
            ) from exc
        for descriptor in configured.descriptors:
            envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
            prior = conn.execute(
                "SELECT channel_id, instrument_id, source_key, descriptor_revision, envelope_json "
                "FROM main.channel_descriptors WHERE descriptor_hash = ?",
                (envelope.descriptor_hash,),
            ).fetchone()
            if prior is not None:
                expected = (
                    envelope.channel_id,
                    envelope.instrument_id,
                    envelope.source_key,
                    envelope.descriptor_revision,
                    envelope.canonical_json,
                )
                if prior != expected:
                    raise ChannelDescriptorStorageError("descriptor hash collision or non-idempotent row")
                continue
            conn.execute(
                "INSERT INTO main.channel_descriptors "
                "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    envelope.descriptor_hash,
                    envelope.channel_id,
                    envelope.instrument_id,
                    envelope.source_key,
                    envelope.descriptor_revision,
                    envelope.canonical_json,
                ),
            )
        if conn.execute("PRAGMA main.foreign_key_check").fetchall():
            raise ChannelDescriptorStorageError("descriptor catalog foreign-key check failed")
        # Validate the exact post-insert state before any commit.  This catches
        # unexpected trigger side effects and canonical/history corruption in
        # the same transaction that introduced it.
        _verify_schema(conn)
        _load_envelopes(conn)
        if not within_transaction:
            conn.commit()
    except Exception:
        if not within_transaction:
            conn.rollback()
        raise

    if not within_transaction:
        _verify_schema(conn)
        _load_envelopes(conn)


def verify_descriptor_storage(conn: sqlite3.Connection) -> None:
    """Verify the complete hot descriptor authority at the current cut."""

    _enable_foreign_keys(conn)
    _verify_schema(conn)
    _load_envelopes(conn)
    if conn.execute("PRAGMA main.foreign_key_check").fetchall():
        raise ChannelDescriptorStorageError("descriptor storage foreign-key check failed")


def descriptor_hash_for_reading(
    catalog: ChannelCatalog,
    *,
    instrument_id: object,
    channel: object,
    unit: object,
) -> str:
    """Bind a reading to the configured current descriptor or fail closed."""

    if any(type(item) is not str for item in (instrument_id, channel, unit)):
        raise ChannelDescriptorStorageError("descriptor-required reading identity must use exact strings")
    descriptor = catalog.by_channel_id.get(channel)
    if descriptor is None:
        raise ChannelDescriptorStorageError("descriptor-required reading has an unknown channel_id")
    if descriptor.instrument_id != instrument_id:
        raise ChannelDescriptorStorageError("reading instrument_id disagrees with descriptor")
    if descriptor.unit != unit:
        raise ChannelDescriptorStorageError("reading unit disagrees with descriptor")
    return descriptor.descriptor_hash


def resolve_sqlite_descriptor(
    conn: sqlite3.Connection,
    descriptor_hash: object,
    *,
    legacy_instrument_id: object,
    legacy_channel: object,
    legacy_unit: object,
) -> ChannelDescriptorV1:
    """Resolve one hot row; only SQL NULL is allowed to select legacy."""

    _enable_foreign_keys(conn)
    if descriptor_hash is None:
        reading_columns = _columns(conn, "readings")
        if reading_columns == _V1_READING_COLUMNS:
            _verify_schema(conn)
            _load_envelopes(conn)
            if conn.execute("PRAGMA main.foreign_key_check").fetchall():
                raise ChannelDescriptorStorageError("legacy row database fails foreign-key integrity")
        elif reading_columns != _LEGACY_READING_COLUMNS:
            raise ChannelDescriptorStorageError("legacy row belongs to an unknown readings schema")
        return resolve_persisted_channel(
            None,
            legacy_instrument_id=legacy_instrument_id,
            legacy_channel=legacy_channel,
            legacy_unit=legacy_unit,
        )
    if type(descriptor_hash) is not str:
        raise ChannelDescriptorStorageError("present descriptor_hash is not an exact string")
    _verify_schema(conn)
    _load_envelopes(conn)
    if conn.execute("PRAGMA main.foreign_key_check").fetchall():
        raise ChannelDescriptorStorageError("present descriptor reference fails foreign-key integrity")
    row = conn.execute(
        "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
        "descriptor_revision, envelope_json FROM main.channel_descriptors WHERE descriptor_hash = ?",
        (descriptor_hash,),
    ).fetchone()
    if row is None:
        raise ChannelDescriptorStorageError("present descriptor_hash has no catalog row")
    sql_hash, channel_id, instrument_id, source_key, revision, payload = row
    if type(payload) is not bytes:
        raise ChannelDescriptorStorageError("present descriptor envelope is not exact bytes")
    try:
        envelope = decode_persisted_channel_envelope(payload)
    except (TypeError, PersistedChannelEnvelopeError) as exc:
        raise ChannelDescriptorStorageError("present descriptor envelope is corrupt") from exc
    if payload != envelope.canonical_json:
        raise ChannelDescriptorStorageError("present descriptor envelope is not exact canonical bytes")
    if (sql_hash, channel_id, instrument_id, source_key, revision) != (
        envelope.descriptor_hash,
        envelope.channel_id,
        envelope.instrument_id,
        envelope.source_key,
        envelope.descriptor_revision,
    ):
        raise ChannelDescriptorStorageError("present descriptor indexes disagree with envelope")
    if (
        envelope.instrument_id != legacy_instrument_id
        or envelope.channel_id != legacy_channel
        or envelope.descriptor.unit != legacy_unit
    ):
        raise ChannelDescriptorStorageError("reading identity disagrees with present descriptor")
    return envelope.descriptor


def read_sqlite_reading(conn: sqlite3.Connection, reading_id: object) -> ResolvedSQLiteReading:
    """Read one hot row and return an owned reading-plus-descriptor value."""

    _enable_foreign_keys(conn)
    if type(reading_id) is not int or reading_id < 1:
        raise TypeError("reading_id must be a positive exact integer")
    reading_columns = _columns(conn, "readings")
    if reading_columns == _LEGACY_READING_COLUMNS:
        row = conn.execute(
            "SELECT id, timestamp, instrument_id, channel, value, unit, status FROM main.readings WHERE id = ?",
            (reading_id,),
        ).fetchone()
        if row is not None:
            row = (*row, None)
    elif reading_columns == _V1_READING_COLUMNS:
        row = conn.execute(
            "SELECT id, timestamp, instrument_id, channel, value, unit, status, descriptor_hash "
            "FROM main.readings WHERE id = ?",
            (reading_id,),
        ).fetchone()
    else:
        raise ChannelDescriptorStorageError("hot reading belongs to an unknown readings schema")
    if row is None:
        raise ChannelDescriptorStorageError("hot reading row does not exist")
    row_id, timestamp, instrument_id, channel, value, unit, status, descriptor_hash = row
    if (
        type(row_id) is not int
        or type(timestamp) not in (int, float)
        or type(instrument_id) is not str
        or type(channel) is not str
        or type(value) not in (int, float)
        or type(unit) is not str
        or type(status) is not str
    ):
        raise ChannelDescriptorStorageError("hot reading row has invalid SQLite value types")
    descriptor = (
        None
        if reading_columns == _LEGACY_READING_COLUMNS
        else resolve_sqlite_descriptor(
            conn,
            descriptor_hash,
            legacy_instrument_id=instrument_id,
            legacy_channel=channel,
            legacy_unit=unit,
        )
    )
    return ResolvedSQLiteReading(
        id=row_id,
        timestamp=float(timestamp),
        instrument_id=instrument_id,
        channel=channel,
        value=float(value),
        unit=unit,
        status=status,
        descriptor=descriptor,
    )


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "MAX_CATALOG_ENVELOPE_BYTES",
    "ChannelDescriptorStorageError",
    "ResolvedSQLiteReading",
    "descriptor_hash_for_reading",
    "initialize_descriptor_storage",
    "install_catalog",
    "read_sqlite_reading",
    "resolve_sqlite_descriptor",
    "snapshot_catalog",
    "verify_descriptor_storage",
]
