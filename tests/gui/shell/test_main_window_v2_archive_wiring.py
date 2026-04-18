"""II.2 host integration: verify MainWindowV2 pushes connection state
into the Archive overlay and that unrelated readings don't crash.

Follows the Host Integration Contract pattern from II.6/II.3.
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


def _finalized_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="x",
        channel="analytics/experiment_finalized",
        value=0.0,
        unit="",
        metadata={},
    )


# ----------------------------------------------------------------------
# Connection wiring
# ----------------------------------------------------------------------


def test_overlay_opens_connected_when_recent_reading():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("archive")
        assert w._archive_panel is not None
        assert w._archive_panel._connected is True
    finally:
        _stop_timers(w)


def test_overlay_opens_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        assert w._archive_panel is not None
        assert w._archive_panel._connected is False
    finally:
        _stop_timers(w)


def test_tick_status_flips_overlay_connected_bool():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        assert w._archive_panel._connected is True
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        assert w._archive_panel._connected is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# on_reading passthrough
# ----------------------------------------------------------------------


def test_on_reading_is_noop_and_does_not_crash():
    """Archive overlay's on_reading is a contract no-op today (no engine
    finalized event). Verify the shell still routes without raising.
    """
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        # The shell only routes analytics/* to operator_log, not to archive.
        # A finalized-event reading reaches the analytics branch and lands on
        # operator_log, but archive's on_reading is callable directly.
        w._archive_panel.on_reading(_finalized_reading())
        # No state mutation expected.
        assert w._archive_panel._entries == []
    finally:
        _stop_timers(w)


def test_unrelated_reading_does_not_affect_archive():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
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
        # Archive should not crash nor mutate its entries.
        assert w._archive_panel._entries == []
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy-open replay combinations
# ----------------------------------------------------------------------


def test_lazy_open_with_stale_silence_sets_disconnected():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic() - 100.0
        w._ensure_overlay("archive")
        assert w._archive_panel._connected is False
    finally:
        _stop_timers(w)


def test_archive_overlay_is_independent_from_current_experiment():
    """Archive is global scope. It must not break when no experiment is active."""
    _app()
    w = MainWindowV2()
    try:
        # No experiment status cached.
        assert w._latest_experiment_status is None
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("archive")
        # Overlay constructs fine, connected mirror applied.
        assert w._archive_panel is not None
        assert w._archive_panel._connected is True
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Export workers don't block main thread (smoke)
# ----------------------------------------------------------------------


def test_export_cancel_returns_promptly(monkeypatch):
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("archive")
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
        start = time.monotonic()
        w._archive_panel._on_export_csv_clicked()
        elapsed = time.monotonic() - start
        # Dialog cancel path must be fast — no export worker spawned.
        assert elapsed < 1.0
        assert not w._archive_panel._export_in_flight
    finally:
        _stop_timers(w)
