from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.shell.main_window_v2 import MainWindowV2
    from cryodaq.gui.zmq_client import ZmqBridge

    app = QApplication.instance() or QApplication([])
    assert app is not None
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


def test_disk_evidence_expires_while_measurement_stream_remains_live(monkeypatch) -> None:
    window, bridge = _window()
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


def test_bridge_replacement_immediately_stales_prior_disk_evidence(monkeypatch) -> None:
    window, bridge = _window()
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
