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
        # 2026-05-08 (v0.56.3 amend): widget-side Y-range cache for the
        # deadband helper — see _update_y_range_with_deadband for why we
        # do not trust pyqtgraph's getViewBox().viewRange() readings.
        self._y_cache_lo: float | None = None
        self._y_cache_hi: float | None = None
        self._y_last_set_ts: float = 0.0
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
        """Cache-driven deadband: rate-limit to ≥2 s between Y resizes,
        widen Y only when new bounds escape ±max(15%, 0.5 K) of the
        widget-cached last-set range.

        Two prior fixes failed to stop the jitter operator-side:
        - v0.56.2 used pyqtgraph ``enableAutoRange(axis="y", enable=0.95)``,
          which is a percentile selector that re-runs on every ``setData``.
        - v0.56.3 disabled native autoRange and read the current Y range
          via ``getViewBox().viewRange()[1]`` to gate the deadband.

        The v0.56.3 fix likely fired spuriously because pyqtgraph can
        report stale or default ``viewRange`` mid-update (especially
        right after ``setAxisItems`` / ``setData`` re-computes
        ``childrenBoundingRect``), so the comparison kept saying "drift
        too big, resize" even when no real envelope change had occurred.

        This version owns Y range state widget-side: cache the range
        we last asked pyqtgraph for, gate every future setYRange against
        that cache (never against pyqtgraph's reported view), and rate
        limit so even pathological signals can resize Y at most once
        per 2 seconds.
        """
        import time as _time

        if not in_window_y or self._is_log_y:
            return
        new_lo_raw = min(in_window_y)
        new_hi_raw = max(in_window_y)
        span = max(new_hi_raw - new_lo_raw, 1.0)
        new_lo = new_lo_raw - span * 0.05
        new_hi = new_hi_raw + span * 0.05
        pi = self._plot.getPlotItem()

        # First call — seed the cache without rate-limit / threshold gate.
        if self._y_cache_lo is None or self._y_cache_hi is None:
            pi.setYRange(new_lo, new_hi, padding=0)
            self._y_cache_lo = new_lo
            self._y_cache_hi = new_hi
            self._y_last_set_ts = _time.monotonic()
            return

        # Rate limit — at most one Y resize per 2 wall-clock seconds.
        now_mono = _time.monotonic()
        if now_mono - self._y_last_set_ts < 2.0:
            return

        # Threshold floor 0.5 K so sensor noise (~0.01-0.1 K) is absorbed
        # even when the visible span is small (steady-state at 4 K).
        cached_span = max(self._y_cache_hi - self._y_cache_lo, 1.0)
        threshold = max(cached_span * 0.15, 0.5)
        if (
            abs(new_lo - self._y_cache_lo) > threshold
            or abs(new_hi - self._y_cache_hi) > threshold
        ):
            pi.setYRange(new_lo, new_hi, padding=0)
            self._y_cache_lo = new_lo
            self._y_cache_hi = new_hi
            self._y_last_set_ts = now_mono

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
