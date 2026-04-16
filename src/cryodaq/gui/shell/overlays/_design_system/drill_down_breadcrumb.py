"""DrillDownBreadcrumb — sticky top bar with back navigation."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from cryodaq.gui import theme


class _ClickableLabel(QLabel):
    """Minimal clickable label with button-like semantics for tests."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def click(self) -> None:
        self.clicked.emit()


class DrillDownBreadcrumb(QWidget):
    """Compact breadcrumb bar for overlay drill-down surfaces."""

    back_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        overlay_name: str,
        parent: QWidget | None = None,
        *,
        show_close_button: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DrillDownBreadcrumb")
        self._overlay_name = overlay_name
        self._back_label = "\u0414\u0430\u0448\u0431\u043e\u0440\u0434"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        self._back_button = _ClickableLabel(self)
        self._back_button.setObjectName("drillDownBackButton")
        self._back_button.setStyleSheet(
            f"#drillDownBackButton {{"
            f"background: transparent;"
            f"color: {theme.MUTED_FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"padding: 0px;"
            f"margin: 0px;"
            f"}}"
            f"#drillDownBackButton:hover {{"
            f"color: {theme.FOREGROUND};"
            f"text-decoration: underline;"
            f"}}"
        )
        self._back_button.clicked.connect(self.back_requested.emit)
        layout.addWidget(self._back_button, 0)

        self._separator = QLabel(" / ", self)
        self._separator.setObjectName("drillDownSeparator")
        self._separator.setStyleSheet(
            f"#drillDownSeparator {{"
            f"color: {theme.MUTED_FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"}}"
        )
        layout.addWidget(self._separator, 0)

        self._overlay_label = QLabel(self)
        self._overlay_label.setObjectName("drillDownOverlayLabel")
        self._overlay_label.setStyleSheet(
            f"#drillDownOverlayLabel {{"
            f"color: {theme.FOREGROUND};"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_SM}px;"
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
        )
        self._overlay_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        layout.addWidget(self._overlay_label, 1)

        layout.addStretch()

        self._close_button = QPushButton("\u2715", self)
        self._close_button.setObjectName("drillDownCloseButton")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            f"#drillDownCloseButton {{"
            f"background: transparent;"
            f"color: {theme.MUTED_FOREGROUND};"
            f"border: none;"
            f"border-radius: {theme.RADIUS_FULL}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_SIZE_BASE}px;"
            f"}}"
            f"#drillDownCloseButton:hover {{"
            f"color: {theme.FOREGROUND};"
            f"background: {theme.MUTED};"
            f"}}"
        )
        self._close_button.clicked.connect(self.close_requested.emit)
        self._close_button.setVisible(show_close_button)
        layout.addWidget(self._close_button, 0, Qt.AlignmentFlag.AlignRight)

        self.setFixedHeight(32)
        self._refresh_labels()

    def set_overlay_name(self, name: str) -> None:
        """Update overlay name displayed in breadcrumb."""
        self._overlay_name = name
        self._refresh_labels()

    def set_back_label(self, label: str) -> None:
        """Override the default back label."""
        self._back_label = label
        self._refresh_labels()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._refresh_labels()
        super().resizeEvent(event)

    def _refresh_labels(self) -> None:
        self._back_button.setText(f"\u2190 {self._back_label}")
        fm = QFontMetrics(self._overlay_label.font())
        reserved_width = (
            self._back_button.sizeHint().width()
            + self._separator.sizeHint().width()
            + (self._close_button.sizeHint().width() if self._close_button.isVisible() else 0)
            + theme.SPACE_5
        )
        available = max(40, self.width() - reserved_width)
        self._overlay_label.setText(
            fm.elidedText(self._overlay_name, Qt.TextElideMode.ElideRight, available)
        )
        self._overlay_label.setToolTip(self._overlay_name)
