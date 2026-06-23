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
    # Drive via _on_cooldown_status() with the real result payload — not the
    # private _update_cooldown_ui() bypass. Asserts the full result path.
    panel._on_cooldown_status({"state": "DISARMED", "progress": None, "eta_h": None})
    assert "Ожидает" in panel._cooldown_status_lbl.text(), (
        f"DISARMED must show 'Ожидает', got: {panel._cooldown_status_lbl.text()!r}"
    )


def test_cooldown_footer_armed_state_displays_active(panel: AlarmPanel) -> None:
    panel._on_cooldown_status({"state": "ARMED", "progress": None, "eta_h": None})
    assert "Активен" in panel._cooldown_status_lbl.text(), (
        f"ARMED must show 'Активен', got: {panel._cooldown_status_lbl.text()!r}"
    )


def test_cooldown_footer_watchdog_state(panel: AlarmPanel) -> None:
    panel.show()
    try:
        panel._on_cooldown_status(
            {"state": "WATCHDOG", "progress": None, "eta_h": None, "t_cold": 4.5}
        )
        assert "Сторож" in panel._cooldown_status_lbl.text(), (
            f"WATCHDOG must show 'Сторож', got: {panel._cooldown_status_lbl.text()!r}"
        )
        assert panel._cooldown_eta_lbl.isVisible()
        assert "Т11" in panel._cooldown_eta_lbl.text(), (
            f"Eta label must mention Т11 for WATCHDOG, got: {panel._cooldown_eta_lbl.text()!r}"
        )
    finally:
        panel.hide()


def test_cooldown_footer_fired_uses_status_fault_color(panel: AlarmPanel) -> None:
    panel._on_cooldown_status({"state": "FIRED", "progress": 0.6, "eta_h": 2.5})
    style = panel._cooldown_status_lbl.styleSheet()
    assert theme.STATUS_FAULT in style, (
        f"FIRED state must use STATUS_FAULT color; styleSheet={style!r}"
    )
    # Also assert text is rendered (not just color).
    assert "ПРЕДУПРЕЖДЕНИЕ" in panel._cooldown_status_lbl.text() or \
        "захолажив" in panel._cooldown_status_lbl.text().lower() or \
        "план" in panel._cooldown_status_lbl.text().lower(), (
        f"FIRED status text unexpected: {panel._cooldown_status_lbl.text()!r}"
    )


def test_cooldown_footer_auto_disarmed_uses_status_ok_color(panel: AlarmPanel) -> None:
    panel._on_cooldown_status({"state": "AUTO_DISARMED", "progress": None, "eta_h": None})
    style = panel._cooldown_status_lbl.styleSheet()
    assert theme.STATUS_OK in style, (
        f"AUTO_DISARMED must use STATUS_OK color; styleSheet={style!r}"
    )
    assert "Захолаживание завершено" in panel._cooldown_status_lbl.text(), (
        f"AUTO_DISARMED text wrong: {panel._cooldown_status_lbl.text()!r}"
    )


def test_cooldown_footer_progress_bar_only_visible_while_watching(panel: AlarmPanel) -> None:
    panel.show()
    try:
        panel._on_cooldown_status({"state": "DISARMED", "progress": None, "eta_h": None})
        assert not panel._cooldown_progress.isVisible(), (
            "Progress bar must be hidden for DISARMED"
        )
        panel._on_cooldown_status({"state": "WATCHING", "progress": 0.5, "eta_h": 2.0})
        assert panel._cooldown_progress.isVisible(), (
            "Progress bar must be visible for WATCHING"
        )
        assert panel._cooldown_progress.value() == 50
    finally:
        panel.hide()


def test_cooldown_footer_no_arm_handler_attributes(panel: AlarmPanel) -> None:
    """No arm/disarm QPushButton must exist anywhere in the cooldown footer
    widget tree — the UI contract is verified by rendered widgets, not
    private attribute presence."""
    box = _cooldown_groupbox(panel)
    assert box is not None
    arm_buttons = [
        btn for btn in box.findChildren(QPushButton)
        if any(kw in btn.text().lower() for kw in ("arm", "disarm", "захолаж", "взвод"))
    ]
    assert arm_buttons == [], (
        f"No arm/disarm buttons must exist in cooldown footer; found: {arm_buttons}"
    )
