"""Tests for the CooldownEstimator analytics plugin."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from plugins.cooldown_estimator import CooldownEstimator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_CH = "lakeshore/ch1"
TARGET_T = 10.0   # K — target temperature used in most tests


def _configured_plugin(
    target_T: float = TARGET_T,
    fit_window_s: float = 300.0,
) -> CooldownEstimator:
    plugin = CooldownEstimator()
    plugin.configure(
        {
            "target_channel": TARGET_CH,
            "target_T": target_T,
            "fit_window_s": fit_window_s,
        }
    )
    return plugin


def _make_reading(channel: str, value: float, timestamp: datetime) -> Reading:
    return Reading(
        timestamp=timestamp,
        instrument_id="test",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
    )


def _exponential_readings(
    *,
    n: int = 15,
    T_base: float = 4.0,
    A: float = 100.0,
    tau: float = 200.0,
    t_end_offset: float = 0.0,
    fit_window_s: float = 300.0,
) -> list[Reading]:
    """
    Generate *n* readings following T(t) = T_base + A * exp(-t / tau).

    Timestamps are spread uniformly over [now - fit_window_s + 1, now + t_end_offset]
    so they all fall inside the plugin's sliding window.
    """
    t_now = datetime.now(UTC).timestamp()
    t_start = t_now - fit_window_s + 1.0  # just inside the window boundary
    t_end = t_now + t_end_offset

    readings = []
    for i in range(n):
        frac = i / (n - 1)
        t_abs = t_start + frac * (t_end - t_start)
        t_rel = t_abs - t_start  # seconds from first point
        T = T_base + A * math.exp(-t_rel / tau)
        dt = datetime.fromtimestamp(t_abs, tz=UTC)
        readings.append(_make_reading(TARGET_CH, T, dt))

    return readings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_exponential_decay_fit():
    """Synthetic T(t) = T_base + A*exp(-t/tau) data should yield a finite ETA."""
    # Parameters are chosen so that:
    #   - temperatures decay slowly (tau = 600 s, window = 300 s)
    #   - T_min * 0.9 < target_T  (so T_base < target_T, giving target_diff > 0)
    #   - current_T > target_T    (not yet reached)
    #   - ratio = (target_T - T_base) / A is in (0, 1)
    #
    # With T_base_true=3, A=100, tau=600, window=300:
    #   T(0) ≈ 103 K, T(290) ≈ 65 K
    #   T_min ≈ 65, T_min*0.9 ≈ 58.2 < target_T=60 ✓
    #   current_T ≈ 65 > 60 ✓
    T_base_true = 3.0
    A_true = 100.0
    tau_true = 600.0
    target_T = 60.0
    fit_window_s = 300.0

    plugin = _configured_plugin(target_T=target_T, fit_window_s=fit_window_s)

    readings = _exponential_readings(
        n=20,
        T_base=T_base_true,
        A=A_true,
        tau=tau_true,
        fit_window_s=fit_window_s,
    )

    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    metric = metrics[0]
    assert metric.metric == "cooldown_eta_s"
    assert metric.unit == "s"
    # ETA must be a positive finite number
    assert math.isfinite(metric.value)
    assert metric.value > 0.0


async def test_insufficient_data_returns_empty():
    """Fewer than 10 data points in the window → no metric produced."""
    plugin = _configured_plugin()

    t_now = datetime.now(UTC).timestamp()
    readings = [
        _make_reading(
            TARGET_CH,
            200.0 - i * 5.0,
            datetime.fromtimestamp(t_now - 30 + i * 3, tz=UTC),
        )
        for i in range(5)  # only 5 points
    ]

    metrics = await plugin.process(readings)

    assert metrics == []


async def test_warming_returns_empty():
    """Temperature increasing (last >= first) → no metric produced."""
    plugin = _configured_plugin()

    t_now = datetime.now(UTC).timestamp()
    # Monotonically increasing temperature
    readings = [
        _make_reading(
            TARGET_CH,
            10.0 + i * 2.0,
            datetime.fromtimestamp(t_now - 150 + i * 10, tz=UTC),
        )
        for i in range(15)
    ]

    metrics = await plugin.process(readings)

    assert metrics == []


async def test_target_already_reached():
    """Current temperature at or below target → no metric produced."""
    target_T = 50.0
    plugin = _configured_plugin(target_T=target_T, fit_window_s=300.0)

    t_now = datetime.now(UTC).timestamp()
    # Temperatures all below or at the target, decreasing
    readings = [
        _make_reading(
            TARGET_CH,
            target_T - i * 2.0,   # starts at target_T, goes below
            datetime.fromtimestamp(t_now - 280 + i * 10, tz=UTC),
        )
        for i in range(15)
    ]

    metrics = await plugin.process(readings)

    assert metrics == []


async def test_metric_has_metadata():
    """Returned metric must contain tau, A, T_base, and target_T in metadata."""
    # Same well-behaved parameters as test_exponential_decay_fit
    T_base_true = 3.0
    A_true = 100.0
    tau_true = 600.0
    target_T = 60.0
    fit_window_s = 300.0

    plugin = _configured_plugin(target_T=target_T, fit_window_s=fit_window_s)

    readings = _exponential_readings(
        n=20,
        T_base=T_base_true,
        A=A_true,
        tau=tau_true,
        fit_window_s=fit_window_s,
    )

    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    meta = metrics[0].metadata

    assert "tau" in meta
    assert "A" in meta
    assert "T_base" in meta
    assert "target_T" in meta

    # Sanity checks on the fitted values
    assert meta["tau"] > 0.0
    assert meta["A"] > 0.0
    assert meta["target_T"] == pytest.approx(target_T)
