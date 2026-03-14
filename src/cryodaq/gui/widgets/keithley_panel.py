"""Панель источника-измерителя Keithley 2604B.

Два SMU-канала (smua, smub), каждый с четырьмя графиками (V, I, R, P)
и текущими значениями крупным шрифтом.
"""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0

# Измеряемые величины: суффикс → (название, единица)
_MEASUREMENTS = {
    "voltage":    ("Напряжение",    "В"),
    "current":    ("Ток",           "А"),
    "resistance": ("Сопротивление", "Ом"),
    "power":      ("Мощность",      "Вт"),
}

# Цвета для smua и smub
_SMU_COLORS = {
    "smua": {"voltage": "#58a6ff", "current": "#3fb950", "resistance": "#f0883e", "power": "#f85149"},
    "smub": {"voltage": "#79c0ff", "current": "#56d364", "resistance": "#ffa657", "power": "#ffa198"},
}


class _SmuTab(QWidget):
    """Вкладка одного SMU-канала с 4 графиками и значениями."""

    def __init__(self, smu_name: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._smu = smu_name

        self._buffers: dict[str, deque[tuple[float, float]]] = {
            k: deque(maxlen=_BUFFER_MAXLEN) for k in _MEASUREMENTS
        }
        self._value_labels: dict[str, QLabel] = {}
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._plot_widgets: dict[str, pg.PlotWidget] = {}

        self._build_ui(colors)

    def _build_ui(self, colors: dict[str, str]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Верх: 4 карточки
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)

        big_font = QFont()
        big_font.setPointSize(20)
        big_font.setBold(True)

        label_font = QFont()
        label_font.setPointSize(9)

        for key, (name, unit) in _MEASUREMENTS.items():
            color = colors[key]
            card = QWidget()
            card.setStyleSheet(
                f"background-color: #2A2A2A; border: 1px solid {color}; border-radius: 6px;"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)

            title = QLabel(name)
            title.setFont(label_font)
            title.setStyleSheet(f"color: {color}; border: none;")
            title.setAlignment(Qt.AlignCenter)
            cl.addWidget(title)

            val = QLabel("—")
            val.setFont(big_font)
            val.setStyleSheet("color: #FFFFFF; border: none;")
            val.setAlignment(Qt.AlignCenter)
            cl.addWidget(val)

            unit_lbl = QLabel(unit)
            unit_lbl.setFont(label_font)
            unit_lbl.setStyleSheet("color: #888888; border: none;")
            unit_lbl.setAlignment(Qt.AlignCenter)
            cl.addWidget(unit_lbl)

            self._value_labels[key] = val
            cards_row.addWidget(card)

        root.addLayout(cards_row)

        # Низ: 2×2 графики
        grid = QGridLayout()
        grid.setSpacing(6)

        for idx, (key, (name, unit)) in enumerate(_MEASUREMENTS.items()):
            color = colors[key]
            pw = pg.PlotWidget()
            pw.setBackground("#111111")
            pi = pw.getPlotItem()
            pi.setLabel("left", name, units=unit, color="#AAAAAA")
            pi.showGrid(x=True, y=True, alpha=0.2)
            pi.enableAutoRange(axis="y", enable=True)
            for ax in ("left", "bottom"):
                a = pi.getAxis(ax)
                if a:
                    a.setPen(pg.mkPen(color="#444444"))
                    a.setTextPen(pg.mkPen(color="#AAAAAA"))

            item = pw.plot([], [], pen=pg.mkPen(color=color, width=2))
            self._plots[key] = item
            self._plot_widgets[key] = pw

            r, c = divmod(idx, 2)
            grid.addWidget(pw, r, c)

        root.addLayout(grid, stretch=1)

    def handle_reading(self, suffix: str, reading: Reading) -> None:
        """Обработать показание для этого SMU."""
        if suffix in self._buffers:
            self._buffers[suffix].append(
                (reading.timestamp.timestamp(), reading.value)
            )
            self._value_labels[suffix].setText(f"{reading.value:.6g}")

    def refresh(self) -> None:
        """Обновить графики."""
        now = time.time()
        x_min = now - _WINDOW_S
        for key, item in self._plots.items():
            buf = self._buffers[key]
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            item.setData(xs, ys)
            self._plot_widgets[key].getPlotItem().setXRange(x_min, now, padding=0)


class KeithleyPanel(QWidget):
    """Панель Keithley 2604B с вкладками smua/smub."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: #1A1A1A;")

        self._smu_tabs: dict[str, _SmuTab] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: #2A2A2A; color: #CCCCCC; padding: 6px 16px; "
            "border: 1px solid #444; border-bottom: none; border-radius: 4px 4px 0 0; }"
            "QTabBar::tab:selected { background: #1A1A1A; color: #FFFFFF; }"
        )

        for smu_name, colors in _SMU_COLORS.items():
            tab = _SmuTab(smu_name, colors)
            self._smu_tabs[smu_name] = tab
            label = smu_name.upper()
            self._tab_widget.addTab(tab, label)

        root.addWidget(self._tab_widget)

        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        # Format: "Keithley_1/smua/voltage" or "Keithley_1/smub/current"
        for smu_name, tab in self._smu_tabs.items():
            if f"/{smu_name}/" in ch:
                for suffix in _MEASUREMENTS:
                    if ch.endswith(f"/{suffix}"):
                        tab.handle_reading(suffix, reading)
                        return

    @Slot()
    def _refresh(self) -> None:
        for tab in self._smu_tabs.values():
            tab.refresh()
