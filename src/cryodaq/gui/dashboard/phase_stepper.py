"""Compact phase progression stepper (B.5.6).

Horizontal pills showing phase numbers 1-6. Current highlighted,
past muted, future dim. Hover tooltip shows full Russian phase name.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from cryodaq.core.phase_labels import PHASE_LABELS_PILL, PHASE_LABELS_RU, PHASE_ORDER
from cryodaq.gui import theme

PHASE_NUMBERS: dict[str, int] = {phase: idx + 1 for idx, phase in enumerate(PHASE_ORDER)}

_PILL_HEIGHT_PX = 24
_PILL_PADDING_PX = 6


class PhaseStepper(QWidget):
    """Compact horizontal phase stepper — numbers only, tooltip names."""

    phase_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("phaseStepper")
        self._pills: dict[str, QFrame] = {}
        self._current_phase: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for phase in PHASE_ORDER:
            pill = self._make_pill(phase)
            self._pills[phase] = pill
            layout.addWidget(pill)
            if phase != PHASE_ORDER[-1]:
                arrow = QLabel("\u203a")  # › (smaller than →)
                arrow.setObjectName(f"stepperArrow_{phase}")
                arrow.setStyleSheet(
                    f"#{arrow.objectName()} {{ "
                    f"color: {theme.MUTED_FOREGROUND}; "
                    f"font-size: {theme.FONT_SIZE_XS}px; "
                    f"}}"
                )
                layout.addWidget(arrow)

    def _make_pill(self, phase: str) -> QFrame:
        pill = QFrame()
        pill.setObjectName(f"stepperPill_{phase}")
        pill.setFixedHeight(_PILL_HEIGHT_PX)
        pill.setToolTip(PHASE_LABELS_RU[phase])
        inner = QHBoxLayout(pill)
        inner.setContentsMargins(_PILL_PADDING_PX, 1, _PILL_PADDING_PX, 1)
        inner.setSpacing(4)
        num = QLabel(str(PHASE_NUMBERS[phase]))
        num.setObjectName(f"stepperPillNum_{phase}")
        inner.addWidget(num)
        short = QLabel(PHASE_LABELS_PILL[phase])
        short.setObjectName(f"stepperPillShort_{phase}")
        inner.addWidget(short)
        self._style_pill(pill, "future")
        return pill

    def _style_pill(self, pill: QFrame, state: str) -> None:
        pid = pill.objectName()
        if state == "current":
            border, bg, fg = theme.ACCENT, theme.SECONDARY, theme.FOREGROUND
        elif state == "past":
            border, bg, fg = theme.BORDER, "transparent", theme.MUTED_FOREGROUND
        else:
            border, bg, fg = theme.BORDER, "transparent", theme.MUTED_FOREGROUND
        pill.setStyleSheet(
            f"#{pid} {{ "
            f"background-color: {bg}; "
            f"border: 1px solid {border}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"}} "
            f"#{pid} QLabel {{ "
            f"color: {fg}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"background: transparent; border: none; "
            f"}}"
        )

    def set_current_phase(self, phase: str | None) -> None:
        self._current_phase = phase
        if phase is None:
            for p in PHASE_ORDER:
                self._style_pill(self._pills[p], "future")
            return
        try:
            idx = PHASE_ORDER.index(phase)
        except ValueError:
            return
        for i, p in enumerate(PHASE_ORDER):
            if i < idx:
                self._style_pill(self._pills[p], "past")
            elif i == idx:
                self._style_pill(self._pills[p], "current")
            else:
                self._style_pill(self._pills[p], "future")
