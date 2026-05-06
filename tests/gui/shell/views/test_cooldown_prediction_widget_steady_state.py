"""F-MockPredictor — CooldownPredictionWidget steady-state asymptote display.

Mirrors the FP3 RThermalLiveWidget test pattern (mock SteadyStatePrediction
to drive the convergence branch deterministically — avoids depending on
scipy curve_fit success in tests).

Covers:
1. Construction — overlays hidden, placeholder visible.
2. set_cooldown_data(None) — overlays hidden, placeholder visible.
3. Active prediction (predicted+ci) — trajectory rendered, asymptote hidden.
4. No active prediction + settled predictor — asymptote line + band + badge visible.
5. No active prediction + unsettled predictor — placeholder visible, overlays hidden.
6. Active → steady → inactive transitions hide stale overlays.
7. Predictor only fed timestamps it has not seen (no double-feed).
8. Asymptote position == t_predicted; band == ±sigma.
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.analytics.steady_state import SteadyStatePrediction
from cryodaq.gui.shell.views.analytics_widgets import CooldownPredictionWidget


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _cooldown_data(
    actual: list[tuple[float, float]] | None = None,
    predicted: list[tuple[float, float]] | None = None,
    ci: list[tuple[float, float, float]] | None = None,
):
    """Minimal duck-type for CooldownData (actual / predicted / ci trajectories)."""
    d = MagicMock()
    d.actual_trajectory = actual or []
    d.predicted_trajectory = predicted or []
    d.ci_trajectory = ci or []
    return d


def _steady_pred(
    t_predicted: float = 4.5,
    amplitude: float = 90.0,
    percent_settled: float = 60.0,
    confidence: float = 0.9,
    valid: bool = True,
) -> SteadyStatePrediction:
    return SteadyStatePrediction(
        channel="cold_stage",
        t_predicted=t_predicted,
        t_current=t_predicted + amplitude * 0.05,
        tau_s=200.0,
        amplitude=amplitude,
        percent_settled=percent_settled,
        confidence=confidence,
        valid=valid,
    )


# 1. Construction
def test_construction_overlays_hidden(app) -> None:
    w = CooldownPredictionWidget()
    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()
    assert w._last_ts_seen == 0.0


# 2. None data
def test_none_data_shows_placeholder(app) -> None:
    w = CooldownPredictionWidget()
    # Force overlays visible to verify they get cleared.
    w._asym_line.setVisible(True)
    w._asym_band.setVisible(True)
    w._steady_badge.setVisible(True)
    w._placeholder.setVisible(False)

    w.set_cooldown_data(None)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


# 3. Active prediction — trajectory path
def test_active_prediction_renders_trajectory(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(
        actual=[(now - 60, 100.0), (now, 90.0)],
        predicted=[(now + 60, 80.0), (now + 120, 70.0)],
        ci=[(now + 60, 75.0, 85.0), (now + 120, 65.0, 75.0)],
    )

    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=None):
            w.set_cooldown_data(data)

    assert not w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


# 4. Steady state — asymptote visible
def test_steady_state_shows_asymptote_and_badge(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(actual=[(now - 60, 4.5), (now, 4.5)])
    pred = _steady_pred(t_predicted=4.5, percent_settled=60.0, valid=True)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
        with patch.object(w._ss_predictor, "update"):
            w.set_cooldown_data(data)

    assert w._asym_line.isVisible()
    assert w._asym_band.isVisible()
    assert w._steady_badge.isVisible()
    assert not w._placeholder.isVisible()
    assert "Стационарное состояние" in w._steady_badge.toPlainText()
    assert "4.50" in w._steady_badge.toPlainText()


# 5. Unsettled predictor — placeholder
def test_unsettled_predictor_shows_placeholder(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(actual=[(now, 100.0)])
    pred_low = _steady_pred(percent_settled=15.0)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_low):
        with patch.object(w._ss_predictor, "update"):
            w.set_cooldown_data(data)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


def test_invalid_predictor_shows_placeholder(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(actual=[(now, 100.0)])
    pred_invalid = _steady_pred(percent_settled=80.0, valid=False)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_invalid):
        with patch.object(w._ss_predictor, "update"):
            w.set_cooldown_data(data)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()


# 6. Transition: active → steady → inactive
def test_active_to_steady_to_inactive_transitions(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()

    # Active
    active = _cooldown_data(
        actual=[(now, 90.0)],
        predicted=[(now + 60, 80.0)],
        ci=[(now + 60, 75.0, 85.0)],
    )
    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=None):
            w.set_cooldown_data(active)
    assert not w._asym_line.isVisible()
    assert not w._placeholder.isVisible()

    # Steady
    steady_data = _cooldown_data(actual=[(now + 5, 4.5)])
    pred_settled = _steady_pred(percent_settled=70.0)
    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=pred_settled):
            w.set_cooldown_data(steady_data)
    assert w._asym_line.isVisible()
    assert w._steady_badge.isVisible()

    # Inactive (no prediction, predictor lost convergence)
    inactive = _cooldown_data(actual=[(now + 10, 4.5)])
    pred_unsettled = _steady_pred(percent_settled=10.0)
    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=pred_unsettled):
            w.set_cooldown_data(inactive)
    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


# 7. No double-feed
def test_predictor_only_fed_new_timestamps(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data_a = _cooldown_data(actual=[(now + i, 100.0 - i) for i in range(5)])
    data_b = _cooldown_data(
        actual=[(now + i, 100.0 - i) for i in range(5)]
        + [(now + 5, 95.0), (now + 6, 94.0)]
    )

    add_calls: list[tuple] = []
    original_add = w._ss_predictor.add_point

    def spy_add(channel, ts, val):
        add_calls.append((ts, val))
        original_add(channel, ts, val)

    w._ss_predictor.add_point = spy_add  # type: ignore[method-assign]

    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=None):
            w.set_cooldown_data(data_a)
            first_count = len(add_calls)
            w.set_cooldown_data(data_b)
            second_count = len(add_calls)

    assert first_count == 5
    assert second_count - first_count == 2
    assert w._last_ts_seen == pytest.approx(now + 6)


# 8. Asymptote position and band
def test_asymptote_position_and_band(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(actual=[(now, 4.5)])
    pred = _steady_pred(
        t_predicted=4.5,
        amplitude=90.0,
        percent_settled=70.0,
        confidence=0.8,
    )
    expected_sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)  # 90 * 0.2 = 18

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
        with patch.object(w._ss_predictor, "update"):
            w.set_cooldown_data(data)

    assert w._asym_line.value() == pytest.approx(4.5, rel=1e-6)
    lo, hi = w._asym_band.getRegion()
    assert lo == pytest.approx(4.5 - expected_sigma, rel=1e-6)
    assert hi == pytest.approx(4.5 + expected_sigma, rel=1e-6)
