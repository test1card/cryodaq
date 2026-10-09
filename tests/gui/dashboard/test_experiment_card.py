"""Tests for ExperimentCard dashboard tile (B.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.gui import theme
from cryodaq.gui.dashboard.experiment_card import (
    ExperimentCard,
    ExperimentCardData,
)


def _make_data(
    *,
    name: str = "calibration_run_042",
    mode: str = "experiment",
    started_minutes_ago: int = 47,
    current_phase: str = "cooldown",
    target_channel_id: str = "Т11",
    target_value: float = 4.21,
    pressure_mbar: float | None = 1.23e-6,
    faulted: bool = False,
) -> ExperimentCardData:
    return ExperimentCardData(
        name=name,
        mode=mode,
        started_at=datetime.now(UTC) - timedelta(minutes=started_minutes_ago),
        current_phase=current_phase,
        target_channel_id=target_channel_id,
        target_channel_value=target_value,
        target_channel_unit="K",
        pressure_mbar=pressure_mbar,
        faulted=faulted,
    )


def test_experiment_card_no_active_experiment_shows_placeholder(app):
    # Note: in offscreen Qt, child.isVisible() reports False unless the
    # top-level window is shown. We check isHidden() (the widget's own
    # hide flag) instead — it reflects the show/hide toggle we did
    # without depending on an active window.
    card = ExperimentCard()
    card.set_experiment(None)
    assert not card._empty_label.isHidden()
    assert not card._create_btn.isHidden()
    assert card._name_label.isHidden()
    assert card._phase_stepper.isHidden()
    assert "Нет активного эксперимента" in card._empty_label.text()


def test_experiment_card_active_shows_mode_badge_surface_elevated(app):
    # Phase III.A: Эксперимент mode badge is low-emphasis chip
    # (SURFACE_ELEVATED + FOREGROUND + BORDER_SUBTLE), not STATUS_OK
    # safety-green which collided with status-display semantics.
    card = ExperimentCard()
    card.set_experiment(_make_data(mode="experiment"))
    assert not card._mode_badge.isHidden()
    assert card._mode_badge.text() == "Эксперимент"
    ss = card._mode_badge.styleSheet()
    assert theme.SURFACE_ELEVATED in ss
    assert theme.FOREGROUND in ss
    assert theme.BORDER_SUBTLE in ss
    assert theme.STATUS_OK not in ss


def test_experiment_card_debug_shows_status_caution(app):
    # Phase III.A: Отладка keeps STATUS_CAUTION colour (operator-
    # attention signal) but renders as bordered chip on SURFACE_ELEVATED.
    card = ExperimentCard()
    card.set_experiment(_make_data(mode="debug"))
    assert card._mode_badge.text() == "Отладка"
    ss = card._mode_badge.styleSheet()
    assert theme.STATUS_CAUTION in ss
    assert theme.SURFACE_ELEVATED in ss
    assert theme.STATUS_OK not in ss  # no mix


def test_experiment_card_fault_variant_has_status_fault_border(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(faulted=True))
    card_ss = card.styleSheet()
    assert f"3px solid {theme.STATUS_FAULT}" in card_ss
    assert "border-left:" in card_ss


def test_experiment_card_no_fault_has_no_status_fault_border(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(faulted=False))
    assert theme.STATUS_FAULT not in card.styleSheet()


def test_experiment_card_open_button_emits_signal(app):
    card = ExperimentCard()
    card.set_experiment(_make_data())
    seen: list[bool] = []
    card.open_requested.connect(lambda: seen.append(True))
    card._open_btn.click()
    assert seen == [True]


def test_experiment_card_finalize_button_emits_signal(app):
    card = ExperimentCard()
    card.set_experiment(_make_data())
    seen: list[bool] = []
    card.finalize_requested.connect(lambda: seen.append(True))
    card._finalize_btn.click()
    assert seen == [True]


def test_experiment_card_create_button_emits_signal_from_empty(app):
    # Empty state offers «Создать эксперимент» → emits create_requested
    # so the parent can open new_experiment_dialog.
    card = ExperimentCard()
    card.set_experiment(None)
    seen: list[bool] = []
    card.create_requested.connect(lambda: seen.append(True))
    card._create_btn.click()
    assert seen == [True]


def test_experiment_card_target_channel_line_uses_cyrillic_T(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(target_channel_id="Т11", target_value=4.21))
    text = card._target_label.text()
    assert "Т11" in text  # Cyrillic Т
    assert "4.21" in text
    assert "K" in text


def test_experiment_card_pressure_line_uses_cyrillic_unit(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(pressure_mbar=1.23e-6))
    text = card._pressure_label.text()
    # Compact scientific via shared _format_pressure helper —
    # "1.2e-6" (rounded to 1 decimal, exponent without leading zeros),
    # not "1.23e-06".
    assert "1.2e-6" in text
    assert "мбар" in text  # Cyrillic
    assert "mbar" not in text  # no Latin bleed


def test_experiment_card_pressure_missing_shows_dash(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(pressure_mbar=None))
    assert card._pressure_label.text() == "Давление: —"


def test_experiment_card_rejects_non_reference_target_channel(app):
    # Design system invariant #4: target must be Т11 or Т12.
    with pytest.raises(ValueError, match="Т11 or Т12"):
        _make_data(target_channel_id="Т5")


def test_experiment_card_rejects_unknown_mode(app):
    with pytest.raises(ValueError, match="experiment"):
        _make_data(mode="production")  # not a recognised mode


def test_experiment_card_switching_back_to_none_clears_fault_chrome(app):
    # Opening a faulted experiment paints the fault border; closing the
    # experiment (set_experiment(None)) must drop it back to the base
    # chrome so the tile isn't forever red.
    card = ExperimentCard()
    card.set_experiment(_make_data(faulted=True))
    assert theme.STATUS_FAULT in card.styleSheet()
    card.set_experiment(None)
    assert theme.STATUS_FAULT not in card.styleSheet()


def test_experiment_card_phase_stepper_reflects_current_phase(app):
    card = ExperimentCard()
    card.set_experiment(_make_data(current_phase="measurement"))
    assert card._phase_stepper._current_phase == "measurement"
