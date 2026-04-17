"""Панель диагностики датчиков (SensorDiagPanel).

Таблица здоровья датчиков с цветовой индикацией.
Встраивается в InstrumentStatusPanel как секция внизу.
Данные запрашиваются через ZMQ get_sensor_diagnostics.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.widgets.common import apply_panel_frame_style

logger = logging.getLogger(__name__)

_COLOR_GREEN = theme.STATUS_OK
_COLOR_YELLOW = theme.STATUS_CAUTION
_COLOR_RED = theme.STATUS_FAULT
_COLOR_MUTED = theme.TEXT_MUTED

_HEADERS = ["Канал", "T (K)", "Шум (мК)", "Дрейф (мК/мин)", "Выбросы", "Корр.", "Здоровье"]


def _health_color(score: int) -> str:
    if score >= 80:
        return _COLOR_GREEN
    if score >= 50:
        return _COLOR_YELLOW
    return _COLOR_RED


def _fmt(value: float, decimals: int = 1) -> str:
    if not math.isfinite(value):
        return "—"
    return f"{value:.{decimals}f}"


class SensorDiagPanel(QWidget):
    """Таблица диагностики датчиков с summary badge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_data: dict[str, dict[str, Any]] = {}
        self._summary: dict[str, Any] = {}
        self._build_ui()

        # Polling timer: refresh every 10s via ZMQ command
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(10_000)
        self._poll_timer.timeout.connect(self._poll_diagnostics)
        self._poll_timer.start()
        # Initial fetch after short delay
        QTimer.singleShot(500, self._poll_diagnostics)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)

        # Header with summary badge
        header_frame = QFrame()
        apply_panel_frame_style(header_frame)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel("ДИАГНОСТИКА ДАТЧИКОВ")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {_COLOR_MUTED};")
        header_layout.addWidget(self._summary_label)
        layout.addWidget(header_frame)

        # Table
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        h = self._table.horizontalHeader()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._table, stretch=1)

    @Slot()
    def _poll_diagnostics(self) -> None:
        """Request sensor diagnostics from engine via ZMQ."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "get_sensor_diagnostics"}, parent=self)
        worker.finished.connect(self._on_diagnostics_received)
        worker.start()

    @Slot(dict)
    def _on_diagnostics_received(self, result: dict) -> None:
        """Update table from engine response."""
        if not result.get("ok"):
            return
        self._channel_data = result.get("channels", {})
        self._summary = result.get("summary", {})
        self._refresh_table()
        self._refresh_summary()

    def set_diagnostics(self, channels: dict[str, dict[str, Any]], summary: dict[str, Any]) -> None:
        """Set diagnostics data directly (for testing or programmatic use)."""
        self._channel_data = dict(channels)
        self._summary = dict(summary)
        self._refresh_table()
        self._refresh_summary()

    def _refresh_table(self) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._channel_data))

        for row, (ch_id, data) in enumerate(
            sorted(
                self._channel_data.items(),
                key=lambda item: item[1].get("health_score", 100),
            )
        ):
            health = int(data.get("health_score", 100))
            color = _health_color(health)
            name = data.get("channel_name", ch_id)

            items = [
                self._make_item(name),
                self._make_item(_fmt(data.get("current_T", float("nan")))),
                self._make_item(_fmt(data.get("noise_mK", float("nan")), 0)),
                self._make_item(_fmt(data.get("drift_mK_per_min", float("nan")))),
                self._make_item(str(data.get("outlier_count", 0))),
                self._make_item(
                    _fmt(data["correlation"], 2) if data.get("correlation") is not None else "—"
                ),
                self._make_item(str(health)),
            ]

            for col, item in enumerate(items):
                if col == len(items) - 1:
                    item.setForeground(QColor(color))
                    item.setFont(QFont("", -1, QFont.Weight.Bold))
                self._table.setItem(row, col, item)

            # Row background tint for warning/critical
            if health < 50:
                bg = QColor(255, 65, 54, 25)
            elif health < 80:
                bg = QColor(255, 220, 0, 15)
            else:
                bg = QColor(0, 0, 0, 0)
            for col in range(len(items)):
                self._table.item(row, col).setBackground(bg)

        self._table.setSortingEnabled(True)

    def _refresh_summary(self) -> None:
        healthy = self._summary.get("healthy", 0)
        warning = self._summary.get("warning", 0)
        critical = self._summary.get("critical", 0)
        parts = []
        if healthy:
            parts.append(f'<span style="color:{_COLOR_GREEN}">{healthy} ✓</span>')
        if warning:
            parts.append(f'<span style="color:{_COLOR_YELLOW}">{warning} ⚠</span>')
        if critical:
            parts.append(f'<span style="color:{_COLOR_RED}">{critical} ✘</span>')
        self._summary_label.setText("  ".join(parts) if parts else "—")
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)

    @staticmethod
    def _make_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    @property
    def summary_text(self) -> str:
        """Compact summary for status bar: '18✓ 1⚠ 1✘'."""
        healthy = self._summary.get("healthy", 0)
        warning = self._summary.get("warning", 0)
        critical = self._summary.get("critical", 0)
        parts = []
        if healthy:
            parts.append(f"{healthy}✓")
        if warning:
            parts.append(f"{warning}⚠")
        if critical:
            parts.append(f"{critical}✘")
        return " ".join(parts) if parts else "—"
