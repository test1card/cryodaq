"""Exact launcher shutdown ownership and retry contracts."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _ScriptedProcess:
    pid = 9127

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.alive = True
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, *, timeout: float) -> int:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.alive = False
        return int(outcome)


def test_assistant_authority_is_retained_until_a_retry_proves_process_exit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.launcher as module

    authority = module._new_assistant_shutdown_authority(tmp_path)
    process = _ScriptedProcess(
        [
            subprocess.TimeoutExpired("assistant", 10),
            subprocess.TimeoutExpired("assistant", 10),
            subprocess.TimeoutExpired("assistant", 5),
            0,
        ]
    )
    host = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=authority.path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    with pytest.raises(subprocess.TimeoutExpired):
        module.LauncherWindow._stop_assistant(host)

    assert host._assistant_proc is process
    assert host._assistant_shutdown_path == authority.path
    assert host._assistant_shutdown_authority is authority
    assert process.terminate_calls == 1
    assert process.kill_calls == 1

    module.LauncherWindow._stop_assistant(host)

    assert host._assistant_proc is None
    assert host._assistant_shutdown_path is None
    assert host._assistant_shutdown_authority is None


def test_engine_handle_is_retained_until_a_retry_proves_process_exit() -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess(
        [
            subprocess.TimeoutExpired("engine", 10),
            subprocess.TimeoutExpired("engine", 5),
            0,
        ]
    )
    close_stderr = MagicMock()
    host = SimpleNamespace(
        _engine_proc=process,
        _engine_external=False,
        _close_engine_stderr_stream=close_stderr,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        LauncherWindow._stop_engine(host)

    assert host._engine_proc is process
    close_stderr.assert_not_called()

    LauncherWindow._stop_engine(host)

    assert host._engine_proc is None
    close_stderr.assert_called_once_with()
