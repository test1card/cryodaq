"""Tests for engine --force kill lock file handling."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_force_mode_ignores_free_stale_pid_record_without_process_inspection_or_kill(tmp_path):
    """A free stale diagnostic record is not process-termination authority."""
    from cryodaq.engine import _acquire_engine_lock, _force_kill_existing, _release_engine_lock

    lock_file = tmp_path / ".engine.lock"
    lock_file.write_text("12345", encoding="utf-8")

    with (
        patch("cryodaq.engine._LOCK_FILE", lock_file),
        patch("psutil.Process") as process_lookup,
        patch("cryodaq.engine.os.kill", create=True) as raw_kill,
    ):
        _force_kill_existing()

    process_lookup.assert_not_called()
    raw_kill.assert_not_called()
    assert lock_file.exists()
    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        fd = _acquire_engine_lock()
        _release_engine_lock(fd)
    assert lock_file.exists()


def test_force_mode_creates_and_retains_one_stable_free_lock_object(tmp_path):
    """A missing lock becomes the persistent object used by later contenders."""
    from cryodaq.engine import _force_kill_existing

    lock_file = tmp_path / ".engine.lock"
    assert not lock_file.exists()

    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        _force_kill_existing()  # must not raise

    assert lock_file.exists()


def test_force_mode_ignores_free_corrupt_record_without_process_inspection(tmp_path):
    """Corrupt diagnostics do not authorize process lookup or lock replacement."""
    from cryodaq.engine import _acquire_engine_lock, _force_kill_existing, _release_engine_lock

    lock_file = tmp_path / ".engine.lock"
    lock_file.write_text("not-a-pid", encoding="utf-8")

    with (
        patch("cryodaq.engine._LOCK_FILE", lock_file),
        patch("psutil.Process") as process_lookup,
    ):
        _force_kill_existing()

    process_lookup.assert_not_called()
    assert lock_file.exists()
    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        fd = _acquire_engine_lock()
        _release_engine_lock(fd)
    assert lock_file.exists()


def test_release_lock_cannot_unlink_successor_object_after_close(tmp_path):
    """Release must not delete a successor-created lock in the close/unlink gap."""

    from cryodaq.engine import _release_engine_lock

    lock_file = tmp_path / ".engine.lock"
    lock_file.write_text("111\n", encoding="ascii")

    def successor_acquires(_fd: int) -> None:
        lock_file.unlink(missing_ok=True)
        lock_file.write_text("222\n", encoding="ascii")

    with (
        patch("cryodaq.engine._LOCK_FILE", lock_file),
        patch("cryodaq.engine.os.close", side_effect=successor_acquires),
    ):
        _release_engine_lock(17)

    assert lock_file.read_text(encoding="ascii") == "222\n"


def test_force_mode_refuses_nonregular_lock_without_inspecting_or_killing_pid(tmp_path) -> None:
    """An untrusted lock pathname cannot become an arbitrary-process kill primitive."""

    from cryodaq.engine import _force_kill_existing

    lock_path = tmp_path / ".engine.lock"
    lock_path.mkdir()
    with (
        patch("cryodaq.engine._LOCK_FILE", lock_path),
        patch("psutil.Process") as process_lookup,
        patch("cryodaq.engine.os.kill", create=True) as raw_kill,
        pytest.raises(SystemExit),
    ):
        _force_kill_existing()

    process_lookup.assert_not_called()
    raw_kill.assert_not_called()


def test_force_mode_refuses_a_held_kernel_lock_without_process_inspection_or_kill(tmp_path) -> None:
    from cryodaq.engine import _acquire_engine_lock, _force_kill_existing, _release_engine_lock

    lock_file = tmp_path / ".engine.lock"
    with patch("cryodaq.engine._LOCK_FILE", lock_file):
        incumbent_fd = _acquire_engine_lock()
        try:
            with (
                patch("psutil.Process") as process_lookup,
                patch("cryodaq.engine.os.kill", create=True) as raw_kill,
                pytest.raises(SystemExit),
            ):
                _force_kill_existing()
        finally:
            _release_engine_lock(incumbent_fd)

    process_lookup.assert_not_called()
    raw_kill.assert_not_called()
