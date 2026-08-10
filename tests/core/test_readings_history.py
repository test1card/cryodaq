"""Tests for readings_history engine command and SQLiteWriter.read_readings_history."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
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
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    initialize_descriptor_storage,
)
from cryodaq.storage.sentinel import SENTINEL
from cryodaq.storage.sqlite_writer import SCHEMA_READINGS, SQLiteWriter


@pytest.fixture()
def writer_with_data(tmp_path: Path):
    """Create a SQLiteWriter with sample readings already written."""
    # SQLiteWriter checks SQLite version at construction; bypass on known-broken
    # dev SQLite versions (same pattern as test_audit_fixes.py, test_experiment.py).
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())

    # Anchor to a whole second: row timestamps round-trip losslessly through
    # datetime.fromtimestamp (microsecond precision), so the inclusive-boundary
    # filter (timestamp >= base_ts + 50*30) lands deterministically on row 50.
    # A sub-second base_ts (raw time.time()) makes row 50's stored microsecond
    # value jitter above/below from_ts by its fractional part → flaky 49/50.
    base_ts = float(int(time.time()) - 7200)  # 2 hours ago, whole-second anchor
    readings: list[Reading] = []
    for i in range(100):
        ts = base_ts + i * 30  # every 30 seconds
        for ch_name in ["Т1 Камера", "Т2 Экран"]:
            r = Reading(
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
                instrument_id="LS218_1",
                channel=ch_name,
                value=4.2 + i * 0.01,
                unit="K",
                status=ChannelStatus.OK,
            )
            readings.append(r)
        # Pressure channel
        readings.append(
            Reading(
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
                instrument_id="VSP63D",
                channel="P Камера",
                value=1e-3 + i * 1e-5,
                unit="mbar",
                status=ChannelStatus.OK,
            )
        )

    loop.run_until_complete(writer.write_immediate(readings))
    yield writer, base_ts
    loop.run_until_complete(writer.stop())
    loop.close()


def test_read_readings_history_all(writer_with_data) -> None:
    """Read all history without filters — verify exact row count and value correctness."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    assert "Т1 Камера" in data
    assert "Т2 Экран" in data
    assert "P Камера" in data
    assert len(data["Т1 Камера"]) == 100
    # Verify exact values: row i should have value 4.2 + i * 0.01 (ASC order)
    points = data["Т1 Камера"]
    assert abs(points[0][1] - 4.2) < 1e-6, f"First point value must be 4.2, got {points[0][1]}"
    assert abs(points[-1][1] - (4.2 + 99 * 0.01)) < 1e-6, (
        f"Last point value must be {4.2 + 99 * 0.01:.4f}, got {points[-1][1]}"
    )
    # Verify timestamps: first point must be at base_ts (±1s for float precision)
    assert abs(points[0][0] - base_ts) < 1.0, f"First timestamp must be near base_ts={base_ts}, got {points[0][0]}"
    # Oldest point must be first, newest last
    assert points[0][0] < points[-1][0], "Points must be sorted oldest-first"


def test_read_readings_history_time_filter(writer_with_data) -> None:
    """Filter by from_ts returns exactly the rows at the inclusive boundary.

    base_ts is a float (time.time() - 7200) and each row is spaced exactly
    30 s apart, so from_ts = base_ts + 50*30 lands precisely on row index 50.
    SQLiteWriter uses timestamp >= ? (inclusive), so the result must be exactly
    50 rows: indices 50..99.  Allowing 49 would let a regression to
    timestamp > ? (exclusive) go undetected.
    """
    writer, base_ts = writer_with_data
    # Row i has timestamp base_ts + i * 30.  Row 50 is the exact boundary.
    from_ts = base_ts + 50 * 30
    data = writer._read_readings_history(from_ts=from_ts)
    points = data["Т1 Камера"]

    # Exactly 50 rows: indices 50..99 (inclusive lower bound).
    assert len(points) == 50, (
        f"Expected exactly 50 points after midpoint filter (timestamp >= boundary), got {len(points)}"
    )
    # All returned timestamps must be >= from_ts (timestamps are exact multiples).
    for ts, _ in points:
        assert ts >= from_ts, f"Timestamp {ts} is before from_ts {from_ts}"
    # First returned point must be row 50: value = 4.2 + 50 * 0.01
    expected_first_value = 4.2 + 50 * 0.01
    assert abs(points[0][1] - expected_first_value) < 1e-6, (
        f"First filtered point must be row 50 (value={expected_first_value:.4f}), got {points[0][1]}"
    )
    # Last returned point must be row 99: value = 4.2 + 99 * 0.01
    expected_last_value = 4.2 + 99 * 0.01
    assert abs(points[-1][1] - expected_last_value) < 1e-6, (
        f"Last filtered point must be row 99 (value={expected_last_value:.4f}), got {points[-1][1]}"
    )


def test_read_readings_history_channel_filter(writer_with_data) -> None:
    """Filter by specific channels."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(channels=["Т1 Камера"])
    assert "Т1 Камера" in data
    assert "Т2 Экран" not in data
    assert "P Камера" not in data


def test_read_readings_history_limit(writer_with_data) -> None:
    """limit_per_channel truncates to latest N points with correct values."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(limit_per_channel=10)
    assert len(data["Т1 Камера"]) == 10, (
        f"Expected exactly 10 points with limit_per_channel=10, got {len(data['Т1 Камера'])}"
    )
    points = data["Т1 Камера"]
    # Must be the LATEST 10 points (rows 90..99)
    # Latest point value = 4.2 + 99 * 0.01
    expected_last = 4.2 + 99 * 0.01
    assert abs(points[-1][1] - expected_last) < 1e-5, (
        f"Last point must be the newest value {expected_last:.4f}, got {points[-1][1]}"
    )
    expected_first = 4.2 + 90 * 0.01
    assert abs(points[0][1] - expected_first) < 1e-5, (
        f"First of the 10 latest must be row 90 value {expected_first:.4f}, got {points[0][1]}"
    )
    # Sorted oldest-first within the returned window
    assert points[-1][1] > points[0][1], "Returned points must be sorted ascending by value/time"


def test_read_readings_history_sorted_asc(writer_with_data) -> None:
    """Points must be sorted by timestamp ASC."""
    writer, base_ts = writer_with_data
    data = writer._read_readings_history()
    for ch, points in data.items():
        timestamps = [ts for ts, _ in points]
        assert timestamps == sorted(timestamps), f"Channel {ch} not sorted ASC"


def test_history_limit_floored_to_one(writer_with_data) -> None:
    """limit_per_channel <= 0 must floor to 1, not fall through to the full set.

    Regression guard for the ``result[-0:]`` Python quirk: a zero limit used to
    slice to the whole list and return every row (unbounded), the opposite of a
    limit. Fail-closed: a non-positive limit returns the single latest point.
    """
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(limit_per_channel=0)
    assert len(data["Т1 Камера"]) == 1, (
        f"limit_per_channel=0 must floor to 1 latest point, got {len(data['Т1 Камера'])}"
    )
    # The one returned point must be the newest (row 99).
    assert abs(data["Т1 Камера"][0][1] - (4.2 + 99 * 0.01)) < 1e-5


def test_history_channel_list_capped(writer_with_data) -> None:
    """A channel list longer than the cap is truncated; channels past the cap drop.

    Trust-boundary clamp: readings_history is reachable from unauthenticated
    loopback ZMQ, so an over-long channel list must be bounded. A real channel
    placed past the 64-channel cap must NOT come back.
    """
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_CHANNELS

    writer, base_ts = writer_with_data
    # 64 filler names, then a real channel at index 64 (just past the cap).
    channels = [f"fake_{i}" for i in range(_HISTORY_MAX_CHANNELS)] + ["Т1 Камера"]
    data = writer._read_readings_history(channels=channels)
    assert "Т1 Камера" not in data, "channel past the cap must be dropped by the channel-list clamp"


def test_history_clamps_hostile_request(writer_with_data) -> None:
    """limit=10_000_000 + 500 channels returns clamped, bounded counts, no error."""
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_ROWS

    writer, base_ts = writer_with_data
    channels = ["Т1 Камера", "Т2 Экран", "P Камера"] + [f"fake_{i}" for i in range(497)]
    data = writer._read_readings_history(channels=channels, limit_per_channel=10_000_000)
    # Real channels within the first 64 entries still return their (small) data.
    assert len(data["Т1 Камера"]) == 100
    # No channel exceeds the row cap.
    for ch, points in data.items():
        assert len(points) <= _HISTORY_MAX_ROWS


def test_filtered_history_channels_share_one_deterministic_total_row_budget(
    writer_with_data,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-channel limits must not multiply the reply-wide production cap."""
    from cryodaq.storage import sqlite_writer as sqlite_writer_module

    writer, _base_ts = writer_with_data
    monkeypatch.setattr(sqlite_writer_module, "_HISTORY_MAX_TOTAL_ROWS", 125)
    channels = ["Т1 Камера", "Т2 Экран"]

    first = writer._read_readings_history(
        channels=channels,
        limit_per_channel=100,
    )
    second = writer._read_readings_history(
        channels=channels,
        limit_per_channel=100,
    )
    reversed_order = writer._read_readings_history(
        channels=list(reversed(channels)),
        limit_per_channel=100,
    )

    assert first == second
    assert first == reversed_order
    assert set(first) == set(channels)
    assert sum(len(points) for points in first.values()) == 125
    assert all(len(points) <= 100 for points in first.values())
    assert max(map(len, first.values())) - min(map(len, first.values())) <= 1


def test_sparse_history_budget_redistributes_without_caller_order_bias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unused sparse shares must be redistributed without caller-order bias."""
    from cryodaq.storage import sqlite_writer as sqlite_writer_module

    monkeypatch.setattr(sqlite_writer_module, "_HISTORY_MAX_TOTAL_ROWS", 15)
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        base_ts = float(int(time.time()) - 7200)
        readings: list[Reading] = []
        # Two old rows leave unused capacity that the noisy channel may claim.
        for i in range(2):
            readings.append(
                Reading(
                    timestamp=datetime.fromtimestamp(base_ts + i, tz=UTC),
                    instrument_id="VSP63D",
                    channel="quiet",
                    value=float(i),
                    unit="mbar",
                    status=ChannelStatus.OK,
                )
            )
        # 100 NEWER rows on "noisy" (all after the quiet rows).
        for i in range(100):
            readings.append(
                Reading(
                    timestamp=datetime.fromtimestamp(base_ts + 100 + i, tz=UTC),
                    instrument_id="LS218_1",
                    channel="noisy",
                    value=float(i),
                    unit="K",
                    status=ChannelStatus.OK,
                )
            )
        loop.run_until_complete(writer.write_immediate(readings))

        forward = writer._read_readings_history(channels=["quiet", "noisy"], limit_per_channel=10)
        reverse = writer._read_readings_history(channels=["noisy", "quiet"], limit_per_channel=10)
        assert forward == reverse
        assert len(forward.get("quiet", [])) == 2
        assert len(forward.get("noisy", [])) == 10
        assert sum(map(len, forward.values())) == 12 <= 15
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_read_readings_history_masks_sentinel(tmp_path: Path) -> None:
    """NaN-доктрина: a persisted sentinel/error row reads back as NaN, never as
    the raw sentinel — the GUI-reconnect history feed must not show a number."""
    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        base_ts = float(int(time.time()) - 60)
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(base_ts, tz=UTC),
                        instrument_id="ls218s",
                        channel="CH1",
                        value=4.5,
                        unit="K",
                        status=ChannelStatus.OK,
                    ),
                    Reading(
                        timestamp=datetime.fromtimestamp(base_ts + 1, tz=UTC),
                        instrument_id="ls218s",
                        channel="CH1",
                        value=float("nan"),
                        unit="K",
                        status=ChannelStatus.SENSOR_ERROR,
                    ),
                ]
            )
        )
        data = writer._read_readings_history(channels=["CH1"])
        vals = [v for _, v in data["CH1"]]
        assert 4.5 in vals, "usable reading must survive"
        assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
        assert any(math.isnan(v) for v in vals), "sentinel row must read back as NaN"
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_read_readings_history_no_archive_unchanged(writer_with_data) -> None:
    """No archive → a from_ts far before any hot data is hot-only, unchanged.

    Pins the archive-aware branch to a strict no-op when no archive index
    exists (the default for every deployment with cold rotation OFF).
    """
    writer, base_ts = writer_with_data
    data = writer._read_readings_history(from_ts=base_ts - 86400 * 5)
    assert len(data["Т1 Камера"]) == 100, "no-archive path must stay hot-only"


def test_read_readings_history_unions_cold_archive(tmp_path: Path) -> None:
    """A window reaching before the oldest hot day unions in rotated Parquet rows.

    Cold (archived) rows must appear alongside hot rows, sorted ASC, without
    double-reading hot days.
    """
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    now = datetime.now(UTC)
    hot_descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id="pressure.shared.opaque",
        instrument_id="LS218_1",
        source_key="input.hot.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Hot declared temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([hot_descriptor]))
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        # HOT: a row for today lands in data_<today>.db.
        hot_ts = now.timestamp() - 60
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(hot_ts, tz=UTC),
                        instrument_id=hot_descriptor.instrument_id,
                        channel=hot_descriptor.channel_id,
                        value=10.0,
                        unit="K",
                        status=ChannelStatus.OK,
                    )
                ]
            )
        )
        # COLD: a row 3 days ago, only in the Parquet archive.
        cold_day = now - timedelta(days=3)
        cold_ts = cold_day.timestamp()
        cold_descriptor = ChannelDescriptorV1(
            schema_version=1,
            channel_id="pressure.loop.opaque",
            instrument_id="archived-thermometer",
            source_key="input.1.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            role=ChannelRole.PRIMARY_MEASUREMENT,
            safety_class=ChannelSafetyClass.OBSERVATIONAL,
            display_group="Cryostat",
            display_name="Archived temperature",
            visible_by_default=True,
            display_order=1,
            descriptor_revision=1,
        )
        envelope = PersistedChannelEnvelopeV1.from_descriptor(cold_descriptor)
        archive_dir = tmp_path / "archive"
        rel = f"year={cold_day:%Y}/month={cold_day:%m}/data_{cold_day.date().isoformat()}.db.parquet"
        ppath = archive_dir / rel
        ppath.parent.mkdir(parents=True, exist_ok=True)
        cold_descriptor_ts = cold_ts + 1
        table = pa.table(
            {
                "timestamp": pa.array(
                    [
                        datetime.fromtimestamp(cold_ts, tz=UTC),
                        datetime.fromtimestamp(cold_descriptor_ts, tz=UTC),
                    ],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array([hot_descriptor.instrument_id, cold_descriptor.instrument_id]),
                "channel": pa.array([hot_descriptor.channel_id, cold_descriptor.channel_id]),
                "value": pa.array([5.0, 4.2], type=pa.float64()),
                "unit": pa.array(["K", cold_descriptor.unit]),
                "status": pa.array(["ok", "ok"]),
                "descriptor_hash": pa.array([None, cold_descriptor.descriptor_hash], type=pa.string()),
            }
        )
        pq.write_table(table, str(ppath))
        sidecar_rel = Path(rel).with_name(Path(rel).stem + ".channel_descriptors.parquet")
        sidecar = archive_dir / sidecar_rel
        pq.write_table(
            pa.table(
                {
                    "descriptor_hash": pa.array([cold_descriptor.descriptor_hash]),
                    "channel_id": pa.array([cold_descriptor.channel_id]),
                    "instrument_id": pa.array([cold_descriptor.instrument_id]),
                    "source_key": pa.array([cold_descriptor.source_key]),
                    "descriptor_revision": pa.array([cold_descriptor.descriptor_revision], type=pa.int32()),
                    "envelope_json": pa.array([envelope.canonical_json], type=pa.binary()),
                }
            ),
            sidecar,
        )
        (archive_dir / "index.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "original_name": f"data_{cold_day.date().isoformat()}.db",
                            "archive_path": rel,
                            "row_count": table.num_rows,
                            "size_bytes_archive": ppath.stat().st_size,
                            "checksum_md5": hashlib.md5(
                                ppath.read_bytes(),
                                usedforsecurity=False,
                            ).hexdigest(),
                            "channel_descriptors_path": sidecar_rel.as_posix(),
                            "channel_descriptors_rows": 1,
                            "channel_descriptors_checksum": hashlib.md5(
                                sidecar.read_bytes(),
                                usedforsecurity=False,
                            ).hexdigest(),
                            "channel_descriptors_size_bytes": sidecar.stat().st_size,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        data, catalog = writer._read_readings_history_with_descriptors(
            from_ts=cold_ts - 10,
            to_ts=now.timestamp(),
        )

        assert data[hot_descriptor.channel_id] == [(cold_ts, 5.0), (hot_ts, 10.0)]
        assert data[cold_descriptor.channel_id] == [(cold_descriptor_ts, 4.2)]
        assert catalog[hot_descriptor.channel_id] == "legacy_unknown"
        assert catalog[cold_descriptor.channel_id] == "temperature"
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_cross_tier_declared_descriptor_identity_fork_is_refused(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    now = datetime.now(UTC)
    channel = "pressure.cross.tier"
    hot_descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel,
        instrument_id="hot-thermometer",
        source_key="input.hot.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Cross-tier temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    cold_descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel,
        instrument_id="cold-thermometer",
        source_key="input.cold.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Cross-tier temperature",
        visible_by_default=True,
        display_order=2,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([hot_descriptor]))
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        hot_ts = now.timestamp() - 60
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(hot_ts, tz=UTC),
                        instrument_id=hot_descriptor.instrument_id,
                        channel=channel,
                        value=4.0,
                        unit="K",
                        status=ChannelStatus.OK,
                    )
                ]
            )
        )

        cold_day = now - timedelta(days=3)
        cold_ts = cold_day.timestamp()
        envelope = PersistedChannelEnvelopeV1.from_descriptor(cold_descriptor)
        archive_dir = tmp_path / "archive"
        rel = f"year={cold_day:%Y}/month={cold_day:%m}/data_{cold_day.date().isoformat()}.db.parquet"
        ppath = archive_dir / rel
        ppath.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "timestamp": pa.array(
                    [datetime.fromtimestamp(cold_ts, tz=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array([cold_descriptor.instrument_id]),
                "channel": pa.array([channel]),
                "value": pa.array([5.0], type=pa.float64()),
                "unit": pa.array(["K"]),
                "status": pa.array(["ok"]),
                "descriptor_hash": pa.array([cold_descriptor.descriptor_hash]),
            }
        )
        pq.write_table(table, str(ppath))
        sidecar_rel = Path(rel).with_name(Path(rel).stem + ".channel_descriptors.parquet")
        sidecar = archive_dir / sidecar_rel
        pq.write_table(
            pa.table(
                {
                    "descriptor_hash": pa.array([cold_descriptor.descriptor_hash]),
                    "channel_id": pa.array([channel]),
                    "instrument_id": pa.array([cold_descriptor.instrument_id]),
                    "source_key": pa.array([cold_descriptor.source_key]),
                    "descriptor_revision": pa.array([1], type=pa.int32()),
                    "envelope_json": pa.array([envelope.canonical_json], type=pa.binary()),
                }
            ),
            sidecar,
        )
        (archive_dir / "index.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "original_name": f"data_{cold_day.date().isoformat()}.db",
                            "archive_path": rel,
                            "row_count": 1,
                            "size_bytes_archive": ppath.stat().st_size,
                            "checksum_md5": hashlib.md5(
                                ppath.read_bytes(),
                                usedforsecurity=False,
                            ).hexdigest(),
                            "channel_descriptors_path": sidecar_rel.as_posix(),
                            "channel_descriptors_rows": 1,
                            "channel_descriptors_checksum": hashlib.md5(
                                sidecar.read_bytes(),
                                usedforsecurity=False,
                            ).hexdigest(),
                            "channel_descriptors_size_bytes": sidecar.stat().st_size,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="identity or unit"):
            writer._read_readings_history_with_descriptors(
                from_ts=cold_ts - 1,
                to_ts=now.timestamp(),
            )
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


def test_unfiltered_descriptor_history_refuses_cold_channel_overflow(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_CHANNELS

    cold_day = datetime.now(UTC) - timedelta(days=3)
    cold_ts = cold_day.timestamp()
    channels = [
        "ZZ_OLDEST",
        *(f"C{index:02d}" for index in range(_HISTORY_MAX_CHANNELS - 1)),
        "AA_NEWEST",
    ]
    archive_dir = tmp_path / "archive"
    rel = f"year={cold_day:%Y}/month={cold_day:%m}/data_{cold_day.date().isoformat()}.db.parquet"
    ppath = archive_dir / rel
    ppath.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": pa.array(
                [datetime.fromtimestamp(cold_ts + index, tz=UTC) for index in range(len(channels))],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "instrument_id": pa.array(["legacy-thermometer"] * len(channels)),
            "channel": pa.array(channels),
            "value": pa.array([float(index) for index in range(len(channels))], type=pa.float64()),
            "unit": pa.array(["K"] * len(channels)),
            "status": pa.array(["ok"] * len(channels)),
        }
    )
    pq.write_table(table, str(ppath))
    (archive_dir / "index.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "original_name": f"data_{cold_day.date().isoformat()}.db",
                        "archive_path": rel,
                        "row_count": table.num_rows,
                        "size_bytes_archive": ppath.stat().st_size,
                        "checksum_md5": hashlib.md5(
                            ppath.read_bytes(),
                            usedforsecurity=False,
                        ).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    from cryodaq.storage.archive_reader import ArchiveUnavailableError, BoundedReadIssueCode

    writer = SQLiteWriter(tmp_path)
    with pytest.raises(ArchiveUnavailableError) as exc_info:
        writer._read_readings_history_with_descriptors(
            from_ts=cold_ts - 1,
            to_ts=cold_ts + len(channels),
            limit_per_channel=2,
        )

    assert exc_info.value.issue.code == BoundedReadIssueCode.CHANNEL_LIMIT


def test_read_readings_history_unbounded_unions_cold_archive(tmp_path: Path) -> None:
    """F3: an unbounded (from_ts=None) request must also union cold archive rows.

    The cold branch was gated on ``from_ts is not None``, so a full-range /
    unbounded-past request read hot-only and silently dropped rotated days.
    from_ts=None means unbounded past → it ALWAYS reaches archived days.
    """
    pytest.importorskip("pyarrow")
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    os.environ.setdefault("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(writer.start_immediate())
    try:
        now = datetime.now(UTC)
        hot_ts = now.timestamp() - 60
        loop.run_until_complete(
            writer.write_immediate(
                [
                    Reading(
                        timestamp=datetime.fromtimestamp(hot_ts, tz=UTC),
                        instrument_id="LS218_1",
                        channel="Т1",
                        value=10.0,
                        unit="K",
                        status=ChannelStatus.OK,
                    )
                ]
            )
        )
        cold_day = now - timedelta(days=3)
        cold_ts = cold_day.timestamp()
        archive_dir = tmp_path / "archive"
        rel = f"year={cold_day:%Y}/month={cold_day:%m}/data_{cold_day.date().isoformat()}.db.parquet"
        ppath = archive_dir / rel
        ppath.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "timestamp": pa.array(
                    [datetime.fromtimestamp(cold_ts, tz=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "instrument_id": pa.array(["LS218_1"]),
                "channel": pa.array(["Т1"]),
                "value": pa.array([5.0], type=pa.float64()),
                "unit": pa.array(["K"]),
                "status": pa.array(["ok"]),
            }
        )
        pq.write_table(table, str(ppath))
        (archive_dir / "index.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "original_name": f"data_{cold_day.date().isoformat()}.db",
                            "archive_path": rel,
                            "row_count": table.num_rows,
                            "size_bytes_archive": ppath.stat().st_size,
                            "checksum_md5": hashlib.md5(
                                ppath.read_bytes(),
                                usedforsecurity=False,
                            ).hexdigest(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        # from_ts unset (None) → unbounded past. Must still union the cold row.
        data = writer._read_readings_history(to_ts=now.timestamp())
        vals = [v for _, v in data["Т1"]]
        assert 5.0 in vals, "unbounded request must union the cold archived row"
        assert 10.0 in vals, "hot row must remain"
        assert data["Т1"][0][1] == 5.0, "ASC order: cold (older) first"
        assert data["Т1"][-1][1] == 10.0
    finally:
        loop.run_until_complete(writer.stop())
        loop.close()


@pytest.mark.asyncio
async def test_async_read_readings_history(writer_with_data) -> None:
    """Async wrapper must return the same data as the sync implementation."""
    writer, base_ts = writer_with_data
    # Get sync result for comparison
    sync_data = writer._read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
    # Get async result
    async_data = await writer.read_readings_history(channels=["Т1 Камера"], limit_per_channel=5)
    assert len(async_data["Т1 Камера"]) == 5, f"Async wrapper must return 5 points, got {len(async_data['Т1 Камера'])}"
    # Async and sync must return identical data
    assert async_data["Т1 Камера"] == sync_data["Т1 Камера"], (
        "Async wrapper must return identical data to sync implementation"
    )


@pytest.mark.asyncio
async def test_readings_history_carries_the_persisted_descriptor_catalog(tmp_path: Path) -> None:
    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id="archive.temperature",
        instrument_id="thermometer",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Archived temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    try:
        assert await writer.write_immediate(
            [
                Reading(
                    timestamp=datetime.now(UTC),
                    instrument_id=descriptor.instrument_id,
                    channel=descriptor.channel_id,
                    value=4.2,
                    unit=descriptor.unit,
                    status=ChannelStatus.OK,
                )
            ]
        )
    finally:
        await writer.stop()

    reader = SQLiteWriter(tmp_path)
    try:
        data, catalog = await reader.read_readings_history_with_descriptors()

        assert list(data) == [descriptor.channel_id]
        assert catalog[descriptor.channel_id] == "temperature"
    finally:
        await reader.stop()


@pytest.mark.asyncio
async def test_descriptor_history_keeps_migrated_legacy_rows_unknown(tmp_path: Path) -> None:
    timestamp = datetime.now(UTC)
    channel = "legacy.temperature"
    writer = SQLiteWriter(tmp_path)
    try:
        assert await writer.write_immediate(
            [
                Reading(
                    timestamp=timestamp,
                    instrument_id="legacy-thermometer",
                    channel=channel,
                    value=5.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
    finally:
        await writer.stop()

    db_path = tmp_path / f"data_{timestamp.date().isoformat()}.db"
    conn = sqlite3.connect(str(db_path))
    try:
        initialize_descriptor_storage(conn)
    finally:
        conn.close()

    reader = SQLiteWriter(tmp_path)
    try:
        data, catalog = await reader.read_readings_history_with_descriptors()

        assert list(data) == [channel]
        assert catalog[channel] == "legacy_unknown"
    finally:
        await reader.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_per_channel", [1, 2])
@pytest.mark.parametrize("reverse_insertion", [False, True])
async def test_unfiltered_descriptor_history_enforces_channel_cap(
    tmp_path: Path,
    limit_per_channel: int,
    reverse_insertion: bool,
) -> None:
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_CHANNELS

    timestamp = datetime.now(UTC) - timedelta(seconds=_HISTORY_MAX_CHANNELS)
    channels = [
        "ZZ_OLDEST",
        *(f"C{index:02d}" for index in range(_HISTORY_MAX_CHANNELS - 1)),
        "AA_NEWEST",
    ]
    if reverse_insertion:
        channels.reverse()
    writer = SQLiteWriter(tmp_path)
    try:
        assert await writer.write_immediate(
            [
                Reading(
                    timestamp=timestamp,
                    instrument_id="legacy-thermometer",
                    channel=channel,
                    value=float(index),
                    unit="K",
                    status=ChannelStatus.OK,
                )
                for index, channel in enumerate(channels)
            ]
        )

        with pytest.raises(ValueError, match="more than 64 channels"):
            await writer.read_readings_history_with_descriptors(limit_per_channel=limit_per_channel)
    finally:
        await writer.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("busy_first", [False, True])
async def test_unfiltered_hot_history_channel_tie_break_is_insertion_independent(
    tmp_path: Path,
    busy_first: bool,
) -> None:
    from cryodaq.storage.sqlite_writer import _HISTORY_MAX_CHANNELS

    timestamp = datetime.now(UTC)
    busy = [
        Reading(
            timestamp=timestamp,
            instrument_id="legacy-thermometer",
            channel="A_BUSY",
            value=float(index),
            unit="K",
            status=ChannelStatus.OK,
        )
        for index in range(_HISTORY_MAX_CHANNELS + 1)
    ]
    sparse = [
        Reading(
            timestamp=timestamp,
            instrument_id="legacy-thermometer",
            channel=f"B{index:02d}",
            value=float(index),
            unit="K",
            status=ChannelStatus.OK,
        )
        for index in range(_HISTORY_MAX_CHANNELS)
    ]
    readings = [*busy, *sparse] if busy_first else [*sparse, *busy]

    writer = SQLiteWriter(tmp_path)
    try:
        assert await writer.write_immediate(readings)

        with pytest.raises(ValueError, match="more than 64 channels"):
            await writer.read_readings_history_with_descriptors(limit_per_channel=1)
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_descriptor_history_refuses_an_unverifiable_hot_catalog(tmp_path: Path) -> None:
    timestamp = datetime.now(UTC)
    db_path = tmp_path / f"data_{timestamp.date().isoformat()}.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_READINGS)
        conn.execute("ALTER TABLE readings ADD COLUMN descriptor_hash TEXT")
        conn.execute(
            "INSERT INTO readings "
            "(timestamp, instrument_id, channel, value, unit, status, descriptor_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                timestamp.timestamp(),
                "thermometer",
                "archive.temperature",
                4.2,
                "K",
                "ok",
                "sha256:" + ("0" * 64),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    writer = SQLiteWriter(tmp_path)
    try:
        with pytest.raises(ChannelDescriptorStorageError):
            await writer.read_readings_history_with_descriptors()
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_mixed_legacy_and_declared_history_remains_unknown(tmp_path: Path) -> None:
    timestamp = datetime.now(UTC) - timedelta(seconds=2)
    channel = "shared.temperature"
    legacy_writer = SQLiteWriter(tmp_path)
    try:
        assert await legacy_writer.write_immediate(
            [
                Reading(
                    timestamp=timestamp,
                    instrument_id="legacy-thermometer",
                    channel=channel,
                    value=5.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
    finally:
        await legacy_writer.stop()

    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel,
        instrument_id="declared-thermometer",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Shared temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    declared_writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    try:
        assert await declared_writer.write_immediate(
            [
                Reading(
                    timestamp=timestamp + timedelta(seconds=1),
                    instrument_id=descriptor.instrument_id,
                    channel=channel,
                    value=4.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
    finally:
        await declared_writer.stop()

    reader = SQLiteWriter(tmp_path)
    try:
        data, catalog = await reader.read_readings_history_with_descriptors()

        assert [value for _timestamp, value in data[channel]] == [5.0, 4.0]
        projection = catalog[channel]
        quantity = projection if isinstance(projection, str) else projection["quantity"]
        assert quantity == "legacy_unknown"
    finally:
        await reader.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("later_instrument_id", "later_source_key", "later_unit"),
    [
        ("thermometer-2", "input.2.temperature", "K"),
        ("thermometer-1", "input.1.temperature", "°C"),
    ],
)
async def test_cross_day_descriptor_identity_or_unit_fork_is_refused(
    tmp_path: Path,
    later_instrument_id: str,
    later_source_key: str,
    later_unit: str,
) -> None:
    channel = "shared.temperature"
    timestamps = [datetime.now(UTC) - timedelta(days=2), datetime.now(UTC) - timedelta(days=1)]
    descriptors = [
        ChannelDescriptorV1(
            schema_version=1,
            channel_id=channel,
            instrument_id="thermometer-1",
            source_key="input.1.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            role=ChannelRole.PRIMARY_MEASUREMENT,
            safety_class=ChannelSafetyClass.OBSERVATIONAL,
            display_group="Cryostat",
            display_name="Shared temperature",
            visible_by_default=True,
            display_order=1,
            descriptor_revision=1,
        ),
        ChannelDescriptorV1(
            schema_version=1,
            channel_id=channel,
            instrument_id=later_instrument_id,
            source_key=later_source_key,
            quantity=ChannelQuantity.TEMPERATURE,
            unit=later_unit,
            role=ChannelRole.PRIMARY_MEASUREMENT,
            safety_class=ChannelSafetyClass.OBSERVATIONAL,
            display_group="Cryostat",
            display_name="Shared temperature",
            visible_by_default=True,
            display_order=2,
            descriptor_revision=1,
        ),
    ]
    for timestamp, descriptor in zip(timestamps, descriptors, strict=True):
        writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
        try:
            assert await writer.write_immediate(
                [
                    Reading(
                        timestamp=timestamp,
                        instrument_id=descriptor.instrument_id,
                        channel=channel,
                        value=4.2,
                        unit=descriptor.unit,
                        status=ChannelStatus.OK,
                    )
                ]
            )
        finally:
            await writer.stop()

    reader = SQLiteWriter(tmp_path)
    try:
        with pytest.raises(ValueError, match="identity or unit"):
            await reader.read_readings_history_with_descriptors()
    finally:
        await reader.stop()


@pytest.mark.asyncio
async def test_unfiltered_descriptor_history_catalog_uses_retained_rows(tmp_path: Path) -> None:
    channel = "shared.temperature"
    old_timestamp = datetime.now(UTC) - timedelta(seconds=2)
    retained_timestamp = datetime.now(UTC) - timedelta(seconds=1)

    legacy_writer = SQLiteWriter(tmp_path)
    try:
        assert await legacy_writer.write_immediate(
            [
                Reading(
                    timestamp=old_timestamp,
                    instrument_id="legacy-thermometer",
                    channel=channel,
                    value=3.0,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            ]
        )
    finally:
        await legacy_writer.stop()

    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel,
        instrument_id="declared-thermometer",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Shared temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    writer = SQLiteWriter(tmp_path, channel_catalog=ChannelCatalog([descriptor]))
    try:
        assert await writer.write_immediate(
            [
                Reading(
                    timestamp=retained_timestamp,
                    instrument_id=descriptor.instrument_id,
                    channel=channel,
                    value=4.0,
                    unit=descriptor.unit,
                    status=ChannelStatus.OK,
                )
            ]
        )
        data, catalog = await writer.read_readings_history_with_descriptors(limit_per_channel=1)
    finally:
        await writer.stop()

    assert data[channel] == [(retained_timestamp.timestamp(), 4.0)]
    assert catalog[channel] == "temperature"
