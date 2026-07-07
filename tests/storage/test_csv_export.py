"""Tests for CSVExporter — SQLite → CSV export with time-range and channel filters."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.csv_export import CSVExporter
from cryodaq.storage.sentinel import SENTINEL
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_HEADER = ["timestamp", "instrument_id", "channel", "value", "unit", "status"]


def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime,
    instrument_id: str = "ls218s",
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _populate_db(data_dir: Path, readings: list[Reading]) -> None:
    """Write readings into the data_dir using SQLiteWriter."""
    writer = SQLiteWriter(data_dir)
    writer._write_batch(readings)
    if writer._conn is not None:
        writer._conn.close()  # close, don't just drop the ref — Windows locks open DB files
    writer._conn = None


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Return (header, rows) from a CSV file."""
    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)
    return list(header), rows


# ---------------------------------------------------------------------------
# 1. export() produces a CSV file with a header row
# ---------------------------------------------------------------------------


async def test_export_creates_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    _populate_db(data_dir, [_reading(ts=ts)])

    output_path = tmp_path / "out.csv"
    exporter = CSVExporter(data_dir)
    count = exporter.export(output_path)

    assert output_path.exists(), "CSV file was not created"
    assert count == 1, f"Expected 1 exported row, got {count}"


# ---------------------------------------------------------------------------
# 2. Header is exactly: timestamp,instrument_id,channel,value,unit,status
# ---------------------------------------------------------------------------


async def test_correct_columns(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    _populate_db(data_dir, [_reading(ts=ts)])

    output_path = tmp_path / "out.csv"
    CSVExporter(data_dir).export(output_path)

    header, _ = _read_csv(output_path)
    assert header == _EXPECTED_HEADER, f"Unexpected CSV header: {header}"


# ---------------------------------------------------------------------------
# 3. Time-range filter — only readings within start/end exported
# ---------------------------------------------------------------------------


async def test_time_range_filter(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"

    early = datetime(2026, 3, 14, 8, 0, 0, tzinfo=UTC)
    inside = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    late = datetime(2026, 3, 14, 20, 0, 0, tzinfo=UTC)

    readings = [
        _reading("CH1", 1.0, "K", ts=early),
        _reading("CH2", 2.0, "K", ts=inside),
        _reading("CH3", 3.0, "K", ts=late),
    ]
    _populate_db(data_dir, readings)

    output_path = tmp_path / "out.csv"
    start = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 14, 15, 0, 0, tzinfo=UTC)

    count = CSVExporter(data_dir).export(output_path, start=start, end=end)

    _, rows = _read_csv(output_path)
    assert count == 1, f"Expected 1 row in range, got {count}"
    assert len(rows) == 1
    assert rows[0]["channel"] == "CH2"


# ---------------------------------------------------------------------------
# 4. Channel filter — only specified channels exported
# ---------------------------------------------------------------------------


async def test_channel_filter(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)

    readings = [
        _reading("T_STAGE", 4.2, "K", ts=ts),
        _reading("T_SHIELD", 77.0, "K", ts=ts),
        _reading("T_300K", 300.0, "K", ts=ts),
    ]
    _populate_db(data_dir, readings)

    output_path = tmp_path / "out.csv"
    count = CSVExporter(data_dir).export(output_path, channels=["T_STAGE", "T_300K"])

    _, rows = _read_csv(output_path)
    assert count == 2, f"Expected 2 rows, got {count}"
    channels_in_csv = {r["channel"] for r in rows}
    assert channels_in_csv == {"T_STAGE", "T_300K"}
    assert "T_SHIELD" not in channels_in_csv


# ---------------------------------------------------------------------------
# 5. No matching data → file with header only, returns 0
# ---------------------------------------------------------------------------


async def test_empty_result(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    _populate_db(data_dir, [_reading("CH1", ts=ts)])

    output_path = tmp_path / "out.csv"
    # Request a channel that doesn't exist in the DB
    count = CSVExporter(data_dir).export(output_path, channels=["NONEXISTENT"])

    assert count == 0, f"Expected 0 rows, got {count}"
    assert output_path.exists(), "CSV should still be created even when empty"

    header, rows = _read_csv(output_path)
    assert header == _EXPECTED_HEADER, "Header row missing or wrong in empty export"
    assert len(rows) == 0, "Expected no data rows in empty export"


# ---------------------------------------------------------------------------
# 6. D-C9 / ME-10 — early local-hours range must select correct UTC day file
# ---------------------------------------------------------------------------


async def test_csv_selects_utc_day_for_early_local_hours(tmp_path: Path) -> None:
    """A range whose local start is 00:00 MSK must still select the UTC day file.

    Regression: _find_db_files compared UTC-named files against caller-tz
    start.date()/end.date(), dropping early-hours rows.
    """
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 13, 22, 30, 0, tzinfo=UTC)  # lives in data_2026-03-13.db
    _populate_db(data_dir, [_reading("CH1", 1.0, "K", ts=ts)])

    msk = timezone(timedelta(hours=3))
    start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=msk)  # 2026-03-13 21:00 UTC
    end = datetime(2026, 3, 14, 6, 0, 0, tzinfo=msk)  # 2026-03-14 03:00 UTC

    output_path = tmp_path / "early.csv"
    count = CSVExporter(data_dir).export(output_path, start=start, end=end)

    _, rows = _read_csv(output_path)
    assert count == 1, f"early-hours UTC day file dropped: got {count}"
    assert len(rows) == 1
    assert rows[0]["channel"] == "CH1"


# ---------------------------------------------------------------------------
# NaN-доктрина: sentinel/error rows carry status but never a real value
# ---------------------------------------------------------------------------


def test_csv_masks_sentinel_value(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts_good = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    ts_bad = datetime(2026, 3, 14, 12, 0, 30, tzinfo=UTC)
    _populate_db(
        data_dir,
        [
            _reading("CH1", 4.5, ts=ts_good, status=ChannelStatus.OK),
            _reading("CH1", float("nan"), ts=ts_bad, status=ChannelStatus.SENSOR_ERROR),
        ],
    )

    output_path = tmp_path / "masked.csv"
    CSVExporter(data_dir).export(output_path)

    _, rows = _read_csv(output_path)
    by_status = {r["status"]: r for r in rows}
    bad = by_status["sensor_error"]
    assert str(SENTINEL) not in bad["value"], "sentinel leaked into CSV value"
    assert bad["value"].strip().lower() not in {"inf", "-inf", "nan"}
    assert bad["value"] == "", "non-usable value must be blank, status preserved"
    assert by_status["ok"]["value"] not in ("", None)
