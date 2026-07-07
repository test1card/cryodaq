"""NaN-доктрина: report data extraction masks sentinel/error rows.

A stored sentinel (-8.888e88) or legacy raw ±inf from a data_*.db must never
reach a HistoricalReading as a real number — it decodes to NaN so report
tables/plots present "no reading", never the sentinel.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.reporting.data import ReportDataExtractor
from cryodaq.storage.sentinel import SENTINEL


def _create_db(db_path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp REAL NOT NULL, instrument_id TEXT NOT NULL, channel TEXT NOT NULL, "
        "value REAL NOT NULL, unit TEXT NOT NULL, status TEXT NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_archived_blank_value_decodes_to_nan(tmp_path: Path) -> None:
    """NaN-доктрина: a blank masked cell in an archived CSV must read as NaN,
    not 0.0 — a blank means "no reading", not a zero-valued measurement."""
    csv_path = tmp_path / "measured_values.csv"
    csv_path.write_text(
        "timestamp,instrument_id,channel,value,unit,status\n"
        "2026-04-14T00:00:00Z,ls218s,Т1,,K,\n"
        "2026-04-14T00:00:01Z,ls218s,Т1,77.0,K,ok\n",
        encoding="utf-8",
    )
    metadata = {"result_tables": [{"table_id": "measured_values", "path": str(csv_path)}]}
    extractor = ReportDataExtractor(tmp_path)
    rows = extractor._load_archived_readings(metadata)
    assert len(rows) == 2
    assert math.isnan(rows[0].value), "blank cell must be NaN, not 0.0"
    assert rows[1].value == 77.0, "finite value must survive"


def test_load_readings_masks_nonfinite(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()
    _create_db(
        tmp_path / f"data_{day.date().isoformat()}.db",
        [
            (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
            (base_ts + 1, "ls218s", "Т1", SENTINEL, "K", "sensor_error"),
            (base_ts + 2, "ls218s", "Т1", float("inf"), "K", "overrange"),  # legacy raw inf
        ],
    )
    extractor = ReportDataExtractor(tmp_path)
    readings = extractor._load_readings(day, day.replace(hour=23, minute=59))

    vals = [r.value for r in readings]
    assert 77.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"
