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
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

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
register(WIDGET_TEMPERATURE_TRAJECTORY, _temperature_trajectory_placeholder)
register(WIDGET_COOLDOWN_HISTORY, _cooldown_history_placeholder)
register(WIDGET_EXPERIMENT_SUMMARY, _experiment_summary_placeholder)
