"""Панель измерения теплопроводности с предсказанием стационара.

Позволяет выбрать цепочку температурных датчиков, отображает R и G
между соседними парами, прогнозирует стационарные значения T∞
и показывает степень стабилизации (percent_settled).
"""

from __future__ import annotations

import csv
import logging
import math
import time
from collections import deque
from datetime import datetime, timezone

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    apply_button_style,
    apply_status_label_style,
    build_action_row,
    create_panel_root,
)

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0
_STABILITY_THRESHOLD = 0.01

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

_COL_HEADERS = [
    "Пара", "T гор. (К)", "T хол. (К)", "dT (К)", "R (К/Вт)", "G (Вт/К)",
    "T∞ прогноз", "τ (мин)", "Готово %", "R прогноз", "G прогноз",
]


def _pct_color(pct: float) -> str:
    if pct >= 99.0:
        return "#2ECC40"
    if pct >= 90.0:
        return "#FFDC00"
    return "#FF4136"


class ConductivityPanel(QWidget):
    """Панель измерения теплопроводности с предсказанием стационара."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._temps: dict[str, float] = {}
        self._power: float = 0.0
        self._power_channel: str = ""
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._chain: list[str] = []
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._pred_lines: dict[str, pg.InfiniteLine] = {}
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}

        # Предсказатель стационара
        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=10.0)

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        outer = create_panel_root(self)
        outer.addWidget(
            PanelHeader(
                "Теплопроводность",
                "Оценка R и G по выбранной цепочке датчиков с прогнозом стационарных значений.",
            )
        )
        root = QHBoxLayout()
        root.setSpacing(8)

        # --- Левая панель ---
        left = QVBoxLayout()
        left.setSpacing(6)

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)

        t = QLabel("Выбор датчиков")
        t.setFont(title_font)
        apply_status_label_style(t, "accent", bold=True)
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
            cb.stateChanged.connect(lambda state, n=ch_name: self._on_check(n, state))
            self._checkboxes[ch_name] = cb
            ch_layout.addWidget(cb)

        ch_layout.addStretch()
        scroll.setWidget(ch_container)
        left.addWidget(scroll, stretch=1)

        src_lbl = QLabel("Источник P:")
        apply_status_label_style(src_lbl, "info")
        left.addWidget(src_lbl)

        self._power_combo = QComboBox()
        self._power_combo.addItems([
            "Keithley_1/smua/power", "Keithley_1/smub/power",
        ])
        self._power_combo.currentTextChanged.connect(self._on_power_changed)
        self._power_channel = self._power_combo.currentText()
        left.addWidget(self._power_combo)

        up_btn = QPushButton("Вверх")
        apply_button_style(up_btn, "neutral", compact=True)
        up_btn.clicked.connect(self._on_move_up)

        down_btn = QPushButton("Вниз")
        apply_button_style(down_btn, "neutral", compact=True)
        down_btn.clicked.connect(self._on_move_down)
        left.addLayout(build_action_row(up_btn, down_btn))

        export_btn = QPushButton("Экспорт CSV")
        apply_button_style(export_btn, "primary")
        export_btn.clicked.connect(self._on_export)
        left.addWidget(export_btn)

        root.addLayout(left)

        # --- Правая панель ---
        right = QVBoxLayout()
        right.setSpacing(8)

        # Баннер стационара
        self._banner = StatusBanner()
        self._banner.setFont(QFont("", 11, QFont.Weight.Bold))
        self._banner.setAlignment(Qt.AlignCenter)
        self._banner.show_info(" ")
        right.addWidget(self._banner)

        # Индикаторы
        stab_row = QHBoxLayout()
        self._stability_label = QLabel("Стабильность: —")
        self._stability_label.setFont(title_font)
        apply_status_label_style(self._stability_label, "muted")
        stab_row.addWidget(self._stability_label)

        self._power_label = QLabel("P = — Вт")
        self._power_label.setFont(title_font)
        apply_status_label_style(self._power_label, "warning", bold=True)
        stab_row.addWidget(self._power_label)
        stab_row.addStretch()
        right.addLayout(stab_row)

        # Таблица R и G + прогноз
        self._table = QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMaximumHeight(280)
        right.addWidget(self._table)

        # График
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
        outer.addLayout(root, 1)

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
                idx = len(self._plot_items)
                color = _LINE_COLORS[idx % len(_LINE_COLORS)]
                item = self._plot.plot([], [], pen=pg.mkPen(color=color, width=2), name=ch_name)
                self._plot_items[ch_name] = item
        else:
            if ch_name in self._chain:
                self._chain.remove(ch_name)
            if ch_name in self._plot_items:
                self._plot.removeItem(self._plot_items.pop(ch_name))
            if ch_name in self._pred_lines:
                self._plot.removeItem(self._pred_lines.pop(ch_name))

    def _on_move_up(self) -> None:
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
        ts = reading.timestamp.timestamp()

        if ch in self._checkboxes and reading.unit == "K":
            self._temps[ch] = reading.value
            if ch in self._buffers:
                self._buffers[ch].append((ts, reading.value))
                self._rate_buffers[ch].append((ts, reading.value))
            # Кормить предсказатель
            self._predictor.add_point(ch, ts, reading.value)

        if ch == self._power_channel:
            self._power = reading.value

    # ------------------------------------------------------------------
    # Periodic refresh
    # ------------------------------------------------------------------

    @Slot()
    def _refresh(self) -> None:
        now = time.time()
        preds = self._predictor.update(now)
        all_preds = self._predictor.get_all_predictions()

        self._update_table(all_preds)
        self._update_stability()
        self._update_banner(all_preds)
        self._update_pred_lines(all_preds)
        self._update_plot()
        self._power_label.setText(f"P = {self._power:.6g} Вт")

    def _update_table(self, preds: dict) -> None:
        if len(self._chain) < 2:
            self._table.setRowCount(0)
            return

        pairs = list(zip(self._chain[:-1], self._chain[1:]))
        self._table.setRowCount(len(pairs) + 1)

        total_r = 0.0
        total_r_pred = 0.0
        P = self._power

        for row, (hot_ch, cold_ch) in enumerate(pairs):
            t_hot = self._temps.get(hot_ch, float("nan"))
            t_cold = self._temps.get(cold_ch, float("nan"))
            dt = t_hot - t_cold

            R = dt / P if P != 0 and math.isfinite(dt) else float("nan")
            G = P / dt if dt != 0 and P != 0 else float("nan")
            if math.isfinite(R):
                total_r += R

            # Прогноз
            p_hot = preds.get(hot_ch)
            p_cold = preds.get(cold_ch)

            t_inf_str = ""
            tau_str = ""
            pct_str = ""
            r_pred_str = "—"
            g_pred_str = "—"
            pct_val = 0.0

            if p_hot and p_hot.valid and p_cold and p_cold.valid:
                t_inf_hot = p_hot.t_predicted
                t_inf_cold = p_cold.t_predicted
                dt_inf = t_inf_hot - t_inf_cold
                t_inf_str = f"{t_inf_hot:.3f} / {t_inf_cold:.3f}"
                tau_avg = (p_hot.tau_s + p_cold.tau_s) / 2
                tau_str = f"{tau_avg / 60:.1f}"
                pct_val = min(p_hot.percent_settled, p_cold.percent_settled)
                pct_str = f"{pct_val:.0f}%"

                if P != 0 and abs(dt_inf) > 1e-10:
                    r_pred = dt_inf / P
                    g_pred = P / dt_inf
                    r_pred_str = f"{r_pred:.4g}"
                    g_pred_str = f"{g_pred:.4g}"
                    if math.isfinite(r_pred):
                        total_r_pred += r_pred

            self._table.setItem(row, 0, QTableWidgetItem(f"{hot_ch} → {cold_ch}"))
            self._table.setItem(row, 1, QTableWidgetItem(f"{t_hot:.4f}"))
            self._table.setItem(row, 2, QTableWidgetItem(f"{t_cold:.4f}"))
            self._table.setItem(row, 3, QTableWidgetItem(f"{dt:.4f}" if math.isfinite(dt) else "—"))
            self._table.setItem(row, 4, QTableWidgetItem(f"{R:.4g}" if math.isfinite(R) else "—"))
            self._table.setItem(row, 5, QTableWidgetItem(f"{G:.4g}" if math.isfinite(G) else "—"))
            self._table.setItem(row, 6, QTableWidgetItem(t_inf_str))
            self._table.setItem(row, 7, QTableWidgetItem(tau_str))

            pct_item = QTableWidgetItem(pct_str)
            if pct_str:
                pct_item.setForeground(QColor(_pct_color(pct_val)))
            self._table.setItem(row, 8, pct_item)
            self._table.setItem(row, 9, QTableWidgetItem(r_pred_str))
            self._table.setItem(row, 10, QTableWidgetItem(g_pred_str))

        # Total row
        total_row = len(pairs)
        t_first = self._temps.get(self._chain[0], float("nan"))
        t_last = self._temps.get(self._chain[-1], float("nan"))
        total_dt = t_first - t_last
        total_G = P / total_dt if total_dt != 0 and P != 0 else float("nan")
        total_G_pred = P / (total_r_pred * P) if total_r_pred != 0 and P != 0 else float("nan")

        self._table.setItem(total_row, 0, QTableWidgetItem("ИТОГО"))
        self._table.setItem(total_row, 1, QTableWidgetItem(f"{t_first:.4f}" if math.isfinite(t_first) else "—"))
        self._table.setItem(total_row, 2, QTableWidgetItem(f"{t_last:.4f}" if math.isfinite(t_last) else "—"))
        self._table.setItem(total_row, 3, QTableWidgetItem(f"{total_dt:.4f}" if math.isfinite(total_dt) else "—"))
        self._table.setItem(total_row, 4, QTableWidgetItem(f"{total_r:.4g}" if math.isfinite(total_r) and total_r != 0 else "—"))
        self._table.setItem(total_row, 5, QTableWidgetItem(f"{total_G:.4g}" if math.isfinite(total_G) else "—"))
        self._table.setItem(total_row, 9, QTableWidgetItem(f"{total_r_pred:.4g}" if total_r_pred != 0 else "—"))
        self._table.setItem(total_row, 10, QTableWidgetItem(f"{total_G_pred:.4g}" if math.isfinite(total_G_pred) else "—"))

        bold_font = QFont()
        bold_font.setBold(True)
        for col in range(len(_COL_HEADERS)):
            item = self._table.item(total_row, col)
            if item:
                item.setFont(bold_font)

    def _update_banner(self, preds: dict) -> None:
        if len(self._chain) < 2:
            self._banner.setText("")
            self._banner.clear_message()
            return

        valid_preds = [preds.get(ch) for ch in self._chain if preds.get(ch) and preds[ch].valid]
        if not valid_preds:
            self._banner.show_info("Прогноз: сбор данных...")
            return

        min_pct = min(p.percent_settled for p in valid_preds)
        max_tau = max(p.tau_s for p in valid_preds) if valid_preds else 0

        if min_pct >= 99.0:
            self._banner.show_success("ГОТОВО — стационар достигнут")
        elif min_pct >= 95.0:
            remaining = max_tau * math.log(100.0 / max(100.0 - min_pct, 0.1)) / 60.0
            self._banner.show_warning(
                f"Стабилизация {min_pct:.0f}% — ещё ~{remaining:.0f} мин"
            )
        else:
            remaining = max_tau * math.log(100.0 / max(100.0 - min_pct, 0.1)) / 60.0
            self._banner.show_info(
                f"Стабилизация {min_pct:.0f}% — прогноз ~{remaining:.0f} мин"
            )

    def _update_pred_lines(self, preds: dict) -> None:
        """Обновить горизонтальные пунктирные линии T∞ на графике."""
        for ch in self._chain:
            p = preds.get(ch)
            if p and p.valid and p.t_predicted != 0:
                if ch not in self._pred_lines:
                    idx = list(self._plot_items.keys()).index(ch) if ch in self._plot_items else 0
                    color = _LINE_COLORS[idx % len(_LINE_COLORS)]
                    line = pg.InfiniteLine(
                        pos=p.t_predicted, angle=0,
                        pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine),
                    )
                    self._plot.addItem(line)
                    self._pred_lines[ch] = line
                else:
                    self._pred_lines[ch].setValue(p.t_predicted)

        # Удалить линии для каналов, которых нет в цепочке
        for ch in list(self._pred_lines.keys()):
            if ch not in self._chain:
                self._plot.removeItem(self._pred_lines.pop(ch))

    def _update_stability(self) -> None:
        if not self._chain:
            self._stability_label.setText("Стабильность: —")
            apply_status_label_style(self._stability_label, "muted")
            return

        stable = True
        max_rate = 0.0

        for ch in self._chain:
            buf = self._rate_buffers.get(ch)
            if not buf or len(buf) < 10:
                self._stability_label.setText("Стабильность: сбор данных...")
                apply_status_label_style(self._stability_label, "muted")
                return

            t0, v0 = buf[0]
            t1, v1 = buf[-1]
            dt_s = t1 - t0
            if dt_s > 0:
                rate = abs(v1 - v0) / (dt_s / 60.0)
                max_rate = max(max_rate, rate)
                if rate > _STABILITY_THRESHOLD:
                    stable = False

        if stable:
            self._stability_label.setText(f"Стабильно (dT/dt = {max_rate:.4f} К/мин)")
            apply_status_label_style(self._stability_label, "success", bold=True)
        else:
            self._stability_label.setText(f"Нестабильно (dT/dt = {max_rate:.3f} К/мин)")
            apply_status_label_style(self._stability_label, "warning", bold=True)

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
        preds = self._predictor.get_all_predictions()

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp", "P_W",
                *[f"T_{ch}_K" for ch in self._chain],
                "pair", "dT_K", "R_KW", "G_WK",
                "T_inf_hot", "T_inf_cold", "R_pred", "G_pred", "settled_%",
            ])

            for hot_ch, cold_ch in zip(self._chain[:-1], self._chain[1:]):
                t_hot = self._temps.get(hot_ch, float("nan"))
                t_cold = self._temps.get(cold_ch, float("nan"))
                dt = t_hot - t_cold
                R = dt / P if P != 0 else float("nan")
                G = P / dt if dt != 0 else float("nan")
                t_values = [self._temps.get(ch, float("nan")) for ch in self._chain]

                # Prediction data
                p_hot = preds.get(hot_ch)
                p_cold = preds.get(cold_ch)
                t_inf_hot = p_hot.t_predicted if p_hot and p_hot.valid else float("nan")
                t_inf_cold = p_cold.t_predicted if p_cold and p_cold.valid else float("nan")
                dt_inf = t_inf_hot - t_inf_cold
                r_pred = dt_inf / P if P != 0 and math.isfinite(dt_inf) else float("nan")
                g_pred = P / dt_inf if dt_inf != 0 and P != 0 else float("nan")
                settled = min(
                    p_hot.percent_settled if p_hot and p_hot.valid else 0,
                    p_cold.percent_settled if p_cold and p_cold.valid else 0,
                )

                w.writerow([
                    now.isoformat(), P, *t_values,
                    f"{hot_ch} → {cold_ch}", dt, R, G,
                    t_inf_hot, t_inf_cold, r_pred, g_pred, settled,
                ])

        logger.info("Теплопроводность экспортирована: %s", path)
