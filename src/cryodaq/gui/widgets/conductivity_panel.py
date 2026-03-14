"""Панель измерения теплопроводности.

Позволяет выбрать цепочку температурных датчиков, отображает
тепловое сопротивление R = dT/P и проводимость G = P/dT между
соседними парами, а также суммарные значения.
"""

from __future__ import annotations

import csv
import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0
_STABILITY_THRESHOLD = 0.01  # К/мин — порог стабильности

# 24 температурных канала
_ALL_CHANNELS = [
    "Т1 Криостат верх", "Т2 Криостат низ", "Т3 Радиатор 1", "Т4 Радиатор 2",
    "Т5 Экран 77К", "Т6 Экран 4К", "Т7 Детектор", "Т8 Калибровка",
    "Т9 Компрессор вход", "Т10 Компрессор выход",
    "Т11 Теплообменник 1", "Т12 Теплообменник 2",
    "Т13 Труба подачи", "Т14 Труба возврата",
    "Т15 Вакуумный кожух", "Т16 Фланец",
    "Т17 Зеркало 1", "Т18 Зеркало 2", "Т19 Подвес", "Т20 Рама",
    "Т21 Резерв 1", "Т22 Резерв 2", "Т23 Резерв 3", "Т24 Резерв 4",
]

_LINE_COLORS = [
    "#58a6ff", "#3fb950", "#f0883e", "#f85149", "#bc8cff",
    "#ff7b72", "#79c0ff", "#56d364", "#ffa657", "#d2a8ff",
]


class ConductivityPanel(QWidget):
    """Панель измерения теплопроводности цепочки датчиков."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: #1A1A1A;")

        # Текущие значения температур: channel → float
        self._temps: dict[str, float] = {}
        # Текущая мощность Keithley
        self._power: float = 0.0
        self._power_channel: str = ""
        # Буферы для графиков: channel → deque[(ts, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # Выбранные каналы (упорядоченная цепочка)
        self._chain: list[str] = []
        # Чекбоксы
        self._checkboxes: dict[str, QCheckBox] = {}
        # Линии графика
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        # Буферы для dT/dt
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Левая панель: выбор каналов ---
        left = QVBoxLayout()
        left.setSpacing(6)

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)

        t = QLabel("Выбор датчиков")
        t.setFont(title_font)
        t.setStyleSheet("color: #58a6ff;")
        left.addWidget(t)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setFixedWidth(220)

        ch_container = QWidget()
        ch_container.setStyleSheet("background: transparent;")
        ch_layout = QVBoxLayout(ch_container)
        ch_layout.setContentsMargins(4, 4, 4, 4)
        ch_layout.setSpacing(2)

        for ch_name in _ALL_CHANNELS:
            cb = QCheckBox(ch_name)
            cb.setStyleSheet("color: #c9d1d9;")
            cb.stateChanged.connect(lambda state, n=ch_name: self._on_check(n, state))
            self._checkboxes[ch_name] = cb
            ch_layout.addWidget(cb)

        ch_layout.addStretch()
        scroll.setWidget(ch_container)
        left.addWidget(scroll, stretch=1)

        # Источник мощности
        src_lbl = QLabel("Источник P:")
        src_lbl.setStyleSheet("color: #c9d1d9;")
        left.addWidget(src_lbl)

        self._power_combo = QComboBox()
        self._power_combo.addItems([
            "Keithley_1/smua/power",
            "Keithley_1/smub/power",
        ])
        self._power_combo.currentTextChanged.connect(self._on_power_changed)
        self._power_channel = self._power_combo.currentText()
        left.addWidget(self._power_combo)

        # Кнопки
        btn_layout = QHBoxLayout()

        up_btn = QPushButton("Вверх")
        up_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 4px 8px; border-radius: 3px; }"
        )
        up_btn.clicked.connect(self._on_move_up)
        btn_layout.addWidget(up_btn)

        down_btn = QPushButton("Вниз")
        down_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 4px 8px; border-radius: 3px; }"
        )
        down_btn.clicked.connect(self._on_move_down)
        btn_layout.addWidget(down_btn)

        left.addLayout(btn_layout)

        export_btn = QPushButton("Экспорт CSV")
        export_btn.setStyleSheet(
            "QPushButton { background: #238636; color: white; border: none; "
            "padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: #2ea043; }"
        )
        export_btn.clicked.connect(self._on_export)
        left.addWidget(export_btn)

        root.addLayout(left)

        # --- Правая панель: таблица + индикатор + график ---
        right = QVBoxLayout()
        right.setSpacing(8)

        # Индикатор стабильности
        stab_row = QHBoxLayout()
        self._stability_label = QLabel("Стабильность: —")
        self._stability_label.setFont(title_font)
        self._stability_label.setStyleSheet("color: #888888;")
        stab_row.addWidget(self._stability_label)

        self._power_label = QLabel("P = — Вт")
        self._power_label.setFont(title_font)
        self._power_label.setStyleSheet("color: #f0883e;")
        stab_row.addWidget(self._power_label)
        stab_row.addStretch()
        right.addLayout(stab_row)

        # Таблица R и G
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Пара", "T горячая (К)", "T холодная (К)", "dT (К)", "R (К/Вт)", "G (Вт/К)",
        ])
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMaximumHeight(250)
        right.addWidget(self._table)

        # График температур
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#111111")
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="К", color="#AAAAAA")
        pi.setLabel("bottom", "Время", color="#AAAAAA")
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.enableAutoRange(axis="y", enable=True)
        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#444444"))
                ax.setTextPen(pg.mkPen(color="#AAAAAA"))

        right.addWidget(self._plot, stretch=1)

        root.addLayout(right, stretch=1)

    # ------------------------------------------------------------------
    # Channel selection
    # ------------------------------------------------------------------

    def _on_check(self, ch_name: str, state: int) -> None:
        if state == Qt.CheckState.Checked.value:
            if ch_name not in self._chain:
                self._chain.append(ch_name)
                if ch_name not in self._buffers:
                    self._buffers[ch_name] = deque(maxlen=_BUFFER_MAXLEN)
                    self._rate_buffers[ch_name] = deque(maxlen=120)
                # Add plot line
                idx = len(self._plot_items)
                color = _LINE_COLORS[idx % len(_LINE_COLORS)]
                item = self._plot.plot([], [], pen=pg.mkPen(color=color, width=2), name=ch_name)
                self._plot_items[ch_name] = item
        else:
            if ch_name in self._chain:
                self._chain.remove(ch_name)
            if ch_name in self._plot_items:
                self._plot.removeItem(self._plot_items.pop(ch_name))

    def _on_move_up(self) -> None:
        # Find first checked channel and move it up
        for i, ch in enumerate(self._chain):
            if i > 0 and self._checkboxes.get(ch, QCheckBox()).hasFocus():
                self._chain[i - 1], self._chain[i] = self._chain[i], self._chain[i - 1]
                break

    def _on_move_down(self) -> None:
        for i, ch in enumerate(self._chain):
            if i < len(self._chain) - 1 and self._checkboxes.get(ch, QCheckBox()).hasFocus():
                self._chain[i], self._chain[i + 1] = self._chain[i + 1], self._chain[i]
                break

    def _on_power_changed(self, text: str) -> None:
        self._power_channel = text

    # ------------------------------------------------------------------
    # Data input
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel

        if ch in self._checkboxes and reading.unit == "K":
            self._temps[ch] = reading.value
            if ch in self._buffers:
                self._buffers[ch].append((reading.timestamp.timestamp(), reading.value))
                self._rate_buffers[ch].append((reading.timestamp.timestamp(), reading.value))

        if ch == self._power_channel:
            self._power = reading.value

    # ------------------------------------------------------------------
    # Periodic refresh
    # ------------------------------------------------------------------

    @Slot()
    def _refresh(self) -> None:
        self._update_table()
        self._update_stability()
        self._update_plot()
        self._power_label.setText(f"P = {self._power:.6g} Вт")

    def _update_table(self) -> None:
        if len(self._chain) < 2:
            self._table.setRowCount(0)
            return

        pairs = list(zip(self._chain[:-1], self._chain[1:]))
        # +1 row for total
        self._table.setRowCount(len(pairs) + 1)

        total_r = 0.0
        P = self._power

        for row, (hot_ch, cold_ch) in enumerate(pairs):
            t_hot = self._temps.get(hot_ch, float("nan"))
            t_cold = self._temps.get(cold_ch, float("nan"))
            dt = t_hot - t_cold

            if P != 0 and math.isfinite(dt):
                R = dt / P
                G = P / dt if dt != 0 else float("inf")
                total_r += R
            else:
                R = float("nan")
                G = float("nan")

            self._table.setItem(row, 0, QTableWidgetItem(f"{hot_ch} → {cold_ch}"))
            self._table.setItem(row, 1, QTableWidgetItem(f"{t_hot:.4f}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{t_cold:.4f}"))
            self._table.setItem(row, 3, QTableWidgetItem(f"{dt:.4f}"))
            self._table.setItem(row, 4, QTableWidgetItem(f"{R:.4g}" if math.isfinite(R) else "—"))
            self._table.setItem(row, 5, QTableWidgetItem(f"{G:.4g}" if math.isfinite(G) else "—"))

        # Total row
        total_row = len(pairs)
        t_first = self._temps.get(self._chain[0], float("nan"))
        t_last = self._temps.get(self._chain[-1], float("nan"))
        total_dt = t_first - t_last
        total_G = P / total_dt if total_dt != 0 and P != 0 else float("nan")

        self._table.setItem(total_row, 0, QTableWidgetItem("ИТОГО"))
        self._table.setItem(total_row, 1, QTableWidgetItem(f"{t_first:.4f}"))
        self._table.setItem(total_row, 2, QTableWidgetItem(f"{t_last:.4f}"))
        self._table.setItem(total_row, 3, QTableWidgetItem(f"{total_dt:.4f}"))
        self._table.setItem(total_row, 4, QTableWidgetItem(
            f"{total_r:.4g}" if math.isfinite(total_r) else "—"))
        self._table.setItem(total_row, 5, QTableWidgetItem(
            f"{total_G:.4g}" if math.isfinite(total_G) else "—"))

        # Bold total row
        bold_font = QFont()
        bold_font.setBold(True)
        for col in range(6):
            item = self._table.item(total_row, col)
            if item:
                item.setFont(bold_font)

    def _update_stability(self) -> None:
        if not self._chain:
            self._stability_label.setText("Стабильность: —")
            self._stability_label.setStyleSheet("color: #888888;")
            return

        stable = True
        max_rate = 0.0

        for ch in self._chain:
            buf = self._rate_buffers.get(ch)
            if not buf or len(buf) < 10:
                self._stability_label.setText("Стабильность: сбор данных...")
                self._stability_label.setStyleSheet("color: #888888;")
                return

            # dT/dt за последнюю минуту (К/мин)
            t0, v0 = buf[0]
            t1, v1 = buf[-1]
            dt_s = t1 - t0
            if dt_s > 0:
                rate = abs(v1 - v0) / (dt_s / 60.0)
                max_rate = max(max_rate, rate)
                if rate > _STABILITY_THRESHOLD:
                    stable = False

        if stable:
            self._stability_label.setText(f"Стабильно (dT/dt < {max_rate:.4f} К/мин)")
            self._stability_label.setStyleSheet("color: #2ECC40; font-weight: bold;")
        else:
            self._stability_label.setText(f"Нестабильно (dT/dt = {max_rate:.3f} К/мин)")
            self._stability_label.setStyleSheet("color: #FFDC00; font-weight: bold;")

    def _update_plot(self) -> None:
        now = time.time()
        x_min = now - _WINDOW_S
        for ch, item in self._plot_items.items():
            buf = self._buffers.get(ch)
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            item.setData(xs, ys)
        if self._plot_items:
            self._plot.getPlotItem().setXRange(x_min, now, padding=0)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @Slot()
    def _on_export(self) -> None:
        if len(self._chain) < 2:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт теплопроводности", "", "CSV файлы (*.csv)",
        )
        if not path:
            return

        now = datetime.now(timezone.utc)
        P = self._power

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            # Header
            w.writerow(["timestamp", "P_W"] + [f"T_{ch}_K" for ch in self._chain]
                       + ["pair", "dT_K", "R_KW", "G_WK"])
            # Data rows per pair
            for hot_ch, cold_ch in zip(self._chain[:-1], self._chain[1:]):
                t_hot = self._temps.get(hot_ch, float("nan"))
                t_cold = self._temps.get(cold_ch, float("nan"))
                dt = t_hot - t_cold
                R = dt / P if P != 0 else float("nan")
                G = P / dt if dt != 0 else float("nan")

                t_values = [self._temps.get(ch, float("nan")) for ch in self._chain]
                w.writerow(
                    [now.isoformat(), P] + t_values
                    + [f"{hot_ch} → {cold_ch}", dt, R, G]
                )

        logger.info("Теплопроводность экспортирована: %s", path)
