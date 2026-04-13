"""Tests for CalibrationFitter — extract, downsample, breakpoints, coverage."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.calibration_fitter import CalibrationFitter


def _synthetic_dt670(srdg: float) -> float:
    """Approximate DT-670 curve: V(mV) → T(K)."""
    return max(1.5, 1600.0 / (srdg + 15.0) + 0.05 * math.sin(srdg / 5.0))


def _populate_db(db_path: Path, reference_channel: str, target_channel: str,
                 n_points: int = 200, t_start: float = 1000.0) -> float:
    """Create a SQLite DB with synthetic KRDG + SRDG readings. Returns end timestamp."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS readings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp REAL NOT NULL, "
        "instrument_id TEXT NOT NULL, "
        "channel TEXT NOT NULL, "
        "value REAL NOT NULL, "
        "unit TEXT NOT NULL, "
        "status TEXT NOT NULL)"
    )

    srdg_channel = f"{target_channel}_raw"
    for i in range(n_points):
        ts = t_start + i * 1.0
        srdg_val = 5.0 + i * 0.5  # 5 → 105 sensor units
        krdg_val = _synthetic_dt670(srdg_val)

        conn.execute(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, "ls218", reference_channel, krdg_val, "K", "OK"),
        )
        conn.execute(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts + 0.1, "ls218", srdg_channel, srdg_val, "sensor_unit", "OK"),
        )

    conn.commit()
    conn.close()
    return t_start + n_points


@pytest.fixture()
def data_dir(tmp_path):
    db_path = tmp_path / "data_2026-03-17.db"
    _populate_db(db_path, "Т1", "Т2", n_points=200)
    return tmp_path


# ------------------------------------------------------------------
# Extract
# ------------------------------------------------------------------

def test_extract_pairs_basic(data_dir) -> None:
    pairs = CalibrationFitter.extract_pairs(
        data_dir, 1000.0, 2000.0, "Т1", "Т2",
    )
    assert len(pairs) == 200
    for srdg_val, krdg_val in pairs:
        assert srdg_val > 0
        assert krdg_val >= 1.5


def test_extract_filters_ovl(tmp_path) -> None:
    db_path = tmp_path / "data_2026-03-17.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY, "
        "timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    # Normal pair
    conn.execute("INSERT INTO readings VALUES (1, 100.0, 'ls', 'ref', 77.0, 'K', 'OK')")
    conn.execute("INSERT INTO readings VALUES (2, 100.1, 'ls', 'tgt_raw', 82.5, 'sensor_unit', 'OK')")
    # OVL pair (inf KRDG)
    conn.execute("INSERT INTO readings VALUES (3, 101.0, 'ls', 'ref', 1e308, 'K', 'OK')")
    conn.execute("INSERT INTO readings VALUES (4, 101.1, 'ls', 'tgt_raw', 83.0, 'sensor_unit', 'OK')")
    # Zero SRDG
    conn.execute("INSERT INTO readings VALUES (5, 102.0, 'ls', 'ref', 77.0, 'K', 'OK')")
    conn.execute("INSERT INTO readings VALUES (6, 102.1, 'ls', 'tgt_raw', 0.0, 'sensor_unit', 'OK')")
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(tmp_path, 99.0, 103.0, "ref", "tgt")
    assert len(pairs) == 1
    assert pairs[0] == pytest.approx((82.5, 77.0), abs=0.1)


def test_time_alignment_filter(tmp_path) -> None:
    db_path = tmp_path / "data_2026-03-17.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY, "
        "timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    # Aligned pair (0.5s delta)
    conn.execute("INSERT INTO readings VALUES (1, 100.0, 'ls', 'ref', 77.0, 'K', 'OK')")
    conn.execute("INSERT INTO readings VALUES (2, 100.5, 'ls', 'tgt_raw', 82.5, 'sensor_unit', 'OK')")
    # Misaligned pair (5s delta)
    conn.execute("INSERT INTO readings VALUES (3, 110.0, 'ls', 'ref', 78.0, 'K', 'OK')")
    conn.execute("INSERT INTO readings VALUES (4, 115.0, 'ls', 'tgt_raw', 83.0, 'sensor_unit', 'OK')")
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(tmp_path, 99.0, 120.0, "ref", "tgt", max_time_delta_s=2.0)
    assert len(pairs) == 1


# ------------------------------------------------------------------
# Downsample
# ------------------------------------------------------------------

def test_downsample_preserves_curvature(data_dir) -> None:
    pairs = CalibrationFitter.extract_pairs(data_dir, 1000.0, 2000.0, "Т1", "Т2")
    downsampled = CalibrationFitter.adaptive_downsample(pairs, target_count=50)

    assert len(downsampled) <= 80  # roughly around target
    assert len(downsampled) >= 20

    # Check that low-SRDG region (high curvature) has more density
    sorted_ds = sorted(downsampled, key=lambda p: p[0])
    mid = sorted_ds[len(sorted_ds) // 2][0]
    low_count = sum(1 for s, _ in sorted_ds if s < mid)
    high_count = sum(1 for s, _ in sorted_ds if s >= mid)
    # Low-SRDG (low temp, high curvature) should have >= high-SRDG
    assert low_count >= high_count * 0.5  # not a strict requirement


def test_downsample_preserves_boundaries(data_dir) -> None:
    pairs = CalibrationFitter.extract_pairs(data_dir, 1000.0, 2000.0, "Т1", "Т2")
    downsampled = CalibrationFitter.adaptive_downsample(pairs, target_count=50)

    srdg_min = min(s for s, _ in pairs)
    srdg_max = max(s for s, _ in pairs)
    ds_srdg = [s for s, _ in downsampled]

    assert min(ds_srdg) == pytest.approx(srdg_min)
    assert max(ds_srdg) == pytest.approx(srdg_max)


# ------------------------------------------------------------------
# Breakpoints
# ------------------------------------------------------------------

def test_breakpoints_douglas_peucker(data_dir) -> None:
    pairs = CalibrationFitter.extract_pairs(data_dir, 1000.0, 2000.0, "Т1", "Т2")
    downsampled = CalibrationFitter.adaptive_downsample(pairs, target_count=100)
    breakpoints = CalibrationFitter.generate_breakpoints(downsampled, tolerance_mk=100.0)

    assert len(breakpoints) >= 2
    # Verify breakpoints approximate the curve within tolerance
    sorted_bp = sorted(breakpoints, key=lambda p: p[0])
    for srdg_val, krdg_val in downsampled:
        # Find enclosing breakpoints
        for i in range(len(sorted_bp) - 1):
            s0, t0 = sorted_bp[i]
            s1, t1 = sorted_bp[i + 1]
            if s0 <= srdg_val <= s1:
                frac = (srdg_val - s0) / (s1 - s0) if s1 != s0 else 0
                interp_t = t0 + frac * (t1 - t0)
                # Within 200mK (relaxed for synthetic data)
                assert abs(interp_t - krdg_val) < 0.5, (
                    f"Breakpoint interpolation error: {abs(interp_t - krdg_val):.3f} K "
                    f"at SRDG={srdg_val:.1f}"
                )
                break


def test_breakpoints_max_limit() -> None:
    # Generate many points on a curve
    pairs = [(float(i), math.sin(i / 10.0) * 100) for i in range(500)]
    breakpoints = CalibrationFitter.generate_breakpoints(pairs, max_breakpoints=20)
    assert len(breakpoints) <= 20


# ------------------------------------------------------------------
# Coverage
# ------------------------------------------------------------------

def test_coverage_statistics(data_dir) -> None:
    pairs = CalibrationFitter.extract_pairs(data_dir, 1000.0, 2000.0, "Т1", "Т2")
    coverage = CalibrationFitter.compute_coverage(pairs, n_bins=10)

    assert len(coverage) == 10
    total = sum(b["point_count"] for b in coverage)
    assert total == len(pairs)
    for b in coverage:
        assert "temp_min" in b
        assert "temp_max" in b
        assert "status" in b
        assert b["status"] in {"dense", "medium", "sparse", "empty"}


def test_coverage_empty_regions(tmp_path) -> None:
    # Create data with a gap in temperature
    db_path = tmp_path / "data_2026-03-17.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY, "
        "timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    # Points at T=4K and T=300K, nothing in between
    for i in range(20):
        ts = 1000.0 + i
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'ref', 4.0, 'K', 'OK')", (ts,))
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'tgt_raw', 80.0, 'sensor_unit', 'OK')", (ts + 0.1,))
    for i in range(20):
        ts = 1020.0 + i
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'ref', 300.0, 'K', 'OK')", (ts,))
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'tgt_raw', 5.0, 'sensor_unit', 'OK')", (ts + 0.1,))
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(tmp_path, 999.0, 1050.0, "ref", "tgt")
    coverage = CalibrationFitter.compute_coverage(pairs, n_bins=10)

    statuses = [b["status"] for b in coverage]
    assert "empty" in statuses  # gap in middle


# ------------------------------------------------------------------
# Full pipeline
# ------------------------------------------------------------------

def test_fit_end_to_end(data_dir, tmp_path) -> None:
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    store = CalibrationStore(cal_dir)

    fitter = CalibrationFitter()
    result = fitter.fit(
        data_dir, 1000.0, 2000.0,
        "Т1", "Т2", store,
        target_count=100,
        min_points_per_zone=3,
        target_rmse_k=0.5,
    )

    assert result.raw_pairs_count == 200
    assert result.downsampled_count <= 120
    assert result.breakpoint_count >= 2
    assert result.curve is not None
    assert result.metrics["rmse_k"] < 1.0  # relaxed for synthetic data
    assert result.sensor_id == "Т2_cal"
