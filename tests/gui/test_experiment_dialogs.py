from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.experiment_dialogs import (
    ExperimentFinalizeDialog,
    ExperimentStartDialog,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_start_dialog_builds_payload_from_template() -> None:
    _app()
    dialog = ExperimentStartDialog(
        [
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup"],
                "report_enabled": True,
                "custom_fields": [{"id": "target_temperature", "label": "Target Temperature"}],
            }
        ]
    )

    assert dialog.windowTitle() == "Новый эксперимент"

    dialog._title_edit.setText("Cooldown 01")
    dialog._operator_edit.setText("Ivanov")
    dialog._sample_edit.setText("Sample A")
    dialog._custom_edits["target_temperature"].setText("4.2 K")

    payload = dialog.payload()

    assert payload["cmd"] == "experiment_start"
    assert payload["template_id"] == "cooldown_test"
    assert payload["title"] == "Cooldown 01"
    assert payload["custom_fields"]["target_temperature"] == "4.2 K"


def test_finalize_dialog_builds_finalize_payload() -> None:
    _app()
    dialog = ExperimentFinalizeDialog(
        {
            "experiment_id": "exp-001",
            "template_id": "debug_checkout",
            "title": "Checkout",
            "sample": "Board",
            "description": "Initial description",
            "notes": "Initial notes",
            "custom_fields": {"issue_ticket": "BUG-12"},
        }
    )

    assert dialog.windowTitle() == "Завершить эксперимент"

    dialog._notes_edit.setPlainText("Final note")
    dialog._status_combo.setCurrentIndex(1)
    dialog._custom_edits["issue_ticket"].setText("BUG-17")

    payload = dialog.payload()

    assert payload["cmd"] == "experiment_finalize"
    assert payload["experiment_id"] == "exp-001"
    assert payload["status"] == "ABORTED"
    assert payload["custom_fields"]["issue_ticket"] == "BUG-17"
    assert payload["notes"] == "Final note"
