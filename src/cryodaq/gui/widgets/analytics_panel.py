"""Панель аналитики — R_thermal и cooldown ETA.

Показывает результаты плагинов: тепловое сопротивление (график)
и прогноз времени охлаждения (крупная цифра).
"""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0


class AnalyticsPanel(QWidget):
    """Панель аналитических плагинов."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: #1A1A1A;")

        self._r_thermal_buf: deque[tuple[float, float]] = deque(maxlen=_BUFFER_MAXLEN)
        self._eta_buf: deque[tuple[float, float]] = deque(maxlen=_BUFFER_MAXLEN)
        self._current_r: float | None = None
        self._current_eta: float | None = None

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

        # --- Верх: две карточки с текущими значениями ---
        cards = QHBoxLayout()
        cards.setSpacing(12)

        big_font = QFont()
        big_font.setPointSize(28)
        big_font.setBold(True)

        label_font = QFont()
        label_font.setPointSize(10)

        # R_thermal
        r_card = QFrame()
        r_card.setStyleSheet(
            "background-color: #2A2A2A; border: 1px solid #f0883e; border-radius: 8px;"
        )
        rl = QVBoxLayout(r_card)
        rl.setContentsMargins(16, 12, 16, 12)

        r_title = QLabel("Тепловое сопротивление")
        r_title.setFont(label_font)
        r_title.setStyleSheet("color: #f0883e; border: none;")
        r_title.setAlignment(Qt.AlignCenter)
        rl.addWidget(r_title)

        self._r_value = QLabel("—")
        self._r_value.setFont(big_font)
        self._r_value.setStyleSheet("color: #FFFFFF; border: none;")
        self._r_value.setAlignment(Qt.AlignCenter)
        rl.addWidget(self._r_value)

        r_unit = QLabel("К/Вт")
        r_unit.setFont(label_font)
        r_unit.setStyleSheet("color: #888888; border: none;")
        r_unit.setAlignment(Qt.AlignCenter)
        rl.addWidget(r_unit)

        cards.addWidget(r_card)

        # Cooldown ETA
        eta_card = QFrame()
        eta_card.setStyleSheet(
            "background-color: #2A2A2A; border: 1px solid #58a6ff; border-radius: 8px;"
        )
        el = QVBoxLayout(eta_card)
        el.setContentsMargins(16, 12, 16, 12)

        eta_title = QLabel("Прогноз охлаждения")
        eta_title.setFont(label_font)
        eta_title.setStyleSheet("color: #58a6ff; border: none;")
        eta_title.setAlignment(Qt.AlignCenter)
        el.addWidget(eta_title)

        self._eta_value = QLabel("—")
        self._eta_value.setFont(big_font)
        self._eta_value.setStyleSheet("color: #FFFFFF; border: none;")
        self._eta_value.setAlignment(Qt.AlignCenter)
        el.addWidget(self._eta_value)

        self._eta_unit = QLabel("")
        self._eta_unit.setFont(label_font)
        self._eta_unit.setStyleSheet("color: #888888; border: none;")
        self._eta_unit.setAlignment(Qt.AlignCenter)
        el.addWidget(self._eta_unit)

        cards.addWidget(eta_card)
        root.addLayout(cards)

        # --- Низ: график R_thermal ---
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#111111")
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "R_thermal", units="К/Вт", color="#AAAAAA")
        pi.setLabel("bottom", "Время", color="#AAAAAA")
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.enableAutoRange(axis="y", enable=True)
        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#444444"))
                ax.setTextPen(pg.mkPen(color="#AAAAAA"))

        self._r_line = self._plot.plot(
            [], [], pen=pg.mkPen(color="#f0883e", width=2)
        )
        root.addWidget(self._plot, stretch=1)

    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        ts = reading.timestamp.timestamp()

        if ch.endswith("/R_thermal"):
            self._r_thermal_buf.append((ts, reading.value))
            self._current_r = reading.value
            self._r_value.setText(f"{reading.value:.4g}")
        elif ch.endswith("/cooldown_eta_s"):
            self._eta_buf.append((ts, reading.value))
            self._current_eta = reading.value
            # Форматировать ETA
            eta = reading.value
            if eta < 60:
                self._eta_value.setText(f"{eta:.0f}")
                self._eta_unit.setText("секунд")
            elif eta < 3600:
                self._eta_value.setText(f"{eta / 60:.1f}")
                self._eta_unit.setText("минут")
            else:
                self._eta_value.setText(f"{eta / 3600:.1f}")
                self._eta_unit.setText("часов")

    @Slot()
    def _refresh(self) -> None:
        now = time.time()
        x_min = now - _WINDOW_S
        buf = self._r_thermal_buf
        if buf:
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            self._r_line.setData(xs, ys)
            self._plot.getPlotItem().setXRange(x_min, now, padding=0)
