"""Tests for TempPlotWidget (Phase UI-1 v2 Block B.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# LOW: assert embedded plot, channel dict, toolbar, axis exist
def test_constructs(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    assert w is not None
    # has plot widget
    assert w._plot is not None, "TempPlotWidget must have _plot attribute"
    # has plot_items dict
    assert isinstance(w._plot_items, dict), "_plot_items must be a dict"
    # has channel_manager
    assert w._channel_mgr is mgr


# MED: assert each curve cleared (empty data arrays) after empty-buffer refresh
def test_refresh_empty_buffer(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    w.refresh()  # should not raise
    # all plot items must have empty data
    for ch_id, item in w._plot_items.items():
        xdata, ydata = item.getData()
        # getData() returns (None, None) or ([], []) when empty
        if xdata is not None:
            assert len(xdata) == 0, (
                f"Curve for {ch_id!r} must be empty after empty-buffer refresh, "
                f"got {len(xdata)} points"
            )


# HIGH: assert _plot_items["Т1"] getData() got exact (x, y) arrays
def test_refresh_with_data(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    buf.append("Т1", 1000.0, 77.5)
    buf.append("Т1", 1001.0, 78.0)
    w.refresh()
    # "Т1" curve must exist and have the correct data
    assert "Т1" in w._plot_items, (
        f"'Т1' must be in _plot_items after append; keys: {list(w._plot_items)}"
    )
    item = w._plot_items["Т1"]
    xdata, ydata = item.getData()
    assert xdata is not None and ydata is not None, (
        "getData() must return arrays after refresh with data"
    )
    xs = list(xdata)
    ys = list(ydata)
    assert 1000.0 in xs, f"x=1000.0 must be in curve data, got xs={xs}"
    assert 1001.0 in xs, f"x=1001.0 must be in curve data, got xs={xs}"
    assert 77.5 in ys, f"y=77.5 must be in curve data, got ys={ys}"
    assert 78.0 in ys, f"y=78.0 must be in curve data, got ys={ys}"
