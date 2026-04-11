"""Smoke tests for TempPlotWidget (Phase UI-1 v2 Block B.2)."""
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


def test_constructs(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    assert w is not None


def test_refresh_empty_buffer(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    w.refresh()  # should not raise


def test_refresh_with_data(app):
    buf = ChannelBufferStore()
    mgr = ChannelManager()
    w = TempPlotWidget(buf, mgr)
    buf.append("Т1", 1000.0, 77.5)
    buf.append("Т1", 1001.0, 78.0)
    w.refresh()  # should not raise
