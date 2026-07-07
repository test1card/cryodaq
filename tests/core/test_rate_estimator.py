"""Tests for RateEstimator — OLS-based dX/dt estimation."""

from __future__ import annotations

import random

from cryodaq.core.rate_estimator import RateEstimator


def _feed_linear(
    estimator: RateEstimator,
    channel: str,
    *,
    rate_per_min: float,
    start_value: float = 4.2,
    n_points: int = 120,
    interval_s: float = 1.0,
    t0: float | None = None,
) -> float:
    """Feed linearly changing values. Returns timestamp of last point."""
    if t0 is None:
        t0 = 1_000_000.0
    rate_per_sec = rate_per_min / 60.0
    for i in range(n_points):
        ts = t0 + i * interval_s
        value = start_value + rate_per_sec * i * interval_s
        estimator.push(channel, ts, value)
    return t0 + (n_points - 1) * interval_s


def test_rate_linear() -> None:
    """Линейные данные со slope 1 K/мин → rate ≈ 1.0 ± 0.1."""
    est = RateEstimator(window_s=120.0, min_points=60)
    _feed_linear(est, "T1", rate_per_min=1.0, n_points=120)
    rate = est.get_rate("T1")
    assert rate is not None
    assert abs(rate - 1.0) < 0.1, f"Expected ≈1.0 K/min, got {rate}"


def test_rate_negative() -> None:
    """Охлаждение −2 K/мин."""
    est = RateEstimator(window_s=120.0, min_points=60)
    _feed_linear(est, "T1", rate_per_min=-2.0, start_value=200.0, n_points=120)
    rate = est.get_rate("T1")
    assert rate is not None
    assert abs(rate - (-2.0)) < 0.1


def test_rate_constant() -> None:
    """Постоянная 4.2 K → rate ≈ 0 ± 0.01."""
    est = RateEstimator(window_s=120.0, min_points=60)
    for i in range(120):
        est.push("T12", 1_000_000.0 + i, 4.2)
    rate = est.get_rate("T12")
    assert rate is not None
    assert abs(rate) < 0.01, f"Expected ≈0, got {rate}"


def test_rate_insufficient_points() -> None:
    """Менее min_points точек → None."""
    est = RateEstimator(window_s=120.0, min_points=60)
    for i in range(30):
        est.push("T1", 1_000_000.0 + i, 4.2 + i * 0.01)
    assert est.get_rate("T1") is None


def test_rate_unknown_channel() -> None:
    """Нет данных → None."""
    est = RateEstimator()
    assert est.get_rate("nonexistent") is None


def test_rate_window_trim() -> None:
    """После заполнения окна старые точки отбрасываются и не влияют на rate."""
    est = RateEstimator(window_s=60.0, min_points=30)
    t0 = 1_000_000.0

    # Сначала подаём точки с быстрым нагревом (+10 K/мин) — они станут "старыми"
    for i in range(60):
        est.push("T1", t0 + i, 4.2 + (10.0 / 60.0) * i)

    # Затем подаём медленный нагрев (+1 K/мин) в новом временном окне
    t1 = t0 + 300.0  # сдвиг на 5 мин — старые точки выйдут за окно
    for i in range(60):
        ts = t1 + i
        value = 100.0 + (1.0 / 60.0) * i
        est.push("T1", ts, value)

    rate = est.get_rate("T1")
    assert rate is not None
    # Rate должен отражать только свежие данные (~1 K/мин), не старые (~10 K/мин)
    assert abs(rate - 1.0) < 0.5, f"Expected ≈1.0 K/min after trim, got {rate}"


def test_rate_noisy() -> None:
    """Шум ±0.01 K поверх тренда 1 K/мин → rate близок к истинному."""
    est = RateEstimator(window_s=120.0, min_points=60)
    rng = random.Random(42)
    t0 = 1_000_000.0
    rate_per_sec = 1.0 / 60.0
    for i in range(120):
        ts = t0 + i
        value = 4.2 + rate_per_sec * i + rng.uniform(-0.01, 0.01)
        est.push("T1", ts, value)
    rate = est.get_rate("T1")
    assert rate is not None
    assert abs(rate - 1.0) < 0.1, f"Noisy rate should be ≈1.0 K/min, got {rate}"


def test_rate_custom_window_shorter() -> None:
    """get_rate_custom_window с меньшим окном должен игнорировать старые точки.

    Old points (t=0..119) have rate +10 K/min.
    Recent points (t=420..479, within 60s window) have rate +2 K/min.
    If get_rate_custom_window ignores the window_s argument and uses all data,
    the measured slope would be dominated by the old high-rate points and
    the assertion would fail.  This makes the window_s gate observable.
    """
    est = RateEstimator(window_s=600.0, min_points=30)
    t0 = 1_000_000.0

    # Old batch: +10 K/min slope (these will be outside the 60s window)
    for i in range(120):
        est.push("T1", t0 + i, 4.2 + (10.0 / 60.0) * i)

    # Gap: jump forward so old points are >60s back from the new batch
    t1 = t0 + 420.0  # 420s later → old batch is 300–420s ago, outside 60s window

    # Recent batch: +2 K/min slope, 60 points within the 60s window
    recent_start_v = 100.0
    for i in range(60):
        est.push("T1", t1 + i, recent_start_v + (2.0 / 60.0) * i)

    rate_short = est.get_rate_custom_window("T1", window_s=60.0)
    assert rate_short is not None, "Expected a rate estimate from the recent 60s window"
    assert abs(rate_short - 2.0) < 0.3, (
        f"get_rate_custom_window must reflect recent 2 K/min slope, got {rate_short:.3f} K/min. "
        f"A value near 10 K/min means the window_s argument was ignored."
    )


def test_rate_custom_window_insufficient() -> None:
    """Недостаточно точек в кастомном окне → None.

    Total points >= min_points (60) so the global buffer is populated, but
    only the recent points fall within the custom 60s window. This isolates
    the custom-window in-window filtering: get_rate_custom_window must return
    None because the 60s window contains < min_points points, not because the
    buffer as a whole is too small.

    Sampling is continuous at 1.5s so the C-5 clock guard never fires (no gap
    > 4x poll): 100 points span 148.5s, a 60s window holds only ~40 of them.
    """
    est = RateEstimator(window_s=600.0, min_points=60)
    t0 = 1_000_000.0

    # 100 continuous points at 1.5s spacing → 148.5s span, all inside the 600s
    # buffer window; the recent 60s custom window contains only ~40 points.
    for i in range(100):
        est.push("T1", t0 + i * 1.5, 4.2 + i * 0.01)

    # Buffer has 100 total points (>= 60), but < 60 are in the 60s window
    assert est.buffer_size("T1") >= 60, "Pre-condition: buffer must have >= 60 total points"
    assert est.get_rate_custom_window("T1", window_s=60.0) is None, (
        "get_rate_custom_window must return None when < min_points points are in the window, "
        "even if the total buffer exceeds min_points"
    )


def test_multiple_channels_independent() -> None:
    """Несколько каналов не влияют друг на друга."""
    est = RateEstimator(window_s=120.0, min_points=60)
    _feed_linear(est, "T1", rate_per_min=1.0)
    _feed_linear(est, "T11", rate_per_min=3.0)

    r1 = est.get_rate("T1")
    r11 = est.get_rate("T11")
    assert r1 is not None and abs(r1 - 1.0) < 0.1
    assert r11 is not None and abs(r11 - 3.0) < 0.1
