"""Phase III.B — shared PredictionWidget tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.widgets.shared.prediction_widget import (
    _HORIZON_OPTIONS_HOURS,
    PredictionWidget,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _history(n: int = 5, step: float = 60.0) -> list[tuple[float, float]]:
    return [(i * step, 100.0 - i * 2.0) for i in range(n)]


def _forecast(start_t: float, horizon_s: float, step: float = 600.0) -> dict:
    steps = int(horizon_s / step) + 1
    central = [(start_t + i * step, 50.0 + i * 0.1) for i in range(steps)]
    lower = [(t, v - 1.0) for t, v in central]
    upper = [(t, v + 1.0) for t, v in central]
    return {"central": central, "lower": lower, "upper": upper}


def test_widget_constructs_linear_y(app):
    w = PredictionWidget("Cooldown", "Температура", "K", log_y=False)
    assert w._horizon_hours == 24.0


def test_widget_constructs_log_y(app):
    w = PredictionWidget("Vacuum", "Давление", "мбар", log_y=True)
    assert w._log_y is True
    # Verify the actual plot axis is in log mode (not just the private flag).
    left_axis = w._plot.getPlotItem().getAxis("left")
    assert left_axis.logMode is True, "log_y=True must set left axis to log mode"
    # Feed a known positive pressure value; _history_curve must store it
    # via log10 coercion without crashing (log-Y rejects non-positive).
    w.set_history([(1000.0, 1e-5)])
    xs, ys = w._history_curve.getData()
    assert len(xs) == 1
    # pyqtgraph in log-Y mode stores log10(y) in getData() output.
    # set_history passes 1e-5 (positive, no clamping), so getData() returns log10(1e-5) = -5.0.
    import math as _math
    assert abs(ys[0] - _math.log10(1e-5)) < 1e-9, (
        f"log-Y curve getData() must return log10(1e-5)=-5.0, got {ys[0]}"
    )


def test_horizon_selector_has_six_buttons(app):
    w = PredictionWidget("Cooldown", "T", "K")
    assert set(w._horizon_buttons.keys()) == set(_HORIZON_OPTIONS_HOURS)


def test_set_history_populates_curve(app):
    w = PredictionWidget("Cooldown", "T", "K")
    pts = _history(5)
    w.set_history(pts)
    xs, ys = w._history_curve.getData()
    assert len(xs) == 5
    # Assert exact x/y values — not just count.
    # _history(5) → [(i*60, 100 - i*2) for i in range(5)]
    expected_xs = [i * 60.0 for i in range(5)]
    expected_ys = [100.0 - i * 2.0 for i in range(5)]
    for i, (ex, ey) in enumerate(zip(expected_xs, expected_ys)):
        assert abs(xs[i] - ex) < 1e-9, f"xs[{i}]={xs[i]} expected {ex}"
        assert abs(ys[i] - ey) < 1e-9, f"ys[{i}]={ys[i]} expected {ey}"


def test_set_prediction_populates_all_three_curves(app):
    w = PredictionWidget("Cooldown", "T", "K")
    w.set_history(_history(5))
    f = _forecast(start_t=240.0, horizon_s=24 * 3600.0)
    central = f["central"]
    lower = f["lower"]
    upper = f["upper"]
    w.set_prediction(central, lower, upper, ci_level_pct=67.0)
    cx, cy = w._central_curve.getData()
    lx, ly = w._lower_curve.getData()
    ux, uy = w._upper_curve.getData()

    assert len(cx) > 0
    assert len(lx) == len(cx)
    assert len(ux) == len(cx)

    # Assert exact first and last x/y values for each curve — catches swapped bands.
    # central: (start_t + i*600, 50 + i*0.1)
    assert abs(cx[0] - central[0][0]) < 1e-6, f"central x[0] mismatch: {cx[0]}"
    assert abs(cy[0] - central[0][1]) < 1e-6, f"central y[0] mismatch: {cy[0]}"
    assert abs(cx[-1] - central[-1][0]) < 1e-6, f"central x[-1] mismatch: {cx[-1]}"
    assert abs(cy[-1] - central[-1][1]) < 1e-6, f"central y[-1] mismatch: {cy[-1]}"

    # lower = central - 1.0; upper = central + 1.0
    assert abs(ly[0] - lower[0][1]) < 1e-6, f"lower y[0] mismatch: {ly[0]}"
    assert abs(uy[0] - upper[0][1]) < 1e-6, f"upper y[0] mismatch: {uy[0]}"

    # CI bounds: lower < central < upper at each point
    for i in range(len(cx)):
        assert ly[i] < cy[i] < uy[i], (
            f"CI ordering violated at i={i}: lower={ly[i]} central={cy[i]} upper={uy[i]}"
        )


def test_horizon_change_emits_signal(app):
    w = PredictionWidget("Cooldown", "T", "K")
    seen: list[float] = []
    w.horizon_changed.connect(seen.append)
    w.set_horizon(12.0)
    assert seen == [12.0]
    assert w.get_horizon() == 12.0


def test_horizon_change_same_value_is_noop(app):
    w = PredictionWidget("Cooldown", "T", "K")
    seen: list[float] = []
    w.horizon_changed.connect(seen.append)
    w.set_horizon(24.0)  # default
    assert seen == []


def test_readout_rows_have_static_horizon_captions(app):
    """Each row's caption is fixed to its own horizon; captions no longer
    follow the selected button."""
    w = PredictionWidget("Cooldown", "T", "K")
    for hrs in _HORIZON_OPTIONS_HOURS:
        caption = w._horizon_rows[hrs]["caption"].text()
        hrs_text = f"{int(hrs) if hrs == int(hrs) else hrs}"
        assert hrs_text in caption
        assert "ч" in caption


def test_readout_value_reflects_central_at_horizon(app):
    w = PredictionWidget("Cooldown", "T", "K")
    now = 1000.0
    w.set_history([(now, 77.0)])
    # Forecast: linear from (now, 50) to (now + 24h, 60).
    central = [(now, 50.0), (now + 24 * 3600.0, 60.0)]
    lower = [(now, 48.0), (now + 24 * 3600.0, 58.0)]
    upper = [(now, 52.0), (now + 24 * 3600.0, 62.0)]
    w.set_prediction(central, lower, upper, ci_level_pct=67.0)
    text = w._horizon_rows[24.0]["value"].text()
    assert "60" in text and "K" in text


def test_ci_band_brush_uses_status_info_not_status_ok(app):
    w = PredictionWidget("Cooldown", "T", "K")
    # FillBetweenItem brush: pull the color back out.
    brush = w._ci_band.brush()
    color = brush.color()
    status_info = theme.STATUS_INFO.lstrip("#")
    hex_from_color = color.name().lstrip("#")
    assert hex_from_color.lower() == status_info.lower()
    # Alpha ≈ 64 (semi-transparent); definitely not opaque.
    assert 0 < color.alpha() < 255


def test_log_y_readout_uses_scientific_notation(app):
    w = PredictionWidget("Vacuum", "P", "мбар", log_y=True)
    now = 1000.0
    w.set_history([(now, 1e-5)])
    horizon_s = 24.0 * 3600.0
    central = [(now, 1e-5), (now + horizon_s, 3.8e-6)]
    lower = [(now, 0.5e-5), (now + horizon_s, 1e-6)]
    upper = [(now, 2e-5), (now + horizon_s, 6.5e-6)]
    w.set_prediction(central, lower, upper, ci_level_pct=95.0)
    text = w._horizon_rows[24.0]["value"].text()
    # The 24h horizon interpolates central at now + 24h = the last central point = 3.8e-6.
    # _format_value for log_y uses f"{value:.1e}{unit_suffix}" → "3.8e-06 мбар"
    assert text == "3.8e-06 мбар", f"expected '3.8e-06 мбар', got {text!r}"


def test_prediction_readout_shows_all_horizons(app):
    """All 6 horizon rows render correct value+CI labels after set_prediction.

    central[h] = (now + h*3600, 100 - h) → at horizon h hours: value = 100 - h.
    CI band is ±2 → half_ci = 2.0 → "± 2.00 K, 67% ДИ".
    """
    import time as _time

    w = PredictionWidget("Cooldown", "T", "K")
    now = _time.time()
    w.set_history([(now, 77.0)])
    # central[i] = (now + i*3600, 100 - i) for i in range(50)
    central = [(now + h * 3600.0, 100.0 - h) for h in range(50)]
    lower = [(t, v - 2.0) for t, v in central]
    upper = [(t, v + 2.0) for t, v in central]
    w.set_prediction(central, lower, upper, ci_level_pct=67.0)

    for hrs in _HORIZON_OPTIONS_HOURS:
        row = w._horizon_rows[hrs]
        val_text = row["value"].text()
        ci_text = row["ci"].text()

        assert val_text != "—", f"Row {hrs}h has empty value"
        assert ci_text != "", f"Row {hrs}h has empty CI"
        assert "67% ДИ" in ci_text, f"Row {hrs}h missing CI level: {ci_text!r}"

        # Assert exact value: central at now + hrs*3600 = 100 - hrs
        expected_val = 100.0 - hrs
        expected_val_text = f"{expected_val:.2f} K"
        assert val_text == expected_val_text, (
            f"Row {hrs}h: expected {expected_val_text!r}, got {val_text!r}"
        )

        # Assert exact CI: half_ci = (upper - lower) / 2 = 2.0 → "± 2.00 K, 67% ДИ"
        assert "± 2.00 K" in ci_text, (
            f"Row {hrs}h: expected '± 2.00 K' in CI, got {ci_text!r}"
        )


def test_prediction_readout_empty_state(app):
    """Without a prediction or history, all 6 rows show — placeholder."""
    w = PredictionWidget("Cooldown", "T", "K")
    for hrs in _HORIZON_OPTIONS_HOURS:
        row = w._horizon_rows[hrs]
        assert row["value"].text() == "—"
        assert row["ci"].text() == ""


def test_prediction_horizon_buttons_drive_plot_range_not_readout(app):
    """Clicking a horizon button changes _horizon_hours (plot X-range driver)
    but leaves the populated readout rows untouched."""
    import time as _time

    w = PredictionWidget("Cooldown", "T", "K")
    now = _time.time()
    w.set_history([(now, 77.0)])
    central = [(now + h * 3600.0, 100.0 - h) for h in range(50)]
    lower = [(t, v - 2.0) for t, v in central]
    upper = [(t, v + 2.0) for t, v in central]
    w.set_prediction(central, lower, upper, ci_level_pct=67.0)

    snapshot = {hrs: w._horizon_rows[hrs]["value"].text() for hrs in _HORIZON_OPTIONS_HOURS}

    # Switch the plot horizon to 6 ч.
    w._horizon_buttons[6.0].click()
    assert w.get_horizon() == 6.0

    # Readout rows are unchanged — every horizon still populated.
    for hrs in _HORIZON_OPTIONS_HOURS:
        assert w._horizon_rows[hrs]["value"].text() == snapshot[hrs]


def test_horizon_button_sets_plot_x_range(app):
    """Clicking a horizon button updates plot X-range right edge to
    now + horizon hours, left edge to history start."""
    import time as _time

    w = PredictionWidget("Cooldown", "T", "K")
    now = _time.time()
    history = [(now - 3600.0, 300.0), (now, 100.0)]
    w.set_history(history)

    w.set_horizon(6.0)
    left, right = w._plot.getPlotItem().getViewBox().viewRange()[0]

    expected_right = _time.time() + 6.0 * 3600.0
    assert abs(right - expected_right) < 60.0, f"right={right} expected≈{expected_right}"
    assert abs(left - (now - 3600.0)) < 60.0, f"left={left} expected≈{now - 3600.0}"


def test_horizon_change_reanchors_after_set_prediction(app):
    """set_prediction re-applies X-range so plot tracks wall-clock now —
    right edge never goes backward as new prediction frames arrive."""
    import time as _time

    w = PredictionWidget("Cooldown", "T", "K")
    now = _time.time()
    w.set_history([(now - 60.0, 100.0)])
    w.set_horizon(1.0)

    initial_right = w._plot.getPlotItem().getViewBox().viewRange()[0][1]

    central = [(now + h * 60.0, 100.0 - h) for h in range(120)]
    w.set_prediction(central, central, central, ci_level_pct=67.0)

    new_right = w._plot.getPlotItem().getViewBox().viewRange()[0][1]
    # Right edge re-anchors on the latest time.time() call inside
    # _apply_x_range; tolerance for clock-tick sensitivity.
    assert new_right >= initial_right - 1.0


def test_empty_history_x_range_uses_minute_lookback(app):
    """No history → left edge falls back to now - 60s, never the Unix epoch.
    Right edge still anchors on now + horizon."""
    import time as _time

    w = PredictionWidget("Cooldown", "T", "K")
    now = _time.time()
    w.set_horizon(3.0)

    left, right = w._plot.getPlotItem().getViewBox().viewRange()[0]
    assert left > now - 120.0, f"left={left} suggests epoch fallback"
    expected_right = _time.time() + 3.0 * 3600.0
    assert abs(right - expected_right) < 60.0, f"right={right} expected≈{expected_right}"


def test_left_axis_auto_si_prefix_disabled_linear_y(app):
    """IV.1 finding 2 — cooldown Y axis must stay in K across 300→4 K range.

    Before the fix pyqtgraph auto-rescaled the axis to mK when the value
    range exceeded ~1000× contrast, so "4 K" rendered as "4000 mK" and
    operators misread the absolute temperature by 1000×.
    """
    w = PredictionWidget("Cooldown", "Температура", "K", log_y=False)
    left_axis = w._plot.getPlotItem().getAxis("left")
    assert left_axis.autoSIPrefix is False


def test_left_axis_auto_si_prefix_disabled_log_y(app):
    """IV.1 finding 2 — vacuum prediction must not auto-prefix мбар either."""
    w = PredictionWidget("Vacuum", "Давление", "мбар", log_y=True)
    left_axis = w._plot.getPlotItem().getAxis("left")
    assert left_axis.autoSIPrefix is False


def test_k_range_300_to_4_does_not_auto_rescale_to_mk(app):
    """IV.1 finding 2 — integration: 300→4 K history should not flip axis to mK.

    Feed a full cooldown history; force the view range to 0-300 so
    pyqtgraph's tick generator actually emits strings, then verify the
    rendered tick labels are in K (not thousands of mK). With
    autoSIPrefix enabled (the bug), pyqtgraph would re-scale the axis
    to mK and emit tick strings like "4000" / "100000" / "300000";
    with it disabled the strings remain "4" / "100" / "300".
    """
    w = PredictionWidget("Cooldown", "Температура", "K", log_y=False)
    # Cooldown trajectory: 300 K → 4 K over 24 hours.
    now = 1_700_000_000.0
    hist = [(now + i * 60.0, 300.0 - (296.0 * i / 1440.0)) for i in range(1440)]
    w.set_history(hist)
    left_axis = w._plot.getPlotItem().getAxis("left")
    assert left_axis.autoSIPrefix is False
    # autoSIPrefixScale stays at 1.0 when autoSIPrefix is disabled; if
    # pyqtgraph had been allowed to rescale, this would be 1e-3 (the
    # multiplier that turns 4 K into 4000 mK on the tick layer).
    assert left_axis.autoSIPrefixScale == 1.0
    # labelUnitPrefix is the prefix pyqtgraph would inject into the
    # rendered axis title. It must stay empty — not "m" for milli-.
    assert left_axis.labelUnitPrefix == ""
    # Rendered tick strings for the actual value range stay in K.
    tick_strings = left_axis.tickStrings(
        [4.0, 100.0, 300.0],
        left_axis.autoSIPrefixScale * left_axis.scale,
        spacing=50.0,
    )
    # None of the strings should read as the thousands-of-mK rendering
    # (tick "4000" or "300000"); any of "4" / "100" / "300" may appear
    # depending on pyqtgraph's internal formatting, but the large values
    # are disqualifying.
    for s in tick_strings:
        assert "4000" not in s
        assert "300000" not in s


def test_does_not_import_global_window_controller(app):
    """Prediction widget is forward-looking; must NOT subscribe to the global
    TimeWindowController. Verified behaviorally: changing the global window must
    leave the widget's X-range and readouts unchanged."""
    import time as _time

    from cryodaq.gui.state.time_window import (
        TimeWindow,
        get_time_window_controller,
        reset_time_window_controller,
    )

    reset_time_window_controller()
    try:
        w = PredictionWidget("Cooldown", "T", "K")
        now = _time.time()
        w.set_history([(now - 3600.0, 100.0), (now, 80.0)])
        central = [(now + h * 3600.0, 80.0 - h) for h in range(25)]
        lower = [(t, v - 1.0) for t, v in central]
        upper = [(t, v + 1.0) for t, v in central]
        w.set_prediction(central, lower, upper, ci_level_pct=67.0)

        # Capture state before controller change.
        vb = w._plot.getPlotItem().getViewBox()
        x_lo_before, x_hi_before = vb.viewRange()[0]
        readout_before = {
            hrs: w._horizon_rows[hrs]["value"].text()
            for hrs in _HORIZON_OPTIONS_HOURS
        }

        # Change global controller to HOUR_1 (3600s window).
        get_time_window_controller().set_window(TimeWindow.HOUR_1)

        # Widget X-range must be unchanged (it does not subscribe).
        x_lo_after, x_hi_after = vb.viewRange()[0]
        assert abs(x_lo_after - x_lo_before) < 1.0, (
            f"X-left changed after global window change: {x_lo_before} → {x_lo_after}"
        )
        assert abs(x_hi_after - x_hi_before) < 1.0, (
            f"X-right changed after global window change: {x_hi_before} → {x_hi_after}"
        )

        # Readouts must be unchanged too.
        for hrs in _HORIZON_OPTIONS_HOURS:
            after = w._horizon_rows[hrs]["value"].text()
            assert after == readout_before[hrs], (
                f"Row {hrs}h readout changed after window change: "
                f"{readout_before[hrs]!r} → {after!r}"
            )
    finally:
        reset_time_window_controller()
