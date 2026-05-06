"""F-MockPredictor — CooldownPredictionWidget steady-state asymptote display.

Cycle 2: cold-stage temperature flows through ``set_cold_temperature_reading``
(architect direction a2). ``CooldownData.actual_trajectory`` stays empty by
contract; the widget owns its raw buffer + predictor feed, mirroring
``VacuumPredictionWidget`` and ``RThermalLiveWidget``.

Covers:
1. Construction — overlays hidden, placeholder visible, raw buffer empty.
2. ``set_cooldown_data(None)`` — overlays hidden, stale prediction cleared.
3. Active prediction (predicted+ci) — trajectory rendered, asymptote hidden.
4. ``set_cold_temperature_reading`` populates raw buffer, predictor, and inner
   history; only new timestamps are forwarded to the predictor.
5. Raw buffer caps at ``_MAX_RAW_PTS``.
6. Settled predictor — asymptote line + band + badge visible.
7. Unsettled / invalid predictor — placeholder visible, overlays hidden.
8. State transitions clear stale prediction curves on ``self._inner``.
9. Asymptote position == ``t_predicted``; band == ±sigma.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
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
    predicted: list[tuple[float, float]] | None = None,
    ci: list[tuple[float, float, float]] | None = None,
):
    """Minimal duck-type for CooldownData (predicted / ci only — actual stays empty)."""
    d = MagicMock()
    d.actual_trajectory = []
    d.predicted_trajectory = predicted or []
    d.ci_trajectory = ci or []
    return d


def _reading(ts: float, val: float):
    """Minimal duck-type for cryodaq.drivers.base.Reading."""
    r = MagicMock()
    r.timestamp = datetime.fromtimestamp(ts, tz=UTC)
    r.value = val
    return r


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
    assert w._raw_cold_buffer == []


# 2. None data
def test_none_data_shows_placeholder_and_clears_prediction(app) -> None:
    w = CooldownPredictionWidget()
    w._asym_line.setVisible(True)
    w._asym_band.setVisible(True)
    w._steady_badge.setVisible(True)
    w._placeholder.setVisible(False)

    with patch.object(w._inner, "set_prediction") as mock_set:
        w.set_cooldown_data(None)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()
    mock_set.assert_called_once_with([], [], [], ci_level_pct=67.0)


# 3. Active prediction — trajectory path
def test_active_prediction_renders_trajectory(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()
    data = _cooldown_data(
        predicted=[(now + 60, 80.0), (now + 120, 70.0)],
        ci=[(now + 60, 75.0, 85.0), (now + 120, 65.0, 75.0)],
    )

    with patch.object(w._ss_predictor, "get_prediction", return_value=None):
        w.set_cooldown_data(data)

    assert not w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


# 4. Cold reading feeds buffer + predictor + history
def test_cold_reading_feeds_buffer_predictor_and_history(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()

    add_calls: list[tuple] = []
    original_add = w._ss_predictor.add_point

    def spy_add(channel, ts, val):
        add_calls.append((channel, ts, val))
        original_add(channel, ts, val)

    w._ss_predictor.add_point = spy_add  # type: ignore[method-assign]

    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._inner, "set_history") as mock_set_history:
            w.set_cold_temperature_reading(_reading(now, 4.5))
            w.set_cold_temperature_reading(_reading(now + 1, 4.51))
            # Same ts again — must NOT increment add_calls (no double-feed).
            w.set_cold_temperature_reading(_reading(now + 1, 4.51))

    assert len(w._raw_cold_buffer) == 3
    # Two adds (third is suppressed as a duplicate ts).
    assert len(add_calls) == 2
    assert add_calls[0][0] == "cold_stage"
    assert add_calls[0][1] == pytest.approx(now, abs=1e-3)
    assert add_calls[0][2] == 4.5
    assert add_calls[1][0] == "cold_stage"
    assert add_calls[1][1] == pytest.approx(now + 1, abs=1e-3)
    assert add_calls[1][2] == 4.51
    assert w._last_ts_seen == pytest.approx(now + 1, abs=1e-3)
    assert mock_set_history.call_count == 3
    last_history = mock_set_history.call_args_list[-1].args[0]
    assert len(last_history) == 3
    assert [v for _, v in last_history] == [4.5, 4.51, 4.51]


def test_cold_reading_none_is_noop(app) -> None:
    w = CooldownPredictionWidget()
    with patch.object(w._ss_predictor, "add_point") as mock_add:
        w.set_cold_temperature_reading(None)
    assert w._raw_cold_buffer == []
    mock_add.assert_not_called()


# 5. Buffer cap
def test_cold_reading_buffer_caps_at_max_raw_pts(app) -> None:
    w = CooldownPredictionWidget()
    cap = w._MAX_RAW_PTS
    now = time.time()

    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._inner, "set_history"):
            for i in range(cap + 50):
                w.set_cold_temperature_reading(_reading(now + i, 4.5))

    assert len(w._raw_cold_buffer) == cap
    # Trimming drops the oldest 50 — first remaining ts should be now+50.
    assert w._raw_cold_buffer[0][0] == pytest.approx(now + 50)


# 6. Settled predictor
def test_steady_state_shows_asymptote_and_badge(app) -> None:
    w = CooldownPredictionWidget()
    data = _cooldown_data()  # no active prediction
    pred = _steady_pred(t_predicted=4.5, percent_settled=60.0, valid=True)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
        w.set_cooldown_data(data)

    assert w._asym_line.isVisible()
    assert w._asym_band.isVisible()
    assert w._steady_badge.isVisible()
    assert not w._placeholder.isVisible()
    assert "Стационарное состояние" in w._steady_badge.toPlainText()
    assert "4.50" in w._steady_badge.toPlainText()


# 7. Unsettled / invalid predictor
def test_unsettled_predictor_shows_placeholder(app) -> None:
    w = CooldownPredictionWidget()
    data = _cooldown_data()
    pred_low = _steady_pred(percent_settled=15.0)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_low):
        w.set_cooldown_data(data)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


def test_invalid_predictor_shows_placeholder(app) -> None:
    w = CooldownPredictionWidget()
    data = _cooldown_data()
    pred_invalid = _steady_pred(percent_settled=80.0, valid=False)

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_invalid):
        w.set_cooldown_data(data)

    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()


# 8. Stale-prediction clear on transition
def test_set_cooldown_data_steady_clears_prior_prediction(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()

    # First: an active prediction populates self._inner curves.
    active = _cooldown_data(
        predicted=[(now + 60, 80.0)],
        ci=[(now + 60, 75.0, 85.0)],
    )
    with patch.object(w._ss_predictor, "get_prediction", return_value=None):
        w.set_cooldown_data(active)
    # Inner central curve has data points after active push.
    assert len(w._inner._central) == 1

    # Then: a steady-state push must clear the inner prediction first.
    steady = _cooldown_data()
    pred_settled = _steady_pred(percent_settled=70.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_settled):
        w.set_cooldown_data(steady)

    assert w._asym_line.isVisible()
    assert w._inner._central == []
    assert w._inner._lower_ci == []
    assert w._inner._upper_ci == []


def test_set_cooldown_data_inactive_clears_prior_prediction(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()

    active = _cooldown_data(
        predicted=[(now + 60, 80.0)],
        ci=[(now + 60, 75.0, 85.0)],
    )
    with patch.object(w._ss_predictor, "get_prediction", return_value=None):
        w.set_cooldown_data(active)
    assert len(w._inner._central) == 1

    inactive = _cooldown_data()
    pred_unsettled = _steady_pred(percent_settled=10.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_unsettled):
        w.set_cooldown_data(inactive)

    assert w._placeholder.isVisible()
    assert w._inner._central == []


def test_active_to_steady_to_inactive_transitions(app) -> None:
    w = CooldownPredictionWidget()
    now = time.time()

    active = _cooldown_data(
        predicted=[(now + 60, 80.0)],
        ci=[(now + 60, 75.0, 85.0)],
    )
    with patch.object(w._ss_predictor, "get_prediction", return_value=None):
        w.set_cooldown_data(active)
    assert not w._asym_line.isVisible()
    assert not w._placeholder.isVisible()

    steady = _cooldown_data()
    pred_settled = _steady_pred(percent_settled=70.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_settled):
        w.set_cooldown_data(steady)
    assert w._asym_line.isVisible()
    assert w._steady_badge.isVisible()

    inactive = _cooldown_data()
    pred_unsettled = _steady_pred(percent_settled=10.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=pred_unsettled):
        w.set_cooldown_data(inactive)
    assert w._placeholder.isVisible()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()


# 9. Asymptote position and band
def test_asymptote_position_and_band(app) -> None:
    w = CooldownPredictionWidget()
    data = _cooldown_data()
    pred = _steady_pred(
        t_predicted=4.5,
        amplitude=90.0,
        percent_settled=70.0,
        confidence=0.8,
    )
    expected_sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)  # 18.0

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
        w.set_cooldown_data(data)

    assert w._asym_line.value() == pytest.approx(4.5, rel=1e-6)
    lo, hi = w._asym_band.getRegion()
    assert lo == pytest.approx(4.5 - expected_sigma, rel=1e-6)
    assert hi == pytest.approx(4.5 + expected_sigma, rel=1e-6)
