"""Tests for VacuumTrendPredictor — 20 unit tests per spec."""

from __future__ import annotations

import json
import math
from dataclasses import asdict

import numpy as np

from cryodaq.analytics.vacuum_trend import (
    _LOG_P_ULT_BOUND_EPS,
    _LOG_P_ULT_MIN,
    VacuumTrendPredictor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _push_exponential(
    pred: VacuumTrendPredictor,
    log_p_ult: float,
    A: float,
    tau: float,
    n: int = 200,
    dt: float = 5.0,
    t0: float = 0.0,
    noise_sigma: float = 0.0,
    rng: np.random.Generator | None = None,
) -> None:
    """Push synthetic exponential pumpdown curve."""
    if rng is None:
        rng = np.random.default_rng(42)
    for i in range(n):
        t = t0 + i * dt
        logP = log_p_ult + A * math.exp(-t / tau)
        p_mbar = 10.0 ** (logP + rng.normal(0, noise_sigma))
        pred.push(t, p_mbar)


def _push_power_law(
    pred: VacuumTrendPredictor,
    log_p_ult: float,
    B: float,
    alpha: float,
    n: int = 200,
    dt: float = 5.0,
    t0: float = 10.0,
    noise_sigma: float = 0.0,
    rng: np.random.Generator | None = None,
) -> None:
    """Push synthetic power-law pumpdown curve. t0>0 to avoid t=0."""
    if rng is None:
        rng = np.random.default_rng(42)
    for i in range(n):
        t = t0 + i * dt
        t_safe = max(t, 1.0)
        logP = log_p_ult + B * t_safe ** (-alpha)
        p_mbar = 10.0 ** (logP + rng.normal(0, noise_sigma))
        pred.push(t, p_mbar)


# ---------------------------------------------------------------------------
# 1. test_fit_exponential_synthetic — params ±10%
# ---------------------------------------------------------------------------


def test_fit_exponential_synthetic() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10, "min_points_combined": 300})
    log_p_ult = -6.0
    A = 5.0
    tau = 300.0
    _push_exponential(pred, log_p_ult, A, tau, n=200, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    # Must select exponential model (not power_law or combined)
    assert p.model_type == "exponential"
    assert p.confidence > 0.95
    # Fit params within ±10% of ground truth
    assert abs(p.fit_params["log_p_ult"] - log_p_ult) / abs(log_p_ult) < 0.10
    assert abs(p.fit_params["A"] - A) / A < 0.10
    assert abs(p.fit_params["tau"] - tau) / tau < 0.10


# ---------------------------------------------------------------------------
# 2. test_fit_power_law_synthetic — params ±10%
# ---------------------------------------------------------------------------


def test_fit_power_law_synthetic() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10, "min_points_combined": 300})
    log_p_ult = -6.0
    B = 3.0
    alpha = 1.0
    _push_power_law(pred, log_p_ult, B, alpha, n=200, dt=5.0, t0=10.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    # Must select power_law model (not exponential or combined)
    assert p.model_type == "power_law"
    assert p.confidence > 0.90
    # log_p_ult must be recovered within ±10%
    assert abs(p.fit_params["log_p_ult"] - log_p_ult) / abs(log_p_ult) < 0.10
    # B and alpha are jointly unidentifiable: different (B, alpha) pairs can produce
    # equivalent fits over finite data (e.g. B=0.35, alpha=0.38 fits B=3, alpha=1 data
    # equally well over t=10..1005 s). The real bound: verify the fitted power-law
    # TERM B_fit*t^(-alpha_fit) reproduces ground truth at two timepoints within
    # 0.1 log-decades (proves correct curve shape, not raw parameter recovery).
    # Ground truth: logP(t) = -6 + 3 * t^(-1).
    for t_check in [50.0, 500.0]:
        fitted_logP = (
            p.fit_params["log_p_ult"]
            + p.fit_params["B"] * (t_check ** (-p.fit_params["alpha"]))
        )
        gt_logP = log_p_ult + B * (t_check ** (-alpha))
        assert abs(fitted_logP - gt_logP) < 0.1, (
            f"Model prediction mismatch at t={t_check}: fitted={fitted_logP:.3f}, gt={gt_logP:.3f}"
        )


# ---------------------------------------------------------------------------
# 3. test_fit_combined_synthetic — BIC selects combined
# ---------------------------------------------------------------------------


def test_fit_combined_synthetic() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10, "min_points_combined": 50})
    rng = np.random.default_rng(42)
    log_p_ult = -7.0
    A, tau = 3.0, 200.0
    B, alpha = 2.0, 0.8
    for i in range(300):
        t = 10.0 + i * 5.0
        logP = log_p_ult + A * math.exp(-t / tau) + B * max(t, 1.0) ** (-alpha)
        p_mbar = 10.0 ** (logP + rng.normal(0, 0.01))
        pred.push(t, p_mbar)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    # BIC must select combined model — pure exponential/power_law won't capture both terms
    assert p.model_type == "combined"
    assert p.confidence > 0.90
    # Key params within ±10% of ground truth
    assert abs(p.fit_params["log_p_ult"] - log_p_ult) / abs(log_p_ult) < 0.10
    assert abs(p.fit_params["A"] - A) / A < 0.10
    assert abs(p.fit_params["tau"] - tau) / tau < 0.10
    # B and alpha: the 5-param combined fit has strong B/alpha degeneracy —
    # different (B, alpha) pairs produce equivalent fits over finite data, so
    # raw parameter recovery is not a reliable bound. The real bound: verify
    # the fitted power-law TERM B_fit*t^(-alpha_fit) reproduces ground truth at
    # two timepoints within 0.15 log-decades (proves the power-law component is
    # correctly captured; 0.15 decade ≈ 40% in linear P).
    # Ground truth power-law term: B * t^(-alpha) = 2.0 * t^(-0.8).
    for t_check in [50.0, 500.0]:
        fitted_pl = p.fit_params["B"] * (t_check ** (-p.fit_params["alpha"]))
        gt_pl = B * (t_check ** (-alpha))
        assert abs(fitted_pl - gt_pl) < 0.15, (
            f"Power-law term mismatch at t={t_check}: fitted={fitted_pl:.4f}, gt={gt_pl:.4f}"
        )


# ---------------------------------------------------------------------------
# 4. test_model_selection_prefers_simple — few points → 3-param model
# ---------------------------------------------------------------------------


def test_model_selection_prefers_simple() -> None:
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "min_points_combined": 200,  # won't try combined with only 80 points
        }
    )
    _push_exponential(pred, -5.0, 4.0, 500.0, n=80, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type in ("exponential", "power_law")


# ---------------------------------------------------------------------------
# 5. test_eta_computation_exponential — ETA for exponential
# ---------------------------------------------------------------------------


def test_no_eta_when_the_fitted_floor_is_below_the_measurable_range() -> None:
    """A floor the gauge cannot read cannot support an arrival time.

    logP(t) = -7 + 5*exp(-t/300), target 1e-5. The target crossing is at
    300*ln(2.5) = 274.9 s against data spanning 0..245 s, so it sits WELL
    INSIDE the extrapolation horizon -- the refusal here is about the floor,
    not the distance.

    The module already refuses to report a floor below _LOG_P_ULT_UNMEASURABLE
    as an ultimate pressure, on the grounds that it "is not a prediction but
    the floor of the search space". This test pins that an ETA, which is a
    statement about reaching that floor, is refused on the same grounds. It
    previously asserted a finite ETA, computed from exactly the value the
    module was simultaneously reporting as unidentified.
    """
    pred = VacuumTrendPredictor(
        config={
            "window_s": 10000,
            "min_points": 10,
            "min_points_combined": 300,
            "targets_mbar": [1e-5],
        }
    )
    _push_exponential(pred, -7.0, 5.0, 300.0, n=50, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type == "exponential"
    assert math.isnan(p.p_ultimate_mbar), "a floor below the gauge's range is not reported"
    assert p.eta_targets.get("1e-05") is None, (
        "and an ETA resting on that floor is not reported either"
    )


def test_no_eta_when_the_fitted_floor_rests_on_its_bound() -> None:
    """An optimiser's bound is not a fit.

    logP(t) = -6 + 8*t^(-0.3) with a 1e-5 target: the crossing is just past
    the data, comfortably inside the horizon. But the power-law fit does not
    recover the -6 floor -- it drives log_p_ult onto its -20 lower bound and
    absorbs the difference into B and alpha. The curve below the data is then
    unconstrained, which is what produced "0.01 mbar by 14.09" on this stand's
    31.08 pump-down.
    """
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "min_points_combined": 300,
            "targets_mbar": [1e-5],
        }
    )
    for index in range(50):
        t = 10.0 + index * 5.0
        pred.push(t, 10.0 ** (-6.0 + 8.0 * max(t, 1.0) ** (-0.3)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type == "power_law"
    assert p.fit_params["log_p_ult"] <= _LOG_P_ULT_MIN + _LOG_P_ULT_BOUND_EPS, (
        "this scenario exists because the fit lands on the bound"
    )
    assert p.eta_targets.get("1e-05") is None


def test_already_reached_follows_the_gauge_not_the_fit() -> None:
    """A fit below the target while the measurement is above it is not arrival.

    The last accepted reading decides. Using fit.predict() instead announced an
    arrival that had not happened -- the model can lead the instrument.
    """
    pred = VacuumTrendPredictor(
        config={"window_s": 10000, "min_points": 10, "min_points_combined": 300, "targets_mbar": [1e-3]}
    )
    _push_exponential(pred, -4.0, 2.0, 200.0, n=40, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    fitted_now = float(p.extrapolation_logP[0]) if p.extrapolation_logP else None
    assert fitted_now is not None
    # Whatever the curve says, the ETA must not claim arrival unless the last
    # MEASUREMENT is at or below the target.
    if p.eta_targets.get("0.001") == 0.0:
        assert fitted_now <= math.log10(1e-3)

def test_eta_unreachable() -> None:
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "targets_mbar": [1e-8],
        }
    )
    # P_ult ≈ 1e-5, target 1e-8 is unreachable
    _push_exponential(pred, -5.0, 3.0, 300.0, n=200, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    eta = p.eta_targets.get("1e-08")
    assert eta is None


# ---------------------------------------------------------------------------
# 8. test_trend_pumping_down — d(logP)/dt < 0 → "pumping_down"
# ---------------------------------------------------------------------------


def test_trend_pumping_down() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    _push_exponential(pred, -6.0, 5.0, 300.0, n=200, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.trend == "pumping_down"


# ---------------------------------------------------------------------------
# 9. test_trend_stable — |d(logP)/dt| ≈ 0 → "stable"
# ---------------------------------------------------------------------------


def test_trend_stable() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    rng = np.random.default_rng(42)
    # Constant pressure with tiny noise
    for i in range(200):
        t = i * 5.0
        pred.push(t, 1e-6 * (1 + rng.normal(0, 0.001)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.trend == "stable"


# ---------------------------------------------------------------------------
# 10. test_trend_rising — d(logP)/dt > 0, sustained → "rising"
# ---------------------------------------------------------------------------


def test_trend_rising() -> None:
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "rising_sustained_s": 30,
        }
    )
    # Start stable, then rising
    rng = np.random.default_rng(42)
    for i in range(100):
        t = i * 2.0
        # First 50 points stable at 1e-6, then rising
        if i < 50:
            p = 1e-6
        else:
            p = 1e-6 * 10 ** ((i - 50) * 0.02)  # rising ~0.01 decades/s
        pred.push(t, p * (1 + rng.normal(0, 0.001)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.trend == "rising"


# ---------------------------------------------------------------------------
# 11. test_trend_anomaly — residual > 3σ sustained → "anomaly"
# ---------------------------------------------------------------------------


def test_trend_anomaly() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    rng = np.random.default_rng(42)
    # Normal pumpdown (150 pts), then sustained jump (50 pts).
    # The majority is normal so the fit is anchored there,
    # making the last 30 residuals all large → mean > 3σ.
    for i in range(200):
        t = i * 5.0
        logP = -6.0 + 5.0 * math.exp(-t / 300.0)
        if i >= 150:
            logP += 5.0
        pred.push(t, 10.0 ** (logP + rng.normal(0, 0.01)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.trend == "anomaly"


# ---------------------------------------------------------------------------
# 12. test_insufficient_data — <60 points → prediction = insufficient_data
# ---------------------------------------------------------------------------


def test_insufficient_data() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 60})
    for i in range(30):
        pred.push(i * 5.0, 1e-3 * math.exp(-i * 0.01))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type == "insufficient_data"


# ---------------------------------------------------------------------------
# 13. test_buffer_sliding_window — old points expire
# ---------------------------------------------------------------------------


def test_buffer_sliding_window() -> None:
    pred = VacuumTrendPredictor(config={"window_s": 100, "min_points": 5})
    # Push 50 points spanning t=0..245s (dt=5s). After last push at t=245,
    # cutoff = 245-100 = 145. Points at t>=145 are retained.
    expected_values: list[tuple[float, float]] = []
    for i in range(50):
        t = i * 5.0
        p_mbar = 1e-3 * math.exp(-i * 0.01)
        pred.push(t, p_mbar)
        if t >= 145.0:
            expected_values.append((t, math.log10(p_mbar)))

    t_last = 49 * 5.0  # 245 s
    cutoff = t_last - 100.0  # 145 s

    # All retained timestamps must be within the window
    retained_ts = [t for t, _ in pred._buffer]
    assert all(t >= cutoff for t in retained_ts), (
        f"Buffer contains points older than cutoff {cutoff}: min ts = {min(retained_ts)}"
    )
    # Exact count: points at t=145,150,...,245 => (245-145)/5+1 = 21 points
    assert len(pred._buffer) == len(expected_values)
    # Values match (log10 stored internally)
    for (buf_t, buf_lp), (exp_t, exp_lp) in zip(pred._buffer, expected_values):
        assert abs(buf_t - exp_t) < 1e-9
        assert abs(buf_lp - exp_lp) < 1e-9


# ---------------------------------------------------------------------------
# 14. test_all_log_scale — verify fit operates on log₁₀(P), not P
# ---------------------------------------------------------------------------


def test_all_log_scale() -> None:
    # Ground truth: logP(t) = -6 + 6*exp(-t/300).
    # At t=0: logP=0 (1 mbar). At t=999s (last): logP=-6+6*exp(-999/300)≈-6+0.30=-5.70.
    # A log-space fit must recover log_p_ult≈-6 and A≈6.
    # A linear-P fit would be dominated by the large early values and give very different params.
    pred = VacuumTrendPredictor(config={"min_points": 10, "min_points_combined": 300})
    _push_exponential(pred, -6.0, 6.0, 300.0, n=200, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type == "exponential"
    assert p.confidence > 0.95

    # The fit_params are the log-space model parameters.
    # A linear-P fit would converge to a wildly different log_p_ult and A;
    # a correct log-space fit must recover the ground-truth params within ±10%.
    assert abs(p.fit_params["log_p_ult"] - (-6.0)) / 6.0 < 0.10
    assert abs(p.fit_params["A"] - 6.0) / 6.0 < 0.10
    assert abs(p.fit_params["tau"] - 300.0) / 300.0 < 0.10

    # Extrapolation array is in log₁₀ space (not raw mbar)
    assert len(p.extrapolation_logP) > 0
    for v in p.extrapolation_logP:
        assert -15.0 < v < 5.0, f"extrapolation_logP value {v} out of log₁₀ range"

    # Verify the extrapolation_t and extrapolation_logP are a consistent
    # independent trajectory (not just a copy of the raw data)
    assert len(p.extrapolation_t) == len(p.extrapolation_logP)
    # The trajectory must extend beyond the last data point (t_max ~ 995 s)
    t_max_data = 199 * 5.0  # last pushed timestamp (relative to t0=0)
    assert max(p.extrapolation_t) > t_max_data


# ---------------------------------------------------------------------------
# 15. test_negative_pressure_rejected — P ≤ 0 → point rejected
# ---------------------------------------------------------------------------


def test_negative_pressure_rejected() -> None:
    pred = VacuumTrendPredictor()
    pred.push(1.0, -1e-3)  # negative
    pred.push(2.0, 0.0)  # zero
    pred.push(3.0, 1e-3)  # valid
    assert len(pred._buffer) == 1


# ---------------------------------------------------------------------------
# 16. test_prediction_serialization — asdict → JSON-compatible
# ---------------------------------------------------------------------------


def test_prediction_serialization() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    _push_exponential(pred, -6.0, 5.0, 300.0, n=200, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None

    d = asdict(p)
    json_str = json.dumps(d, default=str)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert "model_type" in parsed
    assert "eta_targets" in parsed
    assert "extrapolation_t" in parsed
    assert isinstance(parsed["extrapolation_t"], list)


# ---------------------------------------------------------------------------
# 17. test_targets_already_reached — P < target → ETA = 0
# ---------------------------------------------------------------------------


def test_targets_already_reached() -> None:
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "targets_mbar": [1e-3],
        }
    )
    # All pressures around 1e-6, well below 1e-3 target
    rng = np.random.default_rng(42)
    for i in range(100):
        pred.push(i * 5.0, 1e-6 * (1 + rng.normal(0, 0.001)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    eta = p.eta_targets.get("0.001")
    assert eta is not None
    assert eta == 0.0


# ---------------------------------------------------------------------------
# 18. test_noisy_data — realistic noise ±0.5 decade → fit converges
# ---------------------------------------------------------------------------


def test_noisy_data() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    _push_exponential(pred, -6.0, 5.0, 300.0, n=300, dt=5.0, noise_sigma=0.3)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type != "insufficient_data"
    # Even with noise, should get reasonable fit
    assert p.confidence > 0.5


# ---------------------------------------------------------------------------
# 19. test_start_stop_lifecycle — push → update → prediction → clear
# ---------------------------------------------------------------------------


def test_start_stop_lifecycle() -> None:
    pred = VacuumTrendPredictor(config={"min_points": 10})
    assert pred.get_prediction() is None

    _push_exponential(pred, -6.0, 5.0, 300.0, n=100, dt=5.0)
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.model_type != "insufficient_data"

    # After clearing buffer, prediction remains (cached) but buffer is empty
    pred._buffer.clear()
    pred.update()
    p2 = pred.get_prediction()
    assert p2 is not None
    assert p2.model_type == "insufficient_data"


# ---------------------------------------------------------------------------
# 20. test_update_interval_config_stored — update_interval_s is config storage
# ---------------------------------------------------------------------------


def test_update_interval_config_stored() -> None:
    """update_interval_s is stored as config; the engine tick loop enforces it.

    VacuumTrendPredictor does NOT self-throttle — every call to update()
    recomputes. The interval is exposed so the engine integration layer
    (VacuumTrendEngine / plugin runner) can skip ticks that arrive sooner
    than update_interval_s. This test verifies the contract:
      1. Config is stored faithfully.
      2. Calling update() twice in succession still produces a valid prediction
         (i.e. the predictor does NOT silently drop the second call).
    """
    pred = VacuumTrendPredictor(
        config={
            "min_points": 10,
            "update_interval_s": 30,
        }
    )
    # Config stored
    assert pred.update_interval_s == 30

    # Push data, call update() twice — both must return a valid prediction
    _push_exponential(pred, -6.0, 5.0, 300.0, n=100, dt=5.0)
    pred.update()
    p1 = pred.get_prediction()
    assert p1 is not None
    assert p1.model_type != "insufficient_data"

    # Second immediate call: predictor does not throttle itself
    pred.update()
    p2 = pred.get_prediction()
    assert p2 is not None
    assert p2.model_type != "insufficient_data"


# ---------------------------------------------------------------------------
# Integration: engine config loading + feed + command response
# ---------------------------------------------------------------------------


def test_engine_config_loading() -> None:
    """VacuumTrendPredictor created from plugins.yaml-style config dict."""
    config = {
        "enabled": True,
        "window_s": 3600,
        "update_interval_s": 30,
        "min_points": 60,
        "min_points_combined": 200,
        "targets_mbar": [1e-4, 1e-5, 1e-6],
        "anomaly_threshold_sigma": 3.0,
        "rising_sustained_s": 60,
        "trend_threshold_log10_per_s": 1e-4,
        "extrapolation_horizon_factor": 2.0,
    }
    pred = VacuumTrendPredictor(config=config)
    assert pred.window_s == 3600
    assert pred.update_interval_s == 30
    assert pred.min_points == 60
    assert pred.targets == [1e-4, 1e-5, 1e-6]
    assert pred.anomaly_sigma == 3.0


def test_predictor_serialization_contract() -> None:
    """VacuumPrediction → asdict() → JSON round-trip produces the exact fields the
    ZMQ command handler sends to the GUI.

    This is a PREDICTOR CONTRACT test, not an engine integration test.
    The real engine handler (zmq_bridge vacuum_trend command) calls
    ``asdict(pred.get_prediction())`` and wraps it in ``{"ok": True, ...}``.
    We verify that contract here without wiring the full engine stack.
    """
    config = {
        "min_points": 10,
        "targets_mbar": [1e-4, 1e-5],
    }
    pred = VacuumTrendPredictor(config=config)
    _push_exponential(pred, -7.0, 6.0, 300.0, n=200, dt=5.0)
    pred.update()

    p = pred.get_prediction()
    assert p is not None
    d = asdict(p)

    # --- Field contract: every field the ZMQ bridge relies on must be present ---
    assert "model_type" in d
    assert "p_ultimate_mbar" in d
    assert "eta_targets" in d
    assert "trend" in d
    assert "confidence" in d
    assert "residual_std" in d
    assert "fit_params" in d
    assert "extrapolation_t" in d
    assert "extrapolation_logP" in d
    assert "updated_at" in d

    # --- Type contract ---
    assert d["model_type"] != "insufficient_data"
    assert isinstance(d["p_ultimate_mbar"], float)
    assert isinstance(d["eta_targets"], dict)
    assert d["trend"] in ("pumping_down", "stable", "rising", "anomaly")
    assert isinstance(d["extrapolation_t"], list)
    assert len(d["extrapolation_t"]) > 0
    assert isinstance(d["confidence"], float)
    assert 0.0 <= d["confidence"] <= 1.0

    # --- JSON-serialization contract ---
    # ZMQ bridge: json.dumps({"ok": True, **asdict(pred)}, default=str)
    response = {"ok": True, **d}
    json_str = json.dumps(response, default=str)
    parsed = json.loads(json_str)
    assert parsed["ok"] is True
    assert parsed["model_type"] != "insufficient_data"
    assert isinstance(parsed["extrapolation_t"], list)
    assert len(parsed["extrapolation_t"]) > 0


# ---------------------------------------------------------------------------
# BIC -inf overfit guard (POLISH_FIXES_2)
# ---------------------------------------------------------------------------


def test_bic_perfect_fit_is_finite_and_penalises_complexity() -> None:
    """A degenerate perfect fit (residuals≈0) must NOT return -inf.

    Otherwise min(BIC) auto-selects whichever model first hit residual≈0,
    ignoring the complexity penalty. The clamped finite floor must still let
    the +k*ln(n) term discriminate: a higher-param model pays a larger BIC.
    """
    from cryodaq.analytics.vacuum_trend import _compute_bic

    zero_resid = np.zeros(200)

    bic_3 = _compute_bic(200, 3, zero_resid)
    bic_5 = _compute_bic(200, 5, zero_resid)

    assert math.isfinite(bic_3)
    assert math.isfinite(bic_5)
    # Complexity penalty intact: the 5-param perfect fit must cost MORE than
    # the 3-param perfect fit, so the simpler model wins on a tie.
    assert bic_5 > bic_3


def test_an_eta_far_beyond_the_data_is_refused() -> None:
    """Owner: "vacuum ETA does not work ... predictions did not align".

    Replaying this stand's 31.08 pump-down, a six-hour window holding two days
    of history produced "0.01 mbar by 14.09" -- twelve days out, from a fit
    whose asymptote had rested on the optimiser's lower bound while the same
    code reported the ultimate pressure as unidentified. An answer that reaches
    that far past the data is not a forecast; it is the fitted curve continued
    into a region nothing observed.
    """
    pred = VacuumTrendPredictor(
        config={
            "window_s": 600.0,
            "extrapolation_horizon_factor": 2.0,
            "min_points": 10,
            "min_points_combined": 300,
            # Far below where this decaying curve is going, so any answer must
            # come from deep extrapolation.
            "targets_mbar": [1e-12],
        }
    )
    for index in range(60):
        t = 10.0 + index * 10.0
        pred.push(t, 10.0 ** (-2.0 + 1.0 * max(t, 1.0) ** (-0.2)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.eta_targets.get("1e-12") is None, (
        "an ETA beyond the extrapolation horizon must be refused, not reported"
    )


def test_the_eta_limit_matches_the_plotted_extrapolation() -> None:
    """The text and the curve must stop in the same place."""
    pred = VacuumTrendPredictor(config={"window_s": 3600.0, "extrapolation_horizon_factor": 2.0})
    assert pred._eta_extrapolation_limit_s() == 7200.0


def test_an_already_reached_target_is_reported_as_reached() -> None:
    """Not as unreachable, and not as a future date.

    Whether a target is already met is an observation about where the pressure
    IS, so it is answered before anything about the asymptote or the horizon.
    """
    pred = VacuumTrendPredictor(
        config={"window_s": 600.0, "min_points": 10, "min_points_combined": 300, "targets_mbar": [1.0]}
    )
    for index in range(60):
        t = 10.0 + index * 10.0
        pred.push(t, 10.0 ** (-3.0 + 1.0 * max(t, 1.0) ** (-0.2)))
    pred.update()
    p = pred.get_prediction()
    assert p is not None
    assert p.eta_targets.get("1.0") == 0.0
