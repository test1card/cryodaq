"""Regression tests from deep review pass."""

from __future__ import annotations

import numpy as np
import pytest

from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


# ---------------------------------------------------------------------------
# Bug #1: Float timestamp alignment in correlation computation
# ---------------------------------------------------------------------------


def test_correlation_with_tiny_timestamp_offset() -> None:
    """Correlation must work even when timestamps differ by nanoseconds.

    Regression: before fix, float set intersection failed with any offset,
    causing correlation to always return None.
    """
    engine = SensorDiagnosticsEngine(config={
        "correlation_groups": {"shield": ["T1", "T2"]},
    })
    rng = np.random.default_rng(42)
    # Push with sub-millisecond offset (simulating slight timing jitter)
    for i in range(200):
        base = 50.0 + 0.1 * rng.normal()
        engine.push("T1", i * 0.5, base + rng.normal(0, 0.001))
        engine.push("T2", i * 0.5 + 1e-6, base + rng.normal(0, 0.001))  # 1µs offset
    engine.update()
    diag = engine.get_diagnostics()
    # Should find correlation (not None) despite tiny timestamp differences
    assert diag["T1"].correlation is not None


def test_correlation_with_identical_timestamps() -> None:
    """Correlation still works with exactly matching timestamps (common case)."""
    engine = SensorDiagnosticsEngine(config={
        "correlation_groups": {"shield": ["T1", "T2"]},
    })
    rng = np.random.default_rng(42)
    for i in range(200):
        base = 50.0 + 0.1 * rng.normal()
        engine.push("T1", i * 0.5, base)
        engine.push("T2", i * 0.5, base)  # identical timestamp
    engine.update()
    diag = engine.get_diagnostics()
    assert diag["T1"].correlation is not None
    assert diag["T1"].correlation > 0.99
