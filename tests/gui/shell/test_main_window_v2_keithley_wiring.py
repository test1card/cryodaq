"""II.6 post-review: verify MainWindowV2 pushes connection + safety state
into the Keithley overlay.

Codex external review flagged that the shell never invoked
``KeithleyPanel.set_connected`` or ``set_safety_ready`` after the II.6
rewrite — so in production the overlay showed permanent «Нет связи»
and controls stayed disabled. These tests exercise the host wiring
end-to-end, not the overlay setters in isolation.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2, _map_safety_state


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _safety_reading(state: str, reason: str = "") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="safety_manager",
        channel="analytics/safety_state",
        value=0.0,
        unit="",
        metadata={"state": state, "reason": reason},
    )


# ----------------------------------------------------------------------
# Pure helper tests — no Qt needed
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "state, reason, expected",
    [
        ("ready", "any", (True, "")),
        ("run_permitted", "", (True, "")),
        ("running", "", (True, "")),
        ("safe_off", "system stop", (False, "system stop")),
        ("fault_latched", "", (False, "fault_latched")),
        ("unknown_state", "", (False, "unknown_state")),
        (None, "", (False, "unknown")),
    ],
)
def test_map_safety_state_cases(state, reason, expected):
    assert _map_safety_state(state, reason) == expected


def test_map_safety_state_truncates_long_reason():
    long_reason = "x" * 200
    ready, text = _map_safety_state("safe_off", long_reason)
    assert ready is False
    # 120 chars preserved + ellipsis character.
    assert text == "x" * 120 + "…"


def test_map_safety_state_empty_reason_falls_back_to_state():
    ready, text = _map_safety_state("fault_latched", "")
    assert ready is False
    assert text == "fault_latched"


def test_map_safety_state_whitespace_reason_falls_back():
    ready, text = _map_safety_state("safe_off", "   \t  ")
    assert ready is False
    assert text == "safe_off"


# ----------------------------------------------------------------------
# Host wiring — connection state
# ----------------------------------------------------------------------


def test_keithley_overlay_receives_connection_state_on_open():
    _app()
    w = MainWindowV2()
    try:
        # Simulate a recent reading — overlay should open as connected.
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        assert w._keithley_panel._connected is True
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_disconnection_on_open_with_no_readings():
    _app()
    w = MainWindowV2()
    try:
        # Cold-start: _last_reading_time == 0.0 — overlay should open disconnected.
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        assert w._keithley_panel._connected is False
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_connection_state_via_tick():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        # Simulate recent data → tick flips connected to True.
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._keithley_panel._connected is True
        # Advance silence past the 3 s threshold → tick flips to False.
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        assert w._keithley_panel._connected is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Host wiring — safety state
# ----------------------------------------------------------------------


def test_keithley_overlay_receives_safety_state_via_dispatch():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        w._dispatch_reading(_safety_reading("fault_latched", "test reason"))
        assert w._keithley_panel._safety_ready is False
        assert "test reason" in w._keithley_panel._gate_reason_label.text()
        assert "Управление заблокировано" in w._keithley_panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_keithley_overlay_receives_safety_ready_via_dispatch():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("source")
        # First transition to blocked.
        w._dispatch_reading(_safety_reading("fault_latched", "boom"))
        assert w._keithley_panel._safety_ready is False
        # Then back to ready — gate label hides.
        w._dispatch_reading(_safety_reading("ready", ""))
        assert w._keithley_panel._safety_ready is True
        assert w._keithley_panel._gate_reason_label.isHidden()
    finally:
        _stop_timers(w)


def test_keithley_overlay_safety_replay_on_lazy_open():
    _app()
    w = MainWindowV2()
    try:
        # Dispatch safety reading BEFORE overlay is constructed.
        assert w._keithley_panel is None
        w._dispatch_reading(_safety_reading("fault_latched", "stale sensor"))
        # Cache populated but overlay still lazy.
        assert w._last_safety_state == "fault_latched"
        assert w._last_safety_reason == "stale sensor"
        assert w._keithley_panel is None

        # Open overlay — cached state should be replayed.
        w._ensure_overlay("source")
        assert w._keithley_panel is not None
        assert w._keithley_panel._safety_ready is False
        assert "stale sensor" in w._keithley_panel._gate_reason_label.text()
    finally:
        _stop_timers(w)


def test_keithley_overlay_connection_replay_on_lazy_open():
    _app()
    w = MainWindowV2()
    try:
        # No reading yet → cold-start disconnected.
        w._ensure_overlay("source")
        assert w._keithley_panel._connected is False
    finally:
        _stop_timers(w)
