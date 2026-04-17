"""ToolRail — vertical icon navigation (Phase UI-1 v2 Block A).

10 icon buttons + separators in a fixed-width column. Each button emits
``tool_clicked(name)`` where name is the overlay identifier consumed by
OverlayContainer.

Pixel sizes (rail width, button height) are first-pass guesses; calibrate
on lab PC. Icons are loaded from src/cryodaq/gui/resources/icons/ as
Lucide SVGs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme


@lru_cache(maxsize=128)
def _colored_icon(svg_path_str: str, color: str, size: int) -> QIcon:
    """Render a Lucide stroke-based SVG with a specific stroke color.

    Lucide icons declare ``stroke="currentColor"`` so we can substitute the
    placeholder before handing the bytes to QSvgRenderer.
    """
    path = Path(svg_path_str)
    if not path.exists():
        return QIcon()
    raw = path.read_text(encoding="utf-8")
    raw = raw.replace('stroke="currentColor"', f'stroke="{color}"')
    raw = raw.replace('fill="currentColor"', f'fill="{color}"')
    renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


_RAIL_WIDTH = 50  # [calibrate]
_BUTTON_SIZE = 40  # [calibrate]
_ICON_SIZE = 20

_ICONS_DIR = Path(__file__).parent.parent / "resources" / "icons"

# (name, icon_filename, label) — order matches wireframe section 4
_TOP_ITEMS = [
    ("home", "home.svg", "Дашборд"),
]
_NEW_ITEMS = [
    ("new_experiment", "plus.svg", "Новый эксперимент"),
]
_OVERLAY_ITEMS = [
    ("experiment", "flask-conical.svg", "Эксперимент"),
    ("source", "zap.svg", "Источник мощности"),
    ("analytics", "trending-up.svg", "Аналитика"),
    ("conductivity", "thermometer.svg", "Теплопроводность"),
    ("alarms", "bell.svg", "Алармы"),
    ("log", "file-text.svg", "Служебный лог"),
    ("instruments", "cpu.svg", "Приборы"),
]
_MORE_NAME = "more"
_MORE_ICON = "more-horizontal.svg"
_MORE_ITEMS = [
    ("archive", "Архив"),
    ("calibration", "Калибровка"),
    ("settings", "Настройки"),
    ("__separator__", ""),
    ("web_panel", "Открыть Web-панель"),
    ("restart_engine", "Перезапустить Engine"),
]


class ToolRailButton(QToolButton):
    """Single icon button with active/hover/idle states."""

    def __init__(
        self,
        name: str,
        icon_path: Path,
        tooltip: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._active = False
        self._hover = False
        self._icon_path = icon_path
        self.setFixedSize(_RAIL_WIDTH, _BUTTON_SIZE)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not icon_path.exists():
            self.setText(tooltip[:2])
        self._refresh_icon()
        self._apply_style()

    def _refresh_icon(self) -> None:
        if not self._icon_path.exists():
            return
        if self._active:
            color = theme.ACCENT_400
        elif self._hover:
            color = theme.TEXT_SECONDARY
        else:
            color = theme.TEXT_MUTED
        self.setIcon(_colored_icon(str(self._icon_path), color, _ICON_SIZE))

    def enterEvent(self, event):  # noqa: ANN001
        self._hover = True
        self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: ANN001
        self._hover = False
        self._refresh_icon()
        super().leaveEvent(event)

    @property
    def name(self) -> str:
        return self._name

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._refresh_icon()
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            border = f"3px solid {theme.ACCENT_400}"
        else:
            border = "3px solid transparent"
        self.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; "
            f"border-left: {border}; padding: 0px; }}"
            f"QToolButton:hover {{ background: {theme.SECONDARY}; }}"
        )


class ToolRail(QFrame):
    """Vertical navigation rail."""

    tool_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_RAIL_WIDTH)
        self.setObjectName("ToolRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"#ToolRail {{ background-color: {theme.SURFACE_PANEL}; "
            f"border-right: 1px solid {theme.BORDER_SUBTLE}; }}"
        )

        self._buttons: dict[str, ToolRailButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE_2, 0, theme.SPACE_2)
        layout.setSpacing(2)

        for group in (_TOP_ITEMS, _NEW_ITEMS, _OVERLAY_ITEMS):
            for name, icon_file, label in group:
                btn = ToolRailButton(name, _ICONS_DIR / icon_file, label, self)
                btn.clicked.connect(lambda checked=False, n=name: self.tool_clicked.emit(n))
                self._buttons[name] = btn
                layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addSpacing(theme.SPACE_2)

        layout.addStretch()

        # More menu — bypass tool_clicked signal, open popup directly
        self._more_btn = ToolRailButton(_MORE_NAME, _ICONS_DIR / _MORE_ICON, "Ещё", self)
        self._more_btn.clicked.connect(self._show_more_menu)
        self._buttons[_MORE_NAME] = self._more_btn
        layout.addWidget(self._more_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        for name, label in _MORE_ITEMS:
            if name == "__separator__":
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, n=name: self.tool_clicked.emit(n))
        # Position near the more button
        pos = self._more_btn.mapToGlobal(self._more_btn.rect().topRight())
        menu.exec(pos)

    # ------------------------------------------------------------------

    def set_active(self, name: str | None) -> None:
        """Mark one button as active (or none)."""
        for btn_name, btn in self._buttons.items():
            btn.set_active(btn_name == name)
