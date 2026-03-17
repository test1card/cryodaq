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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.widgets.common import (
    apply_button_style,
    apply_panel_frame_style,
    apply_status_label_style,
    create_panel_root,
)
from cryodaq.gui.widgets.experiment_workspace import ExperimentWorkspace
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
        apply_panel_frame_style(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)

        # SafetyManager state
        self._safety_label = QLabel("SAFE_OFF")
        self._safety_label.setFont(self._bold_font(14))
        apply_status_label_style(self._safety_label, "success")
        layout.addWidget(self._safety_label)
        layout.addWidget(self._separator())

        # Engine uptime
        self._uptime_label = QLabel("Аптайм: 00:00:00")
        apply_status_label_style(self._uptime_label, "muted")
        layout.addWidget(self._uptime_label)
        layout.addWidget(self._separator())

        # Active alarms
        self._alarm_label = QLabel("0 алармов")
        apply_status_label_style(self._alarm_label, "muted")
        layout.addWidget(self._alarm_label)
        layout.addWidget(self._separator())

        # Keithley status
        self._keithley_label = QLabel("ВЫКЛ")
        apply_status_label_style(self._keithley_label, "muted")
        layout.addWidget(self._keithley_label)
        layout.addWidget(self._separator())

        # Cooldown ETA
        self._cooldown_label = QLabel("")
        apply_status_label_style(self._cooldown_label, "accent")
        self._cooldown_label.setVisible(False)
        layout.addWidget(self._cooldown_label)
        layout.addWidget(self._separator())

        # Disk free
        self._disk_label = QLabel("")
        apply_status_label_style(self._disk_label, "muted")
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
        state = state.upper()
        self._safety_label.setText(state)
        if state in {"FAULT_LATCHED", "FAULT"}:
            apply_status_label_style(self._safety_label, "error", bold=True)
        elif state == "RUNNING":
            apply_status_label_style(self._safety_label, "info", bold=True)
        elif state in {"READY", "RUN_PERMITTED"}:
            apply_status_label_style(self._safety_label, "warning", bold=True)
        else:
            apply_status_label_style(self._safety_label, "success", bold=True)

    def set_alarm_count(self, count: int) -> None:
        self._alarm_count = count
        if count == 0:
            self._alarm_label.setText("0 алармов")
            apply_status_label_style(self._alarm_label, "muted")
        else:
            # Правильное склонение
            if count == 1:
                word = "аларм"
            elif 2 <= count <= 4:
                word = "аларма"
            else:
                word = "алармов"
            self._alarm_label.setText(f"{count} {word}!")
            apply_status_label_style(self._alarm_label, "error", bold=True)

    def set_keithley_status(self, text: str, is_on: bool) -> None:
        if is_on:
            self._keithley_label.setText(text)
            apply_status_label_style(self._keithley_label, "success")
        else:
            self._keithley_label.setText("ВЫКЛ")
            apply_status_label_style(self._keithley_label, "muted")

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
        self._uptime_label.setText(f"Аптайм: {hours:02d}:{mins:02d}:{secs:02d}")

        free = _disk_free_gb()
        if free < 0:
            self._disk_label.setText("Диск: ?")
            apply_status_label_style(self._disk_label, "muted")
        elif free < 2:
            self._disk_label.setText(f"Диск: {free:.1f} ГБ")
            apply_status_label_style(self._disk_label, "error", bold=True)
        elif free < 10:
            self._disk_label.setText(f"Диск: {free:.1f} ГБ")
            apply_status_label_style(self._disk_label, "warning")
        else:
            self._disk_label.setText(f"Диск: {free:.0f} ГБ")
            apply_status_label_style(self._disk_label, "muted")

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
        apply_panel_frame_style(self)

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
    """Dual-channel Keithley strip driven by backend truth."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(50)
        apply_panel_frame_style(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        lbl_font = QFont()
        lbl_font.setPointSize(10)

        title = QLabel("Keithley")
        title.setFont(self._bold_font(10))
        apply_status_label_style(title, "muted", bold=True)
        layout.addWidget(title)

        self._smua_label = QLabel("smua: ВЫКЛ")
        self._smua_label.setFont(lbl_font)
        apply_status_label_style(self._smua_label, "muted")
        layout.addWidget(self._smua_label)

        self._smub_label = QLabel("smub: ВЫКЛ")
        self._smub_label.setFont(lbl_font)
        apply_status_label_style(self._smub_label, "muted")
        layout.addWidget(self._smub_label)

        layout.addSpacing(12)

        # Quick-action buttons
        for smu in ("smua", "smub"):
            start_btn = QPushButton(f"\u25b6 {smu}")
            start_btn.setFixedSize(QSize(70, 28))
            apply_button_style(start_btn, "primary", compact=True)
            start_btn.clicked.connect(lambda _, ch=smu: self._on_quick_start(ch))
            layout.addWidget(start_btn)

            stop_btn = QPushButton(f"\u25a0 {smu}")
            stop_btn.setFixedSize(QSize(70, 28))
            apply_button_style(stop_btn, "neutral", compact=True)
            stop_btn.clicked.connect(lambda _, ch=smu: self._on_quick_stop(ch))
            layout.addWidget(stop_btn)

        eoff_btn = QPushButton("\u26a1 E-Off")
        eoff_btn.setFixedSize(QSize(70, 28))
        apply_button_style(eoff_btn, "danger", compact=True)
        eoff_btn.clicked.connect(self._on_emergency_off)
        layout.addWidget(eoff_btn)

        layout.addStretch()

        # Состояние
        self._smua_data: dict[str, float] = {}
        self._smub_data: dict[str, float] = {}
        self._channel_state: dict[str, str] = {"smua": "off", "smub": "off"}
        self._workers: list[object] = []

    def on_reading(self, reading: Reading) -> None:
        """Update display values from backend telemetry."""
        ch = reading.channel
        val = reading.value

        if "/smua/" in ch:
            param = ch.split("/")[-1]
            self._smua_data[param] = val
        elif "/smub/" in ch:
            param = ch.split("/")[-1]
            self._smub_data[param] = val
        self._refresh_labels()

    def set_channel_state(self, channel: str, state: str) -> None:
        self._channel_state[channel] = state.lower()
        self._refresh_labels()

    def set_safety_state(self, state: str) -> None:
        """Apply global safety state without overriding channel-owned fault."""
        if state.upper() == "SAFE_OFF":
            for channel, channel_state in list(self._channel_state.items()):
                if channel_state != "fault":
                    self._channel_state[channel] = "off"
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        self._update_smu_label(
            self._smua_label,
            "smua",
            self._smua_data,
            state=self._channel_state["smua"],
        )
        self._update_smu_label(
            self._smub_label,
            "smub",
            self._smub_data,
            state=self._channel_state["smub"],
        )
        self.setVisible(
            any(state != "off" for state in self._channel_state.values())
            or bool(self._smua_data)
            or bool(self._smub_data)
        )

    def _on_quick_start(self, channel: str) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "keithley_start", "channel": channel})
        worker.finished.connect(lambda r: None)
        self._workers.append(worker)
        worker.start()

    def _on_quick_stop(self, channel: str) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "keithley_stop", "channel": channel})
        worker.finished.connect(lambda r: None)
        self._workers.append(worker)
        worker.start()

    def _on_emergency_off(self) -> None:
        reply = QMessageBox.question(
            self,
            "Emergency Off",
            "Аварийное отключение Keithley?\n\nИсточник будет немедленно отключён.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        for ch in ("smua", "smub"):
            worker = ZmqCommandWorker({"cmd": "keithley_emergency_off", "channel": ch})
            worker.finished.connect(lambda r: None)
            self._workers.append(worker)
            worker.start()

    @staticmethod
    def _update_smu_label(
        label: QLabel,
        name: str,
        data: dict[str, float],
        *,
        state: str,
    ) -> None:
        if state == "fault":
            label.setText(f"{name}: АВАРИЯ")
            apply_status_label_style(label, "error", bold=True)
            return
        if state == "on" and not data:
            label.setText(f"{name}: ВКЛ")
            apply_status_label_style(label, "success", bold=True)
            return
        if not data:
            label.setText(f"{name}: ВЫКЛ")
            apply_status_label_style(label, "muted")
            return
        v = data.get("voltage", 0.0)
        i = data.get("current", 0.0)
        r = data.get("resistance", 0.0)
        p = data.get("power", 0.0)
        state_text = {
            "on": "ВКЛ",
            "fault": "АВАРИЯ",
            "off": "ВЫКЛ",
        }.get(state, state.upper())
        label.setText(f"{name}: {state_text}  V={v:.3f} I={i:.4f} R={r:.1f} P={p:.2f}")
        if state == "on":
            apply_status_label_style(label, "success", bold=True)
        else:
            apply_status_label_style(label, "muted")

    @staticmethod
    def _bold_font(pt: int) -> QFont:
        f = QFont()
        f.setPointSize(pt)
        f.setBold(True)
        return f


# ---------------------------------------------------------------------------
# ExperimentStatusWidget
# ---------------------------------------------------------------------------

class ExperimentStatusWidget(QFrame):
    """Compact experiment status bar for Overview: name, template, elapsed time."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        apply_panel_frame_style(self, background="#1A2332", border="#2A4060")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(8)

        self._status_label = QLabel("Нет активного эксперимента")
        lbl_font = QFont()
        lbl_font.setPointSize(10)
        self._status_label.setFont(lbl_font)
        self._status_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._elapsed_label = QLabel("")
        self._elapsed_label.setFont(lbl_font)
        self._elapsed_label.setStyleSheet("color: #58a6ff; border: none;")
        layout.addWidget(self._elapsed_label)

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    @Slot()
    def _refresh(self) -> None:
        from cryodaq.gui.zmq_client import send_command

        result = send_command({"cmd": "experiment_status"})
        if not result.get("ok") or not result.get("active"):
            self._status_label.setText("Нет активного эксперимента")
            self._status_label.setStyleSheet("color: #888888; border: none;")
            self._elapsed_label.setText("")
            return

        name = result.get("name", "")
        template = result.get("template", "")
        parts = [f"\u25cf {name}"]
        if template:
            parts.append(f"[{template}]")
        self._status_label.setText(" ".join(parts))
        self._status_label.setStyleSheet("color: #2ECC40; border: none;")

        started = result.get("started_at", "")
        if started:
            try:
                from datetime import datetime, timezone

                start_dt = datetime.fromisoformat(str(started))
                elapsed = datetime.now(timezone.utc) - start_dt.astimezone(timezone.utc)
                total_s = int(elapsed.total_seconds())
                h, rem = divmod(max(0, total_s), 3600)
                m, s = divmod(rem, 60)
                self._elapsed_label.setText(f"{h:02d}:{m:02d}:{s:02d}")
            except Exception:
                self._elapsed_label.setText("")
        else:
            self._elapsed_label.setText("")


# ---------------------------------------------------------------------------
# QuickLogWidget
# ---------------------------------------------------------------------------

class QuickLogWidget(QFrame):
    """Inline quick-log entry for Overview: single-line input + recent entries."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(90)
        apply_panel_frame_style(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        input_label = QLabel("Журнал:")
        input_label.setStyleSheet("color: #888888; border: none;")
        input_row.addWidget(input_label)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Заметка оператора...")
        self._input.setStyleSheet(
            "QLineEdit { background: #21262d; color: #c9d1d9; "
            "border: 1px solid #30363d; border-radius: 3px; padding: 2px 6px; }"
        )
        self._input.returnPressed.connect(self._on_submit)
        input_row.addWidget(self._input, stretch=1)

        submit_btn = QPushButton("Записать")
        submit_btn.setFixedSize(QSize(80, 24))
        apply_button_style(submit_btn, "primary", compact=True)
        submit_btn.clicked.connect(self._on_submit)
        input_row.addWidget(submit_btn)

        layout.addLayout(input_row)

        # Recent entries
        self._recent_label = QLabel("")
        self._recent_label.setStyleSheet("color: #666666; border: none; font-size: 9pt;")
        self._recent_label.setWordWrap(True)
        layout.addWidget(self._recent_label, stretch=1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10000)
        self._refresh_timer.timeout.connect(self._refresh_recent)
        self._refresh_timer.start()
        self._refresh_recent()

    @Slot()
    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({
            "cmd": "log_entry",
            "message": text,
            "source": "overview",
            "current_experiment": True,
        })
        worker.finished.connect(self._on_submit_done)
        self._workers: list[object] = getattr(self, "_workers", [])
        self._workers.append(worker)
        worker.start()
        self._input.clear()

    @Slot(dict)
    def _on_submit_done(self, result: dict) -> None:
        if result.get("ok"):
            self._refresh_recent()

    @Slot()
    def _refresh_recent(self) -> None:
        from cryodaq.gui.zmq_client import send_command

        result = send_command({"cmd": "log_get", "limit": 5, "current_experiment": True})
        if not result.get("ok"):
            return
        entries = result.get("entries", [])
        if not entries:
            self._recent_label.setText("Нет записей")
            return
        lines: list[str] = []
        for entry in entries[:5]:
            ts = str(entry.get("timestamp", ""))
            if "T" in ts:
                ts = ts.split("T")[1][:8]
            msg = str(entry.get("message", ""))
            if len(msg) > 80:
                msg = msg[:77] + "..."
            lines.append(f"{ts} — {msg}")
        self._recent_label.setText("\n".join(lines))


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
        root = create_panel_root(self)
        root.setSpacing(6)

        # 1. StatusStrip
        self._status_strip = StatusStrip()
        root.addWidget(self._status_strip)

        # 1a. Experiment status
        self._experiment_status = ExperimentStatusWidget()
        root.addWidget(self._experiment_status)

        # 2. Operator workspace
        self._experiment_workspace = ExperimentWorkspace()
        root.addWidget(self._experiment_workspace)

        # 3. TempCardGrid
        self._card_grid = TempCardGrid(self._channel_mgr)
        root.addWidget(self._card_grid)

        # 4. График с кнопками
        plot_frame = QFrame()
        apply_panel_frame_style(plot_frame, background="#111111", border="#333", radius=4)
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
            apply_button_style(btn, "neutral", compact=True)
            btn.clicked.connect(lambda checked, s=seconds: self._set_window(s))
            btn_bar.addWidget(btn)

        all_btn = QPushButton("Всё")
        all_btn.setFixedSize(QSize(50, 24))
        apply_button_style(all_btn, "neutral", compact=True)
        all_btn.clicked.connect(self._set_window_all)
        btn_bar.addWidget(all_btn)

        btn_bar.addStretch()

        # Log/Lin toggle
        self._log_btn = QPushButton("Lin Y")
        self._log_btn.setFixedSize(QSize(60, 24))
        apply_button_style(self._log_btn, "neutral", compact=True)
        self._log_btn.clicked.connect(self._toggle_log)
        self._is_log_y = False
        btn_bar.addWidget(self._log_btn)

        # Export PNG
        png_btn = QPushButton("PNG")
        png_btn.setFixedSize(QSize(60, 24))
        apply_button_style(png_btn, "neutral", compact=True)
        png_btn.clicked.connect(self._on_export_png)
        btn_bar.addWidget(png_btn)

        # Export CSV
        csv_btn = QPushButton("CSV")
        csv_btn.setFixedSize(QSize(60, 24))
        apply_button_style(csv_btn, "neutral", compact=True)
        csv_btn.clicked.connect(self._on_export_csv)
        btn_bar.addWidget(csv_btn)

        plot_root.addLayout(btn_bar)

        # PlotWidget
        self._plot = pg.PlotWidget()
        plot_root.addWidget(self._plot)

        root.addWidget(plot_frame, stretch=1)

        # 5. PressureStrip
        self._pressure_strip = PressureStrip()
        root.addWidget(self._pressure_strip)

        # 6. KeithleyStrip
        self._keithley_strip = KeithleyStrip()
        root.addWidget(self._keithley_strip)

        # 7. QuickLogWidget
        self._quick_log = QuickLogWidget()
        root.addWidget(self._quick_log)

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

    def refresh_experiment_workspace(self) -> bool:
        return self._experiment_workspace.refresh_state()

    def focus_experiment_workspace(self) -> None:
        self._experiment_workspace.focus_create_form()

    def focus_experiment_finalize(self) -> None:
        self._experiment_workspace.focus_finalize_action()

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        """Обработать показание в GUI-потоке. Маршрутизация к суб-виджетам."""
        channel = reading.channel
        self._experiment_workspace.on_reading(reading)

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
            status_bits: list[str] = []
            if self._keithley_strip._channel_state["smua"] == "on":
                status_bits.append(
                    f"A ВКЛ {self._keithley_strip._smua_data.get('power', 0.0):.1f}W"
                )
            if self._keithley_strip._channel_state["smub"] == "on":
                status_bits.append(
                    f"B ВКЛ {self._keithley_strip._smub_data.get('power', 0.0):.1f}W"
                )
            self._status_strip.set_keithley_status(" | ".join(status_bits), is_on=bool(status_bits))

        if channel.startswith("analytics/keithley_channel_state/"):
            smu_name = channel.rsplit("/", 1)[-1]
            state_name = str(reading.metadata.get("state", "off"))
            self._keithley_strip.set_channel_state(smu_name, state_name)
            status_bits: list[str] = []
            if self._keithley_strip._channel_state["smua"] == "on":
                status_bits.append(
                    f"A ВКЛ {self._keithley_strip._smua_data.get('power', 0.0):.1f}W"
                )
            elif self._keithley_strip._channel_state["smua"] == "fault":
                status_bits.append("A АВАРИЯ")
            if self._keithley_strip._channel_state["smub"] == "on":
                status_bits.append(
                    f"B ВКЛ {self._keithley_strip._smub_data.get('power', 0.0):.1f}W"
                )
            elif self._keithley_strip._channel_state["smub"] == "fault":
                status_bits.append("B АВАРИЯ")
            self._status_strip.set_keithley_status(" | ".join(status_bits), is_on=bool(status_bits))

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
    def _set_window_all(self) -> None:
        """Show full buffer range — all available data."""
        if not self._buffers:
            return
        earliest = float("inf")
        for buf in self._buffers.values():
            if buf:
                earliest = min(earliest, buf[0][0])
        if earliest == float("inf"):
            return
        span = time.time() - earliest
        self._window_s = max(span + 60.0, 300.0)  # at least 5 min

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
