"""F-P2 VacuumPredictionWidget — unit tests.

Covers acceptance criteria:
1. Widget creates without crash, polling timer starts.
2. set_pressure_reading() accumulates raw history into inner widget.
3. No-data ZMQ result → no prediction rendered (graceful).
4. ok=False ZMQ result → no prediction rendered (graceful).
5. Valid ZMQ result → central/lower/upper computed and forwarded to inner widget.
6. residual_std=0 → lower=upper=central (degenerate band, no crash).
7. NaN/inf in logP skipped cleanly.
8. Raw buffer capped at MAX_RAW_PTS (no memory growth).
9. Legacy set_vacuum_prediction() path still works.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views.analytics_widgets import VacuumPredictionWidget


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _make_reading(value: float, ts: float | None = None) -> Reading:
    if ts is None:
        ts = 1_000_000.0
    return Reading(
        channel="vacuum/pressure",
        value=value,
        unit="mbar",
        instrument_id="thyracont",
        timestamp=datetime.fromtimestamp(ts, tz=UTC),
    )


def _make_trend_result(
    extrap_t: list | None = None,
    extrap_logP: list | None = None,
    residual_std: float = 0.05,
    ok: bool = True,
    status: str | None = None,
) -> dict:
    result: dict = {
        "ok": ok,
        "extrapolation_t": extrap_t or [1000.0, 2000.0, 3000.0, 4000.0, 5000.0],
        "extrapolation_logP": extrap_logP or [-4.0, -4.5, -5.0, -5.5, -6.0],
        "residual_std": residual_std,
    }
    if status is not None:
        result["status"] = status
    return result


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


def test_construction_no_crash(app) -> None:
    w = VacuumPredictionWidget()
    assert w._inner is not None
    assert w._poll_timer is not None
    assert w._poll_timer.isActive()
    assert w._raw_buffer == []


# ---------------------------------------------------------------------------
# 2. set_pressure_reading accumulates history
# ---------------------------------------------------------------------------


def test_set_pressure_reading_accumulates(app) -> None:
    w = VacuumPredictionWidget()
    w.set_pressure_reading(_make_reading(1e-4, ts=1_000_000.0))
    w.set_pressure_reading(_make_reading(5e-5, ts=1_000_001.0))
    assert len(w._raw_buffer) == 2
    assert w._raw_buffer[0] == pytest.approx((1_000_000.0, 1e-4), rel=1e-6)
    assert w._raw_buffer[1] == pytest.approx((1_000_001.0, 5e-5), rel=1e-6)


def test_set_pressure_reading_updates_inner_history(app) -> None:
    w = VacuumPredictionWidget()
    calls = []
    w._inner.set_history = lambda data: calls.append(list(data))  # type: ignore[method-assign]
    w.set_pressure_reading(_make_reading(1e-4, ts=1_000_000.0))
    assert len(calls) == 1
    assert calls[0][0][1] == pytest.approx(1e-4, rel=1e-6)


# ---------------------------------------------------------------------------
# 3. No-data result → no prediction
# ---------------------------------------------------------------------------


def test_no_data_status_clears_prediction(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central, "lower": lower, "upper": upper}
    )
    w._on_trend_result({"ok": True, "status": "no_data"})
    # Fix: clears any previously-rendered forecast with empty lists
    assert len(pred_calls) == 1
    assert pred_calls[0] == {"central": [], "lower": [], "upper": []}


# ---------------------------------------------------------------------------
# 4. ok=False → no prediction
# ---------------------------------------------------------------------------


def test_ok_false_clears_prediction(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central}
    )
    w._on_trend_result({"ok": False})
    # Fix: clears any previously-rendered forecast with empty lists
    assert len(pred_calls) == 1
    assert pred_calls[0]["central"] == []


# ---------------------------------------------------------------------------
# 5. Valid result → prediction forwarded with correct shape
# ---------------------------------------------------------------------------


def test_valid_result_prediction_forwarded(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central, "lower": lower, "upper": upper, "ci": ci_level_pct}
    )
    result = _make_trend_result(
        extrap_t=[1000.0, 2000.0, 3000.0],
        extrap_logP=[-4.0, -5.0, -6.0],
        residual_std=0.5,
    )
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)
    assert len(pred_calls) == 1
    c = pred_calls[0]
    # 3 points, all finite
    assert len(c["central"]) == 3
    assert len(c["lower"]) == 3
    assert len(c["upper"]) == 3
    # central pressure values are in mbar (10^logP)
    assert c["central"][0][1] == pytest.approx(10.0**-4.0, rel=1e-6)
    assert c["central"][1][1] == pytest.approx(10.0**-5.0, rel=1e-6)
    # lower < central < upper for same t
    assert c["lower"][0][1] < c["central"][0][1] < c["upper"][0][1]
    # CI level
    assert c["ci"] == pytest.approx(68.0)


# ---------------------------------------------------------------------------
# 6. residual_std=0 → lower=upper=central (no band crash)
# ---------------------------------------------------------------------------


def test_zero_residual_std_no_crash(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central, "lower": lower, "upper": upper}
    )
    result = _make_trend_result(residual_std=0.0)
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)
    assert len(pred_calls) == 1
    c = pred_calls[0]
    # lower = central = upper when residual_std=0
    assert c["lower"] == c["central"]
    assert c["upper"] == c["central"]


# ---------------------------------------------------------------------------
# 7. NaN/inf in logP skipped
# ---------------------------------------------------------------------------


def test_nan_logP_skipped(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central}
    )
    result = _make_trend_result(
        extrap_t=[1000.0, 2000.0, 3000.0, 4000.0],
        extrap_logP=[-4.0, float("nan"), float("inf"), -6.0],
        residual_std=0.1,
    )
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)
    assert len(pred_calls) == 1
    # Only 2 finite points (-4.0 and -6.0)
    assert len(pred_calls[0]["central"]) == 2


# ---------------------------------------------------------------------------
# 8. Raw buffer capped at MAX_RAW_PTS
# ---------------------------------------------------------------------------


def test_raw_buffer_capped(app) -> None:
    w = VacuumPredictionWidget()
    cap = w._MAX_RAW_PTS
    for i in range(cap + 100):
        w.set_pressure_reading(_make_reading(1e-4, ts=float(i)))
    assert len(w._raw_buffer) == cap


# ---------------------------------------------------------------------------
# 9a. Stale forecast cleared on subsequent no-data reply
# ---------------------------------------------------------------------------


def test_stale_forecast_cleared_on_no_data(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []

    def _spy_predict(central, lower, upper, ci_level_pct=68.0):
        pred_calls.append({"central": central, "lower": lower, "upper": upper})

    w._inner.set_prediction = _spy_predict  # type: ignore[method-assign]

    # First call: valid prediction rendered
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result())
    assert len(pred_calls) == 1
    assert len(pred_calls[0]["central"]) > 0

    # Second call: no_data — must clear the previously-shown forecast
    w._on_trend_result({"ok": True, "status": "no_data"})
    assert len(pred_calls) == 2
    assert pred_calls[1]["central"] == []
    assert pred_calls[1]["lower"] == []
    assert pred_calls[1]["upper"] == []


def test_stale_forecast_cleared_on_ok_false(app) -> None:
    w = VacuumPredictionWidget()
    pred_calls: list = []
    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
        {"central": central}
    )
    # First: valid
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result())
    assert len(pred_calls[0]["central"]) > 0
    # Second: error
    w._on_trend_result({"ok": False})
    assert pred_calls[1]["central"] == []


# ---------------------------------------------------------------------------
# 9. Legacy set_vacuum_prediction path
# ---------------------------------------------------------------------------


def test_legacy_set_vacuum_prediction(app) -> None:
    w = VacuumPredictionWidget()
    hist_calls: list = []
    pred_calls: list = []
    w._inner.set_history = lambda data: hist_calls.append(list(data))  # type: ignore[method-assign]
    w._inner.set_prediction = lambda *a, **kw: pred_calls.append((a, kw))  # type: ignore[method-assign]
    w.set_vacuum_prediction(
        {
            "history": [(1.0, 1e-4), (2.0, 5e-5)],
            "central": [(3.0, 1e-5)],
            "lower": [(3.0, 5e-6)],
            "upper": [(3.0, 2e-5)],
            "ci_level_pct": 95.0,
        }
    )
    assert len(hist_calls) == 1
    assert len(pred_calls) == 1
