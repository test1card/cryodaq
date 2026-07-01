"""Phase III.B — shared PressurePlot tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
    reset_time_window_controller,
)
from cryodaq.gui.widgets.shared.pressure_plot import (
    PressurePlot,
    ScientificLogAxisItem,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_controller(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def test_log_y_mode_enabled(app):
    plot = PressurePlot()
    pi = plot.plot_item.getPlotItem()
    # Log-Y is implied by setLogMode(y=True) → axis.logMode True.
    assert pi.getAxis("left").logMode is True


def test_scientific_tick_formatter_decade_labels():
    axis = ScientificLogAxisItem(orientation="left")
    # log10(value) inputs: [-6, -5, -4] → values 1e-6, 1e-5, 1e-4.
    ticks = axis.tickStrings([-6.0, -5.0, -4.0], scale=1.0, spacing=1.0)
    assert ticks == ["1e-6", "1e-5", "1e-4"]


def test_scientific_tick_formatter_mantissa_not_one():
    axis = ScientificLogAxisItem(orientation="left")
    # log10(5e-6) ≈ -5.301 → mantissa 5, exponent -6.
    ticks = axis.tickStrings([-5.301], scale=1.0, spacing=1.0)
    assert ticks == ["5e-6"]


def test_pressure_y_range_stable_across_same_decade_jitter(app):
    """Regression: the Y axis must not 'dance'.

    Same-decade min/max fluctuations across refreshes (sensor noise) must
    leave the Y viewport UNCHANGED — the bounds are snapped to integer
    log-decades and only re-applied when the data crosses a decade. The old
    code set log10(min)-0.5 .. log10(max)+0.5 on every refresh, so the axis
    shifted continuously with every wobble.
    """
    import time as _time

    plot = PressurePlot()
    now = _time.time()

    def _y_range():
        QApplication.processEvents()
        return tuple(plot.plot_item.getPlotItem().getViewBox().viewRange()[1])

    # First refresh: vacuum trace ~3e-6 (all inside the 1e-6 decade).
    plot.set_series([now - 2, now - 1, now], [3.0e-6, 3.2e-6, 3.1e-6])
    y_first = _y_range()
    # Second refresh: same decade, different min/max (jitter).
    plot.set_series([now - 2, now - 1, now], [2.7e-6, 3.6e-6, 3.05e-6])
    y_second = _y_range()

    assert y_first == pytest.approx(y_second), (
        f"Y axis danced across same-decade refreshes: {y_first} -> {y_second}"
    )
    # Bounds must be decade-snapped (integer log10 values).
    lo, hi = y_first
    assert lo == int(lo) and hi == int(hi), f"Y bounds not decade-snapped: {y_first}"


def test_pressure_x_defers_to_link_master(app):
    """Regression: when the pressure X is slaved via setXLink (dashboard links
    it to the temperature plot), set_series must NOT overwrite its own X range —
    otherwise the two linked plots push slightly different ranges each refresh
    and the X axis jitters. set_series must leave the link-driven X untouched.
    """
    import time as _time

    import pyqtgraph as pg

    # Widgets are left to session GC like the other tests here — do NOT
    # close()/deleteLater() the raw PlotWidget (pyqtgraph's PlotWidget.close()
    # double-frees and errors in teardown, polluting later tests).
    master = pg.PlotWidget()
    slave = PressurePlot()
    slave.plot_item.setXLink(master)
    master.getPlotItem().getViewBox().setXRange(1000.0, 2000.0, padding=0)
    QApplication.processEvents()
    x_before = tuple(slave.plot_item.getPlotItem().getViewBox().viewRange()[0])

    now = _time.time()
    slave.set_series([now - 2, now - 1, now], [3.0e-6, 3.2e-6, 3.1e-6])
    QApplication.processEvents()
    x_after = tuple(slave.plot_item.getPlotItem().getViewBox().viewRange()[0])

    # A slaved plot must defer to the master: set_series must not move X.
    # (Old code called setXRange in _apply_window, fighting the link.)
    assert x_after == pytest.approx(x_before), (
        f"slaved pressure X was overwritten by set_series: {x_before} -> {x_after}"
    )
    slave.plot_item.setXLink(None)


def test_scientific_tick_formatter_handles_invalid():
    axis = ScientificLogAxisItem(orientation="left")
    ticks = axis.tickStrings([float("nan")], scale=1.0, spacing=1.0)
    assert ticks == [""]


def test_subscribes_to_global_window(app):
    """After set_window(HOUR_1) the subscribed plot's X range must narrow to 1h."""
    import time as _time

    plot = PressurePlot()
    # Give it some data so the X range is meaningful.
    now = _time.time()
    plot.set_series([now - 7200.0, now - 3600.0, now], [1e-5, 1.1e-5, 1.2e-5])

    controller = get_time_window_controller()
    controller.set_window(TimeWindow.HOUR_1)

    # Process any pending Qt signals.
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()

    pi = plot.plot_item.getPlotItem()
    x_lo, x_hi = pi.getViewBox().viewRange()[0]
    span = x_hi - x_lo
    # HOUR_1 = 3600s; allow ±10% for timing jitter between set_window and assertion.
    assert 3240 <= span <= 3960, (
        f"Expected X span ≈ 3600s for HOUR_1, got {span:.1f}s"
    )
    assert plot.plot_item is not None


def test_forward_looking_skips_subscribe(app):
    """Forward-looking plot must ignore global window changes — X range unchanged."""
    import time as _time

    from PySide6.QtWidgets import QApplication

    plot = PressurePlot(forward_looking=True)
    # Give it data so there's a defined X range.
    now = _time.time()
    plot.set_series([now - 60.0, now], [1e-5, 1.2e-5])
    QApplication.processEvents()

    pi = plot.plot_item.getPlotItem()
    x_lo_before, x_hi_before = pi.getViewBox().viewRange()[0]

    controller = get_time_window_controller()
    controller.set_window(TimeWindow.HOUR_1)
    QApplication.processEvents()
    controller.set_window(TimeWindow.MIN_1)
    QApplication.processEvents()

    x_lo_after, x_hi_after = pi.getViewBox().viewRange()[0]

    # X range must be unchanged — forward-looking plot does not subscribe.
    assert abs(x_lo_after - x_lo_before) < 1.0, (
        f"Forward-looking X-left changed: {x_lo_before} → {x_lo_after}"
    )
    assert abs(x_hi_after - x_hi_before) < 1.0, (
        f"Forward-looking X-right changed: {x_hi_before} → {x_hi_after}"
    )
    assert plot.plot_item is not None


def test_non_positive_values_guarded(app):
    """Non-positive values must be clamped to a positive fallback before setData.

    pyqtgraph in log-Y mode calls log10 internally, so getData() returns
    log10(clamped_y). The fallback for non-positive inputs is the minimum
    positive value in the series (here 1e-5), so all three getData() Y values
    must equal log10(1e-5) = -5.0.
    """
    import math as _math

    plot = PressurePlot()
    # inputs: [0.0, -1.0, 1e-5] — two non-positive, one positive
    plot.set_series([1.0, 2.0, 3.0], [0.0, -1.0, 1e-5])

    xs, ys = plot._curve.getData()
    assert xs is not None and ys is not None, "getData() returned None"
    assert len(ys) == 3, f"Expected 3 Y values, got {len(ys)}"

    # All getData() Y values must be finite (no -inf from log10(0) or log10(-1)).
    assert all(_math.isfinite(v) for v in ys), (
        f"All getData() Y must be finite after clamping, got: {list(ys)}"
    )

    # The fallback is min positive = 1e-5; log10(1e-5) = -5.0.
    # Both clamped slots AND the original 1e-5 map to the same log10 value.
    expected_log = _math.log10(1e-5)
    for i, v in enumerate(ys):
        assert abs(v - expected_log) < 1e-9, (
            f"ys[{i}]={v} expected log10(1e-5)={expected_log} "
            f"(non-positive clamped to 1e-5 fallback)"
        )


def test_set_title_updates(app):
    plot = PressurePlot(title="A")
    plot.set_title("B")
    assert plot.plot_item.getPlotItem().titleLabel.text == "B"


def test_left_axis_auto_si_prefix_disabled(app):
    """IV.1 finding 2 — left-axis must NOT auto-rescale to µбар / mбар.

    ScientificLogAxisItem renders its own "1e-6" style ticks; pyqtgraph's
    autoSIPrefix would re-scale on top of that and prefix labels with
    SI multipliers. The left axis must stay in the stated unit at all
    value ranges.
    """
    plot = PressurePlot()
    left_axis = plot.plot_item.getPlotItem().getAxis("left")
    assert left_axis.autoSIPrefix is False


def test_tick_values_decade_only_on_compact_panel():
    """IV.1 finding 3 — short panel must drop the 5× midpoints.

    Dashboard panel is ~80 px tall; pyqtgraph's default tick generator
    piled 6-8 labels (8e0 / 7e0 / …) that overlapped completely. The
    compact panel path returns only decade majors, no minor ticks.
    """
    axis = ScientificLogAxisItem(orientation="left")
    major, minor = axis.tickValues(-7.0, -5.0, size=80)
    assert major == (1.0, [-7.0, -6.0, -5.0])
    assert minor == (0.2, [])


def test_tick_values_include_midpoints_on_tall_panel():
    """Tall panel (>150 px) gets the 5× midpoints back."""
    axis = ScientificLogAxisItem(orientation="left")
    major, minor = axis.tickValues(-7.0, -5.0, size=400)
    assert major[1] == [-7.0, -6.0, -5.0]
    mid_values = minor[1]
    assert len(mid_values) == 2
    import math as _math

    for v in mid_values:
        # Midpoint = decade + log10(5), e.g. -6.3010
        frac = v - _math.floor(v)
        assert abs(frac - _math.log10(5.0)) < 1e-6


def test_pressure_autorange_excludes_sentinel_values(app):
    """IV.1 finding 3 — Y range must come from positive values only.

    Mix of legitimate ~1e-6 pressure readings and zero sentinels (pump
    warmup, sensor fault). The autorange bound must reflect 1e-6, not
    the 1e-12 replacement sentinel that would drag the viewport six
    decades too low and hide the trace.
    """
    plot = PressurePlot()
    times = [float(i) for i in range(5)]
    values = [1.0e-6, 0.0, 1.2e-6, -1.0, 1.1e-6]
    plot.set_series(times, values)
    pi = plot.plot_item.getPlotItem()
    view_range = pi.viewRange()
    y_lo_log, y_hi_log = view_range[1]
    import math as _math

    # 1e-6 should be well inside the viewport.
    assert y_lo_log < _math.log10(1e-6) < y_hi_log
    # 1e-12 sentinel must NOT be inside the viewport (that's the bug
    # signature — it would be if autorange was sentinel-contaminated).
    assert y_lo_log > _math.log10(1e-11)


def test_pressure_trace_visible_at_1e_minus_6(app):
    """Integration: a 1.2e-6 trace lands inside BOTH X and Y ranges.

    The prior version only checked Y inclusion; an off-screen sample
    in X would still have "passed" under that assertion. Now we
    explicitly verify at least one plotted point's (x, y) coordinates
    lie inside the viewport.
    """
    plot = PressurePlot()
    times = [float(i) for i in range(3)]
    values = [1.2e-6, 1.2e-6, 1.2e-6]
    plot.set_series(times, values)
    # Force an explicit X range that contains all samples so the test
    # does not depend on whatever default viewport pyqtgraph picks.
    pi = plot.plot_item.getPlotItem()
    pi.setXRange(-1.0, 3.0, padding=0)
    # Y range is recomputed on X-range change; drain any pending
    # signals synchronously.
    QApplication.processEvents()
    (x_lo, x_hi), (y_lo_log, y_hi_log) = pi.viewRange()
    import math as _math

    y_log = _math.log10(1.2e-6)
    # Some plotted sample must lie strictly inside the viewport.
    assert any(x_lo <= t <= x_hi and y_lo_log < y_log < y_hi_log for t in times), (
        f"no sample inside view rect ({x_lo},{x_hi}) × ({y_lo_log},{y_hi_log})"
    )


def test_pressure_y_range_excludes_offscreen_outlier(app):
    """Old off-screen outlier (1e-2 @ x=0) must not squash current 1e-6 trace."""
    plot = PressurePlot()
    # Off-screen high value at t=0, current readings near 1e-6 at
    # t=100..102. Dashboard's X range will cover only the recent tail.
    xs = [0.0, 100.0, 101.0, 102.0]
    ys = [1e-2, 1.0e-6, 1.1e-6, 1.2e-6]
    plot.set_series(xs, ys)
    pi = plot.plot_item.getPlotItem()
    pi.setXRange(99.0, 103.0, padding=0)
    QApplication.processEvents()
    (_, (y_lo_log, y_hi_log)) = pi.viewRange()
    import math as _math

    # The 1e-6 trace must be inside the viewport.
    assert y_lo_log < _math.log10(1e-6) < y_hi_log
    # The off-screen 1e-2 spike must NOT drag the Y range up with it
    # (that was the exact bug — Y computed across full buffer).
    assert y_hi_log < _math.log10(1e-3)


def test_pressure_set_series_all_non_positive_does_not_crash(app):
    """Edge: all values zero → explicit default Y range, no exception.

    Prior amend skipped setYRange when positive was empty, which left
    the plot clinging to whatever Y range pyqtgraph defaulted to (or
    the previous positive-data range). Now the empty case pins an
    explicit default so the fallback-clamped curve is visible.
    """
    plot = PressurePlot()
    plot.set_series([0.0, 1.0, 2.0], [0.0, 0.0, 0.0])
    pi = plot.plot_item.getPlotItem()
    (_, (y_lo_log, y_hi_log)) = pi.viewRange()
    import math as _math

    # Fallback 1e-12 curve must be inside the viewport.
    assert y_lo_log < _math.log10(1e-12) < y_hi_log


def test_dashboard_pressure_uses_shared_component(app):
    """IV.1 finding 3 — dashboard PressurePlotWidget composes PressurePlot and
    routes data through it. Verified behaviorally: instantiate the widget,
    refresh() with known data, assert the shared curve gets the expected (x,y)."""
    import time as _time

    from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
    from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget

    # Assert structural composition first.
    buf = ChannelBufferStore()
    widget = PressurePlotWidget(buf)
    assert isinstance(widget._shared, PressurePlot), (
        f"_shared must be PressurePlot, got {type(widget._shared)}"
    )

    # Feed data into the buffer for the expected channel and refresh.
    now = _time.time()
    pressures = [1.2e-5, 1.1e-5, 1.0e-5]
    times = [now - 2.0, now - 1.0, now]
    for t, v in zip(times, pressures):
        buf.append("VSP63D_1/pressure", t, v)

    widget.refresh()

    # The shared PressurePlot curve must carry the data we fed in.
    # pyqtgraph log-Y mode: getData() returns (x, log10(y)).
    import math as _math

    curve = widget._shared._curve
    assert curve is not None, "_shared._curve is None after refresh()"
    raw_x, raw_y = curve.getData()
    assert raw_x is not None, "curve getData() x is None after refresh()"
    assert raw_y is not None, "curve getData() y is None after refresh()"
    assert len(raw_x) == 3, f"expected 3 x points, got {len(raw_x)}"
    assert len(raw_y) == 3, f"expected 3 y points, got {len(raw_y)}"
    # All getData() Y values are log10(pressure) — must be finite (no -inf from bad clamping).
    assert all(_math.isfinite(v) for v in raw_y), (
        f"all getData() Y must be finite, got {list(raw_y)}"
    )
    # The maximum pressure 1.2e-5 → log10(1.2e-5) ≈ -4.921.
    expected_log_max = _math.log10(1.2e-5)
    assert any(abs(v - expected_log_max) < 1e-6 for v in raw_y), (
        f"Expected log10(1.2e-5)≈{expected_log_max:.4f} in curve getData() Y, got {list(raw_y)}"
    )
