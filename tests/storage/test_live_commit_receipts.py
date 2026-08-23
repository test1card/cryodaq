from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
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
from cryodaq.core.operator_log import OperatorLogIdempotencyConflictError
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage import sqlite_writer as sqlite_writer_module
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog
from cryodaq.storage.sqlite_writer import (
    SCHEMA_ALARM_ACK_OUTBOX_LEGACY,
    SCHEMA_ALARM_ACK_OUTBOX_LEGACY_QUARANTINE,
    CommittedBatchReceipt,
    CommittedReadingReceipt,
    SQLiteWriter,
)


def test_alarm_ack_registry_preflights_aggregate_bytes_before_streaming_rows() -> None:
    source = textwrap.dedent(inspect.getsource(SQLiteWriter._alarm_ack_registry_usage))
    tree = ast.parse(source)
    fetchall_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fetchall"
    ]

    assert fetchall_calls == [], f"ACK registry materializes rows before its byte cap at {fetchall_calls}"
    preflight_index = source.find("SUM(")
    stream_index = source.find("while True")
    assert 0 <= preflight_index < stream_index, "aggregate SQL preflight must precede bounded row decoding"


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


def _alarm_ack_case(
    request_char: str,
    fingerprint_char: str,
    *,
    engine_instance_id: str = "1" * 32,
) -> dict[str, object]:
    request_id = request_char * 32
    request_fingerprint = fingerprint_char * 64
    source_activation_id = str(int(request_char, 16) + 1)
    activation_id = f"activation-{request_char}"
    alarm_name = f"alarm-{request_char}"
    acknowledged_at = 123.5
    return {
        "request_id": request_id,
        "request_fingerprint": request_fingerprint,
        "alarm_name": alarm_name,
        "activation_id": activation_id,
        "engine_instance_id": engine_instance_id,
        "source_activation_id": source_activation_id,
        "operator_name": "operator",
        "reason": "observed",
        "event": {
            "schema": "alarm_ack_event_v1",
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
            "alarm_name": alarm_name,
            "engine_instance_id": engine_instance_id,
            "source_activation_id": source_activation_id,
            "activation_id": activation_id,
            "acknowledged_at": acknowledged_at,
            "operator": "operator",
            "reason": "observed",
        },
        "receipt": {
            "schema": "alarm_ack_commit_v1",
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
            "alarm_name": alarm_name,
            "engine_instance_id": engine_instance_id,
            "source_activation_id": source_activation_id,
            "activation_id": activation_id,
            "acknowledged_at": acknowledged_at,
            "committed": True,
        },
    }


def _alarm_ack_abort_kwargs(case: dict[str, object]) -> dict[str, object]:
    keys = (
        "request_id",
        "request_fingerprint",
        "engine_instance_id",
        "activation_id",
        "source_activation_id",
        "event",
        "receipt",
    )
    return {key: case[key] for key in keys}


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
        # Two: the described channel, and the reserved entry that a reading gets when the
        # catalog describes no channel for it. That entry MUST be installed -- the readings
        # foreign key refuses a row whose descriptor is not in the table, and storing such a
        # row instead of destroying the batch is the whole point of it. What this line is here
        # for -- that the catalog is installed in the same transaction as its first readings,
        # and only then -- is unchanged.
        assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (2,)
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


# THE UNKNOWN-CHANNEL CASE IS DELIBERATELY NOT IN THIS LIST (2026-08-21). It used to be
# first. Measured on the real descriptor-authoritative path with a control: a batch of two
# readings, one on a channel the catalog does not describe, raised at admission and left NO
# DATABASE FILE AT ALL -- the described reading died with the undescribed one, on every
# acquisition cycle, for as long as the catalog gap lasted. A re-wired sensor, or one added
# mid-campaign, produces exactly that gap in an ordinary laboratory week.
#
# The decision that an unknown label may never be granted a canonical identity is untouched
# and is why the reserved catalog entry exists: it grants no identity and states that the
# channel is not described. What changed is the COST of the refusal. Losing every reading
# acquired in the same cycle is not required by that decision and is not survivable for a
# week-long run.
#
# The two cases that REMAIN are the ones where refusing the batch is right. An instrument
# that disagrees may mean the reading is not the quantity the descriptor names; a non-finite
# value with an OK status is garbage the doctrine never produces. Both still roll everything
# back, and this test still proves it.
@pytest.mark.parametrize(
    "bad",
    [
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
            # Two: the described channel, and the reserved entry that a reading gets when the
            # catalog describes no channel for it. That entry MUST be installed -- the readings
            # foreign key refuses a row whose descriptor is not in the table, and storing such a
            # row instead of destroying the batch is the whole point of it. What this line is here
            # for -- that the catalog is installed in the same transaction as its first readings,
            # and only then -- is unchanged.
            assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone() == (2,)
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


async def test_operator_log_publication_outbox_survives_restart(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "e" * 32
    fingerprint = "f" * 64
    event = {
        "schema": "operator_log_commit_v1",
        "entry": {
            "id": 7,
            "timestamp": "2026-07-23T12:00:00+00:00",
            "experiment_id": "exp-stable",
            "author": "operator",
            "source": "gui",
            "message": "stable",
            "tags": ["reviewed"],
        },
    }
    receipt = {
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "entry_id": 7,
        "experiment_id": "exp-stable",
        "committed": True,
    }
    prepared = await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    assert prepared.state == "intent"
    published = await writer.publish_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert published.state == "published"
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    replay = await restarted.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    assert replay.state == "published"
    assert replay.event == event
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await restarted.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint="0" * 64,
            event=event,
            receipt=receipt,
        )
    await restarted.stop()


async def test_alarm_ack_outbox_survives_restart_and_rejects_request_reuse(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "b" * 64
    engine_instance_id = "1" * 32
    conflicting_engine_instance_id = "2" * 32
    acknowledged_at = 123.5
    event = {
        "schema": "alarm_ack_event_v1",
        "request_id": request_id,
        "request_fingerprint": fingerprint,
        "alarm_name": "alarm",
        "engine_instance_id": engine_instance_id,
        "source_activation_id": "1",
        "activation_id": "activation-1",
        "acknowledged_at": acknowledged_at,
        "operator": "operator",
        "reason": "observed",
    }
    receipt = {
        "schema": "alarm_ack_commit_v1",
        "request_id": request_id,
        "request_fingerprint": fingerprint,
        "alarm_name": "alarm",
        "engine_instance_id": engine_instance_id,
        "source_activation_id": "1",
        "activation_id": "activation-1",
        "acknowledged_at": acknowledged_at,
        "committed": True,
    }
    prepared = await writer.prepare_alarm_ack_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        alarm_name="alarm",
        activation_id="activation-1",
        engine_instance_id=engine_instance_id,
        source_activation_id="1",
        operator_name="operator",
        reason="observed",
        event=event,
        receipt=receipt,
    )
    assert prepared.state == "prepared"
    assert prepared.engine_instance_id == engine_instance_id
    assert prepared.source_activation_id == "1"
    assert (
        await writer.find_alarm_ack_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
        == prepared
    )
    committed = await writer.commit_alarm_ack_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    assert committed.state == "committed"
    assert await writer.committed_alarm_ack_outbox() == (committed,)
    published = await writer.publish_alarm_ack_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    assert published.state == "published"
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    retained = await restarted.find_alarm_ack_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert retained == published
    replay = await restarted.prepare_alarm_ack_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        alarm_name="alarm",
        activation_id="activation-1",
        engine_instance_id=engine_instance_id,
        source_activation_id="1",
        operator_name="operator",
        reason="observed",
        event=event,
        receipt=receipt,
    )
    assert replay.state == "published"
    assert replay.event == event
    assert replay.receipt == receipt
    conflicting_fingerprint = "c" * 64
    conflicting_event = {
        **event,
        "request_fingerprint": conflicting_fingerprint,
        "engine_instance_id": conflicting_engine_instance_id,
        "source_activation_id": "2",
        "reason": "different",
    }
    conflicting_receipt = {
        **receipt,
        "request_fingerprint": conflicting_fingerprint,
        "engine_instance_id": conflicting_engine_instance_id,
        "source_activation_id": "2",
    }
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await restarted.prepare_alarm_ack_outbox(
            request_id=request_id,
            request_fingerprint=conflicting_fingerprint,
            alarm_name="alarm",
            activation_id="activation-1",
            engine_instance_id=conflicting_engine_instance_id,
            source_activation_id="2",
            operator_name="operator",
            reason="different",
            event=conflicting_event,
            receipt=conflicting_receipt,
        )
    await restarted.stop()


async def test_prepared_alarm_ack_rows_are_atomically_aborted_before_restart_replay(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    first = _alarm_ack_case("a", "f")
    second = _alarm_ack_case("b", "e")
    committed_case = _alarm_ack_case("c", "d")
    first_prepared = await writer.prepare_alarm_ack_outbox(**first)
    second_prepared = await writer.prepare_alarm_ack_outbox(**second)
    committed_prepared = await writer.prepare_alarm_ack_outbox(**committed_case)
    committed = await writer.commit_alarm_ack_outbox(
        request_id=committed_case["request_id"],
        request_fingerprint=committed_case["request_fingerprint"],
        event=committed_case["event"],
        receipt=committed_case["receipt"],
    )
    assert {first_prepared.state, second_prepared.state, committed_prepared.state} == {"prepared"}
    assert committed.state == "committed"

    recovery_engine = "2" * 32
    dispositions = await writer.abort_prepared_alarm_ack_outbox(
        recovery_engine_instance_id=recovery_engine,
    )

    assert [item.request_id for item in dispositions] == [first["request_id"], second["request_id"]]
    assert all(item.schema == "alarm_ack_abort_disposition_v1" for item in dispositions)
    assert all(item.state == "aborted" for item in dispositions)
    assert all(item.terminal_code == "engine_restart_before_ack_commit" for item in dispositions)
    assert all(item.prior_engine_instance_id == "1" * 32 for item in dispositions)
    assert all(item.recovery_engine_instance_id == recovery_engine for item in dispositions)
    assert all(type(item.disposed_at) is float and item.disposed_at > 0.0 for item in dispositions)

    status = await writer.alarm_ack_outbox_registry_status()
    assert (status.prepared_count, status.committed_count, status.aborted_count) == (0, 1, 2)
    assert await writer.abort_prepared_alarm_ack_outbox(recovery_engine_instance_id=recovery_engine) == ()
    assert await writer.committed_alarm_ack_outbox() == (committed,)
    for case, prepared in ((first, first_prepared), (second, second_prepared)):
        retained = await writer.find_alarm_ack_outbox(
            request_id=case["request_id"],
            request_fingerprint=case["request_fingerprint"],
        )
        assert retained is not None
        assert retained.state == "aborted"
        assert retained.terminal_code == "engine_restart_before_ack_commit"
        assert retained.terminal_engine_instance_id == recovery_engine
        assert retained.event == prepared.event
        assert retained.receipt == prepared.receipt
        assert await writer.prepare_alarm_ack_outbox(**case) == retained
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.find_alarm_ack_outbox(
            request_id=first["request_id"],
            request_fingerprint="0" * 64,
        )
    await writer.stop()


async def test_restart_abort_rejects_same_engine_incarnation_atomically(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    first = _alarm_ack_case("a", "f", engine_instance_id="1" * 32)
    conflicting_late = _alarm_ack_case("b", "e", engine_instance_id="2" * 32)
    first_prepared = await writer.prepare_alarm_ack_outbox(**first)
    late_prepared = await writer.prepare_alarm_ack_outbox(**conflicting_late)
    before = await writer.alarm_ack_outbox_registry_status()
    try:
        with pytest.raises(RuntimeError, match="recovery engine incarnation must differ"):
            await writer.abort_prepared_alarm_ack_outbox(
                recovery_engine_instance_id=conflicting_late["engine_instance_id"],
            )

        for case, prepared in ((first, first_prepared), (conflicting_late, late_prepared)):
            retained = await writer.find_alarm_ack_outbox(
                request_id=case["request_id"],
                request_fingerprint=case["request_fingerprint"],
            )
            assert retained == prepared
        after = await writer.alarm_ack_outbox_registry_status()
        assert after == before
        assert (after.prepared_count, after.aborted_count) == (2, 0)
        assert after.pending_bytes == before.pending_bytes
    finally:
        await writer.stop()


@pytest.mark.parametrize(
    ("terminal_code", "terminal_engine_instance_id"),
    (
        ("engine_restart_before_ack_commit", "1" * 32),
        ("activation_changed_before_ack_commit", "2" * 32),
    ),
)
async def test_retained_alarm_ack_terminal_incarnation_contradiction_fails_closed_without_mutation(
    tmp_path: Path,
    terminal_code: str,
    terminal_engine_instance_id: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    case = _alarm_ack_case("a", "f", engine_instance_id="1" * 32)
    await writer.prepare_alarm_ack_outbox(**case)
    await writer.stop()

    control_db = tmp_path / "control.db"
    conn = sqlite3.connect(str(control_db))
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "UPDATE alarm_ack_outbox SET state = 'aborted', terminal_code = ?, "
            "terminal_engine_instance_id = ? WHERE request_id = ?",
            (terminal_code, terminal_engine_instance_id, case["request_id"]),
        )
        conn.commit()
        before = conn.execute(
            "SELECT * FROM alarm_ack_outbox WHERE request_id = ?",
            (case["request_id"],),
        ).fetchone()
        assert before is not None
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="terminal engine incarnation is inconsistent"):
            await restarted.find_alarm_ack_outbox(
                request_id=case["request_id"],
                request_fingerprint=case["request_fingerprint"],
            )
        with pytest.raises(RuntimeError, match="terminal engine incarnation is inconsistent"):
            await restarted.alarm_ack_outbox_registry_status()
        with pytest.raises(RuntimeError, match="terminal engine incarnation is inconsistent"):
            await restarted.abort_prepared_alarm_ack_outbox(
                recovery_engine_instance_id="3" * 32,
            )
    finally:
        await restarted.stop()

    conn = sqlite3.connect(str(control_db))
    try:
        after = conn.execute(
            "SELECT * FROM alarm_ack_outbox WHERE request_id = ?",
            (case["request_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert after == before


async def test_live_alarm_ack_abort_is_idempotent_terminal_and_frees_pending_capacity(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    case = _alarm_ack_case("a", "f")
    prepared = await writer.prepare_alarm_ack_outbox(**case)
    before = await writer.alarm_ack_outbox_registry_status()
    assert (before.prepared_count, before.aborted_count) == (1, 0)

    disposition = await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(case))
    repeated = await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(case))
    assert repeated == disposition
    assert disposition.schema == "alarm_ack_abort_disposition_v1"
    assert disposition.state == "aborted"
    assert disposition.terminal_code == "activation_changed_before_ack_commit"
    assert disposition.prior_engine_instance_id == case["engine_instance_id"]
    assert disposition.recovery_engine_instance_id == case["engine_instance_id"]

    terminal = await writer.find_alarm_ack_outbox(
        request_id=case["request_id"],
        request_fingerprint=case["request_fingerprint"],
    )
    assert terminal is not None
    assert terminal.state == "aborted"
    assert terminal.event == prepared.event
    assert terminal.receipt == prepared.receipt
    assert await writer.prepare_alarm_ack_outbox(**case) == terminal
    after = await writer.alarm_ack_outbox_registry_status()
    assert (after.prepared_count, after.aborted_count) == (0, 1)
    assert after.pending_bytes == 0

    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.abort_alarm_ack_outbox(
            **{
                **_alarm_ack_abort_kwargs(case),
                "request_fingerprint": "0" * 64,
            }
        )
    committed_case = _alarm_ack_case("b", "e")
    await writer.prepare_alarm_ack_outbox(**committed_case)
    await writer.commit_alarm_ack_outbox(
        request_id=committed_case["request_id"],
        request_fingerprint=committed_case["request_fingerprint"],
        event=committed_case["event"],
        receipt=committed_case["receipt"],
    )
    with pytest.raises(RuntimeError, match="committed request cannot be aborted"):
        await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(committed_case))
    published_case = _alarm_ack_case("c", "d")
    await writer.prepare_alarm_ack_outbox(**published_case)
    await writer.commit_alarm_ack_outbox(
        request_id=published_case["request_id"],
        request_fingerprint=published_case["request_fingerprint"],
        event=published_case["event"],
        receipt=published_case["receipt"],
    )
    await writer.publish_alarm_ack_outbox(
        request_id=published_case["request_id"],
        request_fingerprint=published_case["request_fingerprint"],
        event=published_case["event"],
        receipt=published_case["receipt"],
    )
    with pytest.raises(RuntimeError, match="committed request cannot be aborted"):
        await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(published_case))
    assert (await writer.alarm_ack_outbox_registry_status()).prepared_count == 0
    await writer.stop()


@pytest.mark.parametrize(
    ("mode", "terminal_code"),
    [
        ("restart", "engine_restart_before_ack_commit"),
        ("live", "activation_changed_before_ack_commit"),
    ],
)
async def test_cancelled_alarm_ack_abort_owner_is_retained_until_writer_stop_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    terminal_code: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    case = _alarm_ack_case("a", "f")
    await writer.prepare_alarm_ack_outbox(**case)
    entered = Event()
    release = Event()
    stop_settlement_entered = asyncio.Event()
    original_settle_owned_tasks = writer._settle_owned_tasks

    async def observed_settle_owned_tasks(collection):  # noqa: ANN001, ANN202
        if collection is writer._owned_write_tasks:
            stop_settlement_entered.set()
        await original_settle_owned_tasks(collection)

    monkeypatch.setattr(writer, "_settle_owned_tasks", observed_settle_owned_tasks)
    api_owner: asyncio.Task[object] | None = None
    stop_owner: asyncio.Task[None] | None = None
    try:
        if mode == "restart":
            original = writer._abort_prepared_alarm_ack_outbox_sync

            def blocked(*args):  # noqa: ANN202
                entered.set()
                assert release.wait(timeout=5.0)
                return original(*args)

            monkeypatch.setattr(writer, "_abort_prepared_alarm_ack_outbox_sync", blocked)
            api_owner = asyncio.create_task(
                writer.abort_prepared_alarm_ack_outbox(recovery_engine_instance_id="2" * 32)
            )
        else:
            original = writer._abort_alarm_ack_outbox_sync

            def blocked(*args):  # noqa: ANN202, F811
                entered.set()
                assert release.wait(timeout=5.0)
                return original(*args)

            monkeypatch.setattr(writer, "_abort_alarm_ack_outbox_sync", blocked)
            api_owner = asyncio.create_task(writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(case)))
        assert await asyncio.to_thread(entered.wait, 1.0)

        api_owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await api_owner
        assert writer._owned_write_tasks

        stop_owner = asyncio.create_task(writer.stop())
        await asyncio.wait_for(stop_settlement_entered.wait(), timeout=1.0)
        assert not stop_owner.done()
        release.set()
        await asyncio.wait_for(asyncio.shield(stop_owner), timeout=5.0)

        inspection = sqlite3.connect(tmp_path / "control.db")
        try:
            retained = inspection.execute(
                "SELECT state, terminal_code FROM alarm_ack_outbox WHERE request_id = ?",
                (case["request_id"],),
            ).fetchone()
        finally:
            inspection.close()
        assert retained == ("aborted", terminal_code)
    finally:
        release.set()
        if api_owner is not None and not api_owner.done():
            api_owner.cancel()
        if api_owner is not None:
            await asyncio.gather(api_owner, return_exceptions=True)
        if stop_owner is None:
            stop_owner = asyncio.create_task(writer.stop())
        await asyncio.wait_for(asyncio.shield(stop_owner), timeout=5.0)


async def test_alarm_ack_terminal_pruning_enforces_byte_cap_without_evicting_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    first = _alarm_ack_case("a", "f")
    second = _alarm_ack_case("b", "e")
    third = _alarm_ack_case("c", "d")
    await writer.prepare_alarm_ack_outbox(**first)
    await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(first))
    one_row = await writer.alarm_ack_outbox_registry_status()
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MAX_TOTAL_BYTES", one_row.total_bytes * 2 + 1)
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MIN_TERMINAL_RETAINED", 1)

    await writer.prepare_alarm_ack_outbox(**second)
    await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(second))
    two_rows = await writer.alarm_ack_outbox_registry_status()
    assert two_rows.total_count == 2
    assert two_rows.total_bytes <= two_rows.max_total_bytes

    await writer.prepare_alarm_ack_outbox(**third)
    final = await writer.alarm_ack_outbox_registry_status()
    assert (final.total_count, final.aborted_count, final.prepared_count) == (2, 1, 1)
    assert final.total_bytes <= final.max_total_bytes
    assert (
        await writer.find_alarm_ack_outbox(
            request_id=first["request_id"],
            request_fingerprint=first["request_fingerprint"],
        )
        is None
    )
    retained_pending = await writer.find_alarm_ack_outbox(
        request_id=third["request_id"],
        request_fingerprint=third["request_fingerprint"],
    )
    assert retained_pending is not None and retained_pending.state == "prepared"
    await writer.stop()


async def test_alarm_ack_terminal_pruning_never_evicts_pending_or_crosses_retention_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MAX_TOTAL", 3)
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MIN_TERMINAL_RETAINED", 1)
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MAX_PRUNE_PER_ADMISSION", 3)
    monkeypatch.setattr(sqlite_writer_module, "_ALARM_ACK_MAX_REGISTRY_SCAN", 6)
    writer = SQLiteWriter(tmp_path)
    cases = [
        _alarm_ack_case("a", "f"),
        _alarm_ack_case("b", "e"),
        _alarm_ack_case("c", "d"),
        _alarm_ack_case("d", "c"),
        _alarm_ack_case("e", "b"),
        _alarm_ack_case("f", "a"),
    ]
    for case in cases[:3]:
        await writer.prepare_alarm_ack_outbox(**case)
        await writer.abort_alarm_ack_outbox(**_alarm_ack_abort_kwargs(case))

    await writer.prepare_alarm_ack_outbox(**cases[3])
    assert (
        await writer.find_alarm_ack_outbox(
            request_id=cases[0]["request_id"],
            request_fingerprint=cases[0]["request_fingerprint"],
        )
        is None
    )
    await writer.prepare_alarm_ack_outbox(**cases[4])
    status = await writer.alarm_ack_outbox_registry_status()
    assert (status.total_count, status.aborted_count, status.prepared_count) == (3, 1, 2)
    for case in cases[3:5]:
        retained = await writer.find_alarm_ack_outbox(
            request_id=case["request_id"],
            request_fingerprint=case["request_fingerprint"],
        )
        assert retained is not None and retained.state == "prepared"

    with pytest.raises(RuntimeError, match="capacity cannot admit"):
        await writer.prepare_alarm_ack_outbox(**cases[5])
    final = await writer.alarm_ack_outbox_registry_status()
    assert final == status
    for case in cases[3:5]:
        retained = await writer.find_alarm_ack_outbox(
            request_id=case["request_id"],
            request_fingerprint=case["request_fingerprint"],
        )
        assert retained is not None and retained.state == "prepared"
    await writer.stop()


async def test_alarm_ack_restart_abort_rolls_back_every_transition_on_late_row_corruption(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    first = _alarm_ack_case("a", "f")
    second = _alarm_ack_case("b", "e")
    await writer.prepare_alarm_ack_outbox(**first)
    await writer.prepare_alarm_ack_outbox(**second)

    connection = sqlite3.connect(tmp_path / "control.db")
    try:
        connection.execute(
            "UPDATE alarm_ack_outbox SET event_json = ? WHERE request_id = ?",
            ("{", second["request_id"]),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="JSON|json"):
        await writer.abort_prepared_alarm_ack_outbox(
            recovery_engine_instance_id="2" * 32,
        )

    inspection = sqlite3.connect(tmp_path / "control.db")
    try:
        states = inspection.execute(
            "SELECT request_id, state, terminal_code, terminal_engine_instance_id "
            "FROM alarm_ack_outbox ORDER BY request_id"
        ).fetchall()
    finally:
        inspection.close()
    assert states == [
        (first["request_id"], "prepared", None, None),
        (second["request_id"], "prepared", None, None),
    ]
    await writer.stop()


@pytest.mark.parametrize("state", ["intent", "committed", "published"])
async def test_nonempty_legacy_alarm_ack_rows_are_quarantined_without_synthesizing_incarnation(
    tmp_path: Path,
    state: str,
) -> None:
    control_path = tmp_path / "control.db"
    connection = sqlite3.connect(control_path)
    connection.execute(SCHEMA_ALARM_ACK_OUTBOX_LEGACY)
    connection.execute(
        "INSERT INTO alarm_ack_outbox "
        "(request_id, request_fingerprint, alarm_name, activation_id, operator_name, reason, state, "
        "event_json, receipt_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "a" * 32,
            "b" * 64,
            "alarm",
            "a1",
            "operator",
            "observed",
            state,
            None if state == "intent" else '{"activation_id":"a1"}',
            None if state == "intent" else '{"committed":true}',
            1.0,
            1.0,
        ),
    )
    connection.commit()
    connection.close()
    writer = SQLiteWriter(tmp_path)

    with pytest.raises(RuntimeError, match="request identity is quarantined"):
        await writer.find_alarm_ack_outbox(
            request_id="a" * 32,
            request_fingerprint="b" * 64,
        )
    await writer.stop()

    inspection = sqlite3.connect(control_path)
    try:
        current_columns = tuple(row[1] for row in inspection.execute("PRAGMA table_info(alarm_ack_outbox)"))
        quarantine_columns = tuple(
            row[1] for row in inspection.execute("PRAGMA table_info(alarm_ack_outbox_legacy_quarantine_v1)")
        )
        assert inspection.execute("SELECT COUNT(*) FROM alarm_ack_outbox").fetchone() == (0,)
        retained = inspection.execute(
            "SELECT request_id, request_fingerprint, activation_id, state, event_json, receipt_json "
            "FROM alarm_ack_outbox_legacy_quarantine_v1"
        ).fetchall()
    finally:
        inspection.close()
    assert "engine_instance_id" in current_columns
    assert "source_activation_id" in current_columns
    assert "engine_instance_id" not in quarantine_columns
    assert "source_activation_id" not in quarantine_columns
    assert retained == [
        (
            "a" * 32,
            "b" * 64,
            "a1",
            state,
            None if state == "intent" else '{"activation_id":"a1"}',
            None if state == "intent" else '{"committed":true}',
        )
    ]


async def test_empty_exact_legacy_alarm_ack_table_migrates_before_first_lookup(tmp_path: Path) -> None:
    control_path = tmp_path / "control.db"
    connection = sqlite3.connect(control_path)
    connection.execute(SCHEMA_ALARM_ACK_OUTBOX_LEGACY)
    connection.commit()
    connection.close()
    writer = SQLiteWriter(tmp_path)

    assert (
        await writer.find_alarm_ack_outbox(
            request_id="a" * 32,
            request_fingerprint="b" * 64,
        )
        is None
    )
    await writer.stop()

    inspection = sqlite3.connect(control_path)
    try:
        columns = tuple(row[1] for row in inspection.execute("PRAGMA table_info(alarm_ack_outbox)"))
    finally:
        inspection.close()
    assert "engine_instance_id" in columns
    assert "source_activation_id" in columns


async def test_legacy_alarm_ack_migration_rejects_foreign_key_dependency_without_schema_rewrite(
    tmp_path: Path,
) -> None:
    control_path = tmp_path / "control.db"
    connection = sqlite3.connect(control_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(SCHEMA_ALARM_ACK_OUTBOX_LEGACY)
    connection.execute(
        "INSERT INTO alarm_ack_outbox "
        "(request_id, request_fingerprint, alarm_name, activation_id, operator_name, reason, state, "
        "event_json, receipt_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "a" * 32,
            "b" * 64,
            "alarm",
            "a1",
            "operator",
            "observed",
            "published",
            '{"activation_id":"a1"}',
            '{"committed":true}',
            1.0,
            1.0,
        ),
    )
    connection.execute(
        "CREATE TABLE alarm_ack_reference ("
        "id INTEGER PRIMARY KEY, "
        "ack_request_id TEXT NOT NULL REFERENCES alarm_ack_outbox(request_id))"
    )
    connection.execute(
        "INSERT INTO alarm_ack_reference (id, ack_request_id) VALUES (?, ?)",
        (1, "a" * 32),
    )
    before = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name IN ('alarm_ack_outbox', 'alarm_ack_reference') ORDER BY name, type"
    ).fetchall()
    connection.commit()
    connection.close()

    writer = SQLiteWriter(tmp_path)
    with pytest.raises(RuntimeError, match="dependency|foreign-key"):
        await writer.find_alarm_ack_outbox(
            request_id="c" * 32,
            request_fingerprint="d" * 64,
        )
    await writer.stop()

    inspection = sqlite3.connect(control_path)
    try:
        after = inspection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name IN ('alarm_ack_outbox', 'alarm_ack_reference') ORDER BY name, type"
        ).fetchall()
        retained_ack = inspection.execute(
            "SELECT request_id, request_fingerprint, state FROM alarm_ack_outbox"
        ).fetchall()
        retained_reference = inspection.execute("SELECT id, ack_request_id FROM alarm_ack_reference").fetchall()
        quarantine = inspection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'alarm_ack_outbox_legacy_quarantine_v1'"
        ).fetchone()
        columns = tuple(row[1] for row in inspection.execute("PRAGMA table_info(alarm_ack_outbox)"))
    finally:
        inspection.close()

    assert after == before
    assert retained_ack == [("a" * 32, "b" * 64, "published")]
    assert retained_reference == [(1, "a" * 32)]
    assert quarantine is None
    assert "engine_instance_id" not in columns
    assert "source_activation_id" not in columns


async def test_legacy_alarm_ack_migration_collision_rolls_back_both_exact_tables(tmp_path: Path) -> None:
    control_path = tmp_path / "control.db"
    connection = sqlite3.connect(control_path)
    connection.execute(SCHEMA_ALARM_ACK_OUTBOX_LEGACY)
    connection.execute(SCHEMA_ALARM_ACK_OUTBOX_LEGACY_QUARANTINE)
    rows = (
        ("alarm_ack_outbox", "a" * 32, "b" * 64, "current-legacy"),
        ("alarm_ack_outbox_legacy_quarantine_v1", "c" * 32, "d" * 64, "quarantined-legacy"),
    )
    for table, request_id, fingerprint, alarm_name in rows:
        connection.execute(
            f'INSERT INTO "{table}" '
            "(request_id, request_fingerprint, alarm_name, activation_id, operator_name, reason, state, "
            "event_json, receipt_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                fingerprint,
                alarm_name,
                "a1",
                "operator",
                "observed",
                "published",
                '{"activation_id":"a1"}',
                '{"committed":true}',
                1.0,
                1.0,
            ),
        )
    before = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name LIKE 'alarm_ack_outbox%' ORDER BY name, type"
    ).fetchall()
    connection.commit()
    connection.close()

    writer = SQLiteWriter(tmp_path)
    with pytest.raises(RuntimeError, match="migration authority is ambiguous"):
        await writer.find_alarm_ack_outbox(
            request_id="e" * 32,
            request_fingerprint="f" * 64,
        )
    await writer.stop()

    inspection = sqlite3.connect(control_path)
    try:
        after = inspection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name LIKE 'alarm_ack_outbox%' ORDER BY name, type"
        ).fetchall()
        retained = {
            table: inspection.execute(
                f'SELECT request_id, request_fingerprint, alarm_name, state FROM "{table}"'
            ).fetchall()
            for table, *_rest in rows
        }
    finally:
        inspection.close()

    assert after == before
    assert retained == {
        "alarm_ack_outbox": [("a" * 32, "b" * 64, "current-legacy", "published")],
        "alarm_ack_outbox_legacy_quarantine_v1": [("c" * 32, "d" * 64, "quarantined-legacy", "published")],
    }


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
    assert any(not owner.done() for owner in writer._owned_write_tasks)
    stop_task = asyncio.create_task(writer.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    release.set()
    await stop_task

    retained = writer.take_retained_commit_receipts()
    assert len(retained) == 1
    assert writer.owns_commit(retained[0])
    assert len(writer._owned_write_tasks) == 0
    assert len(writer._pending_write_futures) == 0


async def test_cancelled_read_waiter_remains_owned_until_stop_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    entered = Event()
    release = Event()
    original = writer._read_operator_log

    def blocked(**kwargs: object):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(writer, "_read_operator_log", blocked)
    task = asyncio.create_task(writer.get_operator_log())
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(not owner.done() for owner in writer._owned_read_tasks)
    stop_task = asyncio.create_task(writer.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    release.set()
    await stop_task
    assert not writer._owned_read_tasks
    assert not writer._pending_read_futures


async def test_persistence_failure_callback_is_owned_until_writer_stop(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def callback(_reason: str) -> None:
        entered.set()
        await release.wait()

    writer.set_event_loop(asyncio.get_running_loop())
    writer.set_persistence_failure_callback(callback)
    await asyncio.to_thread(writer._signal_persistence_failure, "disk full: test")
    await entered.wait()
    assert writer._pending_callback_futures
    stop_task = asyncio.create_task(writer.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    release.set()
    await stop_task
    assert not writer._pending_callback_futures


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
