"""Multi-channel temperature plot widget for the dashboard.

Receives data from ChannelBufferStore via refresh() called from
DashboardView's refresh timer. Time window picker, Lin/Log toggle,
and clickable legend live entirely inside this widget.
"""

from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore, peak_preserving_decimate
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
)
from cryodaq.gui.state.time_window_selector import TimeWindowSelector

_MAX_POINTS = 2000
# Opacity applied to a legend entry whose curve the operator has hidden.
_LEGEND_HIDDEN_OPACITY = 0.35


class _ClickableLegendLabel(pg.LabelItem):
    """Legend text that toggles its curve, like the sample swatch does.

    pyqtgraph's ``ItemSample`` already toggles visibility when the colour
    swatch is clicked, but the channel NAME beside it is an inert
    ``LabelItem``. Operators click the name, so the plot appeared to have
    lost the feature entirely. This restores it on the label and keeps the
    two in sync, dimming the entry so a hidden channel is visible as hidden
    rather than silently absent.
    """

    def __init__(self, text: str, sample: pg.ItemSample, **kwargs: object) -> None:
        super().__init__(text, **kwargs)
        self._sample = sample
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def _sync_opacity(self) -> None:
        item = getattr(self._sample, "item", None)
        visible = True if item is None else bool(item.isVisible())
        self.setOpacity(1.0 if visible else _LEGEND_HIDDEN_OPACITY)

    def mousePressEvent(self, event: object) -> None:
        item = getattr(self._sample, "item", None)
        if item is None:
            super().mousePressEvent(event)
            return
        item.setVisible(not item.isVisible())
        self._sample.update()
        self._sync_opacity()
        event.accept()


class _ClickableLegend(pg.LegendItem):
    """LegendItem whose labels are clickable as well as its samples."""

    def addItem(self, item: object, name: str) -> None:  # noqa: D102 — pyqtgraph API
        sample = item if isinstance(item, self.sampleType) else self.sampleType(item)
        label = _ClickableLegendLabel(
            name,
            sample,
            color=self.opts["labelTextColor"],
            justify="left",
            size=self.opts["labelTextSize"],
        )
        self.items.append((sample, label))
        self._addItemToLayout(sample, label)
        self.updateSize()


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
        # The X axis is shared with the pressure plot below, and this one used
        # to hide its tick labels on the usual stacked-plot convention that the
        # bottom-most plot carries them. In this layout that does not work: the
        # temperature plot is the tall one operators actually read (stretch 50
        # against 18), and its times were an axis-height away at the bottom of
        # another widget. Reading a temperature off a curve meant tracking down
        # past the pressure plot to find when it happened.
        pi.getAxis("bottom").setStyle(showValues=True)
        # Same wiring as PlotItem.addLegend(), with the clickable subclass so
        # the channel name toggles its curve and not only the colour swatch.
        if pi.legend is None:
            pi.legend = _ClickableLegend(offset=(10, 10))
            pi.legend.setParentItem(pi.vb)

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

    def set_channel_plotted(self, channel_id: str, plotted: bool) -> None:
        """Show or hide one curve, keeping its legend entry in sync.

        Same effect as clicking the legend entry, exposed so the dashboard's
        sensor cards can drive it too. Silently ignores unknown channels —
        the grid and the plot can hold different channel sets between a
        visibility change and the next rebuild.
        """
        item = self._plot_items.get(channel_id)
        if item is None:
            return
        item.setVisible(bool(plotted))
        legend = self._plot.getPlotItem().legend
        if legend is not None:
            for sample, label in legend.items:
                if getattr(sample, "item", None) is item and hasattr(label, "_sync_opacity"):
                    label._sync_opacity()
                    sample.update()
                    break

    def is_channel_plotted(self, channel_id: str) -> bool:
        """Whether this channel's curve is currently drawn."""
        item = self._plot_items.get(channel_id)
        return True if item is None else bool(item.isVisible())

    def _on_channels_changed(self) -> None:
        self._rebuild_curves()

    # ------------------------------------------------------------------
    # Refresh (called by DashboardView at no more than 2 Hz)
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
                pts = peak_preserving_decimate(pts, _MAX_POINTS)
            xs = [t for t, _ in pts]
            ys = [v for _, v in pts]
            item.setData(x=xs, y=ys)
            if not item.isVisible():
                # Operator hid this curve from the legend. Keep feeding it so
                # unhiding is instant, but leave it out of the Y range —
                # otherwise hiding an out-of-scale channel would not actually
                # declutter the axis, which is the whole point of hiding it.
                continue
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

        # Seed once, then preserve the operator's viewport. Scale toggles
        # explicitly clear the cache and authorize one compatible reseed.
        self._update_y_range_with_deadband(in_window_y)

    def _update_y_range_with_deadband(self, in_window_y: list[float]) -> None:
        """Seed one compatible Y range without overriding later operator zoom.

        Refreshes never authorize live auto-ranging. The only intentional
        cache reset is an explicit linear/log scale change.
        """
        import math

        values = [value for value in in_window_y if math.isfinite(value) and (not self._is_log_y or value > 0.0)]
        if not values:
            return
        if self._is_log_y:
            values = [math.log10(value) for value in values]
        new_lo_raw = min(values)
        new_hi_raw = max(values)
        span = max(new_hi_raw - new_lo_raw, 0.1 if self._is_log_y else 1.0)
        new_lo = new_lo_raw - span * 0.05
        new_hi = new_hi_raw + span * 0.05
        pi = self._plot.getPlotItem()

        if self._y_cache_lo is not None and self._y_cache_hi is not None:
            return
        pi.setYRange(new_lo, new_hi, padding=0)
        self._y_cache_lo = new_lo
        self._y_cache_hi = new_hi

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
        self._y_cache_lo = None
        self._y_cache_hi = None
        self._log_button.setText("Лог Y" if checked else "Лин Y")
        self._style_time_button(self._log_button, checked)
        self.refresh()

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
