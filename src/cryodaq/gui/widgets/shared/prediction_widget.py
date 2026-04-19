"""Prediction plot — always-full history + forward horizon with band.

Layout (single widget)::

    | full history (all time since experiment start)  |  forward horizon |
                                                       ^ now boundary

Independent from :class:`GlobalTimeWindowController` — predictions
look forward, not backward. History is always full because
prediction confidence depends on the full observed series, so
hiding part of it has no meaning.

Forward horizon is selectable via a 6-button strip (1/3/6/12/24/48 ч).
Uncertainty band rendered as :class:`pyqtgraph.FillBetweenItem`
between ``lower_ci`` and ``upper_ci`` series, semi-transparent tint
derived from :data:`theme.STATUS_INFO` (neutral informational — NOT
safety semantic).
"""

from __future__ import annotations

import math
from bisect import bisect_left

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.widgets.shared.pressure_plot import ScientificLogAxisItem

_HORIZON_OPTIONS_HOURS: tuple[float, ...] = (1.0, 3.0, 6.0, 12.0, 24.0, 48.0)
_CI_BAND_ALPHA: int = 64  # 0-255; ~25% opacity
_DEFAULT_HORIZON_HOURS: float = 24.0


def _hex_to_qcolor_with_alpha(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(int(alpha))
    return color


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_MEDIUM))
    return font


def _value_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_SIZE_BASE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _interpolate_at(series: list[tuple[float, float]], t: float) -> float | None:
    """Return the Y value at or near timestamp ``t`` in the series.

    Linear interpolation between bracketing samples; returns None on
    empty series."""
    if not series:
        return None
    times = [p[0] for p in series]
    idx = bisect_left(times, t)
    if idx <= 0:
        return series[0][1]
    if idx >= len(series):
        return series[-1][1]
    t0, y0 = series[idx - 1]
    t1, y1 = series[idx]
    if t1 == t0:
        return y1
    frac = (t - t0) / (t1 - t0)
    return y0 + frac * (y1 - y0)


class PredictionWidget(QWidget):
    """Forward-looking prediction plot + horizon selector + readout."""

    horizon_changed = Signal(float)  # hours

    def __init__(
        self,
        title: str,
        y_label: str,
        y_unit: str,
        *,
        log_y: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._y_label = y_label
        self._y_unit = y_unit
        self._log_y = log_y
        self._horizon_hours: float = _DEFAULT_HORIZON_HOURS
        self._history: list[tuple[float, float]] = []
        self._central: list[tuple[float, float]] = []
        self._lower_ci: list[tuple[float, float]] = []
        self._upper_ci: list[tuple[float, float]] = []
        self._ci_level_pct: float = 67.0
        self._horizon_buttons: dict[float, QPushButton] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        root.setSpacing(theme.SPACE_2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(theme.SPACE_2)
        self._title_label = QLabel(self._title)
        self._title_label.setFont(_label_font())
        self._title_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        header.addWidget(self._title_label)
        header.addStretch()
        header.addWidget(self._build_horizon_selector())
        root.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SPACE_2)
        body.addWidget(self._build_plot(), stretch=4)
        body.addWidget(self._build_readout(), stretch=1)
        root.addLayout(body)

    def _build_horizon_selector(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        for hrs in _HORIZON_OPTIONS_HOURS:
            btn = QPushButton(f"{int(hrs) if hrs == int(hrs) else hrs}ч")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, h=hrs: self.set_horizon(h))
            self._horizon_buttons[hrs] = btn
            layout.addWidget(btn)
        self._apply_horizon_styles()
        return w

    def _apply_horizon_styles(self) -> None:
        for hrs, btn in self._horizon_buttons.items():
            checked = hrs == self._horizon_hours
            if btn.isChecked() != checked:
                btn.setChecked(checked)
            if checked:
                # Phase III.A: UI activation renders in ACCENT; the
                # status tier stays reserved for semantic safety cues.
                bg, fg, border = theme.ACCENT, theme.ON_ACCENT, theme.ACCENT
            else:
                bg = theme.SURFACE_MUTED
                fg = theme.FOREGROUND
                border = theme.BORDER_SUBTLE
            btn.setStyleSheet(
                f"QPushButton {{"
                f" background-color: {bg};"
                f" color: {fg};"
                f" border: 1px solid {border};"
                f" border-radius: {theme.RADIUS_SM}px;"
                f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
                f" font-size: {theme.FONT_LABEL_SIZE}px;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
                f"}}"
            )

    def _build_plot(self) -> QWidget:
        axis_items: dict[str, pg.AxisItem] = {}
        if self._log_y:
            axis_items["left"] = ScientificLogAxisItem(orientation="left")
        plot = pg.PlotWidget(axisItems=axis_items if axis_items else None)
        apply_plot_style(plot)
        pi = plot.getPlotItem()
        if self._y_unit:
            pi.setLabel("left", self._y_label, units=self._y_unit, color=theme.PLOT_LABEL_COLOR)
        else:
            pi.setLabel("left", self._y_label, color=theme.PLOT_LABEL_COLOR)
        pi.setLabel("bottom", "Время", color=theme.PLOT_LABEL_COLOR)
        date_axis = pg.DateAxisItem(orientation="bottom")
        plot.setAxisItems({"bottom": date_axis})
        if self._log_y:
            pi.setLogMode(x=False, y=True)

        self._plot = plot

        # History — solid line, full series.
        self._history_curve = plot.plot([], [], pen=series_pen(0), name="История")
        # Central prediction — dashed.
        prediction_pen = pg.mkPen(
            color=QColor(theme.STATUS_INFO), width=theme.PLOT_LINE_WIDTH, style=Qt.DashLine
        )
        self._central_curve = plot.plot([], [], pen=prediction_pen, name="Прогноз")

        # CI band via FillBetweenItem between invisible lower / upper curves.
        self._lower_curve = plot.plot([], [], pen=pg.mkPen(None))
        self._upper_curve = plot.plot([], [], pen=pg.mkPen(None))
        band_color = _hex_to_qcolor_with_alpha(theme.STATUS_INFO, _CI_BAND_ALPHA)
        self._ci_band = pg.FillBetweenItem(
            self._lower_curve, self._upper_curve, brush=pg.mkBrush(band_color)
        )
        pi.addItem(self._ci_band)

        # Now marker — vertical dashed line rendered via InfiniteLine.
        self._now_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(color=QColor(theme.BORDER), style=Qt.DashLine),
            movable=False,
        )
        pi.addItem(self._now_line)

        return plot

    def _build_readout(self) -> QWidget:
        frame = QWidget()
        frame.setObjectName("predictionReadout")
        frame.setStyleSheet(
            f"#predictionReadout {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_1)

        self._horizon_caption_label = QLabel(self._horizon_caption())
        self._horizon_caption_label.setFont(_label_font())
        self._horizon_caption_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._horizon_caption_label)

        self._predicted_value_label = QLabel("—")
        self._predicted_value_label.setFont(_value_font())
        self._predicted_value_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._predicted_value_label)

        self._ci_label = QLabel("")
        self._ci_label.setFont(_label_font())
        self._ci_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._ci_label)
        layout.addStretch()
        return frame

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_history(self, points: list[tuple[float, float]]) -> None:
        self._history = list(points)
        xs = [t for t, _ in self._history]
        ys = [v for _, v in self._history]
        if self._log_y:
            ys = [v if v > 0 else 1e-12 for v in ys]
        self._history_curve.setData(x=xs, y=ys)
        self._update_now_marker()
        self._refresh_readout()

    def set_prediction(
        self,
        central: list[tuple[float, float]],
        lower_ci: list[tuple[float, float]],
        upper_ci: list[tuple[float, float]],
        ci_level_pct: float,
    ) -> None:
        self._central = list(central)
        self._lower_ci = list(lower_ci)
        self._upper_ci = list(upper_ci)
        self._ci_level_pct = float(ci_level_pct)

        self._central_curve.setData(
            x=[t for t, _ in self._central],
            y=self._coerce_ys([v for _, v in self._central]),
        )
        self._lower_curve.setData(
            x=[t for t, _ in self._lower_ci],
            y=self._coerce_ys([v for _, v in self._lower_ci]),
        )
        self._upper_curve.setData(
            x=[t for t, _ in self._upper_ci],
            y=self._coerce_ys([v for _, v in self._upper_ci]),
        )
        self._refresh_readout()

    def set_horizon(self, hours: float) -> None:
        hours = float(hours)
        if hours == self._horizon_hours:
            return
        self._horizon_hours = hours
        self._apply_horizon_styles()
        self._horizon_caption_label.setText(self._horizon_caption())
        self._refresh_readout()
        self.horizon_changed.emit(hours)

    def get_horizon(self) -> float:
        return self._horizon_hours

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _coerce_ys(self, values: list[float]) -> list[float]:
        if self._log_y:
            return [v if v > 0 else 1e-12 for v in values]
        return list(values)

    def _horizon_caption(self) -> str:
        hrs = self._horizon_hours
        hrs_text = f"{int(hrs) if hrs == int(hrs) else hrs}"
        return f"Через {hrs_text} ч"

    def _update_now_marker(self) -> None:
        if self._history:
            now = self._history[-1][0]
        elif self._central:
            now = self._central[0][0]
        else:
            return
        self._now_line.setPos(now)

    def _refresh_readout(self) -> None:
        if self._history:
            now = self._history[-1][0]
        elif self._central:
            now = self._central[0][0]
        else:
            self._predicted_value_label.setText("—")
            self._ci_label.setText("")
            return
        target_t = now + self._horizon_hours * 3600.0
        central = _interpolate_at(self._central, target_t)
        lower = _interpolate_at(self._lower_ci, target_t)
        upper = _interpolate_at(self._upper_ci, target_t)
        if central is None:
            self._predicted_value_label.setText("—")
            self._ci_label.setText("")
            return
        self._predicted_value_label.setText(self._format_value(central))
        if lower is not None and upper is not None:
            half_ci = (upper - lower) / 2.0
            # Russian label: «ДИ» = доверительный интервал (confidence
            # interval). Keeps operator-facing copy consistent with
            # the rest of the overlay.
            self._ci_label.setText(
                f"± {self._format_value(abs(half_ci))}, "
                f"{self._ci_level_pct:.0f}% ДИ"
            )
        else:
            self._ci_label.setText("")

    def _format_value(self, value: float) -> str:
        if not math.isfinite(value):
            return "—"
        unit_suffix = f" {self._y_unit}" if self._y_unit else ""
        if self._log_y:
            return f"{value:.1e}{unit_suffix}"
        return f"{value:.2f}{unit_suffix}"
