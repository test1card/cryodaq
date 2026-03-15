"""Панель обзора — домашняя вкладка CryoDAQ.

Объединяет температуры, давление, статус и Keithley в единый виджет.

Классы:
    StatusStrip — горизонтальная полоса статуса (~40px)
    CompactTempCard — мини-карточка температурного канала (~100x60)
    TempCardGrid — адаптивная сетка CompactTempCard
    PressureStrip — полоса давления с мини-графиком (~80px)
    KeithleyStrip — полоса Keithley smua/smub (~50px)
    OverviewPanel — главный виджет вкладки «Обзор»
"""

from __future__ import annotations

import logging
import math
import shutil
import time
from collections import deque
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.paths import get_data_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
_BUFFER_MAXLEN = 3600
_DEFAULT_WINDOW_S = 3600.0  # 1 час по умолчанию

_LINE_PALETTE: list[str] = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#AEC7E8", "#FFBB78", "#98DF8A", "#FF9896", "#C5B0D5",
    "#C49C94", "#F7B6D2", "#C7C7C7", "#DBDB8D", "#9EDAE5",
    "#393B79", "#637939", "#8C6D31", "#843C39",
]

# Цвета давления
_PRESSURE_GOOD = "#2ECC40"
_PRESSURE_WARN = "#FFDC00"
_PRESSURE_BAD = "#FF4136"


def _pressure_color(value: float) -> str:
    if value <= 0 or not math.isfinite(value):
        return _PRESSURE_WARN
    if value < 1e-3:
        return _PRESSURE_GOOD
    if value < 1e-1:
        return _PRESSURE_WARN
    return _PRESSURE_BAD


def _disk_free_gb() -> float:
    """Свободное место на диске data/ (или C:) в ГБ."""
    try:
        usage = shutil.disk_usage(get_data_dir())
        return usage.free / (1024 ** 3)
    except Exception:
        return -1.0


# ---------------------------------------------------------------------------
# StatusStrip
# ---------------------------------------------------------------------------

class StatusStrip(QFrame):
    """Горизонтальная полоса статуса (~40px)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet(
            "StatusStrip { background-color: #1E1E1E; border: 1px solid #333; border-radius: 4px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)

        # SafetyManager state
        self._safety_label = QLabel("SAFE_OFF")
        self._safety_label.setFont(self._bold_font(14))
        self._safety_label.setStyleSheet("color: #2ECC40; border: none;")
        layout.addWidget(self._safety_label)
        layout.addWidget(self._separator())

        # Engine uptime
        self._uptime_label = QLabel("Uptime: 00:00:00")
        self._uptime_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._uptime_label)
        layout.addWidget(self._separator())

        # Active alarms
        self._alarm_label = QLabel("0 алармов")
        self._alarm_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._alarm_label)
        layout.addWidget(self._separator())

        # Keithley status
        self._keithley_label = QLabel("OFF")
        self._keithley_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._keithley_label)
        layout.addWidget(self._separator())

        # Cooldown ETA
        self._cooldown_label = QLabel("")
        self._cooldown_label.setStyleSheet("color: #00CED1; border: none;")
        self._cooldown_label.setVisible(False)
        layout.addWidget(self._cooldown_label)
        layout.addWidget(self._separator())

        # Disk free
        self._disk_label = QLabel("")
        self._disk_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._disk_label)

        layout.addStretch()

        self._start_time = time.monotonic()
        self._alarm_count = 0

        # Периодическое обновление uptime и диска
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    # --- Публичные методы обновления ---

    def set_safety_state(self, state: str) -> None:
        colors = {
            "SAFE_OFF": "#2ECC40",
            "READY": "#FFDC00",
            "RUN_PERMITTED": "#FFDC00",
            "RUNNING": "#3498DB",
            "FAULT_LATCHED": "#FF4136",
            "FAULT": "#FF4136",
        }
        color = colors.get(state, "#888888")
        self._safety_label.setText(state)
        self._safety_label.setStyleSheet(f"color: {color}; border: none;")

    def set_alarm_count(self, count: int) -> None:
        self._alarm_count = count
        if count == 0:
            self._alarm_label.setText("0 алармов")
            self._alarm_label.setStyleSheet("color: #888888; border: none;")
        else:
            # Правильное склонение
            if count == 1:
                word = "аларм"
            elif 2 <= count <= 4:
                word = "аларма"
            else:
                word = "алармов"
            self._alarm_label.setText(f"{count} {word}!")
            self._alarm_label.setStyleSheet("color: #FF4136; font-weight: bold; border: none;")

    def set_keithley_status(self, text: str, is_on: bool) -> None:
        if is_on:
            self._keithley_label.setText(text)
            self._keithley_label.setStyleSheet("color: #2ECC40; border: none;")
        else:
            self._keithley_label.setText("OFF")
            self._keithley_label.setStyleSheet("color: #888888; border: none;")

    def set_cooldown_eta(self, eta_text: str | None) -> None:
        if eta_text:
            self._cooldown_label.setText(eta_text)
            self._cooldown_label.setVisible(True)
        else:
            self._cooldown_label.setVisible(False)

    # --- Внутренние ---

    @Slot()
    def _tick(self) -> None:
        uptime_s = int(time.monotonic() - self._start_time)
        hours, rem = divmod(uptime_s, 3600)
        mins, secs = divmod(rem, 60)
        self._uptime_label.setText(f"Uptime: {hours:02d}:{mins:02d}:{secs:02d}")

        free = _disk_free_gb()
        if free < 0:
            self._disk_label.setText("Диск: ?")
            self._disk_label.setStyleSheet("color: #888888; border: none;")
        elif free < 2:
            self._disk_label.setText(f"Диск: {free:.1f} ГБ")
            self._disk_label.setStyleSheet("color: #FF4136; font-weight: bold; border: none;")
        elif free < 10:
            self._disk_label.setText(f"Диск: {free:.1f} ГБ")
            self._disk_label.setStyleSheet("color: #FFDC00; border: none;")
        else:
            self._disk_label.setText(f"Диск: {free:.0f} ГБ")
            self._disk_label.setStyleSheet("color: #888888; border: none;")

    @staticmethod
    def _bold_font(pt: int) -> QFont:
        f = QFont()
        f.setPointSize(pt)
        f.setBold(True)
        return f

    @staticmethod
    def _separator() -> QLabel:
        sep = QLabel(" | ")
        sep.setStyleSheet("color: #555555; border: none;")
        return sep


# ---------------------------------------------------------------------------
# CompactTempCard
# ---------------------------------------------------------------------------

class CompactTempCard(QFrame):
    """Мини-карточка температурного канала (~100x60px)."""

    def __init__(self, channel_id: str, display_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_id = channel_id
        self._last_value: float | None = None
        self._last_ts: float | None = None
        self._prev_value: float | None = None
        self._prev_ts: float | None = None
        self._dt_dt: float = 0.0  # K/h
        self._has_alarm = False
        self._has_error = False

        self.setMinimumSize(100, 60)
        self.setMaximumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_bg("#2A2A2A")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        # Строка 1: имя канала
        self._name_label = QLabel(display_name)
        name_font = QFont()
        name_font.setPointSize(9)
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet("color: #BBBBBB; border: none;")
        self._name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._name_label)

        # Строка 2: значение
        self._value_label = QLabel("---- K")
        val_font = QFont()
        val_font.setPointSize(14)
        val_font.setBold(True)
        self._value_label.setFont(val_font)
        self._value_label.setStyleSheet("color: #FFFFFF; border: none;")
        self._value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value_label)

        # Строка 3: тренд
        self._trend_label = QLabel("")
        trend_font = QFont()
        trend_font.setPointSize(8)
        self._trend_label.setFont(trend_font)
        self._trend_label.setStyleSheet("color: #888888; border: none;")
        self._trend_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._trend_label)

    @property
    def channel_id(self) -> str:
        return self._channel_id

    def update_reading(self, reading: Reading) -> None:
        """Обновить карточку по новому показанию."""
        ts = reading.timestamp.timestamp()
        value = reading.value
        status = reading.status

        # Ошибка сенсора
        if status in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
            self._has_error = True
            self._value_label.setText("ОТКЛ")
            self._value_label.setStyleSheet("color: #888888; border: none;")
            self._trend_label.setText("")
            self._apply_bg("#3A3A3A")
            return

        self._has_error = False
        self._value_label.setText(f"{value:.2f} K")
        self._value_label.setStyleSheet("color: #FFFFFF; border: none;")

        # Вычислить dT/dt
        if self._last_ts is not None and ts > self._last_ts:
            dt_s = ts - self._last_ts
            if dt_s > 0.5:  # минимум 0.5с
                dv = value - (self._last_value or 0.0)
                self._dt_dt = (dv / dt_s) * 3600.0  # K/h

        self._prev_value = self._last_value
        self._prev_ts = self._last_ts
        self._last_value = value
        self._last_ts = ts

        # Тренд
        abs_rate = abs(self._dt_dt)
        if abs_rate < 0.1:
            arrow = "="
        elif self._dt_dt > 0:
            arrow = "\u25b2"  # ▲
        else:
            arrow = "\u25bc"  # ▼
        self._trend_label.setText(f"{arrow} {self._dt_dt:+.1f} K/ч")

        # Фон
        if self._has_alarm:
            self._apply_bg("#4A2020")  # красный оттенок
        elif abs_rate > 10:
            self._apply_bg("#1E2A3A")  # синий оттенок
        else:
            self._apply_bg("#2A2A2A")

    def set_alarm(self, active: bool) -> None:
        self._has_alarm = active
        if active and not self._has_error:
            self._apply_bg("#4A2020")
        elif not self._has_error:
            abs_rate = abs(self._dt_dt)
            self._apply_bg("#1E2A3A" if abs_rate > 10 else "#2A2A2A")

    def _apply_bg(self, color: str) -> None:
        self.setStyleSheet(
            f"CompactTempCard {{ background-color: {color}; "
            f"border: 1px solid #444; border-radius: 4px; }}"
        )


# ---------------------------------------------------------------------------
# TempCardGrid
# ---------------------------------------------------------------------------

class TempCardGrid(QWidget):
    """Адаптивная сетка CompactTempCard."""

    _MIN_CARD_WIDTH = 110

    def __init__(self, channel_manager: ChannelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._cards: dict[str, CompactTempCard] = {}
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        self._cols = 4

        self._build_cards()

    def _build_cards(self) -> None:
        """Создать карточки для видимых каналов."""
        visible_ids = self._channel_mgr.get_all_visible()
        # Фильтруем только температурные каналы
        temp_ids = [ch for ch in visible_ids if ch.startswith("\u0422")]  # Т
        for ch_id in temp_ids:
            display = self._channel_mgr.get_display_name(ch_id)
            card = CompactTempCard(ch_id, display)
            self._cards[ch_id] = card

        self._relayout()

    def get_cards(self) -> dict[str, CompactTempCard]:
        return self._cards

    def resizeEvent(self, event: object) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """Перестроить сетку по текущей ширине."""
        width = self.width() if self.width() > 0 else 800
        new_cols = max(1, width // self._MIN_CARD_WIDTH)
        if new_cols == self._cols and self._grid.count() > 0:
            return
        self._cols = new_cols

        # Убрать все из layout (без удаления виджетов)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        # Разместить заново
        for idx, card in enumerate(self._cards.values()):
            row, col = divmod(idx, self._cols)
            self._grid.addWidget(card, row, col)
            card.setParent(self)


# ---------------------------------------------------------------------------
# PressureStrip
# ---------------------------------------------------------------------------

class PressureStrip(QFrame):
    """Полоса давления (~80px): слева — значение, справа — мини-график."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setStyleSheet(
            "PressureStrip { background-color: #1E1E1E; border: 1px solid #333; border-radius: 4px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 4, 4)
        layout.setSpacing(8)

        # Левая часть: значение
        val_frame = QFrame()
        val_frame.setStyleSheet("border: none;")
        val_layout = QVBoxLayout(val_frame)
        val_layout.setContentsMargins(0, 0, 0, 0)
        val_layout.setSpacing(0)

        title = QLabel("Давление")
        title.setStyleSheet("color: #888888; border: none;")
        title_font = QFont()
        title_font.setPointSize(9)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        val_layout.addWidget(title)

        self._value_label = QLabel("---")
        big_font = QFont()
        big_font.setPointSize(20)
        big_font.setBold(True)
        self._value_label.setFont(big_font)
        self._value_label.setStyleSheet(f"color: {_PRESSURE_GOOD}; border: none;")
        self._value_label.setAlignment(Qt.AlignCenter)
        val_layout.addWidget(self._value_label)

        val_frame.setFixedWidth(160)
        layout.addWidget(val_frame)

        # Правая часть: мини-график
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#111111")
        pi = self._plot.getPlotItem()
        pi.setLogMode(x=False, y=True)
        pi.hideAxis("bottom")
        pi.hideAxis("left")
        pi.showGrid(x=False, y=True, alpha=0.2)
        pi.setMouseEnabled(x=False, y=False)
        pi.hideButtons()
        self._plot.setStyleSheet("border: none;")
        layout.addWidget(self._plot, stretch=1)

        self._buffer: deque[tuple[float, float]] = deque(maxlen=_BUFFER_MAXLEN)
        self._plot_item: pg.PlotDataItem | None = None

    def on_reading(self, reading: Reading) -> None:
        """Обновить давление."""
        value = reading.value
        ts = reading.timestamp.timestamp()
        self._buffer.append((ts, value))

        # Обновить значение
        if value > 0 and math.isfinite(value):
            exp = math.floor(math.log10(value))
            mantissa = value / (10 ** exp)
            self._value_label.setText(f"{mantissa:.2f}e{exp}")
        else:
            self._value_label.setText(f"{value:.2e}")

        color = _pressure_color(value)
        self._value_label.setStyleSheet(f"color: {color}; border: none;")

    def refresh_plot(self) -> None:
        """Обновить мини-график (вызывается по таймеру)."""
        if not self._buffer:
            return
        if self._plot_item is None:
            pen = pg.mkPen(color="#17BECF", width=1.5)
            self._plot_item = self._plot.plot([], [], pen=pen)

        now = time.time()
        x_min = now - 600.0  # 10 минут
        xs = [t for t, _ in self._buffer if t >= x_min]
        ys = [v for t, v in self._buffer if t >= x_min]
        self._plot_item.setData(xs, ys)
        if xs:
            self._plot.getPlotItem().setXRange(x_min, now, padding=0)


# ---------------------------------------------------------------------------
# KeithleyStrip
# ---------------------------------------------------------------------------

class KeithleyStrip(QFrame):
    """Полоса Keithley smua/smub (~50px), условно видимая."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet(
            "KeithleyStrip { background-color: #1E1E1E; border: 1px solid #333; border-radius: 4px; }"
        )
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        lbl_font = QFont()
        lbl_font.setPointSize(10)

        title = QLabel("Keithley")
        title.setFont(self._bold_font(10))
        title.setStyleSheet("color: #AAAAAA; border: none;")
        layout.addWidget(title)

        self._smua_label = QLabel("smua: ---")
        self._smua_label.setFont(lbl_font)
        self._smua_label.setStyleSheet("color: #FFFFFF; border: none;")
        layout.addWidget(self._smua_label)

        self._smub_label = QLabel("smub: OFF")
        self._smub_label.setFont(lbl_font)
        self._smub_label.setStyleSheet("color: #888888; border: none;")
        self._smub_label.setVisible(False)
        layout.addWidget(self._smub_label)

        layout.addStretch()

        # Состояние
        self._smua_data: dict[str, float] = {}
        self._smub_data: dict[str, float] = {}
        self._is_on = False

    def on_reading(self, reading: Reading) -> None:
        """Обновить по Keithley показанию."""
        ch = reading.channel
        val = reading.value

        if "/smua/" in ch:
            param = ch.split("/")[-1]  # voltage, current, resistance, power
            self._smua_data[param] = val
            self._update_smu_label(self._smua_label, "smua", self._smua_data)
            self._is_on = True
            self.setVisible(True)

    def set_safety_state(self, state: str) -> None:
        """Скрыть при SAFE_OFF."""
        if state == "SAFE_OFF":
            self.setVisible(False)
            self._is_on = False
        elif self._is_on:
            self.setVisible(True)

    @staticmethod
    def _update_smu_label(label: QLabel, name: str, data: dict[str, float]) -> None:
        v = data.get("voltage", 0.0)
        i = data.get("current", 0.0)
        r = data.get("resistance", 0.0)
        p = data.get("power", 0.0)
        label.setText(f"{name}: V={v:.3f} I={i:.4f} R={r:.1f} P={p:.2f}")
        label.setStyleSheet("color: #FFFFFF; border: none;")

    @staticmethod
    def _bold_font(pt: int) -> QFont:
        f = QFont()
        f.setPointSize(pt)
        f.setBold(True)
        return f


# ---------------------------------------------------------------------------
# OverviewPanel
# ---------------------------------------------------------------------------

class OverviewPanel(QWidget):
    """Главный виджет вкладки «Обзор».

    Объединяет StatusStrip, TempCardGrid, график, PressureStrip, KeithleyStrip.
    """

    _reading_received = Signal(object)

    def __init__(self, channel_manager: ChannelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self.setStyleSheet("background-color: #1A1A1A;")

        # Буферы данных: channel_id -> deque[(ts, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # plot items: channel_id -> PlotDataItem
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        # Текущее окно времени (секунды)
        self._window_s = _DEFAULT_WINDOW_S

        self._build_ui()
        self._init_plot()

        # Signal/Slot для потокобезопасности
        self._reading_received.connect(self._handle_reading)

        # Таймер обновления графика — 2 Гц
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(500)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 1. StatusStrip
        self._status_strip = StatusStrip()
        root.addWidget(self._status_strip)

        # 2. TempCardGrid
        self._card_grid = TempCardGrid(self._channel_mgr)
        root.addWidget(self._card_grid)

        # 3. График с кнопками
        plot_frame = QFrame()
        plot_frame.setStyleSheet(
            "QFrame { background-color: #111111; border: 1px solid #333; border-radius: 4px; }"
        )
        plot_root = QVBoxLayout(plot_frame)
        plot_root.setContentsMargins(4, 4, 4, 4)
        plot_root.setSpacing(4)

        # Кнопки над графиком
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(6)

        # Временные кнопки
        for label, seconds in [("1\u0447", 3600), ("6\u0447", 21600), ("24\u0447", 86400)]:
            btn = QPushButton(label)
            btn.setFixedSize(QSize(50, 24))
            btn.setStyleSheet(
                "QPushButton { background: #333; color: #CCC; border: 1px solid #555; "
                "border-radius: 3px; } QPushButton:hover { background: #444; }"
            )
            btn.clicked.connect(lambda checked, s=seconds: self._set_window(s))
            btn_bar.addWidget(btn)

        btn_bar.addStretch()

        # Log/Lin toggle
        self._log_btn = QPushButton("Lin Y")
        self._log_btn.setFixedSize(QSize(60, 24))
        self._log_btn.setStyleSheet(
            "QPushButton { background: #333; color: #CCC; border: 1px solid #555; "
            "border-radius: 3px; } QPushButton:hover { background: #444; }"
        )
        self._log_btn.clicked.connect(self._toggle_log)
        self._is_log_y = False
        btn_bar.addWidget(self._log_btn)

        # Export PNG
        png_btn = QPushButton("PNG")
        png_btn.setFixedSize(QSize(60, 24))
        png_btn.setStyleSheet(
            "QPushButton { background: #333; color: #CCC; border: 1px solid #555; "
            "border-radius: 3px; } QPushButton:hover { background: #444; }"
        )
        png_btn.clicked.connect(self._on_export_png)
        btn_bar.addWidget(png_btn)

        # Export CSV
        csv_btn = QPushButton("CSV")
        csv_btn.setFixedSize(QSize(60, 24))
        csv_btn.setStyleSheet(
            "QPushButton { background: #333; color: #CCC; border: 1px solid #555; "
            "border-radius: 3px; } QPushButton:hover { background: #444; }"
        )
        csv_btn.clicked.connect(self._on_export_csv)
        btn_bar.addWidget(csv_btn)

        plot_root.addLayout(btn_bar)

        # PlotWidget
        self._plot = pg.PlotWidget()
        plot_root.addWidget(self._plot)

        root.addWidget(plot_frame, stretch=1)

        # 4. PressureStrip
        self._pressure_strip = PressureStrip()
        root.addWidget(self._pressure_strip)

        # 5. KeithleyStrip
        self._keithley_strip = KeithleyStrip()
        root.addWidget(self._keithley_strip)

    def _init_plot(self) -> None:
        """Настроить внешний вид основного графика."""
        pw = self._plot
        pw.setBackground("#111111")

        pi = pw.getPlotItem()
        pi.setLabel("left", "\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430", units="\u041a", color="#AAAAAA")
        pi.setLabel("bottom", "\u0412\u0440\u0435\u043c\u044f", color="#AAAAAA")
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.enableAutoRange(axis="y", enable=True)

        for axis_name in ("left", "bottom", "top", "right"):
            axis = pi.getAxis(axis_name)
            if axis is not None:
                axis.setPen(pg.mkPen(color="#444444"))
                axis.setTextPen(pg.mkPen(color="#AAAAAA"))

        # Создать линии для всех видимых каналов
        visible_ids = self._channel_mgr.get_all_visible()
        temp_ids = [ch for ch in visible_ids if ch.startswith("\u0422")]
        for idx, ch_id in enumerate(temp_ids):
            display = self._channel_mgr.get_display_name(ch_id)
            color = _LINE_PALETTE[idx % len(_LINE_PALETTE)]
            pen = pg.mkPen(color=color, width=1.5)
            item = pw.plot([], [], pen=pen, name=display)
            self._plot_items[ch_id] = item
            self._buffers[ch_id] = deque(maxlen=_BUFFER_MAXLEN)

    # ------------------------------------------------------------------
    # Публичный интерфейс
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Принять показание (потокобезопасно через Signal)."""
        self._reading_received.emit(reading)

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        """Обработать показание в GUI-потоке. Маршрутизация к суб-виджетам."""
        channel = reading.channel

        # Температуры → карточки + буфер графика
        if channel.startswith("\u0422") and reading.unit == "K":
            # Обновить карточку
            cards = self._card_grid.get_cards()
            # channel_id в карточках — короткий (Т1), в reading — может быть полный
            short_id = channel.split(" ")[0] if " " in channel else channel
            card = cards.get(short_id)
            if card is not None:
                card.update_reading(reading)

            # Буфер графика
            if short_id in self._buffers:
                self._buffers[short_id].append(
                    (reading.timestamp.timestamp(), reading.value)
                )

        # Давление
        if reading.unit == "mbar":
            self._pressure_strip.on_reading(reading)

        # Keithley
        if "/smua/" in channel or "/smub/" in channel:
            self._keithley_strip.on_reading(reading)
            # Обновить status strip
            if channel.endswith("/power"):
                power = reading.value
                if power > 0:
                    self._status_strip.set_keithley_status(
                        f"ON P={power:.1f}W", is_on=True,
                    )

        # Аналитика — cooldown ETA
        if channel == "analytics/cooldown_eta_hours":
            hours = reading.value
            if hours > 0 and math.isfinite(hours):
                h = int(hours)
                m = int((hours - h) * 60)
                self._status_strip.set_cooldown_eta(f"{h}\u0447 {m}\u043c\u0438\u043d")
            else:
                self._status_strip.set_cooldown_eta(None)

        # Safety state
        if channel == "analytics/safety_state":
            state_name = reading.metadata.get("state", "")
            if state_name:
                self._status_strip.set_safety_state(state_name)
                self._keithley_strip.set_safety_state(state_name)

        # Alarm count
        if channel == "analytics/alarm_count":
            self._status_strip.set_alarm_count(int(reading.value))

    @Slot()
    def _refresh_plot(self) -> None:
        """Обновить все линии на графике (2 Гц)."""
        now = time.time()
        x_min = now - self._window_s

        for ch_id, item in self._plot_items.items():
            buf = self._buffers.get(ch_id)
            if not buf:
                item.setData([], [])
                continue
            xs: list[float] = []
            ys: list[float] = []
            for ts, val in buf:
                if ts >= x_min:
                    xs.append(ts)
                    ys.append(val)
            item.setData(xs, ys)

        if self._plot_items:
            self._plot.getPlotItem().setXRange(x_min, now, padding=0)

        # Обновить мини-график давления
        self._pressure_strip.refresh_plot()

    # ------------------------------------------------------------------
    # Кнопки управления
    # ------------------------------------------------------------------

    def _set_window(self, seconds: int) -> None:
        self._window_s = float(seconds)

    @Slot()
    def _toggle_log(self) -> None:
        self._is_log_y = not self._is_log_y
        self._plot.getPlotItem().setLogMode(x=False, y=self._is_log_y)
        self._log_btn.setText("Log Y" if self._is_log_y else "Lin Y")

    @Slot()
    def _on_export_png(self) -> None:
        from datetime import datetime

        default_name = f"CryoDAQ_\u041e\u0431\u0437\u043e\u0440_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c PNG", default_name, "PNG (*.png)")
        if path:
            # Белый фон для печати
            self._plot.setBackground("white")
            self._plot.grab().save(path, "PNG")
            self._plot.setBackground("#111111")

    @Slot()
    def _on_export_csv(self) -> None:
        from datetime import datetime

        default_name = f"CryoDAQ_\u041e\u0431\u0437\u043e\u0440_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c CSV", default_name, "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                # Заголовок: Время;Channel1;Channel2;...
                channels = sorted(self._buffers.keys())
                f.write("\u0412\u0440\u0435\u043c\u044f;" + ";".join(channels) + "\n")

                # Собрать все уникальные метки времени
                all_ts: dict[float, dict[str, float]] = {}
                for ch_id in channels:
                    for ts, val in self._buffers.get(ch_id, []):
                        if ts not in all_ts:
                            all_ts[ts] = {}
                        all_ts[ts][ch_id] = val

                # Записать строки, отсортированные по времени
                for ts in sorted(all_ts.keys()):
                    from datetime import datetime as dt, timezone

                    time_str = dt.fromtimestamp(ts, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    row_data = all_ts[ts]
                    values = []
                    for ch_id in channels:
                        if ch_id in row_data:
                            # Десятичная запятая для русской локали
                            values.append(str(row_data[ch_id]).replace(".", ","))
                        else:
                            values.append("")
                    f.write(time_str + ";" + ";".join(values) + "\n")
