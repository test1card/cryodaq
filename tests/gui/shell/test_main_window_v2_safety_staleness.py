"""Regression: the bottom-bar safety strip must NOT show a stale runtime state
after the engine dies. runtime invariant — the GUI is not the source of truth
for runtime state; a stale green "running" while the engine is gone is dangerous.
"""

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


def test_safety_strip_blanks_when_engine_lost() -> None:
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

        # The safety strip must NOT keep showing the stale "running" state.
        assert w._last_safety_state is None, "stale safety state must be cleared on engine loss"
        assert w._bottom_bar._safety_label.text() == "● —"
    finally:
        _stop_timers(w)


def test_safety_strip_restored_on_reconnect() -> None:
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(_safety_reading("running"))
        w._last_reading_time = time.monotonic() - 200.0
        w._tick_status()
        assert w._last_safety_state is None

        # A fresh safety reading after reconnect restores the strip.
        w._dispatch_reading(_safety_reading("ready"))
        assert w._last_safety_state == "ready"
        assert w._bottom_bar._safety_label.text() != "● —"
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
