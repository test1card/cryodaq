"""II.3 host integration: verify MainWindowV2 pushes connection +
current-experiment state into the OperatorLog overlay.

Mirrors the II.6 Keithley wiring test pattern — end-to-end via the
shell's existing signals, not the overlay setters in isolation.
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


def _log_entry_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="operator_log",
        channel="analytics/operator_log_entry",
        value=1.0,
        unit="",
        metadata={},
    )


def _experiment_status(exp_id: str | None) -> dict:
    if exp_id is None:
        return {"active_experiment": None, "phases": []}
    return {
        "active_experiment": {"experiment_id": exp_id, "name": exp_id},
        "phases": [],
    }


# ----------------------------------------------------------------------
# Connection wiring
# ----------------------------------------------------------------------


def test_overlay_opens_connected_when_recent_reading():
    _app()
    w = MainWindowV2()
    try:
        w._last_reading_time = time.monotonic()
        w._ensure_overlay("log")
        assert w._operator_log_panel is not None
        # Visible contract: set_connected(True) enables the log submit button.
        assert w._operator_log_panel._submit_btn.isEnabled() is True
    finally:
        _stop_timers(w)


def test_overlay_opens_disconnected_on_cold_start():
    _app()
    w = MainWindowV2()
    try:
        # _last_reading_time == 0.0 by default.
        w._ensure_overlay("log")
        assert w._operator_log_panel is not None
        # Visible contract: set_connected(False) disables the log submit button.
        assert w._operator_log_panel._submit_btn.isEnabled() is False
    finally:
        _stop_timers(w)


def test_tick_status_flips_overlay_connected_bool():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        w._last_reading_time = time.monotonic()
        w._tick_status()
        # Visible contract: connected → submit + author + message enabled.
        assert w._operator_log_panel._submit_btn.isEnabled() is True
        assert w._operator_log_panel._author_edit.isEnabled() is True
        assert w._operator_log_panel._message_edit.isEnabled() is True
        w._last_reading_time = time.monotonic() - 10.0
        w._tick_status()
        # Visible contract: disconnected → all composer controls disabled.
        assert w._operator_log_panel._submit_btn.isEnabled() is False
        assert w._operator_log_panel._author_edit.isEnabled() is False
        assert w._operator_log_panel._message_edit.isEnabled() is False
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Current experiment wiring
# ----------------------------------------------------------------------


def test_experiment_status_propagates_exp_id():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        w._on_experiment_status_received(_experiment_status("exp-2026-04-18"))
        assert w._operator_log_panel._current_experiment_id == "exp-2026-04-18"
        assert w._operator_log_panel._bind_experiment_check.isChecked()
    finally:
        _stop_timers(w)


def test_experiment_cleared_resets_bind_checkbox():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        w._on_experiment_status_received(_experiment_status("exp-xyz"))
        assert w._operator_log_panel._bind_experiment_check.isChecked()
        w._on_experiment_status_received(_experiment_status(None))
        assert w._operator_log_panel._current_experiment_id is None
        assert not w._operator_log_panel._bind_experiment_check.isChecked()
    finally:
        _stop_timers(w)


def test_lazy_open_replays_current_experiment():
    _app()
    w = MainWindowV2()
    try:
        # Cache an experiment BEFORE overlay is constructed.
        assert w._operator_log_panel is None
        w._on_experiment_status_received(_experiment_status("exp-pre-open"))
        assert w._operator_log_panel is None  # still lazy
        # Open overlay — should replay cached exp id.
        w._ensure_overlay("log")
        assert w._operator_log_panel is not None
        assert w._operator_log_panel._current_experiment_id == "exp-pre-open"
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# on_reading passthrough
# ----------------------------------------------------------------------


def test_operator_log_entry_does_not_forge_connection_or_refresh_on_overlay():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        last_measurement = w._last_reading_time
        connected_before = w._operator_log_panel._connected
        w._dispatch_reading(_log_entry_reading())
        # Analytics/support traffic is not measurement freshness or engine
        # presence authority. A log entry may update the view only after a
        # separately established live connection; it cannot spawn a poll by
        # itself.
        assert w._last_reading_time == last_measurement
        assert w._operator_log_panel._connected == connected_before
    finally:
        _stop_timers(w)


def test_unrelated_analytics_reading_does_not_crash():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        workers_before = len(w._operator_log_panel._workers)
        # Any non-operator_log_entry analytics reading must not raise and must
        # not trigger a refresh.
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
        # No refresh spawned for unrelated reading.
        assert len(w._operator_log_panel._workers) == workers_before
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Lazy replay combinations
# ----------------------------------------------------------------------


def test_lazy_open_with_no_experiment_sets_none():
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("log")
        assert w._operator_log_panel._current_experiment_id is None
        assert not w._operator_log_panel._bind_experiment_check.isChecked()
    finally:
        _stop_timers(w)


def test_lazy_open_after_connection_loss_is_disconnected():
    _app()
    w = MainWindowV2()
    try:
        # Simulate prior activity then stale.
        w._last_reading_time = time.monotonic() - 100.0
        w._ensure_overlay("log")
        # Visible contract: stale silence → submit button disabled.
        assert w._operator_log_panel._submit_btn.isEnabled() is False
    finally:
        _stop_timers(w)
