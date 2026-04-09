"""Панель давления (вакуумметр).

Логарифмический график давления + текущее значение крупным шрифтом.
Цветовая индикация: зелёный < 1e-3, жёлтый 1e-3–1e-1, красный > 1e-1 мбар.
"""

from __future__ import annotations

import math
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0

# Цвета по уровню давления
_COLOR_GOOD = theme.STATUS_OK       # < 1e-3 мбар
_COLOR_WARN = theme.STATUS_CAUTION  # 1e-3 ... 1e-1 мбар
_COLOR_BAD = theme.STATUS_FAULT     # > 1e-1 мбар


def _pressure_color(value: float) -> str:
    """Определить цвет по давлению."""
    if value <= 0 or not math.isfinite(value):
        return _COLOR_WARN
    if value < 1e-3:
        return _COLOR_GOOD
    if value < 1e-1:
        return _COLOR_WARN
    return _COLOR_BAD


class PressurePanel(QWidget):
    """Панель давления с логарифмическим графиком."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # channel → deque[(ts, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._current: dict[str, float] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # --- Верх: карточка с текущим давлением ---
        self._card = QFrame()
        self._card.setStyleSheet(
            f"background-color: {theme.SURFACE_CARD}; border: 2px solid {_COLOR_GOOD}; border-radius: {theme.RADIUS_LG}px;"
        )
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(16, 12, 16, 12)

        title_font = QFont()
        title_font.setPointSize(10)

        title = QLabel("Давление в криостате")
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        title.setAlignment(Qt.AlignCenter)
        cl.addWidget(title)

        big_font = QFont()
        big_font.setPointSize(32)
        big_font.setBold(True)

        self._value_label = QLabel("—")
        self._value_label.setFont(big_font)
        self._value_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; border: none;")
        self._value_label.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._value_label)

        unit_font = QFont()
        unit_font.setPointSize(11)

        self._unit_label = QLabel("мбар")
        self._unit_label.setFont(unit_font)
        self._unit_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        self._unit_label.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._unit_label)

        root.addWidget(self._card)

        # --- Низ: логарифмический график ---
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._plot.setBackground("#111111")
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Давление", units="мбар", color="#AAAAAA")
        pi.setLabel("bottom", "Время", color="#AAAAAA")
        pi.showGrid(x=True, y=True, alpha=0.3)
        # Логарифмическая ось Y
        pi.setLogMode(x=False, y=True)
        pi.enableAutoRange(axis="y", enable=True)
        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#444444"))
                ax.setTextPen(pg.mkPen(color="#AAAAAA"))

        root.addWidget(self._plot, stretch=1)

    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        if ch not in self._buffers:
            self._buffers[ch] = deque(maxlen=_BUFFER_MAXLEN)
            color = "#17BECF"
            pen = pg.mkPen(color=color, width=2)
            item = self._plot.plot([], [], pen=pen, name=ch)
            self._plot_items[ch] = item

        self._buffers[ch].append((reading.timestamp.timestamp(), reading.value))
        self._current[ch] = reading.value

        # Обновить карточку — берём первый канал
        value = reading.value
        if value > 0 and math.isfinite(value):
            exp = math.floor(math.log10(value))
            mantissa = value / (10 ** exp)
            self._value_label.setText(f"{mantissa:.2f}e{exp}")
        else:
            self._value_label.setText(f"{value:.2e}")

        color = _pressure_color(value)
        self._value_label.setStyleSheet(f"color: {color}; border: none;")
        self._card.setStyleSheet(
            f"background-color: {theme.SURFACE_CARD}; border: 2px solid {color}; border-radius: {theme.RADIUS_LG}px;"
        )

    @Slot()
    def _refresh(self) -> None:
        from cryodaq.gui.widgets.common import snap_x_range

        now = time.time()
        x_min = now - _WINDOW_S
        earliest = now
        for ch, item in self._plot_items.items():
            buf = self._buffers.get(ch)
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            item.setData(xs, ys)
            if xs:
                earliest = min(earliest, xs[0])
        if self._plot_items:
            snap_x_range(self._plot.getPlotItem(), now, _WINDOW_S, earliest)
