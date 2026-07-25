from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window(bridge=None):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.shell.main_window_v2 import MainWindowV2
    from cryodaq.gui.zmq_client import ZmqBridge

    app = QApplication.instance() or QApplication([])
    assert app is not None
    if bridge is None:
        bridge = ZmqBridge()
    window = MainWindowV2(bridge=bridge)
    for timer in window.findChildren(QTimer):
        timer.stop()
    return window, bridge


def _disk_reading(bridge_id: str):
    from cryodaq.drivers.base import Reading

    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="system",
        channel="system/disk_free_gb",
        value=20.0,
        unit="GB",
        metadata={
            "source": "disk_monitor",
            "operator_state": "ok",
            "bridge_instance_id": bridge_id,
        },
    )


@pytest.mark.parametrize(
    "invalid_bridge_id",
    ["A" * 32, "g" * 32, "a" * 31 + "\n"],
)
def test_noncanonical_bridge_identity_cannot_bind_disk_evidence(
    invalid_bridge_id: str,
) -> None:
    window, bridge = _window()
    try:
        bridge._bridge_instance_id = invalid_bridge_id
        window._dispatch_reading(_disk_reading(invalid_bridge_id))

        assert window._current_bridge_instance_id() is None
        assert window._accepted_disk_bridge_instance_id is None
        assert window._last_disk_observed_at is None
    finally:
        window.close()


def test_disk_evidence_expires_while_measurement_stream_remains_live(live_zmq_bridge, monkeypatch) -> None:
    window, bridge = _window(live_zmq_bridge)
    stale_calls: list[bool] = []
    try:
        assert bridge.bridge_instance_id is not None
        window._dispatch_reading(_disk_reading(bridge.bridge_instance_id))
        assert window._last_disk_observed_at is not None
        window._last_disk_observed_at = datetime.now(UTC) - timedelta(seconds=601)
        window._last_reading_time = time.monotonic()
        monkeypatch.setattr(
            window._bottom_bar,
            "mark_disk_stale",
            lambda *, disconnected: stale_calls.append(disconnected),
        )
        window._tick_status()
        assert stale_calls == [False]
    finally:
        window.close()


def test_bridge_replacement_immediately_stales_prior_disk_evidence(live_zmq_bridge, monkeypatch) -> None:
    window, bridge = _window(live_zmq_bridge)
    stale_calls: list[bool] = []
    try:
        assert bridge.bridge_instance_id is not None
        window._dispatch_reading(_disk_reading(bridge.bridge_instance_id))
        accepted = window._accepted_disk_bridge_instance_id
        assert accepted == bridge.bridge_instance_id
        monkeypatch.setattr(
            window._bottom_bar,
            "mark_disk_stale",
            lambda *, disconnected: stale_calls.append(disconnected),
        )
        bridge._bridge_instance_id = "f" * 32
        window._last_reading_time = time.monotonic()
        window._tick_status()
        assert stale_calls == [False]
        assert window._accepted_disk_bridge_instance_id is None
        assert window._last_disk_observed_at is None
    finally:
        window.close()
