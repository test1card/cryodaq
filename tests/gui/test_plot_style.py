"""Tests for centralized pyqtgraph styling helpers (B.5.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_apply_plot_style_sets_plot_bg_token(app):
    plot = pg.PlotWidget()
    apply_plot_style(plot)
    # pyqtgraph stores the brush; the painter uses theme.PLOT_BG.
    # Read back the underlying GraphicsScene background color to assert.
    bg = plot.backgroundBrush().color().name()
    assert bg.lower() == theme.PLOT_BG.lower(), (
        f"plot background {bg} != PLOT_BG {theme.PLOT_BG}"
    )


def test_series_pen_cycles_palette(app):
    # Index 0..N-1 must select N distinct palette colours; N+X wraps.
    palette = theme.PLOT_LINE_PALETTE
    for i in range(len(palette)):
        pen = series_pen(i)
        assert pen.color().name().lower() == palette[i].lower()
    # Cycle wrap
    assert (
        series_pen(len(palette)).color().name().lower()
        == palette[0].lower()
    )


def test_series_pen_width_defaults_to_plot_line_width(app):
    pen = series_pen(0)
    assert pen.widthF() == theme.PLOT_LINE_WIDTH


def test_series_pen_highlighted_uses_highlighted_width(app):
    pen = series_pen(0, highlighted=True)
    assert pen.widthF() == theme.PLOT_LINE_WIDTH_HIGHLIGHTED
