"""Tests for experiment_advance_phase and phase_started_at in status (B.5)."""

from __future__ import annotations

from pathlib import Path

from cryodaq.core.experiment import ExperimentManager


def _make_manager(tmp_path: Path) -> ExperimentManager:
    """Create an ExperimentManager with a temporary data dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "custom.yaml").write_text(
        "id: custom\nname: Custom\nsections:\n  - setup\nreport_enabled: false\n"
        "report_sections: []\ncustom_fields: []\n",
        encoding="utf-8",
    )
    instruments_cfg = tmp_path / "instruments.yaml"
    instruments_cfg.write_text("instruments: {}\n", encoding="utf-8")
    return ExperimentManager(
        data_dir=data_dir,
        instruments_config=instruments_cfg,
        templates_dir=templates_dir,
    )


def test_advance_phase_updates_current_phase(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.create_experiment(name="Test", operator="op", template_id="custom")
    assert mgr.get_current_phase() is None
    entry = mgr.advance_phase("preparation", operator="op")
    assert entry["phase"] == "preparation"
    assert mgr.get_current_phase() == "preparation"


def test_advance_phase_invalid_raises(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.create_experiment(name="Test", operator="op", template_id="custom")
    try:
        mgr.advance_phase("invalid_phase")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown phase" in str(e)


def test_advance_phase_no_experiment_raises(tmp_path):
    mgr = _make_manager(tmp_path)
    try:
        mgr.advance_phase("preparation")
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_status_payload_includes_phase_started_at(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.create_experiment(name="Test", operator="op", template_id="custom")
    status = mgr.get_status_payload()
    assert "phase_started_at" in status
    assert status["phase_started_at"] is None  # no phase yet

    mgr.advance_phase("vacuum", operator="op")
    status = mgr.get_status_payload()
    assert status["current_phase"] == "vacuum"
    assert isinstance(status["phase_started_at"], float)
    assert status["phase_started_at"] > 0


def test_phase_history_tracks_transitions(tmp_path):
    mgr = _make_manager(tmp_path)
    mgr.create_experiment(name="Test", operator="op", template_id="custom")
    mgr.advance_phase("preparation")
    mgr.advance_phase("vacuum")
    history = mgr.get_phase_history()
    assert len(history) == 2
    assert history[0]["phase"] == "preparation"
    assert history[0]["ended_at"] is not None  # closed
    assert history[1]["phase"] == "vacuum"
    assert history[1]["ended_at"] is None  # still open
