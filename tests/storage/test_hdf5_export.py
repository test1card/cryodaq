"""Tests for HDF5Exporter — SQLite → HDF5 export."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import h5py

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.hdf5_export import HDF5Exporter
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


def _populate_db(tmp_path: Path, readings: list[Reading]) -> Path:
    """Write readings to a SQLite DB and return its path."""
    writer = SQLiteWriter(tmp_path)
    writer._write_batch(readings)
    day = readings[0].timestamp.date()
    return tmp_path / f"data_{day.isoformat()}.db"


# ---------------------------------------------------------------------------
# 1. export() produces an .h5 file
# ---------------------------------------------------------------------------


async def test_export_creates_file(tmp_path: Path) -> None:
    db_path = _populate_db(tmp_path, [_reading()])
    output_path = tmp_path / "export" / "test.h5"

    exporter = HDF5Exporter()
    count = exporter.export(db_path, output_path)

    assert output_path.exists(), "HDF5 output file was not created"
    assert count > 0, "Expected non-zero exported row count"


# ---------------------------------------------------------------------------
# 2. Exported readings have correct values in datasets
# ---------------------------------------------------------------------------


async def test_readings_in_hdf5(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    readings = [
        _reading("T_STAGE", 4.235, "K", ts=ts),
        _reading("T_STAGE", 4.240, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
    ]
    db_path = _populate_db(tmp_path, readings)
    output_path = tmp_path / "out.h5"

    HDF5Exporter().export(db_path, output_path)

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
    readings = [
        _reading("CH1", 4.5, "K", ts=ts, instrument_id="ls218s_a"),
        _reading("CH1", 77.0, "K", ts=ts, instrument_id="ls218s_b"),
        _reading("CH2", 4.6, "K", ts=ts, instrument_id="ls218s_a"),
    ]
    db_path = _populate_db(tmp_path, readings)
    output_path = tmp_path / "out.h5"

    HDF5Exporter().export(db_path, output_path)

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
    db_path = _populate_db(tmp_path, [_reading()])
    output_path = tmp_path / "out.h5"

    metadata = {
        "experiment_id": "exp_001",
        "operator": "Иванов",
        "sample": "Si_wafer",
        "run_number": 42,
        "temperature_K": 4.2,
    }

    HDF5Exporter().export(db_path, output_path, experiment_metadata=metadata)

    with h5py.File(str(output_path), "r") as hf:
        assert hf.attrs["experiment_id"] == "exp_001"
        assert hf.attrs["operator"] == "Иванов"
        assert hf.attrs["sample"] == "Si_wafer"
        assert hf.attrs["run_number"] == 42
        assert abs(hf.attrs["temperature_K"] - 4.2) < 1e-9
        # Built-in attrs are also present
        assert "source_db" in hf.attrs
        assert "export_time" in hf.attrs


# ---------------------------------------------------------------------------
# 5. DB with no readings → returns 0
# ---------------------------------------------------------------------------


async def test_empty_db_returns_zero(tmp_path: Path) -> None:
    # Create an empty DB by writing an empty batch (no-op) — but that doesn't
    # create the file. Instead write one reading to trigger DB creation, then
    # delete the data from the table.
    import sqlite3

    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    writer._write_batch([_reading(ts=ts)])
    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"
    if writer._conn is not None:
        writer._conn.close()  # close, don't just drop the ref — Windows locks open DB files
    writer._conn = None

    # Wipe the rows so we have a valid-schema but empty DB
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM readings;")
    conn.commit()
    conn.close()

    output_path = tmp_path / "out.h5"
    count = HDF5Exporter().export(db_path, output_path)

    assert count == 0, f"Expected 0 for empty DB, got {count}"
    assert output_path.exists(), "HDF5 file should still be created even for empty DB"


# ---------------------------------------------------------------------------
# 6. All datasets have gzip compression enabled
# ---------------------------------------------------------------------------


async def test_hdf5_datasets_have_compression(tmp_path: Path) -> None:
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    readings = [
        _reading("T_STAGE", 4.235, "K", ts=ts),
        _reading("T_STAGE", 4.240, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
    ]
    db_path = _populate_db(tmp_path, readings)
    output_path = tmp_path / "compressed.h5"

    HDF5Exporter().export(db_path, output_path)

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
    readings = [
        _reading("T_STAGE", 4.2, "K", ts=ts, status=ChannelStatus.OK),
        _reading(
            "T_STAGE",
            4.3,
            "K",
            ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC),
            status=ChannelStatus.SENSOR_ERROR,
        ),
    ]
    db_path = _populate_db(tmp_path, readings)
    output_path = tmp_path / "status.h5"

    HDF5Exporter().export(db_path, output_path)

    with h5py.File(str(output_path), "r") as hf:
        grp = hf["ls218s"]["T_STAGE"]
        assert "status" in grp, f"status dataset dropped: {list(grp.keys())}"
        statuses = [
            s.decode() if isinstance(s, bytes) else s for s in grp["status"]
        ]
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
    readings = [
        _reading("A:B", 1.0, "K", ts=ts),
        _reading("A B", 2.0, "K", ts=datetime(2026, 3, 14, 10, 0, 1, tzinfo=UTC)),
    ]
    db_path = _populate_db(tmp_path, readings)
    output_path = tmp_path / "collide.h5"

    count = HDF5Exporter().export(db_path, output_path)  # must not raise
    assert count == 2, f"expected 2 exported readings, got {count}"

    with h5py.File(str(output_path), "r") as hf:
        inst = hf["ls218s"]
        # Both channels must be represented as distinct groups
        ch_groups = [k for k in inst if isinstance(inst[k], h5py.Group)]
        assert len(ch_groups) == 2, f"collision dropped a channel: {ch_groups}"
