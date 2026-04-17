"""Compact log-Y pressure plot for the dashboard.

No toolbar — synchronizes X axis with the temperature plot via
setXLink in DashboardView. Always uses log Y because cryogenic
vacuum spans many orders of magnitude.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore

_MAX_POINTS = 2000


def _decimate(pts: list[tuple[float, float]], target: int) -> list[tuple[float, float]]:
    n = len(pts)
    if n <= target:
        return pts
    stride = max(1, n // target)
    result = pts[::stride]
    if result[-1] is not pts[-1]:
        result.append(pts[-1])
    return result


class PressurePlotWidget(QWidget):
    """Compact log-Y pressure plot for the dashboard."""

    def __init__(
        self,
        buffer_store: ChannelBufferStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buffer = buffer_store
        self._channel_id = "VSP63D_1/pressure"
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._plot = pg.PlotWidget()
        self._init_plot()
        root.addWidget(self._plot)

    def _init_plot(self) -> None:
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        # DESIGN: RULE-COPY-006 — operator-facing pressure unit is Cyrillic мбар.
        pi.setLabel("left", "Давление", units="мбар", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").setWidth(theme.PLOT_AXIS_WIDTH_PX)
        pi.setLabel("bottom", "Время", color=theme.PLOT_LABEL_COLOR)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        # DESIGN: RULE-DATA-008 — pressure plots mandatory log-Y.
        pi.setLogMode(x=False, y=True)
        # Single-series pressure curve uses palette slot 0
        # (COLD_HIGHLIGHT by convention; see tokens/chart-tokens.md).
        self._curve = self._plot.plot([], [], pen=series_pen(0))

    def refresh(self) -> None:
        pts = self._buffer.get_history(self._channel_id)
        if not pts:
            return
        if len(pts) > _MAX_POINTS:
            pts = _decimate(pts, _MAX_POINTS)
        xs = [t for t, _ in pts]
        # Guard non-positive for log Y
        ys = [v if v > 0 else 1e-12 for _, v in pts]
        self._curve.setData(x=xs, y=ys)
