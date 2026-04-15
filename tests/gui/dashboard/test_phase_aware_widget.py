"""Tests for PhaseAwareWidget (B.5)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

from cryodaq.core.phase_labels import PHASE_LABELS_RU, PHASE_ORDER
from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget
from cryodaq.gui.dashboard.phase_content.eta_display import (
    _format_duration_ru as _format_duration,
)


def test_phase_order_matches_enum():
    from cryodaq.core.experiment import ExperimentPhase

    enum_values = [p.value for p in ExperimentPhase]
    assert list(PHASE_ORDER) == enum_values


def test_phase_labels_complete():
    for phase in PHASE_ORDER:
        assert phase in PHASE_LABELS_RU
        assert PHASE_LABELS_RU[phase]


def test_widget_initial_state_inactive(app):
    w = PhaseAwareWidget()
    assert w._current_phase is None
    assert w._has_active_experiment is False


def test_widget_status_update_activates(app):
    w = PhaseAwareWidget()
    now = datetime.now(timezone.utc).timestamp()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": now,
    })
    assert w._current_phase == "cooldown"
    assert w._has_active_experiment is True


def test_widget_status_update_deactivates(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 1000.0,
    })
    assert w._has_active_experiment is True
    w.on_status_update({
        "current_phase": None,
        "phase_started_at": None,
    })
    assert w._has_active_experiment is False


def test_widget_phase_change(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "preparation",
        "phase_started_at": 1000.0,
    })
    assert w._current_phase == "preparation"
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "vacuum",
        "phase_started_at": 2000.0,
    })
    assert w._current_phase == "vacuum"


def test_back_button_emits_signal(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 1000.0,
    })
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    w._on_back_clicked()
    assert received == ["vacuum"]


def test_forward_button_emits_signal(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 1000.0,
    })
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    w._on_forward_clicked()
    assert received == ["measurement"]


def test_back_disabled_at_first_phase(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "preparation",
        "phase_started_at": 1000.0,
    })
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    w._on_back_clicked()
    assert received == []


def test_forward_disabled_at_last_phase(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "teardown",
        "phase_started_at": 1000.0,
    })
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    w._on_forward_clicked()
    assert received == []


def test_format_duration_seconds():
    assert _format_duration(45) == "45\u0441"


def test_format_duration_minutes():
    assert _format_duration(125) == "2\u043c\u0438\u043d"


def test_format_duration_hours_only():
    assert _format_duration(3600) == "1\u0447"


def test_format_duration_hours_minutes():
    assert _format_duration(3725) == "1\u0447 2\u043c\u0438\u043d"


def test_format_duration_zero():
    assert _format_duration(0) == "0\u0441"


def test_widget_handles_unknown_phase_gracefully(app):
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "nonsense_phase",
        "phase_started_at": 1000.0,
    })
    # Should not crash


def test_widget_handles_missing_keys(app):
    w = PhaseAwareWidget()
    w.on_status_update({})
    # Should not crash — treats as inactive


def test_widget_active_experiment_no_phase(app):
    """Active experiment with no phase yet shows 'awaiting phase'."""
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": None,
        "phase_started_at": None,
    })
    assert w._has_active_experiment is True
    assert w._current_phase is None


def test_widget_cleanup_on_close(app):
    w = PhaseAwareWidget()
    assert w._duration_timer.isActive()
    w.close()
    assert not w._duration_timer.isActive()


# --- B.5.5 QStackedWidget tests ---


def test_widget_switches_pages_on_phase_change(app):
    """Stack page index changes when phase changes."""
    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "preparation",
        "phase_started_at": 1000.0,
    })
    assert w._stack.currentIndex() == 1  # _PAGE_PREPARATION

    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 2000.0,
    })
    assert w._stack.currentIndex() == 3  # _PAGE_COOLDOWN

    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "teardown",
        "phase_started_at": 3000.0,
    })
    assert w._stack.currentIndex() == 6  # _PAGE_TEARDOWN


def test_widget_no_experiment_shows_page_0(app):
    w = PhaseAwareWidget()
    assert w._stack.currentIndex() == 0

    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 1000.0,
    })
    assert w._stack.currentIndex() == 3

    w.on_status_update({
        "current_phase": None,
        "phase_started_at": None,
    })
    assert w._stack.currentIndex() == 0


def test_widget_cooldown_eta_update(app):
    """Cooldown ETA widget receives analytics data."""
    from cryodaq.drivers.base import ChannelStatus, Reading
    from datetime import datetime, timezone

    w = PhaseAwareWidget()
    w.on_status_update({
        "active_experiment": {"name": "Test"},
        "current_phase": "cooldown",
        "phase_started_at": 1000.0,
    })
    reading = Reading(
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=12.5,  # hours
        unit="h",
        timestamp=datetime.now(timezone.utc),
        status=ChannelStatus.OK,
        instrument_id="cooldown_predictor",
        metadata={},
    )
    w.on_reading(reading)
    # ETA should show ~12h 30min
    assert w._cooldown_eta._value_label.text() != "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e"
