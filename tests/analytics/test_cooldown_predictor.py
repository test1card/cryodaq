"""Unit tests for the refactored cooldown_predictor library.

Covers:
- compute_progress boundary conditions and monotonicity
- predict() with a synthetic ensemble at various cooldown stages
- compute_rate_from_history on known linear data
- validate_new_curve quality gate
- Module-level hygiene: no matplotlib at import time, no bare print() calls
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reference_curves(synthetic_curves: list[dict]):
    """Convert fixture dicts to ReferenceCurve objects and prepare them."""
    from cryodaq.analytics.cooldown_predictor import ReferenceCurve, prepare_all

    rcs = [
        ReferenceCurve(
            name=d["name"],
            date=d["date"],
            t_hours=d["t_hours"],
            T_cold=d["T_cold"],
            T_warm=d["T_warm"],
            duration_hours=d["duration_hours"],
            phase1_hours=d["phase1_hours"],
            phase2_hours=d["phase2_hours"],
            T_cold_final=d["T_cold_final"],
            T_warm_final=d["T_warm_final"],
        )
        for d in synthetic_curves
    ]
    return prepare_all(rcs)


# ---------------------------------------------------------------------------
# test_compute_progress_boundaries
# ---------------------------------------------------------------------------


async def test_compute_progress_room_temperature():
    """At room temperature (295 K / 295 K) progress should be ≈ 0."""
    from cryodaq.analytics.cooldown_predictor import compute_progress

    p = compute_progress(np.array([295.0]), np.array([295.0]))
    assert float(p[0]) == pytest.approx(0.0, abs=0.02)


async def test_compute_progress_base_temperature():
    """At base temperature (T_cold=4 K, T_warm=85 K) progress should be ≈ 1."""
    from cryodaq.analytics.cooldown_predictor import compute_progress

    p = compute_progress(np.array([4.0]), np.array([85.0]))
    assert float(p[0]) == pytest.approx(1.0, abs=0.02)


async def test_compute_progress_monotone():
    """Progress must be monotonically non-decreasing as T_cold decreases."""
    from cryodaq.analytics.cooldown_predictor import compute_progress

    T_cold_values = np.array([295.0, 200.0, 100.0, 50.0, 20.0, 10.0, 5.0, 4.0])
    # Use a realistic T_warm that also decreases
    T_warm_values = np.array([295.0, 250.0, 180.0, 140.0, 100.0, 90.0, 86.0, 85.0])

    p = compute_progress(T_cold_values, T_warm_values)

    # p must be non-decreasing
    diffs = np.diff(p)
    assert np.all(diffs >= -1e-9), f"Progress not monotone: diffs={diffs}"
    # First value near 0, last near 1
    assert p[0] < 0.05
    assert p[-1] > 0.95


async def test_compute_progress_clipped():
    """Progress values must stay in [0, 1] even for out-of-range temperatures."""
    from cryodaq.analytics.cooldown_predictor import compute_progress

    # Slightly beyond expected range
    p_low = compute_progress(np.array([300.0]), np.array([300.0]))
    p_high = compute_progress(np.array([3.0]), np.array([80.0]))

    assert float(p_low[0]) >= 0.0
    assert float(p_high[0]) <= 1.0


# ---------------------------------------------------------------------------
# test_predict_with_synthetic_ensemble
# ---------------------------------------------------------------------------


async def test_predict_with_synthetic_ensemble(synthetic_curves):
    """predict() returns a valid PredictionResult from a synthetic ensemble."""
    from cryodaq.analytics.cooldown_predictor import (
        PredictionResult,
        build_ensemble,
        predict,
    )

    curves = _make_reference_curves(synthetic_curves)
    assert len(curves) >= 3, "Need at least 3 prepared curves for a meaningful ensemble"

    model = build_ensemble(curves)
    pred = predict(model, T_cold_now=50.0, T_warm_now=120.0, t_elapsed=8.0)

    assert isinstance(pred, PredictionResult)
    assert pred.t_remaining_hours > 0.0
    assert pred.t_remaining_hours < 20.0
    # CI width must be positive
    ci68 = pred.t_remaining_high_68 - pred.t_remaining_hours
    assert ci68 > 0.0
    assert pred.n_references > 0
    assert pred.progress > 0.0
    assert pred.phase in {"phase1", "phase2", "transition", "steady"}


async def test_predict_required_fields(synthetic_curves):
    """PredictionResult must expose all documented fields."""
    from cryodaq.analytics.cooldown_predictor import build_ensemble, predict

    curves = _make_reference_curves(synthetic_curves)
    model = build_ensemble(curves)
    pred = predict(model, T_cold_now=50.0, T_warm_now=120.0, t_elapsed=8.0)

    required_fields = [
        "t_remaining_hours",
        "t_remaining_low_68",
        "t_remaining_high_68",
        "t_remaining_low_95",
        "t_remaining_high_95",
        "t_total_hours",
        "progress",
        "phase",
        "T_cold_predicted_final",
        "T_warm_predicted_final",
        "n_references",
        "individual_estimates",
    ]
    for field in required_fields:
        assert hasattr(pred, field), f"Missing field: {field}"


# ---------------------------------------------------------------------------
# test_predict_early_in_cooldown
# ---------------------------------------------------------------------------


async def test_predict_early_in_cooldown(synthetic_curves):
    """Early in cooldown (T_cold≈280K, 0.5h elapsed): large t_remaining, wide CI."""
    from cryodaq.analytics.cooldown_predictor import build_ensemble, predict

    curves = _make_reference_curves(synthetic_curves)
    model = build_ensemble(curves)
    pred = predict(model, T_cold_now=280.0, T_warm_now=280.0, t_elapsed=0.5)

    # Far from done → large remaining time
    assert pred.t_remaining_hours > 15.0
    # Early = less certain → CI span should be > 0
    ci68 = pred.t_remaining_high_68 - pred.t_remaining_low_68
    assert ci68 > 0.0


# ---------------------------------------------------------------------------
# test_predict_near_end
# ---------------------------------------------------------------------------


async def test_predict_near_end(synthetic_curves):
    """Near end of cooldown (T_cold=5K, T_warm=86K, 18h elapsed): small t_remaining."""
    from cryodaq.analytics.cooldown_predictor import build_ensemble, predict

    curves = _make_reference_curves(synthetic_curves)
    model = build_ensemble(curves)
    pred = predict(model, T_cold_now=5.0, T_warm_now=86.0, t_elapsed=18.0)

    # Almost there → small remaining time
    assert pred.t_remaining_hours < 2.0
    assert pred.t_remaining_hours >= 0.0


# ---------------------------------------------------------------------------
# test_compute_rate_from_history
# ---------------------------------------------------------------------------


async def test_compute_rate_from_history_linear():
    """Linear T = 295 - 10*t should give rate_cold ≈ -10 K/h."""
    from cryodaq.analytics.cooldown_predictor import compute_rate_from_history

    # Build 2h of data at 10-second intervals
    dt_h = 10.0 / 3600.0
    t = np.arange(0, 2.0 + dt_h, dt_h)
    T_cold = 295.0 - 10.0 * t  # slope = -10 K/h exactly

    rate_cold, rate_warm = compute_rate_from_history(t, T_cold, T_warm=None)

    assert rate_cold is not None
    assert rate_cold == pytest.approx(-10.0, rel=0.05)
    assert rate_warm is None


async def test_compute_rate_from_history_warm_channel():
    """Warm channel rate is also computed when T_warm is provided."""
    from cryodaq.analytics.cooldown_predictor import compute_rate_from_history

    dt_h = 10.0 / 3600.0
    t = np.arange(0, 2.0 + dt_h, dt_h)
    T_cold = 295.0 - 10.0 * t
    T_warm = 295.0 - 5.0 * t  # slope = -5 K/h

    rate_cold, rate_warm = compute_rate_from_history(t, T_cold, T_warm=T_warm)

    assert rate_cold is not None
    assert rate_cold == pytest.approx(-10.0, rel=0.05)
    assert rate_warm is not None
    assert rate_warm == pytest.approx(-5.0, rel=0.05)


async def test_compute_rate_from_history_insufficient_data():
    """Returns (None, None) when there is less than RATE_MIN_HISTORY_H of data."""
    from cryodaq.analytics.cooldown_predictor import compute_rate_from_history

    dt_h = 10.0 / 3600.0
    # Only 10 minutes of data (< 0.5 h minimum)
    t = np.arange(0, 0.1, dt_h)
    T_cold = 295.0 - 10.0 * t

    rate_cold, rate_warm = compute_rate_from_history(t, T_cold)

    assert rate_cold is None
    assert rate_warm is None


# ---------------------------------------------------------------------------
# test_validate_new_curve quality gate
# ---------------------------------------------------------------------------


async def test_validate_new_curve_rejects_short_duration():
    """Curves shorter than INGEST_MIN_DURATION_H must be rejected."""
    from cryodaq.analytics.cooldown_predictor import (
        INGEST_MIN_DURATION_H,
        ReferenceCurve,
        validate_new_curve,
    )

    dt = 10.0 / 3600.0
    duration = INGEST_MIN_DURATION_H - 1.0  # too short
    t = np.arange(0, duration + dt, dt)
    n = len(t)

    rc = ReferenceCurve(
        name="short_curve",
        date="2026-01-01",
        t_hours=t,
        T_cold=np.linspace(295.0, 4.0, n),
        T_warm=np.linspace(295.0, 85.0, n),
        duration_hours=duration,
        phase1_hours=4.0,
        phase2_hours=duration - 4.0,
        T_cold_final=4.0,
        T_warm_final=85.0,
    )
    passed, reason = validate_new_curve(rc)
    assert not passed
    assert "short" in reason.lower() or "duration" in reason.lower()


async def test_validate_new_curve_rejects_low_T_start():
    """Curves that did not start from near room temperature are rejected."""
    from cryodaq.analytics.cooldown_predictor import (
        INGEST_MIN_POINTS,
        INGEST_MIN_T_START,
        ReferenceCurve,
        validate_new_curve,
    )

    n = INGEST_MIN_POINTS + 100
    t = np.linspace(0, 15.0, n)

    rc = ReferenceCurve(
        name="low_start",
        date="2026-01-01",
        t_hours=t,
        T_cold=np.linspace(INGEST_MIN_T_START - 10, 4.0, n),  # starts too low
        T_warm=np.linspace(200.0, 85.0, n),
        duration_hours=float(t[-1]),
        phase1_hours=7.0,
        phase2_hours=8.0,
        T_cold_final=4.0,
        T_warm_final=85.0,
    )
    passed, reason = validate_new_curve(rc)
    assert not passed
    assert "start" in reason.lower() or "t_start" in reason.lower()


async def test_validate_new_curve_accepts_good_curve(synthetic_curves):
    """A well-formed synthetic curve must pass the quality gate."""
    from cryodaq.analytics.cooldown_predictor import ReferenceCurve, validate_new_curve

    # Pick the longest synthetic curve (most likely to pass all gates)
    best = max(synthetic_curves, key=lambda d: d["duration_hours"])

    rc = ReferenceCurve(
        name=best["name"],
        date=best["date"],
        t_hours=best["t_hours"],
        T_cold=best["T_cold"],
        T_warm=best["T_warm"],
        duration_hours=best["duration_hours"],
        phase1_hours=best["phase1_hours"],
        phase2_hours=best["phase2_hours"],
        T_cold_final=best["T_cold_final"],
        T_warm_final=best["T_warm_final"],
    )
    passed, reason = validate_new_curve(rc)
    # Note: synthetic curves use dt=10s, 18-21h → ~6500-7600 points > INGEST_MIN_POINTS=500
    assert passed, f"Expected acceptance, got reject: {reason}"


# ---------------------------------------------------------------------------
# test_no_matplotlib_at_import
# ---------------------------------------------------------------------------


async def test_no_matplotlib_at_import():
    """Importing cooldown_predictor must NOT trigger a top-level matplotlib import.

    This test is meaningful only when run in a fresh interpreter where
    matplotlib has not already been imported by some other test.  We check
    whether the import of cooldown_predictor *itself* causes matplotlib to
    appear in sys.modules.  If matplotlib was already present before this
    test runs we skip gracefully.
    """
    # Record state before import
    mpl_before = "matplotlib" in sys.modules

    # Force a reimport (the module may already be cached — that's fine;
    # what we care about is that any cached version did not pull in
    # matplotlib at module load time during a fresh import)
    if "cryodaq.analytics.cooldown_predictor" not in sys.modules:
        import importlib

        importlib.import_module("cryodaq.analytics.cooldown_predictor")

    mpl_after = "matplotlib" in sys.modules

    if mpl_before:
        # matplotlib was already loaded by some earlier test — can't isolate
        pytest.skip(
            "matplotlib already in sys.modules before test; "
            "cannot verify lazy-import behaviour in this session"
        )
    else:
        assert not mpl_after, (
            "cooldown_predictor imported matplotlib at module level. "
            "matplotlib imports must be inside plot_*() functions."
        )


# ---------------------------------------------------------------------------
# test_no_print_in_module
# ---------------------------------------------------------------------------


async def test_no_print_in_module():
    """The cooldown_predictor module must not contain bare print() calls.

    After the refactor all print() calls should have been replaced with
    logging.  We parse the module source with ast and look for Call nodes
    whose function is the builtin `print`.
    """
    import cryodaq.analytics.cooldown_predictor as _mod

    src_path = Path(_mod.__file__)
    assert src_path.exists(), f"Source file not found: {src_path}"  # noqa: ASYNC240

    source = src_path.read_text(encoding="utf-8")  # noqa: ASYNC240
    tree = ast.parse(source, filename=str(src_path))

    bare_prints: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            bare_prints.append(node.lineno)

    assert bare_prints == [], (
        f"Found bare print() calls in cooldown_predictor.py at lines: {bare_prints}. "
        "Replace with logging.getLogger(__name__).info/warning/error."
    )
