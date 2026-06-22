"""Tests for engine --force kill lock file handling."""

from __future__ import annotations

from unittest.mock import patch


def test_force_kill_removes_lock_when_pid_not_alive(tmp_path):
    """_force_kill_existing reads PID via os.open and unlinks the lock
    when the PID is not alive (behavioral, not source-grep)."""
    from cryodaq.engine import _force_kill_existing

    lock_file = tmp_path / ".engine.lock"
    lock_file.write_text("12345", encoding="utf-8")

    with (
        patch("cryodaq.engine._LOCK_FILE", lock_file),
        patch("cryodaq.engine._is_pid_alive", return_value=False) as is_pid_alive,
    ):
        _force_kill_existing()

    is_pid_alive.assert_called_once_with(12345)
    assert not lock_file.exists(), "lock file must be removed after force-kill of dead PID"


def test_force_kill_noop_when_lock_absent(tmp_path):
    """_force_kill_existing is a no-op when the lock file does not exist."""
    from cryodaq.engine import _force_kill_existing

    lock_file = tmp_path / ".engine.lock"
    assert not lock_file.exists()

    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        _force_kill_existing()  # must not raise

    assert not lock_file.exists()


def test_force_kill_removes_lock_on_corrupt_pid(tmp_path):
    """If the lock file contains garbage (unparseable PID), the lock is
    still removed so the engine can restart cleanly."""
    from cryodaq.engine import _force_kill_existing

    lock_file = tmp_path / ".engine.lock"
    lock_file.write_text("not-a-pid", encoding="utf-8")

    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        _force_kill_existing()

    assert not lock_file.exists(), "corrupt lock file must be removed"
