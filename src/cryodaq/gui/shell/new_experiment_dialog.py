"""NewExperimentDialog — stub for Phase UI-1 v2 Block A.

Real form lands in Block E. This stub exists so the tool rail ``+`` button
has a dialog to open without crashing.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class NewExperimentDialog(QDialog):
    """Placeholder modal dialog for new-experiment creation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создание эксперимента")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        label = QLabel("Создание эксперимента — в разработке")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
