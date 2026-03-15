"""Tests for XLSXExporter — SQLite → XLSX export with sheet structure and filters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
from cryodaq.storage.xlsx_export import XLSXExporter

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Write readings directly into the data_dir via SQLiteWriter._write_batch()."""
    writer = SQLiteWriter(data_dir)
    writer._write_batch(readings)
    writer._conn = None  # release without graceful teardown


# ---------------------------------------------------------------------------
# 1. export() creates an XLSX file and returns a positive row count
# ---------------------------------------------------------------------------


async def test_xlsx_creates_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    readings = [_reading("CH1", 4.5, ts=ts) for _ in range(5)]
    _populate_db(data_dir, readings)

    output_path = tmp_path / "out.xlsx"
    exporter = XLSXExporter(data_dir)
    count = exporter.export(output_path)

    assert output_path.exists(), "XLSX file was not created"
    assert count > 0, f"Expected count > 0, got {count}"


# ---------------------------------------------------------------------------
# 2. Workbook has exactly two sheets: "Данные" and "Информация"
# ---------------------------------------------------------------------------


async def test_xlsx_has_two_sheets(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)
    _populate_db(data_dir, [_reading(ts=ts)])

    output_path = tmp_path / "out.xlsx"
    XLSXExporter(data_dir).export(output_path)

    wb = openpyxl.load_workbook(output_path)
    assert wb.sheetnames == ["Данные", "Информация"], (
        f"Unexpected sheet names: {wb.sheetnames}"
    )


# ---------------------------------------------------------------------------
# 3. "Данные" sheet contains correct headers and known data values
# ---------------------------------------------------------------------------


async def test_xlsx_data_values_correct(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)

    readings = [
        _reading("CH1", 4.5, "K", ts=ts),
        _reading("CH2", 77.0, "K", ts=ts),
    ]
    _populate_db(data_dir, readings)

    output_path = tmp_path / "out.xlsx"
    XLSXExporter(data_dir).export(output_path)

    wb = openpyxl.load_workbook(output_path)
    ws = wb["Данные"]

    # Pivoted format: header = ["Время", "CH1", "CH2"]
    header = [cell.value for cell in ws[1]]
    assert "CH1" in header, f"CH1 missing from header: {header}"
    assert "CH2" in header, f"CH2 missing from header: {header}"

    ch1_col = header.index("CH1") + 1
    ch2_col = header.index("CH2") + 1

    # Read first data row
    ch1_val = ws.cell(row=2, column=ch1_col).value
    ch2_val = ws.cell(row=2, column=ch2_col).value

    assert ch1_val is not None and abs(ch1_val - 4.5) < 0.01, f"CH1 value: {ch1_val}"
    assert ch2_val is not None and abs(ch2_val - 77.0) < 0.01, f"CH2 value: {ch2_val}"


# ---------------------------------------------------------------------------
# 4. Empty DB → export returns 0 and file is created with no data rows
# ---------------------------------------------------------------------------


async def test_xlsx_empty_db_returns_zero(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    # Initialise the DB schema without inserting any readings
    writer = SQLiteWriter(data_dir)
    writer._ensure_connection(datetime(2026, 3, 14).date())
    writer._conn = None

    output_path = tmp_path / "out.xlsx"
    exporter = XLSXExporter(data_dir)
    count = exporter.export(output_path)

    assert count == 0, f"Expected 0 rows from empty DB, got {count}"
    assert output_path.exists(), "XLSX should be created even when DB is empty"

    wb = openpyxl.load_workbook(output_path)
    ws = wb["Данные"]
    # Row 1 is the header; no data rows expected
    assert ws.max_row <= 1, f"Expected no data rows, found max_row={ws.max_row}"


# ---------------------------------------------------------------------------
# 5. Channel filter — only requested channels appear in the output
# ---------------------------------------------------------------------------


async def test_xlsx_channel_filter(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ts = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)

    readings = [
        _reading("CH1", 4.5, "K", ts=ts),
        _reading("CH2", 77.0, "K", ts=ts),
        _reading("CH3", 300.0, "K", ts=ts),
    ]
    _populate_db(data_dir, readings)

    output_path = tmp_path / "out.xlsx"
    count = XLSXExporter(data_dir).export(output_path, channels=["CH1"])

    assert count >= 1, f"Expected at least 1 row for CH1 filter, got {count}"

    wb = openpyxl.load_workbook(output_path)
    ws = wb["Данные"]

    # Pivoted: header should only have Время + CH1 (not CH2, CH3)
    header = [cell.value for cell in ws[1]]
    assert "CH1" in header, f"CH1 missing from header: {header}"
    assert "CH2" not in header, f"CH2 should not be in filtered output: {header}"
    assert "CH3" not in header, f"CH3 should not be in filtered output: {header}"
