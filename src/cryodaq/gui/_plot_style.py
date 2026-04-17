"""Centralized pyqtgraph styling — applies the design-system chart tokens.

Single source of truth for how a CryoDAQ plot should look. Every
`pg.PlotWidget` in dashboard / domain code should pass through
`apply_plot_style()` at construction time so that token changes in
`theme.py` propagate to every plot without per-widget edits.

Token coverage: this module consumes 11 of the 12 canonical PLOT_*
tokens from `docs/design-system/tokens/chart-tokens.md`. The single
exception is `PLOT_AXIS_WIDTH_PX`, which the spec explicitly leaves
to the caller so that multiple stacked plots can align their y-axis
columns by setting it on the appropriate axis (see TempPlotWidget
and PressurePlotWidget).

Tokens applied here:
  * PLOT_BG              — set as pyqtgraph global background and
                           per-widget background
  * PLOT_FG              — set as pyqtgraph global foreground
                           (legend text, default lines)
  * PLOT_GRID_COLOR      — axis pen color; pyqtgraph derives grid
                           colour from the axis pen, so this becomes
                           the grid colour
  * PLOT_GRID_ALPHA      — showGrid(alpha=...) transparency
  * PLOT_TICK_COLOR      — tick pen (setTickPen on pyqtgraph >= 0.13;
                           falls back silently on older versions)
  * PLOT_LABEL_COLOR     — setTextPen for tick labels and axis title
  * PLOT_LINE_PALETTE    — series_pen() cycles through these 8 hues
  * PLOT_LINE_WIDTH      — default series stroke width
  * PLOT_LINE_WIDTH_HIGHLIGHTED — series_pen(highlighted=True) width
  * PLOT_REGION_WARN_ALPHA — warn_region_brush() alpha over
                           STATUS_WARNING base colour
  * PLOT_REGION_FAULT_ALPHA — fault_region_brush() alpha over
                           STATUS_FAULT base colour
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtGui import QColor, QFont

from cryodaq.gui import theme

# Module-import side effect: set pyqtgraph's global foreground /
# background defaults so that any untouched plot construction falls
# through to the design-system tokens. Per-widget apply_plot_style()
# calls still set the background explicitly (pyqtgraph caches a
# per-widget brush), but grid/legend text picks up PLOT_FG from here.
pg.setConfigOption("foreground", theme.PLOT_FG)
pg.setConfigOption("background", theme.PLOT_BG)


def apply_plot_style(plot_widget: pg.PlotWidget) -> None:
    """Apply canonical CryoDAQ styling to a pyqtgraph PlotWidget.

    Safe to call multiple times; overrides prior styling.
    """
    plot_widget.setBackground(theme.PLOT_BG)
    plot_widget.showGrid(x=True, y=True, alpha=theme.PLOT_GRID_ALPHA)

    tick_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
    for axis_name in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(axis_name)
        if axis is None:
            continue
        # axis.setPen() colours the axis line AND the grid (pyqtgraph
        # grid inherits axis pen colour). Use PLOT_GRID_COLOR (BORDER,
        # dim) here so the grid is subtle; tick marks are lifted back
        # to PLOT_TICK_COLOR (FOREGROUND, bright) via setTickPen below
        # where the API is available.
        axis.setPen(pg.mkPen(color=theme.PLOT_GRID_COLOR, width=1))
        try:
            # pyqtgraph >= 0.13 separates tick pen from axis pen.
            axis.setTickPen(pg.mkPen(color=theme.PLOT_TICK_COLOR, width=1))
        except AttributeError:
            pass
        axis.setTextPen(pg.mkPen(color=theme.PLOT_LABEL_COLOR))
        axis.setStyle(tickFont=tick_font)


def series_pen(
    index: int,
    *,
    highlighted: bool = False,
    style: Any = None,
) -> pg.mkPen:
    """Return a pyqtgraph pen for series `index` using `PLOT_LINE_PALETTE`.

    The palette cycles on overflow. Callers should pass the channel
    index (or position in a visible-channels list). Use `highlighted`
    for the currently-selected / focus-followed series.
    """
    palette = theme.PLOT_LINE_PALETTE
    color = palette[index % len(palette)]
    width = theme.PLOT_LINE_WIDTH_HIGHLIGHTED if highlighted else theme.PLOT_LINE_WIDTH
    if style is not None:
        return pg.mkPen(color=color, width=width, style=style)
    return pg.mkPen(color=color, width=width)


def warn_region_brush(base_color: str | None = None) -> pg.mkBrush:
    """Return a pyqtgraph brush for a warning region overlay.

    Applies `PLOT_REGION_WARN_ALPHA` on top of the provided base colour
    (defaults to `theme.STATUS_WARNING`). Intended for `LinearRegionItem`
    / `FillBetweenItem` overlays marking "warning" zones on a plot.
    """
    color = QColor(base_color or theme.STATUS_WARNING)
    color.setAlphaF(theme.PLOT_REGION_WARN_ALPHA)
    return pg.mkBrush(color)


def fault_region_brush(base_color: str | None = None) -> pg.mkBrush:
    """Return a pyqtgraph brush for a fault region overlay.

    Applies `PLOT_REGION_FAULT_ALPHA` on top of the provided base colour
    (defaults to `theme.STATUS_FAULT`). Intended for `LinearRegionItem`
    / `FillBetweenItem` overlays marking "fault" zones on a plot.
    """
    color = QColor(base_color or theme.STATUS_FAULT)
    color.setAlphaF(theme.PLOT_REGION_FAULT_ALPHA)
    return pg.mkBrush(color)
