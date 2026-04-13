"""Tests for Parquet experiment archive — pyarrow optional."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _make_readings(n: int = 100, channels: int = 3) -> list[dict[str, Any]]:
    """Build synthetic readings in _load_experiment_readings format."""
    base_ts = datetime(2026, 3, 21, 12, 0, 0, tzinfo=UTC)
    readings = []
    for i in range(n):
        for ch_idx in range(channels):
            ts = datetime.fromtimestamp(
                base_ts.timestamp() + i * 0.5, tz=UTC
            )
            readings.append({
                "timestamp": ts,
                "instrument_id": "LS218_1",
                "channel": f"T{ch_idx + 1}",
                "value": 4.2 + i * 0.001 + ch_idx * 10,
                "unit": "K",
                "status": "ok",
            })
    return readings


# ---------------------------------------------------------------------------
# Tests requiring pyarrow
# ---------------------------------------------------------------------------


def test_write_creates_parquet(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    from cryodaq.storage.parquet_archive import write_experiment_parquet

    readings = _make_readings(50, 2)
    out = tmp_path / "readings.parquet"
    result = write_experiment_parquet(readings, out)

    assert result == out
    assert out.exists()

    import pyarrow.parquet as pq
    table = pq.read_table(str(out))
    assert table.num_rows == 100  # 50 × 2 channels
    assert set(table.column_names) == {"timestamp", "instrument_id", "channel", "value", "unit", "status"}


def test_write_skips_if_exists(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    from cryodaq.storage.parquet_archive import write_experiment_parquet

    readings = _make_readings(10)
    out = tmp_path / "readings.parquet"
    write_experiment_parquet(readings, out)
    mtime1 = out.stat().st_mtime

    time.sleep(0.05)
    result = write_experiment_parquet(readings, out)
    mtime2 = out.stat().st_mtime

    assert result == out
    assert mtime1 == mtime2  # not rewritten


def test_write_empty_readings(tmp_path: Path) -> None:
    from cryodaq.storage.parquet_archive import write_experiment_parquet

    result = write_experiment_parquet([], tmp_path / "empty.parquet")
    assert result is None


def test_write_no_pyarrow(tmp_path: Path) -> None:
    import cryodaq.storage.parquet_archive as mod

    with patch.dict("sys.modules", {"pyarrow": None, "pyarrow.parquet": None}):
        # Force re-import to hit the ImportError path
        result = mod.write_experiment_parquet(
            _make_readings(5), tmp_path / "nope.parquet"
        )
    assert result is None
    assert not (tmp_path / "nope.parquet").exists()


def test_read_experiment(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    from cryodaq.storage.parquet_archive import read_experiment_parquet, write_experiment_parquet

    readings = _make_readings(20, 2)
    out = tmp_path / "readings.parquet"
    write_experiment_parquet(readings, out)

    result = read_experiment_parquet(out)
    assert "T1" in result
    assert "T2" in result
    assert len(result["T1"]) == 20
    assert len(result["T2"]) == 20

    # Check format: (float_epoch, float_value)
    ts, val = result["T1"][0]
    assert isinstance(ts, float)
    assert isinstance(val, float)


def test_read_with_channel_filter(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    from cryodaq.storage.parquet_archive import read_experiment_parquet, write_experiment_parquet

    readings = _make_readings(20, 3)
    out = tmp_path / "readings.parquet"
    write_experiment_parquet(readings, out)

    result = read_experiment_parquet(out, channels=["T2"])
    assert "T2" in result
    assert "T1" not in result
    assert "T3" not in result


def test_timestamp_precision(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    from cryodaq.storage.parquet_archive import read_experiment_parquet, write_experiment_parquet

    # Create reading with microsecond precision
    precise_ts = datetime(2026, 3, 21, 12, 0, 0, 123456, tzinfo=UTC)
    readings = [{
        "timestamp": precise_ts,
        "instrument_id": "test",
        "channel": "T1",
        "value": 4.2,
        "unit": "K",
        "status": "ok",
    }]
    out = tmp_path / "precision.parquet"
    write_experiment_parquet(readings, out)

    result = read_experiment_parquet(out)
    ts_epoch = result["T1"][0][0]

    # Verify microsecond precision preserved
    original_epoch = precise_ts.timestamp()
    assert abs(ts_epoch - original_epoch) < 1e-6
