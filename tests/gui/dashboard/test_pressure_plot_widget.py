"""Tests for PressurePlotWidget (Phase UI-1 v2 Block B.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# LOW: assert embedded plot widget and _shared exist
def test_constructs(app):
    buf = ChannelBufferStore()
    w = PressurePlotWidget(buf)
    assert w is not None
    # _shared is a PressurePlot widget
    assert w._shared is not None, "PressurePlotWidget must have _shared PressurePlot"
    # _plot property exposes the underlying plot item
    assert w._plot is not None, "_plot property must return the underlying plot"
    # channel id is correct
    assert w._channel_id == "VSP63D_1/pressure"


# HIGH: assert set_series was called with correct (x, y) data after refresh with data
def test_refresh_empty_and_filled(app):
    buf = ChannelBufferStore()
    w = PressurePlotWidget(buf)

    # empty refresh — should not raise
    w.refresh()

    # fill buffer and refresh
    buf.append("VSP63D_1/pressure", 1000.0, 1e-4)
    buf.append("VSP63D_1/pressure", 1001.0, 1e-5)
    w.refresh()

    # assert _shared has the data via getData on the underlying curve
    # PressurePlot stores data in _last_times / _last_values or via set_series
    # Access the plot item to check curve data
    shared = w._shared
    # The PressurePlot._plot is the PlotWidget; get the first PlotDataItem
    plot_item = shared.plot_item
    pi = plot_item.getPlotItem()
    curves = pi.listDataItems()
    assert len(curves) > 0, "PressurePlot must have at least one curve after set_series"
    xdata, ydata = curves[0].getData()
    assert xdata is not None and ydata is not None, (
        "Pressure curve must have data after refresh with points"
    )
    import math

    xs = list(xdata)
    ys = list(ydata)
    assert 1000.0 in xs, f"x=1000.0 must be in pressure curve, got xs={xs}"
    assert 1001.0 in xs, f"x=1001.0 must be in pressure curve, got xs={xs}"
    # PressurePlot uses log Y axis — set_series stores log10(value) or raw value
    # Check either log10 representation or raw values are present
    ys_floats = [float(y) for y in ys]
    raw_ok = (1e-4 in ys_floats or 1e-5 in ys_floats)
    log_ok = (
        any(math.isclose(y, math.log10(1e-4), abs_tol=1e-9) for y in ys_floats)
        and any(math.isclose(y, math.log10(1e-5), abs_tol=1e-9) for y in ys_floats)
    )
    assert raw_ok or log_ok, (
        f"Pressure curve must contain 1e-4/1e-5 (raw) or -4/-5 (log10), got ys={ys_floats}"
    )
