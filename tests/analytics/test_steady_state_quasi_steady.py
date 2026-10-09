"""v0.55.3 — quasi-steady regime detection in SteadyStatePredictor.

Real cryo runs accumulate gas-desorption drift at the end of cooldown
that defeats the pure exponential model in the original predictor.
v0.55.3 introduces a stddev + slope gate that bypasses curve_fit when
the system is sitting near steady. These tests cover the four corners:
pure noise at floor, slow drift within threshold, fast drift, and
high noise — only the first two should be classified quasi-steady.
"""

from __future__ import annotations

import numpy as np

from cryodaq.analytics.steady_state import SteadyStatePredictor


def _feed_synthetic(
    predictor: SteadyStatePredictor,
    *,
    channel: str,
    t0: float,
    duration_s: float,
    f_value,  # callable: t_offset_seconds -> kelvin
) -> float:
    """Push 1Hz samples for `duration_s` seconds. Returns last timestamp."""
    last_ts = t0
    n = int(duration_s) + 1
    for i in range(n):
        ts = t0 + float(i)
        predictor.add_point(channel, ts, float(f_value(float(i))))
        last_ts = ts
    return last_ts


def test_pure_noise_at_floor_quasi_steady() -> None:
    """C1 — T = 2.95 + N(0, 0.04) over 30 min → quasi-steady."""
    rng = np.random.default_rng(seed=42)
    predictor = SteadyStatePredictor()  # defaults: noise_floor 0.05, drift 1.0
    last = _feed_synthetic(
        predictor,
        channel="cold",
        t0=0.0,
        duration_s=1800.0,
        f_value=lambda t: 2.95 + rng.normal(0.0, 0.04),
    )
    updated = predictor.update(now=last + 1.0)
    pred = updated["cold"]
    assert pred.valid is True
    assert pred.is_quasi_steady is True
    assert abs(pred.drift_rate_k_per_h) < 0.5
    # Predicted readout should sit near the synthetic mean.
    assert abs(pred.t_predicted - 2.95) < 0.1


def test_slow_drift_within_threshold_quasi_steady() -> None:
    """C2 — T = 2.95 - 0.5*(t/3600) + N(0, 0.04) over 30 min → quasi-steady."""
    rng = np.random.default_rng(seed=42)
    predictor = SteadyStatePredictor()
    last = _feed_synthetic(
        predictor,
        channel="cold",
        t0=0.0,
        duration_s=1800.0,
        f_value=lambda t: 2.95 - 0.5 * (t / 3600.0) + rng.normal(0.0, 0.04),
    )
    updated = predictor.update(now=last + 1.0)
    pred = updated["cold"]
    assert pred.valid is True
    assert pred.is_quasi_steady is True
    assert -0.7 < pred.drift_rate_k_per_h < -0.3


def test_fast_drift_NOT_quasi_steady() -> None:
    """C3 — T = 50 - 5*(t/3600) + N(0, 0.04) over 30 min → curve_fit path."""
    rng = np.random.default_rng(seed=42)
    predictor = SteadyStatePredictor()
    last = _feed_synthetic(
        predictor,
        channel="cold",
        t0=0.0,
        duration_s=1800.0,
        f_value=lambda t: 50.0 - 5.0 * (t / 3600.0) + rng.normal(0.0, 0.04),
    )
    updated = predictor.update(now=last + 1.0)
    pred = updated["cold"]
    # Drift = -5 K/h is way above threshold, so quasi-steady gate must
    # NOT fire. The drift_rate field is still informative.
    assert pred.is_quasi_steady is False
    assert pred.drift_rate_k_per_h < -3.0


def test_high_noise_NOT_quasi_steady() -> None:
    """C4 — T = 2.95 + N(0, 0.5) over 30 min → curve_fit path."""
    rng = np.random.default_rng(seed=42)
    predictor = SteadyStatePredictor()
    last = _feed_synthetic(
        predictor,
        channel="cold",
        t0=0.0,
        duration_s=1800.0,
        f_value=lambda t: 2.95 + rng.normal(0.0, 0.5),
    )
    updated = predictor.update(now=last + 1.0)
    pred = updated["cold"]
    # Stddev ≈ 0.5 ≫ 0.05 noise floor → quasi-steady gate must NOT fire.
    assert pred.is_quasi_steady is False
    assert pred.stddev_k > 0.4


def test_clear_exponential_decay_uses_curve_fit() -> None:
    """C5 — T(t) = 50 + 100*exp(-t/600) + N(0, 0.05) over 15 min →
    curve_fit path produces valid=True with sensible T_inf and amplitude.
    """
    rng = np.random.default_rng(seed=42)
    predictor = SteadyStatePredictor()
    last = _feed_synthetic(
        predictor,
        channel="cold",
        t0=0.0,
        duration_s=900.0,
        f_value=lambda t: 50.0 + 100.0 * np.exp(-t / 600.0) + rng.normal(0.0, 0.05),
    )
    updated = predictor.update(now=last + 1.0)
    pred = updated["cold"]
    assert pred.is_quasi_steady is False
    assert pred.valid is True
    assert 45.0 <= pred.t_predicted <= 55.0
    assert 80.0 <= pred.amplitude <= 120.0
    # stddev / drift were computed in update() and propagated via dataclasses.replace.
    assert pred.stddev_k > 0.0
    assert pred.drift_rate_k_per_h != 0.0
