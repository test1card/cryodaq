from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QMainWindow, QMenu, QSystemTrayIcon

from cryodaq.gui import theme


class TrayLevel(StrEnum):
    HEALTHY = "healthy"
    CAUTION = "caution"
    WARNING = "caution"  # compatibility alias; no separate operator rung
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class TrayStatus:
    level: TrayLevel
    tooltip: str


def resolve_tray_status(
    *,
    connected: bool | None,
    safety_state: str | None,
    alarm_count: int | None,
    data_fresh: bool | None = None,
    reporting_fault: bool | None = None,
) -> TrayStatus:
    """Resolve a coarse status without converting missing evidence to green."""
    safety = (safety_state or "").strip().lower() or None
    alarms = alarm_count if type(alarm_count) is int and alarm_count >= 0 else None
    connection = connected if type(connected) is bool else None
    freshness = data_fresh if type(data_fresh) is bool else None
    reporting = reporting_fault if type(reporting_fault) is bool else None

    if (alarms is not None and alarms > 0) or safety in {"fault", "fault_latched"}:
        return TrayStatus(
            level=TrayLevel.FAULT,
            tooltip=_build_tooltip(
                "АВАРИЯ",
                connected=connection,
                safety_state=safety,
                alarm_count=alarms,
                data_fresh=freshness,
                reporting_fault=reporting,
            ),
        )
    if connection is not True or safety is None or alarms is None or freshness is not True or reporting is not False:
        return TrayStatus(
            level=TrayLevel.CAUTION,
            tooltip=_build_tooltip(
                "НЕТ ПОЛНОЙ ИНФОРМАЦИИ",
                connected=connection,
                safety_state=safety,
                alarm_count=alarms,
                data_fresh=freshness,
                reporting_fault=reporting,
            ),
        )
    if safety in {"safe_off", "ready", "run_permitted", "running"}:
        return TrayStatus(
            level=TrayLevel.HEALTHY,
            tooltip=_build_tooltip(
                "ВХОДЫ БЕЗ ИСКЛЮЧЕНИЙ",
                connected=connection,
                safety_state=safety,
                alarm_count=alarms,
                data_fresh=freshness,
                reporting_fault=reporting,
            ),
        )
    return TrayStatus(
        level=TrayLevel.CAUTION,
        tooltip=_build_tooltip(
            "СОСТОЯНИЕ ТРЕБУЕТ ПРОВЕРКИ",
            connected=connection,
            safety_state=safety,
            alarm_count=alarms,
            data_fresh=freshness,
            reporting_fault=reporting,
        ),
    )


_SAFETY_TEXT = {
    "safe_off": "безопасно выкл.",
    "ready": "готово",
    "run_permitted": "пуск разрешён",
    "running": "работа",
    "fault": "авария",
    "fault_latched": "авария зафикс.",
}
_WINDOWS_TOOLTIP_UTF16_LIMIT = 127


def _build_tooltip(
    summary: str,
    *,
    connected: bool | None,
    safety_state: str | None,
    alarm_count: int | None,
    data_fresh: bool | None,
    reporting_fault: bool | None,
) -> str:
    connection_text = "да" if connected is True else "нет" if connected is False else "неизв."
    safety_text = _SAFETY_TEXT.get(safety_state or "", "неизв.")
    alarm_text = "неизв." if alarm_count is None else "9999+" if alarm_count > 9999 else str(alarm_count)
    freshness_text = "свежие" if data_fresh is True else "устар." if data_fresh is False else "неизв."
    reporting_text = "сбой" if reporting_fault is True else "норма" if reporting_fault is False else "неизв."
    tooltip = (
        "CryoDAQ · сводка; детали в окне\n"
        f"{summary}\n"
        f"Связь: {connection_text} · Б: {safety_text}\n"
        f"Т: {alarm_text} · Д: {freshness_text} · О: {reporting_text}"
    )
    return _truncate_utf16(tooltip, _WINDOWS_TOOLTIP_UTF16_LIMIT)


def _truncate_utf16(text: str, limit: int) -> str:
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text
    result: list[str] = []
    used = 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if used + units > limit - 1:
            break
        result.append(char)
        used += units
    return "".join(result).rstrip() + "…"


class TrayController:
    def __init__(self, window: QMainWindow) -> None:
        self._window = window
        self._tray: QSystemTrayIcon | None = None
        self._show_action: QAction | None = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(window)
        initial = resolve_tray_status(connected=None, safety_state=None, alarm_count=None)
        tray.setIcon(tray_icon_for_level(initial.level))
        tray.setToolTip(initial.tooltip)
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
        self._tray.setIcon(tray_icon_for_level(status.level))
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


def tray_icon_for_level(level: TrayLevel) -> QIcon:
    """Return a token-colored, shape-redundant 16 px status icon."""

    color = {
        TrayLevel.HEALTHY: QColor(theme.STATUS_OK),
        TrayLevel.CAUTION: QColor(theme.STATUS_CAUTION),
        TrayLevel.FAULT: QColor(theme.STATUS_FAULT),
    }[level]
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)

    if level is TrayLevel.HEALTHY:
        painter.drawEllipse(1, 1, 14, 14)
    elif level is TrayLevel.CAUTION:
        painter.drawPolygon(QPolygonF([QPointF(8, 1), QPointF(15, 14), QPointF(1, 14)]))
    else:
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(5, 1),
                    QPointF(11, 1),
                    QPointF(15, 5),
                    QPointF(15, 11),
                    QPointF(11, 15),
                    QPointF(5, 15),
                    QPointF(1, 11),
                    QPointF(1, 5),
                ]
            )
        )

    # DESIGN: RULE-A11Y-002 — silhouette plus a static glyph duplicates color.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    glyph_pen = QPen(Qt.GlobalColor.transparent, 2)
    glyph_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    glyph_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(glyph_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if level is TrayLevel.HEALTHY:
        painter.drawLine(QPointF(4, 8), QPointF(7, 11))
        painter.drawLine(QPointF(7, 11), QPointF(12, 5))
    elif level is TrayLevel.CAUTION:
        painter.drawLine(QPointF(8, 5), QPointF(8, 9))
        painter.drawPoint(QPointF(8, 12))
    else:
        painter.drawLine(QPointF(5, 5), QPointF(11, 11))
        painter.drawLine(QPointF(11, 5), QPointF(5, 11))
    painter.end()
    return QIcon(pixmap)
