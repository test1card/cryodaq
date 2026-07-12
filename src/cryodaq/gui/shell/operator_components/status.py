"""Canonical six-state status label."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from cryodaq.gui import theme
from cryodaq.operator_snapshot import OperatorPresentationState

from ._visuals import STATE_VISUALS, label_font, paint_state_shape, plain_text_tooltip


class CanonicalStatusLabel(QWidget):
    """Static state label using text plus a distinct painted shape."""

    def __init__(
        self,
        state: OperatorPresentationState = OperatorPresentationState.DISCONNECTED,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = OperatorPresentationState.DISCONNECTED
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFont(label_font(semibold=True))
        self.set_state(state)

    @property
    def state(self) -> OperatorPresentationState:
        return self._state

    def set_state(self, state: OperatorPresentationState) -> None:
        if not isinstance(state, OperatorPresentationState):
            raise TypeError("state must be an OperatorPresentationState")
        self._state = state
        visual = STATE_VISUALS[state]
        self.setAccessibleName(f"Состояние: {visual.accessible_label}")
        self.setAccessibleDescription(
            f"Каноническое состояние {state.value}; обозначено формой и текстом {visual.label}."
        )
        self.setToolTip(plain_text_tooltip(visual.accessible_label))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        visual = STATE_VISUALS[self._state]
        return QSize(theme.SPACE_3 + theme.SPACE_2 + metrics.horizontalAdvance(visual.label), theme.ROW_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        del event
        visual = STATE_VISUALS[self._state]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(label_font(semibold=True))

        center_x = theme.SPACE_2
        center_y = self.height() // 2
        radius = theme.SPACE_1
        paint_state_shape(painter, self._state, center_x=center_x, center_y=center_y, radius=radius)

        painter.setPen(QColor(theme.FOREGROUND))
        text_rect = self.rect().adjusted(theme.SPACE_3, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, visual.label)
