"""Compact quick-log block for dashboard (B.7).

Peripheral awareness indicator — shows last 1-2 journal entries and
inline composer. Not a reading surface; full journal is in
OperatorLogPanel overlay.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

logger = logging.getLogger(__name__)

_MAX_HEIGHT_PX = 70
_MAX_VISIBLE_ENTRIES = 2  # peripheral awareness, not reading surface


class QuickLogBlock(QWidget):
    """Compact dashboard log strip: composer + last 1-2 entries."""

    entry_submitted = Signal(str)  # message text

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("QuickLogBlock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumHeight(_MAX_HEIGHT_PX)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._entries: list[dict] = []
        self._entry_labels: list[QLabel] = []

        self._build_ui()
        self._refresh_entries_display()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        root.setSpacing(2)

        # Row 1: Inline composer
        composer = QHBoxLayout()
        composer.setContentsMargins(0, 0, 0, 0)
        composer.setSpacing(theme.SPACE_2)

        self._input = QLineEdit()
        self._input.setObjectName("quickLogInput")
        self._input.setPlaceholderText(
            "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c "
            "\u0437\u0430\u043c\u0435\u0442\u043a\u0443\u2026"
        )  # Добавить заметку…
        self._input.setFixedHeight(24)
        self._input.returnPressed.connect(self._on_submit)
        self._input.setStyleSheet(
            f"#quickLogInput {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 2px 8px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        composer.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("\u21b5")  # ↵
        self._send_btn.setObjectName("quickLogSendBtn")
        self._send_btn.setFixedSize(24, 24)
        self._send_btn.clicked.connect(self._on_submit)
        self._send_btn.setStyleSheet(
            f"#quickLogSendBtn {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}} "
            f"#quickLogSendBtn:hover {{ "
            f"background-color: {theme.PRIMARY}; "
            f"}}"
        )
        composer.addWidget(self._send_btn)
        root.addLayout(composer)

        # Row 2-3: Entry labels (created dynamically)
        self._entries_container = QVBoxLayout()
        self._entries_container.setContentsMargins(0, 0, 0, 0)
        self._entries_container.setSpacing(1)
        root.addLayout(self._entries_container)

        # Empty state label
        self._empty_label = QLabel(
            "\u0416\u0443\u0440\u043d\u0430\u043b \u043f\u0443\u0441\u0442. "
            "\u21b5 \u2014 \u0434\u043e\u0431\u0430\u0432\u0438\u0442\u044c "
            "\u0437\u0430\u043c\u0435\u0442\u043a\u0443"
        )  # Журнал пуст. ↵ — добавить заметку
        self._empty_label.setObjectName("quickLogEmpty")
        self._empty_label.setStyleSheet(
            f"#quickLogEmpty {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"font-style: italic; "
            f"}}"
        )
        self._entries_container.addWidget(self._empty_label)

        self.setStyleSheet(
            self.styleSheet()
            + f"#QuickLogBlock {{ "
            f"background-color: {theme.SURFACE_PANEL}; "
            f"border-top: 1px solid {theme.BORDER}; "
            f"}}"
        )

    # ------------------------------------------------------------------
    # Entry rendering
    # ------------------------------------------------------------------

    def set_entries(self, entries: list[dict]) -> None:
        """Set the log entries (newest first). Shows max 2."""
        self._entries = entries
        self._refresh_entries_display()

    def _refresh_entries_display(self) -> None:
        """Rebuild entry labels from cached entries."""
        # Clear old labels
        for lbl in self._entry_labels:
            self._entries_container.removeWidget(lbl)
            lbl.deleteLater()
        self._entry_labels.clear()

        visible = self._entries[:_MAX_VISIBLE_ENTRIES]

        if not visible:
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)

        for entry in visible:
            lbl = self._make_entry_label(entry)
            self._entries_container.addWidget(lbl)
            self._entry_labels.append(lbl)

    def _make_entry_label(self, entry: dict) -> QLabel:
        ts_raw = entry.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts_raw)
            ts_text = dt.strftime("%H:%M")
        except (ValueError, TypeError):
            ts_text = "--:--"

        message = entry.get("message", "")
        if len(message) > 60:
            message = message[:57] + "\u2026"

        text = (
            f'<span style="color:{theme.MUTED_FOREGROUND}; '
            f"font-family:'{theme.FONT_MONO}'; "
            f'font-size:{theme.FONT_SIZE_XS}px;">{ts_text}</span>'
            f' <span style="color:{theme.MUTED_FOREGROUND}; '
            f'font-size:{theme.FONT_SIZE_XS}px;">\u00b7</span> '
            f'<span style="color:{theme.FOREGROUND}; '
            f"font-family:'{theme.FONT_BODY}'; "
            f'font-size:{theme.FONT_SIZE_XS}px;">{message}</span>'
        )

        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(text)
        lbl.setToolTip(entry.get("message", ""))
        return lbl

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.entry_submitted.emit(text)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: ANN001
        super().closeEvent(event)
