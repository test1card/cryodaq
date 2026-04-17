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

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme


def _is_focusable_descendant(widget: QWidget) -> bool:
    """A widget is a valid focus-trap target if it's enabled, visible,
    and accepts some form of keyboard focus."""
    if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
        return False
    if not widget.isEnabled():
        return False
    if not widget.isVisible():
        return False
    return True


class _Backdrop(QWidget):
    """Opaque event-catching backdrop that emits on left click."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modalCardBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(f"#modalCardBackdrop {{ background: {theme.SURFACE_OVERLAY_RGBA}; }}")

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
        max_width: int = 1280,
        max_height_vh_pct: int = 80,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModalCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._max_width = max_width
        self._max_height_vh_pct = max_height_vh_pct
        self._content_widget: QWidget | None = None
        # RULE-INTER-002: remember who held focus when the modal opened
        # so we can return focus there after any close path.
        self._opener: QWidget | None = None

        # Restore focus to opener on every close path. closed.emit() fires
        # from backdrop click / close button / Escape; closeEvent fires
        # from programmatic close(). Both route through _restore_opener_focus
        # which is idempotent.
        self.closed.connect(self._restore_opener_focus)

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
        card_layout.setContentsMargins(theme.SPACE_5, theme.SPACE_3, theme.SPACE_5, theme.SPACE_5)
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
        self._content_layout.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, theme.SPACE_3)
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
        # RULE-INTER-002: snapshot the pre-open focus owner so we can
        # return focus there on close. QApplication.focusWidget() may
        # be None if nothing has focus (headless tests often), in which
        # case _restore_opener_focus becomes a no-op.
        self._opener = QApplication.focusWidget()
        self._reposition_card()
        # RULE-A11Y-001: move focus to the first focusable descendant
        # so keyboard users can start interacting immediately.
        if not self._focus_first_child():
            self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Programmatic close() path — restore focus explicitly.
        # The closed-signal handler is idempotent so duplicate calls
        # from closed.emit() + closeEvent are harmless.
        self._restore_opener_focus()
        super().closeEvent(event)

    def focusNextPrevChild(self, next: bool) -> bool:  # type: ignore[override]
        """Focus trap — Tab and Shift+Tab cycle through focusable
        descendants of the modal only; focus cannot leave.

        RULE-A11Y-001 / RULE-INTER-002. Qt calls this on Tab / Shift+Tab;
        default implementation walks the whole top-level window's focus
        chain, which would allow focus to escape. We override to cycle
        only through our own descendants.
        """
        focusable = [w for w in self.findChildren(QWidget) if _is_focusable_descendant(w)]
        if not focusable:
            return False

        current = QApplication.focusWidget()
        try:
            idx = focusable.index(current)
        except ValueError:
            idx = -1 if next else 0

        if next:
            new_idx = (idx + 1) % len(focusable)
        else:
            new_idx = (idx - 1) % len(focusable)

        focusable[new_idx].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def _focus_first_child(self) -> bool:
        """Focus the first focusable descendant. Returns True on success."""
        for w in self.findChildren(QWidget):
            if _is_focusable_descendant(w):
                w.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
        return False

    def _restore_opener_focus(self) -> None:
        """Return focus to the widget that held it when the modal opened."""
        opener = self._opener
        if opener is None:
            return
        try:
            # Opener may have been deleted between show and close; the
            # PySide6 wrapper raises RuntimeError in that case.
            opener.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            pass
        finally:
            # Clear so a reopened modal re-snapshots on the next showEvent
            # instead of restoring to a stale opener.
            self._opener = None

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
        max_height = max(0, min(available_height, (self.height() * self._max_height_vh_pct) // 100))
        card_width = min(self._max_width, available_width)
        card_height = max_height
        x = (self.width() - card_width) // 2
        y = (self.height() - card_height) // 2
        self._card.setGeometry(QRect(x, y, card_width, card_height))
