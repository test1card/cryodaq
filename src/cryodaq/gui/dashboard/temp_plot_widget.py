"""Multi-channel temperature plot widget for the dashboard.

Receives data from ChannelBufferStore via refresh() called from
DashboardView's refresh timer. Time window picker, Lin/Log toggle,
and clickable legend live entirely inside this widget.
"""
from __future__ import annotations

import math
import time

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.time_window import TimeWindow

_LINE_PALETTE: list[str] = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#AEC7E8", "#FFBB78", "#98DF8A", "#FF9896", "#C5B0D5",
    "#C49C94", "#F7B6D2", "#C7C7C7", "#DBDB8D", "#9EDAE5",
    "#393B79", "#637939", "#8C6D31", "#843C39",
]

_MAX_POINTS = 2000


def _decimate(pts: list[tuple[float, float]], target: int) -> list[tuple[float, float]]:
    """Simple decimation via stride. Keeps first and last."""
    n = len(pts)
    if n <= target:
        return pts
    stride = max(1, n // target)
    result = pts[::stride]
    if result[-1] is not pts[-1]:
        result.append(pts[-1])
    return result


class TempPlotWidget(QWidget):
    """Multi-channel temperature plot for the dashboard."""

    time_window_changed = Signal(object)  # emits TimeWindow

    def __init__(
        self,
        buffer_store: ChannelBufferStore,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buffer = buffer_store
        self._channel_mgr = channel_manager
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._current_window = TimeWindow.default()
        self._is_log_y = False
        self._build_ui()
        self._rebuild_curves()
        self._channel_mgr.on_change(self._on_channels_changed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)

        self._time_buttons: dict[TimeWindow, QPushButton] = {}
        for tw in TimeWindow.all_options():
            btn = QPushButton(tw.label)
            btn.setCheckable(True)
            btn.setChecked(tw == self._current_window)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda checked, w=tw: self._on_time_window_clicked(w))
            self._time_buttons[tw] = btn
            self._style_time_button(btn, tw == self._current_window)
            toolbar.addWidget(btn)

        toolbar.addStretch()

        self._log_button = QPushButton("Lin Y")
        self._log_button.setCheckable(True)
        self._log_button.setFixedHeight(24)
        self._log_button.clicked.connect(self._on_log_y_toggled)
        self._style_time_button(self._log_button, False)
        toolbar.addWidget(self._log_button)

        root.addLayout(toolbar)

        # Plot
        self._plot = pg.PlotWidget()
        self._init_plot()
        root.addWidget(self._plot, stretch=1)

    @staticmethod
    def _style_time_button(btn: QPushButton, active: bool) -> None:
        if active:
            bg = theme.ACCENT_400
            fg = theme.TEXT_INVERSE
        else:
            bg = theme.SURFACE_PANEL
            fg = theme.TEXT_MUTED
        btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none; "
            f"border-radius: {theme.RADIUS_SM}px; padding: 2px 8px; }}"
            f"QPushButton:hover {{ background: {theme.SURFACE_CARD}; color: {theme.TEXT_SECONDARY}; }}"
        )

    def _init_plot(self) -> None:
        self._plot.setBackground(theme.SURFACE_CARD)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="K",
                     color=theme.TEXT_SECONDARY)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        pi.getAxis("bottom").setStyle(showValues=False)
        pi.addLegend(offset=(10, 10))

    def _rebuild_curves(self) -> None:
        """Create plot items for all visible Т-channels."""
        pi = self._plot.getPlotItem()
        # Remove old items
        for item in self._plot_items.values():
            pi.removeItem(item)
        self._plot_items.clear()
        if pi.legend is not None:
            pi.legend.clear()

        visible_ids = [ch for ch in self._channel_mgr.get_all_visible()
                       if ch.startswith("\u0422")]
        for idx, ch_id in enumerate(visible_ids):
            display = self._channel_mgr.get_display_name(ch_id)
            color = _LINE_PALETTE[idx % len(_LINE_PALETTE)]
            pen = pg.mkPen(color=color, width=1.5)
            item = self._plot.plot([], [], pen=pen, name=display)
            item.setDownsampling(auto=True, method="peak")
            item.setClipToView(True)
            self._plot_items[ch_id] = item

    def _on_channels_changed(self) -> None:
        self._rebuild_curves()

    # ------------------------------------------------------------------
    # Refresh (called by DashboardView at 1 Hz)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        now = time.time()
        window = self._current_window

        for ch_id, item in self._plot_items.items():
            pts = self._buffer.get_history(ch_id)
            if not pts:
                item.setData([], [])
                continue
            if len(pts) > _MAX_POINTS:
                pts = _decimate(pts, _MAX_POINTS)
            xs = [t for t, _ in pts]
            ys = [v for _, v in pts]
            item.setData(x=xs, y=ys)

        if window == TimeWindow.ALL:
            self._plot.enableAutoRange(axis="x")
        else:
            x_max = now
            x_min = now - window.seconds
            self._plot.setXRange(x_min, x_max, padding=0)

    # ------------------------------------------------------------------
    # Time picker
    # ------------------------------------------------------------------

    def _on_time_window_clicked(self, window: TimeWindow) -> None:
        self._current_window = window
        for tw, btn in self._time_buttons.items():
            btn.setChecked(tw == window)
            self._style_time_button(btn, tw == window)
        self.time_window_changed.emit(window)
        self.refresh()

    # ------------------------------------------------------------------
    # Lin/Log toggle
    # ------------------------------------------------------------------

    def _on_log_y_toggled(self, checked: bool) -> None:
        self._is_log_y = checked
        self._plot.getPlotItem().setLogMode(x=False, y=checked)
        self._log_button.setText("Log Y" if checked else "Lin Y")
        self._style_time_button(self._log_button, checked)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: ANN001
        """Clean up ChannelManager subscription on widget close."""
        try:
            self._channel_mgr.off_change(self._on_channels_changed)
        except Exception:
            pass
        super().closeEvent(event)
