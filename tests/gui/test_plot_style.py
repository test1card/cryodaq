"""Tests for centralized pyqtgraph styling helpers (B.5.2)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui._plot_style import (
    apply_plot_style,
    fault_region_brush,
    series_pen,
    warn_region_brush,
)


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


def test_pg_global_foreground_is_plot_fg(app):
    # Module import must pin pyqtgraph's global foreground to PLOT_FG
    # so legends, untouched grid defaults, etc. pick up the design token.
    assert pg.getConfigOption("foreground") == theme.PLOT_FG


def test_pg_global_background_is_plot_bg(app):
    assert pg.getConfigOption("background") == theme.PLOT_BG


def test_warn_region_brush_applies_alpha_on_status_warning(app):
    brush = warn_region_brush()
    color = brush.color()
    assert color.name().lower() == theme.STATUS_WARNING.lower()
    assert abs(color.alphaF() - theme.PLOT_REGION_WARN_ALPHA) < 1e-3


def test_fault_region_brush_applies_alpha_on_status_fault(app):
    brush = fault_region_brush()
    color = brush.color()
    assert color.name().lower() == theme.STATUS_FAULT.lower()
    assert abs(color.alphaF() - theme.PLOT_REGION_FAULT_ALPHA) < 1e-3


def test_region_brush_accepts_custom_base_color(app):
    # Any operator-chosen base colour survives; only alpha is applied.
    brush = warn_region_brush(base_color=theme.STATUS_CAUTION)
    assert brush.color().name().lower() == theme.STATUS_CAUTION.lower()


def test_apply_plot_style_sets_axis_pens_to_grid_and_label_tokens(app):
    # axis.setPen(PLOT_GRID_COLOR) so that the grid (which inherits axis
    # pen) is rendered in the dim BORDER shade; axis.setTextPen
    # (PLOT_LABEL_COLOR) for tick labels.
    plot = pg.PlotWidget()
    apply_plot_style(plot)
    for axis_name in ("left", "bottom"):
        axis = plot.getAxis(axis_name)
        assert axis.pen().color().name().lower() == theme.PLOT_GRID_COLOR.lower()
        assert axis.textPen().color().name().lower() == theme.PLOT_LABEL_COLOR.lower()
