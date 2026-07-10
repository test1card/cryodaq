"""Tests for single-instance lock mechanism."""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path

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


def test_double_acquire_same_process(lock_name):
    """Second acquire in same process fails: asserts the real observed behavior.

    Both POSIX (flock LOCK_EX|LOCK_NB) and Windows (msvcrt.locking) refuse a
    second exclusive lock from the same process on the same file — fd2 must be
    None. This is the contract the instance-lock mechanism relies on: a running
    process cannot accidentally acquire a second lock and believe it's the sole
    holder.

    Note: POSIX flock is nominally per-open-file-description, but macOS and
    modern Linux kernels enforce per-process semantics for LOCK_EX when the
    same file is locked by the same process via any fd. Empirically verified
    on Darwin 25.x. If a future kernel changes this, the test will catch it.
    """
    fd1 = try_acquire_lock(lock_name)
    assert fd1 is not None

    fd2 = try_acquire_lock(lock_name)
    try:
        assert fd2 is None, (
            "Same-process second acquire must fail — "
            "instance lock relies on this to prevent double-start"
        )
    finally:
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


@pytest.mark.skipif(os.name == "nt", reason="inode identity is a POSIX contract")
def test_persistent_release_keeps_same_inode(lock_name):
    """Report locks close without unlinking so contenders share one inode."""
    from cryodaq.paths import get_data_dir

    lock_path = get_data_dir() / lock_name
    fd = try_acquire_lock(lock_name)
    assert fd is not None
    first_inode = lock_path.stat().st_ino

    release_lock(fd, lock_name, unlink=False)

    fd = try_acquire_lock(lock_name)
    assert fd is not None
    try:
        assert lock_path.stat().st_ino == first_inode
    finally:
        release_lock(fd, lock_name, unlink=False)


def test_persistent_lock_is_reacquired_after_process_death(lock_name):
    """Kernel release, not PID text or unlinking, recovers a dead owner."""
    from cryodaq.paths import get_data_dir

    acquired = mp.Event()
    release = mp.Event()
    proc = mp.Process(
        target=_acquire_in_subprocess,
        args=(lock_name, acquired, release),
        daemon=True,
    )
    proc.start()
    assert acquired.wait(timeout=5)
    proc.kill()
    proc.join(timeout=3)

    lock_path = get_data_dir() / lock_name
    lock_path.write_text("999999\n", encoding="ascii")
    fd = try_acquire_lock(lock_name)
    assert fd is not None
    release_lock(fd, lock_name, unlink=False)
    assert lock_path.exists()


def test_lock_rejects_symlink_without_truncating_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("do-not-touch", encoding="utf-8")
    (tmp_path / ".unsafe.lock").symlink_to(target)

    assert try_acquire_lock(".unsafe.lock", lock_dir=tmp_path) is None
    assert target.read_text(encoding="utf-8") == "do-not-touch"


def test_lock_rejects_nonregular_and_hardlinked_paths(tmp_path: Path) -> None:
    (tmp_path / ".directory.lock").mkdir()
    assert try_acquire_lock(".directory.lock", lock_dir=tmp_path) is None

    target = tmp_path / "hardlink-target"
    target.write_text("do-not-touch", encoding="utf-8")
    try:
        os.link(target, tmp_path / ".hardlink.lock")
    except OSError as exc:
        pytest.skip(f"hard links are unavailable: {exc}")
    assert try_acquire_lock(".hardlink.lock", lock_dir=tmp_path) is None
    assert target.read_text(encoding="utf-8") == "do-not-touch"


def test_lock_rejects_path_replacement_during_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.instance_lock as module

    path = tmp_path / ".replaced.lock"
    path.write_text("old", encoding="ascii")
    real_open = module.os.open

    def replacing_open(raw_path: str, flags: int, mode: int = 0o777) -> int:
        fd = real_open(raw_path, flags, mode)
        path.unlink()
        path.write_text("attacker", encoding="ascii")
        return fd

    monkeypatch.setattr(module.os, "open", replacing_open)
    assert try_acquire_lock(path.name, lock_dir=tmp_path) is None
    assert path.read_text(encoding="ascii") == "attacker"


def test_lock_rejects_symlinked_parent_even_when_target_is_contained(tmp_path: Path) -> None:
    contained = tmp_path / "contained"
    contained.mkdir()
    (tmp_path / ".report-locks").symlink_to(contained, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        try_acquire_lock(".report-locks/periodic.lock", lock_dir=tmp_path)
    assert list(contained.iterdir()) == []


def test_release_never_unlinks_replacement_path(tmp_path: Path) -> None:
    path = tmp_path / ".release.lock"
    fd = try_acquire_lock(path.name, lock_dir=tmp_path)
    assert fd is not None
    path.unlink()
    path.write_text("attacker", encoding="ascii")

    release_lock(fd, path.name, lock_dir=tmp_path)

    assert path.read_text(encoding="ascii") == "attacker"
