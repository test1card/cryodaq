"""F34 — AssistantChatPanel: Гемма chat overlay backed by AssistantQueryAgent.

Bubble-style chat surface that runs `assistant.query` ZMQ commands through a
non-blocking :class:`ZmqCommandWorker`. The panel reuses the F30 query agent
exactly as the Telegram bot does — no streaming, plain-text rendering only.
History is in-session only (no disk persistence).

Visual contract:
- Operator bubbles align right, ACCENT background + ON_ACCENT text.
- Assistant bubbles align left, SURFACE_CARD background + FOREGROUND text.
- Error responses prefix the assistant bubble with ⚠ and use STATUS_WARNING.
- Composer (input + send button) disables while a query is in flight.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_WELCOME_TEXT = (
    "Привет! Я Гемма, помощник по эксперименту. "
    "Спроси про температуру, давление, фазу, прогноз охлаждения или активные тревоги."
)
_ERROR_PREFIX = "⚠ "  # ⚠
# v0.55.2 ds-106: 16 * SPACE_6 + SPACE_2 = 512 + 8 = 520. Wide enough
# for paragraph answers, narrow enough to feel chat-like — value is
# now traceable back to the spacing scale.
_BUBBLE_MAX_WIDTH = 16 * theme.SPACE_6 + theme.SPACE_2
_QUERY_CHAT_ID = "gui"


class _ChatBubble(QFrame):
    """One chat bubble — operator (right) or assistant (left, optionally error-styled)."""

    def __init__(
        self,
        text: str,
        *,
        author: str,  # "operator" | "assistant" | "error"
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._author = author
        self.setObjectName("assistantChatBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        if author == "operator":
            bg = theme.ACCENT
            fg = theme.ON_ACCENT
        elif author == "error":
            bg = theme.STATUS_WARNING
            fg = theme.ON_PRIMARY
        else:
            bg = theme.SURFACE_CARD
            fg = theme.FOREGROUND

        self.setStyleSheet(
            f"#assistantChatBubble {{"
            f" background-color: {bg};"
            f" color: {fg};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f"}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        self._label = QLabel(text)
        body_font = QFont(theme.FONT_BODY)
        body_font.setPixelSize(theme.FONT_BODY_SIZE)
        self._label.setFont(body_font)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        self._label.setMaximumWidth(_BUBBLE_MAX_WIDTH)
        layout.addWidget(self._label)

    @property
    def author(self) -> str:
        return self._author

    def text(self) -> str:
        return self._label.text()


class AssistantChatPanel(QWidget):
    """F34 chat overlay for AssistantQueryAgent.

    Public API:
    - ``send_query(text)`` — programmatic submit (used by tests + return-key).
    - ``set_busy(bool)`` — toggle composer enablement.
    """

    # Emitted after a complete round-trip (query → response) for tests/observers.
    response_received = Signal(str, bool)  # (text, is_error)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantChatPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#assistantChatPanel {{ background-color: {theme.BACKGROUND}; }}"
        )

        # Retain refs so ZmqCommandWorker QThreads don't get GC'd mid-flight
        # while a reply is still pending.
        self._workers: list[ZmqCommandWorker] = []
        self._inflight: ZmqCommandWorker | None = None
        self._bubbles: list[_ChatBubble] = []

        self._build_ui()
        self._add_bubble(_WELCOME_TEXT, author="assistant")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        # Header
        header = QLabel("Помощник Гемма")
        title_font = QFont(theme.FONT_BODY)
        title_font.setPixelSize(theme.FONT_SIZE_XL)
        title_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        header.setFont(title_font)
        header.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        root.addWidget(header)

        # Bubble timeline (scroll area)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(f"background-color: {theme.BACKGROUND}; border: none;")

        self._timeline_host = QWidget()
        self._timeline_host.setStyleSheet("background: transparent;")
        self._timeline = QVBoxLayout(self._timeline_host)
        self._timeline.setContentsMargins(0, 0, 0, 0)
        self._timeline.setSpacing(theme.SPACE_2)
        self._timeline.addStretch(1)
        self._scroll.setWidget(self._timeline_host)
        root.addWidget(self._scroll, stretch=1)

        # Composer
        composer = QHBoxLayout()
        composer.setContentsMargins(0, 0, 0, 0)
        composer.setSpacing(theme.SPACE_2)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Спроси про эксперимент…")
        input_font = QFont(theme.FONT_BODY)
        input_font.setPixelSize(theme.FONT_BODY_SIZE)
        self._input.setFont(input_font)
        self._input.setStyleSheet(
            f"QLineEdit {{"
            f" background-color: {theme.SURFACE_SUNKEN};"
            f" color: {theme.FOREGROUND};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
            f"QLineEdit:disabled {{ color: {theme.MUTED_FOREGROUND}; }}"
        )
        self._input.returnPressed.connect(self._on_send_clicked)
        composer.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Отправить")
        self._send_btn.setStyleSheet(
            f"QPushButton {{"
            f" background-color: {theme.ACCENT};"
            f" color: {theme.ON_ACCENT};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
            f"QPushButton:disabled {{"
            f" background-color: {theme.SURFACE_MUTED};"
            f" color: {theme.MUTED_FOREGROUND};"
            f"}}"
        )
        self._send_btn.clicked.connect(self._on_send_clicked)
        composer.addWidget(self._send_btn)

        root.addLayout(composer)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_query(self, text: str) -> None:
        """Submit a query programmatically. No-op on empty / inflight."""
        text = text.strip()
        if not text:
            return
        if self._inflight is not None:
            return
        self._add_bubble(text, author="operator")
        self._input.clear()
        self.set_busy(True)
        worker = ZmqCommandWorker(
            {"cmd": "assistant.query", "query": text, "chat_id": _QUERY_CHAT_ID},
            parent=self,
        )
        self._inflight = worker
        self._workers.append(worker)
        worker.finished.connect(self._on_response)
        worker.start()

    def set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)

    # ------------------------------------------------------------------
    # Internal — bubbles + worker lifecycle
    # ------------------------------------------------------------------

    def _add_bubble(self, text: str, *, author: str) -> None:
        bubble = _ChatBubble(text, author=author)
        self._bubbles.append(bubble)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if author == "operator":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)
        # Insert before the trailing stretch so timeline grows top-down.
        self._timeline.insertWidget(self._timeline.count() - 1, row)

        # Auto-scroll to the newest bubble.
        scrollbar = self._scroll.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    @Slot(dict)
    def _on_response(self, result: dict) -> None:
        try:
            ok = bool(result.get("ok"))
            if ok:
                text = str(result.get("response") or "").strip() or "(пустой ответ)"
                self._add_bubble(text, author="assistant")
                self.response_received.emit(text, False)
            else:
                err = str(result.get("error") or "Неизвестная ошибка.")
                self._add_bubble(_ERROR_PREFIX + err, author="error")
                self.response_received.emit(err, True)
        finally:
            # Drop the inflight worker reference so the next send is allowed.
            sender = self.sender()
            if isinstance(sender, ZmqCommandWorker) and sender in self._workers:
                # v0.55.15 (audit SCOPE 5 finding 5.4) — actually
                # remove the QThread from the retention list. The previous
                # comment claimed cleanup but only called wait(0) (a no-op
                # zero-timeout join), so workers grew unbounded across an
                # operator session.
                try:
                    sender.wait(0)
                except RuntimeError:
                    pass
                self._workers.remove(sender)
                sender.deleteLater()
            self._inflight = None
            self.set_busy(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_send_clicked(self) -> None:
        self.send_query(self._input.text())
