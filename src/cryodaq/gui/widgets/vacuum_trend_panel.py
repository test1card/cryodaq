"""Панель прогноза вакуума (VacuumTrendPanel).

Встраивается в AnalyticsPanel как секция. Показывает:
- График log₁₀(P) vs время: данные (сплошная), экстраполяция (пунктир),
  целевые уровни (красные горизонтали)
- Sidebar: тренд, ETA, P_предельное, модель + R², confidence bar
- Polling 10с через ZmqCommandWorker → get_vacuum_trend
"""

from __future__ import annotations

import math
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.widgets.common import apply_panel_frame_style

_COLOR_GREEN = theme.STATUS_OK
_COLOR_YELLOW = theme.STATUS_CAUTION
_COLOR_RED = theme.STATUS_FAULT
_COLOR_WHITE = theme.TEXT_PRIMARY
_COLOR_MUTED = theme.TEXT_MUTED

_TREND_ICONS: dict[str, tuple[str, str]] = {
    "pumping_down": ("↓", _COLOR_GREEN),
    "stable": ("→", _COLOR_YELLOW),
    "rising": ("↑", _COLOR_RED),
    "anomaly": ("⚠", _COLOR_RED),
    "insufficient_data": ("…", _COLOR_MUTED),
}

_TREND_LABELS: dict[str, str] = {
    "pumping_down": "Откачка",
    "stable": "Стабильно",
    "rising": "Рост!",
    "anomaly": "Аномалия",
    "insufficient_data": "Нет данных",
}


def _fmt_pressure(p: float) -> str:
    if not math.isfinite(p):
        return "—"
    return f"{p:.1e}"


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds == 0.0:
        return "✓"
    if seconds < 60:
        return f"{seconds:.0f}с"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}ч {mins}мин"
    return f"{mins}мин"


def _confidence_color(r2: float) -> str:
    if r2 >= 0.9:
        return _COLOR_GREEN
    if r2 >= 0.7:
        return _COLOR_YELLOW
    return _COLOR_RED


class VacuumTrendPanel(QWidget):
    """Панель прогноза вакуума с графиком и sidebar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._prediction: dict[str, Any] = {}
        self._build_ui()

        # Polling timer: 10s
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10_000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        QTimer.singleShot(500, self._poll)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(4)

        # Header
        header = QFrame()
        apply_panel_frame_style(header)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        title = QLabel("ПРОГНОЗ ВАКУУМА")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {_COLOR_MUTED};")
        header_layout.addWidget(self._status_label)
        root.addWidget(header)

        # Main content: sidebar + plot
        content = QHBoxLayout()
        content.setSpacing(8)

        # --- Left sidebar ---
        sidebar = QFrame()
        apply_panel_frame_style(sidebar)
        sidebar.setFixedWidth(180)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(12, 12, 12, 12)
        sb.setSpacing(8)

        # Trend icon + label
        self._trend_icon = QLabel("…")
        self._trend_icon.setFont(QFont("", 28, QFont.Weight.Bold))
        self._trend_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._trend_icon.setStyleSheet(f"color: {_COLOR_MUTED};")
        sb.addWidget(self._trend_icon)

        self._trend_label = QLabel("Нет данных")
        self._trend_label.setFont(QFont("", 10, QFont.Weight.Bold))
        self._trend_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._trend_label.setStyleSheet(f"color: {_COLOR_MUTED};")
        sb.addWidget(self._trend_label)

        # ETA section
        eta_title = QLabel("ETA:")
        eta_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")
        sb.addWidget(eta_title)
        self._eta_labels: dict[str, QLabel] = {}
        # Will be populated dynamically
        self._eta_container = QVBoxLayout()
        self._eta_container.setSpacing(2)
        sb.addLayout(self._eta_container)

        # P ultimate
        sb.addSpacing(4)
        p_title = QLabel("P предельное:")
        p_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")
        sb.addWidget(p_title)
        self._p_ult_label = QLabel("—")
        self._p_ult_label.setFont(QFont("", 12, QFont.Weight.Bold))
        self._p_ult_label.setStyleSheet(f"color: {_COLOR_WHITE};")
        sb.addWidget(self._p_ult_label)

        # Model info
        sb.addSpacing(4)
        self._model_label = QLabel("Модель: —")
        self._model_label.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")
        self._model_label.setWordWrap(True)
        sb.addWidget(self._model_label)

        self._r2_label = QLabel("R²: —")
        self._r2_label.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")
        sb.addWidget(self._r2_label)

        # Confidence bar
        sb.addSpacing(4)
        conf_title = QLabel("Уверенность:")
        conf_title.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 10px;")
        sb.addWidget(conf_title)
        self._confidence_bar = QProgressBar()
        self._confidence_bar.setRange(0, 100)
        self._confidence_bar.setValue(0)
        self._confidence_bar.setTextVisible(True)
        self._confidence_bar.setFixedHeight(16)
        self._confidence_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_SM}px; "  # noqa: E501
            f"background: {theme.SURFACE_SUNKEN}; color: {theme.TEXT_SECONDARY}; text-align: center; font-size: 9px; }} "  # noqa: E501
            f"QProgressBar::chunk {{ background: {_COLOR_GREEN}; border-radius: 2px; }}"
        )
        sb.addWidget(self._confidence_bar)

        sb.addStretch()
        content.addWidget(sidebar)

        # --- Right: plot ---
        self._plot = pg.PlotWidget()
        # Background provided by gui.theme global pyqtgraph config.
        pi = self._plot.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.2)
        pi.setLabel("left", "log₁₀(P), мбар", color="#AAAAAA")
        pi.setLabel("bottom", "Время (с от старта)", color="#AAAAAA")
        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#21262d"))
                ax.setTextPen(pg.mkPen(color="#8b949e"))

        # Data curve: solid white
        self._data_curve = self._plot.plot(
            [], [], pen=pg.mkPen(color="#ffffff", width=1.5), name="Данные"
        )
        # Extrapolation: dashed white
        self._extrap_curve = self._plot.plot(
            [],
            [],
            pen=pg.mkPen(color="#ffffff", width=1, style=Qt.PenStyle.DashLine),
            name="Экстраполяция",
        )
        # Target lines stored as list
        self._target_lines: list[pg.InfiniteLine] = []

        # Empty state overlay
        self._empty_label = QLabel(
            "Недостаточно данных для прогноза\n(нужно минимум 60 точек)",
            self._plot,
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: 12pt; background: transparent;"
        )
        self._empty_label.setGeometry(50, 50, 400, 80)
        self._empty_visible = True  # track state ourselves (widget visibility depends on show())

        content.addWidget(self._plot, stretch=1)
        root.addLayout(content, stretch=1)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll(self) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
        worker.finished.connect(self._on_result)
        worker.start()

    @Slot(dict)
    def _on_result(self, result: dict) -> None:
        if not result.get("ok"):
            return
        if result.get("status") == "no_data":
            self._show_empty()
            return
        self._prediction = result
        self._refresh_ui()

    def set_prediction(self, prediction: dict[str, Any]) -> None:
        """Set prediction data directly (for testing)."""
        self._prediction = dict(prediction)
        self._refresh_ui()

    def clear(self) -> None:
        """Reset to empty state."""
        self._prediction = {}
        self._show_empty()

    # ------------------------------------------------------------------
    # UI refresh
    # ------------------------------------------------------------------

    def _show_empty(self) -> None:
        self._empty_label.setVisible(True)
        self._empty_visible = True
        self._data_curve.setData([], [])
        self._extrap_curve.setData([], [])
        for line in self._target_lines:
            self._plot.removeItem(line)
        self._target_lines.clear()
        self._set_trend("insufficient_data")
        self._p_ult_label.setText("—")
        self._model_label.setText("Модель: —")
        self._r2_label.setText("R²: —")
        self._confidence_bar.setValue(0)
        self._status_label.setText("")
        # Clear ETAs
        self._clear_eta_labels()

    def _refresh_ui(self) -> None:
        p = self._prediction
        if not p or p.get("model_type") == "insufficient_data":
            self._show_empty()
            return

        self._empty_label.setVisible(False)
        self._empty_visible = False

        # Trend
        self._set_trend(p.get("trend", "insufficient_data"))

        # P ultimate
        p_ult = p.get("p_ultimate_mbar", float("nan"))
        self._p_ult_label.setText(_fmt_pressure(p_ult))

        # Model
        model = p.get("model_type", "—")
        model_names = {
            "exponential": "Экспонента",
            "power_law": "Степенная",
            "combined": "Комбинированная",
        }
        self._model_label.setText(f"Модель: {model_names.get(model, model)}")

        # R² / confidence
        confidence = p.get("confidence", 0.0)
        self._r2_label.setText(f"R² = {confidence:.3f}")
        self._confidence_bar.setValue(int(confidence * 100))
        color = _confidence_color(confidence)
        self._confidence_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_SM}px; "  # noqa: E501
            f"background: {theme.SURFACE_SUNKEN}; color: {theme.TEXT_SECONDARY}; text-align: center; font-size: 9px; }} "  # noqa: E501
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )

        # ETA
        eta_targets = p.get("eta_targets", {})
        self._refresh_eta_labels(eta_targets)

        # Status label
        self._status_label.setText(f"[{model_names.get(model, model)}]")

        # --- Plot ---
        self._refresh_plot(p)

    def _set_trend(self, trend: str) -> None:
        icon, color = _TREND_ICONS.get(trend, ("?", _COLOR_MUTED))
        label = _TREND_LABELS.get(trend, trend)
        self._trend_icon.setText(icon)
        self._trend_icon.setStyleSheet(f"color: {color};")
        self._trend_label.setText(label)
        self._trend_label.setStyleSheet(f"color: {color};")

    def _clear_eta_labels(self) -> None:
        for lbl in self._eta_labels.values():
            self._eta_container.removeWidget(lbl)
            lbl.deleteLater()
        self._eta_labels.clear()

    def _refresh_eta_labels(self, eta_targets: dict[str, Any]) -> None:
        self._clear_eta_labels()
        for target_str, eta_val in sorted(eta_targets.items(), key=lambda x: float(x[0])):
            try:
                target_mbar = float(target_str)
            except ValueError:
                continue
            text = f"{_fmt_pressure(target_mbar)}: {_fmt_eta(eta_val)}"
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {_COLOR_WHITE}; font-size: 11px;")
            self._eta_container.addWidget(lbl)
            self._eta_labels[target_str] = lbl

    def _refresh_plot(self, p: dict) -> None:
        extrap_t = p.get("extrapolation_t", [])
        extrap_logP = p.get("extrapolation_logP", [])

        # Extrapolation curve
        if extrap_t and extrap_logP:
            self._extrap_curve.setData(extrap_t, extrap_logP)
        else:
            self._extrap_curve.setData([], [])

        # Data curve: reconstruct from fit_params isn't possible directly,
        # but we can show the model fit over the data range.
        # Since we don't have raw data here, show extrapolation only.
        # The data_curve will be empty unless we receive raw buffer data.
        # For now, clear it — engine integration can add raw_t/raw_logP later.
        self._data_curve.setData([], [])

        # Target lines
        for line in self._target_lines:
            self._plot.removeItem(line)
        self._target_lines.clear()

        eta_targets = p.get("eta_targets", {})
        for target_str in eta_targets:
            try:
                target_mbar = float(target_str)
                log_target = math.log10(target_mbar)
            except (ValueError, ZeroDivisionError):
                continue
            line = pg.InfiniteLine(
                pos=log_target,
                angle=0,
                pen=pg.mkPen(color=_COLOR_RED, width=1, style=Qt.PenStyle.DashLine),
                label=f"{_fmt_pressure(target_mbar)}",
                labelOpts={"color": _COLOR_RED, "position": 0.95},
            )
            self._plot.addItem(line)
            self._target_lines.append(line)

    # ------------------------------------------------------------------
    # Public properties for testing
    # ------------------------------------------------------------------

    @property
    def trend_text(self) -> str:
        return self._trend_label.text()

    @property
    def trend_color(self) -> str:
        # Extract color from stylesheet
        ss = self._trend_icon.styleSheet()
        if _COLOR_GREEN in ss:
            return _COLOR_GREEN
        if _COLOR_YELLOW in ss:
            return _COLOR_YELLOW
        if _COLOR_RED in ss:
            return _COLOR_RED
        return _COLOR_MUTED
