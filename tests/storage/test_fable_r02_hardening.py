from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread, Timer

import pytest

import cryodaq.storage.sqlite_writer as sqlite_writer_module
from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import (
    ArchiveReader,
    BoundedReadingQueryResult,
    BoundedReadingRow,
)
from cryodaq.storage.broker_replay import ReplaySource
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    LiveChannelDescriptorCatalog,
)
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _descriptor() -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id="probe.1",
        instrument_id="probe",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 1",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )


def _reading(timestamp: datetime, *, value: float = 4.2, channel: str = "probe.1") -> Reading:
    return Reading(
        timestamp=timestamp,
        instrument_id="probe",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
    )


async def test_descriptor_commit_splits_utc_midnight_and_issues_one_exact_receipt(
    tmp_path: Path,
) -> None:
    descriptor = _descriptor()
    owner = LiveChannelDescriptorCatalog(ChannelCatalog((descriptor,)))
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    first = _reading(datetime(2026, 7, 17, 23, 59, 59, tzinfo=UTC), value=1.0)
    second = _reading(first.timestamp + timedelta(seconds=2), value=2.0)

    try:
        receipt = await writer.write_committed([first, second])

        assert receipt is not None
        assert writer.owns_commit(receipt)
        assert receipt.commit_revision == 1
        assert len(receipt.entries) == 2
        assert [entry.reading.value for entry in receipt.entries] == [1.0, 2.0]
        assert all(entry.descriptor_hash == descriptor.descriptor_hash for entry in receipt.entries)
        assert len(writer._issued_commits) == 1

        for day, expected in (("2026-07-17", 1.0), ("2026-07-18", 2.0)):
            conn = sqlite3.connect(str(tmp_path / f"data_{day}.db"))
            try:
                assert conn.execute("SELECT value, descriptor_hash FROM readings").fetchall() == [
                    (expected, descriptor.descriptor_hash)
                ]
            finally:
                conn.close()
    finally:
        await writer.stop()


async def test_descriptor_catalog_full_scan_runs_only_at_connection_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog((_descriptor(),)))
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)

    try:
        assert await writer.write_committed([_reading(now)]) is not None

        def forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("full catalog/FK scan repeated inside a steady-state batch")

        monkeypatch.setattr(sqlite_writer_module, "install_catalog", forbidden)
        monkeypatch.setattr(sqlite_writer_module, "verify_descriptor_storage", forbidden)

        receipt = await writer.write_committed([_reading(now + timedelta(seconds=1), value=5.0)])
        assert receipt is not None
        assert writer._conn is not None
        assert writer._conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert writer._conn.execute("PRAGMA main.foreign_key_check").fetchall() == []
    finally:
        await writer.stop()


async def test_external_fk_tamper_forces_full_validation_before_next_batch(
    tmp_path: Path,
) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog((_descriptor(),)))
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)

    try:
        assert await writer.write_committed([_reading(now)]) is not None
        db_path = tmp_path / "data_2026-07-17.db"
        external = sqlite3.connect(str(db_path))
        try:
            external.execute("PRAGMA foreign_keys=OFF")
            external.execute(
                "INSERT INTO readings "
                "(timestamp, instrument_id, channel, value, unit, status, descriptor_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (now + timedelta(milliseconds=500)).timestamp(),
                    "probe",
                    "probe.1",
                    4.3,
                    "K",
                    "ok",
                    "sha256:" + "f" * 64,
                ),
            )
            external.commit()
        finally:
            external.close()

        with pytest.raises(ChannelDescriptorStorageError, match="foreign-key"):
            await writer.write_committed([_reading(now + timedelta(seconds=1))])

        assert writer._conn is not None
        assert writer._conn.execute(
            "SELECT COUNT(*) FROM readings WHERE timestamp = ?",
            ((now + timedelta(seconds=1)).timestamp(),),
        ).fetchone() == (0,)
    finally:
        await writer.stop()


async def test_first_descriptor_write_verifies_after_external_post_init_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog((_descriptor(),)))
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)
    db_path = tmp_path / "data_2026-07-17.db"
    real_initialize = sqlite_writer_module.initialize_descriptor_storage
    real_verify = sqlite_writer_module.verify_descriptor_storage
    verified_in_transaction: list[bool] = []

    def initialize_then_external_ddl(conn: sqlite3.Connection) -> None:
        real_initialize(conn)
        external = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            external.execute("CREATE TABLE external_post_init_marker (value INTEGER)")
            external.commit()
        finally:
            external.close()

    def observe_verify(conn: sqlite3.Connection) -> None:
        verified_in_transaction.append(conn.in_transaction)
        real_verify(conn)

    monkeypatch.setattr(
        sqlite_writer_module,
        "initialize_descriptor_storage",
        initialize_then_external_ddl,
    )
    monkeypatch.setattr(sqlite_writer_module, "verify_descriptor_storage", observe_verify)
    try:
        receipt = await writer.write_committed([_reading(now)])

        assert receipt is not None
        assert writer.owns_commit(receipt)
        assert verified_in_transaction == [True]
        assert writer._conn is not None
        assert writer._conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (1,)
    finally:
        await writer.stop()


async def test_descriptor_guard_holds_writer_lock_through_receipted_insert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog((_descriptor(),)))
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)
    allow_external = Event()
    external_started = Event()
    external_committed = Event()

    try:
        assert await writer.write_committed([_reading(now)]) is not None
        db_path = tmp_path / "data_2026-07-17.db"

        def install_delete_trigger() -> None:
            assert allow_external.wait(timeout=2.0)
            external = sqlite3.connect(str(db_path), timeout=5.0)
            try:
                external_started.set()
                external.execute(
                    "CREATE TRIGGER erase_receipted_reading AFTER INSERT ON readings "
                    "BEGIN DELETE FROM readings WHERE id = NEW.id; END"
                )
                external.commit()
                external_committed.set()
            finally:
                external.close()

        attacker = Thread(target=install_delete_trigger, daemon=True)
        attacker.start()
        real_guard = writer._verify_descriptor_write_boundary
        real_guard_state = writer._descriptor_guard_state

        def orchestrated_guard_state(conn: sqlite3.Connection) -> tuple[int, int, int]:
            if not conn.in_transaction and external_started.is_set() and not external_committed.is_set():
                # Characterizes the vulnerable post-commit baseline sample:
                # cache the hostile schema only if state is sampled unlocked.
                assert external_committed.wait(timeout=2.0)
            return real_guard_state(conn)

        def orchestrated_guard(conn: sqlite3.Connection) -> None:
            real_guard(conn)
            allow_external.set()
            assert external_started.wait(timeout=2.0)
            if conn.in_transaction:
                assert not external_committed.wait(timeout=0.1)
            else:
                # Characterizes the vulnerable pre-lock order: the hostile DDL
                # commits before BEGIN IMMEDIATE and erases the next insert.
                assert external_committed.wait(timeout=2.0)

        monkeypatch.setattr(writer, "_descriptor_guard_state", orchestrated_guard_state)
        monkeypatch.setattr(writer, "_verify_descriptor_write_boundary", orchestrated_guard)
        second_time = now + timedelta(seconds=1)
        receipt = await writer.write_committed([_reading(second_time, value=5.0)])
        assert receipt is not None
        assert writer.owns_commit(receipt)

        await asyncio.to_thread(attacker.join, 5.0)
        assert not attacker.is_alive()
        assert external_committed.is_set()
        assert writer._conn is not None
        assert writer._conn.execute(
            "SELECT value FROM readings WHERE timestamp = ?",
            (second_time.timestamp(),),
        ).fetchall() == [(5.0,)]

        monkeypatch.setattr(writer, "_verify_descriptor_write_boundary", real_guard)
        third_time = now + timedelta(seconds=2)
        with pytest.raises(ChannelDescriptorStorageError, match="trigger"):
            await writer.write_committed([_reading(third_time, value=6.0)])
        assert writer._commit_revision == 2
        assert (
            writer._conn.execute(
                "SELECT value FROM readings WHERE timestamp = ?",
                (third_time.timestamp(),),
            ).fetchall()
            == []
        )
    finally:
        allow_external.set()
        await writer.stop()


async def test_replay_unknown_status_never_becomes_ok(tmp_path: Path) -> None:
    ts = datetime(2026, 7, 17, 12, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    try:
        assert writer._write_batch([_reading(ts)])
    finally:
        await writer.stop()
    db_path = tmp_path / "data_2026-07-17.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE readings SET status = 'future_unknown_status'")
        conn.commit()
    finally:
        conn.close()

    broker = DataBroker()
    queue = await broker.subscribe("test", maxsize=10)
    assert await ReplaySource(broker, speed=0.0).play(db_path) == 1

    replayed = queue.get_nowait()
    assert replayed.status is ChannelStatus.SENSOR_ERROR
    assert replayed.status is not ChannelStatus.OK
    assert not replayed.is_usable()


async def test_hot_replay_sqlite_load_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data_2026-07-17.db"
    db_path.touch()
    replay = ReplaySource(DataBroker(), speed=0.0)
    entered = Event()
    release = Event()

    def blocked_load(*_args: object, **_kwargs: object) -> list:
        entered.set()
        assert release.wait(timeout=2.0)
        return []

    monkeypatch.setattr(replay, "_load_rows", blocked_load)
    timer = Timer(0.35, release.set)
    timer.start()
    started = time.monotonic()
    task = asyncio.create_task(replay.play(db_path))
    try:
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - started
        release.set()
        assert await task == 0
    finally:
        release.set()
        timer.cancel()
        if not task.done():
            await task

    assert entered.is_set()
    assert elapsed < 0.20, f"event loop was blocked by SQLite replay load for {elapsed:.3f}s"


async def test_stop_during_hot_replay_load_prevents_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data_2026-07-17.db"
    db_path.touch()
    broker = DataBroker()
    queue = await broker.subscribe("test", maxsize=10)
    replay = ReplaySource(broker, speed=0.0)
    entered = Event()
    release = Event()

    def blocked_load(*_args: object, **_kwargs: object) -> list[tuple]:
        entered.set()
        assert release.wait(timeout=2.0)
        return [
            (
                datetime(2026, 7, 17, 12, tzinfo=UTC).timestamp(),
                "probe.1",
                4.2,
                "K",
                "ok",
                "probe",
            )
        ]

    monkeypatch.setattr(replay, "_load_rows", blocked_load)
    task = asyncio.create_task(replay.play(db_path))
    try:
        assert await asyncio.to_thread(entered.wait, 2.0)
        replay.stop()
        release.set()
        assert await asyncio.wait_for(task, timeout=2.0) == 0
    finally:
        release.set()
        if not task.done():
            await task

    assert queue.empty()
    assert replay.total_replayed == 0


async def test_stop_during_cold_directory_load_cannot_rearm_next_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    broker = DataBroker()
    queue = await broker.subscribe("test", maxsize=10)
    replay = ReplaySource(broker, speed=0.0)
    monkeypatch.setattr(
        replay,
        "_archived_days",
        lambda _reader: {"2026-07-17", "2026-07-18"},
    )
    entered = Event()
    release = Event()
    queried_days: list[str] = []

    def blocked_query(
        _reader: ArchiveReader,
        start: datetime,
        _end: datetime,
        _channels: list[str] | None,
        _limit: int | None,
    ) -> list[tuple]:
        queried_days.append(start.date().isoformat())
        if len(queried_days) == 1:
            entered.set()
            assert release.wait(timeout=2.0)
        return [(start.isoformat(), "probe", "probe.1", 4.2, "K", "ok")]

    monkeypatch.setattr(ArchiveReader, "query_rows", blocked_query)
    task = asyncio.create_task(replay.play_directory(data_dir))
    try:
        assert await asyncio.to_thread(entered.wait, 2.0)
        replay.stop()
        release.set()
        assert await asyncio.wait_for(task, timeout=2.0) == 0
    finally:
        release.set()
        if not task.done():
            await task

    assert queried_days == ["2026-07-17"]
    assert queue.empty()
    assert replay.total_replayed == 0


async def test_operator_log_read_does_not_execute_ddl_on_legacy_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data_2026-07-17.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE legacy_marker (value TEXT)")
        conn.commit()
    finally:
        conn.close()

    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: object, **kwargs: object):
        traced = real_connect(*args, **kwargs)
        traced.set_trace_callback(statements.append)
        return traced

    monkeypatch.setattr(sqlite_writer_module.sqlite3, "connect", traced_connect)
    writer = SQLiteWriter(tmp_path)
    try:
        assert writer._read_operator_log() == []
    finally:
        await writer.stop()

    mutating = ("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "REPLACE")
    assert not [sql for sql in statements if sql.lstrip().upper().startswith(mutating)]
    check = real_connect(str(db_path))
    try:
        assert (
            check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operator_log'").fetchone()
            is None
        )
    finally:
        check.close()


async def test_unfiltered_history_has_one_absolute_cross_file_row_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = datetime(2026, 7, 16, 12, tzinfo=UTC)
    new = datetime(2026, 7, 17, 12, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    try:
        assert writer._write_batch(
            [_reading(old + timedelta(seconds=i), value=float(i)) for i in range(3)]
            + [_reading(new + timedelta(seconds=i), value=float(10 + i)) for i in range(3)]
        )
        monkeypatch.setattr(sqlite_writer_module, "_HISTORY_MAX_TOTAL_ROWS", 3, raising=False)

        history = writer._read_readings_history(limit_per_channel=100)
        values = [value for points in history.values() for _, value in points]

        assert len(values) <= 3
        assert values == [10.0, 11.0, 12.0]
    finally:
        await writer.stop()


async def test_filtered_hot_history_spends_deduplicated_deficits_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    oldest = datetime(2026, 7, 15, 12, tzinfo=UTC)
    middle = datetime(2026, 7, 16, 12, tzinfo=UTC)
    newest = datetime(2026, 7, 17, 12, tzinfo=UTC)
    try:
        assert writer._write_batch(
            [
                _reading(oldest, channel="A", value=1.0),
                _reading(oldest, channel="B", value=2.0),
                _reading(middle, channel="A", value=3.0),
                _reading(middle + timedelta(seconds=1), channel="A", value=4.0),
                _reading(middle, channel="B", value=5.0),
                _reading(newest, channel="A", value=6.0),
                _reading(newest + timedelta(seconds=1), channel="A", value=7.0),
                _reading(newest, channel="B", value=8.0),
            ]
        )
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        (archive_dir / "index.json").write_text('{"files": []}', encoding="utf-8")

        real_connect = sqlite_writer_module.sqlite3.connect
        opened: list[str] = []
        statements: dict[str, list[str]] = {}

        def traced_connect(path: str, *args: object, **kwargs: object):
            name = Path(path).name
            opened.append(name)
            conn = real_connect(path, *args, **kwargs)
            statements.setdefault(name, [])
            conn.set_trace_callback(statements[name].append)
            return conn

        def forbidden_index_read(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("fully satisfied hot request touched archive authority")

        monkeypatch.setattr(sqlite_writer_module.sqlite3, "connect", traced_connect)
        monkeypatch.setattr(ArchiveReader, "_read_bounded_index", forbidden_index_read)
        monkeypatch.setattr(ArchiveReader, "_load_index", forbidden_index_read)
        history = writer._read_readings_history(
            channels=["A", "A", "B"],
            limit_per_channel=2,
        )

        assert [value for _, value in history["A"]] == [6.0, 7.0]
        assert [value for _, value in history["B"]] == [5.0, 8.0]
        assert opened == ["data_2026-07-17.db", "data_2026-07-16.db"]
        middle_sql = "\n".join(statements["data_2026-07-16.db"])
        assert "channel = 'B'" in middle_sql
        assert "channel = 'A'" not in middle_sql
    finally:
        await writer.stop()


async def test_filtered_hot_history_discards_partial_file_on_malformed_real(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    old = datetime(2026, 7, 16, 12, tzinfo=UTC)
    new = datetime(2026, 7, 17, 12, tzinfo=UTC)
    try:
        assert writer._write_batch(
            [
                _reading(old, channel="A", value=1.0),
                _reading(old + timedelta(seconds=1), channel="A", value=2.0),
                _reading(new, channel="A", value=3.0),
                _reading(new + timedelta(seconds=1), channel="A", value=4.0),
            ]
        )
        for day, malformed_ts in (("2026-07-16", old), ("2026-07-17", new)):
            conn = sqlite3.connect(str(tmp_path / f"data_{day}.db"))
            try:
                conn.execute(
                    "UPDATE readings SET value = 'malformed-real' WHERE timestamp = ?",
                    (malformed_ts.timestamp(),),
                )
                conn.commit()
            finally:
                conn.close()

        history = writer._read_readings_history(channels=["A"], limit_per_channel=2)

        assert history == {}
    finally:
        await writer.stop()


async def test_cold_history_uses_pre_materialization_row_byte_and_window_caps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "index.json").write_text(
        '{"files": [{"original_name": "data_2026-06-01.db"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sqlite_writer_module, "_HISTORY_MAX_TOTAL_ROWS", 3)
    monkeypatch.setattr(
        ArchiveReader,
        "_load_index",
        lambda _self: (_ for _ in ()).throw(AssertionError("legacy unbounded index read called")),
    )

    def legacy_query_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy cold query materializes the interval before applying caps")

    calls: list[dict[str, object]] = []
    retained_per_call = 16 * 1024 * 1024

    def bounded_query(_self: ArchiveReader, **kwargs: object) -> BoundedReadingQueryResult:
        calls.append(kwargs)
        start = kwargs["start"]
        end = kwargs["end"]
        assert isinstance(start, datetime)
        assert isinstance(end, datetime)
        assert end - start <= timedelta(hours=168)
        assert 2 <= kwargs["max_total_points"] <= 3
        assert 2 <= kwargs["max_points_per_channel"] <= 3
        assert kwargs["max_retained_bytes"] == 32 * 1024 * 1024 - retained_per_call * len(calls[:-1])
        row = BoundedReadingRow(
            timestamp=end.timestamp() - 1.0,
            instrument_id="probe",
            channel="probe.1",
            value=None if len(calls) == 1 else float(len(calls)),
            unit="K",
            status="ok",
        )
        return BoundedReadingQueryResult(
            rows=(row,),
            complete=True,
            truncated=False,
            issues=(),
            issue_overflow=0,
            discovered_channels=("probe.1",),
            rows_examined=1,
            rows_dropped_by_caps=0,
            retained_encoded_bytes=retained_per_call,
        )

    monkeypatch.setattr(ArchiveReader, "query", legacy_query_forbidden)
    monkeypatch.setattr(ArchiveReader, "query_reading_rows_bounded", bounded_query)
    writer = SQLiteWriter(tmp_path)
    try:
        history = writer._read_readings_history(
            to_ts=datetime(2026, 7, 20, tzinfo=UTC).timestamp(),
            limit_per_channel=100,
        )
        assert len(calls) == 2
        assert len({call["deadline_monotonic"] for call in calls}) == 1
        assert sum(len(points) for points in history.values()) == 2
        values = [value for _, value in history["probe.1"]]
        assert values[0] == 2.0
        assert math.isnan(values[1])
    finally:
        await writer.stop()


async def test_filtered_cold_history_preserves_each_channel_deficit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hot_time = datetime(2026, 7, 17, 12, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    try:
        assert writer._write_batch(
            [
                Reading(
                    timestamp=hot_time + timedelta(seconds=index),
                    instrument_id="probe",
                    channel="A",
                    value=float(100 + index),
                    unit="K",
                    status=ChannelStatus.OK,
                )
                for index in range(9)
            ]
        )
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        (archive_dir / "index.json").write_text(
            '{"files": [{"original_name": "data_2026-07-01.db"}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            ArchiveReader,
            "_load_index",
            lambda _self: (_ for _ in ()).throw(AssertionError("legacy unbounded index read called")),
        )
        monkeypatch.setattr(
            ArchiveReader,
            "query",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy query called")),
        )

        def bounded_query(_self: ArchiveReader, **kwargs: object) -> BoundedReadingQueryResult:
            selected = kwargs["channels"]
            assert isinstance(selected, list) and len(selected) == 1
            channel = selected[0]
            cap = int(kwargs["max_total_points"])
            rows = tuple(
                BoundedReadingRow(
                    timestamp=datetime(2026, 7, 16, tzinfo=UTC).timestamp() + index,
                    instrument_id="probe",
                    channel=channel,
                    value=float(index),
                    unit="K",
                    status="ok",
                )
                for index in range(cap)
            )
            return BoundedReadingQueryResult(
                rows=rows,
                complete=True,
                truncated=False,
                issues=(),
                issue_overflow=0,
                discovered_channels=(channel,),
                rows_examined=len(rows),
                rows_dropped_by_caps=0,
                retained_encoded_bytes=64 * len(rows),
            )

        monkeypatch.setattr(ArchiveReader, "query_reading_rows_bounded", bounded_query)
        history = writer._read_readings_history(channels=["A", "B"], limit_per_channel=10)

        assert len(history["A"]) == 10
        assert len(history["B"]) == 10
        assert history["A"][-1][1] == 108.0
    finally:
        await writer.stop()
