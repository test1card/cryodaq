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
        assert w._conductivity_panel._connected is True
    finally:
        _stop_timers(w)


def test_tick_sets_overlay_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        assert w._conductivity_panel._connected is False
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
        from PySide6.QtWidgets import QCheckBox

        cb = QCheckBox("Т1")
        w._conductivity_panel._checkboxes["Т1"] = cb
        w._conductivity_panel._ch_layout.insertWidget(0, cb)
        cb.stateChanged.connect(lambda state: w._conductivity_panel._on_check("Т1", state))
        cb.setChecked(True)
        # Dispatch the reading through the shell — it should reach the overlay.
        w._dispatch_reading(_temp_reading("Т1", 77.3))
        # Allow signal delivery.
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        assert w._conductivity_panel._temps.get("Т1") == 77.3
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
        assert w._conductivity_panel._power == 0.037
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
        assert w._conductivity_panel._connected is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("conductivity")
        assert w._conductivity_panel._connected is False
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
