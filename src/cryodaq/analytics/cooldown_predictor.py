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
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import stat
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter

from cryodaq.instance_lock import release_lock_exact, try_acquire_lock

logger = logging.getLogger(__name__)


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
T_WARM_START = 295.0

# Floors derived at model-build time from reference curve minima.
# Fallbacks used when no curves are available (empty model, first boot).
# Previous hardcoded values (4.0 K, 85.0 K) silently lost the
# quasi-stationary regime from ~4 K to the actual 2nd-stage base (~2.9 K).
T_COLD_END_FALLBACK = 2.5  # K — below typical 2-stage GM floor
T_WARM_END_FALLBACK = 75.0  # K — 1st-stage floor with margin

# Module-level aliases kept for backward compatibility with external callers.
T_COLD_END = T_COLD_END_FALLBACK
T_WARM_END = T_WARM_END_FALLBACK

_MODEL_UPDATE_LOCK = threading.RLock()
_MODEL_UPDATE_LOCK_NAME = ".predictor-model.lock"
_MODEL_UPDATE_LOCK_TIMEOUT_S = 30.0


@contextmanager
def _model_update_guard(model_dir: Path) -> Iterator[None]:
    """Serialize model transactions across threads and engine/CLI processes."""

    with _MODEL_UPDATE_LOCK:
        deadline = time.monotonic() + _MODEL_UPDATE_LOCK_TIMEOUT_S
        descriptor: int | None = None
        while descriptor is None:
            descriptor = try_acquire_lock(
                _MODEL_UPDATE_LOCK_NAME,
                lock_dir=model_dir,
            )
            if descriptor is not None:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the predictor model update owner")
            time.sleep(0.01)
        try:
            yield
        finally:
            release_lock_exact(
                descriptor,
                _MODEL_UPDATE_LOCK_NAME,
                lock_dir=model_dir,
            )


def _curve_arrays(
    t_hours: object,
    T_cold: object,
    T_warm: object,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return one exact, bounded-shape curve payload or fail closed."""

    t_length = _bounded_vector_length(t_hours, field_name="t_hours")
    cold_length = _bounded_vector_length(T_cold, field_name="T_cold")
    warm_length = _bounded_vector_length(T_warm, field_name="T_warm")
    if t_length == 0 or t_length != cold_length or t_length != warm_length:
        raise ValueError("cooldown curve arrays must have one equal non-zero length")
    t_h = np.asarray(t_hours, dtype=np.float64)
    tc = np.asarray(T_cold, dtype=np.float64)
    tw = np.asarray(T_warm, dtype=np.float64)
    if t_h.ndim != 1 or tc.ndim != 1 or tw.ndim != 1:
        raise ValueError("cooldown curve arrays must be one-dimensional")
    if not np.all(np.isfinite(t_h)) or not np.all(np.isfinite(tc)):
        raise ValueError("cooldown time and cold-temperature arrays must be finite")
    if np.any(np.isinf(tw)):
        raise ValueError("cooldown warm-temperature array cannot contain infinity")
    if t_h[0] != 0.0 or np.signbit(t_h[0]):
        raise ValueError("cooldown time must be anchored at exact 0.0 hours")
    if len(t_h) > 1 and not np.all(np.diff(t_h) > 0.0):
        raise ValueError("cooldown time must be strictly increasing")
    return t_h, tc, tw


def _canonical_float(value: np.float64) -> str:
    scalar = float(value)
    if math.isnan(scalar):
        return "nan"
    return scalar.hex()


def cooldown_curve_source_digest(
    t_hours: object,
    T_cold: object,
    T_warm: object,
) -> str:
    """Bind a model curve to its canonical numeric payload.

    Decimal JSON spellings and ndarray dtypes cannot change this identity;
    every finite value is represented by its exact IEEE-754 hexadecimal form
    and warm-channel NaNs use one canonical marker.
    """

    t_h, tc, tw = _curve_arrays(t_hours, T_cold, T_warm)
    canonical = {
        "schema": 1,
        "t_hours": [_canonical_float(value) for value in t_h],
        "T_cold": [_canonical_float(value) for value in tc],
        "T_warm": [_canonical_float(value) for value in tw],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _verified_curve_source_digest(
    supplied: object,
    t_hours: object,
    T_cold: object,
    T_warm: object,
) -> str:
    computed = cooldown_curve_source_digest(t_hours, T_cold, T_warm)
    if supplied is None or supplied == "":
        return computed
    if type(supplied) is not str or len(supplied) != 64 or any(char not in "0123456789abcdef" for char in supplied):
        raise ValueError("cooldown curve source_digest is invalid")
    if supplied != computed:
        raise ValueError("cooldown curve source_digest does not match its numeric payload")
    return computed


# Adaptive rate-based weighting
RATE_WINDOW_H = 1.5  # compute avg cooling rate over first 1.5h
RATE_MIN_HISTORY_H = 0.5  # need at least 0.5h of data to estimate rate
RATE_WEIGHT_STRENGTH = 2.0  # exponent: higher = sharper preference for similar rates


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
    source_digest: str = ""
    T_cold_smooth: np.ndarray | None = field(default=None, repr=False)
    T_warm_smooth: np.ndarray | None = field(default=None, repr=False)
    progress: np.ndarray | None = field(default=None, repr=False)
    initial_rate_cold: float = 0.0  # K/h, avg dT_cold/dt over first RATE_WINDOW_H
    initial_rate_warm: float = 0.0  # K/h, avg dT_warm/dt over first RATE_WINDOW_H
    _t_of_p: interp1d | None = field(default=None, repr=False)
    _p_of_t: interp1d | None = field(default=None, repr=False)
    _Tc_of_p: interp1d | None = field(default=None, repr=False)
    _Tw_of_p: interp1d | None = field(default=None, repr=False)


_MAX_CURVE_NAME_LENGTH = 255
_MAX_CURVE_DATE_LENGTH = 32
# Capacity is part of the persistent provenance contract. These limits are
# deliberately well above normal CryoDAQ curves (hundreds to low thousands of
# points) while bounding JSON decode and numeric expansion before allocation.
MAX_COOLDOWN_JSON_BYTES = 64 * 1024 * 1024
MAX_COOLDOWN_POINTS_PER_CURVE = 250_000
MAX_COOLDOWN_MODEL_POINTS = 2_000_000
MAX_COOLDOWN_MODEL_CURVES = 100


def _bounded_vector_length(value: object, *, field_name: str) -> int:
    """Preflight one one-dimensional numeric source before ndarray allocation."""

    if isinstance(value, np.ndarray):
        if value.ndim != 1:
            raise ValueError(f"cooldown curve {field_name} must be one-dimensional")
        length = int(value.size)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        length = len(value)
        if length > MAX_COOLDOWN_POINTS_PER_CURVE:
            raise ValueError(f"cooldown curve {field_name} exceeds {MAX_COOLDOWN_POINTS_PER_CURVE} points")
        if any(
            isinstance(item, (Mapping, Sequence, np.ndarray)) and not isinstance(item, (str, bytes, bytearray))
            for item in value
        ):
            raise ValueError(f"cooldown curve {field_name} must be one-dimensional")
    else:
        raise ValueError(f"cooldown curve {field_name} must be a bounded sequence")
    if length > MAX_COOLDOWN_POINTS_PER_CURVE:
        raise ValueError(f"cooldown curve {field_name} exceeds {MAX_COOLDOWN_POINTS_PER_CURVE} points")
    return length


def _require_model_capacity(curves: object) -> None:
    """Bound a persisted ensemble before expanding any curve arrays."""

    if not isinstance(curves, list):
        raise ValueError("predictor model must contain an exact curves list")
    if len(curves) > MAX_COOLDOWN_MODEL_CURVES:
        raise ValueError(f"predictor model exceeds {MAX_COOLDOWN_MODEL_CURVES} curve owners")
    total_points = 0
    for entry in curves:
        if not isinstance(entry, dict):
            raise ValueError("predictor model curve entries must be objects")
        source = entry.get("t_hours")
        if source is None:
            source = entry.get("elapsed_hours")
        total_points += _bounded_vector_length(source, field_name="t_hours")
        if total_points > MAX_COOLDOWN_MODEL_POINTS:
            raise ValueError(f"predictor model exceeds {MAX_COOLDOWN_MODEL_POINTS} aggregate points")


def _bounded_curve_text(
    value: object,
    *,
    field_name: str,
    max_length: int,
    allow_empty: bool,
) -> str:
    """Validate bounded persistent identity text without normalization."""

    if type(value) is not str:
        raise ValueError(f"cooldown curve {field_name} must be an exact string")
    if len(value) > max_length:
        raise ValueError(f"cooldown curve {field_name} exceeds {max_length} characters")
    if not allow_empty and not value:
        raise ValueError(f"cooldown curve {field_name} cannot be empty")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"cooldown curve {field_name} contains unsafe characters")
    return value


def _curve_identity(value: object) -> str:
    return _bounded_curve_text(
        value,
        field_name="name",
        max_length=_MAX_CURVE_NAME_LENGTH,
        allow_empty=False,
    )


def _curve_date(value: object) -> str:
    text = _bounded_curve_text(
        value,
        field_name="date",
        max_length=_MAX_CURVE_DATE_LENGTH,
        allow_empty=True,
    )
    if text and (
        not text.isascii()
        or len(text) != 10
        or text[4] != "-"
        or text[7] != "-"
        or not (text[:4] + text[5:7] + text[8:]).isdigit()
    ):
        raise ValueError("cooldown curve date must use bounded YYYY-MM-DD syntax")
    if text:
        try:
            parsed = _date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("cooldown curve date must be a real calendar date") from exc
        if parsed.isoformat() != text:
            raise ValueError("cooldown curve date must use canonical YYYY-MM-DD syntax")
    return text


def _curve_summary(
    t_hours: object,
    T_cold: object,
    T_warm: object,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, float, float]:
    """Derive every behavior-affecting summary from one validated payload."""

    t_h, tc, tw = _curve_arrays(t_hours, T_cold, T_warm)
    duration = float(t_h[-1])
    crossings = np.flatnonzero(tc < T_PHASE_BOUNDARY)
    phase1 = float(t_h[int(crossings[0])]) if crossings.size else duration
    phase2 = duration - phase1
    cold_final = float(np.min(tc))
    finite_warm = tw[np.isfinite(tw)]
    warm_final = float(np.min(finite_warm)) if finite_warm.size else 0.0
    return t_h, tc, tw, duration, phase1, phase2, cold_final, warm_final


def _reconcile_summary_value(payload: Mapping[str, object], key: str, derived: float) -> float:
    if key not in payload:
        return derived
    supplied = payload[key]
    if type(supplied) not in (int, float) or not math.isfinite(float(supplied)):
        raise ValueError(f"cooldown curve {key} must be a finite number")
    if float(supplied) != derived:
        raise ValueError(f"cooldown curve {key} does not match its numeric payload")
    return derived


def _reference_curve_from_payload(
    payload: Mapping[str, object],
    *,
    default_name: str,
) -> ReferenceCurve:
    """Construct a curve whose summaries and digest share one array provenance."""

    t_h_raw = payload.get("t_hours")
    if t_h_raw is None:
        t_h_raw = payload.get("elapsed_hours")
    if t_h_raw is None:
        raise KeyError("neither 't_hours' nor 'elapsed_hours' is present")
    cold_raw = payload["T_cold"]
    warm_raw = payload.get("T_warm")
    if warm_raw is None or (isinstance(warm_raw, list) and not warm_raw):
        cold_probe = np.asarray(cold_raw, dtype=np.float64)
        warm_raw = np.full_like(cold_probe, np.nan)

    t_h, tc, tw, duration, phase1, phase2, cold_final, warm_final = _curve_summary(
        t_h_raw,
        cold_raw,
        warm_raw,
    )
    name = _curve_identity(payload.get("source_file", default_name))
    date = _curve_date(payload.get("date", ""))
    return ReferenceCurve(
        name=name,
        date=date,
        t_hours=t_h,
        T_cold=tc,
        T_warm=tw,
        duration_hours=_reconcile_summary_value(payload, "duration_hours", duration),
        phase1_hours=_reconcile_summary_value(payload, "phase1_hours", phase1),
        phase2_hours=_reconcile_summary_value(payload, "phase2_hours", phase2),
        T_cold_final=_reconcile_summary_value(payload, "T_cold_final", cold_final),
        T_warm_final=_reconcile_summary_value(payload, "T_warm_final", warm_final),
        source_digest=_verified_curve_source_digest(
            payload.get("source_digest"),
            t_h,
            tc,
            tw,
        ),
    )


def _canonical_reference_curve(rc: ReferenceCurve) -> ReferenceCurve:
    """Derive programmatic metadata instead of trusting mutable summaries."""

    t_h, tc, tw, duration, phase1, phase2, cold_final, warm_final = _curve_summary(
        rc.t_hours,
        rc.T_cold,
        rc.T_warm,
    )
    return ReferenceCurve(
        name=_curve_identity(rc.name),
        date=_curve_date(rc.date),
        t_hours=t_h,
        T_cold=tc,
        T_warm=tw,
        duration_hours=duration,
        phase1_hours=phase1,
        phase2_hours=phase2,
        T_cold_final=cold_final,
        T_warm_final=warm_final,
        source_digest=_verified_curve_source_digest(
            rc.source_digest,
            t_h,
            tc,
            tw,
        ),
    )


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
    future_t: np.ndarray | None = field(default=None, repr=False)
    future_T_cold_mean: np.ndarray | None = field(default=None, repr=False)
    future_T_warm_mean: np.ndarray | None = field(default=None, repr=False)
    future_T_cold_upper: np.ndarray | None = field(default=None, repr=False)
    future_T_cold_lower: np.ndarray | None = field(default=None, repr=False)
    future_T_warm_upper: np.ndarray | None = field(default=None, repr=False)
    future_T_warm_lower: np.ndarray | None = field(default=None, repr=False)


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
    _t_of_p_mean: interp1d | None = field(default=None, repr=False)
    _p_of_t_mean: interp1d | None = field(default=None, repr=False)
    n_curves: int = 0
    duration_mean: float = 0.0
    duration_std: float = 0.0
    T_cold_end: float = T_COLD_END_FALLBACK
    T_warm_end: float = T_WARM_END_FALLBACK


# ============================================================================
# Loading
# ============================================================================


def load_curves(data_dir: Path) -> list[ReferenceCurve]:
    json_files = sorted(data_dir.glob("*.json"))
    json_files = [f for f in json_files if f.name not in ("cooldown_model.json", "reject_log.json")]
    curves = []
    for fp in json_files:
        try:
            d = _read_json_file_exact(fp)
            if not isinstance(d, dict):
                raise ValueError("cooldown curve document must be an object")
            rc = _reference_curve_from_payload(d, default_name=fp.stem)
            if len(rc.t_hours) < MIN_SAMPLES:
                logger.warning(
                    "Пропуск %s: %d точек < %d",
                    fp.name,
                    len(rc.t_hours),
                    MIN_SAMPLES,
                )
                continue
            if rc.T_cold[0] < 100:
                logger.warning("Пропуск %s: T_start=%.0f K", fp.name, rc.T_cold[0])
                continue
            curves.append(rc)
        except Exception as e:
            logger.error("Ошибка загрузки %s: %s", fp.name, e)
    logger.info("Загружено %d кривых охлаждения", len(curves))
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


def compute_progress(
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    T_cold_end: float = T_COLD_END_FALLBACK,
    T_warm_end: float = T_WARM_END_FALLBACK,
) -> np.ndarray:
    """Progress p in [0,1] from both channels. p=0 at 295K, p=1 at floor."""
    dT_c = T_COLD_START - T_cold_end
    dT_w = T_WARM_START - T_warm_end

    p_cold = (T_COLD_START - T_cold) / dT_c if dT_c > 0 else np.zeros_like(T_cold)
    p_warm = (T_WARM_START - T_warm) / dT_w if dT_w > 0 else np.zeros_like(T_warm)

    if np.any(np.isnan(T_warm)):
        p = p_cold
    else:
        p = W_COLD * p_cold + W_WARM * p_warm

    return np.clip(p, 0.0, 1.0)


def _derive_floors(curves: list[ReferenceCurve]) -> tuple[float, float]:
    """Derive T_cold_end and T_warm_end from observed minima across reference curves."""
    cold_mins = [float(np.nanmin(rc.T_cold)) for rc in curves if len(rc.T_cold) > 0]
    warm_mins = [float(np.nanmin(rc.T_warm)) for rc in curves if len(rc.T_warm) > 0 and not np.all(np.isnan(rc.T_warm))]

    T_cold_end = max(1.0, min(cold_mins) - 0.5) if cold_mins else T_COLD_END_FALLBACK
    T_warm_end = max(50.0, min(warm_mins) - 2.0) if warm_mins else T_WARM_END_FALLBACK
    return T_cold_end, T_warm_end


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
    # Linear fit: T = a*t + b -> a = dT/dt [K/h]
    if t_v[-1] - t_v[0] < 0.1:
        return 0.0
    a = float(np.polyfit(t_v, T_v, 1)[0])
    return a


def prepare_curve(
    rc: ReferenceCurve,
    T_cold_end: float = T_COLD_END_FALLBACK,
    T_warm_end: float = T_WARM_END_FALLBACK,
) -> ReferenceCurve:
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

    rc.progress = compute_progress(Tc, Tw, T_cold_end=T_cold_end, T_warm_end=T_warm_end)
    rc.progress = np.maximum.accumulate(rc.progress)

    # p(t)
    rc._p_of_t = interp1d(rc.t_hours, rc.progress, kind="linear", bounds_error=False, fill_value=(0.0, 1.0))

    # t(p), Tc(p), Tw(p) -- need unique progress values
    _, unique_idx = np.unique(rc.progress, return_index=True)
    if len(unique_idx) >= 2:
        p_u = rc.progress[unique_idx]
        t_u = rc.t_hours[unique_idx]
        rc._t_of_p = interp1d(p_u, t_u, kind="linear", bounds_error=False, fill_value=(t_u[0], t_u[-1]))
        rc._Tc_of_p = interp1d(
            p_u,
            Tc[unique_idx],
            kind="linear",
            bounds_error=False,
            fill_value=(Tc[unique_idx[0]], Tc[unique_idx[-1]]),
        )
        if not np.all(np.isnan(Tw)):
            rc._Tw_of_p = interp1d(
                p_u,
                Tw[unique_idx],
                kind="linear",
                bounds_error=False,
                fill_value=(Tw[unique_idx[0]], Tw[unique_idx[-1]]),
            )
    return rc


def prepare_all(
    curves: list[ReferenceCurve],
    T_cold_end: float = T_COLD_END_FALLBACK,
    T_warm_end: float = T_WARM_END_FALLBACK,
) -> list[ReferenceCurve]:
    prepared = []
    for rc in curves:
        try:
            rc = prepare_curve(rc, T_cold_end=T_cold_end, T_warm_end=T_warm_end)
            if rc._t_of_p is not None:
                prepared.append(rc)
            else:
                logger.warning("Пропуск %s: ошибка построения интерполятора", rc.name)
        except Exception as e:
            logger.warning("Пропуск %s: %s", rc.name, e)
    logger.info("Подготовлено %d/%d кривых", len(prepared), len(curves))
    return prepared


# ============================================================================
# Ensemble model
# ============================================================================


def build_ensemble(
    curves: list[ReferenceCurve],
    T_cold_end: float = T_COLD_END_FALLBACK,
    T_warm_end: float = T_WARM_END_FALLBACK,
) -> EnsembleModel:
    n = len(curves)
    p_grid = np.linspace(0, 1, N_PROGRESS_GRID)

    if n == 0:
        empty = np.full(N_PROGRESS_GRID, np.nan)
        return EnsembleModel(
            curves=[],
            p_grid=p_grid,
            t_matrix=np.empty((0, N_PROGRESS_GRID)),
            Tc_matrix=np.empty((0, N_PROGRESS_GRID)),
            Tw_matrix=np.empty((0, N_PROGRESS_GRID)),
            t_mean=empty,
            t_std=empty,
            Tc_mean=empty,
            Tc_std=empty,
            Tw_mean=empty,
            Tw_std=empty,
            n_curves=0,
            duration_mean=0.0,
            duration_std=0.0,
            T_cold_end=T_cold_end,
            T_warm_end=T_warm_end,
        )

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
    _t_of_p = interp1d(
        p_grid[valid],
        t_mean[valid],
        kind="linear",
        bounds_error=False,
        fill_value=(t_mean[valid][0], t_mean[valid][-1]),
    )

    t_sorted_idx = np.argsort(t_mean[valid])
    t_sorted = t_mean[valid][t_sorted_idx]
    p_sorted = p_grid[valid][t_sorted_idx]
    _, u_idx = np.unique(t_sorted, return_index=True)
    _p_of_t = interp1d(t_sorted[u_idx], p_sorted[u_idx], kind="linear", bounds_error=False, fill_value=(0.0, 1.0))

    durations = [rc.duration_hours for rc in curves]

    model = EnsembleModel(
        curves=curves,
        p_grid=p_grid,
        t_matrix=t_mat,
        Tc_matrix=Tc_mat,
        Tw_matrix=Tw_mat,
        t_mean=t_mean,
        t_std=t_std,
        Tc_mean=Tc_mean,
        Tc_std=Tc_std,
        Tw_mean=Tw_mean,
        Tw_std=Tw_std,
        _t_of_p_mean=_t_of_p,
        _p_of_t_mean=_p_of_t,
        n_curves=n,
        duration_mean=float(np.mean(durations)),
        duration_std=float(np.std(durations)),
        T_cold_end=T_cold_end,
        T_warm_end=T_warm_end,
    )
    logger.info(
        "Ансамбль: %d кривых, длительность %.1f +/- %.1f ч, T_cold_end=%.2f K",
        n,
        model.duration_mean,
        model.duration_std,
        model.T_cold_end,
    )
    return model


def build_model_from_curves(raw_curves: list[ReferenceCurve]) -> EnsembleModel:
    """Full build pipeline: derive data-driven floors → prepare → build ensemble."""
    T_cold_end, T_warm_end = _derive_floors(raw_curves)
    prepared = prepare_all(raw_curves, T_cold_end=T_cold_end, T_warm_end=T_warm_end)
    return build_ensemble(prepared, T_cold_end=T_cold_end, T_warm_end=T_warm_end)


# ============================================================================
# Prediction
# ============================================================================


def predict(
    model: EnsembleModel,
    T_cold_now: float,
    T_warm_now: float,
    t_elapsed: float = 0.0,
    generate_trajectory: bool = True,
    observed_rate_cold: float | None = None,
    observed_rate_warm: float | None = None,
) -> PredictionResult:
    """Predict remaining cooldown time from current state.

    Weighting scheme (multiplicative):
        w = w_progress x w_rate

    w_progress: Gaussian kernel on t(p_now) vs t_elapsed.
        Curves whose timing matches the observed elapsed time score higher.

    w_rate: Gaussian kernel on initial cooling rate similarity.
        If observed_rate_cold is provided (typically after 0.5-1.5h of cooldown),
        curves with similar dT/dt in the first hours dominate.
        This is the key: fast cooldown -> fast references, slow -> slow.

    Without observed_rate: falls back to progress-only weighting (v1.0 behavior).
    """
    p_now = float(
        compute_progress(
            np.array([T_cold_now]),
            np.array([T_warm_now]),
            T_cold_end=model.T_cold_end,
            T_warm_end=model.T_warm_end,
        )[0]
    )

    # Compute rate statistics for outlier detection (warm only; see below)
    ref_rates_warm = np.array([rc.initial_rate_warm for rc in model.curves if rc.initial_rate_warm != 0.0])

    rate_warm_mean = float(np.mean(ref_rates_warm)) if len(ref_rates_warm) >= 2 else 0.0
    rate_warm_std = float(np.std(ref_rates_warm)) if len(ref_rates_warm) >= 2 else 999.0

    # Determine if observed rate is an outlier (>2sigma from mean)
    # Only warm rate is used -- cold rate depends on T_start which varies.
    # Warm rate is the true heat-load discriminator (e.g., illuminator: -3.6 vs typical -22 K/h)
    # Cold-rate weighting is intentionally disabled (unreliable when T_start varies).
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
        if use_rate_warm and rc.initial_rate_warm != 0.0:
            # Warm rate is often more discriminating (e.g., illuminator)
            sigma_rw = max(rate_warm_std * 0.4, 1.0)
            dr_w = observed_rate_warm - rc.initial_rate_warm
            w_rate *= np.exp(-0.5 * (dr_w / sigma_rw) ** 2)

        w_total = w_prog * w_rate
        estimates.append((rc.name, t_rem, rc.duration_hours, w_total, w_prog, w_rate))

    if not estimates:
        return PredictionResult(
            t_remaining_hours=0,
            t_remaining_low_68=0,
            t_remaining_high_68=0,
            t_remaining_low_95=0,
            t_remaining_high_95=0,
            t_total_hours=0,
            progress=p_now,
            phase="unknown",
            T_cold_predicted_final=4.0,
            T_warm_predicted_final=85.0,
            n_references=0,
            individual_estimates=[],
        )

    # --- Fallback: if rate weighting killed all references, disable it ---
    rate_weights = np.array([e[5] for e in estimates])
    if use_rate_warm and np.max(rate_weights) < 0.01:
        estimates = [(n, r, d, wp, wp, 1.0) for n, r, d, _, wp, _ in estimates]

    t_rems = np.array([e[1] for e in estimates])
    t_tots = np.array([e[2] for e in estimates])
    weights = np.array([e[3] for e in estimates])
    w_sum = float(weights.sum())
    if not np.isfinite(w_sum) or w_sum <= 0.0:
        # All progress weights underflowed to 0 (elapsed far from every
        # reference, > ~39 sigma). weights /= weights.sum() would yield NaN
        # and poison the whole PredictionResult (ME-13). Fall back to
        # uniform weighting so the ensemble still returns a finite ETA.
        weights = np.ones(len(estimates))
    weights = weights / weights.sum()

    t_rem_mean = float(np.average(t_rems, weights=weights))
    t_tot_mean = float(np.average(t_tots, weights=weights))
    t_rem_var = float(np.average((t_rems - t_rem_mean) ** 2, weights=weights))
    t_rem_std = max(np.sqrt(t_rem_var), 0.1)

    n_eff = len(estimates)
    t_68 = 1.0 + 0.5 / max(n_eff, 1)
    t_95 = 2.0 + 3.0 / max(n_eff, 1)

    if p_now >= 0.999:
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

    if generate_trajectory and p_now < 0.999:
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
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray | None = None,
    window_h: float = RATE_WINDOW_H,
) -> tuple[float | None, float | None]:
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

    return (
        rate_c if rate_c != 0.0 else None,
        rate_w if rate_w is not None and rate_w != 0.0 else None,
    )


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
        t_cold_end_loo, t_warm_end_loo = _derive_floors(training)
        training_p = prepare_all(training, T_cold_end=t_cold_end_loo, T_warm_end=t_warm_end_loo)
        if len(training_p) < 2:
            continue
        model = build_ensemble(training_p, T_cold_end=t_cold_end_loo, T_warm_end=t_warm_end_loo)

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
                hist_mask = held.t_hours[: qi + 1] <= RATE_WINDOW_H
                if np.sum(hist_mask) >= 10:
                    rate_c = _compute_initial_rate(held.t_hours[: qi + 1], held.T_cold[: qi + 1], RATE_WINDOW_H)
                    if not np.all(np.isnan(held.T_warm[: qi + 1])):
                        rate_w = _compute_initial_rate(held.t_hours[: qi + 1], held.T_warm[: qi + 1], RATE_WINDOW_H)
                    if rate_c == 0.0:
                        rate_c = None
                    if rate_w is not None and rate_w == 0.0:
                        rate_w = None

            pred = predict(
                model,
                Tc,
                Tw,
                t_el,
                generate_trajectory=False,
                observed_rate_cold=rate_c,
                observed_rate_warm=rate_w,
            )
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
            t_query=np.array(t_q),
            T_cold_query=np.array(Tc_q),
            T_warm_query=np.array(Tw_q),
            progress_query=np.array(p_q),
            t_remaining_true=rem_true,
            t_remaining_pred=rem_pred,
            t_remaining_err=err,
            t_remaining_pct_err=pct,
        )
        results.append(vr)
        mae = float(np.mean(np.abs(err)))
        logger.info("LOO %s: MAE=%.2f ч, max|err|=%.2f ч", held.name, mae, np.max(np.abs(err)))
    return results


# ============================================================================
# Plotting (matplotlib imported lazily)
# ============================================================================


def plot_ensemble(model: EnsembleModel, output: Path):
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(18, 14))
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.25)
    cmap = plt.cm.tab10

    # T_cold vs time
    ax1 = fig.add_subplot(gs[0, 0])
    for i, rc in enumerate(model.curves):
        ax1.plot(
            rc.t_hours,
            rc.T_cold_smooth,
            color=cmap(i % 10),
            alpha=0.5,
            lw=0.8,
            label=rc.name[:25] if i < 10 else None,
        )
    ax1.plot(model.t_mean, model.Tc_mean, "k-", lw=2, label="Mean")
    ax1.fill_between(
        model.t_mean,
        model.Tc_mean - model.Tc_std,
        model.Tc_mean + model.Tc_std,
        alpha=0.2,
        color="gray",
        label="+/-1s",
    )
    ax1.set_ylabel("T cold, K")
    ax1.set_title("Cold Stage")
    ax1.set_yscale("log")
    ax1.set_ylim(1, 500)
    ax1.legend(fontsize=6, loc="upper right")
    ax1.grid(True, alpha=0.3)

    # T_warm vs time
    ax2 = fig.add_subplot(gs[0, 1])
    for i, rc in enumerate(model.curves):
        if rc.T_warm_smooth is not None and not np.all(np.isnan(rc.T_warm_smooth)):
            ax2.plot(rc.t_hours, rc.T_warm_smooth, color=cmap(i % 10), alpha=0.5, lw=0.8)
    ax2.plot(model.t_mean, model.Tw_mean, "k-", lw=2)
    ax2.fill_between(
        model.t_mean,
        model.Tw_mean - model.Tw_std,
        model.Tw_mean + model.Tw_std,
        alpha=0.2,
        color="gray",
    )
    ax2.set_ylabel("T warm, K")
    ax2.set_title("Warm Stage")
    ax2.grid(True, alpha=0.3)

    # Progress vs time
    ax3 = fig.add_subplot(gs[1, 0])
    for i, rc in enumerate(model.curves):
        if rc.progress is not None:
            ax3.plot(rc.t_hours, rc.progress, color=cmap(i % 10), alpha=0.5, lw=0.8)
    ax3.plot(model.t_mean, model.p_grid, "k-", lw=2, label="Mean p(t)")
    ax3.set_xlabel("Time, h")
    ax3.set_ylabel("Progress p")
    ax3.set_title("Progress Variable")
    ax3.set_ylim(-0.05, 1.05)
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=8)

    # t(p) envelope -- THE predictor
    ax4 = fig.add_subplot(gs[1, 1])
    for i in range(model.n_curves):
        ax4.plot(model.p_grid, model.t_matrix[i], color=cmap(i % 10), alpha=0.4, lw=0.6)
    ax4.plot(model.p_grid, model.t_mean, "k-", lw=2, label="Mean t(p)")
    ax4.fill_between(
        model.p_grid,
        model.t_mean - model.t_std,
        model.t_mean + model.t_std,
        alpha=0.15,
        color="blue",
        label="+/-1s",
    )
    ax4.fill_between(
        model.p_grid,
        model.t_mean - 2 * model.t_std,
        model.t_mean + 2 * model.t_std,
        alpha=0.08,
        color="blue",
        label="+/-2s",
    )
    ax4.set_xlabel("Progress p")
    ax4.set_ylabel("Time, h")
    ax4.set_title("Predictor: t(p) +/- CI")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    # sigma vs progress
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.plot(model.p_grid, model.t_std, "r-", lw=1.5)
    ax5.set_xlabel("Progress p")
    ax5.set_ylabel("sigma(t_remaining), h")
    ax5.set_title("Prediction Uncertainty vs Progress")
    ax5.grid(True, alpha=0.3)

    # Duration histogram
    ax6 = fig.add_subplot(gs[2, 1])
    durs = [rc.duration_hours for rc in model.curves]
    ax6.hist(durs, bins=max(3, len(durs) // 2), edgecolor="black", alpha=0.7, color="steelblue")
    ax6.axvline(model.duration_mean, color="red", ls="--", label=f"Mean: {model.duration_mean:.1f}h")
    ax6.set_xlabel("Duration, h")
    ax6.set_ylabel("Count")
    ax6.set_title(f"Duration (n={model.n_curves})")
    ax6.legend()
    ax6.grid(True, alpha=0.3)

    fig.suptitle("CryoDAQ Cooldown Predictor - Ensemble Model", fontsize=14, fontweight="bold")
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("График ансамбля сохранён: %s", output)


def plot_prediction(model, pred, T_cold_now, T_warm_now, t_elapsed, output):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    for rc in model.curves:
        axes[0].plot(rc.t_hours, rc.T_cold_smooth, color="lightgray", lw=0.5, alpha=0.5)
        if rc.T_warm_smooth is not None and not np.all(np.isnan(rc.T_warm_smooth)):
            axes[1].plot(rc.t_hours, rc.T_warm_smooth, color="lightgray", lw=0.5, alpha=0.5)

    axes[0].plot(
        t_elapsed,
        T_cold_now,
        "ro",
        ms=12,
        zorder=10,
        label=f"Now: {T_cold_now:.1f}K @ {t_elapsed:.1f}h",
    )
    axes[1].plot(t_elapsed, T_warm_now, "ro", ms=12, zorder=10, label=f"Now: {T_warm_now:.1f}K")

    if pred.future_t is not None:
        axes[0].plot(pred.future_t, pred.future_T_cold_mean, "b-", lw=2, label="Predicted")
        axes[0].fill_between(
            pred.future_t,
            pred.future_T_cold_lower,
            pred.future_T_cold_upper,
            alpha=0.2,
            color="blue",
        )
        axes[1].plot(pred.future_t, pred.future_T_warm_mean, "b-", lw=2, label="Predicted")
        axes[1].fill_between(
            pred.future_t,
            pred.future_T_warm_lower,
            pred.future_T_warm_upper,
            alpha=0.2,
            color="blue",
        )

    t_end = t_elapsed + pred.t_remaining_hours
    ci = pred.t_remaining_high_68 - pred.t_remaining_hours
    axes[0].axvline(t_end, color="green", ls="--", alpha=0.7, label=f"ETA: {t_end:.1f}h (+/-{ci:.1f}h)")
    axes[1].axvline(t_end, color="green", ls="--", alpha=0.7)

    axes[0].set_ylabel("T_cold, K")
    axes[0].set_yscale("log")
    axes[0].set_ylim(1, 500)
    axes[0].legend(fontsize=8, loc="upper right")
    axes[0].grid(True, alpha=0.3)
    h, m = int(pred.t_remaining_hours), int((pred.t_remaining_hours % 1) * 60)
    axes[0].set_title(f"p={pred.progress:.1%} | {h}h{m:02d}m left | {pred.phase}", fontsize=11)
    axes[1].set_ylabel("T_warm, K")
    axes[1].set_xlabel("Time, h")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    fig.suptitle("CryoDAQ Cooldown Prediction", fontsize=13, fontweight="bold")
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("График прогноза сохранён: %s", output)


def plot_validation(results: list[ValidationResult], output: Path):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    cmap = plt.cm.tab10

    ax = axes[0, 0]
    for i, vr in enumerate(results):
        ax.plot(
            vr.t_query,
            vr.t_remaining_err * 60,
            "o-",
            color=cmap(i % 10),
            ms=2,
            lw=0.8,
            alpha=0.7,
            label=vr.curve_name[:20],
        )
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("Elapsed, h")
    ax.set_ylabel("Error, min")
    ax.set_title("Error vs Time")
    ax.legend(fontsize=5, ncol=2)
    ax.grid(True, alpha=0.3)

    ax = axes[0, 1]
    for i, vr in enumerate(results):
        ax.plot(
            vr.progress_query,
            vr.t_remaining_err * 60,
            "o-",
            color=cmap(i % 10),
            ms=2,
            lw=0.8,
            alpha=0.7,
        )
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("Progress")
    ax.set_ylabel("Error, min")
    ax.set_title("Error vs Progress")
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    for i, vr in enumerate(results):
        ax.scatter(vr.t_remaining_true, vr.t_remaining_pred, c=[cmap(i % 10)], s=5, alpha=0.6)
    all_t = np.concatenate([vr.t_remaining_true for vr in results])
    all_p = np.concatenate([vr.t_remaining_pred for vr in results])
    lim = max(all_t.max(), all_p.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=0.5)
    ax.set_xlabel("True remaining, h")
    ax.set_ylabel("Predicted, h")
    ax.set_title("Predicted vs True")
    ax.set_aspect("equal")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.grid(True, alpha=0.3)

    ax = axes[1, 1]
    ax.axis("off")
    all_err = np.concatenate([vr.t_remaining_err for vr in results])
    all_abs = np.abs(all_err)
    np.concatenate([vr.t_remaining_pct_err for vr in results])
    curve_maes = [float(np.mean(np.abs(vr.t_remaining_err))) for vr in results]

    txt = (
        f"LOO Cross-Validation (n={len(results)})\n"
        f"{'=' * 40}\n"
        f"MAE:    {np.mean(all_abs):.2f} h ({np.mean(all_abs) * 60:.0f} min)\n"
        f"RMSE:   {np.sqrt(np.mean(all_err**2)):.2f} h\n"
        f"Max:    {np.max(all_abs):.2f} h\n"
        f"Median: {np.median(all_abs):.2f} h\n"
        f"Bias:   {np.mean(all_err):.3f} h\n"
        f"{'=' * 40}\n"
    )
    for vr, mae in zip(results, curve_maes):
        txt += f"  {vr.curve_name[:28]:28s} MAE={mae:.2f}h\n"
    ax.text(
        0.05,
        0.95,
        txt,
        transform=ax.transAxes,
        fontsize=9,
        va="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.8),
    )

    fig.suptitle("CryoDAQ Predictor - LOO Validation", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("График валидации сохранён: %s", output)


# ============================================================================
# Model save/load
# ============================================================================


def _fsync_directory(path: Path) -> None:
    """Durably settle a replacement on platforms with directory fsync."""

    if os.name == "nt":
        # Python cannot open a Windows directory for fsync. os.replace still
        # provides atomic replacement there; file contents were fsynced first.
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _PathIdentityError(RuntimeError):
    """A pathname no longer denotes the exact retained filesystem owner."""


def _is_link_or_junction(path: Path, info: os.stat_result) -> bool:
    """Recognize both ordinary links and Windows directory junctions."""

    is_junction = getattr(path, "is_junction", None)
    return stat.S_ISLNK(info.st_mode) or (callable(is_junction) and is_junction())


def _real_directory(path: Path) -> tuple[Path, os.stat_result]:
    """Return a canonical non-link directory and its retained identity."""

    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    if _is_link_or_junction(path, info) or not stat.S_ISDIR(info.st_mode):
        raise _PathIdentityError(f"filesystem parent is not a real directory: {path}")
    resolved = path.resolve(strict=True)
    resolved_info = resolved.lstat()
    if not os.path.samestat(info, resolved_info):
        raise _PathIdentityError(f"filesystem parent identity changed: {path}")
    return resolved, resolved_info


def _require_directory_identity(path: Path, expected: os.stat_result) -> None:
    current = path.lstat()
    if (
        _is_link_or_junction(path, current)
        or not stat.S_ISDIR(current.st_mode)
        or not os.path.samestat(current, expected)
    ):
        raise _PathIdentityError(f"filesystem parent identity changed: {path}")


def _require_regular_identity(
    path: Path,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    current = path.lstat()
    if (
        _is_link_or_junction(path, current)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or expected.st_nlink != 1
        or not os.path.samestat(current, expected)
    ):
        raise _PathIdentityError(f"{label} pathname identity changed: {path}")


def _unlink_exact_temporary(
    path: Path,
    expected: os.stat_result,
    *,
    parent: Path,
    parent_identity: os.stat_result,
    missing_ok: bool = True,
) -> None:
    """Unlink only the exact temporary owner; never unlink a replacement."""

    _require_directory_identity(parent, parent_identity)
    try:
        _require_regular_identity(path, expected, label="temporary")
    except FileNotFoundError as exc:
        if missing_ok:
            return
        raise _PathIdentityError(f"temporary pathname disappeared before settlement: {path}") from exc
    path.unlink()


def _read_json_file_exact(
    path: Path,
    *,
    expected_identity: os.stat_result | None = None,
    max_bytes: int = MAX_COOLDOWN_JSON_BYTES,
) -> object:
    """Decode UTF-8 JSON from one non-link descriptor-bound file owner."""

    before = path.lstat()
    if _is_link_or_junction(path, before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise _PathIdentityError(f"JSON source is not a real file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    stream = None
    descriptor_owned = True
    try:
        opened = os.fstat(descriptor)
        _require_regular_identity(path, opened, label="JSON source")
        if not os.path.samestat(before, opened):
            raise _PathIdentityError(f"JSON source changed during acquisition: {path}")
        if expected_identity is not None and not os.path.samestat(expected_identity, opened):
            raise _PathIdentityError(f"JSON source is not the expected owner: {path}")
        if opened.st_size > max_bytes:
            raise ValueError(f"JSON source exceeds {max_bytes} bytes: {path}")
        try:
            stream = os.fdopen(descriptor, "r", encoding="utf-8")
        except BaseException as primary:
            descriptor_owned = False
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "JSON stream acquisition and descriptor cleanup both failed",
                    (primary, cleanup),
                ) from None
            raise
        descriptor_owned = False
        return json.load(stream)
    finally:
        if stream is not None:
            stream.close()
        elif descriptor_owned:
            os.close(descriptor)


def _read_file_bytes_exact(
    path: Path,
    *,
    max_bytes: int = MAX_COOLDOWN_JSON_BYTES,
) -> bytes:
    """Read exact bytes from one acquired, non-link regular-file owner."""

    before = path.lstat()
    if _is_link_or_junction(path, before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise _PathIdentityError(f"byte source is not a real file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    stream = None
    descriptor_owned = True
    try:
        opened = os.fstat(descriptor)
        _require_regular_identity(path, opened, label="byte source")
        if not os.path.samestat(before, opened):
            raise _PathIdentityError(f"byte source changed during acquisition: {path}")
        if opened.st_size > max_bytes:
            raise ValueError(f"byte source exceeds {max_bytes} bytes: {path}")
        try:
            stream = os.fdopen(descriptor, "rb")
        except BaseException as primary:
            descriptor_owned = False
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "byte stream acquisition and descriptor cleanup both failed",
                    (primary, cleanup),
                ) from None
            raise
        descriptor_owned = False
        return stream.read()
    finally:
        if stream is not None:
            stream.close()
        elif descriptor_owned:
            os.close(descriptor)


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Strict same-directory write, file fsync, replace, and directory fsync."""

    if type(content) is not bytes:
        raise TypeError("atomic model content must be exact bytes")
    parent, parent_identity = _real_directory(path.parent)
    target = parent / path.name
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    temporary_identity: os.stat_result | None = None
    replaced = False
    raw_descriptor_owned = True
    try:
        temporary_identity = os.fstat(descriptor)
        try:
            stream = os.fdopen(descriptor, "wb")
        except BaseException as primary:
            raw_descriptor_owned = False
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "atomic stream acquisition and descriptor cleanup both failed",
                    (primary, cleanup),
                ) from None
            raise
        raw_descriptor_owned = False
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _require_directory_identity(parent, parent_identity)
        _require_regular_identity(temporary, temporary_identity, label="temporary")
        try:
            os.replace(temporary, target)
        except BaseException:
            try:
                _require_regular_identity(target, temporary_identity, label="replacement")
            except (FileNotFoundError, _PathIdentityError):
                pass
            else:
                replaced = True
            raise
        replaced = True
        _require_regular_identity(target, temporary_identity, label="replacement")
        _require_directory_identity(parent, parent_identity)
        _fsync_directory(parent)
    except BaseException as primary:
        if raw_descriptor_owned:
            raw_descriptor_owned = False
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "atomic write and raw descriptor cleanup both failed",
                    (primary, cleanup),
                ) from None
        if replaced:
            # The unique temporary owner moved to the authoritative path. A
            # following directory-fsync failure is durable-state ambiguity,
            # not an unlinked temporary owner.
            raise
        if temporary_identity is None:
            raise
        try:
            _unlink_exact_temporary(
                temporary,
                temporary_identity,
                parent=parent,
                parent_identity=parent_identity,
            )
        except BaseException as cleanup:
            raise BaseExceptionGroup(
                "atomic model replacement and temporary cleanup both failed",
                (primary, cleanup),
            ) from None
        raise


def _atomic_replace_json(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _atomic_replace_bytes(path, encoded)


def _curve_entry(rc: ReferenceCurve) -> dict[str, object]:
    canonical = _canonical_reference_curve(rc)
    return {
        "name": canonical.name,
        "date": canonical.date,
        "duration_hours": canonical.duration_hours,
        "phase1_hours": canonical.phase1_hours,
        "phase2_hours": canonical.phase2_hours,
        "T_cold_final": canonical.T_cold_final,
        "T_warm_final": canonical.T_warm_final,
        "source_digest": canonical.source_digest,
        "t_hours": canonical.t_hours.tolist(),
        "T_cold": canonical.T_cold.tolist(),
        "T_warm": canonical.T_warm.tolist(),
    }


def _require_persisted_curve(model_file: Path, expected: ReferenceCurve) -> None:
    """Prove one exact name/digest owner exists before reporting success."""

    persisted = _read_json_file_exact(model_file)
    if not isinstance(persisted, dict) or not isinstance(persisted.get("curves"), list):
        raise RuntimeError("persisted predictor model has no exact curves list")
    same_name = []
    for entry in persisted["curves"]:
        if isinstance(entry, dict) and entry.get("name") == expected.name:
            same_name.append(entry)
    if len(same_name) != 1 or same_name[0].get("source_digest") != expected.source_digest:
        raise RuntimeError("persisted predictor model does not contain one exact incoming curve owner")
    payload = dict(same_name[0])
    payload["source_file"] = same_name[0].get("name")
    verified = _reference_curve_from_payload(payload, default_name=expected.name)
    if verified.name != expected.name or verified.source_digest != expected.source_digest:
        raise RuntimeError("persisted predictor curve identity proof failed")


def save_model(model: EnsembleModel, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    md = {
        "version": "2.0",
        "n_curves": model.n_curves,
        "T_cold_end": model.T_cold_end,
        "T_warm_end": model.T_warm_end,
        "duration_mean": model.duration_mean,
        "duration_std": model.duration_std,
        "p_grid": model.p_grid.tolist(),
        "t_mean": model.t_mean.tolist(),
        "t_std": model.t_std.tolist(),
        "Tc_mean": model.Tc_mean.tolist(),
        "Tc_std": model.Tc_std.tolist(),
        "Tw_mean": model.Tw_mean.tolist(),
        "Tw_std": model.Tw_std.tolist(),
        "curves": [_curve_entry(rc) for rc in model.curves],
    }
    out = output_dir / "predictor_model.json"
    with _model_update_guard(output_dir):
        _atomic_replace_json(out, md)
    logger.info("Модель сохранена: %s (%.0f KB)", out, out.stat().st_size / 1024)


def load_model(model_dir: Path) -> EnsembleModel:
    d = _read_json_file_exact(model_dir / "predictor_model.json")
    if not isinstance(d, dict) or not isinstance(d.get("curves"), list):
        raise ValueError("predictor model must contain an exact curves list")
    _require_model_capacity(d["curves"])
    raw_curves = []
    identities: set[str] = set()
    for cd in d["curves"]:
        if not isinstance(cd, dict):
            raise ValueError("predictor model curve entries must be objects")
        payload = dict(cd)
        payload["source_file"] = cd["name"]
        rc = _reference_curve_from_payload(payload, default_name=cd["name"])
        if rc.name in identities:
            raise ValueError(f"predictor model contains duplicate curve identity {rc.name!r}")
        identities.add(rc.name)
        raw_curves.append(rc)
    return build_model_from_curves(raw_curves)


# ============================================================================
# Online learning: ingest new curves into existing model
# ============================================================================

# Quality gate thresholds for incoming curves
INGEST_MIN_DURATION_H = 10.0
INGEST_MAX_DURATION_H = 30.0
INGEST_MIN_T_START = 150.0  # K
INGEST_MAX_T_COLD_FINAL = 12.0  # K
INGEST_MAX_T_WARM_FINAL = 120.0  # K
INGEST_MIN_MONOTONICITY = 0.70
INGEST_MIN_POINTS = 500


def validate_new_curve(rc: ReferenceCurve) -> tuple[bool, str]:
    """Quality gate for a new curve before adding to model.

    Returns (passed, reason).
    """
    try:
        canonical = _canonical_reference_curve(rc)
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"invalid curve provenance: {exc}"

    if len(canonical.t_hours) < INGEST_MIN_POINTS:
        return False, f"too few points: {len(canonical.t_hours)} < {INGEST_MIN_POINTS}"

    if canonical.duration_hours < INGEST_MIN_DURATION_H:
        return False, f"too short: {canonical.duration_hours:.1f}h < {INGEST_MIN_DURATION_H}h"

    if canonical.duration_hours > INGEST_MAX_DURATION_H:
        return False, f"too long: {canonical.duration_hours:.1f}h > {INGEST_MAX_DURATION_H}h"

    if canonical.T_cold[0] < INGEST_MIN_T_START:
        return False, f"T_start too low: {canonical.T_cold[0]:.0f}K < {INGEST_MIN_T_START}K"

    if canonical.T_cold_final > INGEST_MAX_T_COLD_FINAL:
        return False, f"T_cold_final too high: {canonical.T_cold_final:.1f}K"

    if canonical.T_warm_final > INGEST_MAX_T_WARM_FINAL and canonical.T_warm_final > 0:
        return False, f"T_warm_final too high: {canonical.T_warm_final:.0f}K"

    # Monotonicity check
    dT = np.diff(canonical.T_cold)
    frac_dec = float(np.sum(dT < 0.5) / len(dT))
    if frac_dec < INGEST_MIN_MONOTONICITY:
        return False, f"monotonicity {frac_dec:.0%} < {INGEST_MIN_MONOTONICITY:.0%}"

    return True, "OK"


def ingest_curve(
    model_dir: Path,
    new_curve_json: Path,
    force: bool = False,
    max_curves: int = 50,
    *,
    _expected_source_identity: os.stat_result | None = None,
) -> tuple[bool, str, EnsembleModel | None]:
    """Serialize one model read/rebuild/replace transaction in this process."""

    if type(force) is not bool:
        raise TypeError("force must be an exact bool")
    if type(max_curves) is not int:
        raise TypeError("max_curves must be an exact int")
    if max_curves <= 0:
        raise ValueError("max_curves must be positive")
    with _model_update_guard(model_dir):
        return _ingest_curve_locked(
            model_dir,
            new_curve_json,
            force=force,
            max_curves=max_curves,
            expected_source_identity=_expected_source_identity,
        )


def _ingest_curve_locked(
    model_dir: Path,
    new_curve_json: Path,
    force: bool = False,
    max_curves: int = 50,
    expected_source_identity: os.stat_result | None = None,
) -> tuple[bool, str, EnsembleModel | None]:
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
    """
    if type(force) is not bool:
        raise TypeError("force must be an exact bool")
    if type(max_curves) is not int:
        raise TypeError("max_curves must be an exact int")
    if max_curves <= 0:
        raise ValueError("max_curves must be positive")
    model_file = model_dir / "predictor_model.json"
    if not model_file.exists():
        return False, f"Model not found: {model_file}", None

    # Load new curve
    try:
        d = _read_json_file_exact(
            new_curve_json,
            expected_identity=expected_source_identity,
        )
        if not isinstance(d, dict):
            raise ValueError("cooldown curve document must be an object")
        new_rc = _reference_curve_from_payload(d, default_name=new_curve_json.stem)
    except Exception as e:
        return False, f"Failed to parse {new_curve_json.name}: {e}", None

    # Quality gate
    if not force:
        passed, reason = validate_new_curve(new_rc)
        if not passed:
            return False, f"REJECT: {reason}", None

    # Load existing model
    model_bytes = _read_file_bytes_exact(model_file)
    model_data = json.loads(model_bytes.decode("utf-8"))
    if not isinstance(model_data, dict) or not isinstance(model_data.get("curves"), list):
        raise ValueError("predictor model must contain an exact curves list")
    _require_model_capacity(model_data["curves"])

    canonical_curves: list[ReferenceCurve] = []
    identities: set[str] = set()
    for stored in model_data["curves"]:
        if not isinstance(stored, dict):
            raise ValueError("predictor model curve entries must be objects")
        payload = dict(stored)
        payload["source_file"] = stored.get("name")
        canonical = _reference_curve_from_payload(
            payload,
            default_name=str(stored.get("name", "")),
        )
        if canonical.name in identities:
            raise ValueError(f"predictor model contains duplicate curve identity {canonical.name!r}")
        identities.add(canonical.name)
        canonical_entry = _curve_entry(canonical)
        if any(stored.get(key) != value for key, value in canonical_entry.items()):
            stored.update(canonical_entry)
        canonical_curves.append(canonical)

    # A name is the stable cycle identity. Every ingest must create exactly one
    # new owner; even an identical payload cannot turn a repeated identity into
    # an optimistic success.
    for existing_curve in canonical_curves:
        if existing_curve.name != new_rc.name:
            continue
        digest_detail = "same" if existing_curve.source_digest == new_rc.source_digest else "different"
        return (
            False,
            f"CONFLICT: '{new_rc.name}' already exists with the {digest_detail} source digest",
            None,
        )

    # Add new curve data to model JSON
    new_entry = _curve_entry(new_rc)
    model_data["curves"].append(new_entry)
    _require_model_capacity(model_data["curves"])

    # Cap ensemble size: drop oldest if over limit
    if len(model_data["curves"]) > max_curves:
        # Sort by date, keep newest max_curves
        model_data["curves"].sort(key=lambda c: c.get("date", ""))
        n_drop = len(model_data["curves"]) - max_curves
        dropped = [c["name"] for c in model_data["curves"][:n_drop]]
        model_data["curves"] = model_data["curves"][n_drop:]
        logger.info("Удалено %d старых кривых: %s", n_drop, dropped)
    if not any(
        entry.get("name") == new_rc.name and entry.get("source_digest") == new_rc.source_digest
        for entry in model_data["curves"]
    ):
        return (
            False,
            f"REJECT: incoming curve '{new_rc.name}' would be evicted by max_curves",
            None,
        )

    # Rebuild ensemble
    curves = []
    for cd in model_data["curves"]:
        payload = dict(cd)
        payload["source_file"] = cd["name"]
        rc = _reference_curve_from_payload(
            payload,
            default_name=cd["name"],
        )
        curves.append(rc)

    model = build_model_from_curves(curves)

    # Save updated model with history
    model_data["n_curves"] = model.n_curves
    model_data["T_cold_end"] = model.T_cold_end
    model_data["T_warm_end"] = model.T_warm_end
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
    history.append(
        {
            "action": "ingest",
            "curve": new_rc.name,
            "date": new_rc.date,
            "duration_h": round(new_rc.duration_hours, 1),
            "n_curves_after": model.n_curves,
            "source_digest": new_rc.source_digest,
        }
    )
    model_data["history"] = history

    # Retain the prior model, then durably replace the authoritative model.
    backup = model_dir / "predictor_model.json.bak"
    if model_file.exists():
        _atomic_replace_bytes(backup, model_bytes)

    _atomic_replace_json(model_file, model_data)
    _require_persisted_curve(model_file, new_rc)

    msg = (
        f"OK: added '{new_rc.name}' ({new_rc.duration_hours:.1f}h). "
        f"Model v{model_data['version']}: {model.n_curves} curves, "
        f"{model.duration_mean:.1f}+/-{model.duration_std:.1f}h"
    )
    logger.info(msg)
    return True, msg, model


class _TemporaryIngestCleanupError(RuntimeError):
    """A unique ingest file remained after its model transaction settled."""

    def __init__(
        self,
        path: Path,
        result: tuple[bool, str, EnsembleModel | None] | None,
        cleanup_failure: BaseException,
    ) -> None:
        self.path = path
        self.ingest_result = result
        self.cleanup_failure = cleanup_failure
        self.model_committed = result is not None and result[0] is True
        state = "committed" if self.model_committed else "did not commit"
        super().__init__(
            f"cooldown model transaction {state}, but temporary ingest "
            f"identity/ownership changed or cleanup failed: {path}: {cleanup_failure}"
        )


def ingest_from_raw_arrays(
    model_dir: Path,
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    name: str = "",
    date: str = "",
    force: bool = False,
) -> tuple[bool, str, EnsembleModel | None]:
    """Ingest directly from numpy arrays (for real-time CryoDAQ integration).

    Call this when a cooldown cycle completes and you have the data in memory.
    No intermediate JSON file needed.
    """
    if type(force) is not bool:
        raise TypeError("force must be an exact bool")
    if name == "":
        from datetime import datetime as _dt

        name = f"auto_ingest_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
    if date == "":
        from datetime import datetime as _dt

        date = _dt.now().strftime("%Y-%m-%d")

    name = _curve_identity(name)
    date = _curve_date(date)
    (
        t_hours,
        T_cold,
        T_warm,
        duration,
        phase1,
        phase2,
        cold_final,
        warm_final,
    ) = _curve_summary(t_hours, T_cold, T_warm)

    # Write temporary JSON
    tmp_data = {
        "source_file": name,
        "date": date,
        "t_hours": t_hours.tolist(),
        "T_cold": T_cold.tolist(),
        "T_warm": T_warm.tolist(),
        "duration_hours": duration,
        "phase1_hours": phase1,
        "phase2_hours": phase2,
        "T_cold_final": cold_final,
        "T_warm_final": warm_final,
        "source_digest": cooldown_curve_source_digest(t_hours, T_cold, T_warm),
    }
    model_root, parent_identity = _real_directory(model_dir)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=model_root,
        prefix=".cooldown-ingest.",
        suffix=".json.tmp",
    )
    tmp_path = Path(temporary_name)

    result: tuple[bool, str, EnsembleModel | None] | None = None
    primary: BaseException | None = None
    temporary_identity: os.stat_result | None = None
    raw_descriptor_owned = True
    try:
        temporary_identity = os.fstat(descriptor)
        try:
            stream = os.fdopen(descriptor, "w", encoding="utf-8")
        except BaseException as acquisition:
            raw_descriptor_owned = False
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "raw ingest stream acquisition and descriptor cleanup both failed",
                    (acquisition, cleanup),
                ) from None
            raise
        raw_descriptor_owned = False
        with stream:
            json.dump(tmp_data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        _require_directory_identity(model_root, parent_identity)
        _require_regular_identity(tmp_path, temporary_identity, label="raw ingest")
        result = ingest_curve(
            model_root,
            tmp_path,
            force=force,
            max_curves=50,
            _expected_source_identity=temporary_identity,
        )
    except BaseException as exc:
        primary = exc
    if raw_descriptor_owned:
        raw_descriptor_owned = False
        try:
            os.close(descriptor)
        except BaseException as cleanup:
            if primary is None:
                primary = cleanup
            else:
                primary = BaseExceptionGroup(
                    "raw ingest and descriptor cleanup both failed",
                    (primary, cleanup),
                )

    cleanup_error: _TemporaryIngestCleanupError | None = None
    try:
        if temporary_identity is None:
            raise _PathIdentityError("raw ingest temporary identity was not acquired")
        _unlink_exact_temporary(
            tmp_path,
            temporary_identity,
            parent=model_root,
            parent_identity=parent_identity,
            missing_ok=False,
        )
    except BaseException as exc:
        cleanup_error = _TemporaryIngestCleanupError(tmp_path, result, exc)

    if primary is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "cooldown ingest and temporary cleanup both failed",
            (primary, cleanup_error),
        ) from None
    if cleanup_error is not None:
        raise cleanup_error from cleanup_error.cleanup_failure
    if primary is not None:
        raise primary
    assert result is not None

    return result
