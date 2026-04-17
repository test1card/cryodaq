"""Centralized pyqtgraph styling — applies the design-system chart tokens.

Single source of truth for how a CryoDAQ plot should look. Every
`pg.PlotWidget` in dashboard / domain code should pass through
`apply_plot_style()` at construction time so that token changes in
`theme.py` propagate to every plot without per-widget edits.

See `docs/design-system/tokens/chart-tokens.md` and
`docs/design-system/components/chart-tile.md`.
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtGui import QFont

from cryodaq.gui import theme


def apply_plot_style(plot_widget: pg.PlotWidget) -> None:
    """Apply canonical CryoDAQ styling to a pyqtgraph PlotWidget.

    Uses the 12 design-system `PLOT_*` tokens for colors, widths, grid
    alpha. Axis ticks and labels render in Fira Sans
    (``theme.FONT_BODY``) at label size. Safe to call multiple times;
    overrides prior styling.
    """
    # Background / foreground
    plot_widget.setBackground(theme.PLOT_BG)

    # Grid — subtle, muted-foreground with low alpha
    plot_widget.showGrid(x=True, y=True, alpha=theme.PLOT_GRID_ALPHA)

    # Axes — shared font + tick pen + label pen across all four axes.
    # We do not touch axis widths here: left-axis width is coupled to
    # the multi-plot column alignment invariant (PLOT_AXIS_WIDTH_PX)
    # and is set by the caller when needed (e.g. TempPlotWidget sets
    # it explicitly on the "left" axis to align multiple stacked plots).
    tick_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
    for axis_name in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(axis_name)
        if axis is None:
            continue
        axis.setPen(pg.mkPen(color=theme.PLOT_TICK_COLOR, width=1))
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
