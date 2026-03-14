"""Shared fixtures for analytics tests.

Provides `synthetic_curves`: 9 GM cryocooler cooldown curves built from
hard-coded statistics (same physics as generate_synthetic_curves in the
predictor module) WITHOUT importing cooldown_predictor, so conftest remains
usable even if the module has import-level issues.
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Hard-coded model statistics (mirrors defaults used in cmd_demo)
# ---------------------------------------------------------------------------

_STATS = {
    "total_duration_hours": {"mean": 19.3, "std": 1.0},
    "phase1_hours": {"mean": 8.0, "std": 0.5},
    "T_cold_baseline": {"mean": 4.7, "std": 1.5},
    "T_warm_baseline": {"mean": 87.0, "std": 6.0},
}

_T_PHASE_BOUNDARY = 50.0  # K — same constant as in the predictor module


@pytest.fixture
def synthetic_curves() -> list[dict]:
    """9 synthetic GM cryocooler cooldown curves for testing.

    Each entry is a plain dict::

        {
            "t_hours":  np.ndarray,   # monotonically increasing, ~0 … 18-21 h
            "T_cold":   np.ndarray,   # K, 280→4.7 (double-exp + S-bend)
            "T_warm":   np.ndarray,   # K, 280→87  (single-exp)
            "name":     str,
            "date":     str,
            "duration_hours": float,
            "phase1_hours":   float,
            "phase2_hours":   float,
            "T_cold_final":   float,
            "T_warm_final":   float,
        }

    No import of cooldown_predictor.  Suitable for tests that build
    ReferenceCurve objects themselves, or for testing via prepare_curve /
    build_ensemble after import.
    """
    stats = _STATS
    rng = np.random.RandomState(42)

    dur_mean = stats["total_duration_hours"]["mean"]
    dur_std = stats["total_duration_hours"]["std"]
    ph1_mean = stats["phase1_hours"]["mean"]
    ph1_std = stats["phase1_hours"]["std"]
    tc_base_mean = stats["T_cold_baseline"]["mean"]
    tc_base_std = stats["T_cold_baseline"]["std"]
    tw_base_mean = stats["T_warm_baseline"]["mean"]
    tw_base_std = stats["T_warm_baseline"]["std"]

    curves: list[dict] = []

    for i in range(9):
        duration = max(15.0, rng.normal(dur_mean, dur_std))
        phase1 = max(5.0, min(duration - 5, rng.normal(ph1_mean, ph1_std)))
        T_cold_final = max(3.5, rng.normal(tc_base_mean, tc_base_std))
        T_warm_final = max(70.0, min(110.0, rng.normal(tw_base_mean, tw_base_std)))

        # 10-second sample interval → dt = 10/3600 h
        dt_h = 10.0 / 3600.0
        t = np.arange(0, duration + dt_h, dt_h)
        n = len(t)

        # --- Cold channel: double-exponential + S-bend (Cu conductivity peak) ---
        T_start = 280 + rng.uniform(-15, 15)
        tau1 = phase1 / 2.5 + rng.normal(0, 0.2)
        tau2 = (duration - phase1) / 2.0 + rng.normal(0, 0.3)
        A1 = (T_start - 50) * 0.6
        A2 = (50 - T_cold_final) * 1.0

        T_cold = T_cold_final + A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2)

        # S-bend around the N2 plateau region
        t_bend = phase1 + (duration - phase1) * 0.3
        bend_w = 1.5 + rng.uniform(-0.3, 0.3)
        bend_a = 8.0 + rng.normal(0, 2)
        sigmoid = bend_a / (1 + np.exp(-(t - t_bend) / bend_w))
        mask = (T_cold > 10) & (T_cold < 80)
        T_cold[mask] += sigmoid[mask] * 0.3

        # Enforce monotone decrease then clip / add noise
        T_cold = np.maximum.accumulate(T_cold[::-1])[::-1]
        T_cold = np.clip(T_cold, T_cold_final, T_start + 10)
        T_cold += rng.normal(0, 0.1, n)
        T_cold = np.clip(T_cold, T_cold_final * 0.95, 400)

        # --- Warm channel: single-exponential ---
        T_start_w = T_start + rng.uniform(-5, 5)
        tau_w = duration / 3.0 + rng.normal(0, 0.3)
        T_warm = T_warm_final + (T_start_w - T_warm_final) * np.exp(-t / tau_w)
        T_warm += rng.normal(0, 0.2, n)
        T_warm = np.clip(T_warm, T_warm_final * 0.9, 400)

        # Locate phase-1 / phase-2 boundary (where T_cold crosses 50 K)
        cross_idx = np.searchsorted(-T_cold, -_T_PHASE_BOUNDARY)
        actual_ph1 = float(t[min(cross_idx, n - 1)])

        curves.append(
            {
                "t_hours": t,
                "T_cold": T_cold,
                "T_warm": T_warm,
                "name": f"synthetic_{i + 1:02d}",
                "date": f"2025-{6 + i:02d}-01",
                "duration_hours": float(t[-1]),
                "phase1_hours": actual_ph1,
                "phase2_hours": float(t[-1]) - actual_ph1,
                "T_cold_final": float(np.min(T_cold)),
                "T_warm_final": float(np.min(T_warm)),
            }
        )

    return curves
