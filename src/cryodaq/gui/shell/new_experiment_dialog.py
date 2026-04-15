"""Modal dialog for creating new experiment (B.8 rebuild).

Full form with required + optional fields, template dropdown, validation.
Replaces the Block A stub.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

logger = logging.getLogger(__name__)


class NewExperimentDialog(QDialog):
    """Modal dialog for creating a new experiment."""

    experiment_create_requested = Signal(dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        available_templates: list[dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "\u041d\u043e\u0432\u044b\u0439 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"
        )
        self.setMinimumWidth(500)
        self.setModal(True)
        self._templates = available_templates or []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_4)

        form = QFormLayout()
        form.setSpacing(theme.SPACE_3)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(
            "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
        )
        self._name_edit.setMaxLength(100)
        form.addRow("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 *", self._name_edit)

        self._operator_edit = QLineEdit()
        form.addRow("\u041e\u043f\u0435\u0440\u0430\u0442\u043e\u0440 *", self._operator_edit)

        self._template_combo = QComboBox()
        self._template_combo.addItem(
            "\u2014 \u0431\u0435\u0437 \u0448\u0430\u0431\u043b\u043e\u043d\u0430 \u2014", "custom"
        )
        for t in self._templates:
            name = t.get("name", t.get("id", "?"))
            tid = t.get("id", t.get("template_id", "custom"))
            self._template_combo.addItem(name, tid)
        form.addRow("\u0428\u0430\u0431\u043b\u043e\u043d", self._template_combo)

        self._description_edit = QPlainTextEdit()
        self._description_edit.setMaximumHeight(60)
        form.addRow("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435", self._description_edit)

        self._target_t_spin = QDoubleSpinBox()
        self._target_t_spin.setRange(0.1, 350.0)
        self._target_t_spin.setValue(4.2)
        self._target_t_spin.setSuffix(" \u041a")
        self._target_t_spin.setDecimals(1)
        form.addRow("\u0426\u0435\u043b\u0435\u0432\u0430\u044f T", self._target_t_spin)

        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText(
            "\u043c\u0435\u0442\u043a\u0438 \u0447\u0435\u0440\u0435\u0437 \u0437\u0430\u043f\u044f\u0442\u0443\u044e"
        )
        form.addRow("\u041c\u0435\u0442\u043a\u0438", self._tags_edit)

        root.addLayout(form)

        self._validation_label = QLabel("")
        self._validation_label.setStyleSheet(
            f"color: {theme.STATUS_FAULT}; font-size: {theme.FONT_SIZE_SM}px;"
        )
        self._validation_label.setVisible(False)
        root.addWidget(self._validation_label)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("\u041e\u0442\u043c\u0435\u043d\u0430")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self._create_btn = QPushButton(
            "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"
        )
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create_clicked)
        btns.addWidget(self._create_btn)
        root.addLayout(btns)

    def _on_create_clicked(self) -> None:
        name = self._name_edit.text().strip()
        operator = self._operator_edit.text().strip()
        if not name:
            self._show_error("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435")
            self._name_edit.setFocus()
            return
        if not operator:
            self._show_error("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043e\u043f\u0435\u0440\u0430\u0442\u043e\u0440\u0430")
            self._operator_edit.setFocus()
            return

        tags = list(dict.fromkeys(
            t.strip() for t in self._tags_edit.text().split(",") if t.strip()
        ))
        payload = {
            "name": name,
            "operator": operator,
            "template_id": self._template_combo.currentData() or "custom",
            "description": self._description_edit.toPlainText().strip(),
            "target_T_cold": self._target_t_spin.value(),
            "tags": tags,
        }
        self.experiment_create_requested.emit(payload)
        self.accept()

    def _show_error(self, msg: str) -> None:
        self._validation_label.setText(msg)
        self._validation_label.setVisible(True)
