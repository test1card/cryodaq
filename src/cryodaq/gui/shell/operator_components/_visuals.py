"""Shared token-driven painting and bounded-text helpers."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from html import escape

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QLabel, QWidget

from cryodaq.gui import theme
from cryodaq.gui.presentation_severity import operator_state_for_display
from cryodaq.operator_snapshot import OperatorPresentationState

VISIBLE_TEXT_LIMIT = 160


@dataclass(frozen=True, slots=True)
class StateVisual:
    label: str
    accessible_label: str
    color: str
    shape: str


@dataclass(frozen=True, slots=True)
class PreparedText:
    visible: str
    accessible: str
    tooltip: str


STATE_VISUALS = {
    OperatorPresentationState.OK: StateVisual("НОРМА", "Норма", theme.STATUS_OK, "circle"),
    OperatorPresentationState.CAUTION: StateVisual("ВНИМАНИЕ", "Требует внимания", theme.STATUS_CAUTION, "triangle"),
    OperatorPresentationState.FAULT: StateVisual("АВАРИЯ", "Авария", theme.STATUS_FAULT, "square"),
    OperatorPresentationState.STALE: StateVisual("УСТАРЕЛО", "Данные устарели", theme.STATUS_STALE, "hollow_circle"),
    OperatorPresentationState.DISCONNECTED: StateVisual("НЕТ СВЯЗИ", "Нет связи", theme.STATUS_STALE, "diamond"),
}


def state_visual(state: OperatorPresentationState) -> StateVisual:
    """Resolve one operator-visible visual while accepting legacy states."""

    return STATE_VISUALS[operator_state_for_display(state)]


def body_font(*, semibold: bool = False) -> QFont:
    font = QFont(theme.FONT_BODY, theme.FONT_BODY_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD if semibold else theme.FONT_BODY_WEIGHT))
    return font


def label_font(*, semibold: bool = False) -> QFont:
    font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD if semibold else theme.FONT_LABEL_WEIGHT))
    return font


def set_text_color(widget: QWidget, color: str) -> None:
    """Apply a canonical token through Qt's palette, never widget-local QSS."""

    palette = widget.palette()
    token = QColor(color)
    palette.setColor(QPalette.ColorRole.WindowText, token)
    palette.setColor(QPalette.ColorRole.Text, token)
    palette.setColor(QPalette.ColorRole.ButtonText, token)
    widget.setPalette(palette)


def paint_state_shape(
    painter: QPainter,
    state: OperatorPresentationState,
    *,
    center_x: int,
    center_y: int,
    radius: int = theme.SPACE_1,
) -> None:
    """Paint the canonical state-specific non-color shape."""

    display_state = operator_state_for_display(state)
    visual = STATE_VISUALS[display_state]
    color = QColor(visual.color)
    pen = QPen(color, 2)
    if display_state is OperatorPresentationState.DISCONNECTED:
        pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.setBrush(color if visual.shape in {"circle", "triangle", "square"} else Qt.BrushStyle.NoBrush)
    if visual.shape in {"circle", "hollow_circle"}:
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
    elif visual.shape == "triangle":
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(center_x, center_y - radius),
                    QPoint(center_x - radius, center_y + radius),
                    QPoint(center_x + radius, center_y + radius),
                ]
            )
        )
    elif visual.shape == "square":
        painter.drawRect(center_x - radius, center_y - radius, radius * 2, radius * 2)
    else:
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(center_x, center_y - radius),
                    QPoint(center_x - radius, center_y),
                    QPoint(center_x, center_y + radius),
                    QPoint(center_x + radius, center_y),
                ]
            )
        )


def bounded_visible_text(value: str, *, limit: int = VISIBLE_TEXT_LIMIT) -> tuple[str, str]:
    """Bound geometry while retaining full authority in accessibility text.

    The visible form retains both ends, declares truncation, and includes a
    stable digest.  The complete source text is returned for accessible
    description and tooltip use.
    """

    safe = safe_plain_text(value)
    if len(safe) <= limit:
        return safe, safe
    digest = sha256(value.encode("utf-8")).hexdigest()[:10]
    marker = f" … [сокращено, sha256:{digest}] … "
    budget = max(2, limit - len(marker))
    head = budget * 2 // 3
    tail = budget - head
    return f"{safe[:head]}{marker}{safe[-tail:]}", safe


def safe_plain_text(value: str) -> str:
    """Expose control/format characters instead of letting them affect UI."""

    if not isinstance(value, str):
        raise TypeError("operator text must be a string")
    result: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"}:
            result.append(f"⟦U+{ord(character):04X}⟧")
        else:
            result.append(character)
    return "".join(result)


def plain_text_tooltip(*lines: str) -> str:
    """Return owned rich-text chrome containing only escaped plain payloads."""

    encoded = "<br/>".join(escape(safe_plain_text(line), quote=True) for line in lines)
    return f"<qt>{encoded}</qt>"


def prepare_text(value: str, *, limit: int = VISIBLE_TEXT_LIMIT) -> PreparedText:
    visible, full = bounded_visible_text(value, limit=limit)
    return PreparedText(visible=visible, accessible=full, tooltip=plain_text_tooltip(full))


def set_prepared_label(label: QLabel, prepared: PreparedText) -> None:
    label.setText(prepared.visible)
    label.setToolTip(prepared.tooltip)
    label.setAccessibleName(prepared.visible)
    label.setAccessibleDescription(prepared.accessible)


def set_bounded_label(label: QLabel, value: str) -> None:
    set_prepared_label(label, prepare_text(value))


def configure_text_label(
    label: QLabel,
    *,
    muted: bool = False,
    semibold: bool = False,
    wrap: bool = True,
) -> None:
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    label.setFont(body_font(semibold=semibold) if not muted else label_font(semibold=semibold))
    set_text_color(label, theme.MUTED_FOREGROUND if muted else theme.FOREGROUND)
