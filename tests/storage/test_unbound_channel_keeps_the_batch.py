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

import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
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

    # The described readings keep their identity; the unbound one is stored WITHOUT one,
    # rather than being stored under a guessed or synthesised identity.
    assert persisted[0][2] == described.descriptor_hash
    assert persisted[2][2] == described.descriptor_hash
    assert persisted[1][2] is None

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
    assert (
        await writer.write_immediate([_reading(f"sensor.unknown.{index}", 1.0) for index in range(overflow)])
        is True
    )
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

    assert BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING in {issue.code for issue in result.issues}
    assert result.complete is False, "a read that could not identify a row must not report completeness"


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
        assert installed == 1, f"{name} carries no descriptor catalog"


async def test_a_rotated_unbound_row_is_reported_too(tmp_path: Path) -> None:
    """Cold data carries the same rule, and it is measured rather than assumed.

    Once a day is rotated to Parquet the hot database is gone, so a reader change that
    only covered SQLite would hold for a day and then quietly stop holding. The cold
    discriminator is the rotated index's descriptor-row count, which is the sidecar's
    way of saying the same thing the installed catalog says in the hot file.
    """

    described = _descriptor()
    envelope = PersistedChannelEnvelopeV1.from_descriptor(described)
    archive = tmp_path / "archive"
    relative = Path("year=2026") / "month=07" / "data_2026-07-12.parquet"
    path = archive / relative
    path.parent.mkdir(parents=True, exist_ok=True)

    pq.write_table(
        pa.table(
            {
                "timestamp": pa.array([TIMESTAMP, TIMESTAMP], type=pa.timestamp("us", tz="UTC")),
                "instrument_id": pa.array([INSTRUMENT, INSTRUMENT], type=pa.string()),
                "channel": pa.array([described.channel_id, "sensor.rewired"], type=pa.string()),
                "value": pa.array([4.2, 4.3], type=pa.float64()),
                "unit": pa.array(["K", "K"], type=pa.string()),
                "status": pa.array(["ok", "ok"], type=pa.string()),
                # The rotated form of an unbound row: the value is kept, the identity is
                # absent, exactly as the writer stored it.
                "descriptor_hash": pa.array([described.descriptor_hash, None], type=pa.string()),
            }
        ),
        path,
    )
    sidecar_rel = relative.with_name(relative.stem + ".channel_descriptors.parquet")
    sidecar = archive / sidecar_rel
    pq.write_table(
        pa.table(
            {
                "descriptor_hash": pa.array([described.descriptor_hash], type=pa.string()),
                "channel_id": pa.array([described.channel_id], type=pa.string()),
                "instrument_id": pa.array([described.instrument_id], type=pa.string()),
                "source_key": pa.array([described.source_key], type=pa.string()),
                "descriptor_revision": pa.array([described.descriptor_revision], type=pa.int32()),
                "envelope_json": pa.array([envelope.canonical_json], type=pa.binary()),
            }
        ),
        sidecar,
    )
    (archive / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": "data_2026-07-12.db",
                        "archive_path": relative.as_posix(),
                        "row_count": 2,
                        "size_bytes_archive": path.stat().st_size,
                        "checksum_md5": hashlib.md5(path.read_bytes()).hexdigest(),
                        "channel_descriptors_path": sidecar_rel.as_posix(),
                        "channel_descriptors_rows": 1,
                        "channel_descriptors_checksum": hashlib.md5(sidecar.read_bytes()).hexdigest(),
                        "channel_descriptors_size_bytes": sidecar.stat().st_size,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    hot = tmp_path / "data"
    hot.mkdir()
    result = ArchiveReader(hot, archive).query_reading_rows_bounded(
        start=TIMESTAMP - timedelta(hours=1),
        end=TIMESTAMP + timedelta(hours=1),
        channels=None,
        max_channels=64,
        max_points_per_channel=1024,
        max_total_points=4096,
        max_retained_bytes=4 * 1024 * 1024,
        deadline_monotonic=time.monotonic() + 30.0,
    )

    assert BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING in {issue.code for issue in result.issues}
    assert result.complete is False
