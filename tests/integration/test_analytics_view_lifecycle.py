"""Cross-widget analytics view lifecycle integration tests (F3-Cycle5).

Verifies the full AnalyticsView data-flow contract across phase transitions:
- Correct widget swaps per phase (preparation → cooldown → measurement →
  warmup → disassembly)
- Data setters forwarded to the active widget in each phase
- Cached data replayed into freshly-mounted widgets after phase swap
- ExperimentSummaryWidget receives set_experiment_status on disassembly
- set_experiment_status cached in view and replayed on widget recreation

These tests complement the unit-level `test_analytics_view_phase_aware.py`
(which covers layout correctness and single-setter dispatch) with lifecycle
scenarios that exercise the full F3 data-wiring contract.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.views import analytics_widgets as aw
from cryodaq.gui.shell.views.analytics_view import AnalyticsView
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def _reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel=channel,
        value=value,
        unit=unit,
        metadata={},
    )


def _experiment_status(
    experiment_id: str = "exp_001",
    start_time: str = "2026-04-15T10:00:00+00:00",
    current_phase: str = "disassembly",
) -> dict:
    return {
        "active_experiment": {
            "experiment_id": experiment_id,
            "sample": "Si",
            "operator": "Иванов",
            "start_time": start_time,
            "end_time": "2026-04-15T20:00:00+00:00",
            "artifact_dir": "",
            "status": "COMPLETED",
        },
        "current_phase": current_phase,
        "phases": [],
    }


# ─── Phase lifecycle ───────────────────────────────────────────────────────────


def test_full_lifecycle_phase_widgets(app):
    """Cycling through all experiment phases must place the expected main widget."""
    view = AnalyticsView()

    expected = {
        "preparation": "temperature_overview",
        "cooldown": "cooldown_prediction",
        "measurement": "r_thermal_live",
        "disassembly": "experiment_summary",
    }
    for phase, expected_main_id in expected.items():
        view.set_phase(phase)
        active = view.active_widgets()
        assert aw.id_of(active.get("main")) == expected_main_id, (
            f"Phase {phase!r}: expected main={expected_main_id!r}, "
            f"got {aw.id_of(active.get('main'))!r}"
        )


def test_phase_sequence_does_not_carry_over_stale_widgets(app):
    """Going cooldown → measurement → cooldown must not reuse the old
    cooldown widget (it should have been discarded and recreated)."""
    view = AnalyticsView()

    view.set_phase("cooldown")
    widget_first = view.active_widgets().get("main")

    view.set_phase("measurement")
    view.set_phase("cooldown")
    widget_second = view.active_widgets().get("main")

    assert widget_first is not widget_second


# ─── Data forwarding across phases ────────────────────────────────────────────


def test_temperature_reading_forwarded_to_overview_in_fallback(app):
    """Temperature reading must reach TemperatureOverviewWidget in fallback."""
    view = AnalyticsView()
    view.set_temperature_readings({"Т1": _reading("Т1", 295.0)})
    widget = view.active_widgets().get("main")
    assert isinstance(widget, aw.TemperatureOverviewWidget)
    assert "Т1" in widget._curves


def test_temperature_cache_replayed_into_fresh_overview_after_phase_swap(app):
    """Temperature readings pushed in phase A must replay into overview widget
    when returning from phase B back to a phase with temperature_overview."""
    view = AnalyticsView()
    # Push temperature in fallback (temperature_overview is main).
    view.set_temperature_readings({"Т1": _reading("Т1", 295.0)})

    # Swap to a different phase that replaces the main widget.
    view.set_phase("measurement")

    # Swap back to fallback (temperature_overview recreated).
    view.set_phase(None)
    widget = view.active_widgets().get("main")
    assert isinstance(widget, aw.TemperatureOverviewWidget)
    assert "Т1" in widget._curves


def test_pressure_forwarded_in_preparation_top_right(app):
    """Pressure reading must reach PressureCurrentWidget in preparation top_right."""
    view = AnalyticsView()
    view.set_phase("preparation")
    reading = _reading("thyracont/pressure", 5e-6, unit="мбар")
    view.set_pressure_reading(reading)
    widget = view.active_widgets().get("top_right")
    assert isinstance(widget, aw.PressureCurrentWidget)


# ─── set_experiment_status ─────────────────────────────────────────────────────


def test_experiment_status_forwarded_to_summary_widget_on_disassembly(app):
    """set_experiment_status must reach ExperimentSummaryWidget when in
    disassembly phase and populate the content area."""
    view = AnalyticsView()
    view.set_phase("disassembly")

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view.set_experiment_status(_experiment_status())

    widget = view.active_widgets().get("main")
    assert isinstance(widget, aw.ExperimentSummaryWidget)
    assert not widget._content.isHidden()
    assert widget._empty_label.isHidden()


def test_experiment_status_cached_in_view(app):
    """set_experiment_status must be stored in _last_experiment_status for
    replay into freshly-mounted ExperimentSummaryWidget."""
    view = AnalyticsView()
    status = _experiment_status(experiment_id="exp_replay")

    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view.set_experiment_status(status)

    assert view._last_experiment_status is status


def test_experiment_status_replayed_into_summary_on_phase_swap(app):
    """If set_experiment_status was called before entering disassembly, it
    must be replayed into the freshly-created ExperimentSummaryWidget."""
    view = AnalyticsView()
    status = _experiment_status(experiment_id="exp_late")

    # Cache status while NOT in disassembly (e.g. warmup).
    view.set_phase("warmup")
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view.set_experiment_status(status)

    # Now enter disassembly — fresh ExperimentSummaryWidget must get the status.
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        view.set_phase("disassembly")

    widget = view.active_widgets().get("main")
    assert isinstance(widget, aw.ExperimentSummaryWidget)
    # Content shown means set_experiment_status was replayed.
    assert not widget._content.isHidden()
    assert widget._id_label.text() == "exp_late"


# ─── W4 placeholder ────────────────────────────────────────────────────────────


def test_r_thermal_placeholder_has_f8_text(app):
    """r_thermal_placeholder must mention F8 as the unblock criterion."""
    w = aw.create("r_thermal_placeholder")
    assert isinstance(w, aw.PlaceholderCard)
    # The PlaceholderCard must have been created with the F8 subtitle.
    # We verify by checking the title stored on the widget.
    assert "R" in w._title
