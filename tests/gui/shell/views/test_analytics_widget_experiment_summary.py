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
    """set_experiment_status must issue alarm_v2_history with start_ts.

    F19: now also issues readings_history (2 ZMQ workers total); test verifies
    the alarm_v2_history call specifically using call_args_list.
    """
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(start_time="2026-04-15T10:00:00+00:00"))

    # First call is alarm_v2_history, second is readings_history (F19 sub-item 1)
    assert mock_cls.call_count == 2
    alarm_cmd = mock_cls.call_args_list[0][0][0]
    assert alarm_cmd["cmd"] == "alarm_v2_history"
    assert "start_ts" in alarm_cmd
    assert alarm_cmd["start_ts"] == pytest.approx(
        datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC).timestamp(), abs=1
    )


def test_alarm_fetch_worker_has_parent(app):
    """ZmqCommandWorker must be constructed with parent=self for both workers."""
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status())

    # Both alarm and stats workers must have parent=self
    for call in mock_cls.call_args_list:
        _, kwargs = call
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


# ─── F19 sub-item 2: Top-3 alarm names ─────────────────────────────────────────


def test_top3_alarms_shows_most_frequent_names(app):
    """Top-3 most-triggered alarm names shown with counts in _top_alarms_label."""
    w = _make_widget()
    history = [
        _alarm_entry(alarm_id="t_high", level="WARNING"),
        _alarm_entry(alarm_id="t_high", level="WARNING"),
        _alarm_entry(alarm_id="t_high", level="WARNING"),
        _alarm_entry(alarm_id="pressure", level="CRITICAL"),
        _alarm_entry(alarm_id="pressure", level="CRITICAL"),
        _alarm_entry(alarm_id="drift", level="WARNING"),
        # CLEARED transitions should not be counted
        _alarm_entry(alarm_id="t_high", transition="CLEARED"),
    ]
    w._on_alarms_loaded({"ok": True, "history": history})
    text = w._top_alarms_label.text()
    # Most frequent (t_high ×3) must appear first
    assert "t_high" in text
    assert "pressure" in text
    # drift should appear (3rd most frequent ×1)
    assert "drift" in text


def test_top3_alarms_no_history_shows_net(app):
    """Empty alarm history must render 'нет' in top_alarms_label."""
    w = _make_widget()
    w._on_alarms_loaded({"ok": True, "history": []})
    assert "нет" in w._top_alarms_label.text()


def test_top3_alarms_error_shows_dash(app):
    """ok=False from engine must show '—' in top_alarms_label."""
    w = _make_widget()
    w._on_alarms_loaded({"ok": False, "error": "timeout"})
    assert w._top_alarms_label.text() == "—"


def test_top3_alarms_shows_at_most_three(app):
    """When more than 3 alarms exist, only top 3 are displayed."""
    w = _make_widget()
    history = [
        _alarm_entry(alarm_id=f"alarm_{i}")
        for i in range(10)
    ]
    w._on_alarms_loaded({"ok": True, "history": history})
    text = w._top_alarms_label.text()
    # Max 3 entries separated by ";"
    assert text.count(";") <= 2


# ─── F19 sub-item 3: Clickable artifact links ──────────────────────────────────


def test_artifact_links_are_clickable_labels(app):
    """_docx_label and _pdf_label must be _ClickableLabel instances with set_path."""
    from cryodaq.gui.shell.views.analytics_widgets import _ClickableLabel
    w = _make_widget()
    assert isinstance(w._docx_label, _ClickableLabel)
    assert isinstance(w._pdf_label, _ClickableLabel)


def test_artifact_link_set_path_updates_text_and_path(app):
    """set_path() must update displayed text and internal _path."""
    from cryodaq.gui.shell.views.analytics_widgets import _ClickableLabel
    w = _make_widget()
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status(artifact_dir="/data/exp_001"))
    assert isinstance(w._docx_label, _ClickableLabel)
    assert w._docx_label._path != ""
    assert "report_editable.docx" in w._docx_label._path


# ─── F19 sub-item 1: Channel min/max/mean stats ────────────────────────────────


def test_stats_loaded_renders_channel_stats(app):
    """_on_stats_loaded with valid data must populate _stats_label with channel stats."""
    w = _make_widget()
    data = {
        "Т1": [[1000.0, 10.0], [1001.0, 20.0], [1002.0, 30.0]],
        "Т2": [[1000.0, 5.0], [1001.0, 5.0]],
    }
    w._on_stats_loaded({"ok": True, "data": data})
    text = w._stats_label.text()
    assert "Т1" in text
    assert "Т2" in text
    # Min=10, max=30, mean=20 for T1
    assert "10" in text and "30" in text


def test_stats_loaded_empty_data_shows_no_data(app):
    """_on_stats_loaded with empty data must render 'нет данных'."""
    w = _make_widget()
    w._on_stats_loaded({"ok": True, "data": {}})
    assert "нет" in w._stats_label.text()


def test_stats_loaded_error_shows_dash(app):
    """ok=False from readings_history must render '—' in stats label."""
    w = _make_widget()
    w._on_stats_loaded({"ok": False})
    assert w._stats_label.text() == "—"


def test_stats_fetch_issued_on_status_set(app):
    """set_experiment_status must trigger two ZMQ workers: alarm_history + readings_history."""
    w = _make_widget()
    call_cmds: list[str] = []

    def capture(cmd, parent=None):
        call_cmds.append(cmd.get("cmd", ""))
        m = MagicMock()
        m.start = MagicMock()
        return m

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker", side_effect=capture):
        w.set_experiment_status(_make_status())

    assert "alarm_v2_history" in call_cmds
    assert "readings_history" in call_cmds


# ─── Empty-state coverage for new F19 labels ──────────────────────────────────


def test_empty_state_resets_f19_labels(app):
    """show_empty must reset top_alarms, stats, and artifact labels."""
    w = _make_widget()
    # First populate
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w.set_experiment_status(_make_status())
    # Then clear
    w.set_experiment_status(None)
    assert w._top_alarms_label.text() == "—"
    assert w._stats_label.text() == "—"
    assert w._docx_label.text() == "—"
    assert w._pdf_label.text() == "—"
