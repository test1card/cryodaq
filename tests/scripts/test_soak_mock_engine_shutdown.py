"""The soak driver must ASK the engine to stop on a channel it can hear.

`Popen.terminate()` is `Popen.kill()` on Windows -- `TerminateProcess(handle, 1)`
-- so the child's exit code is 1 however gracefully it would have exited, and
`clean_shutdown = exit_code == 0` can never be satisfied there. A soak that
reports FAILED for that reason is measuring the platform, not the engine.

Measured on Windows/CPython 3.14.3 before this guard existed:

    Popen.terminate is Popen.kill          -> True
    cooperative child (SIGTERM -> exit 0)  -> exit_code 1 after terminate()
    cooperative child (SIGBREAK -> exit 0) -> exit_code 0 after CTRL_BREAK_EVENT

These tests are deterministic on every platform: they drive the dispatch
directly rather than spawning a process.
"""

from __future__ import annotations

import signal
import subprocess

import pytest

from scripts.soak_mock_engine import _request_shutdown


class _RecordingProc:
    """Records which shutdown channel the driver chose."""

    def __init__(self) -> None:
        self.signals: list[int] = []
        self.terminated = 0

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)

    def terminate(self) -> None:
        self.terminated += 1


def test_windows_shutdown_uses_ctrl_break_not_terminate(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows the driver must send CTRL_BREAK_EVENT, which is catchable."""
    monkeypatch.setattr("scripts.soak_mock_engine.sys.platform", "win32")
    proc = _RecordingProc()

    _request_shutdown(proc)  # type: ignore[arg-type]

    assert proc.terminated == 0, "terminate() on Windows is TerminateProcess and cannot be handled"
    assert proc.signals == [signal.CTRL_BREAK_EVENT]


def test_posix_shutdown_still_uses_terminate(monkeypatch: pytest.MonkeyPatch) -> None:
    """On POSIX terminate() IS a real SIGTERM, so it stays correct."""
    monkeypatch.setattr("scripts.soak_mock_engine.sys.platform", "linux")
    proc = _RecordingProc()

    _request_shutdown(proc)  # type: ignore[arg-type]

    assert proc.terminated == 1
    assert proc.signals == []


def test_child_is_created_in_its_own_process_group_on_windows() -> None:
    """CTRL_BREAK_EVENT cannot reach a child that shares the parent's group."""
    from scripts.soak_mock_engine import _SHUTDOWN_CREATION_FLAGS

    expected = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert _SHUTDOWN_CREATION_FLAGS == expected
