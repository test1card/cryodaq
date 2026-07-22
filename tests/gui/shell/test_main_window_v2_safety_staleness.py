"""Regression: disconnect retains last safety evidence but revokes currency."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.zmq_client import ZmqBridge


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


def test_analytics_safety_reading_never_enables_mutation_authority() -> None:
    """READY-looking telemetry is display evidence, never command authority."""
    _app()
    bridge = ZmqBridge()
    assert bridge.bridge_instance_id is not None
    window = MainWindowV2(bridge=bridge)
    try:
        window._latest_experiment_status = {"active_experiment": {"experiment_id": "exp-a"}}
        window._ensure_overlay("source")
        assert window._keithley_panel is not None

        # Establish a genuinely connected presentation so disabled controls
        # cannot be explained by an unrelated no-connection condition.
        window._last_reading_time = time.monotonic()
        window._tick_status()
        assert window._keithley_panel._connected is True

        window._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="safety_manager",
                channel="analytics/safety_state",
                value=0.0,
                unit="",
                metadata={
                    "state": "ready",
                    "reason": "",
                    "bridge_instance_id": bridge.bridge_instance_id,
                    "experiment_id": "exp-a",
                },
            )
        )

        assert window._keithley_panel._connected is True
        assert window._keithley_panel._safety_ready is False
        assert window._keithley_panel._smua_block._start_btn.isEnabled() is False
        assert window._keithley_panel._start_both_btn.isEnabled() is False
    finally:
        _stop_timers(window)


def test_disk_reading_is_presented_only_when_backend_metadata_is_exact() -> None:
    _app()
    bridge = ZmqBridge()
    assert bridge.bridge_instance_id is not None
    window = MainWindowV2(bridge=bridge)
    try:
        reading = Reading(
            timestamp=datetime.now(UTC),
            instrument_id="system",
            channel="system/disk_free_gb",
            value=5.0,
            unit="GB",
            metadata={
                "source": "disk_monitor",
                "operator_state": "caution",
                "bridge_instance_id": bridge.bridge_instance_id,
            },
        )
        window._dispatch_reading(reading)
        assert "5.0" in window._bottom_bar._disk_label.text()
        prior = window._bottom_bar._disk_label.text()
        window._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="system",
                channel="system/disk_free_gb",
                value=1.0,
                unit="GB",
                metadata={
                    "source": "untrusted",
                    "operator_state": "fault",
                    "bridge_instance_id": bridge.bridge_instance_id,
                },
            )
        )
        assert window._bottom_bar._disk_label.text() == prior
    finally:
        _stop_timers(window)


def test_disk_evidence_rejects_foreign_future_reordered_and_replaced_bridge_cuts() -> None:
    _app()
    bridge = ZmqBridge()
    assert bridge.bridge_instance_id is not None
    window = MainWindowV2(bridge=bridge)
    try:
        now = datetime.now(UTC)

        def disk(value: float, *, observed_at: datetime, bridge_id: str) -> Reading:
            return Reading(
                timestamp=observed_at,
                instrument_id="system",
                channel="system/disk_free_gb",
                value=value,
                unit="GB",
                metadata={
                    "source": "disk_monitor",
                    "operator_state": "ok",
                    "bridge_instance_id": bridge_id,
                },
            )

        window._dispatch_reading(disk(20.0, observed_at=now, bridge_id=bridge.bridge_instance_id))
        assert "20.0" in window._bottom_bar._disk_label.text()
        prior = window._bottom_bar._disk_label.text()
        window._dispatch_reading(disk(21.0, observed_at=now + timedelta(seconds=10), bridge_id="foreign"))
        window._dispatch_reading(
            disk(22.0, observed_at=now + timedelta(seconds=20), bridge_id=bridge.bridge_instance_id)
        )
        window._dispatch_reading(disk(23.0, observed_at=now, bridge_id=bridge.bridge_instance_id))
        assert window._bottom_bar._disk_label.text() == prior

        bridge._bridge_instance_id = "f" * 32
        window._dispatch_reading(disk(24.0, observed_at=now + timedelta(seconds=1), bridge_id="old" * 8))
        assert "устарело" in window._bottom_bar._disk_label.text()
        window._dispatch_reading(
            disk(25.0, observed_at=now + timedelta(seconds=2), bridge_id=bridge.bridge_instance_id)
        )
        assert "25.0" in window._bottom_bar._disk_label.text()
    finally:
        _stop_timers(window)
