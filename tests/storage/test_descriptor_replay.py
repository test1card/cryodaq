from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import (
    ArchiveReader,
    BoundedReadingQueryResult,
    BoundedReadingRow,
    BoundedReadIssueCode,
)
from cryodaq.storage.broker_replay import DescriptorReplayReader
from cryodaq.storage.channel_descriptors import (
    _TRIGGERS,
    initialize_descriptor_storage,
    install_catalog,
)
from cryodaq.storage.sqlite_writer import SCHEMA_READINGS


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    fields: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "stage-top",
        "instrument_id": "thermometer-a",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Cryostat stage",
        "display_name": "Top plate",
        "visible_by_default": True,
        "display_order": 7,
        "descriptor_revision": 2,
    }
    fields.update(changes)
    return ChannelDescriptorV1(**fields)  # type: ignore[arg-type]


def _write_hot(
    data_dir: Path,
    day: str,
    descriptor: ChannelDescriptorV1,
    rows: list[tuple[datetime, float]],
) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"data_{day}.db"
    connection = sqlite3.connect(path)
    connection.execute(SCHEMA_READINGS)
    initialize_descriptor_storage(connection)
    install_catalog(connection, ChannelCatalog([descriptor]))
    connection.executemany(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status,descriptor_hash) VALUES(?,?,?,?,?,?,?)",
        [
            (
                timestamp.timestamp(),
                descriptor.instrument_id,
                descriptor.channel_id,
                value,
                descriptor.unit,
                "ok",
                descriptor.descriptor_hash,
            )
            for timestamp, value in rows
        ],
    )
    connection.commit()
    connection.close()
    return path


def _write_legacy_hot(data_dir: Path, day: str, timestamp: datetime) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_dir / f"data_{day}.db")
    connection.executescript(
        """
        CREATE TABLE readings(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp REAL NOT NULL,
          instrument_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          value REAL NOT NULL,
          unit TEXT NOT NULL,
          status TEXT NOT NULL
        );
        CREATE INDEX idx_readings_ts ON readings(timestamp);
        CREATE INDEX idx_channel_ts ON readings(channel, timestamp);
        """
    )
    connection.execute(
        "INSERT INTO readings(timestamp,instrument_id,channel,value,unit,status) VALUES(?,?,?,?,?,?)",
        (timestamp.timestamp(), "legacy-meter", "CH1", 4.5, "K", "ok"),
    )
    connection.commit()
    connection.close()


def _write_cold(
    archive_dir: Path,
    day: str,
    descriptor: ChannelDescriptorV1,
    rows: list[tuple[datetime, float]],
) -> bytes:
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    relative = Path(f"year={day[:4]}") / f"data_{day}.parquet"
    path = archive_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "timestamp": pa.array([row[0] for row in rows], type=pa.timestamp("us", tz="UTC")),
                "instrument_id": pa.array([descriptor.instrument_id] * len(rows), type=pa.string()),
                "channel": pa.array([descriptor.channel_id] * len(rows), type=pa.string()),
                "value": pa.array([row[1] for row in rows], type=pa.float64()),
                "unit": pa.array([descriptor.unit] * len(rows), type=pa.string()),
                "status": pa.array(["ok"] * len(rows), type=pa.string()),
                "descriptor_hash": pa.array([descriptor.descriptor_hash] * len(rows), type=pa.string()),
            }
        ),
        path,
    )
    sidecar_relative = relative.with_name(relative.stem + ".channel_descriptors.parquet")
    sidecar = archive_dir / sidecar_relative
    pq.write_table(
        pa.table(
            {
                "descriptor_hash": pa.array([descriptor.descriptor_hash], type=pa.string()),
                "channel_id": pa.array([descriptor.channel_id], type=pa.string()),
                "instrument_id": pa.array([descriptor.instrument_id], type=pa.string()),
                "source_key": pa.array([descriptor.source_key], type=pa.string()),
                "descriptor_revision": pa.array([descriptor.descriptor_revision], type=pa.int32()),
                "envelope_json": pa.array([envelope], type=pa.binary()),
            }
        ),
        sidecar,
    )
    (archive_dir / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": f"data_{day}.db",
                        "archive_path": relative.as_posix(),
                        "channel_descriptors_path": sidecar_relative.as_posix(),
                        "channel_descriptors_rows": 1,
                        "channel_descriptors_checksum": hashlib.md5(sidecar.read_bytes()).hexdigest(),
                        "channel_descriptors_size_bytes": sidecar.stat().st_size,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return envelope


async def test_descriptor_replay_preserves_hot_envelope_and_all_display_fields(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor()
    _write_hot(tmp_path / "data", "2026-07-10", descriptor, [(start, 4.2)])

    event_loop_thread = threading.get_ident()
    observed_threads: list[int] = []
    original = ArchiveReader.query_reading_rows_bounded

    def recording_query(self: ArchiveReader, **kwargs: object):
        observed_threads.append(threading.get_ident())
        return original(self, **kwargs)  # type: ignore[arg-type]

    ArchiveReader.query_reading_rows_bounded = recording_query  # type: ignore[method-assign]
    try:
        batch = await DescriptorReplayReader(tmp_path / "data").read_window(
            start=start,
            end=start + timedelta(seconds=1),
            channels=(descriptor.channel_id,),
        )
    finally:
        ArchiveReader.query_reading_rows_bounded = original  # type: ignore[method-assign]

    assert batch.complete is True
    assert len(batch.readings) == 1
    reading = batch.readings[0]
    assert observed_threads and observed_threads[0] != event_loop_thread
    assert reading.descriptor_envelope == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    assert (
        reading.descriptor.display_group,
        reading.descriptor.display_name,
        reading.descriptor.visible_by_default,
        reading.descriptor.display_order,
    ) == ("Cryostat stage", "Top plate", True, 7)
    assert reading.descriptor.legacy is False
    assert reading.grants_control_authority is False
    assert batch.grants_control_authority is False


async def test_descriptor_replay_overlap_keeps_archived_value_and_matching_descriptor_atomically(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor()
    _write_cold(tmp_path / "archive", "2026-07-10", descriptor, [(start, 10.0)])
    _write_hot(tmp_path / "data", "2026-07-10", descriptor, [(start, 99.0)])

    batch = await DescriptorReplayReader(tmp_path / "data", tmp_path / "archive").read_window(
        start=start,
        end=start + timedelta(seconds=1),
        channels=(descriptor.channel_id,),
    )

    assert batch.complete is True
    assert [(row.value, row.descriptor.descriptor_hash) for row in batch.readings] == [
        (10.0, descriptor.descriptor_hash)
    ]


async def test_descriptor_replay_reads_pure_cold_row_with_original_envelope(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor(display_name="Archived top plate")
    envelope = _write_cold(tmp_path / "archive", "2026-07-10", descriptor, [(start, 8.5)])

    batch = await DescriptorReplayReader(tmp_path / "data", tmp_path / "archive").read_window(
        start=start,
        end=start + timedelta(seconds=1),
        channels=(descriptor.channel_id,),
    )

    assert batch.complete is True
    assert [(row.value, row.descriptor_envelope) for row in batch.readings] == [(8.5, envelope)]
    assert batch.readings[0].descriptor.display_name == "Archived top plate"


async def test_descriptor_replay_keeps_genuine_legacy_explicit_and_unavailable(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    _write_legacy_hot(tmp_path / "data", "2026-07-10", start)

    batch = await DescriptorReplayReader(tmp_path / "data").read_window(
        start=start,
        end=start + timedelta(seconds=1),
        channels=("CH1",),
    )

    assert batch.complete is True
    reading = batch.readings[0]
    assert reading.descriptor.legacy is True
    assert reading.descriptor.quantity == "legacy_unknown"
    assert reading.descriptor.role == "legacy_unknown"
    assert reading.descriptor.safety_class == "legacy_unknown"
    assert reading.descriptor_envelope is None


async def test_descriptor_replay_omits_corrupt_descriptor_rows_without_legacy_downgrade(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    descriptor = _descriptor()
    path = _write_hot(tmp_path / "data", "2026-07-10", descriptor, [(start, 4.2)])
    connection = sqlite3.connect(path)
    connection.execute("DROP TRIGGER channel_descriptors_no_update")
    connection.execute(
        "UPDATE channel_descriptors SET envelope_json=? WHERE descriptor_hash=?",
        (b"{}", descriptor.descriptor_hash),
    )
    connection.execute(_TRIGGERS["channel_descriptors_no_update"])
    connection.commit()
    connection.close()

    batch = await DescriptorReplayReader(tmp_path / "data").read_window(
        start=start,
        end=start + timedelta(seconds=1),
        channels=(descriptor.channel_id,),
    )

    assert batch.readings == ()
    assert batch.complete is False
    assert BoundedReadIssueCode.DESCRIPTOR_INDEX_MISMATCH in {issue.code for issue in batch.issues}


async def test_descriptor_replay_rejects_unbounded_deadline(tmp_path: Path) -> None:
    start = datetime(2026, 7, 10, tzinfo=UTC)
    reader = DescriptorReplayReader(tmp_path / "data")

    for invalid in (0.0, 301.0, float("inf")):
        try:
            await reader.read_window(
                start=start,
                end=start + timedelta(seconds=1),
                deadline_seconds=invalid,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"deadline {invalid!r} was accepted")


def test_descriptor_replay_adapter_fails_closed_if_reader_contract_loses_descriptor() -> None:
    result = BoundedReadingQueryResult(
        rows=(
            BoundedReadingRow(
                timestamp=1.0,
                instrument_id="i",
                channel="T",
                value=4.2,
                unit="K",
                status="ok",
                descriptor=None,
            ),
        ),
        complete=True,
        truncated=False,
        issues=(),
        issue_overflow=0,
        discovered_channels=("T",),
        rows_examined=1,
        rows_dropped_by_caps=0,
        retained_encoded_bytes=64,
    )

    batch = DescriptorReplayReader._from_query_result(result)

    assert batch.readings == ()
    assert batch.complete is False
    assert [issue.code for issue in batch.issues] == [BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING]


async def test_descriptor_replay_cancellation_waits_for_blocked_query_settlement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    settled = threading.Event()
    active_queries = 0
    active_lock = threading.Lock()

    def blocked_query(self: ArchiveReader, **kwargs: object) -> BoundedReadingQueryResult:
        nonlocal active_queries
        del self, kwargs
        with active_lock:
            active_queries += 1
        started.set()
        try:
            assert release.wait(timeout=5.0), "test did not release blocked replay query"
            return BoundedReadingQueryResult(
                rows=(),
                complete=True,
                truncated=False,
                issues=(),
                issue_overflow=0,
                discovered_channels=(),
                rows_examined=0,
                rows_dropped_by_caps=0,
                retained_encoded_bytes=0,
            )
        finally:
            with active_lock:
                active_queries -= 1
            settled.set()

    monkeypatch.setattr(ArchiveReader, "query_reading_rows_bounded", blocked_query)
    start = datetime(2026, 7, 10, tzinfo=UTC)
    read_task = asyncio.create_task(
        DescriptorReplayReader(tmp_path / "data").read_window(
            start=start,
            end=start + timedelta(seconds=1),
        )
    )
    assert await asyncio.to_thread(started.wait, 2.0)

    read_task.cancel("first cancellation")
    await asyncio.sleep(0)
    assert read_task.done() is False
    assert settled.is_set() is False
    with active_lock:
        assert active_queries == 1

    read_task.cancel("repeated cancellation")
    await asyncio.sleep(0)
    assert read_task.done() is False
    assert settled.is_set() is False

    release.set()
    try:
        await asyncio.wait_for(read_task, timeout=2.0)
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("descriptor replay cancellation did not propagate")

    assert settled.is_set() is True
    with active_lock:
        assert active_queries == 0
    await asyncio.sleep(0)
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name() == "descriptor-replay-bounded-query"
    ]


async def test_descriptor_replay_worker_exception_after_repeated_cancel_is_retrieved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    settled = threading.Event()
    active_queries = 0
    active_lock = threading.Lock()

    def exploding_query(self: ArchiveReader, **kwargs: object) -> BoundedReadingQueryResult:
        nonlocal active_queries
        del self, kwargs
        with active_lock:
            active_queries += 1
        started.set()
        try:
            assert release.wait(timeout=5.0), "test did not release exploding replay query"
            raise RuntimeError("bounded replay worker boom")
        finally:
            with active_lock:
                active_queries -= 1
            settled.set()

    monkeypatch.setattr(ArchiveReader, "query_reading_rows_bounded", exploding_query)
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop_events: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: loop_events.append(dict(context)))
    start = datetime(2026, 7, 10, tzinfo=UTC)
    try:
        read_task = asyncio.create_task(
            DescriptorReplayReader(tmp_path / "data").read_window(
                start=start,
                end=start + timedelta(seconds=1),
            )
        )
        assert await asyncio.to_thread(started.wait, 2.0)

        read_task.cancel("first cancellation")
        await asyncio.sleep(0)
        assert read_task.done() is False
        read_task.cancel("repeated cancellation")
        await asyncio.sleep(0)
        assert read_task.done() is False

        release.set()
        try:
            await asyncio.wait_for(read_task, timeout=2.0)
        except asyncio.CancelledError as cancellation:
            assert cancellation.args == ("first cancellation",)
        else:
            raise AssertionError("worker exception displaced caller cancellation")

        assert settled.is_set() is True
        with active_lock:
            assert active_queries == 0
        del read_task
        gc.collect()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert loop_events == []
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and not task.done()
            and task.get_name() == "descriptor-replay-bounded-query"
        ]
    finally:
        release.set()
        loop.set_exception_handler(previous_handler)
