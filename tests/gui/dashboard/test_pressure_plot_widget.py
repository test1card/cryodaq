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


# HIGH: assert set_series stores raw (not log10) clamped pressure values
def test_refresh_empty_and_filled(app):
    buf = ChannelBufferStore()
    w = PressurePlotWidget(buf)

    # empty refresh — should not raise
    w.refresh()

    # fill buffer and refresh
    buf.append("VSP63D_1/pressure", 1000.0, 1e-4)
    buf.append("VSP63D_1/pressure", 1001.0, 1e-5)
    w.refresh()

    # Prod: PressurePlot.set_series() stores raw clamped values via
    #   clamped_values = [v if v > 0 else fallback for v in self._last_values]
    #   self._curve.setData(x=self._last_times, y=clamped_values)
    # Both 1e-4 and 1e-5 are positive — stored as raw. Log-Y is an axis
    # transform only; the underlying data is NOT log10-transformed.
    shared = w._shared
    plot_item = shared.plot_item
    pi = plot_item.getPlotItem()
    curves = pi.listDataItems()
    assert len(curves) > 0, "PressurePlot must have at least one curve after set_series"
    xdata, ydata = curves[0].getData()
    assert xdata is not None and ydata is not None, (
        "Pressure curve must have data after refresh with points"
    )
    assert list(xdata) == pytest.approx([1000.0, 1001.0]), (
        f"x data must be exactly [1000.0, 1001.0], got {list(xdata)}"
    )
    # Verified: pyqtgraph's log-Y PlotWidget converts raw values to log10
    # internally when setData is called in log mode. getData() returns the
    # log10-transformed values: log10(1e-4) = -4.0, log10(1e-5) = -5.0.
    assert list(ydata) == pytest.approx([-4.0, -5.0]), (
        f"y data must be log10-transformed [-4.0, -5.0] (pyqtgraph log-Y), got {list(ydata)}"
    )
