"""Tests for ExperimentOverlay (B.8.0.2 rebuild)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui.shell.experiment_overlay import ExperimentOverlay


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_overlay_renders_experiment_data(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "Cooldown #5", "operator": "V",
         "start_time": "2026-04-15T10:00:00+00:00", "app_mode": "experiment",
         "experiment_id": "exp001", "template_id": "custom"},
        phase_history=[],
    )
    labels = overlay.findChildren(QLabel)
    texts = " ".join(lbl.text() for lbl in labels)
    assert "Cooldown #5" in texts


def test_overlay_phase_pills_show_duration(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "E", "operator": "V", "start_time": "2026-04-15T10:00:00+00:00",
         "current_phase": "cooldown", "experiment_id": "e1", "template_id": "custom"},
        phase_history=[
            {"phase": "preparation", "started_at": "2026-04-15T10:00:00+00:00",
             "ended_at": "2026-04-15T10:18:00+00:00"},
            {"phase": "vacuum", "started_at": "2026-04-15T10:18:00+00:00",
             "ended_at": "2026-04-15T12:30:00+00:00"},
            {"phase": "cooldown", "started_at": "2026-04-15T12:30:00+00:00",
             "ended_at": None},
        ],
    )
    labels = overlay.findChildren(QLabel)
    texts = " ".join(lbl.text() for lbl in labels)
    assert "18" in texts  # preparation 18m
    assert "2\u0447" in texts  # vacuum ~2h


def test_overlay_editable_name_validates(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "Original", "operator": "V", "start_time": "2026-04-15T10:00:00+00:00",
         "experiment_id": "e1", "template_id": "custom"},
        phase_history=[],
    )
    overlay._enter_name_edit()
    overlay._name_edit.setText("   ")
    overlay._commit_name_edit()
    assert overlay._displayed_name() == "Original"


def test_overlay_esc_emits_closed(app):
    overlay = ExperimentOverlay()
    received = []
    overlay.closed.connect(lambda: received.append(True))

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(event)
    assert received == [True]


def test_overlay_no_experiment_disables_finalize(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(None)
    assert not overlay._finalize_btn.isEnabled()


def test_overlay_card_save_payload(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "E", "operator": "V", "start_time": "2026-04-15T10:00:00+00:00",
         "experiment_id": "e1", "template_id": "custom",
         "sample": "S", "description": "D", "notes": "N"},
        phase_history=[],
    )
    overlay._sample_edit.setText("NewSample")
    payload = overlay._build_card_payload()
    assert payload["sample"] == "NewSample"
    assert payload["experiment_id"] == "e1"
    assert "custom_fields" in payload


def test_overlay_abort_in_more_menu(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "E", "operator": "V", "start_time": "2026-04-15T10:00:00+00:00",
         "experiment_id": "e1", "template_id": "custom"},
        [],
    )
    # Abort is NOT a direct visible button in footer — it's in ⋯ menu
    from PySide6.QtWidgets import QPushButton
    buttons = overlay.findChildren(QPushButton)
    visible_abort = [b for b in buttons
                     if "\u041f\u0440\u0435\u0440\u0432\u0430\u0442\u044c" in b.text()
                     and not b.isHidden()]
    assert len(visible_abort) == 0  # only in menu
