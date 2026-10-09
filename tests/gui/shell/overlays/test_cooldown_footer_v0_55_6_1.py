"""v0.55.6.1 PART C — Контроль захолаживания footer is status-only.

Architect 2026-05-07: «не понимаю сути кнопки контроль захолаживания —
он же должен всегда работать, если это аларм». The arm/disarm button
disappears; auto_arm policy (shipped v0.55.4) handles the lifecycle.
The footer continues to surface state, ETA, and progress.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import AlarmPanel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app: QApplication):
    p = AlarmPanel()
    yield p
    p.deleteLater()


def _cooldown_groupbox(panel: AlarmPanel) -> QGroupBox:
    return panel.findChild(QGroupBox, "cooldownControl")


def test_cooldown_footer_has_no_push_button(panel: AlarmPanel) -> None:
    """Architect 2026-05-07 — manual arm/disarm button removed."""
    box = _cooldown_groupbox(panel)
    assert box is not None
    buttons = box.findChildren(QPushButton)
    assert buttons == [], (
        f"Cooldown footer must have no buttons under v0.55.6.1; got {buttons}"
    )


def test_cooldown_footer_status_label_present(panel: AlarmPanel) -> None:
    box = _cooldown_groupbox(panel)
    # The status label is an instance attribute, not a child name —
    # check by attribute then assert it lives inside the groupbox.
    assert panel._cooldown_status_lbl is not None
    assert panel._cooldown_status_lbl.parent() is box


def test_cooldown_footer_status_label_has_auto_arm_tooltip(panel: AlarmPanel) -> None:
    """Tooltip surfaces the auto_arm policy so the operator understands
    why there's no manual control to grab.
    """
    tip = panel._cooldown_status_lbl.toolTip()
    assert "автоматически" in tip
    assert "захолажив" in tip.lower()


def test_cooldown_footer_initial_state_says_waiting(panel: AlarmPanel) -> None:
    panel._update_cooldown_ui("DISARMED", progress=None, eta_h=None)
    assert "Ожидает" in panel._cooldown_status_lbl.text()


def test_cooldown_footer_armed_state_displays_active(panel: AlarmPanel) -> None:
    panel._update_cooldown_ui("ARMED", progress=None, eta_h=None)
    assert "Активен" in panel._cooldown_status_lbl.text()


def test_cooldown_footer_watchdog_state(panel: AlarmPanel) -> None:
    panel.show()
    try:
        panel._update_cooldown_ui("WATCHDOG", progress=None, eta_h=None, t_cold=4.5)
        assert "Сторож" in panel._cooldown_status_lbl.text()
        assert panel._cooldown_eta_lbl.isVisible()
        assert "Т11" in panel._cooldown_eta_lbl.text()
    finally:
        panel.hide()


def test_cooldown_footer_fired_uses_status_fault_color(panel: AlarmPanel) -> None:
    panel._update_cooldown_ui("FIRED", progress=0.6, eta_h=2.5)
    style = panel._cooldown_status_lbl.styleSheet()
    assert theme.STATUS_FAULT in style


def test_cooldown_footer_auto_disarmed_uses_status_ok_color(panel: AlarmPanel) -> None:
    panel._update_cooldown_ui("AUTO_DISARMED", progress=None, eta_h=None)
    style = panel._cooldown_status_lbl.styleSheet()
    assert theme.STATUS_OK in style
    assert "Захолаживание завершено" in panel._cooldown_status_lbl.text()


def test_cooldown_footer_progress_bar_only_visible_while_watching(panel: AlarmPanel) -> None:
    panel.show()
    try:
        panel._update_cooldown_ui("DISARMED", progress=None, eta_h=None)
        assert not panel._cooldown_progress.isVisible()
        panel._update_cooldown_ui("WATCHING", progress=0.5, eta_h=2.0)
        assert panel._cooldown_progress.isVisible()
        assert panel._cooldown_progress.value() == 50
    finally:
        panel.hide()


def test_cooldown_footer_no_arm_handler_attributes(panel: AlarmPanel) -> None:
    """Defensive: no zombie arm/disarm handlers left on the panel."""
    assert not hasattr(panel, "_on_cooldown_arm_clicked")
    assert not hasattr(panel, "_on_cooldown_disarm_clicked")
    assert not hasattr(panel, "_cooldown_arm_btn")
