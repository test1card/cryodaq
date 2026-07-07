"""NaN-доктрина: experiment reading load masks sentinel/error rows.

ExperimentManager._load_experiment_readings reads raw data_*.db rows for the
report dataset; a stored sentinel or legacy raw ±inf must decode to NaN.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.core.experiment import ExperimentInfo, ExperimentManager, ExperimentStatus
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


def test_load_experiment_readings_masks_nonfinite(tmp_path: Path) -> None:
    start = datetime(2026, 4, 14, tzinfo=UTC)
    end = start.replace(hour=23, minute=59)
    base_ts = start.timestamp()
    _create_db(
        tmp_path / f"data_{start.date().isoformat()}.db",
        [
            (base_ts, "ls218s", "Т1", 77.0, "K", "ok"),
            (base_ts + 1, "ls218s", "Т1", SENTINEL, "K", "sensor_error"),
            (base_ts + 2, "ls218s", "Т1", float("inf"), "K", "overrange"),  # legacy raw inf
        ],
    )
    # Only _data_dir is needed by _load_experiment_readings — build a bare manager.
    mgr = ExperimentManager.__new__(ExperimentManager)
    mgr._data_dir = tmp_path
    info = ExperimentInfo(
        experiment_id="exp1",
        name="e",
        title="e",
        template_id="t",
        operator="op",
        cryostat="c",
        sample="s",
        description="",
        notes="",
        start_time=start,
        end_time=end,
        status=ExperimentStatus.COMPLETED,
    )

    rows = mgr._load_experiment_readings(info)
    vals = [r["value"] for r in rows]
    assert 77.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"
