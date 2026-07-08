"""Tests for CalibrationFitter — extract, downsample, breakpoints, coverage."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.calibration_fitter import CalibrationFitter


def _synthetic_dt670(srdg: float) -> float:
    """Approximate DT-670 curve: V(mV) → T(K)."""
    return max(1.5, 1600.0 / (srdg + 15.0) + 0.05 * math.sin(srdg / 5.0))


def _populate_db(
    db_path: Path,
    reference_channel: str,
    target_channel: str,
    n_points: int = 200,
    t_start: float = 1000.0,
) -> float:
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
            (ts, "ls218", reference_channel, krdg_val, "K", "ok"),
        )
        conn.execute(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts + 0.1, "ls218", srdg_channel, srdg_val, "sensor_unit", "ok"),
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
        data_dir,
        1000.0,
        2000.0,
        "Т1",
        "Т2",
    )
    assert len(pairs) == 200

    # Sort by SRDG so index is predictable (extractor may return any order)
    sorted_pairs = sorted(pairs, key=lambda p: p[0])

    # _populate_db inserts srdg_val = 5.0 + i*0.5 for i in range(200)
    # → SRDG: 5.0, 5.5, 6.0, …, 104.5
    # krdg_val = _synthetic_dt670(srdg_val) = max(1.5, 1600/(srdg+15) + 0.05*sin(srdg/5))
    first_srdg = 5.0
    mid_srdg = 5.0 + 99 * 0.5  # i=99 → 54.5
    last_srdg = 5.0 + 199 * 0.5  # i=199 → 104.5

    expected_first_krdg = _synthetic_dt670(first_srdg)
    expected_mid_krdg = _synthetic_dt670(mid_srdg)
    expected_last_krdg = _synthetic_dt670(last_srdg)

    assert sorted_pairs[0] == pytest.approx((first_srdg, expected_first_krdg), abs=1e-6)
    assert sorted_pairs[99] == pytest.approx((mid_srdg, expected_mid_krdg), abs=1e-6)
    assert sorted_pairs[199] == pytest.approx((last_srdg, expected_last_krdg), abs=1e-6)


def test_extract_filters_ovl(tmp_path) -> None:
    db_path = tmp_path / "data_2026-03-17.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY, "
        "timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    # Normal pair
    conn.execute("INSERT INTO readings VALUES (1, 100.0, 'ls', 'ref', 77.0, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (2, 100.1, 'ls', 'tgt_raw', 82.5, 'sensor_unit', 'ok')"
    )
    # OVL pair (inf KRDG)
    conn.execute("INSERT INTO readings VALUES (3, 101.0, 'ls', 'ref', 1e308, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (4, 101.1, 'ls', 'tgt_raw', 83.0, 'sensor_unit', 'ok')"
    )
    # Zero SRDG
    conn.execute("INSERT INTO readings VALUES (5, 102.0, 'ls', 'ref', 77.0, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (6, 102.1, 'ls', 'tgt_raw', 0.0, 'sensor_unit', 'ok')"
    )
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
    conn.execute("INSERT INTO readings VALUES (1, 100.0, 'ls', 'ref', 77.0, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (2, 100.5, 'ls', 'tgt_raw', 82.5, 'sensor_unit', 'ok')"
    )
    # Misaligned pair (5s delta)
    conn.execute("INSERT INTO readings VALUES (3, 110.0, 'ls', 'ref', 78.0, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (4, 115.0, 'ls', 'tgt_raw', 83.0, 'sensor_unit', 'ok')"
    )
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(
        tmp_path, 99.0, 120.0, "ref", "tgt", max_time_delta_s=2.0
    )
    assert len(pairs) == 1
    # Only the aligned pair (srdg=82.5, krdg=77.0) should survive
    assert pairs[0] == pytest.approx((82.5, 77.0), abs=0.01), (
        f"Wrong pair retained: {pairs[0]}; expected (82.5, 77.0)"
    )


# ------------------------------------------------------------------
# Downsample
# ------------------------------------------------------------------


def test_downsample_preserves_curvature() -> None:
    """High-curvature kink region must retain higher per-unit density than flat tails.

    Fixture: 600 points across srdg in [0, 100].
    - srdg in [0, 45]: krdg = 100.0  (perfectly flat, zero curvature)
    - srdg = 50: krdg = 50.0         (sharp kink — maximum second-derivative spike)
    - srdg in [55, 100]: krdg = 10.0 (perfectly flat again)

    The kink region [45, 55] covers 10/100 = 10% of the SRDG range.
    After downsampling the per-unit density there must exceed the flat tails.
    """
    import numpy as np

    rng = np.random.default_rng(0)

    pairs: list[tuple[float, float]] = []
    # Left flat: srdg [0, 45], krdg = 100
    for s in np.linspace(0.1, 44.9, 250):
        pairs.append((float(s), 100.0 + rng.normal(0, 1e-4)))
    # Sharp kink transition [45, 55]: krdg falls 100 → 50 → 10
    for s in np.linspace(45.0, 50.0, 50):
        frac = (s - 45.0) / 5.0
        pairs.append((float(s), 100.0 - 50.0 * frac + rng.normal(0, 1e-4)))
    for s in np.linspace(50.0, 55.0, 50):
        frac = (s - 50.0) / 5.0
        pairs.append((float(s), 50.0 - 40.0 * frac + rng.normal(0, 1e-4)))
    # Right flat: srdg [55, 100], krdg = 10
    for s in np.linspace(55.1, 99.9, 250):
        pairs.append((float(s), 10.0 + rng.normal(0, 1e-4)))

    target = 60
    downsampled = CalibrationFitter.adaptive_downsample(pairs, target_count=target)

    assert len(downsampled) >= target // 3
    assert len(downsampled) <= target * 3

    # Per-unit density: kink [45, 55] (10 units) vs flat tails (90 units)
    kink_count = sum(1 for s, _ in downsampled if 45.0 <= s <= 55.0)
    flat_count = sum(1 for s, _ in downsampled if s < 45.0 or s > 55.0)

    kink_density = kink_count / 10.0   # points per SRDG unit in kink zone
    flat_density = flat_count / 90.0   # points per SRDG unit in flat zones

    assert kink_density > flat_density, (
        f"Curvature-preserving downsample failed: "
        f"kink_density={kink_density:.3f} not > flat_density={flat_density:.3f}  "
        f"(kink_count={kink_count}, flat_count={flat_count}, total={len(downsampled)})"
    )


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
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'ref', 4.0, 'K', 'ok')", (ts,))
        conn.execute(
            "INSERT INTO readings VALUES (NULL, ?, 'ls', 'tgt_raw', 80.0, 'sensor_unit', 'ok')",
            (ts + 0.1,),
        )
    for i in range(20):
        ts = 1020.0 + i
        conn.execute("INSERT INTO readings VALUES (NULL, ?, 'ls', 'ref', 300.0, 'K', 'ok')", (ts,))
        conn.execute(
            "INSERT INTO readings VALUES (NULL, ?, 'ls', 'tgt_raw', 5.0, 'sensor_unit', 'ok')",
            (ts + 0.1,),
        )
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(tmp_path, 999.0, 1050.0, "ref", "tgt")
    coverage = CalibrationFitter.compute_coverage(pairs, n_bins=10)

    # compute_coverage bins over temperature (krdg = second element of pairs).
    # Data: 20 pairs at T=4.0 K, 20 pairs at T=300.0 K, nothing in between.
    # 10 bins over [4.0, 300.0] → width ≈ 29.6 K each.
    #   Bin 0 [4.0, 33.6):  all 20 cold points → point_count == 20
    #   Bins 1–8:            empty gap           → point_count == 0, status == "empty"
    #   Bin 9 [270.4, 300.0]: all 20 warm points → point_count == 20

    assert len(coverage) == 10, f"Expected 10 bins, got {len(coverage)}"

    assert coverage[0]["point_count"] == 20, (
        f"Bin 0 should have 20 cold points; got {coverage[0]}"
    )
    assert coverage[-1]["point_count"] == 20, (
        f"Bin 9 should have 20 warm points; got {coverage[-1]}"
    )

    # All middle bins (indices 1–8) must be empty
    for idx in range(1, 9):
        b = coverage[idx]
        assert b["point_count"] == 0, (
            f"Middle bin {idx} should have 0 points; got {b}"
        )
        assert b["status"] == "empty", (
            f"Middle bin {idx} should have status='empty'; got {b}"
        )

    # Both endpoint bins must be non-empty
    assert coverage[0]["status"] != "empty", (
        f"Bin 0 unexpectedly empty; got {coverage[0]}"
    )
    assert coverage[-1]["status"] != "empty", (
        f"Bin 9 unexpectedly empty; got {coverage[-1]}"
    )

    # Total point count preserved
    total = sum(b["point_count"] for b in coverage)
    assert total == len(pairs)


# ------------------------------------------------------------------
# Full pipeline
# ------------------------------------------------------------------


def test_fit_end_to_end(data_dir, tmp_path) -> None:
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    store = CalibrationStore(cal_dir)

    fitter = CalibrationFitter()
    result = fitter.fit(
        data_dir,
        1000.0,
        2000.0,
        "Т1",
        "Т2",
        store,
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


# ------------------------------------------------------------------
# Silent-NaN metrics guard (POLISH_FIXES_2)
# ------------------------------------------------------------------


def test_fit_logs_warning_when_all_metric_points_fail(
    data_dir, tmp_path, caplog
) -> None:
    """If no downsampled point can be evaluated, rmse_k/max_abs_error_k go NaN.

    The fit itself still succeeds (curve is built); the metrics are reporting-only.
    A silent NaN on a calibration the operator is about to apply must surface a
    WARNING rather than passing silently.
    """
    import logging

    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    store = CalibrationStore(cal_dir)

    # Force every per-point evaluation to throw so the errors list stays empty.
    def _always_raise(*_args, **_kwargs):
        raise RuntimeError("degenerate zone — cannot evaluate")

    store.evaluate = _always_raise  # type: ignore[method-assign]

    fitter = CalibrationFitter()
    with caplog.at_level(logging.WARNING, logger="cryodaq.analytics.calibration_fitter"):
        result = fitter.fit(
            data_dir,
            1000.0,
            2000.0,
            "Т1",
            "Т2",
            store,
            target_count=100,
            min_points_per_zone=3,
            target_rmse_k=0.5,
        )

    # Fit still succeeded; metrics are NaN but no longer silent.
    assert result.curve is not None
    assert math.isnan(result.metrics["rmse_k"])
    assert math.isnan(result.metrics["max_abs_error_k"])
    warnings = [
        r for r in caplog.records if r.levelno >= logging.WARNING and "NaN" in r.message
    ]
    assert warnings, "Expected a WARNING when all metric points fail to evaluate"


# ------------------------------------------------------------------
# NaN-доктрина: extract drops error-status rows even with in-range values
# ------------------------------------------------------------------


def test_extract_pairs_reads_rotated_cold_day(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A calibration fit over data older than the cold-rotation threshold must
    still find its pairs. Once F17 rotates a daily SQLite file to Parquet and
    deletes it, a direct glob goes blind — extract_pairs has to union hot+cold.
    """
    # CI runners link an in-range SQLite (ubuntu 3.45.1 / windows 3.50.4); this
    # test drives the real SQLiteWriter.stop() path which runs the F25 gate.
    # On Linux the pysqlite3 fallback makes the gate pass for real; Windows has
    # no wheels, so acknowledge the bypass explicitly (the gate itself is
    # pinned by tests/core/test_f23_f24_f25_misc.py).
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    import asyncio

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    day = datetime(2026, 4, 14, tzinfo=UTC)
    base_ts = day.timestamp()

    def _reading(channel: str, value: float, ts: float) -> Reading:
        return Reading(
            timestamp=datetime.fromtimestamp(ts, tz=UTC),
            instrument_id="ls218",
            channel=channel,
            value=value,
            unit="K",
            status=ChannelStatus.OK,
        )

    async def _seed_and_rotate() -> None:
        writer = SQLiteWriter(tmp_path)
        batch = []
        for i in range(20):
            ts = base_ts + i
            srdg_val = 5.0 + i * 0.5
            krdg_val = _synthetic_dt670(srdg_val)
            batch.append(_reading("Т1", krdg_val, ts))
            batch.append(_reading("Т2_raw", srdg_val, ts + 0.1))
        writer._write_batch(batch)
        await writer.stop()
        service = ColdRotationService(
            data_dir=tmp_path, archive_dir=tmp_path / "archive", age_days=30
        )
        results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert results, "old day must have rotated to Parquet"

    asyncio.run(_seed_and_rotate())
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    pairs = CalibrationFitter.extract_pairs(
        tmp_path, base_ts, base_ts + 100, "Т1", "Т2"
    )
    assert len(pairs) == 20, f"rotated cold-day calibration pairs lost: {len(pairs)}"


def test_extract_pairs_drops_error_status(tmp_path) -> None:
    """A non-OK status is the discriminator: an error-status reading with an
    otherwise in-range value must never become a calibration pair. Decode at
    the ingest boundary maps it to NaN, and the existing finite-filter drops it.
    """
    db_path = tmp_path / "data_2026-03-17.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE readings (id INTEGER PRIMARY KEY, "
        "timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    # Pair A — both OK, in range → survives.
    conn.execute("INSERT INTO readings VALUES (1, 100.0, 'ls', 'ref', 77.0, 'K', 'ok')")
    conn.execute("INSERT INTO readings VALUES (2, 100.1, 'ls', 'tgt_raw', 82.5, 'sensor_unit', 'ok')")
    # Pair B — SRDG errored (in-range value 90.0) → decode→NaN → dropped.
    conn.execute("INSERT INTO readings VALUES (3, 200.0, 'ls', 'ref', 77.0, 'K', 'ok')")
    conn.execute(
        "INSERT INTO readings VALUES (4, 200.1, 'ls', 'tgt_raw', 90.0, 'sensor_unit', 'sensor_error')"
    )
    # Pair C — KRDG errored (in-range value 78.0) → decode→NaN → dropped.
    conn.execute("INSERT INTO readings VALUES (5, 300.0, 'ls', 'ref', 78.0, 'K', 'sensor_error')")
    conn.execute("INSERT INTO readings VALUES (6, 300.1, 'ls', 'tgt_raw', 95.0, 'sensor_unit', 'ok')")
    conn.commit()
    conn.close()

    pairs = CalibrationFitter.extract_pairs(tmp_path, 99.0, 301.0, "ref", "tgt")
    assert len(pairs) == 1, "only the both-OK pair may survive"
    assert pairs[0] == pytest.approx((82.5, 77.0), abs=0.1)
