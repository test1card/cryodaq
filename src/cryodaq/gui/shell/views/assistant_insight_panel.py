"""AssistantInsightPanel — operator-facing assistant insight viewer.

Displays the last 10 LLM-generated insights from AssistantLiveAgent.
Populated via push_insight() by the shell when it receives
assistant_insight events.

DS compliance: all colors and fonts from theme tokens.
No hardcoded hex/px values.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

logger = logging.getLogger(__name__)

_MAX_INSIGHTS = 10

# Trigger type → (short label, status color token)
_TRIGGER_META: dict[str, tuple[str, str]] = {
    "alarm_fired": ("АЛАРМ", theme.STATUS_WARNING),
    "experiment_finalize": ("ЭКСП", theme.STATUS_INFO),
    "experiment_stop": ("ЭКСП", theme.STATUS_INFO),
    "experiment_abort": ("ПРЕРВАН", theme.STATUS_FAULT),
    "sensor_anomaly_critical": ("ДАТЧИК", theme.STATUS_FAULT),
    "shift_handover_request": ("СМЕНА", theme.STATUS_OK),
    "periodic_report_request": ("ОТЧЁТ", theme.STATUS_INFO),
}
_DEFAULT_META = ("СОБЫТИЕ", theme.STATUS_STALE)


class _InsightEntry(NamedTuple):
    text: str
    trigger_event_type: str
    timestamp: datetime


class _TriggerChip(QLabel):
    """Colored label chip showing trigger type."""

    def __init__(self, trigger_event_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label, color = _TRIGGER_META.get(trigger_event_type, _DEFAULT_META)
        self.setText(label)
        self.setFixedHeight(18)
        font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
        font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(6, 0, 6, 0)
        self.setStyleSheet(
            f"background: {color}; color: {theme.BACKGROUND}; border-radius: 3px;"
        )


class _InsightCard(QFrame):
    """Single insight card: timestamp chip + trigger chip + LLM text."""

    def __init__(self, entry: _InsightEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"background: {theme.SURFACE_CARD}; border-radius: 6px;"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Header row: timestamp + trigger chip
        header = QHBoxLayout()
        header.setSpacing(8)

        ts_label = QLabel(entry.timestamp.astimezone().strftime("%H:%M:%S"))
        ts_font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
        ts_label.setFont(ts_font)
        ts_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        header.addWidget(ts_label)

        header.addWidget(_TriggerChip(entry.trigger_event_type))
        header.addStretch()
        root.addLayout(header)

        # LLM text
        text_label = QLabel(entry.text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_SM)
        text_label.setFont(text_font)
        text_label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
        root.addWidget(text_label)


class AssistantInsightPanel(QWidget):
    """Panel displaying last N assistant insights.

    Public API:
      push_insight(text, trigger_event_type, timestamp)  — add one insight
      clear()                                             — remove all insights
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        brand_name: str = "Гемма",
        brand_emoji: str = "🤖",
    ) -> None:
        super().__init__(parent)
        self._brand_name = brand_name
        self._brand_emoji = brand_emoji
        self._entries: deque[_InsightEntry] = deque(maxlen=_MAX_INSIGHTS)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background: {theme.BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Panel header
        header_frame = QFrame()
        header_frame.setFixedHeight(40)
        header_frame.setStyleSheet(
            f"background: {theme.SURFACE_PANEL};"
            f" border-bottom: 1px solid {theme.BORDER};"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 0, 12, 0)

        title = QLabel(f"{self._brand_emoji} {self._brand_name} — ИИ аналитика")
        title_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
        title_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.FOREGROUND};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._count_label = QLabel("")
        count_font = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
        self._count_label.setFont(count_font)
        self._count_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        header_layout.addWidget(self._count_label)

        root.addWidget(header_frame)

        # Scroll area for insight cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"background: {theme.BACKGROUND};")

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet(f"background: {theme.BACKGROUND};")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(12, 12, 12, 12)
        self._cards_layout.setSpacing(8)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._cards_widget)
        root.addWidget(scroll)
        self._scroll = scroll

        self._placeholder = QLabel(f"{self._brand_name} ещё не прислала ни одного сообщения.")
        placeholder_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_SM)
        self._placeholder.setFont(placeholder_font)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        self._placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._cards_layout.addWidget(self._placeholder)

    def push_insight(
        self,
        text: str,
        trigger_event_type: str = "",
        timestamp: datetime | None = None,
    ) -> None:
        """Add one insight to the panel (newest at top, max 10 kept)."""
        if timestamp is None:
            timestamp = datetime.now(UTC)
        entry = _InsightEntry(
            text=text,
            trigger_event_type=trigger_event_type,
            timestamp=timestamp,
        )
        self._entries.appendleft(entry)
        self._rebuild_cards()
        logger.debug(
            "AssistantInsightPanel: push_insight trigger=%s len=%d",
            trigger_event_type,
            len(self._entries),
        )

    def clear(self) -> None:
        """Remove all displayed insights."""
        self._entries.clear()
        self._rebuild_cards()

    def _rebuild_cards(self) -> None:
        # Remove all items; deleteLater() only transient InsightCard instances,
        # not self._placeholder which is a persistent widget reused across rebuilds.
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._placeholder:
                w.deleteLater()
        self._placeholder.setVisible(False)

        if not self._entries:
            self._cards_layout.addWidget(self._placeholder)
            self._placeholder.setVisible(True)
            self._count_label.setText("")
            return

        n = len(self._entries)
        self._count_label.setText(f"{n}/{_MAX_INSIGHTS}")
        for entry in self._entries:
            card = _InsightCard(entry, self._cards_widget)
            self._cards_layout.addWidget(card)

        # Scroll to top to show newest
        self._scroll.verticalScrollBar().setValue(0)
