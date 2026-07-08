"""II.8 host integration: MainWindowV2 ↔ InstrumentsPanel wiring.

Verifies:
- Connection mirror (_tick_status + _ensure_overlay replay).
- Readings routing (LakeShore + Keithley → cards).
- Analytics readings do NOT create cards.
- Public accessor callable from host.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer
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


def _k_reading(channel: str, value: float = 1.0, instrument_id: str = "") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit="K",
        metadata={},
    )


# ----------------------------------------------------------------------
# Connection mirror
# ----------------------------------------------------------------------


def test_tick_sets_overlay_connected_true_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: set_connected(True) starts the diagnostics poll timer.
        assert w._instrument_panel._diag_poll_timer.isActive() is True
    finally:
        _stop_timers(w)


def test_tick_sets_overlay_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        # First connect so state flips from False → True → False.
        w._last_reading_time = time.monotonic()
        w._tick_status()
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: set_connected(False) stops the diagnostics poll timer.
        assert w._instrument_panel._diag_poll_timer.isActive() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Readings routing
# ----------------------------------------------------------------------


def test_lakeshore_reading_creates_card():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._dispatch_reading(_k_reading("Т7", instrument_id="LS218_1"))
        QCoreApplication.processEvents()
        assert w._instrument_panel.get_instrument_count() == 1
        assert "LS218_1" in w._instrument_panel._cards
        # Visible contract: the rendered card shows the instrument name label.
        card = w._instrument_panel._cards["LS218_1"]
        assert card._name_label.text() == "LS218_1"
    finally:
        _stop_timers(w)


def test_keithley_reading_creates_card():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._dispatch_reading(_k_reading("Keithley_1/smua/voltage"))
        QCoreApplication.processEvents()
        assert "Keithley_1" in w._instrument_panel._cards
        # Visible contract: rendered card shows the instrument name label.
        card = w._instrument_panel._cards["Keithley_1"]
        assert card._name_label.text() == "Keithley_1"
    finally:
        _stop_timers(w)


def test_analytics_reading_does_not_create_card():
    """II.8: analytics/* readings must not create instrument
    cards. _extract_instrument_id drops analytics prefix before the "/"
    split."""
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        w._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="",
                channel="analytics/safety_state",
                value=0.0,
                unit="",
                metadata={},
            )
        )
        QCoreApplication.processEvents()
        assert "analytics" not in w._instrument_panel._cards
        assert w._instrument_panel.get_instrument_count() == 0
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy replay on first open
# ----------------------------------------------------------------------


def test_lazy_open_replays_connection_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("instruments")
        # Visible contract: recent reading replayed → diag poll timer started.
        assert w._instrument_panel._diag_poll_timer.isActive() is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        # Visible contract: cold-open → diag poll timer not started.
        assert w._instrument_panel._diag_poll_timer.isActive() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Public accessor callable from host
# ----------------------------------------------------------------------


def test_get_sensor_summary_text_callable_from_host():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("instruments")
        assert w._instrument_panel.get_sensor_summary_text() == "—"
    finally:
        _stop_timers(w)
