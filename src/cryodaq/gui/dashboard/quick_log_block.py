"""Compact quick-log block for dashboard (B.7).

Peripheral awareness indicator — shows last 1-2 journal entries and
inline composer. Not a reading surface; full journal is in
OperatorLogPanel overlay.
"""

from __future__ import annotations

import html
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._entries: list[dict] = []
        self._entry_labels: list[QLabel] = []
        self._mutation_enabled = False
        self._authority_message = "Нет связи с Engine"
        self._submission_state = "idle"
        self._submission_detail = ""
        self._read_stale_detail = ""

        self._build_ui()
        self._refresh_entries_display()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        root.setSpacing(2)

        # Row 1: Inline composer
        composer = QHBoxLayout()
        composer.setContentsMargins(0, 0, 0, 0)
        composer.setSpacing(theme.SPACE_2)

        self._input = QLineEdit()
        self._input.setObjectName("quickLogInput")
        self._input.setPlaceholderText(
            "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0437\u0430\u043c\u0435\u0442\u043a\u0443\u2026"
        )  # Добавить заметку…
        # v0.55.2 ds-004: 24px = SPACE_5 — keep height on the scale.
        self._input.setFixedHeight(theme.SPACE_5)
        self._input.returnPressed.connect(self._on_submit)
        self._input.setStyleSheet(
            f"#quickLogInput {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: {theme.SPACE_1 // 2}px {theme.SPACE_2}px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        composer.addWidget(self._input, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setObjectName("quickLogStatus")
        self._status_label.setVisible(False)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        composer.addWidget(self._status_label)

        self._send_btn = QPushButton("\u21b5")  # ↵
        self._send_btn.setObjectName("quickLogSendBtn")
        self._send_btn.setAccessibleName("Записать заметку в журнал оператора")
        self._send_btn.setToolTip("Записать заметку в журнал оператора")
        # v0.55.2 ds-005: square at 24px = SPACE_5; matches the input height.
        self._send_btn.setFixedSize(theme.SPACE_5, theme.SPACE_5)
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
            self.styleSheet() + f"#QuickLogBlock {{ "
            f"background-color: {theme.SURFACE_PANEL}; "
            f"border-top: 1px solid {theme.BORDER}; "
            f"}}"
        )
        self._update_composer_state()

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

        message_raw = str(entry.get("message", "") or "")
        message = message_raw.splitlines()[0] if message_raw else ""
        if len(message) > 60:
            message = message[:57] + "\u2026"
        rendered_message = html.escape(message)

        text = (
            f'<span style="color:{theme.MUTED_FOREGROUND}; '
            f"font-family:'{theme.FONT_MONO}'; "
            f'font-size:{theme.FONT_SIZE_XS}px;">{ts_text}</span>'
            f' <span style="color:{theme.MUTED_FOREGROUND}; '
            f'font-size:{theme.FONT_SIZE_XS}px;">\u00b7</span> '
            f'<span style="color:{theme.FOREGROUND}; '
            f"font-family:'{theme.FONT_BODY}'; "
            f'font-size:{theme.FONT_SIZE_XS}px;">{rendered_message}</span>'
        )

        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(text)
        lbl.setToolTip(html.escape(message_raw))
        lbl.setAccessibleName(f"{ts_text}: {message}")
        return lbl

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def _on_submit(self) -> None:
        if not self._mutation_enabled or self._submission_state not in {"idle", "error", "unknown"}:
            return
        text = self._input.text().strip()
        if not text:
            return
        self.set_submission_state("pending", "Запись отправлена; ожидается подтверждение журнала")
        self.entry_submitted.emit(text)

    def set_mutation_enabled(self, enabled: bool, message: str = "") -> None:
        self._mutation_enabled = bool(enabled)
        self._authority_message = message.strip()
        self._update_composer_state()

    def set_submission_state(self, state: str, detail: str = "") -> None:
        if state not in {"idle", "pending", "unknown", "error"}:
            raise ValueError(f"unsupported quick-log submission state: {state}")
        self._submission_state = state
        self._submission_detail = detail.strip()
        self._update_composer_state()

    def set_read_stale(self, detail: str | None) -> None:
        """Mark recent entries as retained, not current, without hiding them."""

        self._read_stale_detail = "" if detail is None else detail.strip()
        self._update_composer_state()

    def confirm_submission(self, expected_message: str) -> None:
        if self._input.text().strip() == expected_message.strip():
            self._input.clear()
        self.set_submission_state("idle")

    def _update_composer_state(self) -> None:
        editable = self._mutation_enabled and self._submission_state in {"idle", "error"}
        retryable_unknown = self._mutation_enabled and self._submission_state == "unknown"
        self._input.setEnabled(editable)
        self._send_btn.setEnabled(editable or retryable_unknown)

        if self._submission_state == "pending":
            text, color = "СОХРАНЕНИЕ…", theme.STATUS_INFO
            detail = self._submission_detail or text
        elif self._submission_state == "unknown":
            text, color = "ИСХОД НЕИЗВЕСТЕН", theme.STATUS_CAUTION
            detail = self._submission_detail or text
        elif self._submission_state == "error":
            text, color = "НЕ СОХРАНЕНО", theme.STATUS_FAULT
            detail = self._submission_detail or text
        elif not self._mutation_enabled:
            text, color = self._authority_message or "НЕДОСТУПНО", theme.MUTED_FOREGROUND
            detail = self._authority_message or text
        elif self._read_stale_detail:
            text, color = "ЖУРНАЛ НЕ ОБНОВЛЁН", theme.STATUS_CAUTION
            detail = self._read_stale_detail
        else:
            self._status_label.setVisible(False)
            self._status_label.setText("")
            self._status_label.setToolTip("")
            return

        self._status_label.setText(text)
        self._status_label.setToolTip(detail)
        self._status_label.setAccessibleName(text)
        self._status_label.setAccessibleDescription(detail)
        self._status_label.setStyleSheet(
            f"color: {color}; font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        self._status_label.setVisible(True)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: ANN001
        super().closeEvent(event)
