"""Readiness blocker presentation row."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.operator_snapshot import ReadinessBlocker

from ._visuals import configure_text_label, safe_plain_text, set_bounded_label
from .status import CanonicalStatusLabel


class ReadinessBlockerRow(QWidget):
    """Pure rendering of one backend-owned readiness blocker."""

    def __init__(self, blocker: ReadinessBlocker | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE_1, 0, theme.SPACE_1)
        layout.setSpacing(theme.SPACE_3)
        self.status_label = CanonicalStatusLabel(parent=self)
        layout.addWidget(self.status_label, 0)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(theme.SPACE_1)
        self.blocker_label = QLabel(self)
        self.evidence_label = QLabel(self)
        configure_text_label(self.blocker_label, semibold=True)
        configure_text_label(self.evidence_label, muted=True)
        text_column.addWidget(self.blocker_label)
        text_column.addWidget(self.evidence_label)
        layout.addLayout(text_column, 1)
        self.setAccessibleName("Причина блокировки готовности")
        if blocker is not None:
            self.render(blocker)

    def render(self, blocker: ReadinessBlocker) -> None:
        if not isinstance(blocker, ReadinessBlocker):
            raise TypeError("blocker must be a ReadinessBlocker")
        self.setUpdatesEnabled(False)
        try:
            self.status_label.set_state(blocker.state)
            set_bounded_label(self.blocker_label, blocker.operator_text)
            set_bounded_label(self.evidence_label, f"Нужно подтвердить: {blocker.required_evidence}")
            self.setAccessibleDescription(
                safe_plain_text(
                    f"{blocker.operator_text}. Нужно подтвердить: {blocker.required_evidence}. Код: {blocker.code}."
                )
            )
        finally:
            self.setUpdatesEnabled(True)
        self.update()
