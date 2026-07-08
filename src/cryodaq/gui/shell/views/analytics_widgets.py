"""Analytics widget registry — keyed by YAML config ID.

Each widget is a self-contained QWidget with setter methods for its
specific data type(s). :class:`AnalyticsView` composes widgets per
``config/analytics_layout.yaml``.

Widgets without live data pipelines yet render a placeholder card —
layout stays coherent while data wiring catches up.

Phase III.C contract:
- Widget IDs in this module map 1:1 to YAML ``phases[<phase>].main``,
  ``top_right``, ``bottom_right`` values.
- Widgets declare setter methods whose names :class:`AnalyticsView`
  uses via duck-typing to forward shell data pushes. Unimplemented
  setters are simply skipped.
- All widgets use DS v1.0.1 tokens only. Interactive chrome (buttons,
  focus rings) uses Phase III.A ``ACCENT`` / ``SELECTION_BG`` /
  ``FOCUS_RING`` — never the status tier.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip
from cryodaq.gui.state.time_window import (
    TimeWindow,
    get_time_window_controller,
)
from cryodaq.gui.widgets.shared.prediction_widget import PredictionWidget
from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot
from cryodaq.gui.widgets.shared.time_window_selector import TimeWindowSelector

# ---------------------------------------------------------------------------
# Widget IDs — must match YAML
# ---------------------------------------------------------------------------

WIDGET_TEMPERATURE_OVERVIEW = "temperature_overview"
WIDGET_VACUUM_PREDICTION = "vacuum_prediction"
WIDGET_COOLDOWN_PREDICTION = "cooldown_prediction"
WIDGET_R_THERMAL_LIVE = "r_thermal_live"
WIDGET_PRESSURE_CURRENT = "pressure_current"
WIDGET_SENSOR_HEALTH_SUMMARY = "sensor_health_summary"
WIDGET_KEITHLEY_POWER = "keithley_power"
WIDGET_R_THERMAL_PLACEHOLDER = "r_thermal_placeholder"
WIDGET_TEMPERATURE_TRAJECTORY = "temperature_trajectory"
WIDGET_COOLDOWN_HISTORY = "cooldown_history"
WIDGET_EXPERIMENT_SUMMARY = "experiment_summary"
# v0.55.6.1 — measurement-phase asymptotic temperature prediction.
# Architect 2026-05-07: «в фазе измерения до сих пор R, а не прогноз
# по температуре (пусть и асимптотический)». The widget pairs T11
# (cooler stage) and T12 (nitrogen plate) with their own
# SteadyStatePredictor instances and surfaces the asymptote + ±σ band
# on the same plot.
WIDGET_TEMPERATURE_STEADY_STATE = "temperature_steady_state"

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, Callable[[], QWidget]] = {}


def register(widget_id: str, factory: Callable[[], QWidget]) -> None:
    _registry[widget_id] = factory


def create(widget_id: str | None) -> QWidget | None:
    if widget_id is None:
        return None
    factory = _registry.get(widget_id)
    if factory is None:
        raise KeyError(f"Analytics widget not registered: {widget_id}")
    widget = factory()
    # Tag the instance with its registry ID so AnalyticsView can
    # decide whether a re-layout should keep or replace an existing
    # widget.
    widget.setProperty("analytics_widget_id", widget_id)
    return widget


def id_of(widget: QWidget | None) -> str | None:
    if widget is None:
        return None
    val = widget.property("analytics_widget_id")
    return str(val) if val else None


def available_ids() -> list[str]:
    return sorted(_registry.keys())


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _card(object_name: str) -> QFrame:
    card = QFrame()
    card.setObjectName(object_name)
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet(
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )
    return card


def _title_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    label.setFont(font)
    label.setStyleSheet(
        f"color: {theme.FOREGROUND}; background: transparent; border: none; letter-spacing: 0.5px;"
    )
    return label


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    label.setFont(font)
    label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label


def _mono_value_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    label.setFont(font)
    label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
    return label


# ---------------------------------------------------------------------------
# Worker-cleanup mixin
# ---------------------------------------------------------------------------


class _WorkerCleanupMixin:
    """Wait for any ZmqCommandWorker QThreads this widget owns before it is
    destroyed.

    These widgets create ``ZmqCommandWorker(parent=self)`` QThreads to fetch
    data. If the widget is destroyed while a worker is still running, Qt aborts
    with "QThread: Destroyed while thread is still running" — a flaky segfault on
    Windows CI when a test (or teardown) deletes the widget mid-fetch. Joining
    the workers in closeEvent makes destruction safe.
    """

    _WORKER_ATTRS = ("_history_worker", "_alarm_worker", "_stats_worker")

    def closeEvent(self, event):  # noqa: ANN001
        for name in self._WORKER_ATTRS:
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    worker.wait(2000)
            except RuntimeError:
                pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Placeholder widget — «данные появятся при переходе фазы»
# ---------------------------------------------------------------------------


class PlaceholderCard(QWidget):
    """Placeholder card for widgets whose data pipeline is not yet wired."""

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        card = _card("analyticsPlaceholder")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        layout.setSpacing(theme.SPACE_2)
        layout.addWidget(_title_label(title))
        layout.addStretch()
        body = subtitle if subtitle is not None else f"{title} — данные появятся при переходе фазы."
        layout.addWidget(_muted_label(body))
        layout.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)


# ---------------------------------------------------------------------------
# Concrete widgets
# ---------------------------------------------------------------------------


@dataclass
class _ChannelSeries:
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)


class TemperatureOverviewWidget(_WorkerCleanupMixin, QWidget):
    """Compact multi-channel temperature plot following the global
    time window. Subscribes to ``GlobalTimeWindowController``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._series: dict[str, _ChannelSeries] = {}
        self._history_worker = None
        self._last_history_fetch_ts: float = 0.0
        self._window_selector = TimeWindowSelector()
        # 2026-05-08 (v0.56.3 amend): widget-side Y-range cache. See
        # _update_y_range_with_deadband for why pyqtgraph's reported
        # viewRange is not trustworthy as the deadband reference.
        self._y_cache_lo: float | None = None
        self._y_cache_hi: float | None = None
        self._y_last_set_ts: float = 0.0
        self._build_ui()
        self._window_selector.window_changed.connect(self._apply_window)
        self._fetch_history()
        self._apply_window(self._window_selector.get_window())

    def _build_ui(self) -> None:
        card = _card("analyticsTemperatureOverview")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(theme.SPACE_2)
        header.addWidget(_title_label("Температурные каналы"))
        header.addStretch()
        header.addWidget(self._window_selector)
        lay.addLayout(header)
        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        # 2026-05-08 (v0.56.3 amend): disable Y autoRange at construction
        # time, NOT only at first _apply_window — the v0.56.3 ordering
        # left a window where pyqtgraph could re-arm autoRange before
        # _apply_window ran. _update_y_range_with_deadband owns Y end
        # to end via a widget-side cache.
        pi.disableAutoRange(axis="y")
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        pi.addLegend(offset=(10, 10))
        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    # ------------------------------------------------------------------
    # Data ingestion — shell pushes via set_temperature_readings.
    # ------------------------------------------------------------------

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        for ch_id, reading in readings.items():
            ts = reading.timestamp.timestamp()
            series = self._series.setdefault(ch_id, _ChannelSeries())
            series.xs.append(ts)
            series.ys.append(float(reading.value))
            # Trim to avoid unbounded memory growth (24h ×1Hz ≈ 86k).
            max_pts = 5000
            if len(series.xs) > max_pts:
                del series.xs[: len(series.xs) - max_pts]
                del series.ys[: len(series.ys) - max_pts]
            if ch_id not in self._curves:
                curve = self._plot.plot([], [], pen=series_pen(len(self._curves)), name=ch_id)
                self._curves[ch_id] = curve
            self._curves[ch_id].setData(x=series.xs, y=series.ys)
        # Scroll the X window to keep live data visible; _apply_window was
        # called once at __init__ with the T₀ snapshot — without this call
        # every batch, the right edge stays frozen at T₀ and live readings
        # (timestamps > T₀) fall outside the visible range.
        self._apply_window(self._window_selector.get_window())

    # ------------------------------------------------------------------
    # Window control
    # ------------------------------------------------------------------

    def _apply_window(self, window: TimeWindow) -> None:
        import math
        import time

        pi = self._plot.getPlotItem()
        if not math.isfinite(window.seconds):
            pi.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
            pi.autoRange()
            # Trigger history backfill if switching to ALL with sparse data.
            self._maybe_refetch_history(window)
            return
        now = time.time()
        pi.setXRange(now - window.seconds, now, padding=0)
        # 2026-05-08 (v0.56.3): manual Y deadband. pyqtgraph's
        # enableAutoRange(enable=<float>) is a percentile selector that
        # still recomputes the range on every setData → visible
        # per-sample jitter. _update_y_range_with_deadband owns Y.
        pi.disableAutoRange(axis=pg.ViewBox.YAxis)
        self._update_y_range_with_deadband(now - window.seconds, now)
        self._maybe_refetch_history(window)

    def _update_y_range_with_deadband(self, x_lo: float, x_hi: float) -> None:
        """Cache-driven Y deadband — see TempPlotWidget for the rationale.

        v0.56.3 used ``getViewBox().viewRange()`` as the deadband
        reference, but pyqtgraph can return stale or default values
        right after ``setData`` / ``setAxisItems`` recompute
        ``childrenBoundingRect``, so the comparison kept firing on
        every tick. This version caches the last range we asked
        pyqtgraph to apply and gates future setYRange calls against
        that cache, never against pyqtgraph's reported view. Combined
        with a 2 s rate limit and a 0.5 K threshold floor, the Y axis
        becomes visually stable under live mock + replay 60×/600×.
        """
        import math
        import time as _time

        in_window: list[float] = []
        for series in self._series.values():
            for x, y in zip(series.xs, series.ys):
                if x_lo <= x <= x_hi and math.isfinite(y):
                    in_window.append(y)
        if not in_window:
            return
        new_lo_raw = min(in_window)
        new_hi_raw = max(in_window)
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

        # Rate limit — ≤1 Y resize per 2 wall-clock seconds.
        now_mono = _time.monotonic()
        if now_mono - self._y_last_set_ts < 2.0:
            return

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

    def _maybe_refetch_history(self, window: TimeWindow) -> None:
        import math
        import time
        if time.time() - self._last_history_fetch_ts < 1.0:
            return
        # Check if any series has enough data to cover the window.
        requested_secs = window.seconds if math.isfinite(window.seconds) else 7 * 24 * 3600.0
        for series in self._series.values():
            if len(series.xs) >= 2:
                span = series.xs[-1] - series.xs[0]
                if span >= requested_secs * 0.9:
                    return  # sufficient data
        self._fetch_history()

    def _fetch_history(self) -> None:
        import time as _time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._last_history_fetch_ts = _time.time()
        channel_mgr = get_channel_manager()
        cold_ids = channel_mgr.get_cold_channels() or []
        channels = [channel_mgr.get_display_name(ch) for ch in cold_ids] or None
        window = self._window_selector.get_window()
        import math as _math
        span = window.seconds if _math.isfinite(window.seconds) else 7 * 24 * 3600.0
        cmd = {
            "cmd": "readings_history",
            "from_ts": _time.time() - span,
            "to_ts": _time.time(),
            "channels": channels,
            "limit_per_channel": 5000,
        }
        self._history_worker = ZmqCommandWorker(cmd, parent=self)
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        if not result.get("ok"):
            return
        data: dict[str, list] = result.get("data", {})
        for channel, points in data.items():
            if not points:
                continue
            series = self._series.setdefault(channel, _ChannelSeries())
            for entry in points:
                series.xs.append(float(entry[0]))
                series.ys.append(float(entry[1]))
        for series in self._series.values():
            if len(series.xs) > 1:
                pairs = sorted(zip(series.xs, series.ys))
                series.xs[:] = [p[0] for p in pairs]
                series.ys[:] = [p[1] for p in pairs]
        for ch_id, series in self._series.items():
            if ch_id not in self._curves:
                curve = self._plot.plot([], [], pen=series_pen(len(self._curves)), name=ch_id)
                self._curves[ch_id] = curve
            self._curves[ch_id].setData(x=series.xs, y=series.ys)
        self._apply_window(self._window_selector.get_window())

    # ------------------------------------------------------------------
    # No-op setters (smoke hotfix v0.55.16.0.1)
    #
    # AnalyticsView's `_forward()` dispatch logs WARNING when no active
    # widget in the current phase implements a setter. Because the PART D
    # measurement layout puts TemperatureOverviewWidget in the bottom-right
    # slot — not PressureCurrentWidget — the dispatcher would log
    # "no active widget in phase='measurement'" warnings on every
    # set_pressure_reading / set_keithley_readings / set_experiment_status
    # / set_cold_temperature_reading call. Those setters carry data this
    # widget legitimately doesn't render; the underlying readings still
    # persist via Scheduler→SQLiteWriter→DataBroker. The no-ops here
    # turn `forwarded = True` in the dispatcher and silence the warning
    # without masking truly-missing setters elsewhere.
    # ------------------------------------------------------------------

    def set_pressure_reading(self, reading) -> None:  # noqa: ARG002
        """Pressure reading is rendered by PressureCurrentWidget — no-op here."""

    def set_keithley_readings(self, readings) -> None:  # noqa: ARG002
        """Keithley readings are rendered by KeithleyPowerWidget — no-op here."""

    def set_experiment_status(self, status) -> None:  # noqa: ARG002
        """Experiment status is rendered elsewhere — no-op here."""

    def set_cold_temperature_reading(self, reading) -> None:  # noqa: ARG002
        """Cold-stage reading is rendered by VacuumPredictionWidget /
        CooldownPredictionWidget — no-op here."""


class TemperatureTrajectoryWidget(_WorkerCleanupMixin, QWidget):
    """Full-experiment temperature history — per-group Y-axis scaling (W1, warmup/main, F3-Cycle2).

    Initial data: ``readings_history`` ZMQ fetch (7-day window, cold channels) on construction.
    Live updates: :meth:`set_temperature_readings` — append-only per spec §4.1.
    Y-axis: one :class:`pg.PlotItem` per channel group (cryostat / compressor / detector)
    for independent auto-scaling (spec §4.1 criterion 3).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = get_channel_manager()
        self._series: dict[str, _ChannelSeries] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._group_plots: dict[str, pg.PlotItem] = {}
        self._next_row: int = 0
        self._history_worker = None
        self._build_ui()
        self._fetch_history()

    def _build_ui(self) -> None:
        card = _card("analyticsTemperatureTrajectory")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Траектория температуры"))
        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setBackground(theme.PLOT_BG)
        self._empty_label = _muted_label("Ожидание данных…")
        lay.addWidget(self._empty_label)
        lay.addWidget(self._graphics, stretch=1)
        self._graphics.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def _get_or_create_group_plot(self, group: str) -> pg.PlotItem:
        """Return the PlotItem for *group*, creating it if needed."""
        if group in self._group_plots:
            return self._group_plots[group]
        pi = self._graphics.addPlot(row=self._next_row, col=0)
        pi.showGrid(x=True, y=True, alpha=0.3)
        label = group if group else "Температура"
        pi.setLabel("left", label, units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        pi.setAxisItems({"bottom": date_axis})
        pi.addLegend(offset=(10, 10))
        # Link x-axis so all groups scroll / zoom together.
        if self._group_plots:
            pi.setXLink(next(iter(self._group_plots.values())))
        self._group_plots[group] = pi
        self._next_row += 1
        return pi

    def _fetch_history(self) -> None:
        """Issue a readings_history ZMQ command for all cold channels (spec §4.1)."""
        import time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        cold_ids = self._channel_mgr.get_cold_channels() or []
        channels = [self._channel_mgr.get_display_name(ch) for ch in cold_ids] or None
        cmd = {
            "cmd": "readings_history",
            "from_ts": time.time() - 7 * 24 * 3600,
            "to_ts": time.time(),
            "channels": channels,
            "limit_per_channel": 5000,
        }
        self._history_worker = ZmqCommandWorker(cmd, parent=self)
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        """Merge engine history response; sort each series by timestamp."""
        if not result.get("ok"):
            return
        data: dict[str, list] = result.get("data", {})
        for channel, points in data.items():
            if not points:
                continue
            series = self._series.setdefault(channel, _ChannelSeries())
            for entry in points:
                series.xs.append(float(entry[0]))
                series.ys.append(float(entry[1]))
        # Sort by timestamp: history may arrive after F4 live-stream replay,
        # producing out-of-order points if not sorted.
        for series in self._series.values():
            if len(series.xs) > 1:
                pairs = sorted(zip(series.xs, series.ys))
                series.xs[:] = [p[0] for p in pairs]
                series.ys[:] = [p[1] for p in pairs]
        self._refresh_all_curves()
        self._update_empty_state()

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        """Append live broker readings (spec §4.1 live stream)."""
        for ch_id, reading in readings.items():
            series = self._series.setdefault(ch_id, _ChannelSeries())
            series.xs.append(reading.timestamp.timestamp())
            series.ys.append(float(reading.value))
            max_pts = 5000
            if len(series.xs) > max_pts:
                del series.xs[: len(series.xs) - max_pts]
                del series.ys[: len(series.ys) - max_pts]
            self._update_curve(ch_id)
        self._update_empty_state()

    def _update_curve(self, ch_id: str) -> None:
        series = self._series.get(ch_id)
        if series is None:
            return
        group = self._channel_mgr.get_group(ch_id)
        pi = self._get_or_create_group_plot(group)
        if ch_id not in self._curves:
            pen = series_pen(len(self._curves))
            name = self._channel_mgr.get_name(ch_id) or ch_id
            curve = pi.plot([], [], pen=pen, name=name)
            self._curves[ch_id] = curve
        self._curves[ch_id].setData(x=series.xs, y=series.ys)

    def _refresh_all_curves(self) -> None:
        for ch_id in self._series:
            self._update_curve(ch_id)

    def _update_empty_state(self) -> None:
        has_data = any(s.xs for s in self._series.values())
        self._empty_label.setHidden(has_data)
        self._graphics.setHidden(not has_data)


class VacuumPredictionWidget(QWidget):
    """Log-Y prediction widget for vacuum pressure forecast (F-P2).

    Self-contained: accumulates raw pressure readings via
    :meth:`set_pressure_reading` and polls the engine every 10 s via
    ``get_vacuum_trend`` to obtain the extrapolated P(t) projection.
    Converts relative-time extrapolation arrays to absolute unix
    timestamps so the inner :class:`PredictionWidget` date axis works
    correctly.  Confidence band = ±1σ from ``residual_std`` (log₁₀
    units), converted to mbar.
    """

    _MAX_RAW_PTS: int = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз вакуума",
            y_label="Давление",
            y_unit="мбар",
            log_y=True,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)

        # Raw pressure history: (unix_ts, pressure_mbar)
        self._raw_buffer: list[tuple[float, float]] = []

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10_000)
        self._poll_timer.timeout.connect(self._poll_trend)
        self._poll_timer.start()
        QTimer.singleShot(500, self._poll_trend)

    def set_pressure_reading(self, reading: Reading) -> None:
        if reading is None:
            return
        ts = reading.timestamp.timestamp()
        self._raw_buffer.append((ts, float(reading.value)))
        if len(self._raw_buffer) > self._MAX_RAW_PTS:
            del self._raw_buffer[: len(self._raw_buffer) - self._MAX_RAW_PTS]
        self._inner.set_history(list(self._raw_buffer))

    def set_vacuum_prediction(self, data: dict | None) -> None:
        """Accept externally-pushed prediction dict (legacy path)."""
        if data is None:
            return
        history = data.get("history") or []
        central = data.get("central") or []
        lower = data.get("lower") or []
        upper = data.get("upper") or []
        ci_pct = float(data.get("ci_level_pct", 67.0))
        self._inner.set_history(list(history))
        if central and lower and upper:
            self._inner.set_prediction(list(central), list(lower), list(upper), ci_level_pct=ci_pct)

    @Slot()
    def _poll_trend(self) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
        worker.finished.connect(self._on_trend_result)
        worker.start()

    @Slot(dict)
    def _on_trend_result(self, result: dict) -> None:
        # D2 INSTRUMENTATION — remove before fix commit
        import logging as _dbg_log
        _dbglog = _dbg_log.getLogger("cryodaq.dbg.vacuum")
        _dbglog.warning(
            "[D2] _on_trend_result: ok=%s status=%s extrap_t_n=%d residual_std=%s",
            result.get("ok"),
            result.get("status"),
            len(result.get("extrapolation_t") or []),
            result.get("residual_std"),
        )
        if not result.get("ok") or result.get("status") == "no_data":
            # Clear any previously-rendered forecast so no stale overlay persists
            # after a bridge restart, disabled predictor, or empty buffer.
            self._inner.set_prediction([], [], [], ci_level_pct=68.0)
            return
        extrap_t = result.get("extrapolation_t") or []
        extrap_logP = result.get("extrapolation_logP") or []
        residual_std = float(result.get("residual_std") or 0.0)
        if not extrap_t or not extrap_logP or len(extrap_t) != len(extrap_logP):
            return

        # extrap_t is seconds from engine buffer t0; extrap_t[0] ≈ buffer duration.
        # Setting t0 = now - extrap_t[0] maps relative times to absolute unix
        # timestamps with the prediction starting at "now".
        now = time.time()
        t0 = now - extrap_t[0]

        central = [
            (t0 + t, 10.0**lp)
            for t, lp in zip(extrap_t, extrap_logP)
            if math.isfinite(lp)
        ]
        if not central:
            return

        if residual_std > 0:
            lower = [
                (t0 + t, 10.0 ** (lp - residual_std))
                for t, lp in zip(extrap_t, extrap_logP)
                if math.isfinite(lp)
            ]
            upper = [
                (t0 + t, 10.0 ** (lp + residual_std))
                for t, lp in zip(extrap_t, extrap_logP)
                if math.isfinite(lp)
            ]
        else:
            lower = central
            upper = central
        self._inner.set_prediction(central, lower, upper, ci_level_pct=68.0)


class CooldownPredictionWidget(QWidget):
    """Linear-Y prediction widget wrapped for cooldown forecast.

    F-MockPredictor: when CooldownDetector backend is IDLE (Mac mock on
    already-cooled data), feed cold-stage temperature readings into a
    SteadyStatePredictor and render a horizontal asymptote line + ±sigma
    band + "Стационарное состояние ≈ X K" badge in place of the empty
    placeholder. Mirrors the pattern in :class:`RThermalLiveWidget` and
    :class:`VacuumPredictionWidget`: the widget owns its own raw buffer
    + setter, since CooldownData.actual_trajectory is intentionally empty
    in the production adapter (a snapshot of CooldownService output).
    """

    # Predictor convergence threshold: show overlay when ≥30% settled
    # (matches RThermalLiveWidget).
    _SETTLE_THRESHOLD: float = 30.0
    # Internal predictor key — channel-id-agnostic, only the widget feeds it.
    _PRED_CHANNEL = "cold_stage"
    # 2026-05-08 (v0.56.3 amend): bump 5000 → 50000. At replay 600× the
    # raw_cold_buffer fills 5000 within ~3.7 s wall-clock and trim-from-
    # left visibly erases the LEFT side of the prediction history plot
    # in 2-3 step jumps (operator complaint). 50 000 covers ≈14 h live
    # at 1 Hz or the demo MTO 18.85 h replay (≈6700 samples per channel)
    # with margin. VacuumPredictionWidget left at 5000 — its replay
    # cadence has not surfaced the same UX issue.
    _MAX_RAW_PTS: int = 50000
    # Canonical cold-stage landmark id from config/physical_alarms.yaml.
    # MainWindowV2 routes only readings whose channel resolves to this id;
    # configuration-decoupling is left to a future spec per architect.
    _COLD_LANDMARK: str = "Т12"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз охлаждения",
            y_label="Температура",
            y_unit="K",
            log_y=False,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)

        # Idle placeholder as pg.TextItem on the plot canvas — plot uses
        # full vertical space rather than being clipped by a label above it.
        self._placeholder = pg.TextItem(
            "Охлаждение не активно — прогноз недоступен",
            anchor=(0.5, 0.5),
            color=QColor(theme.MUTED_FOREGROUND),
        )
        _ph_font = QFont(theme.FONT_BODY)
        _ph_font.setPixelSize(theme.FONT_SIZE_BASE)
        self._placeholder.setFont(_ph_font)

        # F-MockPredictor: steady-state badge (replaces placeholder when stationary).
        self._steady_badge = pg.TextItem(
            "",
            anchor=(0.5, 0.5),
            color=QColor(theme.STATUS_INFO),
        )
        _badge_font = QFont(theme.FONT_BODY)
        _badge_font.setPixelSize(theme.FONT_SIZE_BASE)
        _badge_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        self._steady_badge.setFont(_badge_font)
        self._steady_badge.setVisible(False)

        # F-MockPredictor: asymptote ±sigma band (rendered behind line).
        band_color = QColor(theme.STATUS_INFO)
        band_color.setAlpha(64)
        self._asym_band = pg.LinearRegionItem(
            values=[0.0, 0.0],
            orientation="horizontal",
            brush=pg.mkBrush(band_color),
            movable=False,
        )
        self._asym_band.setVisible(False)
        self._inner._plot.addItem(self._asym_band)

        # F-MockPredictor: asymptote dashed line.
        self._asym_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen(
                color=QColor(theme.STATUS_INFO),
                width=theme.PLOT_LINE_WIDTH,
                style=Qt.DashLine,
            ),
            label="T∞",
            labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
        )
        self._asym_line.setVisible(False)
        self._inner._plot.addItem(self._asym_line)

        _vb = self._inner._plot.getPlotItem().getViewBox()
        _vb.addItem(self._placeholder, ignoreBounds=True)
        _vb.addItem(self._steady_badge, ignoreBounds=True)
        _vb.sigRangeChanged.connect(self._reposition_overlays)

        # F-MockPredictor: SteadyStatePredictor (params verbatim from RThermalLiveWidget).
        self._ss_predictor = SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
        self._last_ts_seen: float = 0.0
        # Raw cold-stage readings — fed by set_cold_temperature_reading()
        # because CooldownData.actual_trajectory is empty in production
        # (intentional contract — see _cooldown_reading_to_data adapter).
        self._raw_cold_buffer: list[tuple[float, float]] = []

        self._reposition_overlays()
        self._placeholder.setVisible(True)

    def set_cold_temperature_reading(self, reading) -> None:
        """Receive one cold-stage temperature reading (Т12 by default).

        Mirrors :meth:`VacuumPredictionWidget.set_pressure_reading`: the
        widget owns its raw buffer, feeds the SteadyStatePredictor with new
        timestamps only, and pushes history into the inner plot so the
        operator sees the actual data line under the eventual asymptote.
        """
        if reading is None:
            return
        # NaN-доктрина (A3): status — дискриминатор годности, не float-конечность.
        # Не годное показание (ошибка статуса / NaN / ±inf) не питает предиктор.
        if not reading.is_usable():
            return
        ts = reading.timestamp.timestamp()
        val = float(reading.value)
        self._raw_cold_buffer.append((ts, val))
        if len(self._raw_cold_buffer) > self._MAX_RAW_PTS:
            # 2026-05-08 (v0.56.3 amend): decimate stride-2 instead of
            # truncate-from-left. The first sample is preserved so
            # _apply_x_range's `self._history[0][0]` X-anchor stays
            # stable, eliminating the visible left-edge jump that
            # appeared each time the cap was hit. Trades time
            # resolution for retention.
            self._raw_cold_buffer = self._raw_cold_buffer[:1] + self._raw_cold_buffer[1::2]
        if ts > self._last_ts_seen:
            self._ss_predictor.add_point(self._PRED_CHANNEL, ts, val)
            self._last_ts_seen = ts
        self._ss_predictor.update(time.time())
        self._inner.set_history(list(self._raw_cold_buffer))

    def _reposition_overlays(self) -> None:
        vb = self._inner._plot.getPlotItem().getViewBox()
        xr, yr = vb.viewRange()
        cx = (xr[0] + xr[1]) / 2
        cy = (yr[0] + yr[1]) / 2
        self._placeholder.setPos(cx, cy)
        self._steady_badge.setPos(cx, cy)

    def set_cooldown_data(self, data) -> None:
        if data is None:
            # Clear any stale forecast curves left from a prior active push
            # (mirrors VacuumPredictionWidget._on_trend_result no-data path).
            self._inner.set_prediction([], [], [], ci_level_pct=67.0)
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)
            self._steady_badge.setVisible(False)
            self._placeholder.setVisible(True)
            return
        # CooldownData from analytics_view has predicted_trajectory and
        # ci_trajectory (t, lo, hi triples). actual_trajectory is empty by
        # contract — cold-stage readings flow in via set_cold_temperature_reading.
        predicted = getattr(data, "predicted_trajectory", []) or []
        ci = getattr(data, "ci_trajectory", []) or []

        if predicted and ci:
            lower = [(t, lo) for (t, lo, _hi) in ci]
            upper = [(t, hi) for (t, _lo, hi) in ci]
            self._inner.set_prediction(
                [(t, v) for (t, v) in predicted],
                lower,
                upper,
                ci_level_pct=67.0,
            )
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)
            self._steady_badge.setVisible(False)
            self._placeholder.setVisible(False)
            return

        # No active prediction — clear any prior forecast curves so the
        # asymptote / placeholder doesn't sit on top of stale data.
        self._inner.set_prediction([], [], [], ci_level_pct=67.0)

        # Then check for steady-state asymptote.
        pred = self._ss_predictor.get_prediction(self._PRED_CHANNEL)
        if pred is not None and pred.valid and getattr(pred, "is_quasi_steady", False):
            # v0.55.3 — quasi-steady regime. Curve fit was bypassed because
            # the system is sitting near steady; report mean ± stddev plus
            # the slow drift rate. No asymptote line / band: t_current is
            # the readout, not an extrapolated asymptote.
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)
            self._steady_badge.setPlainText(
                f"Стационар: T = {pred.t_current:.2f} ± {pred.stddev_k:.2f} K, "
                f"дрейф {pred.drift_rate_k_per_h:+.2f} К/ч"
            )
            self._steady_badge.setVisible(True)
            self._placeholder.setVisible(False)
            self._reposition_overlays()
        elif (
            pred is not None
            and pred.valid
            and pred.percent_settled >= self._SETTLE_THRESHOLD
        ):
            t_inf = pred.t_predicted
            sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
            self._asym_line.setPos(t_inf)
            self._asym_band.setRegion([t_inf - sigma, t_inf + sigma])
            self._asym_line.setVisible(True)
            self._asym_band.setVisible(True)
            self._steady_badge.setPlainText(f"Стационарное состояние ≈ {t_inf:.2f} K")
            self._steady_badge.setVisible(True)
            self._placeholder.setVisible(False)
            self._reposition_overlays()
        else:
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)
            self._steady_badge.setVisible(False)
            self._placeholder.setVisible(True)


class RThermalLiveWidget(QWidget):
    """Live R_thermal readout + delta/min + compact history plot (F-P3).

    Adds a horizontal asymptote overlay via :class:`SteadyStatePredictor`
    applied to the R_thermal history.  The overlay (dashed line + ±σ band)
    appears once the predictor has settled ≥30% and reports a valid fit.

    Visual tokens follow the canonical PredictionWidget convention:
    - Asymptote line: STATUS_INFO, PLOT_LINE_WIDTH, Qt.DashLine
    - Confidence band: STATUS_INFO at alpha=64 (~25% opacity)
    """

    # Predictor convergence threshold: show overlay when ≥30% settled.
    _SETTLE_THRESHOLD: float = 30.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ss_predictor = SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
        self._last_r_ts: float = 0.0
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsRThermalLive")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("R тепл."))
        self._value_label = _mono_value_label("—")
        lay.addWidget(self._value_label)
        self._delta_label = QLabel("ΔR / мин: —")
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        lay.addWidget(self._delta_label)
        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "R", units="К/Вт", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})

        # F-P3: CI band added first so it renders behind the data curve.
        # Color: STATUS_INFO at alpha=64 — matches PredictionWidget convention.
        band_color = QColor(theme.STATUS_INFO)
        band_color.setAlpha(64)
        self._asym_band = pg.LinearRegionItem(
            values=[0.0, 0.0],
            orientation="horizontal",
            brush=pg.mkBrush(band_color),
            movable=False,
        )
        self._asym_band.setVisible(False)
        self._plot.addItem(self._asym_band)

        # Data curve renders above the band.
        self._curve = self._plot.plot([], [], pen=series_pen(0))

        # F-P3: Asymptote dashed line added last — renders above data curve.
        # Pen: STATUS_INFO, PLOT_LINE_WIDTH, DashLine — matches PredictionWidget.
        self._asym_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen(
                color=QColor(theme.STATUS_INFO),
                width=theme.PLOT_LINE_WIDTH,
                style=Qt.DashLine,
            ),
            label="R∞",
            labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
        )
        self._asym_line.setVisible(False)
        self._plot.addItem(self._asym_line)

        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_r_thermal_data(self, data) -> None:
        if data is None:
            self._value_label.setText("—")
            self._delta_label.setText("ΔR / мин: —")
            self._curve.setData([], [])
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)
            return
        current = getattr(data, "current_value", None)
        delta = getattr(data, "delta_per_minute", None)
        history = getattr(data, "history", []) or []
        if current is None:
            self._value_label.setText("—")
        else:
            self._value_label.setText(f"{current:.3f} К/Вт")
        if delta is None:
            self._delta_label.setText("ΔR / мин: —")
        else:
            self._delta_label.setText(f"ΔR / мин: {delta:+.3f}")
        if history:
            xs = [t for t, _ in history]
            ys = [v for _, v in history]
            self._curve.setData(x=xs, y=ys)

            # Feed only new history points into the predictor.
            # NaN-доктрина (A3): buffer replay — только (ts, float), без Reading
            # со статусом; годность уже отфильтрована выше по потоку. Гейтить
            # нечем, оставляем float-питание как есть.
            for ts, val in history:
                if ts > self._last_r_ts:
                    self._ss_predictor.add_point("R_thermal", ts, val)
                    self._last_r_ts = ts

            self._ss_predictor.update(time.time())
            pred = self._ss_predictor.get_prediction("R_thermal")
            if pred is not None and pred.valid and pred.percent_settled >= self._SETTLE_THRESHOLD:
                r_inf = pred.t_predicted
                sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
                self._asym_line.setPos(r_inf)
                self._asym_band.setRegion([r_inf - sigma, r_inf + sigma])
                self._asym_line.setVisible(True)
                self._asym_band.setVisible(True)
            else:
                self._asym_line.setVisible(False)
                self._asym_band.setVisible(False)
        else:
            # Empty history on non-None push — hide stale overlay if present.
            self._asym_line.setVisible(False)
            self._asym_band.setVisible(False)


class PressureCurrentWidget(QWidget):
    """Wraps the shared :class:`PressurePlot` for the analytics view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_selector = TimeWindowSelector()
        self._last_history_fetch_ts: float = 0.0
        card = _card("analyticsPressureCurrent")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(theme.SPACE_2)
        header.addWidget(_title_label("Давление"))
        header.addStretch()
        header.addWidget(self._window_selector)
        lay.addLayout(header)
        self._plot = PressurePlot()
        # Override PressurePlot's global controller subscription with local selector.
        # The get_time_window_controller() call here is the ONLY remaining use
        # of the global controller in this widget — it exists solely to sever
        # PressurePlot's default subscription, not to apply any window value.
        try:
            get_time_window_controller().window_changed.disconnect(self._plot._apply_window)
        except (TypeError, RuntimeError):
            pass
        self._window_selector.window_changed.connect(self._plot._apply_window)
        self._plot._apply_window(self._window_selector.get_window())
        self._window_selector.window_changed.connect(
            lambda w: self._maybe_refetch_history(w)
        )
        lay.addWidget(self._plot, stretch=1)
        self._series: list[tuple[float, float]] = []
        self._history_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)
        self._fetch_history()

    def set_pressure_reading(self, reading: Reading) -> None:
        if reading is None:
            return
        ts = reading.timestamp.timestamp()
        self._series.append((ts, float(reading.value)))
        if len(self._series) > 5000:
            del self._series[: len(self._series) - 5000]
        xs = [t for t, _ in self._series]
        ys = [v for _, v in self._series]
        self._plot.set_series(xs, ys)
        # PressurePlot.set_series() re-applies the global controller window as
        # part of its v0.52.5 X-scroll fix. Re-apply local selector window
        # immediately after so the operator's choice is not overridden.
        self._plot._apply_window(self._window_selector.get_window())

    def _fetch_history(self) -> None:
        import time as _time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._last_history_fetch_ts = _time.time()
        window = self._window_selector.get_window()
        import math as _math
        span = window.seconds if _math.isfinite(window.seconds) else 24 * 3600.0
        cmd = {
            "cmd": "readings_history",
            "from_ts": _time.time() - span,
            "to_ts": _time.time(),
            "unit": "мбар",
            "limit_per_channel": 5000,
        }
        self._history_worker = ZmqCommandWorker(cmd, parent=self)
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    def _maybe_refetch_history(self, window: TimeWindow) -> None:
        import math
        import time
        if time.time() - self._last_history_fetch_ts < 1.0:
            return
        requested_secs = window.seconds if math.isfinite(window.seconds) else 24 * 3600.0
        if self._series:
            span = self._series[-1][0] - self._series[0][0]
            if span >= requested_secs * 0.9:
                return
        self._fetch_history()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        if not result.get("ok"):
            return
        data: dict[str, list] = result.get("data", {})
        for channel, points in data.items():
            if not points:
                continue
            for entry in points:
                self._series.append((float(entry[0]), float(entry[1])))
        if self._series:
            self._series.sort(key=lambda p: p[0])
            if len(self._series) > 5000:
                self._series = self._series[-5000:]
            xs = [t for t, _ in self._series]
            ys = [v for _, v in self._series]
            self._plot.set_series(xs, ys)
            self._plot._apply_window(self._window_selector.get_window())


class SensorHealthSummaryWidget(QWidget):
    """Compact grid of per-sensor status chips."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chips: dict[str, SeverityChip] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsSensorHealth")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Диагностика датчиков"))
        self._empty_label = _muted_label(
            "Датчики без аномалий — свежих диагностических данных нет."
        )
        lay.addWidget(self._empty_label)
        self._grid = QGridLayout()
        self._grid.setSpacing(theme.SPACE_1)
        lay.addLayout(self._grid)
        lay.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_instrument_health(self, health: dict[str, str] | None) -> None:
        # Clear prior chips.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._chips.clear()
        if not health:
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)
        row = 0
        for name, severity in sorted(health.items()):
            name_label = QLabel(name)
            name_label.setStyleSheet(
                f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            )
            chip = SeverityChip(severity.upper())
            self._grid.addWidget(name_label, row, 0)
            self._grid.addWidget(chip, row, 1)
            self._chips[name] = chip
            row += 1


class KeithleyPowerWidget(QWidget):
    """Compact Keithley readout — Channel A + B voltage / current / power."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: dict[str, QLabel] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsKeithleyPower")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Мощность Keithley"))
        grid = QGridLayout()
        grid.setSpacing(theme.SPACE_1)
        for col, channel in enumerate(("A", "B")):
            header = QLabel(f"Канал {channel}")
            header.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
            )
            grid.addWidget(header, 0, col)
            for row, key in enumerate(("voltage", "current", "power"), start=1):
                value = _mono_value_label("—")
                self._values[f"{channel}.{key}"] = value
                grid.addWidget(value, row, col)
        lay.addLayout(grid)
        lay.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_keithley_readings(self, readings: dict[str, Reading]) -> None:
        """Map readings with keys like ``smua/voltage`` → 2-letter
        channel ID + measurement."""
        for key, reading in readings.items():
            parts = key.split("/")
            if len(parts) < 2:
                continue
            channel_raw, measurement = parts[-2], parts[-1]
            channel = "A" if channel_raw == "smua" else "B" if channel_raw == "smub" else None
            if channel is None:
                continue
            label = self._values.get(f"{channel}.{measurement}")
            if label is None:
                continue
            unit = {"voltage": "В", "current": "А", "power": "Вт"}[measurement]
            label.setText(f"{float(reading.value):.3g} {unit}")


class CooldownHistoryWidget(_WorkerCleanupMixin, QWidget):
    """Past cooldown durations for comparison (W2, warmup/bottom_right, F3-Cycle3).

    One-shot ``cooldown_history_get`` ZMQ fetch on construction.
    No live stream — this is historical data only (spec §4.2).
    Scatter: X = cooldown start date, Y = duration in hours.
    Empty state: "Нет завершённых охлаждений".
    Error state: error banner (engine failure gracefully handled).
    """

    def __init__(self, parent: QWidget | None = None, *, limit: int = 20) -> None:
        super().__init__(parent)
        self._limit = limit
        self._cooldowns: list[dict] = []
        self._history_worker = None
        self._build_ui()
        self._fetch_history()

    def _build_ui(self) -> None:
        card = _card("analyticsCooldownHistory")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("История захолаживаний"))

        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Длительность", units="ч", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        self._scatter = pg.ScatterPlotItem(size=9, pen=series_pen(0))
        self._plot.addItem(self._scatter)

        self._empty_label = _muted_label("Нет завершённых охлаждений")
        self._error_label = _muted_label("Ошибка загрузки данных")
        self._error_label.setHidden(True)
        lay.addWidget(self._empty_label)
        lay.addWidget(self._error_label)
        lay.addWidget(self._plot, stretch=1)
        self._plot.setHidden(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def _fetch_history(self) -> None:
        """Issue a cooldown_history_get ZMQ command (spec §5)."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        cmd = {"cmd": "cooldown_history_get", "limit": self._limit}
        self._history_worker = ZmqCommandWorker(cmd, parent=self)
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        """Render fetched cooldown records as a scatter plot."""
        if not result.get("ok"):
            self._empty_label.setHidden(True)
            self._error_label.setHidden(False)
            return
        cooldowns = result.get("cooldowns", [])
        self._cooldowns = list(cooldowns)
        if not cooldowns:
            return
        xs: list[float] = []
        ys: list[float] = []
        for entry in cooldowns:
            started_at = entry.get("cooldown_started_at") or entry.get("started_at")
            duration = entry.get("duration_hours")
            if not started_at or duration is None:
                continue
            try:
                from datetime import datetime as _dt

                ts = _dt.fromisoformat(started_at).timestamp()
                xs.append(ts)
                ys.append(float(duration))
            except Exception:
                continue
        if xs:
            self._scatter.setData(x=xs, y=ys)
            self._empty_label.setHidden(True)
            self._plot.setHidden(False)


class _ClickableLabel(QLabel):
    """QLabel that opens a file path with QDesktopServices on click (F19 sub-item 3)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path: str = ""
        self.setCursor(Qt.PointingHandCursor)

    def set_path(self, path: str) -> None:
        self._path = path
        if path:
            self.setText(path)
            self.setStyleSheet(
                f"color: {theme.ACCENT}; text-decoration: underline; "
                "background: transparent; border: none;"
            )
        else:
            self.setText("—")
            self.setStyleSheet("color: inherit; text-decoration: none;")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        super().mousePressEvent(event)


class ExperimentSummaryWidget(_WorkerCleanupMixin, QWidget):
    """Post-experiment summary card (W3, disassembly/main, F3-Cycle4).

    Receives experiment status via set_experiment_status().
    On data arrival: populates header/duration/artifacts from status dict,
    then issues alarm_v2_history ZMQ fetch for alarm count.
    Empty state rendered when status is None or experiment is not yet
    finalized.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._alarm_worker = None
        self._stats_worker = None  # F19 sub-item 1
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsExperimentSummary")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Сводка эксперимента"))

        self._empty_label = _muted_label("Эксперимент не завершён")
        lay.addWidget(self._empty_label)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        c_lay = QVBoxLayout(self._content)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(theme.SPACE_1)

        self._id_label = self._add_info_row(c_lay, "Эксперимент")
        self._sample_label = self._add_info_row(c_lay, "Образец")
        self._operator_label = self._add_info_row(c_lay, "Оператор")
        self._date_label = self._add_info_row(c_lay, "Начало")
        self._duration_label = self._add_info_row(c_lay, "Продолжительность")
        self._phases_label = self._add_info_row(c_lay, "Фазы")
        self._phases_label.setWordWrap(True)
        self._alarm_label = self._add_info_row(c_lay, "Тревоги")
        # F19 sub-item 2: top-3 alarm names
        self._top_alarms_label = self._add_info_row(c_lay, "Топ тревог")
        self._top_alarms_label.setWordWrap(True)
        # F19 sub-item 1: channel min/max/mean stats
        self._stats_label = self._add_info_row(c_lay, "Каналы")
        self._stats_label.setWordWrap(True)
        # F19 sub-item 3: clickable artifact links
        self._docx_label = self._add_link_row(c_lay, "Отчёт DOCX")
        self._pdf_label = self._add_link_row(c_lay, "Отчёт PDF")

        c_lay.addStretch()
        self._content.setHidden(True)
        lay.addWidget(self._content, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)


    def _add_link_row(self, layout: QVBoxLayout, label_text: str) -> _ClickableLabel:
        """Create a label row where the value is a clickable file link (F19 sub-item 3)."""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.SPACE_2)

        key = QLabel(f"{label_text}:")
        key_font = QFont(theme.FONT_BODY)
        key_font.setPixelSize(theme.FONT_BODY_SIZE)
        key.setFont(key_font)
        key.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        key.setFixedWidth(140)

        val = _ClickableLabel()
        val_font = QFont(theme.FONT_BODY)
        val_font.setPixelSize(theme.FONT_BODY_SIZE)
        val.setFont(val_font)
        val.setWordWrap(True)
        val.set_path("")

        h.addWidget(key)
        h.addWidget(val, stretch=1)
        layout.addWidget(row)
        return val

    def _add_info_row(self, layout: QVBoxLayout, label_text: str) -> QLabel:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.SPACE_2)

        key = QLabel(f"{label_text}:")
        key_font = QFont(theme.FONT_BODY)
        key_font.setPixelSize(theme.FONT_BODY_SIZE)
        key.setFont(key_font)
        key.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        key.setFixedWidth(140)

        val = QLabel("—")
        val_font = QFont(theme.FONT_BODY)
        val_font.setPixelSize(theme.FONT_BODY_SIZE)
        val.setFont(val_font)
        val.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")

        h.addWidget(key)
        h.addWidget(val, stretch=1)
        layout.addWidget(row)
        return val

    def set_experiment_status(self, status: dict | None) -> None:
        if status is None:
            self._show_empty()
            return
        active = status.get("active_experiment")
        if not isinstance(active, dict):
            self._show_empty()
            return
        self._populate(active, status.get("phases", []))

    def _show_empty(self) -> None:
        self._empty_label.setHidden(False)
        self._content.setHidden(True)
        self._top_alarms_label.setText("—")
        self._stats_label.setText("—")
        self._docx_label.set_path("")
        self._pdf_label.set_path("")

    def _populate(self, active: dict, phases: list) -> None:
        from datetime import UTC
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        self._id_label.setText(active.get("experiment_id") or "—")
        self._sample_label.setText(active.get("sample") or "—")
        self._operator_label.setText(active.get("operator") or "—")

        start_ts: float | None = None
        start_str = active.get("start_time") or ""
        end_str = active.get("end_time") or ""
        try:
            start_dt = _dt.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)
            self._date_label.setText(start_dt.strftime("%Y-%m-%d %H:%M UTC"))
            start_ts = start_dt.timestamp()
            if end_str:
                end_dt = _dt.fromisoformat(end_str)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                total_h = (end_dt - start_dt).total_seconds() / 3600
                self._duration_label.setText(f"{total_h:.1f} ч")
            else:
                self._duration_label.setText("в процессе")
        except (ValueError, TypeError):
            self._date_label.setText("—")
            self._duration_label.setText("—")

        phase_parts: list[str] = []
        for p in phases:
            name = str(p.get("phase") or "—")
            ps = p.get("started_at") or ""
            pe = p.get("ended_at") or ""
            try:
                dt_s = _dt.fromisoformat(ps)
                dt_e = _dt.fromisoformat(pe)
                ph_h = (dt_e - dt_s).total_seconds() / 3600
                phase_parts.append(f"{name}: {ph_h:.1f} ч")
            except (ValueError, TypeError):
                phase_parts.append(f"{name}: —")
        self._phases_label.setText(", ".join(phase_parts) if phase_parts else "—")

        artifact_dir = active.get("artifact_dir") or ""
        end_ts: float | None = None
        if artifact_dir:
            base = _Path(artifact_dir)
            self._docx_label.set_path(str(base / "reports" / "report_editable.docx"))
            self._pdf_label.set_path(str(base / "reports" / "report_raw.pdf"))
        else:
            self._docx_label.set_path("")
            self._pdf_label.set_path("")

        try:
            if end_str:
                end_dt = _dt.fromisoformat(end_str)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                end_ts = end_dt.timestamp()
        except (ValueError, TypeError):
            pass

        if start_ts is not None:
            self._fetch_alarms(start_ts)
            # F19 sub-item 1: fetch channel stats for experiment timespan
            self._stats_label.setText("Загрузка…")
            self._fetch_stats(start_ts, end_ts)
        else:
            self._alarm_label.setText("—")
            self._top_alarms_label.setText("—")
            self._stats_label.setText("—")

        self._empty_label.setHidden(True)
        self._content.setHidden(False)

    def _fetch_stats(self, start_ts: float, end_ts: float | None) -> None:
        """Issue readings_history ZMQ fetch for experiment timespan; compute channel stats (F19)."""
        import time as _time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        to_ts = end_ts if end_ts is not None else _time.time()
        cmd = {
            "cmd": "readings_history",
            "from_ts": start_ts,
            "to_ts": to_ts,
            # 50k samples covers ~7h at 0.5s polling cadence (P2: 5k was 42 min)
            "limit_per_channel": 50000,
        }
        self._stats_worker = ZmqCommandWorker(cmd, parent=self)
        self._stats_worker.finished.connect(self._on_stats_loaded)
        self._stats_worker.start()

    @Slot(dict)
    def _on_stats_loaded(self, result: dict) -> None:
        """Compute per-channel min/max/mean from readings_history response."""
        if not result.get("ok"):
            self._stats_label.setText("—")
            return
        data: dict[str, list] = result.get("data", {})
        if not data:
            self._stats_label.setText("нет данных")
            return

        lines: list[str] = []
        # Show temperature channels (K) first, then others
        temp_chs = sorted(
            ch for ch in data
            if ch.startswith("Т") or ch.startswith("T")
        )
        other_chs = sorted(ch for ch in data if ch not in temp_chs)
        ordered = (temp_chs + other_chs)[:12]  # limit display

        for ch in ordered:
            pts = data[ch]
            if not pts:
                continue
            vals = [float(p[1]) for p in pts if len(p) >= 2]
            if not vals:
                continue
            mn = min(vals)
            mx = max(vals)
            mean = sum(vals) / len(vals)
            lines.append(f"{ch}: {mn:.2f}–{mx:.2f} (ср {mean:.2f})")

        self._stats_label.setText("\n".join(lines) if lines else "нет данных")

    def _fetch_alarms(self, start_ts: float) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        cmd = {"cmd": "alarm_v2_history", "start_ts": start_ts, "limit": 500}
        self._alarm_worker = ZmqCommandWorker(cmd, parent=self)
        self._alarm_worker.finished.connect(self._on_alarms_loaded)
        self._alarm_worker.start()

    @Slot(dict)
    def _on_alarms_loaded(self, result: dict) -> None:
        if not result.get("ok"):
            self._alarm_label.setText("—")
            self._top_alarms_label.setText("—")
            return
        history = result.get("history", [])
        triggered = [e for e in history if e.get("transition") == "TRIGGERED"]
        warnings = sum(1 for e in triggered if str(e.get("level", "")).upper() == "WARNING")
        criticals = sum(1 for e in triggered if str(e.get("level", "")).upper() == "CRITICAL")
        total = len(triggered)
        self._alarm_label.setText(f"{total} ({warnings} пред. / {criticals} крит.)")

        # F19 sub-item 2: top-3 most-triggered alarm names
        counts: dict[str, int] = {}
        for e in triggered:
            aid = str(e.get("alarm_id") or "")
            if aid:
                counts[aid] = counts.get(aid, 0) + 1
        if counts:
            top3 = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
            parts = [f"{name} ×{n}" for name, n in top3]
            self._top_alarms_label.setText("; ".join(parts))
        else:
            self._top_alarms_label.setText("нет")


# ---------------------------------------------------------------------------
# Placeholder widget factories
# ---------------------------------------------------------------------------


def _r_thermal_placeholder() -> QWidget:
    # Unblock criterion: F8 (cooldown ML upgrade or new R_thermal engine service).
    return PlaceholderCard(
        "R тепловое сопротивление",
        subtitle="данные источника ожидают (зависит от F8)",
    )


def _temperature_trajectory_placeholder() -> QWidget:
    return PlaceholderCard("Траектория температуры")


def _cooldown_history_placeholder() -> QWidget:
    return PlaceholderCard("История захолаживаний")


def _experiment_summary_placeholder() -> QWidget:
    return PlaceholderCard("Сводка эксперимента")


# ---------------------------------------------------------------------------
# v0.55.6.1 — TemperatureSteadyStateWidget
# ---------------------------------------------------------------------------


class TemperatureSteadyStateWidget(QWidget):
    """Asymptotic temperature prediction for the measurement phase.

    Replaces R_thermal as the headline analytics widget during
    `measurement` (architect 2026-05-07: «в фазе измерения до сих пор
    R, а не прогноз по температуре (пусть и асимптотический)»).

    Two SteadyStatePredictor instances — one per landmark stage
    (Т11 cooler / Т12 nitrogen plate) — share the chart. Each draws:
    - a live trace (`series_pen` palette index 0/1)
    - a horizontal asymptote dashed line (STATUS_INFO, DashLine)
    - a ±σ band (STATUS_INFO at alpha=64) when ≥30% settled

    The hero readout above the plot shows ``Т12 → X.XX K (σ Y.YY)``
    while settled, falls back to ``Стабилизация…`` until the
    predictor reports a valid fit. Tracking is per-channel so one
    stage can settle before the other without blanking the row.
    """

    _SETTLE_THRESHOLD: float = 30.0
    # Predictor channel keys mirror the canonical landmark short ids
    # (config/physical_alarms.yaml). Operator-facing labels stay in
    # Russian; the keys are internal to SteadyStatePredictor.
    _LANDMARKS: tuple[tuple[str, str, str], ...] = (
        # (short_id, predictor_key, display_label)
        ("Т12", "T12", "Т12"),
        ("Т11", "T11", "Т11"),
    )
    # 2026-05-08 (v0.56.3 amend): bump 5000 → 50000. At replay 600× the
    # raw_buffer fills 5000 within ~3.7 s wall-clock and trim-from-left
    # erases the visible left edge of the plot in 2-3 step jumps. 50 000
    # covers 14 h live (1 Hz) or ≈1.4 h replay-time at 600× — plenty for
    # the demo MTO 18.85 h replay (≈6700 samples per channel).
    _MAX_RAW_PTS: int = 50000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._predictors: dict[str, SteadyStatePredictor] = {
            key: SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
            for _, key, _ in self._LANDMARKS
        }
        self._buffers: dict[str, list[tuple[float, float]]] = {
            key: [] for _, key, _ in self._LANDMARKS
        }
        self._last_ts: dict[str, float] = {key: 0.0 for _, key, _ in self._LANDMARKS}
        # 2026-05-08 (v0.56.3 amend): widget-side Y-range cache for the
        # cache-driven deadband helper.
        self._y_cache_lo: float | None = None
        self._y_cache_hi: float | None = None
        self._y_last_set_ts: float = 0.0
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsTempSteadyState")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Прогноз асимптоты T11/T12"))

        # Hero readouts — one row per landmark, monospaced.
        self._hero_labels: dict[str, QLabel] = {}
        hero_box = QVBoxLayout()
        hero_box.setSpacing(theme.SPACE_1)
        for _short, key, label in self._LANDMARKS:
            row = QLabel(f"{label}: стабилизация…")
            row.setStyleSheet(
                f"color: {theme.FOREGROUND}; "
                f"font-family: '{theme.FONT_MONO}'; "
                f"font-feature-settings: 'tnum'; "
                f"background: transparent; border: none;"
            )
            hero_box.addWidget(row)
            self._hero_labels[key] = row
        lay.addLayout(hero_box)

        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "T", units="K", color=theme.PLOT_LABEL_COLOR)
        # 2026-05-08 (v0.56.3): manual Y deadband applied in _refresh().
        # pyqtgraph's float enable= autoRange still rescales every
        # setData — disable native autoRange so the deadband helper
        # owns Y end-to-end (mirror of TemperatureOverviewWidget).
        pi.disableAutoRange(axis="y")
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})

        self._curves: dict[str, pg.PlotDataItem] = {}
        self._asym_lines: dict[str, pg.InfiniteLine] = {}
        self._asym_bands: dict[str, pg.LinearRegionItem] = {}
        for idx, (_short, key, label) in enumerate(self._LANDMARKS):
            band_color = QColor(theme.STATUS_INFO)
            band_color.setAlpha(64)
            band = pg.LinearRegionItem(
                values=[0.0, 0.0],
                orientation="horizontal",
                brush=pg.mkBrush(band_color),
                movable=False,
            )
            band.setVisible(False)
            self._plot.addItem(band)
            self._asym_bands[key] = band

            curve = self._plot.plot([], [], pen=series_pen(idx), name=label)
            self._curves[key] = curve

            asym = pg.InfiniteLine(
                angle=0,
                pen=pg.mkPen(
                    color=QColor(theme.STATUS_INFO),
                    width=theme.PLOT_LINE_WIDTH,
                    style=Qt.DashLine,
                ),
                label=f"{label}∞",
                labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
            )
            asym.setVisible(False)
            self._plot.addItem(asym)
            self._asym_lines[key] = asym

        self._plot.addLegend(offset=(10, 10))
        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    # ------------------------------------------------------------------
    # Setters used by AnalyticsView duck-typed forwarding
    # ------------------------------------------------------------------

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        """Absorb live K-unit readings; filter to landmark short ids.

        AnalyticsView pushes every K-unit reading; this widget cares
        only about Т11/Т12 (split short-id check matches the same
        heuristic MainWindowV2 uses to feed CooldownPredictionWidget).
        """
        if not readings:
            return
        for ch_id, reading in readings.items():
            short_id = ch_id.split(" ", 1)[0] if " " in ch_id else ch_id
            key = self._key_for_short_id(short_id)
            if key is None:
                continue
            # NaN-доктрина (A3): не годное показание не питает предиктор.
            if not reading.is_usable():
                continue
            try:
                value = float(reading.value)
            except (TypeError, ValueError):
                continue
            ts = reading.timestamp.timestamp()
            buf = self._buffers[key]
            buf.append((ts, value))
            if len(buf) > self._MAX_RAW_PTS:
                # 2026-05-08 (v0.56.3 amend): decimate stride-2 instead of
                # truncate-from-left. Truncation made the plot's left edge
                # jump forward visibly each time the cap was hit; stride-2
                # downsamples the older history while keeping the first
                # sample so the X-range anchor (set by _apply_x_range) is
                # preserved. Trades time resolution for retention.
                buf[:] = buf[:1] + buf[1::2]
            if ts > self._last_ts[key]:
                self._predictors[key].add_point(key, ts, value)
                self._last_ts[key] = ts
        self._refresh()

    @classmethod
    def _key_for_short_id(cls, short_id: str) -> str | None:
        for s, key, _ in cls._LANDMARKS:
            if short_id == s:
                return key
        return None

    def _refresh(self) -> None:
        now = time.time()
        for _short, key, label in self._LANDMARKS:
            buf = self._buffers[key]
            curve = self._curves[key]
            asym = self._asym_lines[key]
            band = self._asym_bands[key]
            hero = self._hero_labels[key]

            if buf:
                curve.setData(x=[t for t, _ in buf], y=[v for _, v in buf])

            self._predictors[key].update(now)
            pred = self._predictors[key].get_prediction(key)
            if (
                pred is not None
                and pred.valid
                and pred.percent_settled >= self._SETTLE_THRESHOLD
            ):
                t_inf = pred.t_predicted
                sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
                asym.setPos(t_inf)
                band.setRegion([t_inf - sigma, t_inf + sigma])
                asym.setVisible(True)
                band.setVisible(True)
                hero.setText(f"{label}: {t_inf:.2f} K (σ {sigma:.2f})")
            else:
                asym.setVisible(False)
                band.setVisible(False)
                if buf:
                    last_val = buf[-1][1]
                    hero.setText(f"{label}: {last_val:.2f} K — стабилизация…")
                else:
                    hero.setText(f"{label}: стабилизация…")
        # 2026-05-08 (v0.56.3): manual Y deadband (same rationale as
        # TemperatureOverviewWidget — pyqtgraph float autoRange is a
        # percentile not hysteresis).
        self._update_y_range_with_deadband()

    def _update_y_range_with_deadband(self) -> None:
        """Cache-driven Y deadband — same approach as TempPlotWidget /
        TemperatureOverviewWidget. Includes visible asymptote line
        positions in the envelope so the predicted-T marker stays in
        view as it converges.
        """
        import math
        import time as _time

        in_window: list[float] = []
        for buf in self._buffers.values():
            for _t, v in buf:
                if math.isfinite(v):
                    in_window.append(v)
        for key, asym in self._asym_lines.items():
            if asym.isVisible():
                in_window.append(float(asym.value()))
        if not in_window:
            return
        new_lo_raw = min(in_window)
        new_hi_raw = max(in_window)
        span = max(new_hi_raw - new_lo_raw, 1.0)
        new_lo = new_lo_raw - span * 0.05
        new_hi = new_hi_raw + span * 0.05
        pi = self._plot.getPlotItem()

        if self._y_cache_lo is None or self._y_cache_hi is None:
            pi.setYRange(new_lo, new_hi, padding=0)
            self._y_cache_lo = new_lo
            self._y_cache_hi = new_hi
            self._y_last_set_ts = _time.monotonic()
            return

        now_mono = _time.monotonic()
        if now_mono - self._y_last_set_ts < 2.0:
            return

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


# ---------------------------------------------------------------------------
# Registration (module load time)
# ---------------------------------------------------------------------------

register(WIDGET_TEMPERATURE_OVERVIEW, TemperatureOverviewWidget)
register(WIDGET_VACUUM_PREDICTION, VacuumPredictionWidget)
register(WIDGET_COOLDOWN_PREDICTION, CooldownPredictionWidget)
register(WIDGET_R_THERMAL_LIVE, RThermalLiveWidget)
register(WIDGET_PRESSURE_CURRENT, PressureCurrentWidget)
register(WIDGET_SENSOR_HEALTH_SUMMARY, SensorHealthSummaryWidget)
register(WIDGET_KEITHLEY_POWER, KeithleyPowerWidget)
register(WIDGET_R_THERMAL_PLACEHOLDER, _r_thermal_placeholder)
register(WIDGET_TEMPERATURE_TRAJECTORY, TemperatureTrajectoryWidget)
register(WIDGET_COOLDOWN_HISTORY, CooldownHistoryWidget)
register(WIDGET_EXPERIMENT_SUMMARY, ExperimentSummaryWidget)
register(WIDGET_TEMPERATURE_STEADY_STATE, lambda: TemperatureSteadyStateWidget())
