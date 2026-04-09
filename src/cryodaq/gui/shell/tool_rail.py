"""ToolRail — vertical icon navigation (Phase UI-1 v2 Block A).

10 icon buttons + separators in a fixed-width column. Each button emits
``tool_clicked(name)`` where name is the overlay identifier consumed by
OverlayContainer.

Pixel sizes (rail width, button height) are first-pass guesses; calibrate
on lab PC. Icons are loaded from src/cryodaq/gui/resources/icons/ as
Lucide SVGs.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

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
        self.setFixedSize(_RAIL_WIDTH, _BUTTON_SIZE)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_path.exists():
            self.setIcon(QIcon(str(icon_path)))
        else:
            self.setText(tooltip[:2])
        self._apply_style()

    @property
    def name(self) -> str:
        return self._name

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            border = f"3px solid {theme.ACCENT_400}"
            bg = theme.SURFACE_CARD
        else:
            border = "3px solid transparent"
            bg = "transparent"
        self.setStyleSheet(
            f"QToolButton {{ background: {bg}; border: none; "
            f"border-left: {border}; padding: 0px; }}"
            f"QToolButton:hover {{ background: {theme.SURFACE_CARD}; }}"
        )


class ToolRail(QFrame):
    """Vertical navigation rail."""

    tool_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_RAIL_WIDTH)
        self.setStyleSheet(
            f"ToolRail {{ background-color: {theme.SURFACE_PANEL}; "
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
        self._more_btn = ToolRailButton(
            _MORE_NAME, _ICONS_DIR / _MORE_ICON, "Ещё", self
        )
        self._more_btn.clicked.connect(self._show_more_menu)
        self._buttons[_MORE_NAME] = self._more_btn
        layout.addWidget(self._more_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        for name, label in _MORE_ITEMS:
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
