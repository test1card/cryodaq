"""v0.55.3 — CooldownService.expected_value() contract.

Three cases:

1. ``expected_value`` returns ``None`` when the service is idle (no
   detector phase entered COOLING / STABILIZING yet).
2. ``expected_value`` returns ``None`` when no model is loaded.
3. During COOLING with a cached prediction trajectory, ``expected_value``
   interpolates ``future_T_cold_mean`` correctly and reports
   sigma = (upper - lower) / 2.

The tests construct CooldownService directly and tweak its private
attributes (``_model``, ``_last_prediction_raw``, ``_detector.phase``,
``_cooldown_wall_start``) — full integration is covered by the existing
``test_cooldown_service.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from cryodaq.analytics.cooldown_predictor import PredictionResult
from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService
from cryodaq.core.broker import DataBroker


def _make_service(tmp_path: Path) -> CooldownService:
    cfg = {
        "channel_cold": "T_cold",
        "channel_warm": "T_warm",
        "predict_interval_s": 60.0,
        "rate_window_h": 0.01,
        "auto_ingest": False,
        "min_cooldown_hours": 0.001,
        "detect": {
            "start_rate_threshold": -5.0,
            "start_confirm_minutes": 0.01,
            "end_T_cold_threshold": 6.0,
            "end_rate_threshold": 0.1,
            "end_confirm_minutes": 0.01,
        },
    }
    return CooldownService(
        broker=DataBroker(),
        config=cfg,
        model_dir=tmp_path / "model",
    )


def test_returns_none_when_idle(tmp_path: Path) -> None:
    """C1 — service hasn't seen cooldown start; expected_value must be None."""
    svc = _make_service(tmp_path)
    # No model yet, no prediction cached, phase = IDLE.
    assert svc.phase == CooldownPhase.IDLE
    assert svc.expected_value("T_cold", ts_monotonic=1.0) is None


def test_returns_none_when_no_model(tmp_path: Path) -> None:
    """C2 — phase advanced to COOLING by hand, but no model loaded."""
    svc = _make_service(tmp_path)
    svc._detector._phase = CooldownPhase.COOLING
    svc._cooldown_wall_start = 1000.0
    # _model is still None; expected_value must short-circuit.
    assert svc.expected_value("T_cold", ts_monotonic=2000.0) is None


def test_returns_value_during_cooling(tmp_path: Path) -> None:
    """C3 — during COOLING with a cached prediction, expected_value
    interpolates correctly and reports half-band sigma.
    """
    svc = _make_service(tmp_path)
    svc._model = MagicMock()  # presence is enough; we don't run predict()
    svc._detector._phase = CooldownPhase.COOLING
    svc._cooldown_wall_start = 1000.0  # arbitrary monotonic anchor

    # Synthetic linear cooldown trajectory: 100 K → 50 K over 4 hours.
    future_t = np.array([0.0, 1.0, 2.0, 3.0, 4.0])  # hours since cooldown_start
    future_mean = np.array([100.0, 87.5, 75.0, 62.5, 50.0])
    future_upper = future_mean + np.array([1.0, 1.5, 2.0, 2.5, 3.0])
    future_lower = future_mean - np.array([1.0, 1.5, 2.0, 2.5, 3.0])

    pred = PredictionResult(
        t_remaining_hours=4.0,
        t_remaining_low_68=3.5,
        t_remaining_high_68=4.5,
        t_remaining_low_95=3.0,
        t_remaining_high_95=5.0,
        t_total_hours=4.0,
        progress=0.0,
        phase="phase1",
        T_cold_predicted_final=50.0,
        T_warm_predicted_final=70.0,
        n_references=3,
        individual_estimates=[],
        future_t=future_t,
        future_T_cold_mean=future_mean,
        future_T_cold_upper=future_upper,
        future_T_cold_lower=future_lower,
    )
    svc._last_prediction_raw = pred

    # Query at t = cooldown_start + 2h (= ts_monotonic 1000 + 7200).
    result = svc.expected_value("T_cold", ts_monotonic=1000.0 + 7200.0)
    assert result is not None
    mean_val, sigma = result
    assert mean_val == pytest.approx(75.0, rel=1e-6)
    assert sigma == pytest.approx(2.0, rel=1e-6)

    # Out-of-horizon query → None.
    assert svc.expected_value("T_cold", ts_monotonic=1000.0 - 1.0) is None
    assert (
        svc.expected_value("T_cold", ts_monotonic=1000.0 + 5.0 * 3600.0) is None
    )

    # Unknown channel → None even with cached prediction.
    assert svc.expected_value("UnknownChannel", ts_monotonic=1000.0 + 7200.0) is None


def test_returns_none_for_warm_channel_when_no_warm_arrays(tmp_path: Path) -> None:
    """Cold-only PredictionResult does not satisfy a warm-channel query."""
    svc = _make_service(tmp_path)
    svc._model = MagicMock()
    svc._detector._phase = CooldownPhase.COOLING
    svc._cooldown_wall_start = 1000.0

    pred = PredictionResult(
        t_remaining_hours=2.0,
        t_remaining_low_68=1.5,
        t_remaining_high_68=2.5,
        t_remaining_low_95=1.0,
        t_remaining_high_95=3.0,
        t_total_hours=2.0,
        progress=0.0,
        phase="phase1",
        T_cold_predicted_final=50.0,
        T_warm_predicted_final=70.0,
        n_references=1,
        individual_estimates=[],
        future_t=np.array([0.0, 1.0, 2.0]),
        future_T_cold_mean=np.array([100.0, 75.0, 50.0]),
        future_T_cold_upper=np.array([101.0, 76.0, 51.0]),
        future_T_cold_lower=np.array([99.0, 74.0, 49.0]),
        # warm fields stay None — ensemble didn't cover warm side.
    )
    svc._last_prediction_raw = pred

    # Cold side resolves; warm side returns None because arrays are missing.
    assert (
        svc.expected_value("T_cold", ts_monotonic=1000.0 + 3600.0) is not None
    )
    assert (
        svc.expected_value("T_warm", ts_monotonic=1000.0 + 3600.0) is None
    )
