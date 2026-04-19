"""Shared pressure plot — scientific-notation log-Y axis.

Used by dashboard, analytics view (after III.C integration), archive
viewer, and any future surface rendering pressure history. Provides:

- Log-Y always (RULE-DATA-008 — cryogenic vacuum spans many orders).
- Custom scientific-notation tick formatter so compact panels still
  render readable Y labels (fixes the dashboard pressure panel's
  missing ticks).
- Optional subscription to :class:`GlobalTimeWindowController` for
  historical mode. Forward-looking mode (prediction widgets) bypasses
  subscription.

Public API:

- ``set_series(times, values)`` — update main curve (guards
  non-positive values for log-Y).
- ``set_title(text)`` — plot title.
- ``plot_item`` — expose the underlying ``PlotWidget`` for setXLink
  cross-plot synchronization.
"""

from __future__ import annotations

import math
import time

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
)


class ScientificLogAxisItem(pg.AxisItem):
    """Log-axis tick formatter that emits scientific-notation labels.

    pyqtgraph's default log-Y formatter prints `1e-6`, `1e-5` etc. but
    only for exact decade ticks; compact panels with a narrow range
    often end up with no labels at all because no decade fits.
    This subclass formats every tick value in `{m}e{exp}` form,
    clipping exponents and rounding mantissa to 1 decimal.
    """

    def tickStrings(self, values, scale, spacing):
        out: list[str] = []
        for v in values:
            # Values from a log-Y axis come in as log10(pressure).
            try:
                power = 10.0 ** float(v)
            except (TypeError, ValueError, OverflowError):
                out.append("")
                continue
            if power == 0 or not math.isfinite(power):
                out.append("")
                continue
            exponent = int(math.floor(math.log10(abs(power))))
            mantissa = power / (10**exponent)
            if abs(mantissa - round(mantissa)) < 0.05:
                mantissa_text = f"{int(round(mantissa))}"
            else:
                mantissa_text = f"{mantissa:.1f}"
            out.append(f"{mantissa_text}e{exponent}")
        return out


class PressurePlot(QWidget):
    """Shared log-Y pressure plot with scientific-notation ticks."""

    def __init__(
        self,
        *,
        title: str | None = None,
        forward_looking: bool = False,
        show_date_axis: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._forward_looking = bool(forward_looking)
        self._show_date_axis = bool(show_date_axis)
        self._title = title
        self._curve: pg.PlotDataItem | None = None
        self._build_ui()
        if not self._forward_looking:
            controller = get_time_window_controller()
            self._apply_window(controller.get_window())
            controller.window_changed.connect(self._apply_window)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._plot = pg.PlotWidget(axisItems={"left": ScientificLogAxisItem(orientation="left")})
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Давление", units="мбар", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").setWidth(theme.PLOT_AXIS_WIDTH_PX)
        if self._show_date_axis and not self._forward_looking:
            pi.setLabel("bottom", "Время", color=theme.PLOT_LABEL_COLOR)
            date_axis = pg.DateAxisItem(orientation="bottom")
            self._plot.setAxisItems({"bottom": date_axis})
        else:
            pi.setLabel("bottom", "Время", units="с", color=theme.PLOT_LABEL_COLOR)
        pi.setLogMode(x=False, y=True)
        if self._title:
            pi.setTitle(self._title)
        self._curve = self._plot.plot([], [], pen=series_pen(0))
        root.addWidget(self._plot)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_series(self, times: list[float], values: list[float]) -> None:
        """Update the main curve. Guards non-positive values for log-Y."""
        if self._curve is None:
            return
        clamped_values = [v if v > 0 else 1e-12 for v in values]
        self._curve.setData(x=list(times), y=clamped_values)

    def set_title(self, text: str) -> None:
        self._title = text
        self._plot.getPlotItem().setTitle(text)

    @property
    def plot_item(self) -> pg.PlotWidget:
        return self._plot

    # ------------------------------------------------------------------
    # Window control
    # ------------------------------------------------------------------

    def _apply_window(self, window: TimeWindow) -> None:
        if self._forward_looking:
            return
        pi = self._plot.getPlotItem()
        seconds = window.seconds
        if not math.isfinite(seconds):
            # ALL — restore full-history X range. enableAutoRange alone
            # leaves the prior fixed window visible until the next
            # setData; call autoRange() directly so the X range jumps
            # to the full extent of the current curve's data
            # immediately. Autorange remains armed for subsequent ticks.
            pi.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
            pi.autoRange()
            return
        now = time.time()
        pi.setXRange(now - seconds, now, padding=0)
