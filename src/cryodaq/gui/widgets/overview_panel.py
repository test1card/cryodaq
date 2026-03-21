"""Панель обзора — домашняя вкладка CryoDAQ.

Объединяет температуры, давление, статус и Keithley в единый виджет.

Классы:
    StatusStrip — горизонтальная полоса статуса (~40px)
    CompactTempCard — мини-карточка температурного канала (~100x60)
    TempCardGrid — фиксированная сетка CompactTempCard (8 в строке)
    KeithleyStrip — полоса Keithley smua/smub (~50px)
    ExperimentStatusWidget — компактная полоса статуса эксперимента
    QuickLogWidget — ввод записи в журнал
    OverviewPanel — главный виджет вкладки «Обзор»
"""

from __future__ import annotations

import logging
import math
import shutil
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
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
from cryodaq.gui.widgets.shift_handover import ShiftBar
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
    """Мини-карточка температурного канала (~100x60px). Clickable to toggle plot visibility."""

    toggled = Signal(str)  # emits channel_id on click

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
        self._last_status: ChannelStatus = ChannelStatus.OK
        self._last_ui_update: float = 0.0
        self._current_bg: str = ""
        self._active: bool = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setMinimumSize(80, 54)
        self.setMaximumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._set_bg("#2A2A2A")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(0)

        # Строка 1: имя канала
        self._name_label = QLabel(display_name)
        name_font = QFont()
        name_font.setPointSize(8)
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet("color: #BBBBBB; border: none;")
        self._name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._name_label)

        # Строка 2: значение
        self._value_label = QLabel("---- K")
        val_font = QFont()
        val_font.setPointSize(12)
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
        """Обновить карточку по новому показанию.

        Stores data immediately but throttles UI updates to max 1 Hz.
        """
        ts = reading.timestamp.timestamp()
        value = reading.value
        status = reading.status

        # Compute dT/dt and store state (cheap, no UI)
        if status not in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
            if self._last_ts is not None and ts > self._last_ts:
                dt_s = ts - self._last_ts
                if dt_s > 0.5:
                    dv = value - (self._last_value or 0.0)
                    self._dt_dt = (dv / dt_s) * 3600.0
            self._prev_value = self._last_value
            self._prev_ts = self._last_ts

        self._last_value = value
        self._last_ts = ts
        self._last_status = status

        # Throttle UI updates to max 1 Hz
        if ts - self._last_ui_update < 1.0:
            return
        self._last_ui_update = ts
        self._flush_ui()

    def _flush_ui(self) -> None:
        """Apply buffered state to UI labels (called at most 1 Hz)."""
        status = self._last_status
        value = self._last_value

        if status in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
            if not self._has_error:
                self._has_error = True
                self._value_label.setText("ОТКЛ")
                self._value_label.setStyleSheet("color: #888888; border: none;")
                self._trend_label.setText("")
                self._set_bg("#3A3A3A")
            return

        if self._has_error:
            self._has_error = False
            self._value_label.setStyleSheet("color: #FFFFFF; border: none;")

        if value is not None:
            self._value_label.setText(f"{value:.2f} K")

        # Тренд
        abs_rate = abs(self._dt_dt)
        if abs_rate < 0.1:
            arrow = "="
        elif self._dt_dt > 0:
            arrow = "\u25b2"
        else:
            arrow = "\u25bc"
        self._trend_label.setText(f"{arrow} {self._dt_dt:+.1f} K/ч")

        # Фон — only update if changed
        if self._has_alarm:
            self._set_bg("#4A2020")
        elif abs_rate > 10:
            self._set_bg("#1E2A3A")
        else:
            self._set_bg("#2A2A2A")

    def set_alarm(self, active: bool) -> None:
        self._has_alarm = active
        if active and not self._has_error:
            self._set_bg("#4A2020")
        elif not self._has_error:
            abs_rate = abs(self._dt_dt)
            self._set_bg("#1E2A3A" if abs_rate > 10 else "#2A2A2A")

    def _set_bg(self, color: str) -> None:
        """Set background only if color actually changed."""
        if color == self._current_bg:
            return
        self._current_bg = color
        self.setStyleSheet(
            f"CompactTempCard {{ background-color: {color}; "
            f"border: 1px solid #444; border-radius: 4px; }}"
        )

    def mousePressEvent(self, event: object) -> None:  # noqa: ANN001
        self.toggled.emit(self._channel_id)

    def set_active(self, active: bool) -> None:
        self._active = active
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(1.0 if active else 0.3)
        self.setGraphicsEffect(effect)


# ---------------------------------------------------------------------------
# TempCardGrid
# ---------------------------------------------------------------------------

class _PlaceholderCard(QFrame):
    """Greyed-out placeholder for invisible / empty grid cells."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(80, 54)
        self.setMaximumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "background: #1a1a2e; border: 1px dashed #333; border-radius: 4px;"
        )


class TempCardGrid(QWidget):
    """Fixed 3x8 temperature card grid — flat positional layout.

    All Т-channels sorted by number are laid out 8 per row:
    - Row 0: Т1–Т8
    - Row 1: Т9–Т16
    - Row 2: Т17–Т24
    Invisible channels render as grey placeholders.
    """

    card_toggled = Signal(str)  # forwarded from individual cards
    _COLS = 8

    def __init__(self, channel_manager: ChannelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._cards: dict[str, CompactTempCard] = {}
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(2)

        self._build_cards()
        self._channel_mgr.on_change(self.rebuild)

    def rebuild(self) -> None:
        """Clear all cards and rebuild from current ChannelManager state."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        self._build_cards()

    def _build_cards(self) -> None:
        """Создать карточки: плоская позиционная сетка 8 в ряд."""
        all_channels = self._channel_mgr.get_all()

        # Collect all Т-channels and sort by numeric suffix
        temp_channels: list[tuple[int, str]] = []
        for ch_id in all_channels:
            if ch_id.startswith("\u0422"):  # Т
                try:
                    num = int(ch_id[1:])
                except ValueError:
                    continue
                temp_channels.append((num, ch_id))
        temp_channels.sort()

        for idx, (_num, ch_id) in enumerate(temp_channels):
            row = idx // self._COLS
            col = idx % self._COLS
            info = all_channels.get(ch_id, {})
            visible = info.get("visible", True)
            if visible:
                display = self._channel_mgr.get_display_name(ch_id)
                card = CompactTempCard(ch_id, display)
                card.toggled.connect(self.card_toggled.emit)
                self._cards[ch_id] = card
                self._grid.addWidget(card, row, col)
            else:
                self._grid.addWidget(_PlaceholderCard(), row, col)

    def get_cards(self) -> dict[str, CompactTempCard]:
        return self._cards


# ---------------------------------------------------------------------------
# PressureCard
# ---------------------------------------------------------------------------

class PressureCard(QFrame):
    """Карточка текущего давления с цветовой индикацией вакуума."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._current_bg = ""
        self._set_bg("#2A2A2A")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(0)

        # Title
        self._title = QLabel("Давление")
        title_font = QFont()
        title_font.setPointSize(8)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #BBBBBB; border: none;")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        # Value
        self._value_label = QLabel("---- mbar")
        val_font = QFont()
        val_font.setPointSize(14)
        val_font.setBold(True)
        self._value_label.setFont(val_font)
        self._value_label.setStyleSheet("color: #FFFFFF; border: none;")
        self._value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value_label)

        self._last_value: float | None = None

    def update_pressure(self, reading: Reading) -> None:
        """Обновить карточку давления."""
        value = reading.value

        if reading.status in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
            self._value_label.setText("ОТКЛ")
            self._value_label.setStyleSheet("color: #888888; border: none;")
            self._set_bg("#3A3A3A")
            return

        self._last_value = value

        # Format: compact scientific for small values
        if value < 0.01:
            text = f"{value:.1e} mbar"
        else:
            text = f"{value:.2f} mbar"
        self._value_label.setText(text)

        # Color by vacuum quality
        if value > 1.0:
            # Atmosphere
            self._value_label.setStyleSheet("color: #FF4444; border: none;")
            self._set_bg("#4A2020")
        elif value > 1e-2:
            # Bad vacuum
            self._value_label.setStyleSheet("color: #FF8C00; border: none;")
            self._set_bg("#3A2A1A")
        elif value > 1e-4:
            # Transitional
            self._value_label.setStyleSheet("color: #FFD700; border: none;")
            self._set_bg("#2A2A1A")
        else:
            # Good vacuum
            self._value_label.setStyleSheet("color: #2ECC40; border: none;")
            self._set_bg("#1A2A1A")

    def _set_bg(self, color: str) -> None:
        if color == self._current_bg:
            return
        self._current_bg = color
        self.setStyleSheet(
            f"PressureCard {{ background-color: {color}; "
            f"border: 1px solid #444; border-radius: 4px; }}"
        )


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

        layout.addStretch()

        # Состояние
        self._smua_data: dict[str, float] = {}
        self._smub_data: dict[str, float] = {}
        self._channel_state: dict[str, str] = {"smua": "off", "smub": "off"}

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

        self._worker = None

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        # Immediate first poll (deferred 200ms to let ZMQ connect)
        QTimer.singleShot(200, self._refresh)

    @Slot()
    def _refresh(self) -> None:
        if self._worker is not None and not self._worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._worker = ZmqCommandWorker({"cmd": "experiment_status"})
        self._worker.finished.connect(self._on_refresh_result)
        self._worker.start()

    @Slot(dict)
    def _on_refresh_result(self, result: dict) -> None:
        exp = result.get("active_experiment")
        if not result.get("ok") or not exp:
            self._status_label.setText("Нет активного эксперимента")
            self._status_label.setStyleSheet("color: #888888; border: none;")
            self._elapsed_label.setText("")
            return

        name = exp.get("name", "")
        template = exp.get("template_id", "")
        parts = [f"\u25cf {name}"]
        if template:
            parts.append(f"[{template}]")
        phase = result.get("current_phase")
        if phase:
            _phase_labels = {
                "preparation": "Подготовка", "vacuum": "Откачка",
                "cooldown": "Захолаживание", "measurement": "Измерение",
                "warmup": "Растепление", "teardown": "Разборка",
            }
            parts.append(_phase_labels.get(phase, phase))
        self._status_label.setText(" ".join(parts))
        self._status_label.setStyleSheet("color: #2ECC40; border: none;")

        started = exp.get("start_time", "")
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

        self._refresh_worker = None

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10000)
        self._refresh_timer.timeout.connect(self._refresh_recent)
        self._refresh_timer.start()

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
        if self._refresh_worker is not None and not self._refresh_worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._refresh_worker = ZmqCommandWorker({"cmd": "log_get", "limit": 5, "current_experiment": True})
        self._refresh_worker.finished.connect(self._on_refresh_result)
        self._refresh_worker.start()

    @Slot(dict)
    def _on_refresh_result(self, result: dict) -> None:
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

    Объединяет StatusStrip, TempCardGrid, графики температуры и давления, KeithleyStrip.
    """

    _reading_received = Signal(object)

    def __init__(self, channel_manager: ChannelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager

        # Буферы данных: channel_id -> deque[(ts, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # plot items: channel_id -> PlotDataItem
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        # Channel visibility for click-toggle
        self._channel_visible: dict[str, bool] = {}
        # Pressure buffer
        self._pressure_buffer: deque[tuple[float, float]] = deque(maxlen=_BUFFER_MAXLEN)
        self._pressure_plot_item: pg.PlotDataItem | None = None
        # Текущее окно времени (секунды)
        self._window_s = _DEFAULT_WINDOW_S

        self._build_ui()
        self._init_plot()

        # Signal/Slot для потокобезопасности
        self._reading_received.connect(self._handle_reading)

        # Таймер обновления графика — 1 Гц
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(1000)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start()

        # Load 1 hour of history from SQLite on startup (deferred to avoid blocking constructor)
        self._history_worker = None
        QTimer.singleShot(500, self._load_initial_history)

        # Sync plot items when channels change
        self._channel_mgr.on_change(self._on_channels_changed)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = create_panel_root(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(2)

        # ============ 1. STATUS BARS (full width, compact) ============
        self._status_strip = StatusStrip()
        root.addWidget(self._status_strip)

        # Experiment status + Shift bar in one row
        exp_shift_row = QHBoxLayout()
        exp_shift_row.setSpacing(4)
        self._experiment_status = ExperimentStatusWidget()
        exp_shift_row.addWidget(self._experiment_status, stretch=1)
        self._shift_bar = ShiftBar()
        exp_shift_row.addWidget(self._shift_bar, stretch=1)
        root.addLayout(exp_shift_row)

        # ============ 2. TEMPERATURE CARDS + PRESSURE CARD ============
        self._card_grid = TempCardGrid(self._channel_mgr)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(4)
        cards_row.addWidget(self._card_grid, stretch=1)

        self._pressure_card = PressureCard()
        self._pressure_card.setFixedWidth(160)
        cards_row.addWidget(self._pressure_card)

        root.addLayout(cards_row)

        # Wire card toggle signal (grid-level — survives rebuild)
        self._card_grid.card_toggled.connect(self._on_card_toggled)

        # ============ 3. BUTTON BAR (full width) ============
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(6)

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

        self._log_btn = QPushButton("Lin Y")
        self._log_btn.setFixedSize(QSize(60, 24))
        apply_button_style(self._log_btn, "neutral", compact=True)
        self._log_btn.clicked.connect(self._toggle_log)
        self._is_log_y = False
        btn_bar.addWidget(self._log_btn)

        png_btn = QPushButton("PNG")
        png_btn.setFixedSize(QSize(60, 24))
        apply_button_style(png_btn, "neutral", compact=True)
        png_btn.clicked.connect(self._on_export_png)
        btn_bar.addWidget(png_btn)

        csv_btn = QPushButton("CSV")
        csv_btn.setFixedSize(QSize(60, 24))
        apply_button_style(csv_btn, "neutral", compact=True)
        csv_btn.clicked.connect(self._on_export_csv)
        btn_bar.addWidget(csv_btn)

        root.addLayout(btn_bar)

        # ============ 4. GRAPHS — vertical splitter (temp ~70%, pressure ~30%) ============
        graph_splitter = QSplitter(Qt.Orientation.Vertical)
        graph_splitter.setHandleWidth(3)
        graph_splitter.setStyleSheet("QSplitter::handle { background-color: #333333; }")

        # Temperature plot
        temp_axis = pg.DateAxisItem(orientation="bottom")
        self._plot = pg.PlotWidget(axisItems={"bottom": temp_axis})
        graph_splitter.addWidget(self._plot)

        # Pressure plot (linked X axis)
        pressure_axis = pg.DateAxisItem(orientation="bottom")
        self._pressure_plot = pg.PlotWidget(axisItems={"bottom": pressure_axis})
        self._pressure_plot.setXLink(self._plot)
        graph_splitter.addWidget(self._pressure_plot)

        graph_splitter.setStretchFactor(0, 7)
        graph_splitter.setStretchFactor(1, 3)

        root.addWidget(graph_splitter, stretch=1)

        # ============ 5. BOTTOM BAR: Keithley left, QuickLog right ============
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(4)

        self._keithley_strip = KeithleyStrip()
        bottom_bar.addWidget(self._keithley_strip, stretch=55)

        self._quick_log = QuickLogWidget()
        self._quick_log.setFixedHeight(40)
        bottom_bar.addWidget(self._quick_log, stretch=45)

        root.addLayout(bottom_bar)

    def _init_plot(self) -> None:
        """Настроить внешний вид основного графика и графика давления."""
        # --- Temperature plot ---
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

        visible_ids = self._channel_mgr.get_all_visible()
        temp_ids = [ch for ch in visible_ids if ch.startswith("\u0422")]
        for idx, ch_id in enumerate(temp_ids):
            display = self._channel_mgr.get_display_name(ch_id)
            color = _LINE_PALETTE[idx % len(_LINE_PALETTE)]
            pen = pg.mkPen(color=color, width=1.5)
            item = pw.plot([], [], pen=pen, name=display)
            item.setDownsampling(auto=True, method="peak")
            item.setClipToView(True)
            self._plot_items[ch_id] = item
            self._buffers[ch_id] = deque(maxlen=_BUFFER_MAXLEN)
            self._channel_visible[ch_id] = True

        # --- Pressure plot ---
        pp = self._pressure_plot
        pp.setBackground("#111111")

        ppi = pp.getPlotItem()
        ppi.setLabel("left", "\u0414\u0430\u0432\u043b\u0435\u043d\u0438\u0435", units="mbar", color="#AAAAAA")
        ppi.setLabel("bottom", "\u0412\u0440\u0435\u043c\u044f", color="#AAAAAA")
        ppi.setLogMode(x=False, y=True)
        ppi.showGrid(x=True, y=True, alpha=0.3)
        ppi.enableAutoRange(axis="y", enable=True)

        for axis_name in ("left", "bottom", "top", "right"):
            axis = ppi.getAxis(axis_name)
            if axis is not None:
                axis.setPen(pg.mkPen(color="#444444"))
                axis.setTextPen(pg.mkPen(color="#AAAAAA"))

        pen = pg.mkPen(color="#17BECF", width=1.5)
        self._pressure_plot_item = pp.plot([], [], pen=pen)
        self._pressure_plot_item.setDownsampling(auto=True, method="peak")
        self._pressure_plot_item.setClipToView(True)

        # Sync Y-axis widths between temp and pressure plots
        _AXIS_WIDTH = 60
        self._plot.getPlotItem().getAxis("left").setWidth(_AXIS_WIDTH)
        self._pressure_plot.getPlotItem().getAxis("left").setWidth(_AXIS_WIDTH)

        # --- Cooldown prediction overlay on temperature plot ---
        self._pred_curve = self._plot.plot(
            [], [],
            pen=pg.mkPen(color="#ff7b72", width=2, style=Qt.PenStyle.DashLine),
            name="Прогноз",
        )
        self._pred_curve.setVisible(False)

        self._ci_upper_curve = self._plot.plot([], [], pen=None)
        self._ci_lower_curve = self._plot.plot([], [], pen=None)
        self._ci_band = pg.FillBetweenItem(
            self._ci_upper_curve, self._ci_lower_curve,
            brush=pg.mkBrush(255, 123, 114, 30),
        )
        self._plot.addItem(self._ci_band)
        self._ci_band.setVisible(False)

        from PySide6.QtWidgets import QLabel as _Label
        self._eta_overlay = _Label("", self._plot)
        self._eta_overlay.setStyleSheet(
            "color: #ff7b72; font-size: 12pt; font-weight: bold; "
            "background: rgba(17,17,17,200); padding: 4px 8px; border-radius: 4px;"
        )
        self._eta_overlay.setVisible(False)

    # ------------------------------------------------------------------
    # Channel change sync
    # ------------------------------------------------------------------

    def _on_channels_changed(self) -> None:
        """Rebuild plot items to match current channel config."""
        new_visible = [ch for ch in self._channel_mgr.get_all_visible() if ch.startswith("\u0422")]
        old_ids = set(self._plot_items.keys())
        new_ids = set(new_visible)

        for ch_id in old_ids - new_ids:
            item = self._plot_items.pop(ch_id)
            self._plot.removeItem(item)
            self._buffers.pop(ch_id, None)
            self._channel_visible.pop(ch_id, None)

        for ch_id in new_ids - old_ids:
            idx = new_visible.index(ch_id)
            display = self._channel_mgr.get_display_name(ch_id)
            color = _LINE_PALETTE[idx % len(_LINE_PALETTE)]
            pen = pg.mkPen(color=color, width=1.5)
            item = self._plot.plot([], [], pen=pen, name=display)
            item.setDownsampling(auto=True, method="peak")
            item.setClipToView(True)
            self._plot_items[ch_id] = item
            self._buffers[ch_id] = deque(maxlen=_BUFFER_MAXLEN)
            self._channel_visible[ch_id] = True

    # ------------------------------------------------------------------
    # Публичный интерфейс
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Принять показание (потокобезопасно через Signal)."""
        self._reading_received.emit(reading)

    # ------------------------------------------------------------------
    # Card toggle
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_card_toggled(self, channel_id: str) -> None:
        visible = not self._channel_visible.get(channel_id, True)
        self._channel_visible[channel_id] = visible
        item = self._plot_items.get(channel_id)
        if item is not None:
            item.setVisible(visible)
        card = self._card_grid.get_cards().get(channel_id)
        if card is not None:
            card.set_active(visible)

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

        # Давление → карточка + буфер графика
        if reading.unit == "mbar":
            self._pressure_card.update_pressure(reading)
            self._pressure_buffer.append(
                (reading.timestamp.timestamp(), reading.value)
            )

        # Cooldown prediction
        if channel.endswith("/cooldown_eta"):
            self._update_cooldown_prediction(reading)

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

    def _update_cooldown_prediction(self, reading: Reading) -> None:
        """Draw ML prediction curve on temperature chart."""
        meta = reading.metadata or {}
        active = meta.get("cooldown_active", False)

        if not active:
            self._pred_curve.setVisible(False)
            self._ci_band.setVisible(False)
            self._eta_overlay.setVisible(False)
            return

        future_t = meta.get("future_t", [])
        future_mean = meta.get("future_T_cold_mean", [])
        future_upper = meta.get("future_T_cold_upper", [])
        future_lower = meta.get("future_T_cold_lower", [])
        cooldown_start = meta.get("cooldown_start_ts", 0)

        if cooldown_start and future_t and future_mean:
            abs_ts = [cooldown_start + h * 3600 for h in future_t]
            self._pred_curve.setData(abs_ts, future_mean)
            self._pred_curve.setVisible(True)

            if (future_upper and future_lower
                    and len(future_upper) == len(future_t)):
                self._ci_upper_curve.setData(abs_ts, future_upper)
                self._ci_lower_curve.setData(abs_ts, future_lower)
                self._ci_band.setVisible(True)
            else:
                self._ci_band.setVisible(False)
        else:
            self._pred_curve.setVisible(False)
            self._ci_band.setVisible(False)

        # ETA overlay
        t_rem = meta.get("t_remaining_hours", 0)
        ci_raw = meta.get("t_remaining_ci68", (0, 0))
        ci = ci_raw[1] if isinstance(ci_raw, (list, tuple)) and len(ci_raw) > 1 else 0
        if t_rem > 0:
            if t_rem < 1:
                text = f"ETA: {t_rem * 60:.0f} мин (\u00b1{ci * 60:.0f})"
            else:
                text = f"ETA: {t_rem:.1f} ч (\u00b1{ci:.1f})"
            self._eta_overlay.setText(text)
            self._eta_overlay.setVisible(True)
            pw = self._plot.width()
            self._eta_overlay.adjustSize()
            self._eta_overlay.move(max(0, pw - self._eta_overlay.width() - 10), 10)
        else:
            self._eta_overlay.setVisible(False)

    @Slot()
    def _refresh_plot(self) -> None:
        """Обновить все линии на графиках (1 Гц)."""
        now = time.time()
        x_min = now - self._window_s

        # Temperature lines
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
            # 75% data / 25% forecast zone
            forecast_s = self._window_s / 3.0
            x_max = now + forecast_s
            # Extend further if prediction curve goes beyond
            if self._pred_curve.isVisible():
                pred_xs = self._pred_curve.getData()[0]
                if pred_xs is not None and len(pred_xs) > 0:
                    x_max = max(x_max, float(pred_xs[-1]))
            self._plot.getPlotItem().setXRange(x_min, x_max, padding=0)

        # Pressure line (X range synced via setXLink)
        if self._pressure_buffer:
            xs = [t for t, _ in self._pressure_buffer if t >= x_min]
            ys = [v for t, v in self._pressure_buffer if t >= x_min]
            if self._pressure_plot_item is not None:
                self._pressure_plot_item.setData(xs, ys)

    # ------------------------------------------------------------------
    # Кнопки управления
    # ------------------------------------------------------------------

    def _set_window(self, seconds: int) -> None:
        self._window_s = float(seconds)
        hours = max(1, seconds // 3600)
        self._load_history(hours=hours)

    @Slot()
    def _set_window_all(self) -> None:
        """Show full buffer range — load full history from SQLite then expand window."""
        self._load_history(hours=24)

    def _load_initial_history(self) -> None:
        """Load 1 hour of history from SQLite on startup."""
        self._load_history(hours=1)

    def _load_history(self, hours: int = 1) -> None:
        """Query readings_history from engine and populate plot buffers."""
        if self._history_worker is not None and not self._history_worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        now = time.time()
        channels = list(self._buffers.keys())
        # Also include pressure channels — unit-based match, use broad query
        cmd = {
            "cmd": "readings_history",
            "from_ts": now - hours * 3600,
            "to_ts": now,
            "limit_per_channel": max(_BUFFER_MAXLEN, hours * 360),
        }
        self._history_worker = ZmqCommandWorker(cmd)
        self._history_hours = hours
        self._history_worker.finished.connect(self._on_history_loaded)
        self._history_worker.start()

    @Slot(dict)
    def _on_history_loaded(self, result: dict) -> None:
        """Populate buffers with historical data from SQLite."""
        if not result.get("ok"):
            logger.debug("readings_history failed: %s", result.get("error"))
            return
        data: dict[str, list] = result.get("data", {})
        loaded = 0
        for channel, points in data.items():
            if not points:
                continue
            # Temperature channels — match by short_id (Т1, Т2, ...)
            short_id = channel.split(" ")[0] if " " in channel else channel
            if short_id in self._buffers:
                buf = self._buffers[short_id]
                # Only prepend points older than existing data
                existing_min_ts = buf[0][0] if buf else float("inf")
                new_points = [(ts, val) for ts, val in points if ts < existing_min_ts]
                if new_points:
                    # Prepend: create merged deque (historical + existing)
                    existing = list(buf)
                    merged = new_points + existing
                    buf.clear()
                    buf.extend(merged[-_BUFFER_MAXLEN:])
                    loaded += len(new_points)
            # Pressure channel
            if any(isinstance(pt, (list, tuple)) and len(pt) >= 2 for pt in points[:1]):
                # Check if this is a pressure channel (unit=mbar) by channel name patterns
                if "mbar" in channel.lower() or "pressure" in channel.lower() or channel.startswith("P"):
                    existing_min_ts = self._pressure_buffer[0][0] if self._pressure_buffer else float("inf")
                    new_points = [(ts, val) for ts, val in points if ts < existing_min_ts]
                    if new_points:
                        existing = list(self._pressure_buffer)
                        merged = new_points + existing
                        self._pressure_buffer.clear()
                        self._pressure_buffer.extend(merged[-_BUFFER_MAXLEN:])
                        loaded += len(new_points)

        if loaded > 0:
            logger.info("Загружено %d исторических точек из SQLite", loaded)
            # Expand window to show all loaded data
            earliest = float("inf")
            for buf in self._buffers.values():
                if buf:
                    earliest = min(earliest, buf[0][0])
            if self._pressure_buffer:
                earliest = min(earliest, self._pressure_buffer[0][0])
            if earliest < float("inf"):
                span = time.time() - earliest
                self._window_s = max(span + 60.0, 300.0)

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
            with open(path, "w", encoding="utf-8-sig") as f:
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
