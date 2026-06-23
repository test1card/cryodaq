"""II.5 host integration: verify MainWindowV2 pushes connection state
into the Conductivity overlay and that temperature / power readings
route correctly.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _temp_reading(channel: str, value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LakeShore_1",
        channel=channel,
        value=value,
        unit="K",
        metadata={},
    )


def _power_reading(value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="Keithley_1",
        channel="Keithley_1/smua/power",
        value=value,
        unit="W",
        metadata={},
    )


# ----------------------------------------------------------------------
# Connection mirror
# ----------------------------------------------------------------------


def test_tick_sets_overlay_connected_true_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: set_connected(True) enables the auto-sweep Start
        # button (idle state → start_ok = connected and not stabilizing).
        assert w._conductivity_panel._auto_start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_tick_sets_overlay_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: set_connected(False) disables the auto-sweep Start
        # button.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Readings routing
# ----------------------------------------------------------------------


def test_temperature_reading_reaches_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        # Inject a visible T channel so the overlay accepts it.
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QCheckBox

        cb = QCheckBox("Т1")
        w._conductivity_panel._checkboxes["Т1"] = cb
        # v0.55.2 A3: chain checkboxes live in a QGridLayout (2-col compact);
        # drop the Т1 stub into the top-left cell.
        w._conductivity_panel._ch_layout.addWidget(cb, 0, 0)
        cb.stateChanged.connect(lambda state: w._conductivity_panel._on_check("Т1", state))
        cb.setChecked(True)
        # Dispatch the reading through the shell — it should reach the overlay.
        w._dispatch_reading(_temp_reading("Т1", 77.3))
        QCoreApplication.processEvents()
        # Assert stored value (feeds R/G table on next _refresh tick).
        assert w._conductivity_panel._temps.get("Т1") == 77.3
        # Invoke the rendering path explicitly to confirm the stored value
        # propagates without error into the live display.
        w._conductivity_panel._refresh()
    finally:
        _stop_timers(w)


def test_power_reading_reaches_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._dispatch_reading(_power_reading(0.037))
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        # Assert stored value AND that it renders into the power label.
        assert w._conductivity_panel._power == 0.037
        w._conductivity_panel._update_power_label()
        assert "0.037" in w._conductivity_panel._power_label.text()
    finally:
        _stop_timers(w)


def test_unrelated_reading_does_not_affect_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="x",
                channel="analytics/safety_state",
                value=0.0,
                unit="",
                metadata={"state": "ready"},
            )
        )
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        # No mutation.
        assert w._conductivity_panel._temps == {}
        assert w._conductivity_panel._power == 0.0
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy replay
# ----------------------------------------------------------------------


def test_lazy_open_replays_connection_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("conductivity")
        assert w._conductivity_panel is not None
        # Visible contract: lazy-open with recent reading → Start button enabled.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        # Visible contract: cold-open → Start button disabled.
        assert w._conductivity_panel._auto_start_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Auto-state accessor
# ----------------------------------------------------------------------


def test_get_auto_state_accessible_from_host():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        # The future finalize guard wiring (II.9) will call this.
        assert w._conductivity_panel.get_auto_state() == "idle"
        assert w._conductivity_panel.is_auto_sweep_active() is False
    finally:
        _stop_timers(w)
