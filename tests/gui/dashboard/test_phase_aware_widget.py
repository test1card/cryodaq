"""Tests for PhaseAwareWidget (B.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime

from cryodaq.core.phase_labels import PHASE_LABELS_RU, PHASE_ORDER
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget
from cryodaq.gui.dashboard.phase_content.eta_display import _format_duration_ru


def _format_duration(s):
    return _format_duration_ru(s)


def test_phase_order_matches_enum():
    from cryodaq.core.experiment import ExperimentPhase

    enum_values = [p.value for p in ExperimentPhase]
    assert list(PHASE_ORDER) == enum_values


# LOW: assert exact expected labels, not just non-empty
def test_phase_labels_complete():
    # Read the actual canonical values from PHASE_LABELS_RU (source of truth),
    # then assert each is non-empty and matches the canonical spelling.
    expected = {
        "preparation": "Подготовка",
        "vacuum": "Откачка",
        "cooldown": "Захолаживание",
        "measurement": "Измерение",
        "warmup": "Растепление",
        "teardown": "Разборка",
    }
    for phase in PHASE_ORDER:
        assert phase in PHASE_LABELS_RU
        assert PHASE_LABELS_RU[phase], f"Empty label for phase {phase!r}"
        if phase in expected:
            assert PHASE_LABELS_RU[phase] == expected[phase], (
                f"Label for {phase!r}: got {PHASE_LABELS_RU[phase]!r}, expected {expected[phase]!r}"
            )


# MED: assert rendered UI, not just private flags.
# Note: isVisible() requires parent to be shown. Use isHidden() which reflects
# explicit setVisible() calls regardless of parent shown state.
def test_widget_initial_state_inactive(app):
    w = PhaseAwareWidget()
    assert w._stepper.isHidden(), "stepper should be hidden in inactive state"
    assert w._controls.isHidden(), "controls should be hidden in inactive state"
    assert not w._create_btn.isHidden(), "create btn should be visible in inactive state"
    label_text = w._context_label.text()
    assert "Нет" in label_text or "активного" in label_text or "эксперимент" in label_text.lower()


# MED: assert rendered UI after activation
def test_widget_status_update_activates(app):
    w = PhaseAwareWidget()
    now = datetime.now(UTC).timestamp()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": now,
        }
    )
    assert not w._stepper.isHidden(), "stepper should be visible when active"
    assert not w._controls.isHidden(), "controls should be visible when active"
    assert w._create_btn.isHidden(), "create btn should be hidden when active"
    active_ss = w._stepper._pills["cooldown"].styleSheet()
    assert theme.ACCENT in active_ss


# MED: assert rendered UI after deactivation
def test_widget_status_update_deactivates(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    assert not w._stepper.isHidden()
    w.on_status_update(
        {
            "current_phase": None,
            "phase_started_at": None,
        }
    )
    assert w._stepper.isHidden(), "stepper should hide after deactivation"
    assert w._controls.isHidden(), "controls should hide after deactivation"
    assert not w._create_btn.isHidden(), "create btn should reappear after deactivation"


# MED: assert rendered label text changes on phase change
def test_widget_phase_change(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "preparation",
            "phase_started_at": 1000.0,
        }
    )
    label_text = w._context_label.text()
    assert "ПОДГОТОВКА" in label_text.upper() or "ПОДГОТОВК" in label_text.upper()

    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "vacuum",
            "phase_started_at": 2000.0,
        }
    )
    label_text = w._context_label.text()
    # PHASE_LABELS_RU["vacuum"] = "Откачка"
    assert "ОТКАЧКА" in label_text.upper()
    prep_ss = w._stepper._pills["preparation"].styleSheet()
    vac_ss = w._stepper._pills["vacuum"].styleSheet()
    assert theme.STATUS_OK not in prep_ss
    assert theme.BORDER in prep_ss
    assert theme.ACCENT in vac_ss
    assert theme.ACCENT in vac_ss


# HIGH: click real button via QPushButton.click(), assert emitted signal
def test_back_button_emits_signal(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    assert w._back_btn.isEnabled(), "back btn must be enabled for cooldown (not first phase)"
    w._back_btn.click()
    assert received == ["vacuum"]


# HIGH: click real forward button via QPushButton.click(), assert emitted signal
def test_forward_button_emits_signal(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    received = []
    w.phase_transition_requested.connect(lambda p: received.append(p))
    assert w._forward_btn.isEnabled(), "forward btn must be enabled for cooldown (not last phase)"
    w._forward_btn.click()
    assert received == ["measurement"]


# HIGH: assert button is disabled, not just that handler no-ops
def test_back_disabled_at_first_phase(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "preparation",
            "phase_started_at": 1000.0,
        }
    )
    assert w._back_btn.isEnabled() is False, "back btn must be disabled at first phase (preparation)"


# HIGH: assert button is disabled at last phase (teardown per PHASE_ORDER)
def test_forward_disabled_at_last_phase(app):
    w = PhaseAwareWidget()
    last_phase = PHASE_ORDER[-1]  # "teardown"
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": last_phase,
            "phase_started_at": 1000.0,
        }
    )
    assert w._forward_btn.isEnabled() is False, f"forward btn must be disabled at last phase ({last_phase!r})"


def test_format_duration_seconds():
    assert _format_duration(45) == "45с"


def test_format_duration_minutes():
    assert _format_duration(125) == "2мин"


def test_format_duration_hours_only():
    assert _format_duration(3600) == "1ч"


def test_format_duration_hours_minutes():
    assert _format_duration(3725) == "1ч 2мин"


def test_format_duration_zero():
    assert _format_duration(0) == "0с"


# LOW: assert defined fallback UI state for unknown phase
def test_widget_handles_unknown_phase_gracefully(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "nonsense_phase",
            "phase_started_at": 1000.0,
        }
    )
    # Should not crash; widget stays in active state with controls visible
    assert not w._controls.isHidden(), "controls must remain visible for unknown phase"
    assert not w._stepper.isHidden(), "stepper must remain visible for unknown phase"


# MED: assert inactive state + text (was: no assertion)
def test_widget_handles_missing_keys(app):
    w = PhaseAwareWidget()
    w.on_status_update({})
    # Missing active_experiment → treated as inactive
    assert w._stepper.isHidden(), "stepper should be hidden for missing-keys status"
    assert not w._create_btn.isHidden(), "create btn should show for missing-keys (inactive) status"
    label_text = w._context_label.text()
    assert "Нет" in label_text or "активного" in label_text or "эксперимент" in label_text.lower()


# MED: assert rendered UI for active-no-phase
def test_widget_active_experiment_no_phase(app):
    """Active experiment with no phase yet shows 'awaiting phase'."""
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": None,
            "phase_started_at": None,
        }
    )
    assert not w._stepper.isHidden(), "stepper should be visible for active-no-phase"
    assert not w._controls.isHidden(), "controls should be visible for active-no-phase"
    assert w._create_btn.isHidden(), "create btn must be hidden when experiment is active"
    label_text = w._context_label.text()
    assert "Ожидани" in label_text or "фаз" in label_text.lower()


def test_widget_cleanup_on_close(app):
    w = PhaseAwareWidget()
    assert w._duration_timer.isActive()
    w.close()
    assert not w._duration_timer.isActive()


# --- B.5.6 Compact widget tests ---


def test_widget_height_capped(app):
    w = PhaseAwareWidget()
    assert w.maximumHeight() <= 60


def test_context_label_shows_phase_name_uppercase(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    text = w._context_label.text()
    assert "ЗАХОЛАЖИВАНИЕ" in text


# HIGH: assert exact formatted duration "12ч 30мин"
# on_reading multiplies value (hours) by 3600 → stores seconds.
# 12.5 h → 45000 s → "12ч 30мин"
def test_context_label_shows_eta_when_cooldown_eta_received(app):
    from cryodaq.drivers.base import ChannelStatus, Reading

    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    # on_reading: channel ending with /cooldown_eta, value in hours → * 3600
    reading = Reading(
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=12.5,  # hours; code does value * 3600 → 45000 s → "12ч 30мин"
        unit="h",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="cooldown_predictor",
        metadata={},
    )
    w.on_reading(reading)
    label_text = w._context_label.text()
    assert "ETA" in label_text
    assert "12ч 30мин" in label_text, f"Expected '12ч 30мин' in label text, got: {label_text!r}"


def test_context_label_omits_eta_when_not_received(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    assert "ETA" not in w._context_label.text()


# MED: assert cached values reset on experiment end + rendered state reset
def test_cached_values_reset_on_experiment_end(app):
    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"name": "Test"},
            "current_phase": "cooldown",
            "phase_started_at": 1000.0,
        }
    )
    w._cached_r_thermal = 3.14
    w.on_status_update(
        {
            "current_phase": None,
            "phase_started_at": None,
        }
    )
    assert w._cached_r_thermal is None
    assert w._cached_eta_s is None
    assert w._stepper.isHidden()
    assert not w._create_btn.isHidden()
