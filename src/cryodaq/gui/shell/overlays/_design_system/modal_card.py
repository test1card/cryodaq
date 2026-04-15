"""ModalCard — centered card overlay with backdrop dim.

Foundational primitive for all Phase II overlays. Content-agnostic; subclass
or compose with content widgets. Provides:
- Backdrop dim via theme token
- Centered card (configurable max width/height)
- 3 close mechanisms: ESC key, close button, backdrop click
- ``closed`` signal emitted on any close mechanism
- Theme-token based styling only
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme


class _Backdrop(QWidget):
    """Opaque event-catching backdrop that emits on left click."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modalCardBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(
            f"#modalCardBackdrop {{ background: {theme.SURFACE_OVERLAY_RGBA}; }}"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ModalCard(QWidget):
    """Centered modal card with backdrop and built-in close affordances."""

    closed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        max_width: int = 1100,
        max_height_vh_pct: int = 80,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModalCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._max_width = max_width
        self._max_height_vh_pct = max_height_vh_pct
        self._content_widget: QWidget | None = None

        self._backdrop = _Backdrop(self)
        self._backdrop.clicked.connect(self.closed.emit)

        self._card = QFrame(self)
        self._card.setObjectName("modalCardBody")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setStyleSheet(
            f"#modalCardBody {{"
            f"background: {theme.SURFACE_ELEVATED};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(
            theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_5
        )
        card_layout.setSpacing(theme.SPACE_3)

        chrome_row = QHBoxLayout()
        chrome_row.setContentsMargins(0, 0, 0, 0)
        chrome_row.setSpacing(theme.SPACE_2)
        chrome_row.addStretch()

        self._close_button = QPushButton("\u2715", self._card)
        self._close_button.setObjectName("modalCardCloseButton")
        self._close_button.setFixedSize(32, 32)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            f"#modalCardCloseButton {{"
            f"background: transparent;"
            f"color: {theme.MUTED_FOREGROUND};"
            f"border: none;"
            f"border-radius: {theme.RADIUS_FULL}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_LG}px;"
            f"}}"
            f"#modalCardCloseButton:hover {{"
            f"color: {theme.FOREGROUND};"
            f"background: {theme.MUTED};"
            f"}}"
        )
        self._close_button.clicked.connect(self.closed.emit)
        chrome_row.addWidget(self._close_button)
        card_layout.addLayout(chrome_row)

        self._content_host = QWidget(self._card)
        self._content_host.setObjectName("modalCardContentHost")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(theme.SPACE_3)
        card_layout.addWidget(self._content_host, 1)

    def set_content(self, widget: QWidget) -> None:
        """Set the card's content widget, replacing any existing content."""
        if self._content_widget is widget:
            return

        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)

        self._content_widget = widget
        self._content_layout.addWidget(widget)
        self._reposition_card()

    def card_widget(self) -> QWidget:
        """Return the styled inner card widget."""
        return self._card

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._backdrop.setGeometry(self.rect())
        self._reposition_card()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self._reposition_card()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _reposition_card(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return

        outer_margin = theme.SPACE_5
        available_width = max(0, self.width() - 2 * outer_margin)
        available_height = max(0, self.height() - 2 * outer_margin)
        max_height = max(
            0, min(available_height, (self.height() * self._max_height_vh_pct) // 100)
        )
        size_hint = self._card.sizeHint()
        card_width = min(self._max_width, available_width, size_hint.width())
        card_height = min(max_height, size_hint.height())
        if card_width <= 0:
            card_width = min(self._max_width, available_width)
        if card_height <= 0:
            card_height = max_height
        x = (self.width() - card_width) // 2
        y = (self.height() - card_height) // 2
        self._card.setGeometry(QRect(x, y, card_width, card_height))

