"""NewExperimentDialog — full rebuild restoring legacy feature parity (B.8.0.2).

Modal dialog with templates, autocomplete, dynamic custom fields per template,
full legacy payload on submit.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.user_preferences import UserPreferences, suggest_experiment_name
from cryodaq.gui import theme
from cryodaq.paths import get_data_dir

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
            "\u041d\u043e\u0432\u044b\u0439 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"  # noqa: E501
        )
        self.setMinimumWidth(550)
        self.setModal(True)
        self._templates = available_templates or []
        self._templates_by_id = {str(t.get("id", "")): t for t in self._templates if t.get("id")}
        self._custom_edits: dict[str, QLineEdit] = {}
        self._preferences = UserPreferences(get_data_dir() / "user_preferences.json")
        self._build_ui()
        self._apply_preferences()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACE_3)

        form = QFormLayout()
        form.setSpacing(theme.SPACE_2)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Template
        self._template_combo = QComboBox()
        self._template_combo.addItem(
            "\u2014 \u0431\u0435\u0437 \u0448\u0430\u0431\u043b\u043e\u043d\u0430 \u2014", "custom"
        )
        for t in self._templates:
            name = t.get("name", t.get("id", "?"))
            tid = t.get("id", t.get("template_id", "custom"))
            self._template_combo.addItem(name, tid)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        form.addRow("\u0428\u0430\u0431\u043b\u043e\u043d:", self._template_combo)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setMaxLength(100)
        form.addRow("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 *:", self._name_edit)

        # Operator (editable combobox with history)
        self._operator_combo = QComboBox()
        self._operator_combo.setEditable(True)
        self._operator_combo.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
        from PySide6.QtCore import QSettings

        known_ops = QSettings("FIAN", "CryoDAQ").value("known_operators", [])
        if isinstance(known_ops, list) and known_ops:
            self._operator_combo.addItems(known_ops)
        form.addRow("\u041e\u043f\u0435\u0440\u0430\u0442\u043e\u0440 *:", self._operator_combo)

        # Sample
        self._sample_edit = QLineEdit()
        form.addRow("\u041e\u0431\u0440\u0430\u0437\u0435\u0446:", self._sample_edit)

        # Cryostat (editable combobox)
        self._cryostat_combo = QComboBox()
        self._cryostat_combo.setEditable(True)
        self._cryostat_combo.addItems(
            [
                "\u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0410\u041a\u0426 \u0424\u0418\u0410\u041d"  # noqa: E501
            ]
        )
        form.addRow("\u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442:", self._cryostat_combo)

        # Description
        self._description_edit = QPlainTextEdit()
        self._description_edit.setMaximumHeight(60)
        form.addRow("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435:", self._description_edit)

        # Notes
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setMaximumHeight(60)
        form.addRow("\u0417\u0430\u043c\u0435\u0442\u043a\u0438:", self._notes_edit)

        root.addLayout(form)

        # Custom fields (dynamic per template)
        self._custom_form = QFormLayout()
        self._custom_form.setSpacing(theme.SPACE_2)
        root.addLayout(self._custom_form)

        # Validation hint
        self._validation_label = QLabel("")
        self._validation_label.setStyleSheet(
            f"color: {theme.STATUS_FAULT}; font-size: {theme.FONT_SIZE_SM}px;"
        )
        self._validation_label.setVisible(False)
        root.addWidget(self._validation_label)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("\u041e\u0442\u043c\u0435\u043d\u0430")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self._create_btn = QPushButton(
            "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"  # noqa: E501
        )
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create_clicked)
        btns.addWidget(self._create_btn)
        root.addLayout(btns)

    def _apply_preferences(self) -> None:
        last = self._preferences.get_last_experiment()
        if last.get("operator") and not self._operator_combo.currentText():
            self._operator_combo.setCurrentText(last["operator"])
        if last.get("sample") and not self._sample_edit.text():
            self._sample_edit.setText(last["sample"])
        if last.get("cryostat") and not self._cryostat_combo.currentText():
            self._cryostat_combo.setCurrentText(last["cryostat"])

        def _make_completer(items: list[str]) -> QCompleter:
            c = QCompleter(items, self)
            c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            return c

        self._operator_combo.lineEdit().setCompleter(
            _make_completer(self._preferences.get_history("operator"))
        )
        self._sample_edit.setCompleter(_make_completer(self._preferences.get_history("sample")))
        self._cryostat_combo.lineEdit().setCompleter(
            _make_completer(self._preferences.get_history("cryostat"))
        )

    def _on_template_changed(self) -> None:
        self._rebuild_custom_fields()
        self._suggest_name()

    def _suggest_name(self) -> None:
        if self._name_edit.text().strip():
            return
        tid = self._template_combo.currentData() or ""
        if tid == "custom":
            return
        t = self._templates_by_id.get(tid, {})
        name_map = {tid: t.get("name", tid)} if tid else {}
        suggested = suggest_experiment_name(tid, [], name_map)
        self._name_edit.setText(suggested)

    def _rebuild_custom_fields(self) -> None:
        while self._custom_form.rowCount() > 0:
            self._custom_form.removeRow(0)
        self._custom_edits.clear()
        tid = self._template_combo.currentData() or "custom"
        t = self._templates_by_id.get(tid, {})
        for field in t.get("custom_fields", []):
            fid = str(field.get("id", "")).strip()
            if not fid:
                continue
            edit = QLineEdit()
            edit.setPlaceholderText(str(field.get("default", "")))
            edit.setObjectName(f"custom_{fid}")
            self._custom_edits[fid] = edit
            self._custom_form.addRow(f"{field.get('label', fid)}:", edit)

    def _on_create_clicked(self) -> None:
        name = self._name_edit.text().strip()
        operator = self._operator_combo.currentText().strip()
        if not name:
            self._show_error(
                "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435"  # noqa: E501
            )
            self._name_edit.setFocus()
            return
        if not operator:
            self._show_error(
                "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043e\u043f\u0435\u0440\u0430\u0442\u043e\u0440\u0430"  # noqa: E501
            )
            self._operator_combo.setFocus()
            return

        payload = {
            "cmd": "experiment_create",
            "template_id": self._template_combo.currentData() or "custom",
            "title": name,
            "name": name,
            "operator": operator,
            "sample": self._sample_edit.text().strip(),
            "cryostat": self._cryostat_combo.currentText().strip(),
            "description": self._description_edit.toPlainText().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
            "custom_fields": {
                fid: edit.text().strip()
                for fid, edit in self._custom_edits.items()
                if edit.text().strip()
            },
        }

        # Save preferences
        if operator:
            from PySide6.QtCore import QSettings

            s = QSettings("FIAN", "CryoDAQ")
            known = s.value("known_operators", [])
            if not isinstance(known, list):
                known = []
            if operator not in known:
                known.insert(0, operator)
                known = known[:20]
                s.setValue("known_operators", known)

        self._preferences.save_last_experiment(
            template_id=str(payload.get("template_id", "")),
            operator=operator,
            sample=str(payload.get("sample", "")),
            cryostat=str(payload.get("cryostat", "")),
            description=str(payload.get("description", "")),
            custom_fields=payload.get("custom_fields", {}),
        )

        self.experiment_create_requested.emit(payload)
        self.accept()

    def _show_error(self, msg: str) -> None:
        self._validation_label.setText(msg)
        self._validation_label.setVisible(True)
