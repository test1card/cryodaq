"""Tests for F13 LeakRateEstimator — vacuum leak rate measurement."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.analytics.leak_rate import (
    LeakRateEstimator,
    LeakRateMeasurement,
    _linear_regression,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 29, 10, 0, 0, tzinfo=UTC)


def _estimator(volume: float = 50.0, window_s: float = 300.0) -> LeakRateEstimator:
    return LeakRateEstimator(chamber_volume_l=volume, sample_window_s=window_s)


def _feed_samples(
    est: LeakRateEstimator,
    n: int,
    p_start: float,
    dpdt: float,
    dt_s: float = 10.0,
) -> None:
    """Feed n samples with known linear pressure rise."""
    for i in range(n):
        t = _T0 + timedelta(seconds=i * dt_s)
        p = p_start + dpdt * i * dt_s
        est.add_sample(t, p)


# ---------------------------------------------------------------------------
# _linear_regression unit tests
# ---------------------------------------------------------------------------


def test_linear_regression_perfect_fit() -> None:
    """Known linear data returns exact slope, R²=1."""
    xs = [0.0, 1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 3.0, 5.0, 7.0, 9.0]  # slope=2, intercept=1
    slope, intercept, r2 = _linear_regression(xs, ys)
    assert abs(slope - 2.0) < 1e-9
    assert abs(intercept - 1.0) < 1e-9
    assert abs(r2 - 1.0) < 1e-9


def test_linear_regression_constant_returns_zero_slope() -> None:
    """Constant pressure → zero slope, R²=1."""
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [5.0, 5.0, 5.0, 5.0]
    slope, intercept, r2 = _linear_regression(xs, ys)
    assert abs(slope) < 1e-9
    assert abs(r2 - 1.0) < 1e-6


def test_linear_regression_noisy_data_low_r2() -> None:
    """Very noisy data yields R² < 0.5."""
    xs = [float(i) for i in range(10)]
    # Alternating high/low with tiny trend — noisy
    ys = [1e-3 if i % 2 == 0 else 1.0 for i in range(10)]
    _, _, r2 = _linear_regression(xs, ys)
    assert r2 < 0.5


# ---------------------------------------------------------------------------
# LeakRateEstimator: measurement lifecycle
# ---------------------------------------------------------------------------


def test_measurement_lifecycle() -> None:
    """start → add_sample × N → finalize returns valid measurement."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=20, p_start=1e-5, dpdt=1e-7)

    result = est.finalize()
    assert isinstance(result, LeakRateMeasurement)
    assert result.samples_n == 21  # initial + 20
    assert result.duration_s > 0
    assert result.chamber_volume_l == 50.0
    assert result.fit_quality_r2 > 0.99


def test_leak_rate_linear_fit_known_data() -> None:
    """Known dP/dt produces correct leak_rate = dpdt × volume."""
    volume = 50.0
    dpdt_known = 2e-7  # mbar/s
    est = _estimator(volume=volume)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=30, p_start=1e-5, dpdt=dpdt_known, dt_s=10.0)

    result = est.finalize()
    expected_leak = dpdt_known * volume
    assert abs(result.dpdt_mbar_per_s - dpdt_known) / dpdt_known < 0.01
    assert abs(result.leak_rate_mbar_l_per_s - expected_leak) / expected_leak < 0.01
    assert result.fit_quality_r2 > 0.999


def test_leak_rate_zero_when_pressure_constant() -> None:
    """Zero pressure rise → near-zero dP/dt and leak_rate."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-6)
    _feed_samples(est, n=20, p_start=1e-6, dpdt=0.0)

    result = est.finalize()
    assert abs(result.dpdt_mbar_per_s) < 1e-15
    assert abs(result.leak_rate_mbar_l_per_s) < 1e-13


def test_leak_rate_low_r2_on_noisy_data() -> None:
    """Noisy pressure data yields low R²."""
    import random

    rng = random.Random(42)
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)

    for i in range(20):
        t = _T0 + timedelta(seconds=i * 15.0)
        p = 1e-5 + rng.uniform(-1e-4, 1e-4)  # large noise relative to signal
        est.add_sample(t, p)

    result = est.finalize()
    assert result.fit_quality_r2 < 0.5


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_chamber_volume_unset_raises() -> None:
    """volume_l <= 0 raises ValueError on finalize."""
    est = _estimator(volume=0.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
    with pytest.raises(ValueError, match="Chamber volume not configured"):
        est.finalize()


def test_insufficient_samples_raises() -> None:
    """Only 1 sample → ValueError."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    # No add_sample calls — only the initial p0_mbar sample
    with pytest.raises(ValueError, match="Insufficient samples"):
        est.finalize()


def test_disabled_state() -> None:
    """is_active is False after finalize or cancel."""
    est = _estimator()
    assert not est.is_active
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    assert est.is_active
    est.cancel()
    assert not est.is_active


def test_start_while_active_resets() -> None:
    """Calling start_measurement twice resets state (no crash)."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
    # Start again — resets
    t1 = _T0 + timedelta(minutes=10)
    est.start_measurement(t0=t1, p0_mbar=2e-5)
    _feed_samples(est, n=5, p_start=2e-5, dpdt=1e-7)
    result = est.finalize()
    assert result.initial_pressure_mbar == pytest.approx(2e-5)


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def test_history_file_written(tmp_path: Path) -> None:
    """Finalized measurement appended to leak_rate_history.json."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=10, p_start=1e-5, dpdt=1e-7)
    est.finalize()

    history_path = tmp_path / "leak_rate_history.json"
    assert history_path.exists()
    data = json.loads(history_path.read_text())
    assert len(data["measurements"]) == 1
    assert "leak_rate_mbar_l_per_s" in data["measurements"][0]


def test_history_appends_multiple(tmp_path: Path) -> None:
    """Multiple finalizations append to the same history file."""
    for _ in range(3):
        est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
        est.start_measurement(t0=_T0, p0_mbar=1e-5)
        _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
        est.finalize()

    history_path = tmp_path / "leak_rate_history.json"
    data = json.loads(history_path.read_text())
    assert len(data["measurements"]) == 3
