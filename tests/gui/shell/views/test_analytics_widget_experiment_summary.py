"""ExperimentSummaryWidget — unit tests (F3-Cycle4, spec §4.3).

Acceptance criteria:
1. Widget shows empty state on construction and when status is None/incomplete.
2. Header fields (ID, sample, operator, date) populated from status dict.
3. Duration computed correctly for completed experiments.
4. Phase breakdown rendered from phases list.
5. alarm_v2_history ZMQ fetch issued with experiment start_ts.
6. Alarm count rendered correctly (0, N, error → "—").
7. Artifact paths derived from artifact_dir.
8. ZmqCommandWorker constructed with parent=self (lifecycle safety).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.views.analytics_widgets import ExperimentSummaryWidget
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def _make_widget() -> ExperimentSummaryWidget:
    return ExperimentSummaryWidget()


def _make_status(
    experiment_id: str = "exp_001",
    sample: str = "Si wafer",
    operator: str = "Иванов",
    start_time: str = "2026-04-15T10:00:00+00:00",
    end_time: str | None = "2026-04-15T18:00:00+00:00",
    artifact_dir: str = "/data/experiments/exp_001",
    phases: list | None = None,
) -> dict:
    return {
        "active_experiment": {
            "experiment_id": experiment_id,
            "sample": sample,
            "operator": operator,
            "start_time": start_time,
            "end_time": end_time,
            "artifact_dir": artifact_dir,
            "status": "COMPLETED" if end_time else "RUNNING",
        },
        "current_phase": "disassembly",
        "phases": phases or [],
    }


def _alarm_entry(
    alarm_id: str = "alarm_1",
    level: str = "WARNING",
    transition: str = "TRIGGERED",
    at: float = 1744700000.0,
) -> dict:
    return {
        "alarm_id": alarm_id,
        "transition": transition,
        "at": at,
        "level": level,
        "message": f"Test alarm {alarm_id}",
    }


# ─── Construction ─────────────────────────────────────────────────────────────


def test_construction_shows_empty_state(app):
    """Fresh widget must show empty-state label and hide content."""
    w = _make_widget()
    assert not w._empty_label.isHidden()
    assert w._content.isHidden()


def test_construction_no_zmq_call(app):
    """Widget must NOT issue a ZMQ call on construction (data-driven trigger)."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        _make_widget()
    mock_cls.assert_not_called()


# ─── Empty state ───────────────────────────────────────────────────────────────


def test_set_experiment_status_none_shows_empty(app):
    w = _make_widget()
    w.set_experiment_status(_make_status())  # populate first
    w.set_experiment_status(None)
    assert not w._empty_label.isHidden()
    assert w._content.isHidden()


def test_set_experiment_status_no_active_experiment_shows_empty(app):
    w = _make_widget()
    w.set_experiment_status({"current_phase": "cooldown"})
    assert not w._empty_label.isHidden()
    assert w._content.isHidden()


# ─── Header fields ─────────────────────────────────────────────────────────────


def test_header_fields_populated(app):
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(
            _make_status(
                experiment_id="exp_007",
                sample="Pb sample",
                operator="Петров",
            )
        )
    assert w._id_label.text() == "exp_007"
    assert "Pb sample" in w._sample_label.text()
    assert "Петров" in w._operator_label.text()


def test_header_date_formatted(app):
    """Start date must appear in the date label."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(start_time="2026-04-15T10:00:00+00:00"))
    assert "2026-04-15" in w._date_label.text()


# ─── Duration ──────────────────────────────────────────────────────────────────


def test_duration_computed_for_completed_experiment(app):
    """8-hour experiment must show '8.0 ч'."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(
            _make_status(
                start_time="2026-04-15T10:00:00+00:00",
                end_time="2026-04-15T18:00:00+00:00",
            )
        )
    assert "8.0" in w._duration_label.text()


def test_duration_in_progress_when_no_end_time(app):
    """Missing end_time must render 'в процессе'."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(end_time=None))
    assert "в процессе" in w._duration_label.text()


# ─── Phase breakdown ───────────────────────────────────────────────────────────


def test_phases_rendered_in_label(app):
    """Phase list with valid start/end times must appear in phases label."""
    w = _make_widget()
    phases = [
        {
            "phase": "cooldown",
            "started_at": "2026-04-15T10:00:00+00:00",
            "ended_at": "2026-04-15T16:00:00+00:00",
        }
    ]
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(phases=phases))
    assert "cooldown" in w._phases_label.text()
    assert "6.0" in w._phases_label.text()


def test_empty_phases_renders_dash(app):
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(phases=[]))
    assert w._phases_label.text() == "—"


# ─── Alarm fetch ───────────────────────────────────────────────────────────────


def test_alarm_fetch_triggered_with_start_ts(app):
    """set_experiment_status must issue alarm_v2_history with start_ts."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(start_time="2026-04-15T10:00:00+00:00"))

    mock_cls.assert_called_once()
    cmd = mock_cls.call_args[0][0]
    assert cmd["cmd"] == "alarm_v2_history"
    assert "start_ts" in cmd
    assert cmd["start_ts"] == pytest.approx(
        datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC).timestamp(), abs=1
    )


def test_alarm_fetch_worker_has_parent(app):
    """ZmqCommandWorker must be constructed with parent=self."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status())

    _, kwargs = mock_cls.call_args
    assert kwargs.get("parent") is w


# ─── Alarm count rendering ─────────────────────────────────────────────────────


def test_alarm_count_zero_alarms(app):
    """Empty history must render '0 (0 пред. / 0 крит.)'."""
    w = _make_widget()
    w._on_alarms_loaded({"ok": True, "history": []})
    assert "0" in w._alarm_label.text()


def test_alarm_count_with_warnings_and_criticals(app):
    """2 warnings + 1 critical must show '3 (2 пред. / 1 крит.)'."""
    w = _make_widget()
    history = [
        _alarm_entry(alarm_id="a1", level="WARNING"),
        _alarm_entry(alarm_id="a2", level="WARNING"),
        _alarm_entry(alarm_id="a3", level="CRITICAL"),
        _alarm_entry(alarm_id="a1", transition="CLEARED"),
    ]
    w._on_alarms_loaded({"ok": True, "history": history})
    text = w._alarm_label.text()
    assert "3" in text
    assert "2" in text
    assert "1" in text


def test_alarm_count_error_shows_dash(app):
    """ok=False from engine must render '—'."""
    w = _make_widget()
    w._on_alarms_loaded({"ok": False, "error": "timeout"})
    assert w._alarm_label.text() == "—"


# ─── Artifacts ─────────────────────────────────────────────────────────────────


def test_artifact_paths_derived_from_artifact_dir(app):
    """artifact_dir must produce DOCX and PDF paths in labels."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(artifact_dir="/data/exp_001"))
    assert "report_editable.docx" in w._docx_label.text()
    assert "report_raw.pdf" in w._pdf_label.text()


def test_no_artifact_dir_shows_dash(app):
    """Missing artifact_dir must render '—' for artifact labels."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(artifact_dir=""))
    assert w._docx_label.text() == "—"
    assert w._pdf_label.text() == "—"


# ─── Content visibility ────────────────────────────────────────────────────────


def test_content_shown_after_status_received(app):
    """After valid status, content widget must be visible and empty label hidden."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status())
    assert w._empty_label.isHidden()
    assert not w._content.isHidden()
