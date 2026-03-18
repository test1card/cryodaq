"""Tests for ExperimentStatusWidget — correct parsing of experiment_status payload."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.overview_panel import ExperimentStatusWidget


@pytest.fixture(scope="module")
def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def widget(_app):
    """Create ExperimentStatusWidget with timers stopped."""
    w = ExperimentStatusWidget()
    w._timer.stop()
    return w


def test_active_experiment_shows_name(widget) -> None:
    """When active_experiment is present, widget must show experiment name."""
    payload = {
        "ok": True,
        "active_experiment": {
            "name": "Cooldown #42",
            "template_id": "standard",
            "start_time": "2026-03-18T10:00:00+00:00",
            "status": "IN_PROGRESS",
        },
        "current_phase": "cooldown",
    }
    widget._on_refresh_result(payload)
    text = widget._status_label.text()
    assert "Cooldown #42" in text
    assert "Захолаживание" in text
    assert widget._status_label.styleSheet() == "color: #2ECC40; border: none;"


def test_no_experiment_shows_inactive(widget) -> None:
    """When active_experiment is None, widget must show inactive state."""
    payload = {
        "ok": True,
        "active_experiment": None,
        "current_phase": None,
    }
    widget._on_refresh_result(payload)
    assert "Нет активного эксперимента" in widget._status_label.text()


def test_error_response_shows_inactive(widget) -> None:
    """When ok=False, widget must show inactive state."""
    widget._on_refresh_result({"ok": False, "error": "timeout"})
    assert "Нет активного эксперимента" in widget._status_label.text()


def test_elapsed_time_computed_from_start_time(widget) -> None:
    """Elapsed time must be computed from active_experiment.start_time, not top-level."""
    from datetime import datetime, timezone, timedelta

    start = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=15)).isoformat()
    payload = {
        "ok": True,
        "active_experiment": {
            "name": "Test",
            "template_id": "custom",
            "start_time": start,
            "status": "IN_PROGRESS",
        },
        "current_phase": None,
    }
    widget._on_refresh_result(payload)
    elapsed_text = widget._elapsed_label.text()
    # Should show approximately 02:15:XX
    assert elapsed_text.startswith("02:1"), f"Expected ~02:15:xx, got {elapsed_text}"


def test_template_id_shown_in_brackets(widget) -> None:
    """template_id must be shown in brackets after name."""
    payload = {
        "ok": True,
        "active_experiment": {
            "name": "Run 1",
            "template_id": "thermal_conductivity",
            "start_time": "2026-03-18T10:00:00+00:00",
        },
        "current_phase": None,
    }
    widget._on_refresh_result(payload)
    text = widget._status_label.text()
    assert "[thermal_conductivity]" in text
