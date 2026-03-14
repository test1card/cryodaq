#!/usr/bin/env python3
"""CryoDAQ Cooldown Predictor v1.0

Dual-channel progress-variable predictor for GM cryocooler cooldown.
Uses ensemble of reference curves from historical data.

Architecture:
    1. Load & normalize reference curves (JSON from log_parser extract)
    2. Build monotone progress variable p(T_cold, T_warm) in [0, 1]
    3. Build p->t mapping per reference curve, then ensemble statistics
    4. Online: (T_cold, T_warm, t_elapsed) -> t_remaining +/- CI
    5. Leave-one-out cross-validation for error estimation

Physics:
    - GM cryocooler, 2-stage (Gifford-McMahon)
    - Phase 1: 295K -> 50K (~8h), 1st stage dominates
    - N2 plateau: S-bend around 20-40K (OFHC Cu conductivity peak)
    - Phase 2: 50K -> 4K (~11h), 2nd stage dominates
    - Dual-channel (cold + warm) disambiguates the S-bend region

Usage:
    python cooldown_predictor.py build    --data cooldown_v5/ --output model/
    python cooldown_predictor.py predict  --model model/ --T_cold 50.0 --T_warm 120.0 --t_elapsed 8.0
    python cooldown_predictor.py validate --data cooldown_v5/ --output validation/
    python cooldown_predictor.py demo     --output demo/
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ============================================================================
# Constants
# ============================================================================

SMOOTH_WINDOW = 51
SMOOTH_ORDER = 3

W_COLD = 0.7
W_WARM = 0.3

MIN_SAMPLES = 50
T_PHASE_BOUNDARY = 50.0
N_PROGRESS_GRID = 500

T_COLD_START = 295.0
T_COLD_END = 4.0
T_WARM_START = 295.0
T_WARM_END = 85.0

# Adaptive rate-based weighting
RATE_WINDOW_H = 1.5          # compute avg cooling rate over first 1.5h
RATE_MIN_HISTORY_H = 0.5     # need at least 0.5h of data to estimate rate
RATE_WEIGHT_STRENGTH = 2.0   # exponent: higher = sharper preference for similar rates


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class ReferenceCurve:
    name: str
    date: str
    t_hours: np.ndarray
    T_cold: np.ndarray
    T_warm: np.ndarray
    duration_hours: float
    phase1_hours: float
    phase2_hours: float
    T_cold_final: float
    T_warm_final: float
    T_cold_smooth: Optional[np.ndarray] = field(default=None, repr=False)
    T_warm_smooth: Optional[np.ndarray] = field(default=None, repr=False)
    progress: Optional[np.ndarray] = field(default=None, repr=False)
    initial_rate_cold: float = 0.0    # K/h, avg dT_cold/dt over first RATE_WINDOW_H
    initial_rate_warm: float = 0.0    # K/h, avg dT_warm/dt over first RATE_WINDOW_H
    _t_of_p: Optional[interp1d] = field(default=None, repr=False)
    _p_of_t: Optional[interp1d] = field(default=None, repr=False)
    _Tc_of_p: Optional[interp1d] = field(default=None, repr=False)
    _Tw_of_p: Optional[interp1d] = field(default=None, repr=False)


@dataclass
class PredictionResult:
    t_remaining_hours: float
    t_remaining_low_68: float
    t_remaining_high_68: float
    t_remaining_low_95: float
    t_remaining_high_95: float
    t_total_hours: float
    progress: float
    phase: str
    T_cold_predicted_final: float
    T_warm_predicted_final: float
    n_references: int
    individual_estimates: list
    future_t: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_cold_mean: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_warm_mean: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_cold_upper: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_cold_lower: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_warm_upper: Optional[np.ndarray] = field(default=None, repr=False)
    future_T_warm_lower: Optional[np.ndarray] = field(default=None, repr=False)


@dataclass
class ValidationResult:
    curve_name: str
    t_query: np.ndarray
    T_cold_query: np.ndarray
    T_warm_query: np.ndarray
    progress_query: np.ndarray
    t_remaining_true: np.ndarray
    t_remaining_pred: np.ndarray
    t_remaining_err: np.ndarray
    t_remaining_pct_err: np.ndarray


@dataclass
class EnsembleModel:
    curves: list
    p_grid: np.ndarray
    t_matrix: np.ndarray
    Tc_matrix: np.ndarray
    Tw_matrix: np.ndarray
    t_mean: np.ndarray
    t_std: np.ndarray
    Tc_mean: np.ndarray
    Tc_std: np.ndarray
    Tw_mean: np.ndarray
    Tw_std: np.ndarray
    _t_of_p_mean: Optional[interp1d] = field(default=None, repr=False)
    _p_of_t_mean: Optional[interp1d] = field(default=None, repr=False)
    n_curves: int = 0
    duration_mean: float = 0.0
    duration_std: float = 0.0


# ============================================================================
# Loading & synthetic generation
# ============================================================================

def load_curves(data_dir: Path) -> list[ReferenceCurve]:
    json_files = sorted(data_dir.glob("*.json"))
    json_files = [f for f in json_files
                  if f.name not in ("cooldown_model.json", "reject_log.json")]
    curves = []
    for fp in json_files:
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            t_h = np.array(d["elapsed_hours"], dtype=float)
            tc = np.array(d["T_cold"], dtype=float)
            tw = np.array(d.get("T_warm", []), dtype=float)
            if len(t_h) < MIN_SAMPLES:
                print(f"  skip {fp.name}: {len(t_h)} samples < {MIN_SAMPLES}")
                continue
            if tc[0] < 100:
                print(f"  skip {fp.name}: T_start={tc[0]:.0f}K")
                continue
            if len(tw) == 0 or len(tw) != len(tc):
                tw = np.full_like(tc, np.nan)
            rc = ReferenceCurve(
                name=d.get("source_file", fp.stem), date=d.get("date", ""),
                t_hours=t_h, T_cold=tc, T_warm=tw,
                duration_hours=d.get("duration_hours", float(t_h[-1])),
                phase1_hours=d.get("phase1_hours", 0.0),
                phase2_hours=d.get("phase2_hours", 0.0),
                T_cold_final=d.get("T_cold_final", float(np.min(tc))),
                T_warm_final=d.get("T_warm_final", 0.0),
            )
            curves.append(rc)
        except Exception as e:
            print(f"  error loading {fp.name}: {e}")
    print(f"Loaded {len(curves)} reference curves")
    return curves


def generate_synthetic_curves(model_path: Path, n_curves: int = 9, seed: int = 42) -> list[ReferenceCurve]:
    """Generate synthetic cooldown curves from model statistics.

    Double-exponential + sigmoid S-bend matching GM cryocooler physics.
    """
    stats = json.loads(model_path.read_text(encoding="utf-8"))["statistics"]
    rng = np.random.RandomState(seed)

    dur_mean = stats["total_duration_hours"]["mean"]
    dur_std = stats["total_duration_hours"]["std"]
    ph1_mean = stats["phase1_hours"]["mean"]
    ph1_std = stats["phase1_hours"]["std"]
    tc_base_mean = stats["T_cold_baseline"]["mean"]
    tc_base_std = stats["T_cold_baseline"]["std"]
    tw_base_mean = stats["T_warm_baseline"]["mean"]
    tw_base_std = stats["T_warm_baseline"]["std"]

    curves = []
    for i in range(n_curves):
        duration = max(15.0, rng.normal(dur_mean, dur_std))
        phase1 = max(5.0, min(duration - 5, rng.normal(ph1_mean, ph1_std)))
        T_cold_final = max(3.5, rng.normal(tc_base_mean, tc_base_std))
        T_warm_final = max(70.0, min(110.0, rng.normal(tw_base_mean, tw_base_std)))

        dt_h = 10.0 / 3600.0
        t = np.arange(0, duration + dt_h, dt_h)
        n = len(t)

        # Cold: double exponential + S-bend
        T_start = 280 + rng.uniform(-15, 15)
        tau1 = phase1 / 2.5 + rng.normal(0, 0.2)
        tau2 = (duration - phase1) / 2.0 + rng.normal(0, 0.3)
        A1 = (T_start - 50) * 0.6
        A2 = (50 - T_cold_final) * 1.0

        T_cold = T_cold_final + A1 * np.exp(-t / tau1) + A2 * np.exp(-t / tau2)

        # S-bend (Cu conductivity peak)
        t_bend = phase1 + (duration - phase1) * 0.3
        bend_w = 1.5 + rng.uniform(-0.3, 0.3)
        bend_a = 8.0 + rng.normal(0, 2)
        sigmoid = bend_a / (1 + np.exp(-(t - t_bend) / bend_w))
        mask = (T_cold > 10) & (T_cold < 80)
        T_cold[mask] += sigmoid[mask] * 0.3

        T_cold = np.maximum.accumulate(T_cold[::-1])[::-1]
        T_cold = np.clip(T_cold, T_cold_final, T_start + 10)
        T_cold += rng.normal(0, 0.1, n)
        T_cold = np.clip(T_cold, T_cold_final * 0.95, 400)

        # Warm: single exponential
        T_start_w = T_start + rng.uniform(-5, 5)
        tau_w = duration / 3.0 + rng.normal(0, 0.3)
        T_warm = T_warm_final + (T_start_w - T_warm_final) * np.exp(-t / tau_w)
        T_warm += rng.normal(0, 0.2, n)
        T_warm = np.clip(T_warm, T_warm_final * 0.9, 400)

        cross_idx = np.searchsorted(-T_cold, -T_PHASE_BOUNDARY)
        actual_ph1 = float(t[min(cross_idx, n - 1)])

        rc = ReferenceCurve(
            name=f"synthetic_{i+1:02d}", date=f"2025-{6+i:02d}-01",
            t_hours=t, T_cold=T_cold, T_warm=T_warm,
            duration_hours=float(t[-1]),
            phase1_hours=actual_ph1, phase2_hours=float(t[-1]) - actual_ph1,
            T_cold_final=float(np.min(T_cold)),
            T_warm_final=float(np.min(T_warm)),
        )
        curves.append(rc)

    print(f"Generated {len(curves)} synthetic curves")
    return curves


# ============================================================================
# Curve preparation & progress variable
# ============================================================================

def _smooth(arr: np.ndarray, window: int = SMOOTH_WINDOW) -> np.ndarray:
    n = len(arr)
    w = min(window, n // 2 * 2 - 1)
    if w < 5:
        return arr.copy()
    return savgol_filter(arr, w, min(SMOOTH_ORDER, w - 1))


def compute_progress(T_cold: np.ndarray, T_warm: np.ndarray) -> np.ndarray:
    """Progress p in [0,1] from both channels. p=0 at 295K, p=1 at baseline."""
    dT_c = T_COLD_START - T_COLD_END
    dT_w = T_WARM_START - T_WARM_END

    p_cold = (T_COLD_START - T_cold) / dT_c if dT_c > 0 else np.zeros_like(T_cold)
    p_warm = (T_WARM_START - T_warm) / dT_w if dT_w > 0 else np.zeros_like(T_warm)

    if np.any(np.isnan(T_warm)):
        p = p_cold
    else:
        p = W_COLD * p_cold + W_WARM * p_warm

    return np.clip(p, 0.0, 1.0)


def _compute_initial_rate(t_hours: np.ndarray, T: np.ndarray, window_h: float) -> float:
    """Average cooling rate [K/h] over first `window_h` hours.

    Negative = cooling. Returns 0.0 if insufficient data.
    Uses linear fit over the window for robustness to noise.
    """
    mask = t_hours <= window_h
    if np.sum(mask) < 10:
        return 0.0
    t_w = t_hours[mask]
    T_w = T[mask]
    # Filter NaN
    valid = ~np.isnan(T_w)
    if np.sum(valid) < 5:
        return 0.0
    t_v = t_w[valid]
    T_v = T_w[valid]
    # Linear fit: T = a*t + b → a = dT/dt [K/h]
    if t_v[-1] - t_v[0] < 0.1:
        return 0.0
    a = float(np.polyfit(t_v, T_v, 1)[0])
    return a


def prepare_curve(rc: ReferenceCurve) -> ReferenceCurve:
    """Smooth, compute progress, build interpolators, measure initial rate."""
    n = len(rc.t_hours)
    rc.T_cold_smooth = _smooth(rc.T_cold)

    if len(rc.T_warm) == n and not np.all(np.isnan(rc.T_warm)):
        rc.T_warm_smooth = _smooth(rc.T_warm)
    else:
        rc.T_warm_smooth = np.full(n, np.nan)

    Tc = rc.T_cold_smooth
    Tw = rc.T_warm_smooth

    # --- Initial rate: average dT/dt over first RATE_WINDOW_H ---
    rc.initial_rate_cold = _compute_initial_rate(rc.t_hours, Tc, RATE_WINDOW_H)
    if not np.all(np.isnan(Tw)):
        rc.initial_rate_warm = _compute_initial_rate(rc.t_hours, Tw, RATE_WINDOW_H)

    rc.progress = compute_progress(Tc, Tw)
    rc.progress = np.maximum.accumulate(rc.progress)

    # p(t)
    rc._p_of_t = interp1d(rc.t_hours, rc.progress, kind="linear",
                          bounds_error=False, fill_value=(0.0, 1.0))

    # t(p), Tc(p), Tw(p) — need unique progress values
    _, unique_idx = np.unique(rc.progress, return_index=True)
    if len(unique_idx) >= 2:
        p_u = rc.progress[unique_idx]
        t_u = rc.t_hours[unique_idx]
        rc._t_of_p = interp1d(p_u, t_u, kind="linear",
                              bounds_error=False, fill_value=(t_u[0], t_u[-1]))
        rc._Tc_of_p = interp1d(p_u, Tc[unique_idx], kind="linear",
                               bounds_error=False,
                               fill_value=(Tc[unique_idx[0]], Tc[unique_idx[-1]]))
        if not np.all(np.isnan(Tw)):
            rc._Tw_of_p = interp1d(p_u, Tw[unique_idx], kind="linear",
                                   bounds_error=False,
                                   fill_value=(Tw[unique_idx[0]], Tw[unique_idx[-1]]))
    return rc


def prepare_all(curves: list[ReferenceCurve]) -> list[ReferenceCurve]:
    prepared = []
    for rc in curves:
        try:
            rc = prepare_curve(rc)
            if rc._t_of_p is not None:
                prepared.append(rc)
            else:
                print(f"  skip {rc.name}: interpolator build failed")
        except Exception as e:
            print(f"  skip {rc.name}: {e}")
    print(f"Prepared {len(prepared)}/{len(curves)} curves")
    return prepared


# ============================================================================
# Ensemble model
# ============================================================================

def build_ensemble(curves: list[ReferenceCurve]) -> EnsembleModel:
    n = len(curves)
    p_grid = np.linspace(0, 1, N_PROGRESS_GRID)

    t_mat = np.full((n, N_PROGRESS_GRID), np.nan)
    Tc_mat = np.full((n, N_PROGRESS_GRID), np.nan)
    Tw_mat = np.full((n, N_PROGRESS_GRID), np.nan)

    for i, rc in enumerate(curves):
        if rc._t_of_p is not None:
            t_mat[i] = rc._t_of_p(p_grid)
        if rc._Tc_of_p is not None:
            Tc_mat[i] = rc._Tc_of_p(p_grid)
        if rc._Tw_of_p is not None:
            Tw_mat[i] = rc._Tw_of_p(p_grid)

    t_mean = np.nanmean(t_mat, axis=0)
    t_std = np.nanstd(t_mat, axis=0)
    Tc_mean = np.nanmean(Tc_mat, axis=0)
    Tc_std = np.nanstd(Tc_mat, axis=0)
    Tw_mean = np.nanmean(Tw_mat, axis=0)
    Tw_std = np.nanstd(Tw_mat, axis=0)

    valid = ~np.isnan(t_mean)
    _t_of_p = interp1d(p_grid[valid], t_mean[valid], kind="linear",
                       bounds_error=False,
                       fill_value=(t_mean[valid][0], t_mean[valid][-1]))

    t_sorted_idx = np.argsort(t_mean[valid])
    t_sorted = t_mean[valid][t_sorted_idx]
    p_sorted = p_grid[valid][t_sorted_idx]
    _, u_idx = np.unique(t_sorted, return_index=True)
    _p_of_t = interp1d(t_sorted[u_idx], p_sorted[u_idx], kind="linear",
                       bounds_error=False, fill_value=(0.0, 1.0))

    durations = [rc.duration_hours for rc in curves]

    model = EnsembleModel(
        curves=curves, p_grid=p_grid,
        t_matrix=t_mat, Tc_matrix=Tc_mat, Tw_matrix=Tw_mat,
        t_mean=t_mean, t_std=t_std,
        Tc_mean=Tc_mean, Tc_std=Tc_std,
        Tw_mean=Tw_mean, Tw_std=Tw_std,
        _t_of_p_mean=_t_of_p, _p_of_t_mean=_p_of_t,
        n_curves=n,
        duration_mean=float(np.mean(durations)),
        duration_std=float(np.std(durations)),
    )
    print(f"Ensemble: {n} curves, duration {model.duration_mean:.1f} +/- {model.duration_std:.1f} h")
    return model


# ============================================================================
# Prediction
# ============================================================================

def predict(
    model: EnsembleModel,
    T_cold_now: float,
    T_warm_now: float,
    t_elapsed: float = 0.0,
    generate_trajectory: bool = True,
    observed_rate_cold: Optional[float] = None,
    observed_rate_warm: Optional[float] = None,
) -> PredictionResult:
    """Predict remaining cooldown time from current state.

    Weighting scheme (multiplicative):
        w = w_progress × w_rate

    w_progress: Gaussian kernel on t(p_now) vs t_elapsed.
        Curves whose timing matches the observed elapsed time score higher.

    w_rate: Gaussian kernel on initial cooling rate similarity.
        If observed_rate_cold is provided (typically after 0.5-1.5h of cooldown),
        curves with similar dT/dt in the first hours dominate.
        This is the key: fast cooldown → fast references, slow → slow.

    Without observed_rate: falls back to progress-only weighting (v1.0 behavior).
    """
    p_now = float(compute_progress(
        np.array([T_cold_now]), np.array([T_warm_now])
    )[0])

    # Compute rate statistics for outlier detection
    ref_rates_cold = np.array([rc.initial_rate_cold for rc in model.curves
                               if rc.initial_rate_cold != 0.0])
    ref_rates_warm = np.array([rc.initial_rate_warm for rc in model.curves
                               if rc.initial_rate_warm != 0.0])

    rate_cold_mean = float(np.mean(ref_rates_cold)) if len(ref_rates_cold) >= 2 else 0.0
    rate_cold_std = float(np.std(ref_rates_cold)) if len(ref_rates_cold) >= 2 else 999.0
    rate_warm_mean = float(np.mean(ref_rates_warm)) if len(ref_rates_warm) >= 2 else 0.0
    rate_warm_std = float(np.std(ref_rates_warm)) if len(ref_rates_warm) >= 2 else 999.0

    # Determine if observed rate is an outlier (>2σ from mean)
    # Only warm rate is used — cold rate depends on T_start which varies.
    # Warm rate is the true heat-load discriminator (e.g., illuminator: -3.6 vs typical -22 K/h)
    use_rate_cold = False  # disabled: unreliable when T_start varies
    use_rate_warm = False
    if observed_rate_warm is not None and rate_warm_std > 0:
        z_warm = abs(observed_rate_warm - rate_warm_mean) / rate_warm_std
        use_rate_warm = z_warm > 2.0

    estimates = []
    for rc in model.curves:
        if rc._t_of_p is None:
            continue
        t_at_p = float(rc._t_of_p(p_now))
        t_rem = max(0, rc.duration_hours - t_at_p)

        # --- Weight 1: progress/timing consistency (always active) ---
        if t_elapsed > 0:
            sigma_t = max(1.0, model.duration_std)
            w_prog = np.exp(-0.5 * ((t_at_p - t_elapsed) / sigma_t) ** 2)
        else:
            w_prog = 1.0

        # --- Weight 2: rate similarity (only when current rate is outlier) ---
        w_rate = 1.0
        if use_rate_cold and rc.initial_rate_cold != 0.0:
            sigma_rc = max(rate_cold_std * 0.5, 2.0)
            dr = observed_rate_cold - rc.initial_rate_cold
            w_rate *= np.exp(-0.5 * (dr / sigma_rc) ** 2)

        if use_rate_warm and rc.initial_rate_warm != 0.0:
            # Warm rate is often more discriminating (e.g., illuminator)
            sigma_rw = max(rate_warm_std * 0.4, 1.0)
            dr_w = observed_rate_warm - rc.initial_rate_warm
            w_rate *= np.exp(-0.5 * (dr_w / sigma_rw) ** 2)

        w_total = w_prog * w_rate
        estimates.append((rc.name, t_rem, rc.duration_hours, w_total, w_prog, w_rate))

    if not estimates:
        return PredictionResult(
            t_remaining_hours=0, t_remaining_low_68=0, t_remaining_high_68=0,
            t_remaining_low_95=0, t_remaining_high_95=0, t_total_hours=0,
            progress=p_now, phase="unknown",
            T_cold_predicted_final=4.0, T_warm_predicted_final=85.0,
            n_references=0, individual_estimates=[],
        )

    # --- Fallback: if rate weighting killed all references, disable it ---
    # This happens when observed rate is outlier but no reference has similar rate
    # (e.g., first illuminator test — nothing to match against)
    rate_weights = np.array([e[5] for e in estimates])
    if (use_rate_cold or use_rate_warm) and np.max(rate_weights) < 0.01:
        # No good rate match exists → fall back to progress-only (v1.0)
        estimates = [(n, r, d, wp, wp, 1.0) for n, r, d, _, wp, _ in estimates]

    t_rems = np.array([e[1] for e in estimates])
    t_tots = np.array([e[2] for e in estimates])
    weights = np.array([e[3] for e in estimates])
    weights /= weights.sum()

    t_rem_mean = float(np.average(t_rems, weights=weights))
    t_tot_mean = float(np.average(t_tots, weights=weights))
    t_rem_var = float(np.average((t_rems - t_rem_mean) ** 2, weights=weights))
    t_rem_std = max(np.sqrt(t_rem_var), 0.1)

    n_eff = len(estimates)
    t_68 = 1.0 + 0.5 / max(n_eff, 1)
    t_95 = 2.0 + 3.0 / max(n_eff, 1)

    if p_now >= 0.98:
        phase = "steady"
    elif T_cold_now > T_PHASE_BOUNDARY:
        phase = "phase1"
    elif T_cold_now > 15:
        phase = "transition"
    else:
        phase = "phase2"

    Tc_finals = [rc.T_cold_final for rc in model.curves]
    Tw_finals = [rc.T_warm_final for rc in model.curves if rc.T_warm_final > 0]

    result = PredictionResult(
        t_remaining_hours=t_rem_mean,
        t_remaining_low_68=max(0, t_rem_mean - t_68 * t_rem_std),
        t_remaining_high_68=t_rem_mean + t_68 * t_rem_std,
        t_remaining_low_95=max(0, t_rem_mean - t_95 * t_rem_std),
        t_remaining_high_95=t_rem_mean + t_95 * t_rem_std,
        t_total_hours=t_tot_mean,
        progress=p_now,
        phase=phase,
        T_cold_predicted_final=float(np.mean(Tc_finals)) if Tc_finals else 4.0,
        T_warm_predicted_final=float(np.mean(Tw_finals)) if Tw_finals else 85.0,
        n_references=n_eff,
        individual_estimates=[(n, round(r, 2)) for n, r, *_ in estimates],
    )

    if generate_trajectory and p_now < 0.98:
        p_future = np.linspace(p_now, 1.0, 200)
        t_fut = np.full((n_eff, 200), np.nan)
        Tc_fut = np.full((n_eff, 200), np.nan)
        Tw_fut = np.full((n_eff, 200), np.nan)

        for i, rc in enumerate(model.curves):
            if rc._t_of_p is not None:
                t_c = rc._t_of_p(p_future)
                t_c = t_c - float(rc._t_of_p(p_now)) + t_elapsed
                t_fut[i] = t_c
            if rc._Tc_of_p is not None:
                Tc_fut[i] = rc._Tc_of_p(p_future)
            if rc._Tw_of_p is not None:
                Tw_fut[i] = rc._Tw_of_p(p_future)

        result.future_t = np.nanmean(t_fut, axis=0)
        result.future_T_cold_mean = np.nanmean(Tc_fut, axis=0)
        result.future_T_warm_mean = np.nanmean(Tw_fut, axis=0)
        result.future_T_cold_upper = result.future_T_cold_mean + np.nanstd(Tc_fut, axis=0)
        result.future_T_cold_lower = result.future_T_cold_mean - np.nanstd(Tc_fut, axis=0)
        result.future_T_warm_upper = result.future_T_warm_mean + np.nanstd(Tw_fut, axis=0)
        result.future_T_warm_lower = result.future_T_warm_mean - np.nanstd(Tw_fut, axis=0)

    return result


def _progress_bar(p: float, width: int = 30) -> str:
    filled = int(p * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def compute_rate_from_history(
    t_hours: np.ndarray, T_cold: np.ndarray,
    T_warm: Optional[np.ndarray] = None,
    window_h: float = RATE_WINDOW_H,
) -> tuple[Optional[float], Optional[float]]:
    """Compute initial cooling rates from observed history.

    Call this from CryoDAQ engine with the data buffer so far.
    Returns (rate_cold, rate_warm) in K/h. Returns None if insufficient data.

    Usage:
        rate_c, rate_w = compute_rate_from_history(t_buf, Tc_buf, Tw_buf)
        pred = predict(model, Tc_now, Tw_now, t_elapsed,
                       observed_rate_cold=rate_c, observed_rate_warm=rate_w)
    """
    if len(t_hours) < 10 or t_hours[-1] < RATE_MIN_HISTORY_H:
        return None, None

    rate_c = _compute_initial_rate(t_hours, T_cold, window_h)
    rate_w = None
    if T_warm is not None and len(T_warm) == len(T_cold):
        rate_w = _compute_initial_rate(t_hours, T_warm, window_h)

    return (rate_c if rate_c != 0.0 else None,
            rate_w if rate_w is not None and rate_w != 0.0 else None)


def format_prediction(pred: PredictionResult) -> str:
    h = int(pred.t_remaining_hours)
    m = int((pred.t_remaining_hours - h) * 60)
    ci68 = pred.t_remaining_high_68 - pred.t_remaining_hours
    lines = [
        f"  Progress:  {pred.progress:5.1%}  [{_progress_bar(pred.progress)}]",
        f"  Phase:     {pred.phase}",
        f"  Remaining: {h}h {m:02d}m  (+/-{ci68:.1f}h 68% CI)",
        f"  95% CI:    [{pred.t_remaining_low_95:.1f} - {pred.t_remaining_high_95:.1f}] h",
        f"  Total:     {pred.t_total_hours:.1f} h",
        f"  T_cold ->  {pred.T_cold_predicted_final:.1f} K",
        f"  T_warm ->  {pred.T_warm_predicted_final:.1f} K",
        f"  Ensemble:  {pred.n_references} curves",
    ]
    return "\n".join(lines)


# ============================================================================
# LOO cross-validation
# ============================================================================

def validate_loo(curves: list[ReferenceCurve], n_query: int = 50) -> list[ValidationResult]:
    results = []
    for i_hold in range(len(curves)):
        held = curves[i_hold]
        training = [c for j, c in enumerate(curves) if j != i_hold]
        if len(training) < 2:
            continue
        training_p = prepare_all(training)
        if len(training_p) < 2:
            continue
        model = build_ensemble(training_p)

        n_pts = len(held.t_hours)
        i_s = int(0.05 * n_pts)
        i_e = int(0.98 * n_pts)
        step = max(1, (i_e - i_s) // n_query)

        t_q, Tc_q, Tw_q, p_q, rem_true, rem_pred = [], [], [], [], [], []
        for qi in range(i_s, i_e, step):
            t_el = held.t_hours[qi]
            Tc = held.T_cold[qi]
            Tw = held.T_warm[qi] if qi < len(held.T_warm) and not np.isnan(held.T_warm[qi]) else 200.0

            # Adaptive rate: compute from held-out history up to this point
            rate_c, rate_w = None, None
            if t_el >= RATE_MIN_HISTORY_H:
                hist_mask = held.t_hours[:qi+1] <= RATE_WINDOW_H
                if np.sum(hist_mask) >= 10:
                    rate_c = _compute_initial_rate(held.t_hours[:qi+1], held.T_cold[:qi+1], RATE_WINDOW_H)
                    if not np.all(np.isnan(held.T_warm[:qi+1])):
                        rate_w = _compute_initial_rate(held.t_hours[:qi+1], held.T_warm[:qi+1], RATE_WINDOW_H)
                    if rate_c == 0.0: rate_c = None
                    if rate_w is not None and rate_w == 0.0: rate_w = None

            pred = predict(model, Tc, Tw, t_el, generate_trajectory=False,
                           observed_rate_cold=rate_c, observed_rate_warm=rate_w)
            t_q.append(t_el)
            Tc_q.append(Tc)
            Tw_q.append(Tw)
            p_q.append(pred.progress)
            rem_true.append(held.duration_hours - t_el)
            rem_pred.append(pred.t_remaining_hours)

        rem_true = np.array(rem_true)
        rem_pred = np.array(rem_pred)
        err = rem_pred - rem_true
        pct = np.where(rem_true > 0.5, err / rem_true * 100, 0.0)

        vr = ValidationResult(
            curve_name=held.name,
            t_query=np.array(t_q), T_cold_query=np.array(Tc_q),
            T_warm_query=np.array(Tw_q), progress_query=np.array(p_q),
            t_remaining_true=rem_true, t_remaining_pred=rem_pred,
            t_remaining_err=err, t_remaining_pct_err=pct,
        )
        results.append(vr)
        mae = float(np.mean(np.abs(err)))
        print(f"  LOO {held.name}: MAE={mae:.2f}h, max|err|={np.max(np.abs(err)):.2f}h")
    return results


# ============================================================================
# Plotting
# ============================================================================

def plot_ensemble(model: EnsembleModel, output: Path):
    fig = plt.figure(figsize=(18, 14))
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.25)
    cmap = plt.cm.tab10

    # T_cold vs time
    ax1 = fig.add_subplot(gs[0, 0])
    for i, rc in enumerate(model.curves):
        ax1.plot(rc.t_hours, rc.T_cold_smooth, color=cmap(i % 10),
                 alpha=0.5, lw=0.8, label=rc.name[:25] if i < 10 else None)
    ax1.plot(model.t_mean, model.Tc_mean, "k-", lw=2, label="Mean")
    ax1.fill_between(model.t_mean, model.Tc_mean - model.Tc_std,
                     model.Tc_mean + model.Tc_std, alpha=0.2, color="gray", label="+/-1s")
    ax1.set_ylabel("T cold, K"); ax1.set_title("Cold Stage")
    ax1.set_yscale("log"); ax1.set_ylim(1, 500)
    ax1.legend(fontsize=6, loc="upper right"); ax1.grid(True, alpha=0.3)

    # T_warm vs time
    ax2 = fig.add_subplot(gs[0, 1])
    for i, rc in enumerate(model.curves):
        if rc.T_warm_smooth is not None and not np.all(np.isnan(rc.T_warm_smooth)):
            ax2.plot(rc.t_hours, rc.T_warm_smooth, color=cmap(i % 10), alpha=0.5, lw=0.8)
    ax2.plot(model.t_mean, model.Tw_mean, "k-", lw=2)
    ax2.fill_between(model.t_mean, model.Tw_mean - model.Tw_std,
                     model.Tw_mean + model.Tw_std, alpha=0.2, color="gray")
    ax2.set_ylabel("T warm, K"); ax2.set_title("Warm Stage"); ax2.grid(True, alpha=0.3)

    # Progress vs time
    ax3 = fig.add_subplot(gs[1, 0])
    for i, rc in enumerate(model.curves):
        if rc.progress is not None:
            ax3.plot(rc.t_hours, rc.progress, color=cmap(i % 10), alpha=0.5, lw=0.8)
    ax3.plot(model.t_mean, model.p_grid, "k-", lw=2, label="Mean p(t)")
    ax3.set_xlabel("Time, h"); ax3.set_ylabel("Progress p")
    ax3.set_title("Progress Variable"); ax3.set_ylim(-0.05, 1.05)
    ax3.grid(True, alpha=0.3); ax3.legend(fontsize=8)

    # t(p) envelope — THE predictor
    ax4 = fig.add_subplot(gs[1, 1])
    for i in range(model.n_curves):
        ax4.plot(model.p_grid, model.t_matrix[i], color=cmap(i % 10), alpha=0.4, lw=0.6)
    ax4.plot(model.p_grid, model.t_mean, "k-", lw=2, label="Mean t(p)")
    ax4.fill_between(model.p_grid, model.t_mean - model.t_std,
                     model.t_mean + model.t_std, alpha=0.15, color="blue", label="+/-1s")
    ax4.fill_between(model.p_grid, model.t_mean - 2*model.t_std,
                     model.t_mean + 2*model.t_std, alpha=0.08, color="blue", label="+/-2s")
    ax4.set_xlabel("Progress p"); ax4.set_ylabel("Time, h")
    ax4.set_title("Predictor: t(p) +/- CI"); ax4.legend(fontsize=8); ax4.grid(True, alpha=0.3)

    # sigma vs progress
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.plot(model.p_grid, model.t_std, "r-", lw=1.5)
    ax5.set_xlabel("Progress p"); ax5.set_ylabel("sigma(t_remaining), h")
    ax5.set_title("Prediction Uncertainty vs Progress"); ax5.grid(True, alpha=0.3)

    # Duration histogram
    ax6 = fig.add_subplot(gs[2, 1])
    durs = [rc.duration_hours for rc in model.curves]
    ax6.hist(durs, bins=max(3, len(durs)//2), edgecolor="black", alpha=0.7, color="steelblue")
    ax6.axvline(model.duration_mean, color="red", ls="--",
                label=f"Mean: {model.duration_mean:.1f}h")
    ax6.set_xlabel("Duration, h"); ax6.set_ylabel("Count")
    ax6.set_title(f"Duration (n={model.n_curves})"); ax6.legend(); ax6.grid(True, alpha=0.3)

    fig.suptitle("CryoDAQ Cooldown Predictor - Ensemble Model", fontsize=14, fontweight="bold")
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Ensemble plot: {output}")


def plot_prediction(model, pred, T_cold_now, T_warm_now, t_elapsed, output):
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for rc in model.curves:
        axes[0].plot(rc.t_hours, rc.T_cold_smooth, color="lightgray", lw=0.5, alpha=0.5)
        if rc.T_warm_smooth is not None and not np.all(np.isnan(rc.T_warm_smooth)):
            axes[1].plot(rc.t_hours, rc.T_warm_smooth, color="lightgray", lw=0.5, alpha=0.5)

    axes[0].plot(t_elapsed, T_cold_now, "ro", ms=12, zorder=10,
                 label=f"Now: {T_cold_now:.1f}K @ {t_elapsed:.1f}h")
    axes[1].plot(t_elapsed, T_warm_now, "ro", ms=12, zorder=10,
                 label=f"Now: {T_warm_now:.1f}K")

    if pred.future_t is not None:
        axes[0].plot(pred.future_t, pred.future_T_cold_mean, "b-", lw=2, label="Predicted")
        axes[0].fill_between(pred.future_t, pred.future_T_cold_lower,
                             pred.future_T_cold_upper, alpha=0.2, color="blue")
        axes[1].plot(pred.future_t, pred.future_T_warm_mean, "b-", lw=2, label="Predicted")
        axes[1].fill_between(pred.future_t, pred.future_T_warm_lower,
                             pred.future_T_warm_upper, alpha=0.2, color="blue")

    t_end = t_elapsed + pred.t_remaining_hours
    ci = pred.t_remaining_high_68 - pred.t_remaining_hours
    axes[0].axvline(t_end, color="green", ls="--", alpha=0.7,
                    label=f"ETA: {t_end:.1f}h (+/-{ci:.1f}h)")
    axes[1].axvline(t_end, color="green", ls="--", alpha=0.7)

    axes[0].set_ylabel("T_cold, K"); axes[0].set_yscale("log"); axes[0].set_ylim(1, 500)
    axes[0].legend(fontsize=8, loc="upper right"); axes[0].grid(True, alpha=0.3)
    h, m = int(pred.t_remaining_hours), int((pred.t_remaining_hours % 1) * 60)
    axes[0].set_title(f"p={pred.progress:.1%} | {h}h{m:02d}m left | {pred.phase}", fontsize=11)
    axes[1].set_ylabel("T_warm, K"); axes[1].set_xlabel("Time, h")
    axes[1].legend(fontsize=8); axes[1].grid(True, alpha=0.3)

    fig.suptitle("CryoDAQ Cooldown Prediction", fontsize=13, fontweight="bold")
    fig.savefig(output, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"Prediction plot: {output}")


def plot_validation(results: list[ValidationResult], output: Path):
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    cmap = plt.cm.tab10

    ax = axes[0, 0]
    for i, vr in enumerate(results):
        ax.plot(vr.t_query, vr.t_remaining_err * 60, "o-", color=cmap(i%10),
                ms=2, lw=0.8, alpha=0.7, label=vr.curve_name[:20])
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("Elapsed, h"); ax.set_ylabel("Error, min")
    ax.set_title("Error vs Time"); ax.legend(fontsize=5, ncol=2); ax.grid(True, alpha=0.3)

    ax = axes[0, 1]
    for i, vr in enumerate(results):
        ax.plot(vr.progress_query, vr.t_remaining_err * 60, "o-",
                color=cmap(i%10), ms=2, lw=0.8, alpha=0.7)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("Progress"); ax.set_ylabel("Error, min")
    ax.set_title("Error vs Progress"); ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    for i, vr in enumerate(results):
        ax.scatter(vr.t_remaining_true, vr.t_remaining_pred, c=[cmap(i%10)], s=5, alpha=0.6)
    all_t = np.concatenate([vr.t_remaining_true for vr in results])
    all_p = np.concatenate([vr.t_remaining_pred for vr in results])
    lim = max(all_t.max(), all_p.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=0.5)
    ax.set_xlabel("True remaining, h"); ax.set_ylabel("Predicted, h")
    ax.set_title("Predicted vs True"); ax.set_aspect("equal")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim); ax.grid(True, alpha=0.3)

    ax = axes[1, 1]; ax.axis("off")
    all_err = np.concatenate([vr.t_remaining_err for vr in results])
    all_abs = np.abs(all_err)
    all_pct = np.concatenate([vr.t_remaining_pct_err for vr in results])
    curve_maes = [float(np.mean(np.abs(vr.t_remaining_err))) for vr in results]

    txt = (f"LOO Cross-Validation (n={len(results)})\n"
           f"{'='*40}\n"
           f"MAE:    {np.mean(all_abs):.2f} h ({np.mean(all_abs)*60:.0f} min)\n"
           f"RMSE:   {np.sqrt(np.mean(all_err**2)):.2f} h\n"
           f"Max:    {np.max(all_abs):.2f} h\n"
           f"Median: {np.median(all_abs):.2f} h\n"
           f"Bias:   {np.mean(all_err):.3f} h\n"
           f"{'='*40}\n")
    for vr, mae in zip(results, curve_maes):
        txt += f"  {vr.curve_name[:28]:28s} MAE={mae:.2f}h\n"
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=9,
            va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.8))

    fig.suptitle("CryoDAQ Predictor - LOO Validation", fontsize=14, fontweight="bold")
    fig.tight_layout(); fig.savefig(output, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"Validation plot: {output}")


# ============================================================================
# Model save/load
# ============================================================================

def save_model(model: EnsembleModel, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    md = {
        "version": "1.0", "n_curves": model.n_curves,
        "duration_mean": model.duration_mean, "duration_std": model.duration_std,
        "p_grid": model.p_grid.tolist(),
        "t_mean": model.t_mean.tolist(), "t_std": model.t_std.tolist(),
        "Tc_mean": model.Tc_mean.tolist(), "Tc_std": model.Tc_std.tolist(),
        "Tw_mean": model.Tw_mean.tolist(), "Tw_std": model.Tw_std.tolist(),
        "curves": [{
            "name": rc.name, "date": rc.date,
            "duration_hours": rc.duration_hours,
            "phase1_hours": rc.phase1_hours, "phase2_hours": rc.phase2_hours,
            "T_cold_final": rc.T_cold_final, "T_warm_final": rc.T_warm_final,
            "t_hours": rc.t_hours.tolist(),
            "T_cold": rc.T_cold.tolist(), "T_warm": rc.T_warm.tolist(),
        } for rc in model.curves],
    }
    out = output_dir / "predictor_model.json"
    out.write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
    print(f"Model saved: {out} ({out.stat().st_size/1024:.0f} KB)")


def load_model(model_dir: Path) -> EnsembleModel:
    d = json.loads((model_dir / "predictor_model.json").read_text(encoding="utf-8"))
    curves = []
    for cd in d["curves"]:
        rc = ReferenceCurve(
            name=cd["name"], date=cd["date"],
            t_hours=np.array(cd["t_hours"]), T_cold=np.array(cd["T_cold"]),
            T_warm=np.array(cd["T_warm"]),
            duration_hours=cd["duration_hours"],
            phase1_hours=cd["phase1_hours"], phase2_hours=cd["phase2_hours"],
            T_cold_final=cd["T_cold_final"], T_warm_final=cd["T_warm_final"],
        )
        curves.append(rc)
    curves = prepare_all(curves)
    return build_ensemble(curves)


# ============================================================================
# Online learning: ingest new curves into existing model
# ============================================================================

# Quality gate thresholds for incoming curves
INGEST_MIN_DURATION_H = 10.0
INGEST_MAX_DURATION_H = 30.0
INGEST_MIN_T_START = 150.0       # K
INGEST_MAX_T_COLD_FINAL = 12.0   # K
INGEST_MAX_T_WARM_FINAL = 120.0  # K
INGEST_MIN_MONOTONICITY = 0.70
INGEST_MIN_POINTS = 500


def validate_new_curve(rc: ReferenceCurve) -> tuple[bool, str]:
    """Quality gate for a new curve before adding to model.

    Returns (passed, reason).
    """
    if len(rc.t_hours) < INGEST_MIN_POINTS:
        return False, f"too few points: {len(rc.t_hours)} < {INGEST_MIN_POINTS}"

    if rc.duration_hours < INGEST_MIN_DURATION_H:
        return False, f"too short: {rc.duration_hours:.1f}h < {INGEST_MIN_DURATION_H}h"

    if rc.duration_hours > INGEST_MAX_DURATION_H:
        return False, f"too long: {rc.duration_hours:.1f}h > {INGEST_MAX_DURATION_H}h"

    if rc.T_cold[0] < INGEST_MIN_T_START:
        return False, f"T_start too low: {rc.T_cold[0]:.0f}K < {INGEST_MIN_T_START}K"

    if rc.T_cold_final > INGEST_MAX_T_COLD_FINAL:
        return False, f"T_cold_final too high: {rc.T_cold_final:.1f}K"

    if rc.T_warm_final > INGEST_MAX_T_WARM_FINAL and rc.T_warm_final > 0:
        return False, f"T_warm_final too high: {rc.T_warm_final:.0f}K"

    # Monotonicity check
    dT = np.diff(rc.T_cold)
    frac_dec = float(np.sum(dT < 0.5) / len(dT))
    if frac_dec < INGEST_MIN_MONOTONICITY:
        return False, f"monotonicity {frac_dec:.0%} < {INGEST_MIN_MONOTONICITY:.0%}"

    return True, "OK"


def ingest_curve(
    model_dir: Path,
    new_curve_json: Path,
    force: bool = False,
    max_curves: int = 50,
) -> tuple[bool, str, Optional[EnsembleModel]]:
    """Add a completed cooldown curve to an existing model.

    This is the programmatic API for CryoDAQ integration.
    Call after a cooldown cycle completes and log_parser has extracted the JSON.

    Args:
        model_dir: directory containing predictor_model.json
        new_curve_json: path to the new cooldown JSON (log_parser extract format)
        force: skip quality gate
        max_curves: cap ensemble size (oldest curves dropped if exceeded)

    Returns:
        (success, message, updated_model_or_None)

    Usage from CryoDAQ engine:
        from cooldown_predictor import ingest_curve
        ok, msg, model = ingest_curve(Path("model/"), Path("new_cooldown.json"))
        if ok:
            print(f"Model updated: {model.n_curves} curves")
    """
    model_file = model_dir / "predictor_model.json"
    if not model_file.exists():
        return False, f"Model not found: {model_file}", None

    # Load new curve
    try:
        d = json.loads(new_curve_json.read_text(encoding="utf-8"))
        t_h = np.array(d["elapsed_hours"], dtype=float)
        tc = np.array(d["T_cold"], dtype=float)
        tw = np.array(d.get("T_warm", []), dtype=float)
        if len(tw) == 0 or len(tw) != len(tc):
            tw = np.full_like(tc, np.nan)

        new_rc = ReferenceCurve(
            name=d.get("source_file", new_curve_json.stem),
            date=d.get("date", ""),
            t_hours=t_h, T_cold=tc, T_warm=tw,
            duration_hours=d.get("duration_hours", float(t_h[-1])),
            phase1_hours=d.get("phase1_hours", 0.0),
            phase2_hours=d.get("phase2_hours", 0.0),
            T_cold_final=d.get("T_cold_final", float(np.min(tc))),
            T_warm_final=d.get("T_warm_final", 0.0),
        )
    except Exception as e:
        return False, f"Failed to parse {new_curve_json.name}: {e}", None

    # Quality gate
    if not force:
        passed, reason = validate_new_curve(new_rc)
        if not passed:
            return False, f"REJECT: {reason}", None

    # Load existing model
    model_data = json.loads(model_file.read_text(encoding="utf-8"))

    # Duplicate check (by name)
    existing_names = {c["name"] for c in model_data["curves"]}
    if new_rc.name in existing_names:
        return False, f"Duplicate: '{new_rc.name}' already in model", None

    # Add new curve data to model JSON
    new_entry = {
        "name": new_rc.name,
        "date": new_rc.date,
        "duration_hours": new_rc.duration_hours,
        "phase1_hours": new_rc.phase1_hours,
        "phase2_hours": new_rc.phase2_hours,
        "T_cold_final": new_rc.T_cold_final,
        "T_warm_final": new_rc.T_warm_final,
        "t_hours": new_rc.t_hours.tolist(),
        "T_cold": new_rc.T_cold.tolist(),
        "T_warm": new_rc.T_warm.tolist(),
    }
    model_data["curves"].append(new_entry)

    # Cap ensemble size: drop oldest if over limit
    if len(model_data["curves"]) > max_curves:
        # Sort by date, keep newest max_curves
        model_data["curves"].sort(key=lambda c: c.get("date", ""))
        n_drop = len(model_data["curves"]) - max_curves
        dropped = [c["name"] for c in model_data["curves"][:n_drop]]
        model_data["curves"] = model_data["curves"][n_drop:]
        print(f"  Dropped {n_drop} oldest curves: {dropped}")

    # Rebuild ensemble
    curves = []
    for cd in model_data["curves"]:
        rc = ReferenceCurve(
            name=cd["name"], date=cd["date"],
            t_hours=np.array(cd["t_hours"]),
            T_cold=np.array(cd["T_cold"]),
            T_warm=np.array(cd["T_warm"]),
            duration_hours=cd["duration_hours"],
            phase1_hours=cd["phase1_hours"],
            phase2_hours=cd["phase2_hours"],
            T_cold_final=cd["T_cold_final"],
            T_warm_final=cd["T_warm_final"],
        )
        curves.append(rc)

    curves = prepare_all(curves)
    model = build_ensemble(curves)

    # Save updated model with history
    model_data["n_curves"] = model.n_curves
    model_data["duration_mean"] = model.duration_mean
    model_data["duration_std"] = model.duration_std
    model_data["p_grid"] = model.p_grid.tolist()
    model_data["t_mean"] = model.t_mean.tolist()
    model_data["t_std"] = model.t_std.tolist()
    model_data["Tc_mean"] = model.Tc_mean.tolist()
    model_data["Tc_std"] = model.Tc_std.tolist()
    model_data["Tw_mean"] = model.Tw_mean.tolist()
    model_data["Tw_std"] = model.Tw_std.tolist()

    # Version bump
    old_ver = model_data.get("version", "1.0")
    try:
        major, minor = old_ver.split(".")
        model_data["version"] = f"{major}.{int(minor) + 1}"
    except ValueError:
        model_data["version"] = "1.1"

    # Update history log
    history = model_data.get("history", [])
    history.append({
        "action": "ingest",
        "curve": new_rc.name,
        "date": new_rc.date,
        "duration_h": round(new_rc.duration_hours, 1),
        "n_curves_after": model.n_curves,
    })
    model_data["history"] = history

    # Backup old model, then save
    backup = model_dir / "predictor_model.json.bak"
    if model_file.exists():
        import shutil
        shutil.copy2(model_file, backup)

    model_file.write_text(json.dumps(model_data, ensure_ascii=False), encoding="utf-8")

    msg = (f"OK: added '{new_rc.name}' ({new_rc.duration_hours:.1f}h). "
           f"Model v{model_data['version']}: {model.n_curves} curves, "
           f"{model.duration_mean:.1f}+/-{model.duration_std:.1f}h")
    print(f"  {msg}")
    return True, msg, model


def ingest_from_raw_arrays(
    model_dir: Path,
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    name: str = "",
    date: str = "",
    force: bool = False,
) -> tuple[bool, str, Optional[EnsembleModel]]:
    """Ingest directly from numpy arrays (for real-time CryoDAQ integration).

    Call this when a cooldown cycle completes and you have the data in memory.
    No intermediate JSON file needed.

    Usage:
        from cooldown_predictor import ingest_from_raw_arrays
        ok, msg, model = ingest_from_raw_arrays(
            Path("model/"), t_hours, T_cold, T_warm,
            name="experiment_2026-03-15"
        )
    """
    if not name:
        from datetime import datetime as _dt
        name = f"auto_ingest_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
    if not date:
        from datetime import datetime as _dt
        date = _dt.now().strftime("%Y-%m-%d")

    # Find phase1 boundary
    cross = np.where(T_cold < T_PHASE_BOUNDARY)[0]
    ph1 = float(t_hours[cross[0]]) if len(cross) > 0 else float(t_hours[-1])

    # Write temporary JSON
    tmp_data = {
        "source_file": name,
        "date": date,
        "elapsed_hours": t_hours.tolist(),
        "T_cold": T_cold.tolist(),
        "T_warm": T_warm.tolist(),
        "duration_hours": float(t_hours[-1]),
        "phase1_hours": ph1,
        "phase2_hours": float(t_hours[-1]) - ph1,
        "T_cold_final": float(np.min(T_cold)),
        "T_warm_final": float(np.min(T_warm)) if not np.all(np.isnan(T_warm)) else 0.0,
    }
    tmp_path = model_dir / "_tmp_ingest.json"
    tmp_path.write_text(json.dumps(tmp_data), encoding="utf-8")

    try:
        result = ingest_curve(model_dir, tmp_path, force=force)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return result


# ============================================================================
# CLI
# ============================================================================

def cmd_update(args):
    """CLI: add a new curve to existing model."""
    model_dir = Path(args.model)
    curve_path = Path(args.curve)

    if not curve_path.exists():
        sys.exit(f"Curve file not found: {curve_path}")

    ok, msg, model = ingest_curve(model_dir, curve_path, force=args.force)
    print(msg)

    if ok and model:
        plot_ensemble(model, model_dir / "ensemble_overview.png")

    sys.exit(0 if ok else 1)


def cmd_build(args):
    curves = load_curves(Path(args.data))
    if not curves:
        sys.exit("No curves loaded")
    curves = prepare_all(curves)
    model = build_ensemble(curves)
    out = Path(args.output)
    save_model(model, out)
    plot_ensemble(model, out / "ensemble_overview.png")
    print(f"\nModel: {model.n_curves} curves, {model.duration_mean:.1f}+/-{model.duration_std:.1f} h")


def cmd_predict(args):
    model = load_model(Path(args.model))
    rate_c = args.rate_cold if hasattr(args, 'rate_cold') else None
    rate_w = args.rate_warm if hasattr(args, 'rate_warm') else None
    pred = predict(model, args.T_cold, args.T_warm, args.t_elapsed,
                   observed_rate_cold=rate_c, observed_rate_warm=rate_w)
    print(format_prediction(pred))
    if args.output:
        plot_prediction(model, pred, args.T_cold, args.T_warm, args.t_elapsed, Path(args.output))


def cmd_validate(args):
    curves = load_curves(Path(args.data))
    if len(curves) < 3:
        sys.exit(f"Need >=3 curves, got {len(curves)}")
    curves = prepare_all(curves)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    results = validate_loo(curves)
    if results:
        plot_validation(results, out / "loo_validation.png")
        summary = [{"curve": vr.curve_name,
                     "mae_h": float(np.mean(np.abs(vr.t_remaining_err))),
                     "rmse_h": float(np.sqrt(np.mean(vr.t_remaining_err**2))),
                     "max_err_h": float(np.max(np.abs(vr.t_remaining_err)))}
                    for vr in results]
        (out / "loo_results.json").write_text(json.dumps(summary, indent=2))
    print(f"\nValidation: {len(results)} folds")


def cmd_demo(args):
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    mp = Path(args.model_json) if args.model_json else None
    if mp and mp.exists():
        curves = generate_synthetic_curves(mp)
    else:
        default = {"statistics": {
            "total_duration_hours": {"mean":19.3,"std":1.0,"min":17.7,"max":21.0},
            "phase1_hours": {"mean":8.0,"std":0.5,"min":7.0,"max":9.0},
            "T_cold_baseline": {"mean":4.7,"std":1.5,"min":4.0,"max":9.0},
            "T_warm_baseline": {"mean":87.0,"std":6.0,"min":78.0,"max":98.0},
        }}
        tmp = out / "_tmp.json"; tmp.write_text(json.dumps(default))
        curves = generate_synthetic_curves(tmp); tmp.unlink()

    curves = prepare_all(curves)
    model = build_ensemble(curves)
    save_model(model, out)
    plot_ensemble(model, out / "ensemble_overview.png")

    print("\n" + "=" * 60 + "\nDEMO PREDICTIONS\n" + "=" * 60)
    demos = [
        ("early_2h", 200.0, 260.0, 2.0),
        ("phase1_mid", 100.0, 200.0, 5.0),
        ("50K_crossing", 50.0, 140.0, 8.0),
        ("S_bend_30K", 30.0, 110.0, 12.0),
        ("phase2_10K", 10.0, 95.0, 16.0),
        ("near_end_5K", 5.0, 88.0, 18.0),
    ]
    for label, Tc, Tw, t_el in demos:
        pred = predict(model, Tc, Tw, t_el)
        h, m = int(pred.t_remaining_hours), int((pred.t_remaining_hours % 1) * 60)
        print(f"\n  {label}: Tc={Tc:.0f}K, Tw={Tw:.0f}K, t={t_el:.1f}h")
        print(f"    -> {h}h{m:02d}m left (p={pred.progress:.1%}, {pred.phase})")
        plot_prediction(model, pred, Tc, Tw, t_el, out / f"pred_{label}.png")

    print("\n" + "=" * 60 + "\nLOO VALIDATION\n" + "=" * 60)
    val = validate_loo(curves)
    if val:
        plot_validation(val, out / "loo_validation.png")
    print(f"\nDemo complete -> {out}/")


def main():
    parser = argparse.ArgumentParser(description="CryoDAQ Cooldown Predictor")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build"); p.add_argument("--data", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("predict"); p.add_argument("--model", required=True)
    p.add_argument("--T_cold", type=float, required=True); p.add_argument("--T_warm", type=float, required=True)
    p.add_argument("--t_elapsed", type=float, default=0.0); p.add_argument("--output")
    p.add_argument("--rate_cold", type=float, default=None, help="Observed dT_cold/dt [K/h] (negative=cooling)")
    p.add_argument("--rate_warm", type=float, default=None, help="Observed dT_warm/dt [K/h]")
    p = sub.add_parser("validate"); p.add_argument("--data", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("demo"); p.add_argument("--output", default="demo_output")
    p.add_argument("--model-json", dest="model_json")
    p = sub.add_parser("update", help="Add new curve to existing model")
    p.add_argument("--model", required=True, help="Model directory")
    p.add_argument("--curve", required=True, help="New cooldown JSON file")
    p.add_argument("--force", action="store_true", help="Skip quality gate")

    args = parser.parse_args()
    {"build": cmd_build, "predict": cmd_predict, "validate": cmd_validate,
     "demo": cmd_demo, "update": cmd_update}[args.command](args)


if __name__ == "__main__":
    main()
