"""Audit-fix regression test for cooldown_predictor.predict().

ME-13 / D-C12: `weights /= weights.sum()` produced NaN when every progress
weight underflowed to 0 (elapsed far from all references, > ~39 sigma).
predict() must degrade gracefully (no NaN ETA).
"""

from __future__ import annotations

import math


def _make_reference_curves(synthetic_curves: list[dict]):
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


async def test_predict_far_elapsed_no_nan_eta(synthetic_curves) -> None:
    """t_elapsed absurdly far from all references → all progress weights underflow.

    Without the sum==0 guard, weights /= weights.sum() yields NaN and poisons
    the entire PredictionResult. The prediction must stay finite.
    """
    from cryodaq.analytics.cooldown_predictor import build_ensemble, predict

    curves = _make_reference_curves(synthetic_curves)
    model = build_ensemble(curves)

    # Elapsed time enormously far from any reference timing → every
    # w_prog = exp(-0.5*((t_at_p - t_elapsed)/sigma)^2) underflows to 0.
    pred = predict(model, T_cold_now=50.0, T_warm_now=120.0, t_elapsed=1e9)

    assert math.isfinite(pred.t_remaining_hours), "ETA must not be NaN"
    assert math.isfinite(pred.t_total_hours)
    assert math.isfinite(pred.t_remaining_low_68)
    assert math.isfinite(pred.t_remaining_high_95)
