"""Navigation-only next-action control."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from cryodaq.gui import theme

from ._visuals import body_font, bounded_visible_text, plain_text_tooltip

_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")
_IDENTIFIER_MAX_BYTES = 64
_OPERATOR_TEXT_MAX_BYTES = 256
_BIDI_CONTROL_CLASSES = frozenset({"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI", "BN"})


@dataclass(frozen=True, slots=True)
class NavigationIntent:
    """A logical destination request; never a route execution or command."""

    intent_id: str
    destination: str
    operator_text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", _identifier(self.intent_id, field_name="intent_id"))
        object.__setattr__(self, "destination", _identifier(self.destination, field_name="destination"))
        object.__setattr__(self, "operator_text", _operator_copy(self.operator_text))


class NextActionNavigationControl(QAbstractButton):
    """Keyboard-accessible control that emits intent and performs no action."""

    navigation_requested = Signal(object)

    def __init__(self, intent: NavigationIntent | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._intent: NavigationIntent | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._emit_intent)
        self.set_intent(intent)

    @property
    def intent(self) -> NavigationIntent | None:
        return self._intent

    def set_intent(self, intent: NavigationIntent | None) -> None:
        if intent is not None and not isinstance(intent, NavigationIntent):
            raise TypeError("intent must be a NavigationIntent or None")
        self._intent = intent
        self.setEnabled(intent is not None)
        if intent is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setText("Действие недоступно")
            self.setAccessibleName("Следующий шаг недоступен")
            self.setAccessibleDescription("Нет разрешённого навигационного перехода.")
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            visible, full = bounded_visible_text(intent.operator_text, limit=72)
            self.setText(visible)
            self.setToolTip(plain_text_tooltip(full))
            self.setAccessibleName(f"Следующий шаг: {full}")
            self.setAccessibleDescription(
                f"Навигация к разделу {intent.destination}. Управляющая команда не отправляется."
            )
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        width = max(160, self.fontMetrics().horizontalAdvance(self.text()) + theme.SPACE_6)
        return QSize(min(width, 640), theme.ROW_HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(body_font(semibold=True))
        rect = self.rect().adjusted(1, 1, -1, -1)
        background = theme.SURFACE_ELEVATED if self.isEnabled() else theme.SURFACE_CARD
        if self.isDown():
            background = theme.BORDER
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, theme.RADIUS_SM, theme.RADIUS_SM)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.FOCUS_RING), 2))
            painter.drawRoundedRect(rect, theme.RADIUS_SM, theme.RADIUS_SM)
        painter.setPen(QColor(theme.FOREGROUND if self.isEnabled() else theme.TEXT_DISABLED))
        painter.drawText(
            rect.adjusted(theme.SPACE_3, 0, -theme.SPACE_3, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )

    def _emit_intent(self) -> None:
        if self._intent is not None:
            self.navigation_requested.emit(self._intent)


def _identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if len(value.encode("utf-8")) > _IDENTIFIER_MAX_BYTES:
        raise ValueError(f"{field_name} exceeds {_IDENTIFIER_MAX_BYTES} UTF-8 bytes")
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must match [a-z][a-z0-9_-]*")
    return value


def _operator_copy(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("operator_text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip():
        raise ValueError("operator_text must be non-empty without outer whitespace")
    if len(normalized.encode("utf-8")) > _OPERATOR_TEXT_MAX_BYTES:
        raise ValueError(f"operator_text exceeds {_OPERATOR_TEXT_MAX_BYTES} UTF-8 bytes")
    if "<" in normalized or ">" in normalized:
        raise ValueError("operator_text must not contain markup delimiters")
    if any(
        unicodedata.category(character) in {"Cc", "Cf"} or unicodedata.bidirectional(character) in _BIDI_CONTROL_CLASSES
        for character in normalized
    ):
        raise ValueError("operator_text must not contain control or bidi-format characters")
    return normalized
