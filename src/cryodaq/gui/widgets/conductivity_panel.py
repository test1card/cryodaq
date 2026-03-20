"""Панель измерения теплопроводности с предсказанием стационара.

Позволяет выбрать цепочку температурных датчиков, отображает R и G
между соседними парами, прогнозирует стационарные значения T∞
и показывает степень стабилизации (percent_settled).

Включает встроенное автоизмерение (развёртка мощности Keithley).
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
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    apply_button_style,
    apply_group_box_style,
    apply_status_label_style,
    build_action_row,
    create_panel_root,
)
from cryodaq.gui.zmq_client import send_command

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600

_STABILITY_THRESHOLD = 0.01

def _get_temperature_channels() -> list[str]:
    """Динамический список видимых температурных каналов через ChannelManager."""
    mgr = get_channel_manager()
    return [
        mgr.get_display_name(ch_id)
        for ch_id in mgr.get_all_visible()
        if ch_id.startswith("Т")
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
        self._pred_lines: dict[str, pg.PlotDataItem] = {}
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}

        # Предсказатель стационара
        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=10.0)

        # Авто-развёртка state
        self._auto_state: str = "idle"  # "idle" / "stabilizing" / "done"
        self._auto_power_list: list[float] = []
        self._auto_step: int = 0
        self._auto_step_start: float = 0.0
        self._auto_results: list[dict] = []

        self._all_channels = _get_temperature_channels()

        # Flight recorder
        self._flight_log = None
        self._flight_log_writer = None

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        # Авто-развёртка timer (1 s tick)
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(1000)
        self._auto_timer.timeout.connect(self._auto_tick)

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

        # --- Левая панель (splitter: ручные контролы / автоизмерение) ---
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.setFixedWidth(240)

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)

        # --- Верхняя секция: выбор датчиков + ручные контролы ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)

        t = QLabel("Выбор датчиков")
        t.setFont(title_font)
        apply_status_label_style(t, "accent", bold=True)
        top_layout.addWidget(t)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        ch_container = QWidget()
        ch_container.setStyleSheet("background: transparent;")
        ch_layout = QVBoxLayout(ch_container)
        ch_layout.setContentsMargins(4, 4, 4, 4)
        ch_layout.setSpacing(2)

        for ch_name in self._all_channels:
            cb = QCheckBox(ch_name)
            cb.stateChanged.connect(lambda state, n=ch_name: self._on_check(n, state))
            self._checkboxes[ch_name] = cb
            ch_layout.addWidget(cb)

        ch_layout.addStretch()
        scroll.setWidget(ch_container)
        top_layout.addWidget(scroll, stretch=1)

        src_lbl = QLabel("Источник P:")
        apply_status_label_style(src_lbl, "info")
        top_layout.addWidget(src_lbl)

        self._power_combo = QComboBox()
        self._power_combo.addItems([
            "Keithley_1/smua/power", "Keithley_1/smub/power",
        ])
        self._power_combo.currentTextChanged.connect(self._on_power_changed)
        self._power_channel = self._power_combo.currentText()
        top_layout.addWidget(self._power_combo)

        up_btn = QPushButton("Вверх")
        apply_button_style(up_btn, "neutral", compact=True)
        up_btn.clicked.connect(self._on_move_up)

        down_btn = QPushButton("Вниз")
        apply_button_style(down_btn, "neutral", compact=True)
        down_btn.clicked.connect(self._on_move_down)
        top_layout.addLayout(build_action_row(up_btn, down_btn))

        export_btn = QPushButton("Экспорт CSV")
        apply_button_style(export_btn, "primary")
        export_btn.clicked.connect(self._on_export)
        top_layout.addWidget(export_btn)

        left_splitter.addWidget(top_widget)

        # --- Нижняя секция: Автоизмерение ---
        auto_box = QGroupBox("Автоизмерение")
        auto_box.setCheckable(True)
        auto_box.setChecked(False)
        apply_group_box_style(auto_box, "#f0883e")
        auto_layout = QGridLayout(auto_box)

        auto_layout.addWidget(QLabel("Начальная P:"), 0, 0)
        self._power_start_spin = QDoubleSpinBox()
        self._power_start_spin.setRange(0.0001, 10.0)
        self._power_start_spin.setValue(0.001)
        self._power_start_spin.setDecimals(4)
        self._power_start_spin.setSuffix(" Вт")
        self._power_start_spin.setSingleStep(0.001)
        auto_layout.addWidget(self._power_start_spin, 0, 1)

        auto_layout.addWidget(QLabel("Шаг P:"), 1, 0)
        self._power_step_spin = QDoubleSpinBox()
        self._power_step_spin.setRange(0.0001, 10.0)
        self._power_step_spin.setValue(0.005)
        self._power_step_spin.setDecimals(4)
        self._power_step_spin.setSuffix(" Вт")
        self._power_step_spin.setSingleStep(0.001)
        auto_layout.addWidget(self._power_step_spin, 1, 1)

        auto_layout.addWidget(QLabel("Кол-во шагов:"), 2, 0)
        self._power_count_spin = QSpinBox()
        self._power_count_spin.setRange(2, 100)
        self._power_count_spin.setValue(10)
        auto_layout.addWidget(self._power_count_spin, 2, 1)

        self._power_preview = QLabel("")
        self._power_preview.setStyleSheet("color: #8b949e; font-size: 9pt;")
        self._power_preview.setWordWrap(True)
        auto_layout.addWidget(self._power_preview, 3, 0, 1, 2)

        self._power_start_spin.valueChanged.connect(self._update_power_preview)
        self._power_step_spin.valueChanged.connect(self._update_power_preview)
        self._power_count_spin.valueChanged.connect(self._update_power_preview)

        auto_layout.addWidget(QLabel("Стабилизация:"), 4, 0)
        self._settled_pct_spin = QDoubleSpinBox()
        self._settled_pct_spin.setRange(80.0, 99.9)
        self._settled_pct_spin.setValue(95.0)
        self._settled_pct_spin.setDecimals(1)
        self._settled_pct_spin.setSuffix(" %")
        self._settled_pct_spin.setToolTip(
            "Процент стабилизации по экстраполяции SteadyState.\n"
            "95% = температура в пределах 5% от предсказанного стационара."
        )
        auto_layout.addWidget(self._settled_pct_spin, 4, 1)

        auto_layout.addWidget(QLabel("Мин. ожидание:"), 5, 0)
        self._min_wait_spin = QDoubleSpinBox()
        self._min_wait_spin.setRange(10, 600)
        self._min_wait_spin.setValue(30)
        self._min_wait_spin.setSuffix(" с")
        self._min_wait_spin.setToolTip("Минимальное время перед проверкой стабилизации")
        auto_layout.addWidget(self._min_wait_spin, 5, 1)

        btn_row = QHBoxLayout()
        self._auto_start_btn = QPushButton("Старт")
        apply_button_style(self._auto_start_btn, "primary")
        self._auto_start_btn.clicked.connect(self._on_auto_start)
        btn_row.addWidget(self._auto_start_btn)

        self._auto_stop_btn = QPushButton("Стоп")
        apply_button_style(self._auto_stop_btn, "neutral")
        self._auto_stop_btn.setEnabled(False)
        self._auto_stop_btn.clicked.connect(self._on_auto_stop)
        btn_row.addWidget(self._auto_stop_btn)
        auto_layout.addLayout(btn_row, 6, 0, 1, 2)

        self._auto_progress = QProgressBar()
        self._auto_progress.setRange(0, 100)
        self._auto_progress.setValue(0)
        self._auto_progress.setVisible(False)
        auto_layout.addWidget(self._auto_progress, 7, 0, 1, 2)

        self._auto_status_label = QLabel("")
        apply_status_label_style(self._auto_status_label, "muted")
        auto_layout.addWidget(self._auto_status_label, 8, 0, 1, 2)

        self._update_power_preview()

        left_splitter.addWidget(auto_box)

        # 60% manual, 40% auto
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)

        root.addWidget(left_splitter)

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
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._plot.setBackground("#111111")

        # Empty state overlay
        from PySide6.QtWidgets import QLabel as _Label
        self._empty_overlay = _Label("Нет данных для теплопроводности.\nНачните эксперимент.", self._plot)
        self._empty_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_overlay.setStyleSheet("color: #666666; font-size: 14pt; background: transparent;")
        self._empty_overlay.setGeometry(0, 0, 400, 100)

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
        if self._empty_overlay.isVisible():
            self._empty_overlay.setVisible(False)

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
        self._update_plot()
        self._power_label.setText(f"P = {self._power:.6g} Вт")
        self._write_flight_log(now, all_preds)

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

            if self._is_good_pred(p_hot) and self._is_good_pred(p_cold):
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

    def _is_good_pred(self, p) -> bool:
        """Check if prediction is physically meaningful for display."""
        return (p is not None and p.valid
                and p.confidence > 0.5
                and p.t_predicted > 0
                and abs(p.t_predicted - p.t_current) < 50.0)

    def _update_pred_lines(self, preds: dict) -> None:
        """Clear prediction curves — steady-state chart doesn't need forecast."""
        for ch in list(self._pred_lines.keys()):
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
        """Update plot: full history + 25% extrapolation zone."""
        now = time.time()

        t_start = now
        for ch in self._chain:
            buf = self._buffers.get(ch)
            if buf and len(buf) > 0:
                t_start = min(t_start, buf[0][0])

        for ch, item in self._plot_items.items():
            buf = self._buffers.get(ch)
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf]
            ys = [v for t, v in buf]
            item.setData(xs, ys)

        if self._plot_items and t_start < now:
            forecast_s = (now - t_start) / 3.0
            self._plot.getPlotItem().setXRange(t_start, now + forecast_s, padding=0.02)

    # ------------------------------------------------------------------
    # Auto-sweep (Автоизмерение)
    # ------------------------------------------------------------------

    def _generate_power_list(self) -> list[float]:
        """Generate power list from start/step/count."""
        start = self._power_start_spin.value()
        step = self._power_step_spin.value()
        count = self._power_count_spin.value()
        return [round(start + i * step, 6) for i in range(count)]

    def _update_power_preview(self) -> None:
        """Show generated power list in preview label."""
        powers = self._generate_power_list()
        if len(powers) <= 6:
            text = ", ".join(f"{p:.4g}" for p in powers)
        else:
            first3 = ", ".join(f"{p:.4g}" for p in powers[:3])
            text = f"{first3}, ... , {powers[-1]:.4g}  ({len(powers)} шагов)"
        self._power_preview.setText(text)

    @Slot()
    def _on_auto_start(self) -> None:
        """Запуск автоматической развёртки по мощности."""
        if len(self._chain) < 2:
            QMessageBox.warning(self, "Ошибка", "Выберите минимум 2 датчика в цепочке.")
            return

        powers = self._generate_power_list()
        if not powers:
            QMessageBox.warning(self, "Ошибка", "Список мощностей пуст.")
            return

        self._auto_power_list = powers
        self._auto_step = 0
        self._auto_results = []
        self._auto_state = "stabilizing"

        # UI
        self._auto_start_btn.setEnabled(False)
        self._auto_stop_btn.setEnabled(True)
        self._auto_progress.setVisible(True)
        self._auto_progress.setValue(0)
        self._auto_status_label.setText(
            f"Шаг 1/{len(powers)} — P = {powers[0]:.4g} Вт"
        )
        apply_status_label_style(self._auto_status_label, "info")

        # Send first power command
        self._auto_step_start = time.monotonic()
        send_command({
            "cmd": "keithley_set_target",
            "channel": "smua",
            "p_target": powers[0],
        })
        logger.info("Автоизмерение: старт, %d шагов, P=%s", len(powers), powers)

        self._auto_timer.start()

    @Slot()
    def _on_auto_stop(self) -> None:
        """Прервать автоизмерение."""
        self._auto_state = "idle"
        self._auto_timer.stop()
        send_command({"cmd": "keithley_stop", "channel": "smua"})

        self._auto_start_btn.setEnabled(True)
        self._auto_stop_btn.setEnabled(False)
        self._auto_progress.setVisible(False)
        self._auto_status_label.setText("Остановлено оператором")
        apply_status_label_style(self._auto_status_label, "warning")
        logger.info("Автоизмерение: остановлено оператором")

    @Slot()
    def _auto_tick(self) -> None:
        """Check stabilization using SteadyStatePredictor's percent_settled."""
        if self._auto_state != "stabilizing":
            return

        elapsed = time.monotonic() - self._auto_step_start
        step_total = len(self._auto_power_list)
        step_idx = self._auto_step
        P = self._auto_power_list[step_idx]

        # Collect percent_settled for all chain channels
        settled_values: list[float] = []
        for ch in self._chain:
            pred = self._predictor.get_prediction(ch)
            if pred is not None and pred.valid:
                settled_values.append(pred.percent_settled)
            else:
                settled_values.append(0.0)

        min_settled = min(settled_values) if settled_values else 0.0

        # Check stabilization:
        # 1. Minimum wait time elapsed (avoid false positive from initial transient)
        # 2. All channels above threshold percent_settled
        threshold = self._settled_pct_spin.value()
        min_wait = self._min_wait_spin.value()
        is_stable = elapsed >= min_wait and min_settled >= threshold

        # Progress bar
        step_progress = min(min_settled / threshold, 1.0) if threshold > 0 else 1.0
        pct = int(((step_idx + step_progress) / step_total) * 100)
        self._auto_progress.setValue(min(pct, 99))

        # Status label with live percent_settled
        settled_str = " / ".join(f"{s:.0f}%" for s in settled_values[:4])
        self._auto_status_label.setText(
            f"Шаг {step_idx + 1}/{step_total} — "
            f"P = {P:.4g} Вт — {elapsed:.0f} с — "
            f"стабил.: {settled_str}"
        )

        if is_stable:
            self._auto_record_point()
            self._auto_step += 1
            if self._auto_step >= step_total:
                self._auto_complete()
            else:
                next_p = self._auto_power_list[self._auto_step]
                self._auto_step_start = time.monotonic()
                send_command({
                    "cmd": "keithley_set_target",
                    "channel": "smua",
                    "p_target": next_p,
                })
                logger.info(
                    "Автоизмерение: шаг %d/%d, P=%.4g Вт",
                    self._auto_step + 1, step_total, next_p,
                )

    def _auto_record_point(self) -> None:
        """Записать текущие R/G для данного шага."""
        P = self._auto_power_list[self._auto_step]
        if len(self._chain) < 2:
            return

        hot_ch = self._chain[0]
        cold_ch = self._chain[-1]
        T_hot = self._temps.get(hot_ch, float("nan"))
        T_cold = self._temps.get(cold_ch, float("nan"))
        dT = T_hot - T_cold
        R = dT / P if P != 0 and math.isfinite(dT) else float("nan")
        G = P / dT if dT != 0 and math.isfinite(dT) else float("nan")

        settled_values = []
        for ch in self._chain:
            pred = self._predictor.get_prediction(ch)
            if pred and pred.valid:
                settled_values.append(pred.percent_settled)
        min_settled = min(settled_values) if settled_values else 0.0

        self._auto_results.append({
            "P": P, "T_hot": T_hot, "T_cold": T_cold,
            "dT": dT, "R": R, "G": G, "settled_pct": min_settled,
        })
        logger.info(
            "Автоизмерение: точка P=%.4g, dT=%.4f, R=%.4g, G=%.4g, settled=%.0f%%",
            P, dT, R, G, min_settled,
        )

    def _auto_complete(self) -> None:
        """Завершить развёртку."""
        self._auto_state = "done"
        self._auto_timer.stop()
        send_command({"cmd": "keithley_stop", "channel": "smua"})

        self._auto_start_btn.setEnabled(True)
        self._auto_stop_btn.setEnabled(False)
        self._auto_progress.setValue(100)

        n = len(self._auto_results)
        self._auto_status_label.setText(f"Завершено: {n} точек измерено")
        apply_status_label_style(self._auto_status_label, "success", bold=True)
        logger.info("Автоизмерение: завершено, %d точек", n)

        if self._auto_results:
            summary_lines = ["Автоизмерение завершено:\n"]
            for r in self._auto_results:
                summary_lines.append(
                    f"  P={r['P']:.4g} Вт  dT={r['dT']:.4f} К  "
                    f"R={r['R']:.4g} К/Вт  G={r['G']:.4g} Вт/К"
                )
            QMessageBox.information(self, "Автоизмерение", "\n".join(summary_lines))

    # ------------------------------------------------------------------
    # Flight recorder
    # ------------------------------------------------------------------

    def _write_flight_log(self, now: float, preds: dict) -> None:
        """Append one row to the conductivity flight log CSV."""
        if not self._chain or len(self._chain) < 2:
            return

        if self._flight_log is None:
            from cryodaq.paths import get_data_dir
            log_dir = get_data_dir() / "conductivity_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            log_path = log_dir / f"conductivity_{ts_str}.csv"
            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
            self._flight_log_writer = csv.writer(self._flight_log)
            self._flight_log_writer.writerow([
                "timestamp_utc", "elapsed_s",
                "T_hot", "T_cold", "dT", "P",
                "R_measured", "G_measured",
                "R_predicted", "G_predicted",
                "percent_settled_hot", "percent_settled_cold",
                "tau_hot_s", "tau_cold_s",
                "T_inf_hot", "T_inf_cold",
                "auto_sweep_step", "auto_sweep_power",
            ])

        hot_ch = self._chain[0]
        cold_ch = self._chain[-1]
        T_hot = self._temps.get(hot_ch, float("nan"))
        T_cold = self._temps.get(cold_ch, float("nan"))
        dT = T_hot - T_cold
        P = self._power

        R = dT / P if P != 0 and math.isfinite(dT) else float("nan")
        G = P / dT if dT != 0 and math.isfinite(dT) else float("nan")

        p_hot = preds.get(hot_ch)
        p_cold = preds.get(cold_ch)
        R_pred = G_pred = float("nan")
        pct_hot = pct_cold = 0.0
        tau_hot = tau_cold = T_inf_hot = T_inf_cold = float("nan")

        if p_hot and p_hot.valid:
            pct_hot = p_hot.percent_settled
            tau_hot = p_hot.tau_s
            T_inf_hot = p_hot.t_predicted
        if p_cold and p_cold.valid:
            pct_cold = p_cold.percent_settled
            tau_cold = p_cold.tau_s
            T_inf_cold = p_cold.t_predicted

        if self._is_good_pred(p_hot) and self._is_good_pred(p_cold):
            dt_pred = T_inf_hot - T_inf_cold
            if P != 0 and math.isfinite(dt_pred) and dt_pred != 0:
                R_pred = dt_pred / P
                G_pred = P / dt_pred

        step = self._auto_step if self._auto_state == "stabilizing" else -1
        step_P = (self._auto_power_list[self._auto_step]
                  if self._auto_state == "stabilizing" and self._auto_step < len(self._auto_power_list)
                  else 0)

        elapsed = now - self._buffers[hot_ch][0][0] if self._buffers.get(hot_ch) else 0

        self._flight_log_writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            f"{elapsed:.1f}",
            f"{T_hot:.6f}", f"{T_cold:.6f}", f"{dT:.6f}", f"{P:.6g}",
            f"{R:.6g}", f"{G:.6g}",
            f"{R_pred:.6g}", f"{G_pred:.6g}",
            f"{pct_hot:.1f}", f"{pct_cold:.1f}",
            f"{tau_hot:.1f}", f"{tau_cold:.1f}",
            f"{T_inf_hot:.6f}", f"{T_inf_cold:.6f}",
            step, f"{step_P:.6g}",
        ])
        self._flight_log.flush()

    def closeEvent(self, event) -> None:
        if self._flight_log:
            self._flight_log.close()
            self._flight_log = None
        super().closeEvent(event)

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
