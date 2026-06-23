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
    # PredictionWidget with log_y=True: pyqtgraph setLogMode(y=True) transforms
    # y values to log10 before storing in the PlotDataItem, so getData() returns
    # log10(value), not the raw pressure in mbar.
    w = VacuumPredictionWidget()
    w.set_pressure_reading(_make_reading(1e-4, ts=1_000_000.0))
    xs, ys = w._inner._history_curve.getData()
    assert xs is not None and len(xs) == 1
    assert xs[0] == pytest.approx(1_000_000.0, rel=1e-6)
    # log10(1e-4) == -4.0
    assert ys[0] == pytest.approx(-4.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. No-data result → no prediction
# ---------------------------------------------------------------------------


def test_no_data_status_clears_prediction(app) -> None:
    # Seed a real forecast first
    w = VacuumPredictionWidget()
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result(
            extrap_t=[1000.0, 2000.0],
            extrap_logP=[-4.0, -5.0],
            residual_std=0.1,
        ))
    xs_before, _ = w._inner._central_curve.getData()
    assert xs_before is not None and len(xs_before) == 2

    # Now send no_data — real curves must be cleared
    w._on_trend_result({"ok": True, "status": "no_data"})
    xs, ys = w._inner._central_curve.getData()
    assert xs is None or len(xs) == 0
    xs_lo, _ = w._inner._lower_curve.getData()
    assert xs_lo is None or len(xs_lo) == 0
    xs_hi, _ = w._inner._upper_curve.getData()
    assert xs_hi is None or len(xs_hi) == 0


# ---------------------------------------------------------------------------
# 4. ok=False → no prediction
# ---------------------------------------------------------------------------


def test_ok_false_clears_prediction(app) -> None:
    # Seed a real forecast first
    w = VacuumPredictionWidget()
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result(
            extrap_t=[1000.0, 2000.0],
            extrap_logP=[-4.0, -5.0],
            residual_std=0.1,
        ))
    xs_before, _ = w._inner._central_curve.getData()
    assert xs_before is not None and len(xs_before) == 2

    # ok=False must clear rendered curves
    w._on_trend_result({"ok": False})
    xs, ys = w._inner._central_curve.getData()
    assert xs is None or len(xs) == 0


# ---------------------------------------------------------------------------
# 5. Valid result → prediction forwarded with correct shape
# ---------------------------------------------------------------------------


def test_valid_result_prediction_forwarded(app) -> None:
    w = VacuumPredictionWidget()
    result = _make_trend_result(
        extrap_t=[1000.0, 2000.0, 3000.0],
        extrap_logP=[-4.0, -5.0, -6.0],
        residual_std=0.5,
    )
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)

    # Assert rendered central curve — 3 points.
    # log_y=True: pyqtgraph setLogMode(y=True) stores log10 of the y value.
    # PredictionWidget passes 10^logP values; pyqtgraph then takes log10 → back to logP.
    xs_c, ys_c = w._inner._central_curve.getData()
    assert len(xs_c) == 3
    assert ys_c[0] == pytest.approx(-4.0, abs=1e-9)   # log10(10^-4)
    assert ys_c[1] == pytest.approx(-5.0, abs=1e-9)   # log10(10^-5)
    assert ys_c[2] == pytest.approx(-6.0, abs=1e-9)   # log10(10^-6)

    # Band = ±1·residual_std in log10 space around central (prod:
    # analytics_widgets.py:727-733 → 10**(lp ∓ residual_std), pyqtgraph log10
    # maps back). residual_std=0.5 → lower = central-0.5, upper = central+0.5.
    # This proves the band half-width tracks residual_std, not just ordering:
    # a residual_std*2 / fixed-band / wrong-sigma bug would now fail.
    xs_lo, ys_lo = w._inner._lower_curve.getData()
    xs_hi, ys_hi = w._inner._upper_curve.getData()
    assert list(ys_lo) == pytest.approx([-4.5, -5.5, -6.5], abs=1e-9)
    assert list(ys_hi) == pytest.approx([-3.5, -4.5, -5.5], abs=1e-9)

    # x is anchored at t0 (patched time.time=2_000_000) with offsets relative to
    # the first forecast point: t0 + (extrap_t - extrap_t[0]) for [1000,2000,3000].
    expected_xs = [2_000_000.0, 2_001_000.0, 2_002_000.0]
    assert list(xs_c) == pytest.approx(expected_xs, abs=1e-6)
    assert list(xs_lo) == pytest.approx(expected_xs, abs=1e-6)
    assert list(xs_hi) == pytest.approx(expected_xs, abs=1e-6)

    # Horizon readout row for 24h must show mбар value (non-dash)
    row_24 = w._inner._horizon_rows[24.0]
    assert row_24["value"].text() != "—"
    assert "мбар" in row_24["value"].text()


# ---------------------------------------------------------------------------
# 6. residual_std=0 → lower=upper=central (no band crash)
# ---------------------------------------------------------------------------


def test_zero_residual_std_no_crash(app) -> None:
    w = VacuumPredictionWidget()
    result = _make_trend_result(residual_std=0.0)
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)
    # When residual_std=0: lower curve data == upper curve data == central curve data
    xs_c, ys_c = w._inner._central_curve.getData()
    xs_lo, ys_lo = w._inner._lower_curve.getData()
    xs_hi, ys_hi = w._inner._upper_curve.getData()
    assert len(xs_c) > 0
    assert list(xs_lo) == list(xs_c)
    assert list(ys_lo) == list(ys_c)
    assert list(xs_hi) == list(xs_c)
    assert list(ys_hi) == list(ys_c)


# ---------------------------------------------------------------------------
# 7. NaN/inf in logP skipped
# ---------------------------------------------------------------------------


def test_nan_logP_skipped(app) -> None:
    w = VacuumPredictionWidget()
    result = _make_trend_result(
        extrap_t=[1000.0, 2000.0, 3000.0, 4000.0],
        extrap_logP=[-4.0, float("nan"), float("inf"), -6.0],
        residual_std=0.1,
    )
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(result)
    # Only 2 finite logP values (-4.0 → t=1000, -6.0 → t=4000) plotted.
    # t0 = now - extrap_t[0] = 2_000_000.0 - 1000.0 = 1_999_000.0
    t0 = 2_000_000.0 - 1000.0
    xs_c, ys_c = w._inner._central_curve.getData()
    assert len(xs_c) == 2
    assert xs_c[0] == pytest.approx(t0 + 1000.0, rel=1e-6)
    # log_y=True: pyqtgraph stores log10(10^logP) = logP
    assert ys_c[0] == pytest.approx(-4.0, abs=1e-9)
    assert xs_c[1] == pytest.approx(t0 + 4000.0, rel=1e-6)
    assert ys_c[1] == pytest.approx(-6.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 8. Raw buffer capped at MAX_RAW_PTS
# ---------------------------------------------------------------------------


def test_raw_buffer_capped(app) -> None:
    w = VacuumPredictionWidget()
    cap = w._MAX_RAW_PTS
    total = cap + 100
    for i in range(total):
        w.set_pressure_reading(_make_reading(1e-4, ts=float(i)))
    assert len(w._raw_buffer) == cap
    # Oldest 100 dropped; retained window is [100, total-1]
    assert w._raw_buffer[0] == pytest.approx((100.0, 1e-4), rel=1e-6)
    assert w._raw_buffer[-1] == pytest.approx((float(total - 1), 1e-4), rel=1e-6)


# ---------------------------------------------------------------------------
# 9a. Stale forecast cleared on subsequent no-data reply
# ---------------------------------------------------------------------------


def test_stale_forecast_cleared_on_no_data(app) -> None:
    w = VacuumPredictionWidget()
    # First call: seed a real forecast into the rendered curves
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result())
    xs_c, _ = w._inner._central_curve.getData()
    assert xs_c is not None and len(xs_c) > 0

    # Second call: no_data — real rendered curves must be cleared
    w._on_trend_result({"ok": True, "status": "no_data"})
    xs_c2, _ = w._inner._central_curve.getData()
    assert xs_c2 is None or len(xs_c2) == 0
    xs_lo, _ = w._inner._lower_curve.getData()
    assert xs_lo is None or len(xs_lo) == 0
    xs_hi, _ = w._inner._upper_curve.getData()
    assert xs_hi is None or len(xs_hi) == 0


def test_stale_forecast_cleared_on_ok_false(app) -> None:
    w = VacuumPredictionWidget()
    # First: seed a real forecast
    with patch("time.time", return_value=2_000_000.0):
        w._on_trend_result(_make_trend_result())
    xs_c, _ = w._inner._central_curve.getData()
    assert xs_c is not None and len(xs_c) > 0

    # Second: error — rendered central curve must be cleared
    w._on_trend_result({"ok": False})
    xs_c2, _ = w._inner._central_curve.getData()
    assert xs_c2 is None or len(xs_c2) == 0


# ---------------------------------------------------------------------------
# 9. Legacy set_vacuum_prediction path
# ---------------------------------------------------------------------------


def test_legacy_set_vacuum_prediction(app) -> None:
    w = VacuumPredictionWidget()
    w.set_vacuum_prediction(
        {
            "history": [(1.0, 1e-4), (2.0, 5e-5)],
            "central": [(3.0, 1e-5)],
            "lower": [(3.0, 5e-6)],
            "upper": [(3.0, 2e-5)],
            "ci_level_pct": 95.0,
        }
    )
    # log_y=True: pyqtgraph setLogMode(y=True) stores log10 of all y values.
    # History curve: 2 points, timestamps 1.0 and 2.0
    xs_h, ys_h = w._inner._history_curve.getData()
    assert len(xs_h) == 2
    assert xs_h[0] == pytest.approx(1.0, rel=1e-6)
    assert ys_h[0] == pytest.approx(-4.0, abs=1e-9)   # log10(1e-4)

    # Central curve: 1 forecast point at t=3.0, pressure=1e-5 → log10=-5
    xs_c, ys_c = w._inner._central_curve.getData()
    assert len(xs_c) == 1
    assert xs_c[0] == pytest.approx(3.0, rel=1e-6)
    assert ys_c[0] == pytest.approx(-5.0, abs=1e-9)   # log10(1e-5)

    # CI band: lower 5e-6 → log10=-5.3, upper 2e-5 → log10≈-4.699
    xs_lo, ys_lo = w._inner._lower_curve.getData()
    xs_hi, ys_hi = w._inner._upper_curve.getData()
    assert len(xs_lo) == 1
    import math
    assert ys_lo[0] == pytest.approx(math.log10(5e-6), abs=1e-9)
    assert ys_hi[0] == pytest.approx(math.log10(2e-5), abs=1e-9)

    # CI level stored on widget
    assert w._inner._ci_level_pct == pytest.approx(95.0)
