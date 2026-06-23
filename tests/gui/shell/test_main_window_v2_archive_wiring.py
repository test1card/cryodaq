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
        # Visible contract: set_connected(True) enables the refresh button.
        assert w._archive_panel._refresh_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_overlay_opens_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        assert w._archive_panel is not None
        # Visible contract: set_connected(False) disables the refresh button.
        assert w._archive_panel._refresh_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_tick_status_flips_overlay_connected_bool():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Connected → refresh and export enabled.
        assert w._archive_panel._refresh_btn.isEnabled() is True
        assert w._archive_panel._export_csv_btn.isEnabled() is True
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Disconnected → both disabled.
        assert w._archive_panel._refresh_btn.isEnabled() is False
        assert w._archive_panel._export_csv_btn.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# on_reading passthrough
# ----------------------------------------------------------------------


def test_on_reading_is_noop_and_does_not_crash():
    """Archive overlay's on_reading is a contract no-op today (no engine
    finalized event). Verify routing through the shell does not raise and
    leaves archive entries untouched.

    The shell routes analytics/* to operator_log, not to archive. Dispatch
    the finalized reading via the shell to exercise the actual routing path.
    """
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("archive")
        # Route through the shell dispatcher — archive must be unaffected.
        w._dispatch_reading(_finalized_reading())
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
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
        # Visible contract: stale silence → refresh button disabled.
        assert w._archive_panel._refresh_btn.isEnabled() is False
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
        # Overlay constructs fine, connected mirror applied — refresh enabled.
        assert w._archive_panel is not None
        assert w._archive_panel._refresh_btn.isEnabled() is True
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Export workers don't block main thread (smoke)
# ----------------------------------------------------------------------


def test_export_cancel_leaves_no_in_flight_worker(monkeypatch):
    """Cancelling the save dialog must not spawn an export worker.

    Asserts structural state (no worker, no in-flight flag) — no wall-clock
    threshold so the test is immune to CI timing variability.
    """
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("archive")
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
        w._archive_panel._on_export_csv_clicked()
        # Dialog cancel (empty path) must not start an export.
        assert not w._archive_panel._export_in_flight
        assert not w._archive_panel._export_workers
    finally:
        _stop_timers(w)
