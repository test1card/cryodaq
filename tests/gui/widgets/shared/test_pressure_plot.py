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


def test_scientific_tick_formatter_handles_invalid():
    axis = ScientificLogAxisItem(orientation="left")
    ticks = axis.tickStrings([float("nan")], scale=1.0, spacing=1.0)
    assert ticks == [""]


def test_subscribes_to_global_window(app):
    plot = PressurePlot()
    controller = get_time_window_controller()
    # Changing controller does not crash the subscribed plot.
    controller.set_window(TimeWindow.HOUR_1)
    # And the plot survives — the subscription callback ran without raising.
    assert plot.plot_item is not None


def test_forward_looking_skips_subscribe(app):
    plot = PressurePlot(forward_looking=True)
    controller = get_time_window_controller()
    # Forward-looking plot must not crash on window change, but also
    # must not rely on the controller — toggle twice, plot remains intact.
    controller.set_window(TimeWindow.HOUR_1)
    controller.set_window(TimeWindow.MIN_1)
    assert plot.plot_item is not None
    # Source-level guard: the plot module must gate the connect on
    # `not forward_looking` (grep-assert as a regression guard).
    import inspect

    src = inspect.getsource(PressurePlot.__init__)
    assert "if not self._forward_looking" in src


def test_non_positive_values_guarded(app):
    plot = PressurePlot()
    plot.set_series([1.0, 2.0, 3.0], [0.0, -1.0, 1e-5])
    # Underlying curve stores data (and on log-Y: stores log10(y)).
    # Guard ensures we never pass a non-positive value; once the plot
    # is log-Y, PlotDataItem may expose log10 values. Pull the
    # original array we passed via the opts dict to verify the
    # replacement actually happened.
    opts = plot._curve.opts
    raw_y = opts.get("y")
    if raw_y is not None:
        assert 1e-12 in list(raw_y)
        assert all(v > 0 for v in raw_y)


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


def test_dashboard_pressure_uses_shared_component():
    """IV.1 finding 3 — dashboard pressure plot composes the shared plot."""
    import inspect

    from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget

    src = inspect.getsource(PressurePlotWidget)
    assert "PressurePlot" in src
    assert "from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot" in inspect.getsource(
        inspect.getmodule(PressurePlotWidget)
    )
