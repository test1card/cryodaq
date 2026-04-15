"""Tests for NewExperimentDialog (B.8)."""
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
    dialog._operator_edit.setText("V")
    dialog._on_create_clicked()
    assert not dialog._validation_label.isHidden()


def test_dialog_validates_empty_operator(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Test")
    dialog._operator_edit.setText("")
    dialog._on_create_clicked()
    assert not dialog._validation_label.isHidden()


def test_dialog_emits_payload_on_valid_submit(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("Test exp")
    dialog._operator_edit.setText("Vladimir")
    dialog._target_t_spin.setValue(4.2)

    received = []
    dialog.experiment_create_requested.connect(lambda p: received.append(p))
    dialog._on_create_clicked()

    assert len(received) == 1
    assert received[0]["name"] == "Test exp"
    assert received[0]["operator"] == "Vladimir"
    assert received[0]["target_T_cold"] == 4.2


def test_dialog_tags_parsed_from_csv(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._name_edit.setText("E")
    dialog._operator_edit.setText("V")
    dialog._tags_edit.setText("tag1, tag2 ,  tag3,,tag1")

    received = []
    dialog.experiment_create_requested.connect(lambda p: received.append(p))
    dialog._on_create_clicked()

    assert received[0]["tags"] == ["tag1", "tag2", "tag3"]


def test_dialog_target_t_clamped(app):
    dialog = NewExperimentDialog(available_templates=[])
    dialog._target_t_spin.setValue(-10)
    assert dialog._target_t_spin.value() >= 0.1
    dialog._target_t_spin.setValue(500)
    assert dialog._target_t_spin.value() <= 350


def test_dialog_template_dropdown(app):
    templates = [{"name": "T1", "id": "t1"}, {"name": "T2", "id": "t2"}]
    dialog = NewExperimentDialog(available_templates=templates)
    items = [dialog._template_combo.itemText(i)
             for i in range(dialog._template_combo.count())]
    assert any("\u0448\u0430\u0431\u043b\u043e\u043d" in items[0].lower() or "\u0431\u0435\u0437" in items[0].lower()
               for _ in [1])
    assert "T1" in items
    assert "T2" in items
