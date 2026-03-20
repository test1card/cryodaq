"""Панель статуса приборов (InstrumentStatusPanel).

Отображает карточки для каждого подключённого прибора с индикацией
состояния: зелёный (норма), жёлтый (предупреждение), красный (ошибка).
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.widgets.sensor_diag_panel import SensorDiagPanel

logger = logging.getLogger(__name__)

# Цвета состояния прибора
_COLOR_OK = "#2ECC40"
_COLOR_WARN = "#FFDC00"
_COLOR_ERROR = "#FF4136"
_COLOR_OFFLINE = "#AAAAAA"

# Таймаут «живости» прибора (секунды без данных → offline)
_LIVENESS_TIMEOUT_S = 10.0


class _InstrumentCard(QFrame):
    """Карточка одного прибора."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._last_reading_time: float = 0.0
        self._total_readings: int = 0
        self._error_count: int = 0
        self._last_status: ChannelStatus = ChannelStatus.OK

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setMinimumSize(240, 140)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._build_ui()
        self._update_style(_COLOR_OFFLINE)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Строка заголовка: индикатор + имя
        header = QHBoxLayout()

        self._indicator = QLabel("⬤")
        self._indicator.setFont(QFont("", 14))
        header.addWidget(self._indicator)

        self._name_label = QLabel(self._name)
        self._name_label.setFont(QFont("", 12, QFont.Weight.Bold))
        header.addWidget(self._name_label)
        header.addStretch()

        layout.addLayout(header)

        # Статус
        self._status_label = QLabel("Статус: ожидание данных")
        layout.addWidget(self._status_label)

        # Последний ответ
        self._last_response_label = QLabel("Последний ответ: —")
        layout.addWidget(self._last_response_label)

        # Счётчики
        self._counters_label = QLabel("Показания: 0 | Ошибки: 0")
        layout.addWidget(self._counters_label)

    def update_from_reading(self, reading: Reading) -> None:
        """Обновить карточку по новому показанию."""
        now = time.monotonic()
        self._last_reading_time = now
        self._total_readings += 1
        self._last_status = reading.status

        if reading.status != ChannelStatus.OK:
            self._error_count += 1

        self._refresh_display()

    def refresh_liveness(self) -> None:
        """Проверить таймаут живости и обновить индикатор."""
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Обновить все метки и цвет индикатора."""
        now = time.monotonic()

        # Определить цвет
        if self._last_reading_time == 0.0:
            color = _COLOR_OFFLINE
            status_text = "Нет данных"
        elif now - self._last_reading_time > _LIVENESS_TIMEOUT_S:
            color = _COLOR_ERROR
            status_text = "Нет связи"
        elif self._last_status != ChannelStatus.OK:
            color = _COLOR_WARN
            status_text = f"Предупреждение ({self._last_status.value})"
        else:
            color = _COLOR_OK
            status_text = "Норма"

        self._update_style(color)
        self._status_label.setText(f"Статус: {status_text}")

        # Время последнего ответа
        if self._last_reading_time > 0:
            elapsed = now - self._last_reading_time
            if elapsed < 1.0:
                time_text = "только что"
            elif elapsed < 60:
                time_text = f"{elapsed:.0f} с назад"
            else:
                time_text = f"{elapsed / 60:.0f} мин назад"
            self._last_response_label.setText(f"Последний ответ: {time_text}")

        # Счётчики
        self._counters_label.setText(
            f"Показания: {self._total_readings} | Ошибки: {self._error_count}"
        )

    def _update_style(self, color: str) -> None:
        """Обновить цвет индикатора и рамки."""
        self._indicator.setStyleSheet(f"color: {color};")
        self.setStyleSheet(
            f"_InstrumentCard {{ border: 2px solid {color}; border-radius: 6px; "
            f"background-color: #1a1a2e; }}"
        )


class InstrumentStatusPanel(QWidget):
    """Панель статуса всех приборов.

    Автоматически создаёт карточки по мере поступления данных.
    Обновляет индикаторы живости каждую секунду.
    """

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._cards: dict[str, _InstrumentCard] = {}

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        # Таймер обновления живости
        from PySide6.QtCore import QTimer

        self._liveness_timer = QTimer(self)
        self._liveness_timer.setInterval(1000)
        self._liveness_timer.timeout.connect(self._refresh_all_liveness)
        self._liveness_timer.start()

    @property
    def sensor_diag_panel(self) -> SensorDiagPanel:
        """Expose diagnostics panel for status bar integration."""
        return self._sensor_diag

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        self._scroll_content = QWidget()
        scroll_layout = QVBoxLayout(self._scroll_content)
        scroll_layout.setSpacing(8)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(8)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.addWidget(self._container)

        # Sensor diagnostics section below instrument cards
        self._sensor_diag = SensorDiagPanel()
        scroll_layout.addWidget(self._sensor_diag)

        scroll_layout.addStretch()
        scroll.setWidget(self._scroll_content)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Принять Reading (потокобезопасно)."""
        self._reading_signal.emit(reading)

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        """Обработать Reading, определить прибор, обновить карточку."""
        instrument_id = self._extract_instrument_id(reading)
        if not instrument_id:
            return

        if instrument_id not in self._cards:
            card = _InstrumentCard(instrument_id)
            self._cards[instrument_id] = card

            # Расположить в сетке (3 колонки)
            idx = len(self._cards) - 1
            row, col = divmod(idx, 3)
            self._grid.addWidget(card, row, col)

        self._cards[instrument_id].update_from_reading(reading)

    @Slot()
    def _refresh_all_liveness(self) -> None:
        """Обновить индикаторы живости для всех карточек."""
        for card in self._cards.values():
            card.refresh_liveness()

    @staticmethod
    def _extract_instrument_id(reading: Reading) -> str:
        """Извлечь идентификатор прибора из Reading.

        Приоритет:
        1. reading.instrument_id (first-class field)
        2. Первая часть channel до «/» (для Keithley: «Keithley_1/smua/...»)
        3. Имя канала, начинающееся с «Т» → определяем по номеру (Т1-8 → LS218_1 и т.д.)
        """
        # Из first-class поля
        inst_id = reading.instrument_id
        if inst_id:
            return inst_id

        channel = reading.channel

        # Keithley-стиль каналов: «Name/smua/voltage»
        if "/" in channel:
            return channel.split("/")[0]

        # Аналитика
        if channel.startswith("analytics/"):
            return ""

        # LakeShore: по номеру Т-канала
        if channel.startswith("Т"):
            try:
                # «Т7 Детектор» → 7
                num = int(channel[1:].split(" ")[0])
                if 1 <= num <= 8:
                    return "LS218_1"
                if 9 <= num <= 16:
                    return "LS218_2"
                if 17 <= num <= 24:
                    return "LS218_3"
            except (ValueError, IndexError):
                pass

        return ""
