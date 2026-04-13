"""VacuumTrendPredictor — экстраполяция P(t) при откачке.

Все фиты выполняются в координатах (t, log₁₀(P)).
Три модели: экспоненциальная, степенная, комбинированная.
Выбор лучшей по BIC (Bayesian Information Criterion).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FitResult:
    model_type: str          # "exponential" | "power_law" | "combined"
    params: dict[str, float]
    bic: float
    r_squared: float         # on log₁₀(P)
    residual_std: float      # σ of residuals in log₁₀(mbar)
    predict: Callable[[np.ndarray], np.ndarray]  # t_array -> log10P_array
    n_params: int = 3


@dataclass
class VacuumPrediction:
    model_type: str                        # best model or "insufficient_data"
    p_ultimate_mbar: float                 # estimated ultimate pressure
    eta_targets: dict[str, float | None]   # {target_str: ETA_seconds or None}
    trend: str                             # "pumping_down"|"stable"|"rising"|"anomaly"
    confidence: float                      # R² of best fit (0-1)
    residual_std: float                    # σ of residuals (log₁₀)
    fit_params: dict[str, Any]             # for debugging
    extrapolation_t: list[float] = field(default_factory=list)
    extrapolation_logP: list[float] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Model functions (all operate on log₁₀(P))
# ---------------------------------------------------------------------------

def _exponential_model(t: np.ndarray, log_p_ult: float, A: float, tau: float) -> np.ndarray:
    """log₁₀(P(t)) = log₁₀(P_ult) + A * exp(-t/τ)"""
    return log_p_ult + A * np.exp(-t / tau)


def _power_law_model(t: np.ndarray, log_p_ult: float, B: float, alpha: float) -> np.ndarray:
    """log₁₀(P(t)) = log₁₀(P_ult) + B * (t/t₀)^(-α), t₀=1s"""
    # Avoid division by zero: clamp t to minimum 1.0
    t_safe = np.maximum(t, 1.0)
    return log_p_ult + B * t_safe ** (-alpha)


def _combined_model(
    t: np.ndarray,
    log_p_ult: float,
    A: float, tau: float,
    B: float, alpha: float,
) -> np.ndarray:
    """log₁₀(P(t)) = log₁₀(P_ult) + A*exp(-t/τ) + B*(t/t₀)^(-α)"""
    t_safe = np.maximum(t, 1.0)
    return log_p_ult + A * np.exp(-t / tau) + B * t_safe ** (-alpha)


# ---------------------------------------------------------------------------
# BIC computation
# ---------------------------------------------------------------------------

def _compute_bic(n: int, k: int, residuals: np.ndarray) -> float:
    """Bayesian Information Criterion: BIC = n*ln(σ²) + k*ln(n)."""
    if n <= k:
        return float("inf")
    ss = float(np.sum(residuals ** 2))
    sigma_sq = ss / n
    if sigma_sq <= 0:
        return float("-inf")
    return n * math.log(sigma_sq) + k * math.log(n)


def _compute_r_squared(y: np.ndarray, y_fit: np.ndarray) -> float:
    ss_res = float(np.sum((y - y_fit) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1.0 - ss_res / ss_tot


# ---------------------------------------------------------------------------
# VacuumTrendPredictor
# ---------------------------------------------------------------------------

class VacuumTrendPredictor:
    """Экстраполяция P(t) при откачке. Read-only consumer."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.window_s: float = cfg.get("window_s", 3600)
        self.targets: list[float] = cfg.get("targets_mbar", [1e-4, 1e-5, 1e-6])
        self.update_interval_s: float = cfg.get("update_interval_s", 30)
        self.min_points: int = cfg.get("min_points", 60)
        self.anomaly_sigma: float = cfg.get("anomaly_threshold_sigma", 3.0)
        self.rising_sustained_s: float = cfg.get("rising_sustained_s", 60)
        self.trend_threshold: float = cfg.get("trend_threshold_log10_per_s", 1e-4)
        self.extrapolation_factor: float = cfg.get("extrapolation_horizon_factor", 2.0)
        self.min_points_combined: int = cfg.get("min_points_combined", 200)

        maxlen = max(1000, int(self.window_s * 10) + 200)
        self._buffer: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._prediction: VacuumPrediction | None = None
        self._last_update_ts: float = 0.0

    def push(self, timestamp: float, pressure_mbar: float) -> None:
        """Add a pressure reading. Rejects P <= 0 (log₁₀ undefined)."""
        if pressure_mbar <= 0:
            return
        log_p = math.log10(pressure_mbar)
        self._buffer.append((timestamp, log_p))
        # Trim old points
        cutoff = timestamp - self.window_s
        while self._buffer and self._buffer[0][0] < cutoff:
            self._buffer.popleft()

    def update(self) -> None:
        """Recompute prediction from current buffer."""
        if len(self._buffer) < self.min_points:
            self._prediction = VacuumPrediction(
                model_type="insufficient_data",
                p_ultimate_mbar=float("nan"),
                eta_targets={},
                trend="insufficient_data",
                confidence=0.0,
                residual_std=float("nan"),
                fit_params={},
            )
            return

        points = list(self._buffer)
        t0 = points[0][0]
        t_arr = np.array([t - t0 for t, _ in points])
        logP_arr = np.array([lp for _, lp in points])

        # Fit all models
        fits: list[FitResult] = []
        exp_fit = self._fit_exponential(t_arr, logP_arr)
        if exp_fit is not None:
            fits.append(exp_fit)
        plaw_fit = self._fit_power_law(t_arr, logP_arr)
        if plaw_fit is not None:
            fits.append(plaw_fit)
        if len(points) >= self.min_points_combined:
            comb_fit = self._fit_combined(t_arr, logP_arr)
            if comb_fit is not None:
                fits.append(comb_fit)

        if not fits:
            self._prediction = VacuumPrediction(
                model_type="insufficient_data",
                p_ultimate_mbar=float("nan"),
                eta_targets={},
                trend="insufficient_data",
                confidence=0.0,
                residual_std=float("nan"),
                fit_params={},
            )
            return

        best = self._select_best(fits)

        # ETA computation
        eta_targets = self._compute_eta(best, t_arr[-1])

        # Trend classification
        residuals = logP_arr - best.predict(t_arr)
        trend = self._classify_trend(t_arr, logP_arr, residuals)

        # Extrapolation curve
        t_max = float(t_arr[-1])
        horizon = t_max + self.window_s * self.extrapolation_factor
        t_extrap = np.linspace(max(t_max, 1.0), horizon, 200)
        logP_extrap = best.predict(t_extrap)

        p_ult = 10.0 ** best.params.get("log_p_ult", float("nan"))

        self._prediction = VacuumPrediction(
            model_type=best.model_type,
            p_ultimate_mbar=p_ult,
            eta_targets=eta_targets,
            trend=trend,
            confidence=best.r_squared,
            residual_std=best.residual_std,
            fit_params=dict(best.params),
            extrapolation_t=[float(x) for x in t_extrap],
            extrapolation_logP=[float(x) for x in logP_extrap],
        )

    def get_prediction(self) -> VacuumPrediction | None:
        return self._prediction

    # -------------------------------------------------------------------
    # Fitting
    # -------------------------------------------------------------------

    def _fit_exponential(self, t: np.ndarray, logP: np.ndarray) -> FitResult | None:
        from scipy.optimize import curve_fit

        try:
            # Initial guess: P_ult from last points, A from range, tau from half-time
            log_p_last = float(logP[-1])
            log_p_first = float(logP[0])
            A_init = log_p_first - log_p_last
            if A_init <= 0:
                A_init = 1.0
            tau_init = float(t[-1]) / 3.0
            if tau_init <= 0:
                tau_init = 100.0

            popt, _ = curve_fit(
                _exponential_model, t, logP,
                p0=[log_p_last, A_init, tau_init],
                bounds=([-20, 0, 1], [5, 30, 1e7]),
                maxfev=5000,
            )
            y_fit = _exponential_model(t, *popt)
            residuals = logP - y_fit
            return FitResult(
                model_type="exponential",
                params={"log_p_ult": popt[0], "A": popt[1], "tau": popt[2]},
                bic=_compute_bic(len(t), 3, residuals),
                r_squared=_compute_r_squared(logP, y_fit),
                residual_std=float(np.std(residuals)),
                predict=lambda t_new, p=popt: _exponential_model(t_new, *p),
                n_params=3,
            )
        except (RuntimeError, ValueError, TypeError):
            return None

    def _fit_power_law(self, t: np.ndarray, logP: np.ndarray) -> FitResult | None:
        from scipy.optimize import curve_fit

        try:
            log_p_last = float(logP[-1])
            B_init = float(logP[0]) - log_p_last
            if B_init <= 0:
                B_init = 1.0
            alpha_init = 1.0

            popt, _ = curve_fit(
                _power_law_model, t, logP,
                p0=[log_p_last, B_init, alpha_init],
                bounds=([-20, 0, 0.01], [5, 30, 5.0]),
                maxfev=5000,
            )
            y_fit = _power_law_model(t, *popt)
            residuals = logP - y_fit
            return FitResult(
                model_type="power_law",
                params={"log_p_ult": popt[0], "B": popt[1], "alpha": popt[2]},
                bic=_compute_bic(len(t), 3, residuals),
                r_squared=_compute_r_squared(logP, y_fit),
                residual_std=float(np.std(residuals)),
                predict=lambda t_new, p=popt: _power_law_model(t_new, *p),
                n_params=3,
            )
        except (RuntimeError, ValueError, TypeError):
            return None

    def _fit_combined(self, t: np.ndarray, logP: np.ndarray) -> FitResult | None:
        from scipy.optimize import curve_fit

        try:
            log_p_last = float(logP[-1])
            A_init = max(0.5, (float(logP[0]) - log_p_last) / 2)
            B_init = A_init
            tau_init = float(t[-1]) / 4.0
            if tau_init <= 0:
                tau_init = 100.0

            popt, _ = curve_fit(
                _combined_model, t, logP,
                p0=[log_p_last, A_init, tau_init, B_init, 1.0],
                bounds=([-20, 0, 1, 0, 0.01], [5, 30, 1e7, 30, 5.0]),
                maxfev=10000,
            )
            y_fit = _combined_model(t, *popt)
            residuals = logP - y_fit
            return FitResult(
                model_type="combined",
                params={
                    "log_p_ult": popt[0], "A": popt[1], "tau": popt[2],
                    "B": popt[3], "alpha": popt[4],
                },
                bic=_compute_bic(len(t), 5, residuals),
                r_squared=_compute_r_squared(logP, y_fit),
                residual_std=float(np.std(residuals)),
                predict=lambda t_new, p=popt: _combined_model(t_new, *p),
                n_params=5,
            )
        except (RuntimeError, ValueError, TypeError):
            return None

    def _select_best(self, fits: list[FitResult]) -> FitResult:
        """Select model with lowest BIC."""
        return min(fits, key=lambda f: f.bic)

    # -------------------------------------------------------------------
    # ETA
    # -------------------------------------------------------------------

    def _compute_eta(
        self, fit: FitResult, t_current: float,
    ) -> dict[str, float | None]:
        """Compute ETA to each target pressure.

        Returns dict with target as string key → ETA in seconds from now,
        or None if unreachable, or 0.0 if already reached.
        """
        result: dict[str, float | None] = {}
        log_p_ult = fit.params.get("log_p_ult", float("nan"))
        if not math.isfinite(log_p_ult):
            for target in self.targets:
                result[str(target)] = None
            return result

        # Current predicted pressure
        logP_now = float(fit.predict(np.array([t_current]))[0])

        for target in self.targets:
            log_target = math.log10(target)
            key = str(target)

            # Already reached?
            if logP_now <= log_target:
                result[key] = 0.0
                continue

            # Unreachable: ultimate pressure > target
            if log_p_ult > log_target:
                result[key] = None
                continue

            # Binary search for ETA
            eta = self._binary_search_eta(fit, t_current, log_target)
            result[key] = eta

        return result

    def _binary_search_eta(
        self, fit: FitResult, t_current: float, log_target: float,
    ) -> float | None:
        """Binary search for time when predicted log₁₀(P) crosses log_target."""
        # Search up to 10× window into the future
        t_lo = t_current
        t_hi = t_current + self.window_s * 10

        logP_hi = float(fit.predict(np.array([t_hi]))[0])
        if logP_hi > log_target:
            return None  # won't reach in search horizon

        for _ in range(60):  # ~60 iterations for double precision
            t_mid = (t_lo + t_hi) / 2.0
            logP_mid = float(fit.predict(np.array([t_mid]))[0])
            if logP_mid > log_target:
                t_lo = t_mid
            else:
                t_hi = t_mid
            if t_hi - t_lo < 1.0:
                break

        return t_hi - t_current

    # -------------------------------------------------------------------
    # Trend classification
    # -------------------------------------------------------------------

    def _classify_trend(
        self,
        t: np.ndarray,
        logP: np.ndarray,
        residuals: np.ndarray,
    ) -> str:
        """Classify current vacuum trend.

        Priority: rising (sustained) > anomaly (sudden jump) > pumping_down > stable.
        """
        n = len(residuals)

        # Rate of change from recent raw data
        n_rate = min(30, n)
        if n_rate < 5:
            return "pumping_down"

        t_recent = t[-n_rate:]
        logP_recent = logP[-n_rate:]
        dt = float(t_recent[-1] - t_recent[0])
        if dt > 0:
            d_logP_dt = float(logP_recent[-1] - logP_recent[0]) / dt
        else:
            d_logP_dt = 0.0

        # Rising: sustained positive rate
        if d_logP_dt > self.trend_threshold:
            span = float(t[-1] - t[-n_rate])
            if span >= self.rising_sustained_s:
                return "rising"

        # Anomaly: recent residuals >> baseline σ (sudden deviation from model)
        # Only check when NOT in a sustained rising trend.
        if n > 20:
            n_baseline = max(10, int(n * 0.7))
            baseline_sigma = float(np.std(residuals[:n_baseline]))
            if baseline_sigma > 0:
                recent_residuals = residuals[-min(30, n):]
                if float(np.mean(recent_residuals)) > self.anomaly_sigma * baseline_sigma:
                    return "anomaly"

        # Pumping down
        if d_logP_dt < -self.trend_threshold:
            return "pumping_down"

        return "stable"
