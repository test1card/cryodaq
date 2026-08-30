"""A channel the catalog does not describe must cost its own label, never the batch.

The laboratory case this pins: a sensor is re-wired, or one is added mid-campaign, and
the descriptor catalog does not yet describe its channel. Before this, the resolver
raised inside the row-building loop, `write_immediate` logged CRITICAL and re-raised,
and the scheduler counted an error and published nothing -- so every reading in the
batch was lost, on every acquisition cycle, for as long as the gap lasted.

The rule these tests hold: the row is written without a descriptor identity, which is
the truth about it, and the fact is said and counted.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    unbound_channel_descriptor,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.archive_reader import ArchiveReader, BoundedReadIssueCode
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    ChannelNotDescribedError,
    LiveChannelDescriptorCatalog,
)
from cryodaq.storage.sqlite_writer import _MAX_REMEMBERED_UNBOUND_CHANNELS, SQLiteWriter

TIMESTAMP = datetime(2026, 7, 12, 12, tzinfo=UTC)
INSTRUMENT = "reference-thermometer"


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "sensor.main",
        "instrument_id": INSTRUMENT,
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


def _reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        timestamp=TIMESTAMP,
        instrument_id=INSTRUMENT,
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _rows(root: Path) -> list[tuple[str, float, str | None]]:
    conn = sqlite3.connect(str(root / "data_2026-07-12.db"))
    try:
        return [
            (channel, value, descriptor_hash)
            for channel, value, descriptor_hash in conn.execute(
                "SELECT channel, value, descriptor_hash FROM readings ORDER BY value"
            )
        ]
    finally:
        conn.close()


async def test_one_unbound_channel_does_not_take_the_other_readings_with_it(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three readings, one on a channel the catalog never heard of: three rows."""

    described = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([described]))
    batch = [
        _reading("sensor.main", 4.2),
        _reading("sensor.rewired", 4.3),
        _reading("sensor.main", 4.4),
    ]

    with caplog.at_level(logging.WARNING, logger="cryodaq.storage.sqlite_writer"):
        assert await writer.write_immediate(batch) is True
    await writer.stop()

    persisted = _rows(tmp_path)
    assert [row[0] for row in persisted] == ["sensor.main", "sensor.rewired", "sensor.main"]
    assert [row[1] for row in persisted] == [4.2, 4.3, 4.4]

    # The described readings keep their identity. The unbound one carries the RESERVED
    # identity -- not a guess at what it might be, and not a null, which already means
    # pre-catalog history and could not be told apart from it afterwards.
    assert persisted[0][2] == described.descriptor_hash
    assert persisted[2][2] == described.descriptor_hash
    assert persisted[1][2] == unbound_channel_descriptor().descriptor_hash

    # And the operator is told which channel to add to the catalog, by name.
    said = [record.getMessage() for record in caplog.records if "sensor.rewired" in record.getMessage()]
    assert len(said) == 1, said
    assert "каталог" in said[0].lower()


async def test_a_unit_that_disagrees_with_the_descriptor_still_refuses_the_batch(
    tmp_path: Path,
) -> None:
    """A DESCRIBED channel reporting another unit is a different case, and still refuses.

    This is the boundary of the change above, held here on purpose. An absent channel
    has no identity to contradict, so its reading is stored without one. A channel the
    catalog does describe, reporting a unit the descriptor does not name, may not be the
    quantity the descriptor says it is -- storing it would put a wrong number under a
    real identity. That case keeps its registered fail-closed refusal
    (test_descriptor_mismatch_rejects_whole_batch_atomically).
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    with pytest.raises(ChannelDescriptorStorageError):
        await writer.write_immediate(
            [
                _reading("sensor.main", 4.2),
                _reading("sensor.main", 4.3, unit="mbar"),
            ]
        )
    await writer.stop()


async def test_the_same_unbound_channel_is_not_said_again_within_the_interval(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unbound channel reports every cycle; a week of unrated lines is its own loss."""

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    with caplog.at_level(logging.WARNING, logger="cryodaq.storage.sqlite_writer"):
        for value in (4.2, 4.3, 4.4, 4.5):
            assert await writer.write_immediate([_reading("sensor.rewired", value)]) is True
    await writer.stop()

    said = [record.getMessage() for record in caplog.records if "sensor.rewired" in record.getMessage()]
    assert len(said) == 1, said
    # All four rows are persisted even though only one line was written about them.
    assert len(_rows(tmp_path)) == 4
    assert writer._unbound_channel_rows == 4


async def test_the_memory_of_unbound_channel_names_stays_bounded(tmp_path: Path) -> None:
    """Channel names come from drivers, so remembering them cannot grow without limit."""

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    overflow = _MAX_REMEMBERED_UNBOUND_CHANNELS + 40
    assert await writer.write_immediate([_reading(f"sensor.unknown.{index}", 1.0) for index in range(overflow)]) is True
    await writer.stop()

    assert len(_rows(tmp_path)) == overflow
    assert writer._unbound_channel_rows == overflow
    assert len(writer._unbound_channel_said) <= _MAX_REMEMBERED_UNBOUND_CHANNELS


# ===================================================================
# What a reader makes of a row that has no descriptor identity
# ===================================================================


def _read_bounded(root: Path, archive: Path):
    """Drive the bounded reader the way the assistant's replay path drives it."""

    archive.mkdir(exist_ok=True)
    (archive / "index.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    return ArchiveReader(root, archive).query_reading_rows_bounded(
        start=TIMESTAMP - timedelta(hours=1),
        end=TIMESTAMP + timedelta(hours=1),
        channels=None,
        max_channels=64,
        max_points_per_channel=1024,
        max_total_points=4096,
        max_retained_bytes=4 * 1024 * 1024,
        deadline_monotonic=time.monotonic() + 30.0,
    )


async def test_an_unbound_row_is_reported_as_missing_identity_not_pre_catalog_history(
    tmp_path: Path,
) -> None:
    """The row must not be handed a fabricated identity on the way back out.

    This is the other half of storing the row at all. The bounded reader used to resolve
    a null descriptor hash through `resolve_legacy_descriptor`, which invents a
    pre-catalog identity and leaves the read marked COMPLETE. A newly unbound row would
    then travel through descriptor reporting as ordinary described history -- and a
    report that quietly drops or mislabels a channel is worse than one that says it
    cannot describe it.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    assert await writer.write_immediate([_reading("sensor.main", 4.2), _reading("sensor.rewired", 4.3)]) is True
    await writer.stop()

    result = _read_bounded(tmp_path, tmp_path / "archive")

    # BOTH rows come back, and the unbound one comes back WITHOUT an identity rather than
    # under a fabricated pre-catalog one.
    by_channel = {row.channel: row for row in result.rows}
    assert set(by_channel) == {"sensor.main", "sensor.rewired"}, sorted(by_channel)
    assert by_channel["sensor.main"].descriptor is not None
    assert by_channel["sensor.rewired"].descriptor is None

    # And the source is NOT marked failed. The collector quarantines every row from a
    # failed source, so reporting at this level would cost the whole day -- measured
    # 2026-08-21 against the real rotation service. The report belongs one layer up.
    assert result.complete is False


async def test_a_database_written_without_a_catalog_is_still_read_as_legacy_history(
    tmp_path: Path,
) -> None:
    """The boundary of the reader change, held on purpose and built by production.

    A writer given no descriptor catalog writes every row with a null hash and installs
    no catalog. Those rows ARE pre-catalog history, and resolving them as legacy is
    correct. The discriminator is the catalog's presence in the database, not the null
    itself -- so this database must read exactly as it did before this change.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=None)
    assert await writer.write_immediate([_reading("sensor.main", 4.2)]) is True
    await writer.stop()

    result = _read_bounded(tmp_path, tmp_path / "archive")

    assert BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING not in {issue.code for issue in result.issues}
    assert [row.channel for row in result.rows] == ["sensor.main"]


# ===================================================================
# What is counted, and when
# ===================================================================


async def test_nothing_is_counted_or_said_for_rows_the_batch_never_stored(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unbound row followed by a disagreeing one is not saved, so it is not announced.

    The rows are built before the transaction opens. If the count and the notice were
    taken there, this batch would report readings as saved that a later row destroyed --
    and the rate limiter would then stay silent about the next five minutes of real ones.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    with caplog.at_level(logging.WARNING, logger="cryodaq.storage.sqlite_writer"):
        with pytest.raises(ChannelDescriptorStorageError):
            await writer.write_immediate(
                [
                    _reading("sensor.rewired", 4.2),
                    _reading("sensor.main", 4.3, unit="mbar"),
                ]
            )
    await writer.stop()

    assert writer._unbound_channel_rows == 0
    assert not [r for r in caplog.records if "sensor.rewired" in r.getMessage()]
    assert not (tmp_path / "data_2026-07-12.db").exists() or _rows(tmp_path) == []


async def test_rotating_channel_names_cannot_defeat_the_log_bound(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A per-channel limit alone is not a bound.

    A faulty driver cycling through more distinct labels than are remembered evicts each
    label before it returns, so every label looks new and every reading speaks. The
    named-line ceiling is what actually holds a week.
    """

    from cryodaq.storage.sqlite_writer import _UNBOUND_NAMED_LINES_PER_INTERVAL

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    rotating = 3 * _MAX_REMEMBERED_UNBOUND_CHANNELS
    with caplog.at_level(logging.WARNING, logger="cryodaq.storage.sqlite_writer"):
        assert (
            await writer.write_immediate([_reading(f"sensor.rotating.{index}", 1.0) for index in range(rotating)])
            is True
        )
    await writer.stop()

    named = [r.getMessage() for r in caplog.records if "sensor.rotating." in r.getMessage()]
    assert len(named) <= _UNBOUND_NAMED_LINES_PER_INTERVAL, len(named)
    # Every row is still stored, and the count is still the truth.
    assert len(_rows(tmp_path)) == rotating
    assert writer._unbound_channel_rows == rotating


async def test_a_batch_that_crosses_midnight_describes_both_days(tmp_path: Path) -> None:
    """The catalog must reach every daily file, or the reader's discriminator has a hole.

    The reader decides that a null identity is missing rather than pre-catalog by asking
    whether the database carries a catalog. That is only sound if every daily file a
    catalog-bearing writer touches actually receives one -- including the second day of a
    batch that crosses midnight.
    """

    described = _descriptor()
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([described]))
    midnight = datetime(2026, 7, 13, tzinfo=UTC)
    batch = [
        Reading(
            timestamp=midnight - timedelta(seconds=1),
            instrument_id=INSTRUMENT,
            channel="sensor.main",
            value=4.2,
            unit="K",
            status=ChannelStatus.OK,
        ),
        Reading(
            timestamp=midnight + timedelta(seconds=1),
            instrument_id=INSTRUMENT,
            channel="sensor.main",
            value=4.3,
            unit="K",
            status=ChannelStatus.OK,
        ),
    ]
    assert await writer.write_immediate(batch) is True
    await writer.stop()

    for name in ("data_2026-07-12.db", "data_2026-07-13.db"):
        conn = sqlite3.connect(str(tmp_path / name))
        try:
            installed = conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone()[0]
        finally:
            conn.close()
        # The configured descriptor plus the reserved entry that unbound rows reference.
        assert installed == 2, f"{name} does not carry the catalog and its reserved entry"


async def test_a_rotated_unbound_row_is_reported_too(tmp_path: Path) -> None:
    """Cold data carries the same rule, proved through the REAL rotation service.

    Once a day is rotated to Parquet the hot database is gone, so a change that only
    covered SQLite would hold for a day and then quietly stop holding. This is also the
    exact case an earlier attempt got wrong: it discriminated on whether the archive
    carried a descriptor catalog, and a day whose readings are ALL unbound rotates with no
    descriptor sidecar at all under that scheme -- the marker vanished precisely in the
    worst case.

    The reserved identity has no such hole, because it is a REFERENCED hash: rotation
    carries it through the ordinary referenced-descriptor machinery, with no rotation
    change at all. An earlier version of this test built the parquet and its sidecar by
    hand, which proved only that my fixture agreed with itself.
    """

    import asyncio

    from cryodaq.storage.cold_rotation import ColdRotationService

    data = tmp_path / "data"
    data.mkdir()
    archive = tmp_path / "archive"

    writer = SQLiteWriter(data, channel_catalog=ChannelCatalog([_descriptor()]))
    assert await writer.write_immediate([_reading("sensor.main", 4.2), _reading("sensor.rewired", 4.3)]) is True
    await writer.stop()

    results = await asyncio.to_thread(
        lambda: asyncio.run(
            ColdRotationService(
                data_dir=data,
                archive_dir=archive,
                age_days=30,
                enabled=True,
            ).run_once(now=TIMESTAMP + timedelta(days=40))
        )
    )
    assert len(results) == 1, results
    assert results[0].rows == 2, results[0].rows

    # Read the ARCHIVE alone. Rotation keeps the hot file when the platform will not let it
    # be deleted -- Windows holds the SQLite handle -- and this test is about what the cold
    # path makes of a rotated row, not about which source wins an overlap.
    cold_only = tmp_path / "no-hot-data"
    cold_only.mkdir()
    result = ArchiveReader(cold_only, archive).query_reading_rows_bounded(
        start=TIMESTAMP - timedelta(hours=1),
        end=TIMESTAMP + timedelta(hours=1),
        channels=None,
        max_channels=64,
        max_points_per_channel=1024,
        max_total_points=4096,
        max_retained_bytes=4 * 1024 * 1024,
        deadline_monotonic=time.monotonic() + 30.0,
    )

    by_channel = {row.channel: row for row in result.rows}
    assert set(by_channel) == {"sensor.main", "sensor.rewired"}, sorted(by_channel)
    assert by_channel["sensor.main"].descriptor is not None
    assert by_channel["sensor.rewired"].descriptor is None
    # The day is intact. Before this was measured, one unbound row emptied the whole
    # rotated day, because a source that reports a problem is quarantined WHOLE.
    assert result.complete is False


async def test_live_unbound_admission_is_counted_after_the_commit(tmp_path: Path) -> None:
    """The production receipt path records the persisted unbound row."""

    writer = SQLiteWriter(tmp_path, channel_catalog=LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()])))
    try:
        assert await writer.write_committed([_reading("sensor.rewired", 4.2)]) is not None
        assert writer._unbound_channel_rows == 1
    finally:
        await writer.stop()


def _roster_of(count: int) -> ChannelCatalog:
    return ChannelCatalog(
        [
            replace(
                _descriptor(),
                channel_id=f"sensor.{index}",
                source_key=f"input.{index}.temperature",
                display_order=index,
            )
            for index in range(count)
        ]
    )


async def test_a_failed_commit_does_not_spend_the_unknown_label_budget(tmp_path: Path) -> None:
    """A batch that never reached disk must not decide another batch's identity.

    Review measured this exactly: a no-receipt failed batch consumed the process-local
    naming budget before persistence, and the next unknown sensor after recovery was
    stored under the reserved identity instead of its own name -- a durable identity
    chosen by a commit that never happened. The durable identity of an undescribed
    reading is the emitted label itself; it cannot be spent by any failure.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=LiveChannelDescriptorCatalog(_roster_of(63)))
    try:
        doomed = _reading("ghost.a", 1.0)
        with pytest.raises(ValueError):
            await writer.write_committed([doomed, replace(doomed, value=float("nan"))])
        db = tmp_path / "data_2026-07-12.db"
        if db.exists():
            assert _rows(tmp_path) == [], "the failed batch must not have persisted anything"

        # Recovery: the next batch succeeds, and its own unknown label keeps its name.
        assert await writer.write_committed([_reading("ghost.b", 2.0)]) is not None
    finally:
        await writer.stop()

    stored_labels = [row[0] for row in _rows(tmp_path)]
    assert "ghost.b" in stored_labels
    assert "ghost.a" not in stored_labels
    assert unbound_channel_descriptor().channel_id not in stored_labels


async def test_an_unknown_sensor_keeps_one_identity_across_writer_restart(tmp_path: Path) -> None:
    """The same unknown label must not change identity when the process does.

    Review measured: across a restart the same sensor.target was stored first under the
    reserved identity and then under its own name -- because durable identity depended on
    how much of a volatile, in-process set the previous process had happened to fill.
    One physical channel must not acquire different durable identities across failure
    and restart.
    """

    catalog = _roster_of(63)
    first = SQLiteWriter(tmp_path, channel_catalog=LiveChannelDescriptorCatalog(catalog))
    try:
        assert await first.write_committed([_reading("ghost.x", 1.0), _reading("ghost.y", 2.0)]) is not None
    finally:
        await first.stop()

    second = SQLiteWriter(tmp_path, channel_catalog=LiveChannelDescriptorCatalog(catalog))
    try:
        assert await second.write_committed([_reading("ghost.y", 3.0)]) is not None
    finally:
        await second.stop()

    rows = _rows(tmp_path)
    by_value = {row[1]: row[0] for row in rows}
    assert sorted(by_value) == [1.0, 2.0, 3.0]
    assert by_value[2.0] == by_value[3.0], "a restart must not rename an unknown sensor"
    assert by_value[3.0] == "ghost.y"
    assert unbound_channel_descriptor().channel_id not in set(by_value.values())


async def test_full_roster_unknown_label_survives_receipt_hot_rotation_and_cold(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """64 described channels plus one unknown: nothing disappears, nothing is relabelled.

    Review reproduced three losses with one extra reading on a full production roster:
    the commit receipt carried the emitted label while the row was stored under the
    reserved identity, the hot query returned 64 rows and called them complete, and the
    rotated day came back as zero rows with CHANNEL_LIMIT. This guard walks ONE unknown
    reading through the whole production path -- receipt, persisted bytes, hot read,
    REAL rotation service, cold read -- and holds every stage to one rule: the committed
    reading is present under the label the instrument emitted, and no stage claims
    completeness over a reading whose identity is missing.
    """

    import asyncio

    from cryodaq.storage.cold_rotation import ColdRotationService

    catalog = ChannelCatalog(
        [
            replace(
                _descriptor(),
                channel_id=f"sensor.{index}",
                source_key=f"input.{index}.temperature",
                display_order=index,
            )
            for index in range(64)
        ]
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=LiveChannelDescriptorCatalog(catalog))
    try:
        with caplog.at_level(logging.WARNING, logger="cryodaq.storage.sqlite_writer"):
            receipt = await writer.write_committed(
                [_reading(f"sensor.{index}", float(index)) for index in range(64)] + [_reading("sensor.rewired", 64.0)]
            )
        assert receipt is not None
        # The receipt's reading identity is what publication hands on. It must be the
        # same label the row carries on disk.
        assert [entry.reading.channel for entry in writer.entries_from_commit(receipt)][-1] == "sensor.rewired"
    finally:
        await writer.stop()

    reserved = unbound_channel_descriptor()
    persisted = _rows(tmp_path)
    assert len(persisted) == 65
    assert ("sensor.rewired", 64.0, reserved.descriptor_hash) in persisted, (
        "the row must keep the emitted label durably, not a process-local substitute"
    )

    hot = _read_bounded(tmp_path, tmp_path / "archive")
    assert BoundedReadIssueCode.CHANNEL_LIMIT not in {issue.code for issue in hot.issues}
    hot_rows = {(row.channel, row.value) for row in hot.rows}
    assert ("sensor.rewired", 64.0) in hot_rows
    assert len(hot.rows) == 65, "a committed reading must never be hidden from the hot query"
    rewired_hot = [row for row in hot.rows if row.channel == "sensor.rewired"]
    assert len(rewired_hot) == 1
    assert rewired_hot[0].descriptor is None
    assert hot.complete is False, "a read that could not describe a stored row is not complete"

    archive = tmp_path / "archive"
    results = await asyncio.to_thread(
        lambda: asyncio.run(
            ColdRotationService(data_dir=tmp_path, archive_dir=archive, age_days=30, enabled=True).run_once(
                now=TIMESTAMP + timedelta(days=40)
            )
        )
    )
    assert len(results) == 1, results
    assert results[0].rows == 65, results[0].rows

    cold_only = tmp_path / "no-hot-data"
    cold_only.mkdir()
    cold = ArchiveReader(cold_only, archive).query_reading_rows_bounded(
        start=TIMESTAMP - timedelta(hours=1),
        end=TIMESTAMP + timedelta(hours=1),
        channels=None,
        max_channels=64,
        max_points_per_channel=1024,
        max_total_points=4096,
        max_retained_bytes=4 * 1024 * 1024,
        deadline_monotonic=time.monotonic() + 30.0,
    )
    assert BoundedReadIssueCode.CHANNEL_LIMIT not in {issue.code for issue in cold.issues}
    cold_rows = {(row.channel, row.value) for row in cold.rows}
    assert cold_rows == hot_rows, "hot and cold discovery must have identical semantics"
    assert len(cold.rows) == 65
    rewired_cold = [row for row in cold.rows if row.channel == "sensor.rewired"]
    assert len(rewired_cold) == 1
    assert rewired_cold[0].descriptor is None
    assert cold.complete is False
    assert any("sensor.rewired" in record.getMessage() for record in caplog.records)


async def test_the_replay_layer_is_where_the_missing_identity_is_reported(tmp_path: Path) -> None:
    """The last link, measured rather than assumed.

    The archive keeps an unbound row and does not fail its source, because a failed source
    is quarantined whole and that would cost the day. The report therefore has to happen
    one layer up, and it does: DescriptorReplayReader withholds a reading with no
    descriptor, reports DESCRIPTOR_HASH_MISSING, and marks the batch incomplete.

    This is asserted against the production function, not against a description of it.
    """

    from cryodaq.storage.broker_replay import DescriptorReplayReader

    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([_descriptor()]))
    assert await writer.write_immediate([_reading("sensor.main", 4.2), _reading("sensor.rewired", 4.3)]) is True
    await writer.stop()

    batch = DescriptorReplayReader._from_query_result(_read_bounded(tmp_path, tmp_path / "archive"))

    assert [reading.channel_id for reading in batch.readings] == ["sensor.main"], (
        "a reading with no descriptor identity must not be handed on as if it had one"
    )
    assert batch.complete is False
    assert BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING in {issue.code for issue in batch.issues}


def test_the_reserved_identity_is_pinned_to_an_exact_value() -> None:
    """Its hash is computed FROM ITS FIELDS, so a field change orphans every stored row.

    Rows already on disk reference this exact hash. If someone edits the reserved entry's
    display name, unit or source key, the hash moves, the rows keep pointing at the old
    one, and the reader stops recognising them -- silently, because nothing else would go
    red. A changed value here is a migration, not an edit, and this test is the place that
    says so.
    """

    assert unbound_channel_descriptor().descriptor_hash == (
        "sha256:6ab4987de2e4c8b78cabade3c7d7ae938eac2a74847e243fa2a5b3f4f9c48691"
    ), (
        "the reserved identity changed; rows written before this change reference the old "
        "hash and will no longer be recognised as unbound"
    )


def test_the_reserved_entry_is_not_a_forged_legacy_descriptor() -> None:
    """The catalog refuses synthetic legacy descriptors on purpose, and it is right to.

    The first attempt built the reserved entry with LEGACY_UNKNOWN quantity, role and
    safety class, and `ChannelCatalog` refused it: "synthetic legacy descriptors cannot
    enter the authoritative catalog". That refusal is the guard working. The reserved entry
    is a REAL catalog entry whose meaning is "this channel is not described", not an
    imitation of a pre-catalog one, and this test keeps it that way.
    """

    from cryodaq.channels.descriptors import ChannelRole, ChannelSafetyClass

    reserved = unbound_channel_descriptor()
    assert reserved.role is not ChannelRole.LEGACY_UNKNOWN
    assert reserved.safety_class is not ChannelSafetyClass.LEGACY_UNKNOWN
    # And it is admissible to the authoritative catalog, which is the whole point.
    assert reserved.channel_id in ChannelCatalog([_descriptor(), reserved]).by_channel_id


# ===================================================================
# THE PRODUCTION PATH. The shipped engine gives the writer a LIVE catalog, so the scheduler
# takes write_committed and admission happens before any row is built. Everything above this
# line exercises the legacy API, which no shipped engine reaches.
# ===================================================================


def _live(*descriptors):
    from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog

    return LiveChannelDescriptorCatalog(ChannelCatalog(list(descriptors) or [_descriptor()]))


async def test_the_live_path_keeps_the_batch_when_one_channel_is_undescribed(
    tmp_path: Path,
) -> None:
    """The measurement this whole change exists for, with its control beside it.

    Measured 2026-08-21 before the fix: a batch of two readings, one on a channel the
    catalog does not describe, raised at admission and left NO DATABASE FILE AT ALL. The
    scheduler catches that, counts an error and publishes nothing -- so a laboratory loses
    every reading of every channel, on every acquisition cycle, until somebody notices.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=_live())
    assert writer.descriptor_authoritative is True, "this test is worthless on the legacy path"

    receipt = await writer.write_committed([_reading("sensor.main", 4.2), _reading("sensor.rewired", 4.3)])
    assert receipt is not None
    await writer.stop()

    persisted = _rows(tmp_path)
    assert [row[0] for row in persisted] == ["sensor.main", "sensor.rewired"]
    assert persisted[0][2] == _descriptor().descriptor_hash
    assert persisted[1][2] == unbound_channel_descriptor().descriptor_hash


def test_a_257_byte_unknown_label_cannot_hide_the_described_measurement(
    tmp_path: Path,
) -> None:
    """Reserved admission and the bounded reader must share one durable label bound.

    This is the live catalog -> writer -> SQLite -> bounded-reader path.  A 257-byte
    unknown label is otherwise a valid reading; before the guard, both rows committed
    but discovery rejected the stored label and quarantined the described row with it.
    The admitted representation therefore has to retain a useful prefix while fitting
    the reader's 256-byte grammar, without relabelling the row as described.
    """

    import hashlib

    long_label = "sensor." + "x" * (257 - len("sensor."))
    assert len(long_label.encode("utf-8")) == 257
    owner = _live()
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    try:
        admitted = tuple(owner.admit(reading) for reading in (_reading("sensor.main", 4.2), _reading(long_label, 4.3)))
        assert writer._write_live_batch(admitted) == admitted
    finally:
        if writer._conn is not None:
            writer._conn.close()
            writer._conn = None
        writer._executor.shutdown(wait=True)
        writer._read_executor.shutdown(wait=True)

    persisted = _rows(tmp_path)
    assert len(persisted) == 2, "the fixture must reach durable SQLite as one valid batch"

    result = _read_bounded(tmp_path, tmp_path / "archive")
    by_value = {row.value: row for row in result.rows}
    assert 4.2 in by_value, "an unknown label must never quarantine the described row"
    assert by_value[4.2].channel == "sensor.main"
    assert by_value[4.2].descriptor is not None
    assert 4.3 in by_value, "the bounded unknown identity must remain materialisable"
    bounded_label = by_value[4.3].channel
    assert bounded_label.startswith("sensor."), "the bounded form must still name the channel usefully"
    assert bounded_label != long_label
    assert len(bounded_label.encode("utf-8")) <= 256
    assert bounded_label.endswith(hashlib.sha256(long_label.encode("utf-8")).hexdigest())
    assert by_value[4.3].descriptor is None
    assert result.complete is False


def test_a_new_unknown_label_after_discovery_cannot_leave_the_read_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real commit between hot discovery and materialisation is reported missing.

    The scheduling hook only holds the exact boundary open.  Discovery, live catalog
    admission, SQLite persistence, and bounded materialisation all remain production
    implementations.  The reader may return its discovery snapshot, but it may not call
    that projection complete after the read snapshot contains another channel.
    """

    owner = _live()
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)

    def commit(readings: tuple[Reading, ...]) -> None:
        admitted = tuple(owner.admit(reading) for reading in readings)
        assert writer._write_live_batch(admitted) == admitted

    commit((_reading("sensor.main", 4.2),))

    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "index.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    reader = ArchiveReader(tmp_path, archive)
    discover = reader._discover_sqlite_channels
    boundary_commits = 0

    def pause_after_discovery(*args: object, **kwargs: object) -> bool:
        nonlocal boundary_commits
        result = discover(*args, **kwargs)  # type: ignore[arg-type]
        commit((_reading("sensor.new.after.discovery", 4.3),))
        boundary_commits += 1
        return result

    monkeypatch.setattr(reader, "_discover_sqlite_channels", pause_after_discovery)

    try:
        result = reader.query_reading_rows_bounded(
            start=TIMESTAMP - timedelta(hours=1),
            end=TIMESTAMP + timedelta(hours=1),
            channels=None,
            max_channels=64,
            max_points_per_channel=1024,
            max_total_points=4096,
            max_retained_bytes=4 * 1024 * 1024,
            deadline_monotonic=time.monotonic() + 30.0,
        )
    finally:
        if writer._conn is not None:
            writer._conn.close()
            writer._conn = None
        writer._executor.shutdown(wait=True)
        writer._read_executor.shutdown(wait=True)

    assert boundary_commits == 1, "the real discovery/read boundary must be exercised exactly once"
    assert len(_rows(tmp_path)) == 2, "the boundary commit must be durably present"
    assert [row.channel for row in result.rows] == ["sensor.main"]
    assert result.complete is False, "a row excluded by the discovery snapshot makes the read incomplete"


async def test_the_live_path_keeps_the_label_the_instrument_emitted(tmp_path: Path) -> None:
    """A described reading adopts the canonical channel id; an undescribed one cannot.

    For a described reading the canonical id replaces the emitted label, and that is what
    makes the row, the receipt entry and the descriptor agree. A reading admitted against
    the reserved entry has no canonical identity to adopt, so the emitted label is the only
    thing left that says where the value came from -- and it is kept.
    """

    from cryodaq.channels.descriptors import UNBOUND_CHANNEL_ID

    writer = SQLiteWriter(tmp_path, channel_catalog=_live())
    assert await writer.write_committed([_reading("sensor.rewired", 4.3)]) is not None
    await writer.stop()

    persisted = _rows(tmp_path)
    assert [row[0] for row in persisted] == ["sensor.rewired"]
    assert persisted[0][0] != UNBOUND_CHANNEL_ID, "the row must not be relabelled as the reserved entry"


async def test_the_live_path_keeps_each_undescribed_emitted_label(tmp_path: Path) -> None:
    """Reserved admission preserves each physical source label, not one surrogate.

    This drives ``write_committed`` through the same live binding and row-building
    path as the scheduler. If the storage adapter stops classifying the reserved
    descriptor, the writer replaces both labels with the reserved catalog id and
    this assertion fails.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=_live())
    assert (
        await writer.write_committed([_reading("sensor.rewired.one", 4.2), _reading("sensor.rewired.two", 4.3)])
        is not None
    )
    await writer.stop()

    persisted = _rows(tmp_path)
    assert [row[0] for row in persisted] == ["sensor.rewired.one", "sensor.rewired.two"]


async def test_the_live_path_still_refuses_a_disagreeing_instrument(tmp_path: Path) -> None:
    """The boundary, held on the production path as well as the legacy one.

    A channel the catalog DOES describe, arriving under another instrument, may not be the
    quantity the descriptor names. Admitting it would put a wrong number under a real
    identity, so the batch is still refused whole. Only "no description at all" changed.
    """

    writer = SQLiteWriter(tmp_path, channel_catalog=_live())
    disagreeing = Reading(
        timestamp=TIMESTAMP,
        instrument_id="a-different-instrument",
        channel="sensor.main",
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
    )
    with pytest.raises(ChannelDescriptorStorageError):
        await writer.write_committed([_reading("sensor.main", 4.2), disagreeing])
    await writer.stop()


def test_a_canonical_label_cannot_replace_the_described_alias_row(tmp_path: Path) -> None:
    """A canonical id that bypasses its declared alias is described, not unbound.

    The exact failure needs all three production boundaries. The live catalog maps an
    emitted alias to a different canonical id; the writer first persists that described
    reading, then receives an aliased reading followed by a canonical-label reading at
    the same timestamp. Before this guard, reserved admission let the second batch commit
    two rows with one public key and different descriptor hashes, and the bounded reader
    replaced the valid described value with the later unbound value.
    """

    canonical_id = "sensor.canonical"
    emitted_alias = "sensor.emitted"
    described = _descriptor(channel_id=canonical_id)
    owner = LiveChannelDescriptorCatalog(
        ChannelCatalog([described]),
        bindings={(INSTRUMENT, emitted_alias): canonical_id},
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)

    def commit(readings: list[Reading]) -> None:
        admitted = tuple(owner.admit(reading) for reading in readings)
        assert writer._write_live_batch(admitted) == admitted

    refusal: ChannelDescriptorStorageError | None = None
    try:
        commit([_reading(emitted_alias, 4.2)])
        try:
            commit(
                [
                    _reading(emitted_alias, 4.3),
                    _reading(canonical_id, 999.0),
                ]
            )
        except ChannelDescriptorStorageError as caught:
            refusal = caught
    finally:
        if writer._conn is not None:
            writer._conn.close()
            writer._conn = None
        writer._executor.shutdown(wait=True)
        writer._read_executor.shutdown(wait=True)

    persisted = _rows(tmp_path)
    result = _read_bounded(tmp_path, tmp_path / "archive")
    assert len(result.rows) == 1
    assert result.rows[0].channel == canonical_id
    assert result.rows[0].value == 4.2, "the unbound collision must not replace the described row"
    assert result.rows[0].descriptor is not None
    assert result.rows[0].descriptor.descriptor_hash == described.descriptor_hash
    assert persisted == [(canonical_id, 4.2, described.descriptor_hash)]
    assert refusal is not None, "the binding mismatch must refuse the collision batch"


def test_live_bind_uses_the_absence_error_type_for_a_truly_undescribed_channel() -> None:
    """Reserved admission is coupled to a symbol, never diagnostic prose.

    The same synchronous production boundary also pins both sides of that decision:
    a truly absent label is still admitted without canonical identity, while a channel
    described under another instrument is still refused.
    """

    owner = _live()
    absent = _reading("sensor.not.described", 4.2)
    with pytest.raises(ChannelNotDescribedError):
        owner.bind(absent)

    admitted = owner.admit(absent)
    assert admitted.reading.channel == absent.channel
    assert admitted.descriptor == unbound_channel_descriptor()
    assert owner.owns(admitted)

    disagreeing = replace(_reading("sensor.main", 4.3), instrument_id="another-instrument")
    with pytest.raises(ChannelDescriptorStorageError):
        owner.admit(disagreeing)


def test_the_reserved_entry_declares_nothing_and_is_visible_nowhere_public() -> None:
    """Three places it must NOT appear, each found by a guard rather than by reasoning.

    The BINDINGS are what the tracked manifest declares -- which emitted label belongs to
    which channel of which instrument. The reserved entry declares nothing; it exists so a
    reading with no declaration has a real descriptor to reference, which the foreign key
    requires. An earlier version put it in the bindings, and the manifest guards reported
    that the live catalog was claiming a channel the manifest never declared.

    The INSTRUMENT SET follows from the bindings, so it is clean for the same reason. Before
    that correction, startup refused with "instrument mismatch (extra=['cryodaq'])".

    The PUBLIC SNAPSHOT is read to build rosters of channels that exist -- the safety-pattern
    liveness check derives its canonical-id set from it. Leaving the reserved identity there
    made an alarm referencing it look accepted at startup while remaining inert, because no
    driver emits that spelling. A configuration mistake that looks accepted is worse than one
    that is refused.
    """

    from cryodaq.channels.descriptors import UNBOUND_CHANNEL_ID

    owner = _live()
    assert UNBOUND_CHANNEL_ID not in set(owner._bindings.values())
    assert unbound_channel_descriptor().instrument_id not in owner.instrument_ids
    assert UNBOUND_CHANNEL_ID not in owner.storage_catalog_snapshot().by_channel_id
    owner.require_exact_instruments((INSTRUMENT,))

    # And it is nonetheless installed where the foreign key needs it, which is the whole
    # reason it exists. The writer puts it there itself.
    assert any(
        descriptor.channel_id == UNBOUND_CHANNEL_ID
        for descriptor in SQLiteWriter(Path(tempfile.mkdtemp()), channel_catalog=_live())._channel_catalog.descriptors
    )


async def test_a_flood_of_undescribed_labels_cannot_empty_a_bounded_read(tmp_path: Path) -> None:
    """A fix for one loss of data must not create another. This is the second one, pinned.

    Every distinct label is a CHANNEL to a reader. `query_reading_rows_bounded` declares
    a channel budget -- production uses 64 -- and refuses the WHOLE SOURCE with
    CHANNEL_LIMIT when it is exceeded. Review reproduced exactly that with 65 admitted
    labels: the valid described measurements disappeared from the experiment snapshot
    along with the undescribed ones.

    The durable identity of an undescribed reading is the label the instrument emitted,
    so a flood cannot be answered by relabelling rows -- and it cannot be answered by
    hiding them either. Discovery keeps described channels in their own budget, remembers
    a bounded number of unbound labels for materialisation, and any unbound presence at
    all holds completeness at False. Overflow readings that share one poll timestamp stay
    distinct rows: distinct committed readings must never merge in a collector key.
    """

    from cryodaq.channels.descriptors import UNBOUND_CHANNEL_ID

    flood = _MAX_REMEMBERED_UNBOUND_CHANNELS + 40
    writer = SQLiteWriter(tmp_path, channel_catalog=_live())
    batch = [_reading("sensor.main", 1.0)] + [
        _reading(f"sensor.flood.{index}", float(index + 2)) for index in range(flood)
    ]
    assert await writer.write_committed(batch) is not None
    await writer.stop()

    persisted = _rows(tmp_path)
    assert len(persisted) == flood + 1, "every reading must still be stored"

    labels = {row[0] for row in persisted}
    assert len(labels) == flood + 1, "each committed reading keeps its own emitted label"
    assert UNBOUND_CHANNEL_ID not in labels, "no row may be relabelled into the reserved identity"

    result = _read_bounded(tmp_path, tmp_path / "archive")
    assert BoundedReadIssueCode.CHANNEL_LIMIT not in {issue.code for issue in result.issues}
    assert any(row.channel == "sensor.main" for row in result.rows), (
        "the described measurement survives a flood of undescribed labels"
    )
    assert result.complete is False, "unbound presence holds completeness at False even when rows are materialised"

    # The bounded read materialises a bounded number of unbound labels -- every one a
    # DISTINCT committed reading sharing one poll timestamp, so nothing may have merged.
    # WHICH labels fit the allowance is an implementation detail; that each returned row
    # agrees with its own durable bytes is the contract.
    from cryodaq.storage.archive_reader import _MAX_MATERIALIZED_UNBOUND_CHANNELS

    flood_rows = {row.channel: row.value for row in result.rows if row.channel.startswith("sensor.flood.")}
    assert len(flood_rows) == _MAX_MATERIALIZED_UNBOUND_CHANNELS
    persisted_values = {row[0]: row[1] for row in persisted}
    assert flood_rows == {label: persisted_values[label] for label in flood_rows}, (
        "each overflow reading comes back with exactly the value that was committed for it"
    )
    assert len(result.rows) == len(flood_rows) + 1
