"""Панель тревог (AlarmPanel).

Отображает таблицу тревог с цветовой индикацией по severity.
Позволяет оператору подтверждать тревоги (acknowledge).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

# Цвета severity
_SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": theme.STATUS_FAULT,
    "WARNING": theme.STATUS_WARNING,
    "INFO": theme.STATUS_INFO,
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

# Канонизация event_type (от AlarmEngine) → внутреннее состояние строки
_EVENT_TO_STATE: dict[str, str] = {
    "activated": "active",
    "acknowledged": "acknowledged",
    "cleared": "cleared",
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

    Поддерживает два источника:
    - v1: AlarmEngine readings через on_reading()
    - v2: AlarmEngine v2 polling через alarm_v2_status command (каждые 3 с)
    """

    # Внутренний сигнал для потокобезопасного обновления
    _reading_signal = Signal(object)
    # Сигнал для обновления счётчика v2 алармов в overview
    v2_alarm_count_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._alarms: dict[str, _AlarmRow] = {}
        # v2: alarm_id → {level, message, triggered_at, channels}
        self._v2_alarms: dict[str, dict] = {}
        self._workers: list[ZmqCommandWorker] = []

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        # Polling timer for alarm_v2_status
        self._v2_poll_timer = QTimer(self)
        self._v2_poll_timer.setInterval(3000)  # 3 seconds
        self._v2_poll_timer.timeout.connect(self._poll_v2_status)
        self._v2_poll_timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # --- v1 alarm table ---
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

        # --- v2 alarm section ---
        v2_label = QLabel("Алармы v2 (физические)")
        v2_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(v2_label)

        _V2_COLUMNS = ["Уровень", "Alarm ID", "Сообщение", "Каналы", "Время", "Действие"]
        self._v2_table = QTableWidget(0, len(_V2_COLUMNS))
        self._v2_table.setHorizontalHeaderLabels(_V2_COLUMNS)
        self._v2_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._v2_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._v2_table.setAlternatingRowColors(True)
        self._v2_table.verticalHeader().setVisible(False)
        self._v2_table.setMaximumHeight(200)

        v2_header = self._v2_table.horizontalHeader()
        v2_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v2_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        v2_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._v2_table)

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
            row.state = _EVENT_TO_STATE.get(event_type, row.state)
        else:
            row = _AlarmRow(
                severity=severity,
                name=alarm_name,
                channel=meta.get("channel", channel),
                value=reading.value,
                threshold=threshold,
                first_triggered=time.monotonic(),
                trigger_count=1 if event_type == "activated" else 0,
                state=_EVENT_TO_STATE.get(event_type, "ok"),
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
                    f"background-color: {_SEVERITY_COLORS.get(alarm.severity, theme.STONE_400)}; "
                    f"color: {theme.TEXT_INVERSE}; border: none; padding: {theme.SPACE_1}px {theme.SPACE_2}px; border-radius: {theme.RADIUS_SM}px;"
                )
                btn.clicked.connect(lambda checked=False, name=alarm.name: self._acknowledge(name))
                self._table.setCellWidget(row_idx, 7, btn)
            else:
                state_text = {
                    "ok": "Норма",
                    "cleared": "Сброшена",
                    "acknowledged": "Подтв.",
                }.get(alarm.state, alarm.state)
                self._table.setItem(row_idx, 7, QTableWidgetItem(state_text))

    def _acknowledge(self, alarm_name: str) -> None:
        """Send acknowledge to engine via ZMQ (non-blocking)."""
        worker = ZmqCommandWorker({"cmd": "alarm_acknowledge", "alarm_name": alarm_name})
        worker.finished.connect(lambda result, name=alarm_name: self._on_ack_result(result, name))
        self._workers.append(worker)
        worker.start()

    def _on_ack_result(self, result: dict, alarm_name: str) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            logger.info("Тревога '%s' подтверждена через engine", alarm_name)
        else:
            logger.warning("Ошибка подтверждения тревоги '%s': %s", alarm_name, result.get("error"))

    # ------------------------------------------------------------------
    # Alarm Engine v2 polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll_v2_status(self) -> None:
        """Poll alarm_v2_status from engine and refresh v2 table (non-blocking)."""
        # Skip if a poll worker is already running
        if any(w.isRunning() for w in self._workers if getattr(w, "_poll_marker", False)):
            return
        worker = ZmqCommandWorker({"cmd": "alarm_v2_status"})
        worker._poll_marker = True  # type: ignore[attr-defined]
        worker.finished.connect(self._on_poll_v2_result)
        self._workers.append(worker)
        worker.start()

    def _on_poll_v2_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            self.update_v2_status(result)

    def update_v2_status(self, payload: dict) -> None:
        """Update v2 alarm table from alarm_v2_status response payload."""
        active: dict = payload.get("active", {})
        self._v2_alarms = dict(active)
        self._refresh_v2_table()
        self.v2_alarm_count_changed.emit(len(self._v2_alarms))

    def _refresh_v2_table(self) -> None:
        """Rebuild v2 alarm table, sorted by severity."""
        _sev_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        sorted_items = sorted(
            self._v2_alarms.items(),
            key=lambda kv: (_sev_order.get(kv[1].get("level", "INFO"), 99), kv[0]),
        )
        self._v2_table.setRowCount(len(sorted_items))
        for row_idx, (alarm_id, info) in enumerate(sorted_items):
            level = info.get("level", "INFO")
            message = info.get("message", "")
            channels = ", ".join(info.get("channels", []))
            triggered_at = info.get("triggered_at", 0.0)
            if triggered_at:
                elapsed = time.time() - triggered_at
                if elapsed < 60:
                    time_text = f"{elapsed:.0f} с"
                elif elapsed < 3600:
                    time_text = f"{elapsed / 60:.0f} мин"
                else:
                    time_text = f"{elapsed / 3600:.1f} ч"
            else:
                time_text = "—"

            color = QColor(_SEVERITY_COLORS.get(level, "#AAAAAA"))
            icon = _SEVERITY_ICONS.get(level, "")

            level_item = QTableWidgetItem(f"{icon} {level}")
            level_item.setForeground(color)
            level_item.setFont(QFont("", -1, QFont.Weight.Bold))
            self._v2_table.setItem(row_idx, 0, level_item)
            self._v2_table.setItem(row_idx, 1, QTableWidgetItem(alarm_id))
            self._v2_table.setItem(row_idx, 2, QTableWidgetItem(message[:80]))
            self._v2_table.setItem(row_idx, 3, QTableWidgetItem(channels))
            self._v2_table.setItem(row_idx, 4, QTableWidgetItem(time_text))

            # ACK button
            btn = QPushButton("ACK")
            btn.setStyleSheet(
                f"background-color: {_SEVERITY_COLORS.get(level, theme.STONE_400)}; "
                f"color: {theme.TEXT_INVERSE}; border: none; padding: 2px 6px; border-radius: {theme.RADIUS_SM}px;"
            )
            btn.clicked.connect(lambda checked=False, aid=alarm_id: self._acknowledge_v2(aid))
            self._v2_table.setCellWidget(row_idx, 5, btn)

    def _acknowledge_v2(self, alarm_id: str) -> None:
        """Send alarm_v2_ack to engine (non-blocking)."""
        worker = ZmqCommandWorker({"cmd": "alarm_v2_ack", "alarm_name": alarm_id})
        worker.finished.connect(lambda result, aid=alarm_id: self._on_ack_v2_result(result, aid))
        self._workers.append(worker)
        worker.start()

    def _on_ack_v2_result(self, result: dict, alarm_id: str) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            logger.info("Alarm v2 '%s' подтверждён", alarm_id)
        else:
            logger.warning("Ошибка ack alarm v2 '%s': %s", alarm_id, result.get("error"))
