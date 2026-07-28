"""Tests for TempPlotWidget (Phase UI-1 v2 Block B.2)."""

from __future__ import annotations

import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore, peak_preserving_decimate
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget


def test_peak_preserving_decimation_retains_short_excursion_in_time_order():
    points = [(float(index), 1.0) for index in range(100)]
    points[49] = (49.0, 500.0)

    decimated = peak_preserving_decimate(points, 20)

    assert (49.0, 500.0) in decimated
    assert [timestamp for timestamp, _ in decimated] == sorted(timestamp for timestamp, _ in decimated)
    assert len(decimated) <= 20


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
                f"Curve for {ch_id!r} must be empty after empty-buffer refresh, got {len(xdata)} points"
            )


# HIGH: assert _plot_items["Т1"] getData() got exact paired (x, y) arrays
def test_refresh_with_data(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    buf.append("Т1", 1000.0, 77.5)
    buf.append("Т1", 1001.0, 78.0)
    w.refresh()
    # "Т1" curve must exist and have the correct data
    assert "Т1" in w._plot_items, f"'Т1' must be in _plot_items after append; keys: {list(w._plot_items)}"
    item = w._plot_items["Т1"]
    xdata, ydata = item.getData()
    assert xdata is not None and ydata is not None, "getData() must return arrays after refresh with data"
    # Prod: refresh() calls item.setData(x=xs, y=ys) with raw values —
    # no transform applied. Assert exact paired arrays.
    assert list(xdata) == pytest.approx([1000.0, 1001.0]), f"x data must be exactly [1000.0, 1001.0], got {list(xdata)}"
    assert list(ydata) == pytest.approx([77.5, 78.0]), f"y data must be exactly [77.5, 78.0], got {list(ydata)}"


def test_log_y_toggle_recomputes_visible_range_and_ignores_nonpositive_values(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    widget = TempPlotWidget(buf, mgr)
    now = time.time()
    buf.append("\u04221", now - 2.0, -1.0)
    buf.append("\u04221", now - 1.0, 4.0)
    buf.append("\u04221", now, 8.0)
    widget.refresh()
    linear_range = widget._plot.getPlotItem().getViewBox().viewRange()[1]
    assert linear_range[0] <= 4.0 <= 8.0 <= linear_range[1]

    widget._on_log_y_toggled(True)
    log_range = widget._plot.getPlotItem().getViewBox().viewRange()[1]
    assert log_range[0] <= math.log10(4.0)
    assert log_range[1] >= math.log10(8.0)

    widget._on_log_y_toggled(False)
    linear_range_after = widget._plot.getPlotItem().getViewBox().viewRange()[1]
    assert linear_range_after[0] <= 4.0 <= 8.0 <= linear_range_after[1]


def test_live_refresh_does_not_override_operator_y_viewport(app):
    buf = ChannelBufferStore()
    widget = TempPlotWidget(buf, ChannelManager())
    now = time.time()
    buf.append("\u04221", now, 4.0)
    widget.refresh()
    widget._on_log_y_toggled(True)
    plot_item = widget._plot.getPlotItem()
    plot_item.setYRange(0.5, 1.0, padding=0)

    buf.append("\u04221", now + 0.1, 4000.0)
    widget.refresh()

    visible = plot_item.getViewBox().viewRange()[1]
    assert visible == pytest.approx([0.5, 1.0])
