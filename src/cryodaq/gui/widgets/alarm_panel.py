"""Панель тревог (AlarmPanel).

Отображает таблицу тревог с цветовой индикацией по severity.
Позволяет оператору подтверждать тревоги (acknowledge).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

# Цвета severity
_SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": "#FF4136",
    "WARNING": "#FF851B",
    "INFO": "#0074D9",
}

# Иконки severity (Unicode)
_SEVERITY_ICONS: dict[str, str] = {
    "CRITICAL": "🔴",
    "WARNING": "🟡",
    "INFO": "🔵",
}

# Порядок сортировки (чем меньше — тем выше в таблице)
_SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 0,
    "WARNING": 1,
    "INFO": 2,
}

# Столбцы таблицы
_COLUMNS = [
    "Уровень",
    "Имя",
    "Канал",
    "Значение",
    "Порог",
    "Время",
    "Срабат.",
    "Действие",
]


@dataclass
class _AlarmRow:
    """Внутреннее состояние одной строки тревоги."""

    severity: str
    name: str
    channel: str
    value: float
    threshold: float
    first_triggered: float  # monotonic time
    trigger_count: int
    state: str  # "ok", "active", "acknowledged"


class AlarmPanel(QWidget):
    """Панель отображения и управления тревогами.

    Показывает таблицу с текущими и историческими тревогами.
    Тревоги с severity CRITICAL отображаются вверху.
    """

    # Внутренний сигнал для потокобезопасного обновления
    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._alarms: dict[str, _AlarmRow] = {}

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Таблица тревог
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table)

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
        """Обработать Reading и обновить таблицу.

        Alarm-информация приходит через metadata от AlarmEngine
        (канал вида ``alarm/{alarm_name}``).
        """
        channel = reading.channel
        meta = reading.metadata

        # Только каналы алармов содержат информацию о тревогах
        if not meta.get("alarm_name"):
            return

        alarm_name = meta["alarm_name"]
        severity = meta.get("severity", "INFO").upper()
        event_type = meta.get("event_type", "")
        threshold = meta.get("threshold", 0.0)

        if alarm_name in self._alarms:
            row = self._alarms[alarm_name]
            row.value = reading.value
            row.channel = meta.get("channel", channel)
            row.trigger_count += 1 if event_type == "activated" else 0
            row.state = event_type if event_type in ("active", "cleared", "acknowledged") else row.state
        else:
            row = _AlarmRow(
                severity=severity,
                name=alarm_name,
                channel=meta.get("channel", channel),
                value=reading.value,
                threshold=threshold,
                first_triggered=time.monotonic(),
                trigger_count=1 if event_type == "activated" else 0,
                state=event_type if event_type else "ok",
            )
            self._alarms[alarm_name] = row

        self._refresh_table()

    def _refresh_table(self) -> None:
        """Перестроить таблицу, отсортировав по severity."""
        sorted_alarms = sorted(
            self._alarms.values(),
            key=lambda a: (_SEVERITY_ORDER.get(a.severity, 99), a.name),
        )

        self._table.setRowCount(len(sorted_alarms))

        for row_idx, alarm in enumerate(sorted_alarms):
            color = QColor(_SEVERITY_COLORS.get(alarm.severity, "#AAAAAA"))
            icon_text = _SEVERITY_ICONS.get(alarm.severity, "")

            # Уровень
            severity_item = QTableWidgetItem(f"{icon_text} {alarm.severity}")
            severity_item.setForeground(color)
            severity_item.setFont(QFont("", -1, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, severity_item)

            # Имя
            self._table.setItem(row_idx, 1, QTableWidgetItem(alarm.name))

            # Канал
            self._table.setItem(row_idx, 2, QTableWidgetItem(alarm.channel))

            # Значение
            value_item = QTableWidgetItem(f"{alarm.value:.4g}")
            if alarm.state == "active":
                value_item.setForeground(color)
                value_item.setFont(QFont("", -1, QFont.Weight.Bold))
            self._table.setItem(row_idx, 3, value_item)

            # Порог
            self._table.setItem(row_idx, 4, QTableWidgetItem(f"{alarm.threshold:.4g}"))

            # Время
            elapsed = time.monotonic() - alarm.first_triggered
            if elapsed < 60:
                time_text = f"{elapsed:.0f} с назад"
            elif elapsed < 3600:
                time_text = f"{elapsed / 60:.0f} мин назад"
            else:
                time_text = f"{elapsed / 3600:.1f} ч назад"
            self._table.setItem(row_idx, 5, QTableWidgetItem(time_text))

            # Счётчик срабатываний
            self._table.setItem(row_idx, 6, QTableWidgetItem(str(alarm.trigger_count)))

            # Кнопка подтверждения
            if alarm.state == "active":
                btn = QPushButton("Подтвердить")
                btn.setStyleSheet(
                    f"background-color: {_SEVERITY_COLORS.get(alarm.severity, '#666')}; "
                    "color: white; border: none; padding: 4px 8px; border-radius: 3px;"
                )
                btn.clicked.connect(lambda checked=False, name=alarm.name: self._acknowledge(name))
                self._table.setCellWidget(row_idx, 7, btn)
            else:
                state_text = {
                    "ok": "Норма",
                    "cleared": "Сброшена",
                    "acknowledged": "Подтв.",
                    "activated": "Активна",
                }.get(alarm.state, alarm.state)
                self._table.setItem(row_idx, 7, QTableWidgetItem(state_text))

    def _acknowledge(self, alarm_name: str) -> None:
        """Подтвердить тревогу."""
        if alarm_name in self._alarms:
            self._alarms[alarm_name].state = "acknowledged"
            self._refresh_table()
            logger.info("Тревога '%s' подтверждена оператором", alarm_name)
