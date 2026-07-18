from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog
from cryodaq.storage.sqlite_writer import (
    CommittedBatchReceipt,
    CommittedReadingReceipt,
    SQLiteWriter,
)


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _descriptor(*, channel_id: str = "probe.1", instrument_id: str = "probe") -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id=instrument_id,
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 1",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=3,
    )


def _owner(*descriptors: ChannelDescriptorV1) -> LiveChannelDescriptorCatalog:
    return LiveChannelDescriptorCatalog(ChannelCatalog(descriptors or (_descriptor(),)))


def _reading(
    *,
    channel: str = "probe.1",
    instrument_id: str = "probe",
    value: float = 4.2,
    raw: float | None = 118.25,
    metadata: dict | None = None,
    timestamp: datetime | None = None,
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    return Reading(
        timestamp=timestamp or datetime(2026, 7, 12, 12, tzinfo=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit="K",
        status=status,
        raw=raw,
        metadata={"calibration": {"source": [1, 2]}} if metadata is None else metadata,
    )


def _db(root: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(root / "data_2026-07-12.db"))


async def test_commit_receipt_is_issued_only_after_exact_transaction_commit(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner(descriptor))

    receipt = await writer.write_committed([_reading()])

    assert type(receipt) is CommittedBatchReceipt
    assert writer.owns_commit(receipt)
    assert receipt is not None
    assert receipt.grants_control_authority is False
    assert receipt.commit_revision == 1
    assert len(receipt.entries) == 1
    entry = receipt.entries[0]
    assert type(entry) is CommittedReadingReceipt
    assert entry.channel_id == descriptor.channel_id
    assert entry.descriptor_hash == descriptor.descriptor_hash
    assert entry.descriptor_revision == 3
    assert entry.descriptor_envelope == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    assert entry.grants_control_authority is False
    assert entry.reading.raw == 118.25
    assert writer.readings_from_commit(receipt) == [entry.reading]

    conn = _db(tmp_path)
    try:
        assert conn.execute("SELECT channel, descriptor_hash FROM readings").fetchall() == [
            (descriptor.channel_id, descriptor.descriptor_hash)
        ]
        assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (1,)
    finally:
        conn.close()
    await writer.stop()


async def test_receipted_and_published_channel_is_canonical_for_aliased_emitted_channel(
    tmp_path: Path,
) -> None:
    """F-1 regression: emitted_channel != channel_id must not leak the raw label.

    The receipted (and therefore Scheduler-published) Reading.channel must
    equal descriptor.channel_id, matching entry.channel_id and the persisted
    SQLite row exactly — never the raw driver-emitted lookup label.
    """
    descriptor = _descriptor(channel_id="T1", instrument_id="LS218_1")
    owner = LiveChannelDescriptorCatalog(
        ChannelCatalog((descriptor,)),
        bindings={("LS218_1", "T1 Cryostat top"): "T1"},
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)

    receipt = await writer.write_committed([_reading(channel="T1 Cryostat top", instrument_id="LS218_1")])

    assert receipt is not None
    entry = receipt.entries[0]
    assert entry.channel_id == "T1"
    assert entry.reading.channel == "T1"
    assert entry.reading.channel == entry.channel_id
    assert writer.readings_from_commit(receipt)[0].channel == "T1"

    conn = _db(tmp_path)
    try:
        assert conn.execute("SELECT channel FROM readings").fetchall() == [("T1",)]
    finally:
        conn.close()
    await writer.stop()


async def test_receipt_readings_are_fresh_and_original_metadata_mutation_cannot_rewrite_evidence(
    tmp_path: Path,
) -> None:
    metadata = {"calibration": {"source": [1, 2]}}
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    receipt = await writer.write_committed([_reading(metadata=metadata)])
    assert receipt is not None
    metadata["calibration"]["source"].append(99)

    first = writer.readings_from_commit(receipt)[0]
    second = writer.readings_from_commit(receipt)[0]
    first.metadata["calibration"]["source"].append(42)

    assert second.metadata == {"calibration": {"source": [1, 2]}}
    assert first is not second
    assert writer.owns_commit(receipt)
    await writer.stop()


async def test_receipt_constructors_cross_owner_and_mutation_are_rejected(tmp_path: Path) -> None:
    first = SQLiteWriter(tmp_path / "first", channel_catalog=_owner())
    second = SQLiteWriter(tmp_path / "second", channel_catalog=_owner())
    receipt = await first.write_committed([_reading()])
    assert receipt is not None

    with pytest.raises(TypeError, match="issued only"):
        CommittedBatchReceipt()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="issued only"):
        CommittedReadingReceipt()  # type: ignore[call-arg]
    assert not second.owns_commit(receipt)
    with pytest.raises(TypeError, match="foreign, forged, or mutated"):
        second.readings_from_commit(receipt)

    entry = receipt.entries[0]
    object.__setattr__(entry, "descriptor_hash", "sha256:" + "0" * 64)
    assert not first.owns_commit(receipt)
    with pytest.raises(TypeError, match="foreign, forged, or mutated"):
        first.readings_from_commit(receipt)
    await first.stop()
    await second.stop()


@pytest.mark.parametrize(
    "bad",
    [
        _reading(channel="unknown"),
        _reading(instrument_id="other"),
        _reading(value=float("nan"), status=ChannelStatus.OK),
    ],
)
async def test_partial_invalid_batch_rolls_back_catalog_and_all_rows(
    tmp_path: Path,
    bad: Reading,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    with pytest.raises((TypeError, ValueError, RuntimeError)):
        await writer.write_committed([_reading(), bad])

    path = tmp_path / "data_2026-07-12.db"
    if path.exists():
        conn = _db(tmp_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
            assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (0,)
        finally:
            conn.close()
    assert len(writer._issued_commits) == 0
    await writer.stop()


async def test_midnight_crossing_descriptor_batch_commits_each_day_before_one_receipt(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    first = _reading()
    second = _reading(timestamp=first.timestamp + timedelta(days=1))

    receipt = await writer.write_committed([first, second])

    assert receipt is not None
    assert writer.owns_commit(receipt)
    assert [entry.reading for entry in receipt.entries] == [first, second]
    db_names = await asyncio.to_thread(lambda: sorted(path.name for path in tmp_path.glob("data_*.db")))
    assert db_names == [
        "data_2026-07-12.db",
        "data_2026-07-13.db",
    ]
    for day in ("2026-07-12", "2026-07-13"):
        conn = sqlite3.connect(str(tmp_path / f"data_{day}.db"))
        try:
            assert conn.execute("SELECT COUNT(*) FROM readings").fetchone() == (1,)
            assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (1,)
        finally:
            conn.close()
    assert len(writer._issued_commits) == 1
    await writer.stop()


@pytest.mark.parametrize("failure_mode", ["swallowed", "raised"])
async def test_midnight_partial_commit_never_issues_whole_batch_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    first = _reading()
    second = _reading(timestamp=first.timestamp + timedelta(days=1))
    real_write = writer._write_day_batch
    call_count = 0

    def fail_second_day(conn: sqlite3.Connection, batch: list[Reading]) -> bool:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return real_write(conn, batch)
        if failure_mode == "swallowed":
            return False
        raise sqlite3.OperationalError("simulated second-day persistence failure")

    monkeypatch.setattr(writer, "_write_day_batch", fail_second_day)
    if failure_mode == "swallowed":
        assert await writer.write_committed([first, second]) is None
    else:
        with pytest.raises(sqlite3.OperationalError, match="second-day"):
            await writer.write_committed([first, second])

    assert writer._commit_revision == 0
    assert len(writer._issued_commits) == 0
    first_db = sqlite3.connect(str(tmp_path / "data_2026-07-12.db"))
    second_db = sqlite3.connect(str(tmp_path / "data_2026-07-13.db"))
    try:
        assert first_db.execute("SELECT COUNT(*) FROM readings").fetchone() == (1,)
        assert second_db.execute("SELECT COUNT(*) FROM readings").fetchone() == (0,)
    finally:
        first_db.close()
        second_db.close()
        await writer.stop()


async def test_swallowed_persistence_failure_returns_no_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    monkeypatch.setattr(writer, "_write_day_batch", lambda _conn, _batch: False)

    assert await writer.write_committed([_reading()]) is None
    assert len(writer._issued_commits) == 0
    await writer.stop()


@pytest.mark.parametrize("_repeat", range(25))
async def test_cancellation_ambiguity_never_issues_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _repeat: int,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    entered = Event()
    release = Event()
    original = writer._write_live_batch

    def blocked(batch: list[Reading]):
        entered.set()
        assert release.wait(5)
        return original(batch)

    monkeypatch.setattr(writer, "_write_live_batch", blocked)
    task = asyncio.create_task(writer.write_committed([_reading()]))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await writer.stop()

    assert len(writer._issued_commits) == 0


@pytest.mark.parametrize("_repeat", range(25))
async def test_concurrent_commits_return_only_their_owned_readings(
    tmp_path: Path,
    _repeat: int,
) -> None:
    first = _descriptor(channel_id="probe.1")
    second = ChannelDescriptorV1(
        schema_version=1,
        channel_id="probe.2",
        instrument_id="probe",
        source_key="input.2.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 2",
        visible_by_default=True,
        display_order=2,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner(first, second))

    receipts = await asyncio.gather(
        writer.write_committed([_reading(channel="probe.1", value=1.0)]),
        writer.write_committed([_reading(channel="probe.2", value=2.0)]),
    )

    assert all(receipt is not None and writer.owns_commit(receipt) for receipt in receipts)
    assert [receipt.commit_revision for receipt in receipts if receipt] == [1, 2]
    assert [writer.readings_from_commit(receipt)[0].value for receipt in receipts if receipt] == [1.0, 2.0]
    conn = _db(tmp_path)
    try:
        assert conn.execute("SELECT channel, value FROM readings ORDER BY id").fetchall() == [
            ("probe.1", 1.0),
            ("probe.2", 2.0),
        ]
    finally:
        conn.close()
    await writer.stop()


async def test_commit_revision_is_integrity_bound_and_advances_only_for_issued_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    first = await writer.write_committed([_reading(value=1.0)])
    assert first is not None
    monkeypatch.setattr(writer, "_write_day_batch", lambda _conn, _batch: False)
    assert await writer.write_committed([_reading(value=2.0)]) is None
    monkeypatch.undo()
    second = await writer.write_committed([_reading(value=3.0)])
    assert second is not None

    assert (first.commit_revision, second.commit_revision) == (1, 2)
    object.__setattr__(first, "commit_revision", 2)
    assert not writer.owns_commit(first)
    assert writer.owns_commit(second)
    await writer.stop()


async def test_live_writer_forbids_legacy_bool_authority_api(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner())
    with pytest.raises(RuntimeError, match="legacy bool API"):
        await writer.write_immediate([_reading()])
    with pytest.raises(RuntimeError, match="legacy queue"):
        await writer.start(asyncio.Queue())
    await writer.stop()


# ---------------------------------------------------------------------------
# F35 D4.1 — entries_from_commit(): additive, same verification as
# readings_from_commit(), but keeps the descriptor envelope alongside each
# reading instead of discarding it.
# ---------------------------------------------------------------------------


async def test_entries_from_commit_returns_the_exact_receipt_entries(tmp_path: Path) -> None:
    descriptor = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner(descriptor))

    receipt = await writer.write_committed([_reading()])
    assert receipt is not None

    entries = writer.entries_from_commit(receipt)

    assert entries is receipt.entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry.channel_id == descriptor.channel_id
    assert entry.descriptor_hash == descriptor.descriptor_hash
    assert entry.descriptor_envelope == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    # readings_from_commit() (untouched, D4.1 is purely additive) must still
    # agree reading-for-reading with entries_from_commit()'s .reading values.
    assert writer.readings_from_commit(receipt) == [item.reading for item in entries]
    await writer.stop()


async def test_entries_from_commit_rejects_foreign_and_mutated_receipts_identically_to_readings(
    tmp_path: Path,
) -> None:
    first = SQLiteWriter(tmp_path / "first", channel_catalog=_owner())
    second = SQLiteWriter(tmp_path / "second", channel_catalog=_owner())
    receipt = await first.write_committed([_reading()])
    assert receipt is not None

    with pytest.raises(TypeError, match="foreign, forged, or mutated"):
        second.entries_from_commit(receipt)

    entry = receipt.entries[0]
    object.__setattr__(entry, "descriptor_hash", "sha256:" + "0" * 64)
    with pytest.raises(TypeError, match="foreign, forged, or mutated"):
        first.entries_from_commit(receipt)

    await first.stop()
    await second.stop()


async def test_entries_from_commit_cardinality_matches_persisted_batch(tmp_path: Path) -> None:
    """Positional pairing evidence for D4.3: entries_from_commit()'s length
    and order must agree exactly with the committed batch."""
    first = _descriptor(channel_id="probe.1")
    second = ChannelDescriptorV1(
        schema_version=1,
        channel_id="probe.2",
        instrument_id="probe",
        source_key="input.2.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 2",
        visible_by_default=True,
        display_order=2,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=_owner(first, second))
    batch = [
        _reading(channel="probe.1", value=1.0),
        _reading(channel="probe.2", value=2.0),
    ]

    receipt = await writer.write_committed(batch)
    assert receipt is not None

    entries = writer.entries_from_commit(receipt)

    assert len(entries) == len(batch)
    assert [entry.channel_id for entry in entries] == ["probe.1", "probe.2"]
    assert [entry.reading.value for entry in entries] == [1.0, 2.0]
    await writer.stop()
