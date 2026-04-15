"""Tests for ExperimentOverlay (B.8)."""
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
         "start_time": "2026-04-15T10:00:00+00:00", "app_mode": "experiment"},
        phase_history=[],
    )
    labels = overlay.findChildren(QLabel)
    texts = " ".join(lbl.text() for lbl in labels)
    assert "Cooldown #5" in texts


def test_overlay_milestones_rendered(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "E", "operator": "V",
         "start_time": "2026-04-15T10:00:00+00:00", "app_mode": "experiment"},
        phase_history=[
            {"phase": "preparation", "started_at": "2026-04-15T10:00:00+00:00",
             "ended_at": "2026-04-15T10:30:00+00:00"},
        ],
    )
    assert len(overlay._milestone_list._row_labels) == 1


def test_overlay_editable_name_validates(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {"name": "Original", "operator": "V",
         "start_time": "2026-04-15T10:00:00+00:00", "app_mode": "experiment"},
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
