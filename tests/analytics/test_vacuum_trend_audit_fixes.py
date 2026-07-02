"""Audit-fix regression tests for VacuumTrendPredictor.

- ME-14 / D-C14: push() only guarded pressure_mbar <= 0, so NaN slipped through
  and log10(nan) poisoned the buffer, killing predictions until it aged out.
- D-C13: "rising" required the fixed 30-point rate window to span
  rising_sustained_s; at high sample rates 30 points span far less than the
  threshold, making "rising" unreachable regardless of how long pressure rose.
"""

from __future__ import annotations

import math

import numpy as np

from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor

# ---------------------------------------------------------------------------
# ME-14 / D-C14
# ---------------------------------------------------------------------------


def test_push_rejects_nan_and_does_not_poison_buffer() -> None:
    """A NaN push must be ignored and must not break subsequent predictions."""
    pred = VacuumTrendPredictor(config={"min_points": 60})

    # A NaN push before any data must not enter the buffer.
    pred.push(0.0, float("nan"))
    assert len(pred._buffer) == 0, "NaN push must be dropped"

    # A NaN interleaved with a valid exponential pumpdown must not poison it.
    rng = np.random.default_rng(1)
    for i in range(200):
        t = i * 5.0
        logP = -6.0 + 5.0 * math.exp(-t / 300.0)
        pred.push(t, 10.0 ** (logP + rng.normal(0, 0.01)))
        if i == 100:
            pred.push(t + 0.1, float("nan"))  # would poison the buffer

    # No NaN allowed to sit in the buffer.
    assert all(math.isfinite(lp) for _, lp in pred._buffer)

    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type != "insufficient_data"
    assert math.isfinite(p.residual_std)
    assert math.isfinite(p.confidence)


# ---------------------------------------------------------------------------
# D-C13
# ---------------------------------------------------------------------------


def test_rising_reachable_at_high_sample_rate_default_threshold() -> None:
    """With the default 60 s sustained threshold and a high sample rate, a
    genuinely rising pressure must be classified as "rising".

    Before the fix the sustained check used the fixed 30-point rate window,
    which at 10 Hz spans ~3 s << 60 s, so "rising" was unreachable.
    """
    pred = VacuumTrendPredictor(
        config={"min_points": 60, "rising_sustained_s": 60.0}
    )
    rng = np.random.default_rng(7)
    # 10 Hz sampling: 400 stable points (40 s) then 800 rising points (80 s).
    for i in range(1200):
        t = i * 0.1
        if i < 400:
            logP = -6.0
        else:
            logP = -6.0 + (i - 400) * 0.002  # ~0.02 decades/s rising
        pred.push(t, 10.0 ** (logP + rng.normal(0, 0.0005)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.trend == "rising", f"expected rising, got {p.trend}"
