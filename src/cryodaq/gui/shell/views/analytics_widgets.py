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

from collections.abc import Callable
from dataclasses import dataclass, field

import pyqtgraph as pg
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

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
# Placeholder widget — «данные появятся при переходе фазы»
# ---------------------------------------------------------------------------


class PlaceholderCard(QWidget):
    """Placeholder card for widgets whose data pipeline is not yet wired."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        card = _card("analyticsPlaceholder")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        layout.setSpacing(theme.SPACE_2)
        layout.addWidget(_title_label(title))
        layout.addStretch()
        layout.addWidget(_muted_label(f"{title} — данные появятся при переходе фазы."))
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


class TemperatureOverviewWidget(QWidget):
    """Compact multi-channel temperature plot following the global
    time window. Subscribes to ``GlobalTimeWindowController``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._series: dict[str, _ChannelSeries] = {}
        self._build_ui()
        controller = get_time_window_controller()
        self._apply_window(controller.get_window())
        controller.window_changed.connect(self._apply_window)

    def _build_ui(self) -> None:
        card = _card("analyticsTemperatureOverview")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Температурные каналы"))
        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="K", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
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
            return
        now = time.time()
        pi.setXRange(now - window.seconds, now, padding=0)


class TemperatureTrajectoryWidget(QWidget):
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

        channels = self._channel_mgr.get_cold_channels() or None
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
    """Log-Y prediction widget wrapped for vacuum forecast."""

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

    def set_vacuum_prediction(self, data: dict | None) -> None:
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


class CooldownPredictionWidget(QWidget):
    """Linear-Y prediction widget wrapped for cooldown forecast."""

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

    def set_cooldown_data(self, data) -> None:
        if data is None:
            return
        # CooldownData from analytics_view has actual_trajectory,
        # predicted_trajectory, ci_trajectory (t, lo, hi triples).
        actual = getattr(data, "actual_trajectory", []) or []
        predicted = getattr(data, "predicted_trajectory", []) or []
        ci = getattr(data, "ci_trajectory", []) or []
        self._inner.set_history([(t, v) for (t, v) in actual])
        if predicted and ci:
            lower = [(t, lo) for (t, lo, _hi) in ci]
            upper = [(t, hi) for (t, _lo, hi) in ci]
            self._inner.set_prediction(
                [(t, v) for (t, v) in predicted],
                lower,
                upper,
                ci_level_pct=67.0,
            )


class RThermalLiveWidget(QWidget):
    """Live R_thermal readout + delta/min + compact history plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._curve = self._plot.plot([], [], pen=series_pen(0))
        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_r_thermal_data(self, data) -> None:
        if data is None:
            self._value_label.setText("—")
            self._delta_label.setText("ΔR / мин: —")
            self._curve.setData([], [])
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


class PressureCurrentWidget(QWidget):
    """Wraps the shared :class:`PressurePlot` for the analytics view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card = _card("analyticsPressureCurrent")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Давление"))
        self._plot = PressurePlot()
        lay.addWidget(self._plot, stretch=1)
        self._series: list[tuple[float, float]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

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


class CooldownHistoryWidget(QWidget):
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


class ExperimentSummaryWidget(QWidget):
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
        self._alarm_label = self._add_info_row(c_lay, "Алармы")
        self._docx_label = self._add_info_row(c_lay, "Отчёт DOCX")
        self._docx_label.setWordWrap(True)
        self._pdf_label = self._add_info_row(c_lay, "Отчёт PDF")
        self._pdf_label.setWordWrap(True)

        c_lay.addStretch()
        self._content.setHidden(True)
        lay.addWidget(self._content, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)


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
        if artifact_dir:
            base = _Path(artifact_dir)
            self._docx_label.setText(str(base / "reports" / "report_editable.docx"))
            self._pdf_label.setText(str(base / "reports" / "report_raw.pdf"))
        else:
            self._docx_label.setText("—")
            self._pdf_label.setText("—")

        if start_ts is not None:
            self._fetch_alarms(start_ts)
        else:
            self._alarm_label.setText("—")

        self._empty_label.setHidden(True)
        self._content.setHidden(False)

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
            return
        history = result.get("history", [])
        triggered = [e for e in history if e.get("transition") == "TRIGGERED"]
        warnings = sum(1 for e in triggered if str(e.get("level", "")).upper() == "WARNING")
        criticals = sum(1 for e in triggered if str(e.get("level", "")).upper() == "CRITICAL")
        total = len(triggered)
        self._alarm_label.setText(f"{total} ({warnings} пред. / {criticals} крит.)")


# ---------------------------------------------------------------------------
# Placeholder widget factories
# ---------------------------------------------------------------------------


def _r_thermal_placeholder() -> QWidget:
    return PlaceholderCard("R тепл.")


def _temperature_trajectory_placeholder() -> QWidget:
    return PlaceholderCard("Траектория температуры")


def _cooldown_history_placeholder() -> QWidget:
    return PlaceholderCard("История захолаживаний")


def _experiment_summary_placeholder() -> QWidget:
    return PlaceholderCard("Сводка эксперимента")


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
