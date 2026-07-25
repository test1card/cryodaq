"""Compact log-Y pressure plot for the dashboard.

Phase III.B: delegates to :class:`cryodaq.gui.widgets.shared.PressurePlot`
for rendering + scientific-notation tick labels. This wrapper keeps
the existing dashboard API (``refresh()`` + ``_plot`` for the
``setXLink`` side-channel used by :class:`DashboardView`).
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore, peak_preserving_decimate
from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot

_MAX_POINTS = 2000


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
        self._shared = PressurePlot()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._shared)

    @property
    def _plot(self):
        """Expose underlying PlotWidget so DashboardView.setXLink works."""
        return self._shared.plot_item

    def refresh(self) -> None:
        pts = self._buffer.get_history(self._channel_id)
        if not pts:
            return
        if len(pts) > _MAX_POINTS:
            pts = peak_preserving_decimate(pts, _MAX_POINTS)
        xs = [t for t, _ in pts]
        ys = [v for _, v in pts]
        self._shared.set_series(xs, ys)
