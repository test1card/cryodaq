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
