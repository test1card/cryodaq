"""Multi-channel temperature plot widget for the dashboard.

Receives data from ChannelBufferStore via refresh() called from
DashboardView's refresh timer. Time window picker, Lin/Log toggle,
and clickable legend live entirely inside this widget.
"""

from __future__ import annotations

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
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
)
from cryodaq.gui.state.time_window_selector import TimeWindowSelector

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
        # Phase III.B: single source of truth is the global controller;
        # no local TimeWindow state. `_current_window` is a cached
        # mirror refreshed from the broadcast.
        self._current_window = get_time_window_controller().get_window()
        self._is_log_y = False
        self._build_ui()
        self._rebuild_curves()
        self._channel_mgr.on_change(self._on_channels_changed)
        get_time_window_controller().window_changed.connect(self._on_global_window_changed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # Toolbar — Phase III.B: TimeWindowSelector drives the global
        # controller; this plot subscribes to the broadcast.
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        self._time_selector = TimeWindowSelector(show_6h=True)
        toolbar.addWidget(self._time_selector)
        toolbar.addStretch()

        self._log_button = QPushButton("Лин Y")
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
            f"QPushButton:hover {{ background: {theme.SURFACE_CARD}; color: {theme.TEXT_SECONDARY}; }}"  # noqa: E501
        )

    def _init_plot(self) -> None:
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="K", color=theme.PLOT_LABEL_COLOR)
        left_axis = pi.getAxis("left")
        # Cryogenic plots must read absolute K; forbid pyqtgraph's default
        # auto-rescale to mK / µK when the value range crosses decades.
        left_axis.enableAutoSIPrefix(False)
        left_axis.setWidth(theme.PLOT_AXIS_WIDTH_PX)
        # 2026-05-08 (v0.56.3): manual Y deadband applied in refresh().
        # pyqtgraph's enableAutoRange(enable=<float>) is a percentile of
        # data range, NOT hysteresis — it still recomputes on every
        # setData → visible jitter. Disable native autoRange on Y so
        # _update_y_range_with_deadband owns the axis end-to-end.
        pi.disableAutoRange(axis="y")
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

        visible_ids = [ch for ch in self._channel_mgr.get_all_visible() if ch.startswith("\u0422")]
        for idx, ch_id in enumerate(visible_ids):
            display = self._channel_mgr.get_display_name(ch_id)
            # DESIGN: tokens/chart-tokens.md — palette cycles PLOT_LINE_PALETTE
            # with PLOT_LINE_WIDTH; centralized in _plot_style.series_pen().
            pen = series_pen(idx)
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
        import math

        now = time.time()
        window = self._current_window
        x_min = now - window.seconds if window != TimeWindow.ALL else None

        in_window_y: list[float] = []
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
            for t, v in pts:
                if not math.isfinite(v):
                    continue
                if x_min is None or t >= x_min:
                    in_window_y.append(v)

        if window == TimeWindow.ALL:
            self._plot.enableAutoRange(axis="x")
        else:
            x_max = now
            self._plot.setXRange(x_min, x_max, padding=0)

        # 2026-05-08 (v0.56.3): manual Y deadband — see _init_plot for why
        # pyqtgraph's float enable= autoRange is not enough.
        self._update_y_range_with_deadband(in_window_y)

    def _update_y_range_with_deadband(self, in_window_y: list[float]) -> None:
        """Resize Y range only if new data drifts outside ±10% of current span.

        pyqtgraph rescales on every setData call by default — that is
        what produces the per-sample jitter the operator sees. Tracking
        a deadband here keeps the visible band stable while the data
        wanders, and only redraws when the actual envelope changes.
        """
        if not in_window_y or self._is_log_y:
            return
        new_lo = min(in_window_y)
        new_hi = max(in_window_y)
        span = max(new_hi - new_lo, 1.0)
        new_lo -= span * 0.05
        new_hi += span * 0.05
        pi = self._plot.getPlotItem()
        cur_lo, cur_hi = pi.getViewBox().viewRange()[1]
        cur_span = max(cur_hi - cur_lo, 1.0)
        threshold = cur_span * 0.10
        if abs(new_lo - cur_lo) > threshold or abs(new_hi - cur_hi) > threshold:
            pi.setYRange(new_lo, new_hi, padding=0)

    # ------------------------------------------------------------------
    # Time picker
    # ------------------------------------------------------------------

    def _on_global_window_changed(self, window: TimeWindow) -> None:
        """Receive broadcast from GlobalTimeWindowController."""
        self._current_window = window
        self.time_window_changed.emit(window)
        self.refresh()

    # ------------------------------------------------------------------
    # Lin/Log toggle
    # ------------------------------------------------------------------

    def _on_log_y_toggled(self, checked: bool) -> None:
        self._is_log_y = checked
        self._plot.getPlotItem().setLogMode(x=False, y=checked)
        self._log_button.setText("Лог Y" if checked else "Лин Y")
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
