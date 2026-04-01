from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMainWindow, QMenu, QSystemTrayIcon


class TrayLevel(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class TrayStatus:
    level: TrayLevel
    tooltip: str


def resolve_tray_status(*, connected: bool, safety_state: str | None, alarm_count: int | None) -> TrayStatus:
    safety = (safety_state or "").strip().lower() or None
    alarms = 0 if alarm_count is None else max(0, int(alarm_count))

    if alarms > 0 or safety in {"fault", "fault_latched"}:
        return TrayStatus(
            level=TrayLevel.FAULT,
            tooltip=_build_tooltip("Авария", connected=connected, safety_state=safety, alarm_count=alarms),
        )
    if not connected or safety is None:
        return TrayStatus(
            level=TrayLevel.WARNING,
            tooltip=_build_tooltip("Нет полной информации", connected=connected, safety_state=safety, alarm_count=alarms),
        )
    if safety in {"safe_off", "ready", "run_permitted", "running"}:
        return TrayStatus(
            level=TrayLevel.HEALTHY,
            tooltip=_build_tooltip("Система в норме", connected=connected, safety_state=safety, alarm_count=alarms),
        )
    return TrayStatus(
        level=TrayLevel.WARNING,
        tooltip=_build_tooltip("Состояние требует проверки", connected=connected, safety_state=safety, alarm_count=alarms),
    )


def _build_tooltip(summary: str, *, connected: bool, safety_state: str | None, alarm_count: int) -> str:
    connection_text = "подключено" if connected else "нет данных"
    safety_text = safety_state or "неизвестно"
    return (
        "CryoDAQ\n"
        f"{summary}\n"
        f"Связь: {connection_text}\n"
        f"Безопасность: {safety_text}\n"
        f"Тревоги: {alarm_count}"
    )


class TrayController:
    def __init__(self, window: QMainWindow) -> None:
        self._window = window
        self._tray: QSystemTrayIcon | None = None
        self._show_action: QAction | None = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(window)
        tray.setIcon(_icon_for_level(TrayLevel.WARNING))
        tray.setToolTip("CryoDAQ\nНет полной информации")
        tray.setContextMenu(self._build_menu(window))
        tray.activated.connect(self._on_activated)
        tray.show()
        self._tray = tray

    @property
    def available(self) -> bool:
        return self._tray is not None

    def update(self, status: TrayStatus) -> None:
        if self._tray is None:
            return
        self._tray.setIcon(_icon_for_level(status.level))
        self._tray.setToolTip(status.tooltip)

    def _build_menu(self, window: QMainWindow) -> QMenu:
        menu = QMenu(window)
        self._show_action = QAction("Показать окно", menu)
        self._show_action.triggered.connect(self.show_window)
        menu.addAction(self._show_action)

        hide_action = QAction("Скрыть окно", menu)
        hide_action.triggered.connect(window.hide)
        menu.addAction(hide_action)

        menu.addSeparator()
        exit_action = QAction("Выход", menu)
        exit_action.triggered.connect(window.close)
        menu.addAction(exit_action)
        return menu

    def show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()


def _icon_for_level(level: TrayLevel) -> QIcon:
    color = {
        TrayLevel.HEALTHY: QColor("#2ECC40"),
        TrayLevel.WARNING: QColor("#FFDC00"),
        TrayLevel.FAULT: QColor("#FF4136"),
    }[level]
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QIcon(pixmap)
