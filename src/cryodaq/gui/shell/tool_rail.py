"""ToolRail — vertical icon navigation (Phase UI-1 v2 Block A).

10 icon buttons + separators in a fixed-width column. Each button emits
``tool_clicked(name)`` where name is the overlay identifier consumed by
OverlayContainer.

IV.3 Finding 4: icons migrated from Lucide SVG files to Phosphor via
qtawesome (runtime font-based rendering). Same visual style, 1200+
icons available vs. 10 SVGs, and theme switches are cheap because
``qta.icon(color=…)`` renders fresh on each call. The legacy
SVG files under ``src/cryodaq/gui/resources/icons/`` are retained as
a fallback — see ``_colored_icon`` below.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

# Canonical Phosphor icon names for each ToolRail slot. All names use
# the `ph.` prefix (Phosphor regular weight). Architect-approved
# mapping — kept alphabetized by slot name for reviewability.
_PHOSPHOR_ICONS: dict[str, str] = {
    "alarms": "ph.bell-simple",
    "analytics": "ph.chart-line-up",
    "conductivity": "ph.thermometer-simple",
    "experiment": "ph.flask",
    "home": "ph.house",
    "instruments": "ph.cpu",
    "log": "ph.note-pencil",
    "more": "ph.dots-three",
    "new_experiment": "ph.plus-circle",
    "source": "ph.lightning",
}


@lru_cache(maxsize=128)
def _phosphor_icon(name: str, color: str, size: int) -> QIcon:
    """Render a Phosphor icon at the given color + size.

    Cached by (name, color, size). Theme switches produce a new color
    → new cache entry; lru_cache evicts the oldest entry past 128, so
    stale entries don't accumulate unbounded. ``size`` is carried as a
    cache key even though ``qta.icon`` itself scales the returned QIcon
    through ``pixmap(QSize)`` at paint time — keeping it in the key
    makes test introspection deterministic.
    """
    return qta.icon(name, color=color)


@lru_cache(maxsize=128)
def _colored_icon(svg_path_str: str, color: str, size: int) -> QIcon:
    """Render a Lucide stroke-based SVG with a specific stroke color.

    IV.3 F4: retained as a fallback path for slots that don't have a
    Phosphor mapping (there are none today) or for custom icons added
    later. Not called on the primary rendering path; left intact so a
    future addition can fall back without restoring the SVG pipeline
    in a rush.
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


_RAIL_WIDTH = theme.TOOL_RAIL_WIDTH  # DESIGN: 56px, couples to HEADER_HEIGHT
_BUTTON_SIZE = theme.TOOL_RAIL_WIDTH  # DESIGN: 56×56 square slots
_ICON_SIZE = 24  # proposed: theme.ICON_SIZE_MD (not yet in theme.py)

# Canonical mnemonic shortcuts (AD-002 / tokens/keyboard-shortcuts.md).
# Maps Ctrl+<letter> → ToolRail slot name. Ctrl+R maps to an item in
# the More menu; all others are top-level slots.
_MNEMONIC_SHORTCUTS: dict[str, str] = {
    "Ctrl+L": "log",  # Журнал
    "Ctrl+E": "experiment",  # Эксперимент
    "Ctrl+A": "analytics",  # Аналитика
    "Ctrl+K": "source",  # Keithley (источник мощности)
    "Ctrl+M": "alarms",  # Модуль сигнализации
    "Ctrl+R": "archive",  # Records (архив, lives in More menu)
    "Ctrl+C": "conductivity",  # Теплопроводность
    "Ctrl+D": "instruments",  # Диагностика / приборы
}

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
        # IV.3 F4: Phosphor icons render from a font at runtime so
        # there is no path-on-disk existence check. Fall back to the
        # tooltip-prefix label only when the slot name has no
        # Phosphor mapping (no current slots; defensive).
        if name not in _PHOSPHOR_ICONS and not icon_path.exists():
            self.setText(tooltip[:2])
        self._refresh_icon()
        self._apply_style()

    def _refresh_icon(self) -> None:
        if self._active:
            color = theme.ACCENT_400
        elif self._hover:
            color = theme.TEXT_SECONDARY
        else:
            color = theme.TEXT_MUTED
        # IV.3 F4: Phosphor via qtawesome is the primary renderer.
        # Fall back to Lucide SVG only if the slot is not in
        # _PHOSPHOR_ICONS (currently never the case). Theme awareness
        # is automatic — _phosphor_icon is keyed on (name, color, size)
        # so switching theme yields a fresh cache entry.
        phosphor_name = _PHOSPHOR_ICONS.get(self._name)
        if phosphor_name is not None:
            self.setIcon(_phosphor_icon(phosphor_name, color, _ICON_SIZE))
            return
        if not self._icon_path.exists():
            return
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
        self._register_shortcuts()

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

    def _register_shortcuts(self) -> None:
        """Register canonical mnemonic + transitional numeric shortcuts.

        Shortcuts fire on `tool_clicked` so the parent shell's existing
        handler resolves them (open overlay / activate rail slot) the
        same way as a mouse click on the corresponding button. Uses
        `WindowShortcut` (default) so QLineEdit-local Ctrl+C / Ctrl+A
        still work for text copy / select-all — Qt dispatches to the
        focused widget first and only falls through to the shortcut
        when the widget does not consume the key.
        """
        # Canonical mnemonics (AD-002).
        for seq, slot_name in _MNEMONIC_SHORTCUTS.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda n=slot_name: self.tool_clicked.emit(n))

        # Transitional numeric shortcuts Ctrl+1..Ctrl+9 — phased out per AD-002
        # but kept alive so operators with memorised slot positions are not
        # disrupted mid-release. Map to top-level visible slots in order.
        numeric_order = (
            [name for name, _, _ in _TOP_ITEMS]
            + [name for name, _, _ in _NEW_ITEMS]
            + [name for name, _, _ in _OVERLAY_ITEMS]
        )
        for i, slot_name in enumerate(numeric_order, start=1):
            if i > 9:
                break
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.activated.connect(lambda n=slot_name: self.tool_clicked.emit(n))

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
