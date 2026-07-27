"""TopWatchBar polling owns and retires its real Qt command threads."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from cryodaq.gui import zmq_client
from cryodaq.gui.shell import main_window_v2
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION


def _safety_status() -> dict[str, object]:
    return {
        "ok": True,
        "state": "ready",
        "fault_reason": "",
        "fault_revision": 0,
        "fault_activated_at": 0.0,
        "recovery_reason": "",
        "channels_tracked": 0,
        "keithley_connected": False,
        "active_channels": [],
        "mock": False,
        "engine_instance_id": "a" * 32,
        "proto": CLIENT_PROTOCOL_VERSION,
    }


@pytest.mark.owns_gui_command_worker_admission
def test_repeated_top_watch_bar_polls_retire_real_qthreads_before_shutdown(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    session_epoch = zmq_client.open_gui_command_worker_admission()
    window = MainWindowV2()
    for timer in window.findChildren(type(window._top_bar._fast_timer)):
        timer.stop()
    calls: list[str] = []

    def send_command(command: dict[str, str], *, cancellation_requested=None) -> dict[str, object]:
        del cancellation_requested
        calls.append(command["cmd"])
        return _safety_status() if command["cmd"] == "safety_status" else {"ok": False}

    monkeypatch.setattr(zmq_client, "send_command", send_command)
    try:
        for _ in range(5):
            window._top_bar._poll_fast()
            deadline = time.monotonic() + 2.0
            while window._top_bar._mock_status_worker is not None or window._top_bar._experiment_worker is not None:
                app.processEvents()
                assert time.monotonic() < deadline
            app.processEvents()
            assert window._top_bar.findChildren(QThread) == []

        assert calls.count("safety_status") == 5
        assert calls.count("experiment_status") == 5
        zmq_client.revoke_gui_command_worker_admission(session_epoch)
        assert window.settle_owned_workers()
    finally:
        if zmq_client.gui_command_worker_admission_open():
            zmq_client.revoke_gui_command_worker_admission(session_epoch)
        window.close()


def test_shutdown_stops_qthread_descendant_enumeration_at_deadline(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindowV2()
    window._annunciation_controller = None
    thread = QThread(window)
    ticks = iter((0.0, 2.0))
    monkeypatch.setattr(main_window_v2.time, "monotonic", lambda: next(ticks, 2.0))

    assert not window.settle_owned_workers()

    thread.deleteLater()
    window.deleteLater()
    app.processEvents()
