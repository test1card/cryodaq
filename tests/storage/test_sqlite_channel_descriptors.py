from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import pytest

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import (
    _TRIGGERS,
    ChannelDescriptorStorageError,
    initialize_descriptor_storage,
    install_catalog,
    read_sqlite_reading,
    resolve_sqlite_descriptor,
)
from cryodaq.storage.sqlite_writer import SCHEMA_READINGS, SQLiteWriter


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "sensor.main",
        "instrument_id": "reference-thermometer",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Cryostat",
        "display_name": "Основной датчик",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 1,
    }
    values.update(changes)
    return ChannelDescriptorV1(**values)  # type: ignore[arg-type]


def _reading(**changes: object) -> Reading:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 7, 12, 12, tzinfo=UTC),
        "instrument_id": "reference-thermometer",
        "channel": "sensor.main",
        "value": 4.2,
        "unit": "K",
    }
    values.update(changes)
    return Reading(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _db_path(root: Path) -> Path:
    return root / "data_2026-07-12.db"


async def test_new_database_persists_exact_envelope_and_reading_reference(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    assert await writer.write_immediate([_reading()]) is True
    await writer.stop()

    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        meta = conn.execute("SELECT singleton, schema_version FROM channel_descriptor_meta").fetchall()
        catalog = conn.execute(
            "SELECT descriptor_hash, channel_id, instrument_id, source_key, "
            "descriptor_revision, envelope_json FROM channel_descriptors"
        ).fetchone()
        reading = conn.execute("SELECT instrument_id, channel, unit, descriptor_hash FROM readings").fetchone()
        assert meta == [(1, 1)]
        assert catalog is not None
        assert catalog[:5] == (
            descriptor.descriptor_hash,
            descriptor.channel_id,
            descriptor.instrument_id,
            descriptor.source_key,
            descriptor.descriptor_revision,
        )
        assert type(catalog[5]) is bytes
        assert reading == (
            descriptor.instrument_id,
            descriptor.channel_id,
            descriptor.unit,
            descriptor.descriptor_hash,
        )
        assert (
            resolve_sqlite_descriptor(
                conn,
                reading[3],
                legacy_instrument_id=reading[0],
                legacy_channel=reading[1],
                legacy_unit=reading[2],
            )
            == descriptor
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


async def test_exact_legacy_database_migrates_without_rewriting_old_rows(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.execute(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime(2026, 7, 12, tzinfo=UTC).timestamp(), "legacy", "T1", 4.2, "K", "ok"),
    )
    conn.commit()
    conn.close()

    writer = SQLiteWriter(tmp_path)
    assert await writer.write_immediate([_reading(channel="T2", instrument_id="legacy")]) is True
    await writer.stop()

    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT instrument_id, channel, unit, descriptor_hash FROM readings ORDER BY id").fetchall()
        assert rows == [("legacy", "T1", "K", None), ("legacy", "T2", "K", None)]
        first = resolve_sqlite_descriptor(
            conn,
            None,
            legacy_instrument_id="legacy",
            legacy_channel="T1",
            legacy_unit="K",
        )
        assert first.quantity is ChannelQuantity.LEGACY_UNKNOWN
        assert first.channel_id.startswith("legacy:")
    finally:
        conn.close()


async def test_migration_and_catalog_install_are_idempotent(tmp_path: Path) -> None:
    descriptor = _descriptor()
    for value in (4.2, 4.3):
        writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
        assert await writer.write_immediate([_reading(value=value)]) is True
        await writer.stop()

    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (2,)
    finally:
        conn.close()


async def test_strictly_forward_revision_appends_and_old_reading_keeps_old_hash(tmp_path: Path) -> None:
    first = _descriptor()
    second = replace(first, descriptor_revision=2, display_name="Уточненный датчик")

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([first]))
    await writer.write_immediate([_reading(value=4.2)])
    await writer.stop()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([second]))
    await writer.write_immediate([_reading(value=4.3)])
    await writer.stop()

    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("SELECT descriptor_hash FROM readings ORDER BY id").fetchall() == [
            (first.descriptor_hash,),
            (second.descriptor_hash,),
        ]
        assert conn.execute(
            "SELECT descriptor_revision FROM channel_descriptors ORDER BY descriptor_revision"
        ).fetchall() == [(1,), (2,)]
    finally:
        conn.close()


async def test_unexpected_readings_trigger_rejects_catalog_and_reading_transaction(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    conn = writer._ensure_connection(_reading().timestamp.date())
    conn.execute(
        "CREATE TRIGGER reject_reading BEFORE INSERT ON readings BEGIN SELECT RAISE(ABORT, 'test reading failure'); END"
    )
    conn.commit()

    with pytest.raises(ChannelDescriptorStorageError, match="trigger set"):
        writer._write_day_batch(conn, [_reading()])
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
    await writer.stop()


@pytest.mark.parametrize(
    "message,swallowed",
    [
        ("database or disk is full", True),
        ("database is locked", True),
        ("disk I/O error", False),
    ],
)
def test_every_write_failure_rolls_back_catalog_and_partial_reading(
    tmp_path: Path,
    message: str,
    swallowed: bool,
) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    conn = writer._ensure_connection(_reading().timestamp.date())

    class FailAfterOneInsert:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self.inner = inner

        @property
        def in_transaction(self) -> bool:
            return self.inner.in_transaction

        def execute(self, *args: object, **kwargs: object):
            return self.inner.execute(*args, **kwargs)

        def executemany(self, sql: str, rows: list[tuple[object, ...]]):
            self.inner.execute(sql, rows[0])
            raise sqlite3.OperationalError(message)

        def commit(self) -> None:
            self.inner.commit()

        def rollback(self) -> None:
            self.inner.rollback()

    wrapped = FailAfterOneInsert(conn)
    if swallowed:
        assert writer._write_day_batch(wrapped, [_reading()]) is False  # type: ignore[arg-type]
    else:
        with pytest.raises(sqlite3.OperationalError, match=message):
            writer._write_day_batch(wrapped, [_reading()])  # type: ignore[arg-type]
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
    conn.close()
    writer._conn = None
    writer._executor.shutdown(wait=True)
    writer._read_executor.shutdown(wait=True)


async def test_catalog_rollback_fails_before_new_reading(tmp_path: Path) -> None:
    first = _descriptor()
    second = replace(first, descriptor_revision=2, display_name="revision 2")
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([second]))
    await writer.write_immediate([_reading()])
    await writer.stop()

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([first]))
    with pytest.raises(ChannelDescriptorStorageError, match="conflicts"):
        await writer.write_immediate([_reading(value=5.0)])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (1,)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"channel": "unknown"},
        {"instrument_id": "other"},
        {"unit": "°C"},
        {"instrument_id": ""},
    ],
)
async def test_descriptor_mismatch_rejects_whole_batch_atomically(tmp_path: Path, changes: dict[str, object]) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    with pytest.raises(ChannelDescriptorStorageError):
        await writer.write_immediate([_reading(value=4.2), _reading(value=4.3, **changes)])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
    finally:
        conn.close()


async def test_writer_snapshots_catalog_before_hostile_caller_mutation(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    original_hash = descriptor.descriptor_hash
    object.__setattr__(descriptor, "descriptor_hash", "sha256:" + "0" * 64)
    object.__setattr__(descriptor, "instrument_id", "hostile")

    assert await writer.write_immediate([_reading()]) is True
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("SELECT descriptor_hash FROM readings").fetchone() == (original_hash,)
    finally:
        conn.close()


async def test_append_only_triggers_block_catalog_and_meta_mutation(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM channel_descriptors")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE channel_descriptor_meta SET schema_version=1")
    finally:
        conn.close()


async def test_present_corrupt_envelope_never_downgrades_to_legacy(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        conn.execute("DROP TRIGGER channel_descriptors_no_update")
        conn.execute(
            "UPDATE channel_descriptors SET envelope_json = ? WHERE descriptor_hash = ?",
            (b"{}", descriptor.descriptor_hash),
        )
        conn.execute(_TRIGGERS["channel_descriptors_no_update"])
        conn.commit()
        with pytest.raises(ChannelDescriptorStorageError, match="corrupt"):
            resolve_sqlite_descriptor(
                conn,
                descriptor.descriptor_hash,
                legacy_instrument_id=descriptor.instrument_id,
                legacy_channel=descriptor.channel_id,
                legacy_unit=descriptor.unit,
            )
    finally:
        conn.close()

    legacy_writer = SQLiteWriter(tmp_path)
    with pytest.raises(ChannelDescriptorStorageError, match="corrupt"):
        await legacy_writer.write_immediate([_reading(value=4.3)])
    await legacy_writer.stop()


async def test_noncanonical_envelope_bytes_fail_closed(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        conn.execute("DROP TRIGGER channel_descriptors_no_update")
        payload = conn.execute(
            "SELECT envelope_json FROM channel_descriptors WHERE descriptor_hash = ?",
            (descriptor.descriptor_hash,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE channel_descriptors SET envelope_json = ? WHERE descriptor_hash = ?",
            (b" " + payload, descriptor.descriptor_hash),
        )
        conn.execute(_TRIGGERS["channel_descriptors_no_update"])
        conn.commit()
        with pytest.raises(ChannelDescriptorStorageError, match="canonical"):
            resolve_sqlite_descriptor(
                conn,
                descriptor.descriptor_hash,
                legacy_instrument_id=descriptor.instrument_id,
                legacy_channel=descriptor.channel_id,
                legacy_unit=descriptor.unit,
            )
    finally:
        conn.close()


async def test_hot_reader_enables_foreign_keys_and_returns_frozen_owned_value(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (0,)
        resolved = read_sqlite_reading(conn, 1)
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert resolved.instrument_id == descriptor.instrument_id
        assert resolved.channel == descriptor.channel_id
        assert resolved.descriptor == descriptor
        assert resolved.descriptor is not descriptor
        with pytest.raises((AttributeError, TypeError)):
            resolved.value = 9.0  # type: ignore[misc]
    finally:
        conn.close()


def test_hot_reader_preserves_exact_unmigrated_legacy_row_as_frozen_value(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.execute(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) VALUES (?, ?, ?, ?, ?, ?)",
        (1.0, "legacy", "T1", 4.2, "K", "ok"),
    )
    conn.commit()
    resolved = read_sqlite_reading(conn, 1)
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert resolved.instrument_id == "legacy"
    assert resolved.channel == "T1"
    assert resolved.value == 4.2
    assert resolved.descriptor is None
    with pytest.raises((AttributeError, TypeError)):
        resolved.channel = "mutated"  # type: ignore[misc]
    conn.close()


async def test_present_orphan_hash_never_downgrades_to_legacy(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "UPDATE readings SET descriptor_hash = ?",
            ("sha256:" + "0" * 64,),
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(ChannelDescriptorStorageError, match="foreign-key"):
            resolve_sqlite_descriptor(
                conn,
                "sha256:" + "0" * 64,
                legacy_instrument_id="reference-thermometer",
                legacy_channel="sensor.main",
                legacy_unit="K",
            )
    finally:
        conn.close()


async def test_missing_trigger_fails_closed_on_reopen(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    conn.execute("DROP TRIGGER channel_descriptors_no_delete")
    conn.commit()
    conn.close()

    writer = SQLiteWriter(tmp_path)
    with pytest.raises(ChannelDescriptorStorageError, match="trigger"):
        await writer.write_immediate([_reading(value=4.3)])
    await writer.stop()


async def test_same_columns_with_corrupt_table_contract_fail_closed(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.write_immediate([_reading()])
    await writer.stop()
    conn = sqlite3.connect(str(_db_path(tmp_path)))
    original = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='channel_descriptor_meta'"
    ).fetchone()[0]
    corrupted = original.replace("schema_version = 1", "schema_version >= 1")
    assert corrupted != original
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "UPDATE sqlite_master SET sql=? WHERE type='table' AND name='channel_descriptor_meta'",
        (corrupted,),
    )
    conn.execute("PRAGMA writable_schema=OFF")
    conn.commit()
    conn.close()

    writer = SQLiteWriter(tmp_path)
    with pytest.raises(ChannelDescriptorStorageError, match="table"):
        await writer.write_immediate([_reading(value=4.3)])
    await writer.stop()


def test_failed_migration_statement_rolls_back_every_descriptor_object(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.commit()

    def deny_alter(action: int, _one: str, _two: str, _db: str, _trigger: str) -> int:
        if action == sqlite3.SQLITE_ALTER_TABLE:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_alter)
    with pytest.raises(sqlite3.DatabaseError):
        initialize_descriptor_storage(conn)
    conn.set_authorizer(None)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'channel_descriptor%'").fetchall() == []
    assert [row[1] for row in conn.execute("PRAGMA table_info(readings)")] == [
        "id",
        "timestamp",
        "instrument_id",
        "channel",
        "value",
        "unit",
        "status",
    ]
    initialize_descriptor_storage(conn)
    initialize_descriptor_storage(conn)
    conn.close()


def test_concurrent_legacy_migration_rechecks_schema_inside_write_lock(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    seed = sqlite3.connect(str(path))
    seed.execute(SCHEMA_READINGS)
    seed.commit()
    seed.close()

    initial_schema_read = Event()
    allow_contender = Event()
    contender_error: list[BaseException] = []

    def contender() -> None:
        conn = sqlite3.connect(str(path), timeout=5)

        def trace(statement: str) -> None:
            if statement.startswith("PRAGMA main.table_info(readings)") and not initial_schema_read.is_set():
                initial_schema_read.set()
                assert allow_contender.wait(5)

        conn.set_trace_callback(trace)
        try:
            initialize_descriptor_storage(conn)
        except BaseException as exc:  # pragma: no cover - asserted below
            contender_error.append(exc)
        finally:
            conn.close()

    thread = Thread(target=contender)
    thread.start()
    assert initial_schema_read.wait(5)
    winner = sqlite3.connect(str(path), timeout=5)
    initialize_descriptor_storage(winner)
    winner.close()
    allow_contender.set()
    thread.join(5)
    assert not thread.is_alive()
    assert contender_error == []

    verified = sqlite3.connect(str(path))
    initialize_descriptor_storage(verified)
    assert [row[1] for row in verified.execute("PRAGMA table_info(readings)")].count("descriptor_hash") == 1
    verified.close()


def test_unexpected_catalog_trigger_is_rejected_before_durable_side_effect(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.commit()
    initialize_descriptor_storage(conn)
    conn.execute(
        "CREATE TRIGGER inject_catalog_row AFTER INSERT ON channel_descriptors BEGIN "
        "INSERT INTO channel_descriptors "
        "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
        "VALUES ('sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', "
        "'injected', 'injected', 'injected', 1, X'7B7D'); END"
    )
    conn.commit()
    with pytest.raises(ChannelDescriptorStorageError, match="trigger set"):
        install_catalog(conn, ChannelCatalog([_descriptor()]))
    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (0,)
    conn.close()


@pytest.mark.parametrize(
    "trigger_sql",
    [
        "CREATE TRIGGER inject_from_reading AFTER INSERT ON readings BEGIN "
        "INSERT INTO channel_descriptors "
        "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
        "VALUES ('sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', "
        "'injected', 'injected', 'injected', 1, X'7B7D'); END",
        "CREATE TRIGGER erase_reading_descriptor AFTER INSERT ON readings BEGIN "
        "UPDATE readings SET descriptor_hash = NULL WHERE id = NEW.id; END",
    ],
)
def test_readings_trigger_attacks_are_rejected_and_repeat_without_durable_writes(
    tmp_path: Path,
    trigger_sql: str,
) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    conn = writer._ensure_connection(_reading().timestamp.date())
    conn.execute(trigger_sql)
    conn.commit()

    for _ in range(2):
        with pytest.raises(ChannelDescriptorStorageError, match="trigger set"):
            writer._write_day_batch(conn, [_reading()])
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
    conn.close()
    writer._conn = None
    writer._executor.shutdown(wait=True)
    writer._read_executor.shutdown(wait=True)


def _install_exact_temp_shadow_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TEMP TABLE channel_descriptors (
            descriptor_hash TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            instrument_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            descriptor_revision INTEGER NOT NULL CHECK (descriptor_revision >= 1),
            envelope_json BLOB NOT NULL,
            UNIQUE (channel_id, descriptor_revision),
            UNIQUE (instrument_id, source_key, descriptor_revision)
        );
        CREATE TEMP TABLE readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            instrument_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            status TEXT NOT NULL,
            descriptor_hash TEXT REFERENCES channel_descriptors(descriptor_hash)
        );
        """
    )


def test_writer_rejects_exact_temp_table_shadow_without_diverting_rows(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    conn = writer._ensure_connection(_reading().timestamp.date())
    _install_exact_temp_shadow_tables(conn)

    with pytest.raises(ChannelDescriptorStorageError, match="temporary SQLite object"):
        writer._write_day_batch(conn, [_reading()])

    assert conn.in_transaction is False
    assert conn.execute("SELECT COUNT(*) FROM main.channel_descriptors").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM main.readings").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM temp.channel_descriptors").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM temp.readings").fetchone() == (0,)
    conn.close()
    writer._conn = None
    writer._executor.shutdown(wait=True)
    writer._read_executor.shutdown(wait=True)


async def test_reader_rejects_exact_temp_table_shadow_without_substitution(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    assert await writer.write_immediate([_reading()]) is True
    await writer.stop()

    conn = sqlite3.connect(str(_db_path(tmp_path)))
    _install_exact_temp_shadow_tables(conn)
    with pytest.raises(ChannelDescriptorStorageError, match="temporary SQLite object"):
        read_sqlite_reading(conn, 1)
    assert conn.execute("SELECT COUNT(*) FROM main.readings").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM temp.readings").fetchone() == (0,)
    conn.close()


def test_catalog_cardinality_cap_fails_before_loading_rows(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.commit()
    initialize_descriptor_storage(conn)
    conn.execute("DROP TRIGGER channel_descriptors_no_update")
    conn.execute("DROP TRIGGER channel_descriptors_no_delete")
    conn.executemany(
        "INSERT INTO channel_descriptors "
        "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (
            (f"sha256:{index:064x}", f"channel-{index}", f"instrument-{index}", "input.1", b"{}")
            for index in range(MAX_CATALOG_DESCRIPTORS + 1)
        ),
    )
    conn.execute(_TRIGGERS["channel_descriptors_no_update"])
    conn.execute(_TRIGGERS["channel_descriptors_no_delete"])
    conn.commit()
    with pytest.raises(ChannelDescriptorStorageError, match="bounded"):
        install_catalog(conn, ChannelCatalog([]))
    conn.close()


def test_single_envelope_byte_cap_fails_before_decode(tmp_path: Path) -> None:
    path = _db_path(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA_READINGS)
    conn.commit()
    initialize_descriptor_storage(conn)
    conn.execute(
        "INSERT INTO channel_descriptors "
        "(descriptor_hash, channel_id, instrument_id, source_key, descriptor_revision, envelope_json) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        ("sha256:" + "0" * 64, "channel", "instrument", "input.1", b"x" * 8193),
    )
    conn.commit()
    with pytest.raises(ChannelDescriptorStorageError, match="bounded"):
        install_catalog(conn, ChannelCatalog([]))
    conn.close()
