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

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import ChannelDescriptorStorageError
from cryodaq.storage.sqlite_writer import SQLiteWriter

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

    from cryodaq.storage.sqlite_writer import _MAX_REMEMBERED_UNBOUND_CHANNELS

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
