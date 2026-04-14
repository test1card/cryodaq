"""Smoke tests for PressurePlotWidget (Phase UI-1 v2 Block B.2)."""
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


def test_constructs(app):
    buf = ChannelBufferStore()
    w = PressurePlotWidget(buf)
    assert w is not None


def test_refresh_empty_and_filled(app):
    buf = ChannelBufferStore()
    w = PressurePlotWidget(buf)
    w.refresh()  # empty — should not raise
    buf.append("VSP63D_1/pressure", 1000.0, 1e-4)
    buf.append("VSP63D_1/pressure", 1001.0, 1e-5)
    w.refresh()  # filled — should not raise
