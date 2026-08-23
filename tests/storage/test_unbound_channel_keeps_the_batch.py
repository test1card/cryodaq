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
import time
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
from cryodaq.storage.channel_descriptors import ChannelDescriptorStorageError
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
    assert result.complete is True


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
    assert result.complete is True


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


def test_the_reserved_entry_is_in_the_catalog_and_not_in_the_bindings() -> None:
    """The distinction that made the manifest guards agree again.

    The bindings are what the tracked manifest DECLARES -- which emitted label belongs to
    which channel of which instrument. The reserved entry declares nothing; it exists so a
    reading with no declaration has a real descriptor to reference, which the foreign key
    requires. An earlier version put it in both, and the live catalog then claimed a channel
    the manifest never declared.
    """

    from cryodaq.channels.descriptors import UNBOUND_CHANNEL_ID

    owner = _live()
    assert UNBOUND_CHANNEL_ID in owner.storage_catalog_snapshot().by_channel_id
    assert UNBOUND_CHANNEL_ID not in set(owner._bindings.values())
    # And therefore it cannot pollute the instruments a configuration must name.
    assert unbound_channel_descriptor().instrument_id not in owner.instrument_ids
    owner.require_exact_instruments((INSTRUMENT,))
