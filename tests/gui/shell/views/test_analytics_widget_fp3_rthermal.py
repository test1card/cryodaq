"""F-P3 RThermalLiveWidget asymptote overlay — unit tests.

Covers acceptance criteria:
1. Widget creates without crash; asymptote items hidden initially.
2. set_r_thermal_data(None) → overlay hidden, curve cleared.
3. Predictor not converged (percent_settled < 30%) → overlay hidden.
4. Valid converged prediction → asymptote line and band visible.
5. Asymptote line positioned at t_predicted; band covers ±sigma.
6. Phase transition: converged → not-converged → overlay hides.
7. Only new history points fed to predictor (no duplicate timestamps).
8. High-confidence prediction → narrow band (sigma shrinks).
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.analytics.steady_state import SteadyStatePrediction
from cryodaq.gui.shell.views.analytics_widgets import RThermalLiveWidget


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _r_thermal_data(
    current: float | None = 0.12,
    delta: float | None = -0.001,
    history: list[tuple[float, float]] | None = None,
):
    """Minimal duck-type for RThermalData."""
    d = MagicMock()
    d.current_value = current
    d.delta_per_minute = delta
    d.history = history or []
    return d


def _steady_pred(
    t_predicted: float = 0.10,
    amplitude: float = 0.05,
    percent_settled: float = 60.0,
    confidence: float = 0.9,
    valid: bool = True,
) -> SteadyStatePrediction:
    return SteadyStatePrediction(
        channel="R_thermal",
        t_predicted=t_predicted,
        t_current=t_predicted + amplitude * 0.5,
        tau_s=200.0,
        amplitude=amplitude,
        percent_settled=percent_settled,
        confidence=confidence,
        valid=valid,
    )


# ---------------------------------------------------------------------------
# 1. Construction — overlay items hidden
# ---------------------------------------------------------------------------


def test_construction_overlay_hidden(app) -> None:
    w = RThermalLiveWidget()
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert w._last_r_ts == 0.0


# ---------------------------------------------------------------------------
# 2. set_r_thermal_data(None) → overlay hidden
# ---------------------------------------------------------------------------


def test_none_data_hides_overlay(app) -> None:
    w = RThermalLiveWidget()
    # Manually show the overlay first
    w._asym_line.setVisible(True)
    w._asym_band.setVisible(True)
    w.set_r_thermal_data(None)
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()


# ---------------------------------------------------------------------------
# 3. Not converged → overlay hidden
# ---------------------------------------------------------------------------


def test_not_converged_overlay_hidden(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now - 100 + i, 0.15 - i * 0.001) for i in range(10)]
    not_converged = _steady_pred(percent_settled=15.0)

    with patch.object(w._ss_predictor, "get_prediction", return_value=not_converged):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()


# ---------------------------------------------------------------------------
# 4. Valid converged prediction → overlay visible
# ---------------------------------------------------------------------------


def test_converged_overlay_visible(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now - 100 + i, 0.15 - i * 0.001) for i in range(10)]
    converged = _steady_pred(t_predicted=0.10, percent_settled=60.0, valid=True)

    with patch.object(w._ss_predictor, "get_prediction", return_value=converged):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    assert w._asym_line.isVisible()
    assert w._asym_band.isVisible()


# ---------------------------------------------------------------------------
# 5. Asymptote line position and band region correct
# ---------------------------------------------------------------------------


def test_overlay_position_and_band(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now - 100 + i, 0.15) for i in range(5)]
    pred = _steady_pred(
        t_predicted=0.10,
        amplitude=0.04,
        percent_settled=70.0,
        confidence=0.8,
    )
    expected_sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)  # 0.04 * 0.2 = 0.008

    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))

    assert w._asym_line.value() == pytest.approx(0.10, rel=1e-6)
    lo, hi = w._asym_band.getRegion()
    assert lo == pytest.approx(0.10 - expected_sigma, rel=1e-6)
    assert hi == pytest.approx(0.10 + expected_sigma, rel=1e-6)


# ---------------------------------------------------------------------------
# 6. Phase transition: converged → not-converged → overlay hides
# ---------------------------------------------------------------------------


def test_overlay_hides_on_deconvergence(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now - 100 + i, 0.15) for i in range(5)]

    # First call: converged
    converged = _steady_pred(percent_settled=65.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=converged):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    assert w._asym_line.isVisible()

    # Second call: not converged (e.g. fresh R_thermal data arrived)
    not_converged = _steady_pred(percent_settled=10.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=not_converged):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()


# ---------------------------------------------------------------------------
# 7. Only new history points fed to predictor (no duplicate timestamps)
# ---------------------------------------------------------------------------


def test_no_duplicate_timestamps_in_predictor(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history_a = [(now + i, 0.15 - i * 0.001) for i in range(5)]
    history_b = history_a + [(now + 5, 0.145), (now + 6, 0.144)]

    add_calls: list[tuple] = []
    original_add = w._ss_predictor.add_point

    def spy_add(channel, ts, val):
        add_calls.append((ts, val))
        original_add(channel, ts, val)

    w._ss_predictor.add_point = spy_add  # type: ignore[method-assign]

    with patch.object(w._ss_predictor, "update"):
        with patch.object(w._ss_predictor, "get_prediction", return_value=None):
            w.set_r_thermal_data(_r_thermal_data(history=history_a))
            first_count = len(add_calls)
            w.set_r_thermal_data(_r_thermal_data(history=history_b))
            second_count = len(add_calls)

    assert first_count == 5
    # Only 2 new points added on second call (not re-adding 5 old ones)
    assert second_count - first_count == 2


# ---------------------------------------------------------------------------
# 8a. Empty history on non-None data hides stale overlay
# ---------------------------------------------------------------------------


def test_empty_history_hides_stale_overlay(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now + i, 0.15) for i in range(5)]

    # First call: converged, overlay visible
    converged = _steady_pred(percent_settled=65.0)
    with patch.object(w._ss_predictor, "get_prediction", return_value=converged):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    assert w._asym_line.isVisible()

    # Second call: non-None data but empty history — overlay must hide
    with patch.object(w._ss_predictor, "update"):
        w.set_r_thermal_data(_r_thermal_data(history=[]))
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()


# ---------------------------------------------------------------------------
# 8. High-confidence prediction → narrow band
# ---------------------------------------------------------------------------


def test_high_confidence_narrow_band(app) -> None:
    w = RThermalLiveWidget()
    now = time.time()
    history = [(now + i, 0.15) for i in range(5)]

    low_conf = _steady_pred(amplitude=0.05, confidence=0.5, percent_settled=50.0)
    high_conf = _steady_pred(amplitude=0.05, confidence=0.99, percent_settled=50.0)

    with patch.object(w._ss_predictor, "get_prediction", return_value=low_conf):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    lo_lc, hi_lc = w._asym_band.getRegion()
    band_width_low = hi_lc - lo_lc

    with patch.object(w._ss_predictor, "get_prediction", return_value=high_conf):
        with patch.object(w._ss_predictor, "update"):
            w.set_r_thermal_data(_r_thermal_data(history=history))
    lo_hc, hi_hc = w._asym_band.getRegion()
    band_width_high = hi_hc - lo_hc

    assert band_width_high < band_width_low
