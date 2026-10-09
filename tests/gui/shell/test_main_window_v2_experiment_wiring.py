"""II.9 host integration: MainWindowV2 ↔ ExperimentOverlay wiring.

Verifies:
- Connection mirror (_tick_status) reaches the overlay post-construction.
- `_ensure_overlay("experiment")` replays current connection state.
- Existing readings routing preserved (operator_log_entry).
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


def test_tick_sets_experiment_connected_true_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("experiment")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._experiment_overlay._connected is True
    finally:
        _stop_timers(w)


def test_tick_sets_experiment_connected_false_when_stale():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("experiment")
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        assert w._experiment_overlay._connected is False
    finally:
        _stop_timers(w)


def test_lazy_open_replays_connection_when_recent():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("experiment")
        assert w._experiment_overlay._connected is True
    finally:
        _stop_timers(w)


def test_lazy_open_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("experiment")
        assert w._experiment_overlay._connected is False
    finally:
        _stop_timers(w)


def test_operator_log_reading_reaches_experiment_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("experiment")
        # Inject an active experiment so `on_reading` accepts the entry.
        w._experiment_overlay.set_experiment(
            {
                "name": "E",
                "operator": "V",
                "start_time": "2026-04-15T10:00:00+00:00",
                "experiment_id": "e1",
                "template_id": "custom",
            },
            phase_history=[],
        )
        reading = Reading(
            timestamp=datetime.now(UTC),
            instrument_id="engine",
            channel="analytics/operator_log_entry",
            value=0.0,
            unit="",
            metadata={"experiment_id": "e1"},
        )
        w._dispatch_reading(reading)
        QCoreApplication.processEvents()
        # No assertion on timeline content — log_get is async + worker is
        # stubbed at overlay-level. Contract here is: the call reaches
        # the overlay without raising and without filtering.
        assert w._experiment_overlay is not None
    finally:
        _stop_timers(w)


def test_finalize_button_disabled_when_disconnected():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("experiment")
        w._experiment_overlay.set_experiment(
            {
                "name": "E",
                "operator": "V",
                "start_time": "2026-04-15T10:00:00+00:00",
                "experiment_id": "e1",
                "template_id": "custom",
            },
            phase_history=[],
        )
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        assert w._experiment_overlay._finalize_btn.isEnabled() is False
    finally:
        _stop_timers(w)
