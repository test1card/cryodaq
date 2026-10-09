"""Tests for NewExperimentDialog (B.8.0.2 rebuild)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.new_experiment_dialog import NewExperimentDialog


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_dialog_validates_empty_name(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("")
    dialog._operator_combo.setEditText("V")
    dialog._on_create_clicked()
    assert not dialog._validation_label.isHidden()


def test_dialog_validates_empty_operator(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Test")
    dialog._operator_combo.setEditText("")
    dialog._on_create_clicked()
    assert not dialog._validation_label.isHidden()


def test_dialog_emits_payload_on_valid_submit(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Test exp")
    dialog._operator_combo.setEditText("Vladimir")
    dialog._sample_edit.setText("S-001")
    dialog._cryostat_combo.setEditText("Cryostat-1")
    dialog._description_edit.setPlainText("D")
    dialog._notes_edit.setPlainText("N")

    received = []
    dialog.experiment_create_requested.connect(lambda p: received.append(p))
    dialog._on_create_clicked()

    assert len(received) == 1
    p = received[0]
    assert p["title"] == "Test exp"
    assert p["operator"] == "Vladimir"
    assert p["sample"] == "S-001"
    assert p["cryostat"] == "Cryostat-1"
    assert p["description"] == "D"
    assert p["notes"] == "N"
    assert "custom_fields" in p
    assert "template_id" in p


def test_dialog_template_dropdown_populated(app):
    templates = [
        {"id": "cool", "name": "Cooldown V2", "custom_fields": []},
        {"id": "warm", "name": "Warmup V1", "custom_fields": []},
    ]
    dialog = NewExperimentDialog(available_templates=templates)
    items = [dialog._template_combo.itemText(i) for i in range(dialog._template_combo.count())]
    assert "Cooldown V2" in items
    assert "Warmup V1" in items


def test_dialog_template_change_rebuilds_custom_fields(app):
    templates = [
        {"id": "plain", "name": "Plain", "custom_fields": []},
        {
            "id": "with",
            "name": "WithCustom",
            "custom_fields": [{"id": "goal", "label": "Цель", "default": "test"}],
        },
    ]
    dialog = NewExperimentDialog(available_templates=templates)
    # Select "WithCustom" (index 2: first is "без шаблона", then "Plain", then "WithCustom")
    dialog._template_combo.setCurrentIndex(2)
    assert len(dialog._custom_edits) == 1
    assert "goal" in dialog._custom_edits


def test_report_enabled_checkbox_defaults_to_template_value(app):
    """IV.4 F6: checkbox default reflects the currently-selected template."""
    templates = [
        {"id": "reporting", "name": "Reporting", "report_enabled": True, "custom_fields": []},
        {"id": "silent", "name": "Silent", "report_enabled": False, "custom_fields": []},
    ]
    dialog = NewExperimentDialog(available_templates=templates)
    # Index 0 = "без шаблона"; report_enabled unspecified → True default.
    dialog._template_combo.setCurrentIndex(0)
    assert dialog._report_enabled_check.isChecked() is True
    # Index 1 = "Reporting" (report_enabled: True).
    dialog._template_combo.setCurrentIndex(1)
    assert dialog._report_enabled_check.isChecked() is True
    # Index 2 = "Silent" (report_enabled: False).
    dialog._template_combo.setCurrentIndex(2)
    assert dialog._report_enabled_check.isChecked() is False


def test_payload_includes_report_enabled_true(app):
    """IV.4 F6: payload always carries report_enabled so engine can
    distinguish an explicit operator choice from a no-op."""
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Run")
    dialog._operator_combo.setEditText("Vladimir")
    dialog._report_enabled_check.setChecked(True)

    received = []
    dialog.experiment_create_requested.connect(received.append)
    dialog._on_create_clicked()
    assert received
    assert received[0]["report_enabled"] is True


def test_payload_includes_report_enabled_false(app):
    """Operator untick → payload carries False, engine skips auto-report."""
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Run")
    dialog._operator_combo.setEditText("Vladimir")
    dialog._report_enabled_check.setChecked(False)

    received = []
    dialog.experiment_create_requested.connect(received.append)
    dialog._on_create_clicked()
    assert received
    assert received[0]["report_enabled"] is False
