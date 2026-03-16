from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QWidget,
)

from cryodaq.gui.widgets.common import add_form_rows


class ExperimentStartDialog(QDialog):
    def __init__(self, templates: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новый эксперимент")
        self._templates = templates
        self._custom_edits: dict[str, QLineEdit] = {}

        layout = QFormLayout(self)
        self._template_combo = QComboBox()
        for template in templates:
            self._template_combo.addItem(str(template["name"]), template)
        self._template_combo.currentIndexChanged.connect(self._rebuild_custom_fields)

        self._title_edit = QLineEdit()
        self._operator_edit = QLineEdit()
        self._sample_edit = QLineEdit()
        self._cryostat_edit = QLineEdit()
        self._description_edit = QTextEdit()
        self._description_edit.setMaximumHeight(80)
        self._notes_edit = QTextEdit()
        self._notes_edit.setMaximumHeight(80)

        add_form_rows(
            layout,
            [
                ("Шаблон:", self._template_combo),
                ("Название:", self._title_edit),
                ("Оператор:", self._operator_edit),
                ("Образец:", self._sample_edit),
                ("Криостат:", self._cryostat_edit),
                ("Описание:", self._description_edit),
                ("Заметки:", self._notes_edit),
            ],
        )

        self._custom_anchor_index = layout.rowCount()
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Запустить")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addRow(self._buttons)
        self._layout = layout

        self._rebuild_custom_fields()

    def payload(self) -> dict[str, Any]:
        template = self._template_combo.currentData()
        title = self._title_edit.text().strip()
        return {
            "cmd": "experiment_start",
            "template_id": str(template["id"]),
            "title": title,
            "name": title,
            "operator": self._operator_edit.text().strip(),
            "sample": self._sample_edit.text().strip(),
            "cryostat": self._cryostat_edit.text().strip(),
            "description": self._description_edit.toPlainText().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
            "custom_fields": {
                field_id: edit.text().strip()
                for field_id, edit in self._custom_edits.items()
                if edit.text().strip()
            },
        }

    def _rebuild_custom_fields(self) -> None:
        while self._layout.rowCount() > self._custom_anchor_index + 1:
            self._layout.removeRow(self._custom_anchor_index)
        self._custom_edits.clear()

        template = self._template_combo.currentData() or {}
        for field in template.get("custom_fields", []):
            field_id = str(field["id"])
            edit = QLineEdit()
            edit.setPlaceholderText(str(field.get("default", "")))
            self._custom_edits[field_id] = edit
            row_index = self._custom_anchor_index + len(self._custom_edits) - 1
            self._layout.insertRow(row_index, f"{field['label']}:", edit)


class ExperimentFinalizeDialog(QDialog):
    def __init__(self, active_experiment: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Завершить эксперимент")
        self._active = active_experiment
        self._custom_edits: dict[str, QLineEdit] = {}

        layout = QFormLayout(self)
        self._title_edit = QLineEdit(str(active_experiment.get("title", "")))
        self._sample_edit = QLineEdit(str(active_experiment.get("sample", "")))
        self._description_edit = QTextEdit(str(active_experiment.get("description", "")))
        self._description_edit.setMaximumHeight(80)
        self._notes_edit = QTextEdit(str(active_experiment.get("notes", "")))
        self._notes_edit.setMaximumHeight(80)
        self._status_combo = QComboBox()
        self._status_combo.addItem("Завершён", "COMPLETED")
        self._status_combo.addItem("Прерван", "ABORTED")

        template_line = QLineEdit(str(active_experiment.get("template_id", "")))
        template_line.setEnabled(False)
        add_form_rows(
            layout,
            [
                ("Шаблон:", template_line),
                ("Название:", self._title_edit),
                ("Образец:", self._sample_edit),
                ("Описание:", self._description_edit),
                ("Заметки:", self._notes_edit),
                ("Итоговый статус:", self._status_combo),
            ],
        )

        custom_fields = dict(active_experiment.get("custom_fields") or {})
        for field_id, value in custom_fields.items():
            edit = QLineEdit(str(value))
            self._custom_edits[str(field_id)] = edit
            layout.addRow(f"{field_id}:", edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Завершить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def payload(self) -> dict[str, Any]:
        return {
            "cmd": "experiment_finalize",
            "experiment_id": str(self._active.get("experiment_id", "")),
            "title": self._title_edit.text().strip(),
            "sample": self._sample_edit.text().strip(),
            "description": self._description_edit.toPlainText().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
            "status": str(self._status_combo.currentData()),
            "custom_fields": {
                field_id: edit.text().strip()
                for field_id, edit in self._custom_edits.items()
                if edit.text().strip()
            },
        }
