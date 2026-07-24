"""Regression: disconnect retains last safety evidence but revokes currency."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from datetime import UTC, datetime

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


def _safety_reading(state: str) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="engine",
        channel="analytics/safety_state",
        value=0.0,
        unit="",
        metadata={"state": state, "reason": ""},
    )


def _measurement_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel="T1",
        value=4.2,
        unit="K",
        metadata={},
    )


def test_safety_strip_retains_last_known_state_as_disconnected_when_engine_lost() -> None:
    _app()
    w = MainWindowV2()
    try:
        # Engine reports RUNNING — strip shows it.
        w._dispatch_reading(_safety_reading("running"))
        assert w._last_safety_state == "running"
        assert w._bottom_bar._safety_label.text() != "● —"

        # Engine dies: no more readings; silence exceeds the disconnect window.
        w._last_reading_time = time.monotonic() - 200.0
        w._tick_status()

        assert w._last_safety_state == "running"
        assert "running" in w._bottom_bar._safety_label.text()
        assert "нет связи" in w._bottom_bar._safety_label.text()
        assert "текущая связь" in w._bottom_bar._safety_label.accessibleDescription().lower()
    finally:
        _stop_timers(w)


def test_safety_strip_restored_on_reconnect() -> None:
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(_safety_reading("running"))
        w._last_reading_time = time.monotonic() - 200.0
        w._tick_status()
        assert "нет связи" in w._bottom_bar._safety_label.text()

        # A fresh safety reading after reconnect restores the strip.
        w._dispatch_reading(_safety_reading("ready"))
        assert w._last_safety_state == "ready"
        assert w._bottom_bar._safety_label.text() != "● —"
    finally:
        _stop_timers(w)


def test_safety_publication_expires_while_measurement_connection_stays_live() -> None:
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(_safety_reading("ready"))
        w._last_safety_reading_time = time.monotonic() - 31.0
        w._dispatch_reading(_measurement_reading())
        w._tick_status()

        assert w._overview_panel._connected is True
        assert "нет связи" in w._bottom_bar._safety_label.text()
        assert "ready" in w._bottom_bar._safety_label.text()
    finally:
        _stop_timers(w)


def test_malformed_safety_publication_cannot_replace_or_refresh_last_truth() -> None:
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(_safety_reading("ready"))
        receipt = w._last_safety_reading_time
        w._dispatch_reading(_safety_reading("unknown"))

        assert w._last_safety_state == "ready"
        assert w._last_safety_reading_time == receipt
        assert w._last_reading_time == 0.0
    finally:
        _stop_timers(w)


def test_closeevent_stops_status_timer() -> None:
    """closeEvent must stop the status timer so it can't fire into a
    half-destroyed window (and the QThread teardown stays bounded)."""
    from PySide6.QtGui import QCloseEvent

    _app()
    w = MainWindowV2()
    try:
        assert w._status_timer.isActive()
        w.closeEvent(QCloseEvent())
        assert not w._status_timer.isActive(), "status timer must be stopped on close"
    finally:
        _stop_timers(w)


def test_disk_reading_is_presented_only_when_backend_metadata_is_exact() -> None:
    _app()
    window = MainWindowV2()
    try:
        reading = Reading(
            timestamp=datetime.now(UTC),
            instrument_id="system",
            channel="system/disk_free_gb",
            value=5.0,
            unit="GB",
            metadata={"source": "disk_monitor", "operator_state": "caution"},
        )
        window._dispatch_reading(reading)
        assert "5.0" in window._bottom_bar._disk_label.text()
        window._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="system",
                channel="system/disk_free_gb",
                value=1.0,
                unit="GB",
                metadata={"source": "untrusted", "operator_state": "fault"},
            )
        )
        assert "~5.0" in window._bottom_bar._disk_label.text()
        assert "unavailable" in window._bottom_bar._disk_label.accessibleDescription()
    finally:
        _stop_timers(window)
