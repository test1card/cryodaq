"""A3b — TopWatchBar recent_alarms poller/beeper wiring.

The pure decision logic (plan_from_response) is covered without Qt in
test_alarm_sound.py; this file covers only the Qt-adjacent wiring: the
skip-if-in-flight poll guard, the exact command dict sent, and that
_on_recent_alarms_result routes to the right beep calls.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.top_watch_bar import TopWatchBar


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_bar() -> TopWatchBar:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    return bar


class _FakeWorker:
    """Synchronous stand-in for ZmqCommandWorker (real code only ever uses
    .finished.connect(...) and .start()/.isFinished())."""

    last_cmd: dict | None = None
    result: dict = {"ok": False}

    def __init__(self, cmd: dict, parent=None) -> None:
        self.cmd = cmd
        _FakeWorker.last_cmd = cmd
        self._cb = None

    @property
    def finished(self):
        return self

    def connect(self, cb):
        self._cb = cb

    def start(self):
        if self._cb:
            self._cb(_FakeWorker.result)

    def isFinished(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _patch_worker(monkeypatch):
    import cryodaq.gui.zmq_client as zc

    monkeypatch.setattr(zc, "ZmqCommandWorker", _FakeWorker)
    yield


def test_poll_sends_recent_alarms_with_current_since_seq() -> None:
    bar = _make_bar()
    _FakeWorker.result = {"ok": False}
    bar._poll_recent_alarms()
    assert _FakeWorker.last_cmd == {"cmd": "recent_alarms", "since_seq": 0}

    bar._alarm_sound_last_seq = 42
    bar._poll_recent_alarms()
    assert _FakeWorker.last_cmd == {"cmd": "recent_alarms", "since_seq": 42}


def test_poll_skips_when_previous_worker_in_flight() -> None:
    bar = _make_bar()

    class _StillRunning:
        def isFinished(self) -> bool:
            return False

    bar._alarm_sound_worker = _StillRunning()
    _FakeWorker.last_cmd = None
    bar._poll_recent_alarms()
    assert _FakeWorker.last_cmd is None, "must not spawn a new worker while one is in flight"


def test_first_result_establishes_baseline_without_beeping() -> None:
    bar = _make_bar()
    assert bar._alarm_sound_have_baseline is False
    with patch("cryodaq.gui.shell.top_watch_bar.QApplication.beep") as beep:
        bar._on_recent_alarms_result(
            {"seq": 5, "ok": True, "alarms": [{"seq": i, "level": "CRITICAL"} for i in range(1, 6)]}
        )
    beep.assert_not_called()
    assert bar._alarm_sound_have_baseline is True
    assert bar._alarm_sound_last_seq == 5


def test_not_ok_result_is_ignored() -> None:
    bar = _make_bar()
    bar._alarm_sound_have_baseline = True
    bar._alarm_sound_last_seq = 3
    with patch("cryodaq.gui.shell.top_watch_bar.QApplication.beep") as beep:
        bar._on_recent_alarms_result({"ok": False})
    beep.assert_not_called()
    assert bar._alarm_sound_last_seq == 3


def test_new_warning_beeps_once() -> None:
    bar = _make_bar()
    bar._alarm_sound_have_baseline = True
    bar._alarm_sound_last_seq = 1
    with patch("cryodaq.gui.shell.top_watch_bar.QApplication.beep") as beep, patch(
        "cryodaq.gui.shell.top_watch_bar._beep_critical"
    ) as beep_critical:
        bar._on_recent_alarms_result(
            {"ok": True, "seq": 2, "alarms": [{"seq": 2, "level": "WARNING"}]}
        )
    beep.assert_called_once()
    beep_critical.assert_not_called()
    assert bar._alarm_sound_last_seq == 2


def test_new_critical_uses_three_beep_pattern() -> None:
    bar = _make_bar()
    bar._alarm_sound_have_baseline = True
    bar._alarm_sound_last_seq = 1
    with patch("cryodaq.gui.shell.top_watch_bar.QApplication.beep") as beep, patch(
        "cryodaq.gui.shell.top_watch_bar._beep_critical"
    ) as beep_critical:
        bar._on_recent_alarms_result(
            {"ok": True, "seq": 2, "alarms": [{"seq": 2, "level": "CRITICAL"}]}
        )
    beep_critical.assert_called_once()
    beep.assert_not_called()


def test_multiple_new_alarms_beep_once_each() -> None:
    bar = _make_bar()
    bar._alarm_sound_have_baseline = True
    bar._alarm_sound_last_seq = 0
    with patch("cryodaq.gui.shell.top_watch_bar.QApplication.beep") as beep, patch(
        "cryodaq.gui.shell.top_watch_bar._beep_critical"
    ) as beep_critical:
        bar._on_recent_alarms_result(
            {
                "ok": True,
                "seq": 3,
                "alarms": [
                    {"seq": 1, "level": "WARNING"},
                    {"seq": 2, "level": "CRITICAL"},
                    {"seq": 3, "level": "WARNING"},
                ],
            }
        )
    assert beep.call_count == 2
    assert beep_critical.call_count == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
