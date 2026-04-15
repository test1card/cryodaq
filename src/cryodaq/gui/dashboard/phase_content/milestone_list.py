"""Milestone list — compact list of completed phase milestones."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cryodaq.core.phase_labels import label_for
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_content.eta_display import (
    _format_duration_ru,
)


class MilestoneList(QWidget):
    """Compact list of completed phase milestones for teardown view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("milestoneList")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1
        )
        self._layout.setSpacing(2)
        self._empty_label = QLabel(
            "\u041d\u0435\u0442 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0445 \u0444\u0430\u0437"
        )  # Нет завершённых фаз
        self._empty_label.setObjectName("milestoneEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"#milestoneEmpty {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        self._layout.addWidget(self._empty_label)
        self._row_labels: list[QLabel] = []

    def set_milestones(self, milestones: list[dict]) -> None:
        # Clear previous rows
        for lbl in self._row_labels:
            self._layout.removeWidget(lbl)
            lbl.deleteLater()
        self._row_labels.clear()

        if not milestones:
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)

        for ms in milestones:
            phase_name = label_for(ms.get("phase"))
            duration_s = ms.get("duration_s", 0)
            duration_text = _format_duration_ru(duration_s) if duration_s else "\u2014"
            row = QLabel(f"\u2022 {phase_name}  \u2014  {duration_text}")
            row.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; "
                f"font-family: '{theme.FONT_MONO}'; "
                f"font-size: {theme.FONT_SIZE_SM}px;"
            )
            self._layout.addWidget(row)
            self._row_labels.append(row)
