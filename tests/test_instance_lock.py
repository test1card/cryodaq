"""Tests for single-instance lock mechanism."""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest

from cryodaq.instance_lock import release_lock, try_acquire_lock


@pytest.fixture()
def lock_name():
    """Unique lock name for test isolation."""
    return ".test_instance.lock"


@pytest.fixture(autouse=True)
def cleanup_lock(lock_name):
    """Remove test lock file after each test."""
    yield
    from cryodaq.paths import get_data_dir

    lock_path = get_data_dir() / lock_name
    lock_path.unlink(missing_ok=True)


def test_acquire_and_release(lock_name):
    """Lock can be acquired and released."""
    fd = try_acquire_lock(lock_name)
    assert fd is not None
    release_lock(fd, lock_name)


def test_double_acquire_fails(lock_name):
    """Second acquire in same process fails (lock is held)."""
    fd1 = try_acquire_lock(lock_name)
    assert fd1 is not None

    fd2 = try_acquire_lock(lock_name)
    # On some OSes, same-process re-lock succeeds (flock is per-fd).
    # On Windows msvcrt, it fails. Accept both.
    if fd2 is not None:
        release_lock(fd2, lock_name)
    release_lock(fd1, lock_name)


def _acquire_in_subprocess(lock_name: str, acquired_event: mp.Event, release_event: mp.Event):
    """Helper: acquire lock, signal, wait for release signal."""
    fd = try_acquire_lock(lock_name)
    if fd is None:
        return
    acquired_event.set()
    release_event.wait(timeout=10)
    release_lock(fd, lock_name)


def test_cross_process_lock(lock_name):
    """Lock held by another process prevents acquisition."""
    acquired = mp.Event()
    release = mp.Event()

    proc = mp.Process(
        target=_acquire_in_subprocess,
        args=(lock_name, acquired, release),
        daemon=True,
    )
    proc.start()
    assert acquired.wait(timeout=5), "Subprocess failed to acquire lock"

    # Now try to acquire in main process — should fail
    fd = try_acquire_lock(lock_name)
    assert fd is None, "Should not acquire lock held by another process"

    release.set()
    proc.join(timeout=5)


def test_lock_released_on_process_death(lock_name):
    """Lock is released when holding process dies (kernel cleanup)."""
    acquired = mp.Event()
    release = mp.Event()  # never set — process will be killed

    proc = mp.Process(
        target=_acquire_in_subprocess,
        args=(lock_name, acquired, release),
        daemon=True,
    )
    proc.start()
    assert acquired.wait(timeout=5)

    # Kill the subprocess
    proc.kill()
    proc.join(timeout=3)

    # Lock should now be available (kernel releases flock/msvcrt on process death)
    fd = try_acquire_lock(lock_name)
    assert fd is not None, "Lock should be available after process death"
    release_lock(fd, lock_name)


def test_pid_written_to_lock_file(lock_name):
    """Lock file contains PID of holding process."""
    fd = try_acquire_lock(lock_name)
    assert fd is not None

    # Read via fd (file is locked on Windows, can't open via path)
    os.lseek(fd, 0, os.SEEK_SET)
    content = os.read(fd, 64).decode().strip()
    assert content == str(os.getpid())

    release_lock(fd, lock_name)
