"""Панель автоматического развёртывания по мощности.

Последовательно задаёт мощности на Keithley, ждёт стабилизации
температур, записывает R(P) и G(P), строит итоговый график.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

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
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.common import (
    PanelHeader,
    apply_button_style,
    apply_group_box_style,
    apply_status_label_style,
    create_panel_root,
)
from cryodaq.gui.zmq_client import send_command
from cryodaq.paths import get_data_dir

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 7200
_WINDOW_S = 600.0

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


class AutoSweepPanel(QWidget):
    """Панель автоматического развёртывания по мощности."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # State
        self._running = False
        self._paused = False
        self._power_list: list[float] = []
        self._current_step = 0
        self._step_start_time = 0.0
        self._selected_channels: list[str] = []
        self._smu_channel = "smua"
        self._run_started_at: datetime | None = None
        self._run_finished_at: datetime | None = None

        # Data
        self._temps: dict[str, float] = {}
        self._power: float = 0.0
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=5.0)

        # Results
        self._results: list[dict] = []

        # UI elements stored for access
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_ui(self) -> None:
        outer = create_panel_root(self)
        outer.addWidget(
            PanelHeader(
                "Автоизмерение по мощности",
                "Пошаговая развертка мощности Keithley с ожиданием стабилизации температур.",
            )
        )
        root = QHBoxLayout()
        root.setSpacing(8)

        # --- Левая панель: настройки ---
        left = QVBoxLayout()
        left.setSpacing(6)

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)

        # Метаданные
        meta_box = QGroupBox("Метаданные")
        apply_group_box_style(meta_box, "#58a6ff")
        ml = QGridLayout(meta_box)

        ml.addWidget(QLabel("Образец:"), 0, 0)
        self._sample_edit = QLineEdit()
        self._sample_edit.setPlaceholderText("название образца")
        ml.addWidget(self._sample_edit, 0, 1)

        ml.addWidget(QLabel("Материал:"), 1, 0)
        self._material_edit = QLineEdit()
        self._material_edit.setPlaceholderText("Cu, Al, ...")
        ml.addWidget(self._material_edit, 1, 1)

        ml.addWidget(QLabel("Оператор:"), 2, 0)
        self._operator_edit = QLineEdit()
        ml.addWidget(self._operator_edit, 2, 1)

        left.addWidget(meta_box)

        # Настройка мощности
        power_box = QGroupBox("Мощность")
        apply_group_box_style(power_box, "#f0883e")
        pl = QGridLayout(power_box)

        pl.addWidget(QLabel("Начало (Вт):"), 0, 0)
        self._p_start = QDoubleSpinBox()
        self._p_start.setRange(0.0, 10.0)
        self._p_start.setValue(0.1)
        self._p_start.setDecimals(3)
        self._p_start.setSingleStep(0.1)
        pl.addWidget(self._p_start, 0, 1)

        pl.addWidget(QLabel("Конец (Вт):"), 1, 0)
        self._p_end = QDoubleSpinBox()
        self._p_end.setRange(0.0, 10.0)
        self._p_end.setValue(2.0)
        self._p_end.setDecimals(3)
        self._p_end.setSingleStep(0.1)
        pl.addWidget(self._p_end, 1, 1)

        pl.addWidget(QLabel("Шаг (Вт):"), 2, 0)
        self._p_step = QDoubleSpinBox()
        self._p_step.setRange(0.001, 5.0)
        self._p_step.setValue(0.1)
        self._p_step.setDecimals(3)
        self._p_step.setSingleStep(0.05)
        pl.addWidget(self._p_step, 2, 1)

        pl.addWidget(QLabel("Канал:"), 3, 0)
        self._smu_combo = QComboBox()
        self._smu_combo.addItems(["smua"])
        pl.addWidget(self._smu_combo, 3, 1)

        pl.addWidget(QLabel("Готовность (%):"), 4, 0)
        self._target_pct = QSpinBox()
        self._target_pct.setRange(50, 100)
        self._target_pct.setValue(95)
        pl.addWidget(self._target_pct, 4, 1)

        pl.addWidget(QLabel("Макс. ожидание (мин):"), 5, 0)
        self._max_wait = QSpinBox()
        self._max_wait.setRange(1, 180)
        self._max_wait.setValue(30)
        pl.addWidget(self._max_wait, 5, 1)

        pl.addWidget(QLabel("V пред. (В):"), 6, 0)
        self._v_comp_spin = QDoubleSpinBox()
        self._v_comp_spin.setRange(0.1, 40.0)
        self._v_comp_spin.setValue(10.0)
        self._v_comp_spin.setDecimals(1)
        pl.addWidget(self._v_comp_spin, 6, 1)

        pl.addWidget(QLabel("I пред. (А):"), 7, 0)
        self._i_comp_spin = QDoubleSpinBox()
        self._i_comp_spin.setRange(0.001, 3.0)
        self._i_comp_spin.setValue(0.1)
        self._i_comp_spin.setDecimals(3)
        pl.addWidget(self._i_comp_spin, 7, 1)

        left.addWidget(power_box)

        # Датчики
        sensor_box = QGroupBox("Датчики")
        apply_group_box_style(sensor_box, "#3fb950")
        sl = QVBoxLayout(sensor_box)
        sensor_scroll = QScrollArea()
        sensor_scroll.setWidgetResizable(True)
        sensor_scroll.setMaximumHeight(150)
        sensor_scroll.setStyleSheet("QScrollArea { border: none; }")
        sc = QWidget()
        scl = QVBoxLayout(sc)
        scl.setSpacing(1)
        for ch in _ALL_CHANNELS:
            cb = QCheckBox(ch)
            self._checkboxes[ch] = cb
            scl.addWidget(cb)
        sensor_scroll.setWidget(sc)
        sl.addWidget(sensor_scroll)
        left.addWidget(sensor_box)

        # Кнопки управления
        btn_layout = QHBoxLayout()

        self._start_btn = QPushButton("СТАРТ")
        self._start_btn.setFont(QFont("", 10, QFont.Weight.Bold))
        apply_button_style(self._start_btn, "primary")
        self._start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self._start_btn)

        self._pause_btn = QPushButton("ПАУЗА")
        self._pause_btn.setEnabled(False)
        apply_button_style(self._pause_btn, "warning")
        self._pause_btn.clicked.connect(self._on_pause)
        btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("СТОП")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setFont(QFont("", 10, QFont.Weight.Bold))
        apply_button_style(self._stop_btn, "danger")
        self._stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._stop_btn)

        left.addLayout(btn_layout)
        left.addStretch()

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(280)
        root.addWidget(left_widget)

        # --- Правая панель: прогресс + результаты ---
        right = QVBoxLayout()
        right.setSpacing(8)

        # Прогресс
        self._progress_label = QLabel("Ожидание старта...")
        self._progress_label.setFont(title_font)
        apply_status_label_style(self._progress_label, "info")
        right.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        right.addWidget(self._progress_bar)

        # Таблица результатов
        self._results_table = QTableWidget(0, 7)
        self._results_table.setHorizontalHeaderLabels([
            "P (Вт)", "T гор. (К)", "T хол. (К)", "T ср. (К)",
            "dT (К)", "R (К/Вт)", "G (Вт/К)",
        ])
        self._results_table.setAlternatingRowColors(True)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self._results_table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._results_table.setMaximumHeight(200)
        right.addWidget(self._results_table)

        # График температур (live)
        self._live_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._live_plot.setBackground("#111111")
        pi = self._live_plot.getPlotItem()
        pi.setLabel("left", "Температура", units="К", color="#AAAAAA")
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.enableAutoRange(axis="y", enable=True)
        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#444444"))
                ax.setTextPen(pg.mkPen(color="#AAAAAA"))
        right.addWidget(self._live_plot, stretch=1)

        root.addLayout(right, stretch=1)
        outer.addLayout(root, 1)

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        # Validate
        selected = [ch for ch, cb in self._checkboxes.items() if cb.isChecked()]
        if len(selected) < 2:
            QMessageBox.warning(self, "Ошибка", "Выберите минимум 2 датчика.")
            return

        # Build power list
        p_start = self._p_start.value()
        p_end = self._p_end.value()
        p_step = self._p_step.value()
        if p_step <= 0 or p_start >= p_end:
            QMessageBox.warning(self, "Ошибка", "Некорректные параметры мощности.")
            return

        self._power_list = []
        p = p_start
        while p <= p_end + 1e-9:
            self._power_list.append(round(p, 6))
            p += p_step

        self._selected_channels = selected
        self._smu_channel = self._smu_combo.currentText()
        self._current_step = 0
        self._results = []
        self._running = True
        self._paused = False
        self._run_started_at = datetime.now(timezone.utc)
        self._run_finished_at = None

        # Reset predictor
        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=5.0)
        self._buffers.clear()
        for ch in selected:
            self._buffers[ch] = deque(maxlen=_BUFFER_MAXLEN)

        # Setup plot lines
        for item in self._plot_items.values():
            self._live_plot.removeItem(item)
        self._plot_items.clear()
        for i, ch in enumerate(selected):
            color = _LINE_COLORS[i % len(_LINE_COLORS)]
            item = self._live_plot.plot([], [], pen=pg.mkPen(color=color, width=2), name=ch)
            self._plot_items[ch] = item

        # UI state
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._results_table.setRowCount(0)

        # Begin first step
        self._begin_step()

    def _on_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.setText("ПРОДОЛЖИТЬ" if self._paused else "ПАУЗА")
        if self._paused:
            self._progress_label.setText(
                f"ПАУЗА | Шаг {self._current_step + 1}/{len(self._power_list)}"
            )

    def _on_stop(self) -> None:
        self._running = False
        self._paused = False
        self._run_finished_at = datetime.now(timezone.utc)
        send_command({"cmd": "keithley_stop", "channel": self._smu_channel})
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_label.setText("Остановлено оператором")
        if self._results:
            self._save_results()

    # ------------------------------------------------------------------
    # Sweep logic
    # ------------------------------------------------------------------

    def _begin_step(self) -> None:
        if self._current_step >= len(self._power_list):
            self._finish_sweep()
            return

        p = self._power_list[self._current_step]
        self._step_start_time = time.monotonic()

        # Reset predictor for new step
        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=5.0)

        # Send command
        reply = send_command({
            "cmd": "keithley_start",
            "channel": self._smu_channel,
            "p_target": p,
            "v_comp": self._v_comp_spin.value(),
            "i_comp": self._i_comp_spin.value(),
        })
        logger.info(
            "Автоизмерение: шаг %d/%d, P=%.4f Вт, ответ: %s",
            self._current_step + 1, len(self._power_list), p, reply,
        )

    def _finish_sweep(self) -> None:
        self._running = False
        self._run_finished_at = datetime.now(timezone.utc)
        send_command({"cmd": "keithley_stop", "channel": self._smu_channel})
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_label.setText(
            f"Завершено! {len(self._results)} точек измерено."
        )
        self._progress_bar.setValue(100)
        self._save_results()

    def _record_step(self) -> None:
        """Записать текущий шаг в результаты."""
        P = self._power_list[self._current_step]
        preds = self._predictor.get_all_predictions()
        hot_ch = self._selected_channels[0]
        cold_ch = self._selected_channels[-1]

        p_hot = preds.get(hot_ch)
        p_cold = preds.get(cold_ch)

        T_hot = p_hot.t_predicted if p_hot and p_hot.valid else self._temps.get(hot_ch, 0)
        T_cold = p_cold.t_predicted if p_cold and p_cold.valid else self._temps.get(cold_ch, 0)
        T_avg = (T_hot + T_cold) / 2
        dT = T_hot - T_cold
        R = dT / P if P != 0 else 0
        G = P / dT if dT != 0 else 0

        result = {
            "P": P, "T_hot": T_hot, "T_cold": T_cold,
            "T_avg": T_avg, "dT": dT, "R": R, "G": G,
        }
        self._results.append(result)

        # Update table
        row = self._results_table.rowCount()
        self._results_table.setRowCount(row + 1)
        for col, key in enumerate(["P", "T_hot", "T_cold", "T_avg", "dT", "R", "G"]):
            self._results_table.setItem(
                row, col, QTableWidgetItem(f"{result[key]:.6g}")
            )

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        ts = reading.timestamp.timestamp()

        if ch in self._selected_channels and reading.unit == "K":
            self._temps[ch] = reading.value
            if ch in self._buffers:
                self._buffers[ch].append((ts, reading.value))
            if self._running:
                self._predictor.add_point(ch, ts, reading.value)

        if ch.endswith("/power") and self._smu_channel in ch:
            self._power = reading.value

    # ------------------------------------------------------------------
    # Periodic tick
    # ------------------------------------------------------------------

    @Slot()
    def _tick(self) -> None:
        # Update live plot
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
            self._live_plot.getPlotItem().setXRange(x_min, now, padding=0)

        if not self._running or self._paused:
            return

        # Update predictor
        preds = self._predictor.update(now)
        all_preds = self._predictor.get_all_predictions()

        # Check if step is done
        target_pct = float(self._target_pct.value())
        max_wait_s = self._max_wait.value() * 60.0
        elapsed = time.monotonic() - self._step_start_time

        valid_preds = [all_preds.get(ch) for ch in self._selected_channels
                       if all_preds.get(ch) and all_preds[ch].valid]

        min_pct = min((p.percent_settled for p in valid_preds), default=0.0)
        step_total = len(self._power_list)

        # Progress
        step_progress = min_pct / target_pct * 100 if target_pct > 0 else 0
        overall = ((self._current_step + step_progress / 100) / step_total) * 100
        self._progress_bar.setValue(int(overall))

        remaining_est = ""
        if valid_preds and min_pct < target_pct:
            max_tau = max((p.tau_s for p in valid_preds), default=60)
            if max_tau > 0 and min_pct > 0:
                rem_s = max_tau * math.log(100 / max(100 - min_pct, 0.1))
                remaining_est = f" | ~{rem_s / 60:.0f} мин до след."

        P = self._power_list[self._current_step]
        self._progress_label.setText(
            f"Шаг {self._current_step + 1}/{step_total} | "
            f"P = {P:.4g} Вт | Готово {min_pct:.0f}% | "
            f"{elapsed / 60:.1f} мин{remaining_est}"
        )

        # Check completion
        step_done = min_pct >= target_pct and len(valid_preds) == len(self._selected_channels)
        timed_out = elapsed >= max_wait_s

        if step_done or timed_out:
            if timed_out:
                logger.warning(
                    "Автоизмерение: шаг %d — таймаут (%d мин), записываю текущие",
                    self._current_step + 1, self._max_wait.value(),
                )
            self._record_step()
            self._current_step += 1
            self._begin_step()

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------

    def _save_results(self) -> None:
        if not self._results:
            return

        material = self._material_edit.text() or "unknown"
        operator = self._operator_edit.text() or ""
        sample = self._sample_edit.text() or ""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H%M")

        # Create directory
        sweep_dir = get_data_dir() / "sweeps"
        sweep_dir.mkdir(parents=True, exist_ok=True)

        base = f"{date_str}_{material}"

        # CSV
        csv_path = sweep_dir / f"{base}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["# Образец:", sample])
            w.writerow(["# Материал:", material])
            w.writerow(["# Оператор:", operator])
            w.writerow(["# Дата:", now.isoformat()])
            w.writerow([])
            w.writerow(["P_W", "T_hot_K", "T_cold_K", "T_avg_K", "dT_K", "R_KW", "G_WK"])
            for r in self._results:
                w.writerow([r["P"], r["T_hot"], r["T_cold"], r["T_avg"],
                            r["dT"], r["R"], r["G"]])

        logger.info("Результаты сохранены: %s", csv_path)

        # PNG plot
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            fig.suptitle(
                f"Теплопроводность {material} | {now.strftime('%d.%m.%Y')} | {operator}",
                fontsize=13,
            )

            T_avg = [r["T_avg"] for r in self._results]
            R_vals = [r["R"] for r in self._results]
            G_vals = [r["G"] for r in self._results]

            ax1.plot(T_avg, R_vals, "o-", color="#f0883e", markersize=6)
            ax1.set_xlabel("T_avg (K)")
            ax1.set_ylabel("R (K/W)")
            ax1.set_title("Тепловое сопротивление")
            ax1.grid(True, alpha=0.3)

            ax2.plot(T_avg, G_vals, "s-", color="#3fb950", markersize=6)
            ax2.set_xlabel("T_avg (K)")
            ax2.set_ylabel("G (W/K)")
            ax2.set_title("Теплопроводность")
            ax2.grid(True, alpha=0.3)

            fig.tight_layout()
            png_path = sweep_dir / f"{base}.png"
            fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
            logger.info("График сохранён: %s", png_path)
        except Exception as exc:
            logger.error("Ошибка сохранения графика: %s", exc)
            png_path = None

        attach_result = send_command(
            {
                "cmd": "experiment_attach_run_record",
                "source_tab": "autosweep",
                "source_module": "autosweep_panel",
                "run_type": "autosweep",
                "status": "COMPLETED" if self._running is False else "RUNNING",
                "source_run_id": base,
                "started_at": self._run_started_at.isoformat() if self._run_started_at else now.isoformat(),
                "finished_at": self._run_finished_at.isoformat() if self._run_finished_at else now.isoformat(),
                "parameters": {
                    "sample": sample,
                    "material": material,
                    "operator": operator,
                    "power_start_w": self._p_start.value(),
                    "power_end_w": self._p_end.value(),
                    "power_step_w": self._p_step.value(),
                    "smu_channel": self._smu_channel,
                    "selected_channels": list(self._selected_channels),
                    "target_percent": int(self._target_pct.value()),
                    "max_wait_min": int(self._max_wait.value()),
                    "v_comp_v": self._v_comp_spin.value(),
                    "i_comp_a": self._i_comp_spin.value(),
                },
                "result_summary": {
                    "point_count": len(self._results),
                    "avg_temperature_k": (
                        sum(float(item["T_avg"]) for item in self._results) / len(self._results)
                        if self._results
                        else 0.0
                    ),
                    "max_resistance_kw": max((float(item["R"]) for item in self._results), default=0.0),
                    "max_conductance_wk": max((float(item["G"]) for item in self._results), default=0.0),
                },
                "artifact_paths": [
                    str(csv_path),
                    str(png_path) if png_path is not None else "",
                ],
            }
        )
        if attach_result.get("attached"):
            logger.info("Автоизмерение прикреплено к активной карточке эксперимента.")
