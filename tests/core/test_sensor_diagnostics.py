"""Tests for SensorDiagnosticsEngine — 20 unit tests per spec."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict

import numpy as np
import pytest

from cryodaq.core.sensor_diagnostics import (
    SensorDiagnosticsEngine,
    _get_noise_threshold,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _push_constant(
    engine: SensorDiagnosticsEngine,
    ch: str,
    T: float,
    n: int = 200,
    dt: float = 0.5,
    t0: float = 0.0,
) -> None:
    """Push n constant-temperature readings."""
    for i in range(n):
        engine.push(ch, t0 + i * dt, T)


def _push_noisy(
    engine: SensorDiagnosticsEngine,
    ch: str,
    T: float,
    sigma: float,
    n: int = 200,
    dt: float = 0.5,
    t0: float = 0.0,
    rng: np.random.Generator | None = None,
) -> None:
    """Push n readings with Gaussian noise around T."""
    if rng is None:
        rng = np.random.default_rng(42)
    for i in range(n):
        engine.push(ch, t0 + i * dt, T + rng.normal(0, sigma))


def _push_linear(
    engine: SensorDiagnosticsEngine,
    ch: str,
    T0: float,
    rate_K_per_min: float,
    n: int = 200,
    dt: float = 0.5,
    t0: float = 0.0,
) -> None:
    """Push n readings with a linear drift: T = T0 + rate * t."""
    rate_per_sec = rate_K_per_min / 60.0
    for i in range(n):
        ts = t0 + i * dt
        engine.push(ch, ts, T0 + rate_per_sec * ts)


# ---------------------------------------------------------------------------
# 1. test_noise_std_constant_signal — const T → noise ≈ 0
# ---------------------------------------------------------------------------


def test_noise_std_constant_signal() -> None:
    engine = SensorDiagnosticsEngine()
    _push_constant(engine, "T1", 50.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.noise_std < 1e-9


# ---------------------------------------------------------------------------
# 2. test_noise_std_known_gaussian — T + N(0,σ) → noise ≈ σ (±20%)
# ---------------------------------------------------------------------------


def test_noise_std_known_gaussian() -> None:
    engine = SensorDiagnosticsEngine()
    sigma = 0.05
    _push_noisy(engine, "T1", 100.0, sigma, n=500)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert abs(diag.noise_std - sigma) / sigma < 0.2


# ---------------------------------------------------------------------------
# 3. test_noise_mad_robust_to_outlier — one spike does not inflate noise
# ---------------------------------------------------------------------------


def test_noise_mad_robust_to_outlier() -> None:
    engine = SensorDiagnosticsEngine()
    rng = np.random.default_rng(123)
    sigma = 0.01
    n = 500
    for i in range(n):
        v = 50.0 + rng.normal(0, sigma)
        if i == 250:
            v = 50.0 + 100.0  # massive spike
        engine.push("T1", i * 0.5, v)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    # MAD should stay near sigma, not be inflated by the spike
    assert diag.noise_std < sigma * 3

    # Compare with std which WOULD be inflated
    vals = np.array([50.0 + rng.normal(0, sigma) for _ in range(n)])
    vals[250] = 50.0 + 100.0
    std_val = float(np.std(vals))
    assert std_val > diag.noise_std * 10  # std is much larger due to outlier


# ---------------------------------------------------------------------------
# 4. test_drift_zero_constant — const T → drift ≈ 0
# ---------------------------------------------------------------------------


def test_drift_zero_constant() -> None:
    engine = SensorDiagnosticsEngine()
    _push_constant(engine, "T1", 50.0, n=200, dt=3.0)  # 600s window
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert abs(diag.drift_rate) < 1e-6


# ---------------------------------------------------------------------------
# 5. test_drift_known_slope — T = T₀ + rate·t → drift ≈ rate (±10%)
# ---------------------------------------------------------------------------


def test_drift_known_slope() -> None:
    engine = SensorDiagnosticsEngine()
    rate = 0.5  # K/min
    _push_linear(engine, "T1", 50.0, rate, n=200, dt=3.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert abs(diag.drift_rate - rate) / rate < 0.10


# ---------------------------------------------------------------------------
# 6. test_correlation_identical_signals — r ≈ 1.0
# ---------------------------------------------------------------------------


def test_correlation_identical_signals() -> None:
    engine = SensorDiagnosticsEngine(
        config={
            "correlation_groups": {"shield": ["T1", "T2"]},
        }
    )
    rng = np.random.default_rng(42)
    for i in range(200):
        v = 50.0 + rng.normal(0, 0.1)
        engine.push("T1", i * 0.5, v)
        engine.push("T2", i * 0.5, v)  # identical
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.correlation is not None
    assert diag.correlation > 0.99


# ---------------------------------------------------------------------------
# 7. test_correlation_uncorrelated — random vs random → |r| < 0.3
# ---------------------------------------------------------------------------


def test_correlation_uncorrelated() -> None:
    engine = SensorDiagnosticsEngine(
        config={
            "correlation_groups": {"shield": ["T1", "T2"]},
        }
    )
    rng = np.random.default_rng(42)
    for i in range(500):
        engine.push("T1", i * 0.5, 50.0 + rng.normal(0, 1.0))
        engine.push("T2", i * 0.5, 50.0 + rng.normal(0, 1.0))  # independent
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.correlation is not None
    assert abs(diag.correlation) < 0.3


# ---------------------------------------------------------------------------
# 8. test_correlation_no_neighbor — single channel in group → None
# ---------------------------------------------------------------------------


def test_correlation_no_neighbor() -> None:
    engine = SensorDiagnosticsEngine(
        config={
            "correlation_groups": {"shield": ["T1"]},
        }
    )
    _push_constant(engine, "T1", 50.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.correlation is None


# ---------------------------------------------------------------------------
# 9. test_health_perfect — low noise, zero drift, no outliers → 100
# ---------------------------------------------------------------------------


def test_health_perfect() -> None:
    engine = SensorDiagnosticsEngine(
        config={
            "correlation_groups": {"shield": ["T1", "T2"]},
        }
    )
    rng = np.random.default_rng(42)
    # Shared noise at warm T (threshold=0.2K) — noise ~0.01K << threshold,
    # identical signal → r=1.0, no drift, no outliers.
    for i in range(200):
        shared = rng.normal(0, 0.01)
        engine.push("T1", i * 0.5, 250.0 + shared)
        engine.push("T2", i * 0.5, 250.0 + shared)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.health_score == 100


# ---------------------------------------------------------------------------
# 10. test_health_noisy — noise > 3× threshold → health ≤ 60
# ---------------------------------------------------------------------------


def test_health_noisy() -> None:
    engine = SensorDiagnosticsEngine()
    # At T=50K, threshold=0.05K; noise = 0.2K → >3× threshold → -40
    _push_noisy(engine, "T1", 50.0, sigma=0.2, n=500)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.health_score <= 60


# ---------------------------------------------------------------------------
# 11. test_health_drifting — high drift → health ≤ 75
# ---------------------------------------------------------------------------


def test_health_drifting() -> None:
    engine = SensorDiagnosticsEngine()
    # Drift 0.5 K/min > threshold 0.1 → -25 → health = 75
    _push_linear(engine, "T1", 50.0, rate_K_per_min=0.5, n=200, dt=3.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.health_score <= 75


# ---------------------------------------------------------------------------
# 12. test_health_multiple_faults — noisy + drifting → health ≤ 35
# ---------------------------------------------------------------------------


def test_health_multiple_faults() -> None:
    engine = SensorDiagnosticsEngine()
    rng = np.random.default_rng(42)
    rate_per_sec = 0.5 / 60.0  # 0.5 K/min → > drift threshold
    sigma = 0.2  # > 3× threshold at 50K → -40 noise penalty
    for i in range(500):
        ts = i * 1.2  # spread over drift window
        v = 50.0 + rate_per_sec * ts + rng.normal(0, sigma)
        engine.push("T1", ts, v)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    # noise -40 + drift -25 = 35
    assert diag.health_score <= 35


# ---------------------------------------------------------------------------
# 13. test_noise_threshold_temperature_dependent
# ---------------------------------------------------------------------------


def test_noise_threshold_temperature_dependent() -> None:
    assert _get_noise_threshold(10.0) == pytest.approx(0.02)
    assert _get_noise_threshold(50.0) == pytest.approx(0.05)
    assert _get_noise_threshold(150.0) == pytest.approx(0.1)
    assert _get_noise_threshold(250.0) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# 14. test_outlier_detection — spikes detected, count correct
# ---------------------------------------------------------------------------


def test_outlier_detection() -> None:
    engine = SensorDiagnosticsEngine()
    rng = np.random.default_rng(42)
    sigma = 0.01
    spike_indices = {50, 100, 150}
    for i in range(300):
        v = 50.0 + rng.normal(0, sigma)
        if i in spike_indices:
            v = 50.0 + 10.0  # massive spike: >> 5σ
        engine.push("T1", i * 0.5, v)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert diag.outlier_count == len(spike_indices)


# ---------------------------------------------------------------------------
# 15. test_fault_flags_disconnected — T = 380K → ["disconnected"]
# ---------------------------------------------------------------------------


def test_fault_flags_disconnected() -> None:
    engine = SensorDiagnosticsEngine()
    _push_constant(engine, "T1", 380.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert "disconnected" in diag.fault_flags
    assert diag.health_score == 0


# ---------------------------------------------------------------------------
# 16. test_fault_flags_shorted — T ≈ 0K → ["shorted"]
# ---------------------------------------------------------------------------


def test_fault_flags_shorted() -> None:
    engine = SensorDiagnosticsEngine()
    _push_constant(engine, "T1", 0.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert "shorted" in diag.fault_flags
    assert diag.health_score == 0


# ---------------------------------------------------------------------------
# 17. test_summary_counts — 18 ok + 1 warn + 1 crit → summary correct
# ---------------------------------------------------------------------------


def test_summary_counts() -> None:
    engine = SensorDiagnosticsEngine()
    # 18 healthy channels
    for i in range(1, 19):
        _push_constant(engine, f"T{i}", 50.0)
    # 1 warning: noise > threshold at warm T (-20) + 3 outliers (-15) → health=65
    rng = np.random.default_rng(42)
    spike_at = {50, 100, 150}
    for i in range(200):
        v = 250.0 + rng.normal(0, 0.25)
        if i in spike_at:
            v = 260.0  # >> 5σ from median
        engine.push("T19", i * 0.5, v)
    # 1 critical (disconnected)
    _push_constant(engine, "T20", 380.0)

    engine.update()
    summary = engine.get_summary()
    assert summary.total_channels == 20
    assert summary.healthy == 18
    assert summary.warning == 1
    assert summary.critical == 1
    assert summary.worst_channel == "T20"
    assert summary.worst_score == 0


# ---------------------------------------------------------------------------
# 18. test_insufficient_data — <10 points → noise/drift = NaN, health = 100
# ---------------------------------------------------------------------------


def test_insufficient_data() -> None:
    engine = SensorDiagnosticsEngine()
    for i in range(5):
        engine.push("T1", i * 0.5, 50.0)
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    assert math.isnan(diag.noise_std)
    assert math.isnan(diag.drift_rate)
    assert diag.health_score == 100


# ---------------------------------------------------------------------------
# 19. test_buffer_window_sliding — old points expire
# ---------------------------------------------------------------------------


def test_buffer_window_sliding() -> None:
    engine = SensorDiagnosticsEngine(config={"noise_window_s": 10})
    # Push 100 points spanning 50 seconds
    for i in range(100):
        engine.push("T1", i * 0.5, 50.0 + (1.0 if i < 50 else 0.0))
    engine.update()
    diag = engine.get_diagnostics()["T1"]
    # Noise window is 10s → only last 20 points (all = 50.0) → noise ≈ 0
    assert diag.noise_std < 1e-9


# ---------------------------------------------------------------------------
# 20. test_serialization — asdict → JSON-compatible
# ---------------------------------------------------------------------------


def test_serialization() -> None:
    engine = SensorDiagnosticsEngine(
        config={
            "correlation_groups": {"shield": ["T1", "T2"]},
        }
    )
    _push_constant(engine, "T1", 50.0)
    _push_constant(engine, "T2", 51.0)
    engine.update()

    diag = engine.get_diagnostics()["T1"]
    d = asdict(diag)
    # Must be JSON-serializable (datetimes become strings via default handler)
    json_str = json.dumps(d, default=str)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["channel_id"] == "T1"
    assert isinstance(parsed["health_score"], int)

    summary = engine.get_summary()
    sd = asdict(summary)
    json_str2 = json.dumps(sd, default=str)
    assert isinstance(json_str2, str)
    parsed2 = json.loads(json_str2)
    assert parsed2["total_channels"] == 2


# ---------------------------------------------------------------------------
# Integration: engine config loading + feed + command response
# ---------------------------------------------------------------------------


def test_engine_config_loading() -> None:
    """SensorDiagnosticsEngine created from plugins.yaml-style config dict."""
    config = {
        "enabled": True,
        "update_interval_s": 10,
        "noise_window_s": 120,
        "drift_window_s": 600,
        "outlier_window_s": 300,
        "correlation_window_s": 600,
        "min_points": 10,
        "thresholds": {
            "drift_K_per_min": 0.1,
            "outlier_sigma": 5.0,
            "correlation_min": 0.8,
        },
        "correlation_groups": {
            "shield": ["T1", "T2", "T3"],
            "cold": ["T9", "T10"],
        },
    }
    engine = SensorDiagnosticsEngine(config=config)
    assert engine.noise_window_s == 120
    assert engine.drift_window_s == 600
    assert engine.drift_threshold == 0.1
    assert engine.corr_min == 0.8
    assert "T1" in engine._channel_to_group
    assert engine._channel_to_group["T1"] == "shield"
    assert engine._channel_to_group["T9"] == "cold"


def test_engine_feed_and_command_response() -> None:
    """Simulate engine feed loop → update → get_sensor_diagnostics response."""
    config = {
        "correlation_groups": {"shield": ["T1", "T2"]},
    }
    engine = SensorDiagnosticsEngine(config=config)
    engine.set_channel_names({"T1": "Т1 Экран", "T2": "Т2 Экран"})

    # Simulate readings arriving (like _sensor_diag_feed)
    rng = np.random.default_rng(42)
    for i in range(200):
        ts = i * 0.5
        shared = rng.normal(0, 0.01)
        engine.push("T1", ts, 250.0 + shared)
        engine.push("T2", ts, 250.0 + shared)

    # Simulate tick
    engine.update()

    # Simulate command handler response
    diag = engine.get_diagnostics()
    summary = engine.get_summary()
    response = {
        "ok": True,
        "channels": {k: asdict(v) for k, v in diag.items()},
        "summary": asdict(summary),
    }

    # Verify response structure (what GUI will receive)
    assert response["ok"] is True
    assert "T1" in response["channels"]
    assert "T2" in response["channels"]
    ch1 = response["channels"]["T1"]
    assert ch1["channel_name"] == "Т1 Экран"
    assert ch1["health_score"] == 100
    assert isinstance(ch1["noise_mK"], float)
    assert isinstance(ch1["drift_mK_per_min"], float)
    assert isinstance(ch1["fault_flags"], list)

    s = response["summary"]
    assert s["total_channels"] == 2
    assert s["healthy"] == 2
    assert s["warning"] == 0
    assert s["critical"] == 0

    # Regression: response must be JSON-serializable with default=str
    # (ZMQ bridge uses json.dumps(reply, default=str) to handle datetime)
    json_str = json.dumps(response, default=str)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["ok"] is True
    assert "T1" in parsed["channels"]


# ---------------------------------------------------------------------------
# Regression: correlation groups resolve short config IDs to full runtime names
# ---------------------------------------------------------------------------


def test_correlation_groups_resolve_short_to_full() -> None:
    """Correlation groups use short IDs (Т12), push uses full names (Т12 Теплообменник 2)."""
    cfg = {
        "correlation_groups": {
            "cold": ["\u0422\u0031\u0031", "\u0422\u0031\u0032"],  # Т11, Т12 (Cyrillic)
        },
        "noise_window_s": 10,
        "drift_window_s": 10,
        "outlier_window_s": 10,
        "correlation_window_s": 10,
        "min_points": 3,
    }
    engine = SensorDiagnosticsEngine(cfg)
    t0 = time.time()
    # Push with full runtime names (Cyrillic Т)
    for i in range(10):
        engine.push(
            "\u0422\u0031\u0031 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 1",  # noqa: E501
            t0 + i,
            80.0 + i * 0.1,
        )
        engine.push(
            "\u0422\u0031\u0032 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2",  # noqa: E501
            t0 + i,
            4.2 + i * 0.05,
        )
    engine.update()
    diag = engine.get_diagnostics()
    # Channel with full name should have correlation computed (not None)
    d11 = diag.get(
        "\u0422\u0031\u0031 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 1"  # noqa: E501
    )
    assert d11 is not None, "\u0422\u003111 diagnostics missing"
    # Correlation should be computable (both channels in same group)
    assert d11.correlation is not None, (
        "Correlation should be computed \u2014 short IDs in config must resolve to full runtime names"  # noqa: E501
    )
