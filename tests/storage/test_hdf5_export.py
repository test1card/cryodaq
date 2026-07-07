"""Tests for HDF5Exporter — archive-aware (hot SQLite + cold Parquet) → HDF5 export.

The exporter is per-day and archive-aware: readings flow through
``ArchiveReader.query_rows`` so a day rotated to Parquet cold storage still
exports (the hot ``data_*.db`` is gone once rotated). ``source_data`` and the
``experiments`` metadata come from the hot daily DB when it is still present
(rotation only ever fires on days that carry no ``source_data``).
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import h5py
import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.hdf5_export import HDF5Exporter, hdf5_export_days
from cryodaq.storage.sentinel import SENTINEL
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    timestamp = ts or datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _write_day(data_dir: Path, readings: list[Reading]) -> date:
    """Persist readings to their daily SQLite file; return the (UTC) day.

    The connection is closed so a subsequent ArchiveReader read (or a cold
    rotation) sees a released file.
    """
    writer = SQLiteWriter(data_dir)
    writer._write_batch(readings)
    if writer._conn is not None:
        writer._conn.close()
    writer._conn = None
    return readings[0].timestamp.date()


# ---------------------------------------------------------------------------
# 1. export() produces an .h5 file
# ---------------------------------------------------------------------------


async def test_export_creates_file(tmp_path: Path) -> None:
    day = _write_day(tmp_path, [_reading()])
    output_path = tmp_path / "export" / "test.h5"

    count = HDF5Exporter(tmp_path).export(day, output_path)

    assert output_path.exists(), "HDF5 output file was not created"
    assert count > 0, "Expected non-zero exported row count"


# ---------------------------------------------------------------------------
# 2. Exported readings have correct values in datasets
# ---------------------------------------------------------------------------


async def test_readings_in_hdf5(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    day = _write_day(
        tmp_path,
        [
            _reading("T_STAGE", 4.235, "K", ts=ts),
            _reading("T_STAGE", 4.240, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
        ],
    )
    output_path = tmp_path / "out.h5"

    HDF5Exporter(tmp_path).export(day, output_path)

    with h5py.File(str(output_path), "r") as hf:
        ch_group = hf["ls218s"]["T_STAGE"]
        values = list(ch_group["value"])
        assert len(values) == 2
        assert abs(values[0] - 4.235) < 1e-6
        assert abs(values[1] - 4.240) < 1e-6
        timestamps = list(ch_group["timestamp"])
        assert len(timestamps) == 2
        assert all(t > 0 for t in timestamps)


# ---------------------------------------------------------------------------
# 3. Each instrument_id gets its own HDF5 group
# ---------------------------------------------------------------------------


async def test_instrument_groups(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    day = _write_day(
        tmp_path,
        [
            _reading("CH1", 4.5, "K", ts=ts, instrument_id="ls218s_a"),
            _reading("CH1", 77.0, "K", ts=ts, instrument_id="ls218s_b"),
            _reading("CH2", 4.6, "K", ts=ts, instrument_id="ls218s_a"),
        ],
    )
    output_path = tmp_path / "out.h5"

    HDF5Exporter(tmp_path).export(day, output_path)

    with h5py.File(str(output_path), "r") as hf:
        assert "ls218s_a" in hf, "Group for ls218s_a not found"
        assert "ls218s_b" in hf, "Group for ls218s_b not found"
        # ls218s_a has two channels
        assert "CH1" in hf["ls218s_a"]
        assert "CH2" in hf["ls218s_a"]
        # ls218s_b has one channel
        assert "CH1" in hf["ls218s_b"]


# ---------------------------------------------------------------------------
# 4. experiment_metadata dict written as root attrs
# ---------------------------------------------------------------------------


async def test_experiment_metadata_as_attrs(tmp_path: Path) -> None:
    day = _write_day(tmp_path, [_reading()])
    output_path = tmp_path / "out.h5"

    metadata = {
        "experiment_id": "exp_001",
        "operator": "Иванов",
        "sample": "Si_wafer",
        "run_number": 42,
        "temperature_K": 4.2,
    }

    HDF5Exporter(tmp_path).export(day, output_path, experiment_metadata=metadata)

    with h5py.File(str(output_path), "r") as hf:
        assert hf.attrs["experiment_id"] == "exp_001"
        assert hf.attrs["operator"] == "Иванов"
        assert hf.attrs["sample"] == "Si_wafer"
        assert hf.attrs["run_number"] == 42
        assert abs(hf.attrs["temperature_K"] - 4.2) < 1e-9
        # Built-in provenance attrs are also present. Per-day export has no single
        # source DB path (a rotated day has no DB at all), so provenance is the
        # exported day + the export timestamp.
        assert "source_day" in hf.attrs
        assert "export_time" in hf.attrs


# ---------------------------------------------------------------------------
# 5. Day with no readings → returns 0
# ---------------------------------------------------------------------------


async def test_empty_db_returns_zero(tmp_path: Path) -> None:
    # Create a valid-schema but empty daily DB, then export that day.
    import sqlite3

    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    day = _write_day(tmp_path, [_reading(ts=ts)])
    db_path = tmp_path / f"data_{day.isoformat()}.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM readings;")
    conn.commit()
    conn.close()

    output_path = tmp_path / "out.h5"
    count = HDF5Exporter(tmp_path).export(day, output_path)

    assert count == 0, f"Expected 0 for empty day, got {count}"
    assert output_path.exists(), "HDF5 file should still be created even for an empty day"


# ---------------------------------------------------------------------------
# 6. All datasets have gzip compression enabled
# ---------------------------------------------------------------------------


async def test_hdf5_datasets_have_compression(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    day = _write_day(
        tmp_path,
        [
            _reading("T_STAGE", 4.235, "K", ts=ts),
            _reading("T_STAGE", 4.240, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
        ],
    )
    output_path = tmp_path / "compressed.h5"

    HDF5Exporter(tmp_path).export(day, output_path)

    with h5py.File(str(output_path), "r") as hf:

        def _check_compression(name: str, obj: h5py.Dataset | h5py.Group) -> None:
            if isinstance(obj, h5py.Dataset):
                assert obj.compression == "gzip", (
                    f"Dataset '{name}' missing gzip compression: {obj.compression}"
                )

        hf.visititems(_check_compression)


# ---------------------------------------------------------------------------
# 7. D-C15 — status column must be preserved (not dropped)
# ---------------------------------------------------------------------------


async def test_hdf5_preserves_status(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    day = _write_day(
        tmp_path,
        [
            _reading("T_STAGE", 4.2, "K", ts=ts, status=ChannelStatus.OK),
            _reading(
                "T_STAGE",
                4.3,
                "K",
                ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC),
                status=ChannelStatus.SENSOR_ERROR,
            ),
        ],
    )
    output_path = tmp_path / "status.h5"

    HDF5Exporter(tmp_path).export(day, output_path)

    with h5py.File(str(output_path), "r") as hf:
        grp = hf["ls218s"]["T_STAGE"]
        assert "status" in grp, f"status dataset dropped: {list(grp.keys())}"
        statuses = [s.decode() if isinstance(s, bytes) else s for s in grp["status"]]
        assert len(statuses) == 2, f"expected 2 statuses, got {statuses}"
        assert statuses[0] == ChannelStatus.OK.value
        assert statuses[1] == ChannelStatus.SENSOR_ERROR.value


# ---------------------------------------------------------------------------
# 8. D-C16 — channel names that sanitize to the same string must not crash
# ---------------------------------------------------------------------------


async def test_hdf5_sanitize_name_collision(tmp_path: Path) -> None:
    """Two distinct names collapsing to one sanitized name must not raise.

    'A:B' and 'A B' both sanitize to 'A_B'; naive require_group reuse then
    fails on the second create_dataset('timestamp').
    """
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    day = _write_day(
        tmp_path,
        [
            _reading("A:B", 1.0, "K", ts=ts),
            _reading("A B", 2.0, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
        ],
    )
    output_path = tmp_path / "collide.h5"

    count = HDF5Exporter(tmp_path).export(day, output_path)  # must not raise
    assert count == 2, f"expected 2 exported readings, got {count}"

    with h5py.File(str(output_path), "r") as hf:
        inst = hf["ls218s"]
        # Both channels must be represented as distinct groups
        ch_groups = [k for k in inst if isinstance(inst[k], h5py.Group)]
        assert len(ch_groups) == 2, f"collision dropped a channel: {ch_groups}"


# ---------------------------------------------------------------------------
# NaN-доктрина: sentinel/error values are masked in the value dataset
# ---------------------------------------------------------------------------


async def test_hdf5_masks_sentinel_value(tmp_path: Path) -> None:
    day = _write_day(
        tmp_path,
        [
            _reading("CH1", 4.5, ts=datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)),
            _reading(
                "CH1",
                float("nan"),
                ts=datetime(2026, 3, 14, 12, 0, 30, tzinfo=UTC),
                status=ChannelStatus.SENSOR_ERROR,
            ),
        ],
    )
    output_path = tmp_path / "masked.h5"
    HDF5Exporter(tmp_path).export(day, output_path)

    with h5py.File(str(output_path), "r") as hf:
        ch = hf["ls218s"]["CH1"]
        values = list(ch["value"][:])
        statuses = [s.decode() if isinstance(s, bytes) else s for s in ch["status"][:]]
    assert SENTINEL not in values, "sentinel leaked into HDF5 value dataset"
    assert not any(math.isinf(v) for v in values), "inf leaked into HDF5"
    assert 4.5 in values, "usable reading must survive"
    assert any(math.isnan(v) for v in values), "non-usable reading must be masked to NaN"
    assert "sensor_error" in statuses, "status column must be preserved for forensics"


# ---------------------------------------------------------------------------
# Cold rotation: a day rotated to Parquet must still export (the last blind reader)
# ---------------------------------------------------------------------------

pytest.importorskip("pyarrow")

from cryodaq.storage.cold_rotation import ColdRotationService  # noqa: E402

_TODAY = datetime(2026, 4, 29, tzinfo=UTC)


def test_hdf5_export_reads_rotated_day(tmp_path: Path) -> None:
    """Rotated-day readings live only in Parquet — export must find them there."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = _TODAY - timedelta(days=40)
    _write_day(data_dir, [_reading("T1", 70.0, ts=old_day.replace(hour=12))])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=_TODAY))
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists(), (
        "precondition: old day must be rotated (SQLite deleted)"
    )

    out = tmp_path / "rotated.h5"
    count = HDF5Exporter(data_dir, archive_dir).export(old_day.date(), out)

    assert count == 1, "rotated-day reading must export from Parquet"
    with h5py.File(str(out), "r") as hf:
        values = list(hf["ls218s"]["T1"]["value"])
    assert values == [pytest.approx(70.0)], "rotated value missing from HDF5"


def test_hdf5_rotated_day_masks_sentinel(tmp_path: Path) -> None:
    """A sentinel row rotated to Parquet must surface as NaN with status intact."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = _TODAY - timedelta(days=40)
    _write_day(
        data_dir,
        [
            _reading("T1", 70.0, ts=old_day.replace(hour=12)),
            _reading(
                "T1",
                float("nan"),
                ts=old_day.replace(hour=13),
                status=ChannelStatus.SENSOR_ERROR,
            ),
        ],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=_TODAY))

    out = tmp_path / "rotated_masked.h5"
    HDF5Exporter(data_dir, archive_dir).export(old_day.date(), out)

    with h5py.File(str(out), "r") as hf:
        ch = hf["ls218s"]["T1"]
        values = list(ch["value"][:])
        statuses = [s.decode() if isinstance(s, bytes) else s for s in ch["status"][:]]
    assert SENTINEL not in values, "sentinel leaked out of cold Parquet into HDF5"
    assert 70.0 in values, "usable reading must survive"
    assert any(math.isnan(v) for v in values), "sentinel row must mask to NaN"
    assert "sensor_error" in statuses, "status must be preserved from cold storage"


def test_hdf5_export_days_unions_hot_and_cold(tmp_path: Path) -> None:
    """The GUI enumeration helper lists both rotated (cold) and live (hot) days."""
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = _TODAY - timedelta(days=40)
    recent_day = _TODAY - timedelta(days=1)
    _write_day(data_dir, [_reading("T1", 70.0, ts=old_day.replace(hour=12))])
    _write_day(data_dir, [_reading("T2", 85.0, ts=recent_day.replace(hour=12))])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=_TODAY))
    # old day rotated (no hot DB), recent day still hot
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    days = hdf5_export_days(data_dir, archive_dir)
    assert old_day.date().isoformat() in days, "rotated day missing from enumeration"
    assert recent_day.date().isoformat() in days, "hot day missing from enumeration"
