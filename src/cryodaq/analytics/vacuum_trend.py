"""VacuumTrendPredictor — экстраполяция P(t) при откачке.

Все фиты выполняются в координатах (t, log₁₀(P)).
Три модели: экспоненциальная, степенная, комбинированная.
Выбор лучшей по BIC (Bayesian Information Criterion).
"""

from __future__ import annotations

import logging
import math
import threading
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
    model_type: str  # "exponential" | "power_law" | "combined"
    params: dict[str, float]
    bic: float
    r_squared: float  # on log₁₀(P)
    residual_std: float  # σ of residuals in log₁₀(mbar)
    predict: Callable[[np.ndarray], np.ndarray]  # t_array -> log10P_array
    n_params: int = 3


@dataclass
class VacuumPrediction:
    model_type: str  # best model or "insufficient_data"
    p_ultimate_mbar: float  # estimated ultimate pressure
    eta_targets: dict[str, float | None]  # {target_str: ETA_seconds or None}
    trend: str  # "pumping_down"|"stable"|"rising"|"anomaly"
    confidence: float  # R² of best fit (0-1)
    residual_std: float  # σ of residuals (log₁₀)
    fit_params: dict[str, Any]  # for debugging
    extrapolation_t: list[float] = field(default_factory=list)
    extrapolation_logP: list[float] = field(default_factory=list)
    # Predicted pressure at fixed horizons, {"1": mbar, "3": mbar, ...} keyed
    # by hours ahead. An ETA answers "when do we reach X", which says nothing
    # when X is unreachable; this answers "where will we be", which is always
    # defined and is what an operator reads to decide whether to wait.
    horizon_forecast: dict[str, float] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Model functions (all operate on log₁₀(P))
# ---------------------------------------------------------------------------


# Lower bound shared by every curve_fit call below for the fitted
# log10(ultimate pressure). A result resting on it means the window does not
# constrain the asymptote at all, so the value carries no information.
# How much better another model must fit before it may displace the outgassing
# description: it has to bring the residual σ down to this fraction of the
# outgassing fit's. Scale-free, unlike a BIC margin.
_DECISIVE_RESIDUAL_RATIO = 2.0

# log10 of the lowest pressure any gauge on this stand can report. A fitted
# floor below it carries no information about the system's real limit.
_LOG_P_ULT_UNMEASURABLE = -5.0

_LOG_P_ULT_MIN = -20.0
_LOG_P_ULT_BOUND_EPS = 0.05


def _exponential_model(t: np.ndarray, log_p_ult: float, A: float, tau: float) -> np.ndarray:
    """log₁₀(P(t)) = log₁₀(P_ult) + A * exp(-t/τ)"""
    return log_p_ult + A * np.exp(-t / tau)


def _power_law_model(t: np.ndarray, log_p_ult: float, B: float, alpha: float) -> np.ndarray:
    """log₁₀(P(t)) = log₁₀(P_ult) + B * (t/t₀)^(-α), t₀=1s"""
    # Avoid division by zero: clamp t to minimum 1.0
    t_safe = np.maximum(t, 1.0)
    return log_p_ult + B * t_safe ** (-alpha)


# Points handed to curve_fit. A pump-down is a smooth curve over hours: past a
# couple of thousand samples the extra points buy no accuracy and cost time
# linearly, and every second of that time is a second the engine is not
# acquiring. Six hours of 2 s samples is ~10 000 points and fitted in 33 s;
# thinned to this it fits in a fraction of a second.
_MAX_FIT_POINTS = 1500
_COMBINED_MAX_EVALUATIONS = 2000


def _thin_for_fitting(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    """Evenly thin a sample series, always keeping the first and last point."""
    count = len(points)
    if count <= limit:
        return points
    stride = count / float(limit)
    thinned = [points[int(index * stride)] for index in range(limit)]
    if thinned[-1] is not points[-1]:
        thinned[-1] = points[-1]
    return thinned


def _format_hours(hours: float) -> str:
    """Horizon label: whole hours stay whole ("1", "48"), others keep a decimal."""
    return str(int(hours)) if float(hours).is_integer() else f"{hours:g}"


def _outgassing_model(t: np.ndarray, log_p_ult: float, log_B: float, alpha: float) -> np.ndarray:
    """log₁₀(P(t)) for P(t) = P_ult + B·t^(-α), t measured from pump start.

    The standard description of a pump-down once the chamber volume is empty:
    pressure is set by the gas load the pump has to remove, P = Q(t)/S, and
    surface outgassing decays algebraically, Q ∝ t^(-α) with α ≈ 1 for water
    desorption. P_ult is the floor the system settles on — real leaks plus the
    pump's own limit.

    Distinct from ``_power_law_model``, which decays log₁₀(P) as a power of t
    rather than P itself, and so cannot produce the straight line on log-log
    axes that an outgassing-limited pump-down actually traces. Measured on a
    real 12 h pump-down, this form fits the outgassing tail at R² = 0.9996 with
    α = 1.2, against R² = 0.75 for the other.
    """
    t_safe = np.maximum(t, 1.0)
    return np.log10(np.power(10.0, log_p_ult) + np.power(10.0, log_B) * t_safe ** (-alpha))


def _combined_model(
    t: np.ndarray,
    log_p_ult: float,
    A: float,
    tau: float,
    B: float,
    alpha: float,
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
    ss = float(np.sum(residuals**2))
    sigma_sq = ss / n
    if sigma_sq <= 0:
        # Perfect fit (residuals ≈ 0): clamp to a large finite floor instead of
        # -inf so the +k*ln(n) complexity penalty still discriminates models and
        # an overfit high-param fit cannot auto-win selection (min over BIC).
        return -1e9 + k * math.log(n)
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
        # Pressure below which the chamber is unambiguously being pumped, used
        # to timestamp the start of the pump-down.
        self.pump_start_mbar: float = cfg.get("pump_start_mbar", 900.0)
        self.eta_horizon_s: float = cfg.get("eta_horizon_s", 14 * 24 * 3600.0)
        raw_horizons = cfg.get("forecast_horizons_h", [1, 3, 6, 12, 24, 48])
        self.forecast_horizons_h: list[float] = [
            float(h) for h in raw_horizons if isinstance(h, (int, float)) and not isinstance(h, bool) and h > 0
        ]
        # Wall-clock start of the pump-down. The power-law term is only
        # meaningful measured from it: P ∝ (t - t_start)^-α describes surface
        # outgassing decaying since pumping began, and re-anchoring that origin
        # to the start of a sliding fit window (which is what happens if the
        # window's own t0 is used) makes the exponent unidentifiable. Measured
        # on a real 12 h pump-down: window-anchored fitting drove α onto its
        # lower bound (0.01) with R²=0.75, while anchoring to the true start
        # recovered α≈1.2 at R²=0.9996.
        self._t_ref: float | None = None
        # Whether this instance has actually watched the chamber come down from
        # near atmosphere. Without it, "first reading below the threshold"
        # would anchor the pump-down to process start — an engine restarted
        # mid-run sees 0.3 mbar as its first sample and would date the
        # pump-down from the restart, making α meaningless. A start that was
        # not witnessed has to be supplied from the archive instead.
        self._observed_pump_start: bool = False
        # push() runs on the event loop; update() now runs in a worker thread
        # so a slow fit cannot stall acquisition. That makes the sample buffer
        # genuinely shared, and taking a list() of a deque while another thread
        # appends to it raises "deque mutated during iteration". The lock is
        # held only to copy the samples out — never across the fitting itself,
        # which is the whole point of moving it off the loop.
        self._buffer_lock = threading.Lock()

        maxlen = max(1000, int(self.window_s * 10) + 200)
        self._buffer: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._prediction: VacuumPrediction | None = None
        self._last_update_ts: float = 0.0

    def push(self, timestamp: float, pressure_mbar: float) -> None:
        """Add a pressure reading. Rejects P <= 0 (log₁₀ undefined) and
        non-finite values (NaN/inf).

        NaN-доктрина: validity is decided at the Reading boundary (engine
        _vacuum_trend_feed gates on reading.is_usable()). push() is a
        status-less float API, so both guards stay locally: `P <= 0` is the
        MORE-restrictive log₁₀ DOMAIN guard (stays regardless of doctrine);
        the finite check is fail-closed defense-in-depth for any caller that
        bypasses the boundary — a NaN would pass the `<= 0` guard (NaN
        comparisons are False), then log10(NaN) poisons the buffer and kills
        predictions until it ages out (ME-14 / D-C14)."""
        if not math.isfinite(pressure_mbar) or pressure_mbar <= 0:
            return
        log_p = math.log10(pressure_mbar)
        if pressure_mbar >= self.pump_start_mbar:
            self._observed_pump_start = True
        elif self._t_ref is None and self._observed_pump_start:
            # A genuine downward crossing of the threshold.
            self._t_ref = timestamp
        with self._buffer_lock:
            self._buffer.append((timestamp, log_p))
            # Trim old points
            cutoff = timestamp - self.window_s
            while self._buffer and self._buffer[0][0] < cutoff:
                self._buffer.popleft()

    def set_pump_start(self, timestamp: float) -> None:
        """Supply the pump-down start this instance did not witness.

        Used when the process starts mid-run: the start is recovered from the
        archive so the outgassing exponent is measured against the real origin.
        A start observed live always wins, since it is directly evidenced.
        """
        if self._observed_pump_start:
            return
        if not math.isfinite(timestamp) or timestamp <= 0.0:
            return
        self._t_ref = float(timestamp)

    def update(self) -> None:
        """Recompute prediction from current buffer."""
        with self._buffer_lock:
            samples = list(self._buffer)
        if len(samples) < self.min_points:
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

        points = _thin_for_fitting(samples, _MAX_FIT_POINTS)
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
        # Only meaningful once the start of the pump-down is known: the
        # exponent is defined against that origin, not against the start of
        # whatever window happens to be in the buffer.
        if self._t_ref is not None:
            outgas_fit = self._fit_outgassing(t_arr, logP_arr, offset=float(t0 - self._t_ref))
            if outgas_fit is not None:
                fits.append(outgas_fit)
        if len(samples) >= self.min_points_combined:
            comb_fit = self._fit_combined(
                t_arr,
                logP_arr,
                offset=(float(t0 - self._t_ref) if self._t_ref is not None else 0.0),
            )
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

        # Pressure at each fixed horizon, from the same fitted curve that
        # produces the extrapolation used for plotting.
        horizon_forecast: dict[str, float] = {}
        for hours in self.forecast_horizons_h:
            predicted = float(best.predict(np.array([float(t_arr[-1]) + hours * 3600.0]))[0])
            if math.isfinite(predicted):
                horizon_forecast[_format_hours(hours)] = float(10.0**predicted)

        # Extrapolation curve
        t_max = float(t_arr[-1])
        horizon = t_max + self.window_s * self.extrapolation_factor
        t_extrap = np.linspace(max(t_max, 1.0), horizon, 200)
        logP_extrap = best.predict(t_extrap)

        # log_p_ult is a FITTED parameter bounded to [-20, 5]. When the data
        # window shows no asymptote yet — still on the steep part of the
        # pump-down — the optimizer simply drives it to the lower bound and
        # the reported "ultimate pressure" comes out as 1e-20 mbar, which is
        # not a prediction but the floor of the search space. Reporting that
        # as a physical base pressure is worse than reporting nothing: it is
        # a confident-looking number with no information in it.
        #
        # Treat a parameter resting on its bound as unidentified.
        log_p_ult = best.params.get("log_p_ult", float("nan"))
        # A floor below anything the gauge can read is not a measurement of the
        # system's limit, it is the fit saying "no floor is evident yet" — the
        # outgassing term still dominates everywhere in the observed window. On
        # this stand the Pirani stops at 1e-4 mbar, and reporting a fitted
        # 3e-12 mbar "предел откачки" to an operator is a confident-looking
        # number about a pressure nothing here can see.
        if math.isfinite(log_p_ult) and log_p_ult < _LOG_P_ULT_UNMEASURABLE:
            logger.debug(
                "Vacuum fit %s: fitted floor %.3g mbar is below the measurable range; "
                "reporting the ultimate pressure as unidentified",
                best.model_type,
                10.0**log_p_ult,
            )
            log_p_ult = float("nan")
        if math.isfinite(log_p_ult) and log_p_ult <= _LOG_P_ULT_MIN + _LOG_P_ULT_BOUND_EPS:
            logger.debug(
                "Vacuum fit %s: log_p_ult rests on its lower bound (%.3f); "
                "ultimate pressure is not identifiable from this window",
                best.model_type,
                log_p_ult,
            )
            p_ult = float("nan")
        else:
            p_ult = 10.0**log_p_ult

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
            horizon_forecast=horizon_forecast,
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
                _exponential_model,
                t,
                logP,
                p0=[log_p_last, A_init, tau_init],
                bounds=([_LOG_P_ULT_MIN, 0, 1], [5, 30, 1e7]),
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
                _power_law_model,
                t,
                logP,
                p0=[log_p_last, B_init, alpha_init],
                bounds=([_LOG_P_ULT_MIN, 0, 0.01], [5, 30, 5.0]),
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

    def _fit_outgassing(self, t: np.ndarray, logP: np.ndarray, *, offset: float) -> FitResult | None:
        """Fit P = P_ult + B·t^(-α) with t measured from the pump-down start.

        ``offset`` is (window start - pump start) in seconds. The fit runs in
        absolute pump-down time, while ``predict`` keeps taking window-relative
        time like every other model, so the ETA search and the extrapolation
        curve need no knowledge of the anchoring.
        """
        from scipy.optimize import curve_fit

        t_abs = t + offset
        if float(t_abs[0]) <= 0.0:
            return None
        try:
            # Seed from a straight-line fit on log-log axes: that is exactly
            # what this model reduces to while the outgassing term dominates,
            # so it lands the optimizer in the right basin.
            slope, intercept = np.polyfit(np.log10(np.maximum(t_abs, 1.0)), logP, 1)
            alpha_init = float(min(max(-slope, 0.05), 4.0))
            log_b_init = float(min(max(intercept, -10.0), 30.0))
            log_p_ult_init = float(logP[-1]) - 1.0

            popt, _ = curve_fit(
                _outgassing_model,
                t_abs,
                logP,
                p0=[log_p_ult_init, log_b_init, alpha_init],
                bounds=([_LOG_P_ULT_MIN, -10.0, 0.05], [5.0, 30.0, 4.0]),
                maxfev=10000,
            )
            y_fit = _outgassing_model(t_abs, *popt)
            residuals = logP - y_fit
            return FitResult(
                model_type="outgassing",
                params={"log_p_ult": popt[0], "log_B": popt[1], "alpha": popt[2]},
                bic=_compute_bic(len(t), 3, residuals),
                r_squared=_compute_r_squared(logP, y_fit),
                residual_std=float(np.std(residuals)),
                predict=lambda t_new, q=popt, o=offset: _outgassing_model(t_new + o, *q),
                n_params=3,
            )
        except (RuntimeError, ValueError, TypeError, np.linalg.LinAlgError):
            return None

    def _fit_combined(self, t: np.ndarray, logP: np.ndarray, *, offset: float = 0.0) -> FitResult | None:
        """Fit the exponential + power-law form in pump-down time.

        ``offset`` is (window start - pump start). The power-law term is only
        meaningful measured from the start of the pump-down, exactly as in
        ``_fit_outgassing``; anchored to a sliding window instead, its exponent
        is unidentifiable and the optimizer parks it on a bound, where the term
        contributes flexibility without meaning.
        """
        from scipy.optimize import curve_fit

        t_abs = t + offset
        try:
            log_p_last = float(logP[-1])
            A_init = max(0.5, (float(logP[0]) - log_p_last) / 2)
            B_init = A_init
            tau_init = float(t_abs[-1]) / 4.0
            if tau_init <= 0:
                tau_init = 100.0

            popt, _ = curve_fit(
                _combined_model,
                t_abs,
                logP,
                p0=[log_p_last, A_init, tau_init, B_init, 1.0],
                bounds=([_LOG_P_ULT_MIN, 0, 1, 0, 0.01], [5, 30, 1e7, 30, 5.0]),
                # Five parameters on a curve the simpler models already
                # describe: this fit routinely fails to converge, and at 10000
                # evaluations it spent 5.6 s of every tick doing so — 94% of
                # the whole update, to return nothing. A fit that is not going
                # to converge should give up cheaply.
                maxfev=_COMBINED_MAX_EVALUATIONS,
            )
            y_fit = _combined_model(t_abs, *popt)
            residuals = logP - y_fit
            return FitResult(
                model_type="combined",
                params={
                    "log_p_ult": popt[0],
                    "A": popt[1],
                    "tau": popt[2],
                    "B": popt[3],
                    "alpha": popt[4],
                },
                bic=_compute_bic(len(t), 5, residuals),
                r_squared=_compute_r_squared(logP, y_fit),
                residual_std=float(np.std(residuals)),
                predict=lambda t_new, p=popt, o=offset: _combined_model(t_new + o, *p),
                n_params=5,
            )
        except (RuntimeError, ValueError, TypeError):
            return None

    def _select_best(self, fits: list[FitResult]) -> FitResult:
        """Lowest BIC, with a physics tie-break the raw criterion cannot make.

        On a pump-down the candidate models fit the observed window almost
        identically while disagreeing entirely about the future. Measured on
        this stand over a 6 h window: the exponential and the outgassing model
        matched the data to the same residual σ (0.00208 decades, R² agreeing
        to the sixth decimal), yet one projected a flat 0.162 mbar for ever and
        the other 0.068 mbar within two days.

        BIC separated them by 0.015%, and even that is overstated: it assumes
        independent residuals, while these are 2-second samples of a smooth
        curve and are strongly autocorrelated, so the effective sample size is
        far below the point count and every BIC gap is inflated with it.
        Deciding an operational question on that margin is a coin toss.

        So a decisive margin is required before an asymptotic model may
        override the outgassing description. An asymptote is a claim that the
        pump-down has finished, and while pressure is still falling nothing in
        the data supports it — the flattening a short window shows is exactly
        what a slow power-law decay looks like close up. Genuine evidence of a
        floor still wins; a rounding error does not.
        """
        best = min(fits, key=lambda f: f.bic)
        if best.model_type == "outgassing":
            return best
        outgassing = next((f for f in fits if f.model_type == "outgassing"), None)
        if outgassing is None:
            return best
        # Compared on residual scale rather than on BIC. BIC's gaps grow with
        # the point count, so any fixed margin means something different after
        # the input is thinned; the ratio of residual σ does not move with n at
        # all. "Decisively better" is a model that roughly halves the residual,
        # not one that trims it by a quarter — over a few hours of a pump-down
        # the asymptotic and outgassing descriptions differ by about that much
        # in-sample while disagreeing entirely about the days ahead.
        if outgassing.residual_std <= best.residual_std * _DECISIVE_RESIDUAL_RATIO:
            return outgassing
        return best

    # -------------------------------------------------------------------
    # ETA
    # -------------------------------------------------------------------

    def _compute_eta(
        self,
        fit: FitResult,
        t_current: float,
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
        self,
        fit: FitResult,
        t_current: float,
        log_target: float,
    ) -> float | None:
        """Binary search for time when predicted log₁₀(P) crosses log_target."""
        # An outgassing-limited pump-down reaches its targets on a scale set by
        # the physics, not by however much history happens to be buffered:
        # measured on this stand, 0.05 mbar was ~40 h away while the fit window
        # was 6 h. Tying the search to a multiple of the window reported
        # "unreachable" for targets the system reaches perfectly well.
        t_lo = t_current
        t_hi = t_current + self.eta_horizon_s

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

        # Rising: sustained positive rate.
        #
        # D-C13: the sustained check must not be defeated by sample rate. The
        # recent n_rate-point window is capped at 30 points, so at high sample
        # rates it spans far less than rising_sustained_s (e.g. 30 pts @ 10 Hz
        # ≈ 3 s ≪ 60 s), making "rising" unreachable. Confirm the rise is
        # genuinely sustained by measuring the rate over a time-based lookback
        # of rising_sustained_s (independent of the recent rate window used for
        # the other branches, which is left unchanged).
        if d_logP_dt > self.trend_threshold:
            cutoff = float(t[-1]) - self.rising_sustained_s
            idx = int(np.searchsorted(t, cutoff, side="left"))
            span = float(t[-1] - t[idx])
            # 0.99 tolerance absorbs sampling granularity at the window edge.
            if idx < n - 1 and span >= self.rising_sustained_s * 0.99:
                sustained_rate = float(logP[-1] - logP[idx]) / span
                if sustained_rate > self.trend_threshold:
                    return "rising"

        # Anomaly: recent residuals >> baseline σ (sudden deviation from model)
        # Only check when NOT in a sustained rising trend.
        if n > 20:
            n_baseline = max(10, int(n * 0.7))
            baseline_sigma = float(np.std(residuals[:n_baseline]))
            if baseline_sigma > 0:
                recent_residuals = residuals[-min(30, n) :]
                if float(np.mean(recent_residuals)) > self.anomaly_sigma * baseline_sigma:
                    return "anomaly"

        # Pumping down
        if d_logP_dt < -self.trend_threshold:
            return "pumping_down"

        return "stable"
