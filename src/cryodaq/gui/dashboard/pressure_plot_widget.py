"""Compact log-Y pressure plot for the dashboard.

No toolbar — synchronizes X axis with the temperature plot via
setXLink in DashboardView. Always uses log Y because cryogenic
vacuum spans many orders of magnitude.
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from cryodaq.gui import theme
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
        self._plot.setBackground(theme.SURFACE_CARD)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Давление", units="mbar",
                     color=theme.TEXT_SECONDARY)
        pi.getAxis("left").setWidth(theme.PLOT_AXIS_WIDTH_PX)
        pi.setLabel("bottom", "Время", color=theme.TEXT_SECONDARY)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        pi.setLogMode(x=False, y=True)
        self._curve = self._plot.plot(
            [], [], pen=pg.mkPen("#FF7F0E", width=2),
        )

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
